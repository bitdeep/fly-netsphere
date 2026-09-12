"""Compare the same force controls in CPU MuJoCo and CUDA MuJoCo Warp."""
import json
import time
import numpy as np
import warp as wp
import mujoco_warp as mjw

from flight_mlp import FlightPolicy
from flight_runtime import ROOT, CircleReference, make_environment, step_cpu


def main():
    wp.init()
    if not wp.is_cuda_available():
        raise RuntimeError("CUDA GPU required")
    wp.set_device("cuda:0")
    env = make_environment(CircleReference(yaw_rate=1), 1.0)
    ts = env.reset()
    policy = FlightPolicy(ROOT / "data/policies/flight")
    mjm, mjd = env.physics.model.ptr, env.physics.data.ptr
    print("copying model", mjm.nq, mjm.nv, mjm.ngeom, flush=True)
    model = mjw.put_model(mjm)
    model.block_dim.convex_ccd = 256
    data = mjw.put_data(mjm, mjd, nconmax=128, njmax=256)
    print("fluid", model.has_fluid, "ellipsoid bodies", model.body_fluid_ellipsoid_adr.numpy().tolist(), flush=True)
    # Compile shape-specialized collision kernels before capturing a CUDA graph.
    mjw.step2(model, data)
    mjw.step1(model, data)
    wp.synchronize()
    data = mjw.put_data(mjm, mjd, nconmax=128, njmax=256)
    with wp.ScopedCapture() as capture:
        for _ in range(4):
            mjw.step2(model, data)
            mjw.step1(model, data)
    print("graph captured", flush=True)
    started = time.monotonic()
    errors = []
    for i in range(100):
        ts = step_cpu(env, policy, ts.observation)
        wp.copy(data.ctrl, wp.array(mjd.ctrl[None].astype(np.float32), dtype=wp.float32))
        wp.capture_launch(capture.graph)
        gpu_qpos = data.qpos.numpy()[0]
        errors.append(float(np.max(np.abs(mjd.qpos[:7] - gpu_qpos[:7]))))
    result = dict(device=str(wp.get_device()), sim_seconds=env.physics.time(),
                  wall_seconds=time.monotonic()-started, max_root_qpos_error=max(errors),
                  cpu_root=mjd.qpos[:7].tolist(), gpu_root=gpu_qpos[:7].tolist(),
                  overflow=data.overflow.numpy().tolist())
    print(json.dumps(result), flush=True)
    env.close()


if __name__ == "__main__":
    main()
