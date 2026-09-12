import argparse
import json
import time
import numpy as np
from flight_runtime import ROOT, CircleReference, make_environment, CONTROL_DT
from flight_mlp import FlightPolicy
from flight_cuda import CudaFlight


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--seconds", type=float, default=2)
    p.add_argument("--yaw-rate", type=float, default=4)
    p.add_argument("--pitch", type=float, default=-47.5)
    p.add_argument("--speed", type=float, default=20)
    args = p.parse_args()
    ref = CircleReference(yaw_rate=args.yaw_rate, speed=args.speed, pitch=args.pitch)
    env = make_environment(ref, args.seconds)
    ts = env.reset()
    gpu = CudaFlight(env, FlightPolicy(ROOT / "data/policies/flight"), ts.observation)
    start = time.monotonic()
    errors = []
    inclinations = []
    for i in range(round(args.seconds / CONTROL_DT)):
        if i % gpu.block == 0:
            gpu.upload_reference(ref)
        gpu.step()
        if (i + 1) % gpu.block == 0:
            qpos, qvel = gpu.state()
            r, _ = ref.sample(np.array([gpu.steps * CONTROL_DT]))
            error = float(np.linalg.norm(qpos[:3] - r[0]))
            errors.append(error)
            w, x, y, z = qpos[3:7]
            inclinations.append(float(np.rad2deg(np.arcsin(np.clip(2*(x*z-w*y), -1, 1)))))
            if not np.isfinite(qpos).all() or qpos[2] < .2 or error > 2:
                raise RuntimeError(f"Flight unstable t={gpu.steps*CONTROL_DT} qpos={qpos[:7]} error={error}")
        if (i + 1) % 2500 == 0:
            print(json.dumps(dict(t=gpu.steps*CONTROL_DT, root=qpos[:3].tolist(),
                                  error=errors[-1], wall=time.monotonic()-start)), flush=True)
    print(json.dumps(dict(sim_seconds=gpu.steps*CONTROL_DT, wall=time.monotonic()-start,
                          requested_pitch=args.pitch, speed=args.speed,
                          observed_inclination_percentiles=np.percentile(inclinations, [0, 50, 100]).tolist(),
                          max_error=max(errors), **gpu.health())), flush=True)
    env.close()


if __name__ == "__main__":
    main()
