#!/usr/bin/env python3
"""Try a few action mappings on the flight MLP and print altitude."""
from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

import numpy as np

ROOT = Path("/app") if Path("/app/data").exists() else Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "flybody"))

from flybody.fly_envs import flight_imitation
from flight_mlp import FlightPolicy, concat_obs


def thorax_z(physics):
    return float(physics.named.data.xpos["walker/thorax"][2])


def canonical2real(action, spec):
    action = np.clip(np.asarray(action, np.float32), -1.0, 1.0)
    return spec.minimum + 0.5 * (action + 1.0) * (spec.maximum - spec.minimum)


def run(name, mapper, n=800):
    env = flight_imitation(
        str(ROOT / "data/flight/flight-dataset_saccade-evasion_augmented.hdf5"),
        str(ROOT / "data/flight/wing_pattern_fmech.npy"),
        terminal_com_dist=float("inf"),
        randomize_start_step=False,
        random_state=np.random.RandomState(0),
    )
    policy = FlightPolicy(ROOT / "data/policies/flight")
    spec = env.action_spec()
    ts = env.reset()
    x = concat_obs(ts.observation)
    print(f"\n=== {name}  obs {x.shape} action_spec {spec.shape} ===", flush=True)
    zs = []
    for i in range(n):
        if ts.step_type == 2:
            break
        zs.append(thorax_z(env.physics))
        ts = env.step(mapper(policy(ts.observation), spec))
        if i % 100 == 0:
            try:
                gz = float(env.physics.named.data.xpos["ghost/thorax"][2])
            except Exception:
                gz = float("nan")
            print(f"  t={i:4d} z={zs[-1]:.3f} ghost_z={gz:.3f}", flush=True)
    zs = np.array(zs)
    print(
        f"  ended {len(zs)} steps  z min/mean/last {zs.min():.3f}/{zs.mean():.3f}/{zs[-1]:.3f}",
        flush=True,
    )


def main():
    run("canonical", lambda a, spec: canonical2real(a, spec), n=1500)


if __name__ == "__main__":
    main()
