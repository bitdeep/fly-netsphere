"""Short continuous flight tests before the city or a long recording."""
import argparse
import json
import time
import numpy as np

from flight_mlp import FlightPolicy
from flight_runtime import ROOT, CircleReference, make_environment, step_cpu


def run(args):
    reference = CircleReference(args.speed, args.yaw_rate, args.height)
    env = make_environment(reference, args.seconds, seed=args.seed)
    ts = env.reset()
    policy = FlightPolicy(ROOT / "data/policies/flight")
    print("observations", {k: list(v.shape) for k, v in ts.observation.items()}, flush=True)
    print("model", env.physics.model.nq, env.physics.model.nv, env.physics.model.nu, flush=True)
    started = time.monotonic()
    errors, heights = [], []
    for step in range(round(args.seconds / 0.0002)):
        ts = step_cpu(env, policy, ts.observation)
        if step % 100 == 0:
            pos = env.physics.named.data.xpos["walker/thorax"].copy()
            target, _ = reference.sample(np.array([env.physics.time()]))
            errors.append(float(np.linalg.norm(pos - target[0])))
            heights.append(float(pos[2]))
        if (step + 1) % 2500 == 0 or ts.last():
            print(json.dumps(dict(t=env.physics.time(), pos=pos.tolist(),
                                  error=errors[-1], wall=time.monotonic()-started)), flush=True)
        if ts.last():
            break
    print(json.dumps(dict(sim_seconds=env.physics.time(), wall_seconds=time.monotonic()-started,
                          height_min=min(heights), height_max=max(heights),
                          error_max=max(errors), error_mean=float(np.mean(errors)))), flush=True)
    env.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--seconds", type=float, default=2.0)
    parser.add_argument("--speed", type=float, default=20.0)
    parser.add_argument("--yaw-rate", type=float, default=0.0)
    parser.add_argument("--height", type=float, default=3.0)
    parser.add_argument("--seed", type=int, default=0)
    run(parser.parse_args())
