#!/usr/bin/env python3
"""Roll out the trained flight policy and composite the fly into The City."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import numpy as np
from PIL import Image

ROOT = Path("/app") if Path("/app/data").exists() else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "flybody"))

from flight_mlp import FlightPolicy  # noqa: E402

FLIGHT_HDF5 = ROOT / "data/flight/flight-dataset_saccade-evasion_augmented.hdf5"
WING_NPY = ROOT / "data/flight/wing_pattern_fmech.npy"
POLICY_DIR = ROOT / "data/policies/flight"
CITY = ROOT / "out/blame/corridor.jpg"
OUT = ROOT / "out"
CHROMA = (0, 255, 0)


def f32(tree):
    if isinstance(tree, dict):
        return {k: f32(v) for k, v in tree.items()}
    return np.asarray(tree, dtype=np.float32)


def canonical2real(action, spec, clip=True):
    action = np.asarray(action, dtype=np.float32)
    if clip:
        action = np.clip(action, -1.0, 1.0)
    scale = spec.maximum - spec.minimum
    return spec.minimum + 0.5 * (action + 1.0) * scale


class WrappedEnv:
    def __init__(self, env):
        self.env = env
        self._spec = env.action_spec()

    def reset(self):
        ts = self.env.reset()
        return ts._replace(observation=f32(ts.observation))

    def step(self, action):
        ts = self.env.step(canonical2real(action, self._spec))
        return ts._replace(observation=f32(ts.observation))

    def __getattr__(self, name):
        return getattr(self.env, name)


def make_flight_env(time_limit: float, chroma: bool):
    from dm_control import composer
    from dm_control.locomotion.arenas import floors
    from flybody.fruitfly import fruitfly
    from flybody.tasks.flight_imitation import FlightImitationWBPG
    from flybody.tasks.pattern_generators import WingBeatPatternGenerator
    from flybody.tasks.trajectory_loaders import HDF5FlightTrajectoryLoader

    arena = floors.Floor()
    if chroma:
        for tex in arena.mjcf_model.find_all("texture"):
            tname = (tex.name or "") + " " + str(tex.type)
            if "sky" in tname.lower() or str(tex.type) == "skybox":
                tex.rgb1 = [0.0, 1.0, 0.0]
                tex.rgb2 = [0.0, 1.0, 0.0]
                try:
                    tex.builtin = "gradient"
                    tex.mark = "none"
                except Exception:
                    pass
        for geom in arena.mjcf_model.find_all("geom"):
            gname = geom.name or ""
            if "ground" in gname or "floor" in gname or geom.type == "plane":
                geom.rgba = (0.0, 1.0, 0.0, 1.0)
                if geom.size is not None:
                    geom.size[0] = 80
                    geom.size[1] = 80
    wbpg = WingBeatPatternGenerator(base_pattern_path=str(WING_NPY))
    traj = HDF5FlightTrajectoryLoader(
        path=str(FLIGHT_HDF5),
        randomize_start_step=False,
        random_state=np.random.RandomState(0),
    )
    task = FlightImitationWBPG(
        walker=fruitfly.FruitFly,
        arena=arena,
        wbpg=wbpg,
        traj_generator=traj,
        terminal_com_dist=float("inf"),
        initialize_qvel=True,
        disable_legs=True,
        time_limit=time_limit,
        joint_filter=0.0,
        future_steps=5,
        trajectory_sites=False,
    )
    return composer.Environment(
        time_limit=time_limit,
        task=task,
        random_state=np.random.RandomState(0),
        strip_singleton_obs_buffer_dim=True,
    )


def hide_decorations(physics):
    model = physics.model
    for i in range(model.ngeom):
        name = model.id2name(i, "geom") or ""
        if not name.startswith("walker/"):
            physics.model.geom_rgba[i] = (0.0, 0.0, 0.0, 0.0)
    for i in range(model.nsite):
        physics.model.site_rgba[i, 3] = 0.0


def resolve_camera(physics, wanted) -> int:
    if isinstance(wanted, int):
        return wanted
    for i in range(physics.model.ncam):
        name = physics.model.id2name(i, "camera")
        if name == wanted or name.endswith("/" + wanted):
            return i
    raise KeyError(wanted)


def thorax_z(physics) -> float:
    try:
        return float(physics.named.data.xpos["walker/thorax"][2])
    except Exception:
        return float(physics.data.qpos[2])


def render_frame(physics, cam_id, width, height):
    kwargs = dict(camera_id=cam_id, width=width, height=height)
    try:
        return physics.render(
            render_flag_overrides={"skybox": False, "shadow": False}, **kwargs
        )
    except TypeError:
        return physics.render(**kwargs)


def chroma_mask(rgb: np.ndarray) -> np.ndarray:
    """Keep the fly; drop black void, green floor, and leftover grid."""
    r = rgb[..., 0].astype(np.int16)
    g = rgb[..., 1].astype(np.int16)
    b = rgb[..., 2].astype(np.int16)
    green = (g > r + 18) & (g > b + 18)
    black = (r < 22) & (g < 22) & (b < 22)
    keep = ~(green | black)
    # dilate so thin wing veins survive
    k = keep.astype(np.uint8)
    dil = k.copy()
    dil[1:] |= k[:-1]
    dil[:-1] |= k[1:]
    dil[:, 1:] |= k[:, :-1]
    dil[:, :-1] |= k[:, 1:]
    return dil.astype(np.float32)


def composite(fg: np.ndarray, bg: np.ndarray, mask: np.ndarray) -> np.ndarray:
    if bg.shape[:2] != fg.shape[:2]:
        bg = np.asarray(Image.fromarray(bg).resize((fg.shape[1], fg.shape[0]), Image.BICUBIC))
    m = mask[..., None]
    out = fg.astype(np.float32) * m + bg.astype(np.float32) * (1.0 - m)
    return np.clip(out, 0, 255).astype(np.uint8)


def grade_fly(rgb: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Keep the anatomical fly, slightly crush it into the ink city."""
    x = rgb.astype(np.float32)
    gray = x.mean(axis=-1, keepdims=True)
    mixed = 0.45 * x + 0.55 * gray
    mixed[..., 0] = np.maximum(mixed[..., 0], x[..., 0] * 0.85)  # keep red eyes
    out = rgb.copy()
    m = mask[..., None] > 0.5
    out = np.where(m, np.clip(mixed, 0, 255).astype(np.uint8), rgb)
    return out


