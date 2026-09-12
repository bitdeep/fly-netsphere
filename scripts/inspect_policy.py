#!/usr/bin/env python3
import os
os.environ.setdefault("CUDA_VISIBLE_DEVICES", "-1")
os.environ.setdefault("MUJOCO_GL", "egl")
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")

from pathlib import Path
import numpy as np
import tensorflow as tf

ROOT = Path("/app") if Path("/app/data").exists() else Path(__file__).resolve().parents[1]
ckpt = str(ROOT / "data/policies/flight/variables/variables")
reader = tf.train.load_checkpoint(ckpt)
print("=== checkpoint variables ===")
for k, s in sorted(reader.get_variable_to_shape_map().items()):
    if k == "_CHECKPOINTABLE_OBJECT_GRAPH":
        continue
    print(f"{s!s:20s}  {k}")

from flybody.fly_envs import flight_imitation
env = flight_imitation(
    str(ROOT / "data/flight/flight-dataset_saccade-evasion_augmented.hdf5"),
    str(ROOT / "data/flight/wing_pattern_fmech.npy"),
    terminal_com_dist=float("inf"),
)
ts = env.reset()
spec = env.action_spec()
print("\n=== action spec ===")
print("shape", spec.shape, "min", spec.minimum, "max", spec.maximum)
print("\n=== observation keys (sorted) ===")
obs = ts.observation
total = 0
for k in sorted(obs.keys()):
    a = np.asarray(obs[k])
    n = int(np.prod(a.shape))
    total += n
    print(f"{n:6d}  {a.shape!s:16s}  {k}")
print("total obs dim", total)
print("n_traj steps", getattr(env.task, "_traj_timesteps", None))
print("time_limit", env._time_limit if hasattr(env, "_time_limit") else env.task._time_limit)
