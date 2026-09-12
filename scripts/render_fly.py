#!/usr/bin/env python3
"""Roll out DeepMind/Janelia flybody policies and write MP4s.

Runs inside the project Docker image (EGL render, TensorFlow CPU).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
FLIGHT_HDF5 = ROOT / "data/flight/flight-dataset_saccade-evasion_augmented.hdf5"
WING_NPY = ROOT / "data/flight/wing_pattern_fmech.npy"
POLICY_DIR = ROOT / "data/policies"
OUT = ROOT / "out"


def f32(tree):
    if isinstance(tree, dict):
        return {k: f32(v) for k, v in tree.items()}
    return np.asarray(tree, dtype=np.float32)


def canonical2real(action, spec, clip=True):
    action = np.asarray(action, dtype=np.float32)
    if clip:
        action = np.clip(action, -1.0, 1.0)
    scale = spec.maximum - spec.minimum
    offset = spec.minimum
    return offset + 0.5 * (action + 1.0) * scale


class WrappedEnv:
    """float32 obs + canonical [-1, 1] actions, matching the Acme wrappers
    the policies were trained with."""

    def __init__(self, env):
        self.env = env
        self._spec = env.action_spec()

    def reset(self):
        ts = self.env.reset()
        return ts._replace(observation=f32(ts.observation))

    def step(self, action):
        real = canonical2real(action, self._spec, clip=True)
        ts = self.env.step(real)
        return ts._replace(observation=f32(ts.observation))

    def __getattr__(self, name):
        return getattr(self.env, name)


class SavedPolicy:
    def __init__(self, path: Path):
        import tensorflow as tf

        self._tf = tf
        print(f"loading SavedModel {path}", flush=True)
        self._model = tf.saved_model.load(str(path))
        self._call = self._pick_call()

    def _pick_call(self):
        model = self._model
        if callable(model):
            return model
        for name in ("action", "__call__", "step"):
            fn = getattr(model, name, None)
            if callable(fn):
                return fn
        sigs = getattr(model, "signatures", {})
        if "serving_default" in sigs:
            return sigs["serving_default"]
        if sigs:
            return next(iter(sigs.values()))
        raise RuntimeError("SavedModel has no callable signature")

    def _batch(self, observation):
        tf = self._tf
        return tf.nest.map_structure(
            lambda x: tf.expand_dims(tf.convert_to_tensor(x, dtype=tf.float32), 0),
            observation,
        )

    def __call__(self, observation) -> np.ndarray:
        batched = self._batch(observation)
        out = self._call(batched)
        if hasattr(out, "mean"):
            tensor = out.mean()
        elif isinstance(out, dict):
            tensor = out.get("mean") or out.get("action") or next(iter(out.values()))
        else:
            tensor = out
        if hasattr(tensor, "numpy"):
            arr = tensor.numpy()
        else:
            arr = np.asarray(tensor)
        if arr.ndim > 1:
            arr = arr[0]
        return arr.astype(np.float32)


def camera_table(physics):
    rows = []
    for i in range(physics.model.ncam):
        name = physics.model.id2name(i, "camera")
        rows.append((i, name))
    return rows


def resolve_camera(physics, wanted: str | int) -> int:
    if isinstance(wanted, int):
        return wanted
    for i, name in camera_table(physics):
        if name == wanted or name.endswith("/" + wanted) or wanted in name:
            return i
    raise KeyError(f"camera {wanted!r} not in {camera_table(physics)}")


def label_frame(pixels: np.ndarray, text: str) -> np.ndarray:
    img = Image.fromarray(pixels)
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22
        )
    except OSError:
        font = ImageFont.load_default()
    pad = 10
    draw.rectangle((0, 0, img.width, 36), fill=(8, 10, 16))
    draw.text((pad, 6), text, fill=(240, 240, 235), font=font)
    return np.asarray(img)


def eye_strip(observation, height=80) -> np.ndarray:
    left = observation["walker/left_eye"].mean(axis=-1)
    right = observation["walker/right_eye"].mean(axis=-1)
    eyes = np.concatenate((left, right), axis=1)
    eyes = np.clip(eyes, 0, 255).astype(np.uint8)
    img = Image.fromarray(eyes, mode="L").convert("RGB")
    img = img.resize((img.width * 4, height), Image.NEAREST)
    return np.asarray(img)


def overlay_eyes(scene: np.ndarray, observation) -> np.ndarray:
    strip = eye_strip(observation, height=96)
    out = scene.copy()
    h, w = strip.shape[:2]
    w = min(w, out.shape[1])
    out[8 : 8 + h, 8 : 8 + w] = strip[:, :w]
    return out


def write_mp4(path: Path, frames, fps: int):
    import imageio.v2 as imageio

    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"writing {path} ({len(frames)} frames @ {fps} fps)", flush=True)
    writer = imageio.get_writer(
        str(path),
        fps=fps,
        codec="libx264",
        quality=8,
        pixelformat="yuv420p",
        macro_block_size=None,
    )
    for frame in frames:
        if frame.shape[0] % 2:
            frame = frame[:-1]
        if frame.shape[1] % 2:
            frame = frame[:, :-1]
        writer.append_data(frame)
    writer.close()
    print(f"wrote {path} ({path.stat().st_size / 1e6:.1f} MB)", flush=True)


def rollout(
    env,
    policy,
    camera: str | int,
    width: int,
    height: int,
    skip: int,
    caption: str,
    max_steps: int,
    eyes: bool = False,
):
    ts = env.reset()
    cam_id = resolve_camera(env.physics, camera)
    print("cameras:", camera_table(env.physics), flush=True)
    print(f"using camera_id={cam_id}", flush=True)
    frames = []
    step = 0
    while ts.step_type != 2 and step < max_steps:
        if step % skip == 0:
            pixels = env.physics.render(
                camera_id=cam_id, width=width, height=height
            )
            if eyes and "walker/left_eye" in ts.observation:
                pixels = overlay_eyes(pixels, ts.observation)
            frames.append(label_frame(pixels, caption))
        action = policy(ts.observation)
        ts = env.step(action)
        step += 1
        if step % 250 == 0:
            print(f"  step {step}", flush=True)
    print(f"episode ended after {step} steps, {len(frames)} frames", flush=True)
    return frames


def still(env, camera, width, height, path: Path, caption: str):
    env.reset()
    cam_id = resolve_camera(env.physics, camera)
    pixels = label_frame(
        env.physics.render(camera_id=cam_id, width=width, height=height),
        caption,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(pixels).save(path)
    print(f"still {path}", flush=True)


def render_flight(args):
    from flybody.fly_envs import flight_imitation

    env = WrappedEnv(
        flight_imitation(
            str(FLIGHT_HDF5),
            str(WING_NPY),
            terminal_com_dist=float("inf"),
        )
    )
    still(
        env,
        args.flight_camera,
        args.width,
        args.height,
        OUT / "flight_still.png",
        "flybody  ·  flight imitation  ·  DeepMind + Janelia",
    )
    if args.policy == "wpg":
        print("WPG-only: zero residual on top of the wing-beat generator", flush=True)
        policy = lambda _obs: np.zeros(env._spec.shape, dtype=np.float32)
    else:
        policy = SavedPolicy(POLICY_DIR / "flight")
    frames = rollout(
        env,
        policy,
        camera=args.flight_camera,
        width=args.width,
        height=args.height,
        skip=args.skip,
        caption="virtual Drosophila  ·  trained flight policy tracking a real trajectory",
        max_steps=args.max_steps,
    )
    write_mp4(OUT / "fly_flight.mp4", frames, args.fps)
    return OUT / "fly_flight.mp4"


def render_bumps(args):
    from flybody.fly_envs import vision_guided_flight

    env = WrappedEnv(
        vision_guided_flight(str(WING_NPY), bumps_or_trench="bumps")
    )
    still(
        env,
        args.bumps_camera,
        args.width,
        args.height,
        OUT / "bumps_still.png",
        "flybody  ·  vision-guided flight over terrain",
    )
    policy = SavedPolicy(POLICY_DIR / "vision-bumps")
    frames = rollout(
        env,
        policy,
        camera=args.bumps_camera,
        width=args.width,
        height=args.height,
        skip=max(1, args.skip // 2),
        caption="virtual Drosophila  ·  flying by what it sees",
        max_steps=args.max_steps,
        eyes=True,
    )
    write_mp4(OUT / "fly_vision_flight.mp4", frames, args.fps)
    return OUT / "fly_vision_flight.mp4"


def render_trench(args):
    from flybody.fly_envs import vision_guided_flight

    env = WrappedEnv(
        vision_guided_flight(str(WING_NPY), bumps_or_trench="trench")
    )
    thorax = env.env.task.root_entity.mjcf_model.find("body", "walker/thorax")
    thorax.add(
        "camera",
        name="rear",
        mode="trackcom",
        pos=(-1.566, 0.037, -0.021),
        xyaxes=(-0.014, -1, 0, -0.012, 0, 1),
    )
    still(
        env,
        "walker/rear",
        args.width,
        args.height,
        OUT / "trench_still.png",
        "flybody  ·  vision-guided flight through a trench",
    )
    policy = SavedPolicy(POLICY_DIR / "vision-trench")
    frames = rollout(
        env,
        policy,
        camera="walker/rear",
        width=args.width,
        height=args.height,
        skip=max(1, args.skip // 2),
        caption="virtual Drosophila  ·  unauthorized organism in the corridor",
        max_steps=args.max_steps,
        eyes=True,
    )
    write_mp4(OUT / "fly_trench.mp4", frames, args.fps)
    return OUT / "fly_trench.mp4"


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument(
        "--task",
        choices=("flight", "bumps", "trench", "all"),
        default="all",
    )
    p.add_argument("--width", type=int, default=1280)
    p.add_argument("--height", type=int, default=720)
    p.add_argument("--fps", type=int, default=60)
    p.add_argument("--skip", type=int, default=4, help="control steps per frame")
    p.add_argument("--max-steps", type=int, default=4000)
    p.add_argument("--flight-camera", default="1")
    p.add_argument("--bumps-camera", default="1")
    p.add_argument(
        "--policy",
        choices=("saved", "wpg"),
        default="saved",
        help="saved: trained TF policy. wpg: wing-beat generator only (zeros).",
    )
    args = p.parse_args()
    if args.flight_camera.isdigit():
        args.flight_camera = int(args.flight_camera)
    if args.bumps_camera.isdigit():
        args.bumps_camera = int(args.bumps_camera)
    return args


def main():
    args = parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    missing = [p for p in (FLIGHT_HDF5, WING_NPY, POLICY_DIR / "flight") if not p.exists()]
    if missing:
        sys.exit(f"missing data: {missing}")
    written = []
    if args.task in ("flight", "all"):
        written.append(render_flight(args))
    if args.task in ("bumps", "all"):
        written.append(render_bumps(args))
    if args.task in ("trench", "all"):
        written.append(render_trench(args))
    print("done:", " ".join(str(p) for p in written), flush=True)


if __name__ == "__main__":
    main()