def kenburns_frame(image: Image.Image, t: float, duration: float, w: int, h: int) -> np.ndarray:
    z = 1.0 + 0.22 * (t / max(duration, 1e-6))
    iw, ih = image.size
    cw, ch = iw / z, ih / z
    left = (iw - cw) / 2
    top = (ih - ch) / 2 - 0.04 * ih * (t / max(duration, 1e-6))
    crop = image.crop((left, top, left + cw, top + ch)).resize((w, h), Image.BICUBIC)
    return np.asarray(crop.convert("RGB"))


def write_mp4(path: Path, frames, fps: int):
    import imageio.v2 as imageio

    path.parent.mkdir(parents=True, exist_ok=True)
    writer = imageio.get_writer(
        str(path), fps=fps, codec="libx264", quality=8, pixelformat="yuv420p",
        macro_block_size=None,
    )
    for frame in frames:
        if frame.shape[0] % 2:
            frame = frame[:-1]
        if frame.shape[1] % 2:
            frame = frame[:, :-1]
        writer.append_data(frame)
    writer.close()
    print(f"wrote {path} ({path.stat().st_size / 1e6:.1f} MB, {len(frames)} frames)", flush=True)


def rollout(args):
    env = WrappedEnv(make_flight_env(time_limit=0.6, chroma=True))
    policy = FlightPolicy(POLICY_DIR)
    cam_names = [c.strip() for c in args.camera.split(",")]
    cam_ids = [resolve_camera(env.physics, c) for c in cam_names]
    print(f"cameras {list(zip(cam_names, cam_ids))}", flush=True)
    city = Image.open(CITY).convert("RGB")
    n_traj = int(env.task._traj_generator.num_trajectories)
    indices = list(range(min(args.episodes, n_traj)))
    print(f"rolling out trajectories {indices}", flush=True)

    frames = {name: [] for name in cam_names}
    raw_frames = {name: [] for name in cam_names}
    zs = []
    total_steps = 0
    duration_hint = max(args.episodes * 0.5, 10.0)
    n_out = 0

    for ep, traj_idx in enumerate(indices):
        env.task.set_next_trajectory_index(traj_idx)
        ts = env.reset()
        hide_decorations(env.physics)
        step = 0
        while ts.step_type != 2 and step < 4000:
            z = thorax_z(env.physics)
            zs.append(z)
            if step % args.skip == 0:
                t = n_out / 30.0
                bg = kenburns_frame(city, t, duration_hint, args.width, args.height)
                for name, cam_id in zip(cam_names, cam_ids):
                    rgb = render_frame(env.physics, cam_id, args.width, args.height)
                    raw_frames[name].append(rgb)
                    mask = chroma_mask(rgb)
                    fly = grade_fly(rgb, mask)
                    frames[name].append(composite(fly, bg, mask))
                n_out += 1
            action = policy(ts.observation)
            ts = env.step(action)
            step += 1
            total_steps += 1
            if step % 200 == 0:
                print(
                    f"  ep {ep} traj {traj_idx} step {step} z={z:.3f}",
                    flush=True,
                )
                hide_decorations(env.physics)
        print(f"  ep {ep} ended after {step} steps z_last={zs[-1]:.3f}", flush=True)

    zs = np.asarray(zs)
    print(
        f"total {total_steps} steps / {n_out} frames  "
        f"z min/mean/max {zs.min():.3f}/{zs.mean():.3f}/{zs.max():.3f}",
        flush=True,
    )
    return raw_frames, frames, zs, cam_names


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--episodes", type=int, default=4)
    p.add_argument("--width", type=int, default=1280)
    p.add_argument("--height", type=int, default=720)
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--skip", type=int, default=5)
    p.add_argument("--camera", default="walker/hero,walker/track2")
    return p.parse_args()


def main():
    args = parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    raw, composited, zs, cam_names = rollout(args)
    np.save(OUT / "flight_z.npy", zs)
    for name in cam_names:
        slug = name.replace("/", "_")
        write_mp4(OUT / f"fly_raw_{slug}.mp4", raw[name], args.fps)
        write_mp4(OUT / f"fly_in_the_city_{slug}.mp4", composited[name], args.fps)
        if composited[name]:
            Image.fromarray(composited[name][len(composited[name]) // 2]).save(
                OUT / f"fly_in_the_city_{slug}.png"
            )
            Image.fromarray(raw[name][0]).save(OUT / f"fly_raw_{slug}.png")
    # default aliases for the first camera
    first = cam_names[0]
    write_mp4(OUT / "fly_in_the_city.mp4", composited[first], args.fps)
    write_mp4(OUT / "fly_raw.mp4", raw[first], args.fps)


if __name__ == "__main__":
    main()
