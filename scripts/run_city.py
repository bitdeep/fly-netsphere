"""Run one continuous, recorded simulation. No automatic episode resets."""
import argparse
import hashlib
import importlib.metadata
import json
import time
from pathlib import Path

import mujoco
import numpy as np

from city_navigation import Navigator
from city_world import City
from flight_cuda import CudaFlight
from flight_mlp import FlightPolicy
from flight_runtime import ROOT, CONTROL_DT, PHYSICS_DT, make_environment, step_cpu


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=60)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--backend", choices=["cuda", "cpu"], default="cuda")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--disable-avoidance", action="store_true")
    parser.add_argument("--obstacle-shift", type=float, default=0)
    parser.add_argument("--allow-contact", action="store_true", help="Collision negative control only")
    parser.add_argument("--shutter-samples", type=int, default=8)
    parser.add_argument("--body-pitch", type=float, default=30,
                        help="Nose-up reference angle in degrees; acted on through the flight policy")
    args = parser.parse_args()
    if args.seconds <= 0:
        parser.error("--seconds must be positive")
    if not 1 <= args.shutter_samples <= 16:
        parser.error("--shutter-samples must be between 1 and 16")
    if not 20 <= args.body_pitch <= 55:
        parser.error("--body-pitch must be between 20 and 55; flatter commands can destabilize this policy")
    args.output.mkdir(parents=True, exist_ok=True)
    if (args.output / "states.npz").exists() or (args.output / "metrics.json").exists():
        raise FileExistsError("Choose a new output directory; previous evidence is preserved")
    city = City(obstacle_shift=args.obstacle_shift)
    nav = Navigator(city, seed=args.seed, avoid=not args.disable_avoidance, pitch=-args.body_pitch)
    env = make_environment(nav, args.seconds+.01, city, args.seed)
    ts = env.reset()
    policy = FlightPolicy(ROOT / "data/policies/flight")
    gpu = CudaFlight(env, policy, ts.observation) if args.backend == "cuda" else None
    source_hashes = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in [ROOT/"scripts"/name for name in (
                        "run_city.py", "flight_cuda.py", "flight_runtime.py", "flight_mlp.py",
                        "city_world.py", "city_navigation.py")]
                    + list((ROOT/"data/policies/flight/variables").glob("*"))}
    started = time.monotonic()
    nsteps = round(args.seconds / CONTROL_DT)
    frame_steps = np.rint(np.arange(round(args.seconds*30))/30/CONTROL_DT).astype(int)
    # 1/120-second exposure sampled from integrated physical states, no
    # interpolation or fabricated wing poses. Keep every sample for inspection.
    shutter_steps = np.rint((np.arange(len(frame_steps))[:, None]/30
        + np.arange(args.shutter_samples)[None]/args.shutter_samples/120)/CONTROL_DT).astype(int).ravel()
    frames, logs = [], []
    shutter_qpos = []
    next_shutter = 0
    next_frame, contacts = 0, 0
    failure = None
    try:
        for i in range(nsteps+1):
            if i % 50 == 0 or i == nsteps:
                qpos, qvel = gpu.state() if gpu else (env.physics.data.qpos.copy(), env.physics.data.qvel.copy())
                now = i*CONTROL_DT
                reference, _ = nav.sample(np.array([now]))
                error = float(np.linalg.norm(qpos[:3]-reference[0]))
                clearance = float(city.clearance(qpos[:3]))
                logs.append([now, *qpos[:3], clearance, error, np.linalg.norm(qvel[:3])])
                if not np.isfinite(qpos).all() or not np.isfinite(qvel).all() or qpos[2] < .2 or error > 2:
                    raise RuntimeError(f"Unstable physical flight at {now:.3f}s: error={error:.3f}, z={qpos[2]}")
                nav.update(now, qpos[:3])
                if gpu:
                    gpu.upload_reference(nav)
            if next_frame < len(frame_steps) and i == frame_steps[next_frame]:
                if i % 50:
                    qpos, qvel = gpu.state() if gpu else (env.physics.data.qpos.copy(), env.physics.data.qvel.copy())
                frames.append((i*CONTROL_DT, qpos.copy(), qvel.copy()))
                next_frame += 1
            if next_shutter < len(shutter_steps) and i == shutter_steps[next_shutter]:
                shutter_qpos.append(gpu.data.qpos.numpy()[0].copy() if gpu
                                    else env.physics.data.qpos.copy())
                next_shutter += 1
            if i % 5000 == 0:
                health = gpu.health() if gpu else dict(world_contacts=contacts, overflow=[0])
                print(json.dumps(dict(t=i*CONTROL_DT, root=qpos[:3].tolist(),
                    clearance=logs[-1][4], tracking_error=logs[-1][5],
                    goals=nav.goal_index, wall=time.monotonic()-started, **health)), flush=True)
                if any(health["overflow"]):
                    raise RuntimeError("GPU contact/constraint capacity overflow")
                if health["world_contacts"] and not args.allow_contact:
                    raise RuntimeError("Physical collision detected; take rejected")
            if i == nsteps:
                break
            if gpu:
                gpu.step()
            else:
                ts = step_cpu(env, policy, ts.observation)
                body = env.physics.model.geom_bodyid
                for c in env.physics.data.contact:
                    if c.dist <= 0 and (body[c.geom1] == 0) != (body[c.geom2] == 0):
                        contacts += 1
                if ts.last():
                    raise RuntimeError("Environment terminated before requested duration")
    except (Exception, KeyboardInterrupt) as exc:
        failure = f"{type(exc).__name__}: {exc}"
    finally:
        health = gpu.health() if gpu else dict(world_contacts=contacts, overflow=[0])
        samples = np.asarray(logs)
        metadata = dict(
            requested_seconds=args.seconds, simulated_seconds=i*CONTROL_DT,
            completed=failure is None and i == nsteps, failure=failure, backend=args.backend,
            device="cuda:0" if gpu else "cpu", seed=args.seed,
            obstacle_shift=args.obstacle_shift, avoidance=not args.disable_avoidance,
            body_pitch_command_deg=args.body_pitch,
            control_dt=CONTROL_DT, physics_dt=PHYSICS_DT, control_steps=i,
            physics_steps=i*4, episode_resets=0, fps=30, frames=len(frames),
            shutter_samples=args.shutter_samples, exposure_seconds=1/120,
            minimum_root_surface_clearance_cm=float(samples[:, 4].min()),
            maximum_tracking_error_cm=float(samples[:, 5].max()),
            altitude_range_cm=[float(samples[:, 3].min()), float(samples[:, 3].max())],
            speed_range_cm_s=[float(samples[:, 6].min()), float(samples[:, 6].max())],
            distance_travelled_cm=float(np.linalg.norm(np.diff(samples[:, 1:4], axis=0), axis=1).sum()),
            goals_reached=nav.goal_index, avoidance_updates=nav.avoidance_updates,
            policy_cuda_max_error=gpu.policy_error if gpu else None,
            source_sha256=source_hashes,
            versions={name: importlib.metadata.version(name)
                      for name in ("numpy", "mujoco", "mujoco-warp", "warp-lang", "dm_control")},
            wall_seconds=time.monotonic()-started, **health)
        np.savez_compressed(args.output/"states.npz",
            time=np.array([f[0] for f in frames]), qpos=np.array([f[1] for f in frames]),
            qvel=np.array([f[2] for f in frames]), telemetry=samples,
            navigation=np.asarray(nav.history), shutter_qpos=np.asarray(shutter_qpos),
            shutter_time=shutter_steps[:len(shutter_qpos)]*CONTROL_DT)
        metadata["states_sha256"] = hashlib.sha256((args.output/"states.npz").read_bytes()).hexdigest()
        mujoco.mj_saveModel(env.physics.model.ptr, str(args.output/"model.mjb"))
        metadata["model_sha256"] = hashlib.sha256((args.output/"model.mjb").read_bytes()).hexdigest()
        (args.output/"metrics.json").write_text(json.dumps(metadata, indent=2)+"\n")
        (args.output/"model.xml").write_text(env.physics.model.to_xml_string() if hasattr(env.physics.model, "to_xml_string") else env.task.root_entity.mjcf_model.to_xml_string())
        env.close()
        print(json.dumps(metadata), flush=True)
    if failure:
        raise RuntimeError(failure)


if __name__ == "__main__":
    main()
