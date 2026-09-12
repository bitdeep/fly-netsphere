"""CUDA controller + physical integration, with no pose writes after reset.

The host supplies rolling reference commands. The learned low-level policy,
wingbeat generator, joint feedback and ellipsoid-fluid physics run on CUDA.
"""
import numpy as np
import mujoco
import mujoco_warp as mjw
import warp as wp

from flight_mlp import concat_obs
from flight_runtime import CONTROL_DT, PHYSICS_DT


@wp.kernel
def linear(x: wp.array[float], w: wp.array2d[float], b: wp.array[float],
           y: wp.array[float], activation: int):
    j = wp.tid()
    v = b[j]
    for i in range(w.shape[0]):
        v += x[i] * w[i, j]
    if activation == 1:
        v = wp.where(v > 0.0, v, wp.exp(wp.clamp(v, -80.0, 0.0)) - 1.0)
    if activation == 2:
        v = wp.clamp(v, -1.0, 1.0)
    y[j] = v


@wp.kernel
def norm_tanh(x: wp.array[float], scale: wp.array[float],
              offset: wp.array[float], y: wp.array[float]):
    j = wp.tid()
    mean = float(0.0)
    for i in range(256):
        mean += x[i] / 256.0
    var = float(0.0)
    for i in range(256):
        var += (x[i] - mean) * (x[i] - mean) / 256.0
    y[j] = wp.tanh((x[j] - mean) / wp.sqrt(var + 0.00001) * scale[j] + offset[j])


@wp.kernel
def wing_control(action: wp.array[float], qpos: wp.array2d[float],
                 wing_qadr: wp.array[int], ranges: wp.array2d[float],
                 freqs: wp.array[float], lengths: wp.array[int],
                 phases: wp.array2d[float], patterns: wp.array3d[float],
                 wpg_int: wp.array[int], wpg_freq: wp.array[float],
                 rate: float, ctrl: wp.array2d[float]):
    idx = wpg_int[0]
    step = (wpg_int[1] + 1) % lengths[idx]
    freq = wpg_freq[0] * rate + (218.0 * (1.0 + 0.05 * action[11])) * (1.0 - rate)
    best = int(0)
    error = float(100000.0)
    for i in range(freqs.shape[0]):
        d = wp.abs(freq - freqs[i])
        if d < error:
            error = d
            best = i
    if best != idx:
        phase = phases[idx, step] - wp.floor(phases[idx, step])
        nearest = int(0)
        error = float(100000.0)
        for i in range(lengths[best]):
            d = wp.abs(phase - (phases[best, i] - wp.floor(phases[best, i])))
            if d < error:
                error = d
                nearest = i
        step = nearest
        idx = best
    for j in range(11):
        value = ranges[j, 0] + (action[j] + 1.0) * 0.5 * (ranges[j, 1] - ranges[j, 0])
        if j >= 3 and j < 9:
            value += patterns[idx, step, j - 3] - qpos[0, wing_qadr[j - 3]]
        ctrl[0, j] = value
    wpg_int[0] = idx
    wpg_int[1] = step
    wpg_freq[0] = freq


@wp.kernel
def clear_sensors(sums: wp.array[float]):
    sums[wp.tid()] = 0.0


@wp.kernel
def accumulate_sensors(sensor: wp.array2d[float], sums: wp.array[float]):
    i = wp.tid()
    sums[i] += sensor[0, i] * 0.25


@wp.kernel
def gather_observation(qpos: wp.array2d[float], qvel: wp.array2d[float],
                       xmat: wp.array2d[wp.mat33], root_body: int,
                       qadr: wp.array[int], dadr: wp.array[int],
                       sensors: wp.array[float], refs: wp.array2d[wp.vec3],
                       quats: wp.array2d[wp.vec4], clock: wp.array[int],
                       obs: wp.array[float]):
    for i in range(3):
        obs[i] = sensors[i]
        obs[3 + i] = sensors[3 + i]
        obs[98 + i] = sensors[6 + i]
        obs[101 + i] = xmat[0, root_body][2, i]
    for i in range(25):
        obs[6 + i] = qpos[0, qadr[i]]
        obs[31 + i] = qvel[0, dadr[i]]
    root = wp.vec3(qpos[0, 0], qpos[0, 1], qpos[0, 2])
    # Warp quaternions are xyzw; MuJoCo and the checkpoint are wxyz.
    q = wp.quat(qpos[0, 4], qpos[0, 5], qpos[0, 6], qpos[0, 3])
    qi = wp.quat_inverse(q)
    for i in range(6):
        r = refs[0, clock[1] + i]
        local = wp.quat_rotate(qi, r - root)
        for j in range(3):
            obs[56 + i * 3 + j] = local[j]
        qr = quats[0, clock[1] + i]
        delta = wp.mul(qi, wp.quat(qr[1], qr[2], qr[3], qr[0]))
        sign = wp.where(delta[3] < 0.0, -1.0, 1.0)
        obs[74 + i * 4] = delta[3] * sign
        for j in range(3):
            obs[75 + i * 4 + j] = delta[j] * sign


@wp.kernel
def advance_clock(clock: wp.array[int], time: wp.array[float]):
    clock[0] += 1
    clock[1] += 1
    # Bound fp32 accumulation error across a million physics substeps.
    time[0] = float(clock[0]) * 0.0002


@wp.kernel
def contact_watch(ncon: wp.array[int], geom: wp.array[wp.vec2i],
                  distance: wp.array[float], is_world: wp.array[int],
                  stats: wp.array[int]):
    for i in range(wp.min(ncon[0], geom.shape[0])):
        pair = geom[i]
        if is_world[pair[0]] != is_world[pair[1]] and distance[i] <= 0.0:
            wp.atomic_add(stats, 0, 1)


class CudaFlight:
    def __init__(self, env, policy, initial_obs, block=50):
        wp.init()
        if not wp.is_cuda_available():
            raise RuntimeError("CUDA is required; CPU fallback is not permitted")
        wp.set_device("cuda:0")
        self.env, self.block = env, block
        self.cpu_model, self.cpu_data = env.physics.model.ptr, env.physics.data.ptr
        self.model = mjw.put_model(self.cpu_model)
        # Warp 1.17's occupancy query loads the default 256-thread specialization.
        # Match it when launching CCD, avoiding a stale kernel symbol on the
        # second call after a cold compile. This changes launch layout, not contact.
        self.model.block_dim.convex_ccd = 256
        self.data = mjw.put_data(self.cpu_model, self.cpu_data, nconmax=256, njmax=512)
        # Compile all shape-specialized physics kernels before CUDA capture.
        mjw.step2(self.model, self.data)
        mjw.step1(self.model, self.data)
        wp.synchronize()
        self.data = mjw.put_data(self.cpu_model, self.cpu_data, nconmax=256, njmax=512)
        self.obs = wp.array(concat_obs(initial_obs), dtype=float)
        self.h = [wp.zeros(256, dtype=float) for _ in range(4)]
        self.action = wp.zeros(12, dtype=float)
        self.weights = {k: wp.array(getattr(policy, k), dtype=float)
                        for k in ("w1", "b1", "ln_scale", "ln_offset", "w2",
                                  "b2", "w3", "b3", "w_mean", "b_mean")}
        p, walker = env.physics, env.task.walker
        joints = p.bind(walker.observable_joints).element_id
        self.qadr = wp.array(p.model.jnt_qposadr[joints], dtype=int)
        self.dadr = wp.array(p.model.jnt_dofadr[joints], dtype=int)
        self.root_body = int(p.bind(walker.root_body).element_id)
        wings = p.bind(env.task._wing_joints).element_id
        self.wing_qadr = wp.array(p.model.jnt_qposadr[wings], dtype=int)
        spec = env.action_spec()
        assert spec.shape == (12,) and self.cpu_model.nu == 11
        self.ranges = wp.array(np.stack([spec.minimum, spec.maximum], -1), dtype=float)
        wpg = env.task.wpg
        lengths = [len(x["traj"]) for x in wpg.traj_ctrl]
        phases = np.zeros((len(lengths), max(lengths)), np.float32)
        patterns = np.zeros(phases.shape + (6,), np.float32)
        for i, item in enumerate(wpg.traj_ctrl):
            phases[i, :lengths[i]] = item["phase"]
            patterns[i, :lengths[i]] = item["traj"]
        self.lengths = wp.array(lengths, dtype=int)
        self.phases = wp.array(phases, dtype=float)
        self.patterns = wp.array(patterns, dtype=float)
        self.freqs = wp.array(wpg.beat_freqs, dtype=float)
        self.wpg_int = wp.array([wpg._freq_idx, wpg._step], dtype=int)
        self.wpg_freq = wp.array([wpg._ctrl_freq], dtype=float)
        self.rate = float(wpg._rate)
        self.clock = wp.zeros(2, dtype=int)
        self.sensors = wp.array(np.concatenate([
            initial_obs["walker/accelerometer"], initial_obs["walker/gyro"],
            initial_obs["walker/velocimeter"]]), dtype=float)
        self.refs = wp.zeros((1, block + 7), dtype=wp.vec3)
        self.quats = wp.zeros((1, block + 7), dtype=wp.vec4)
        self.steps = 0
        self.stats = wp.zeros(1, dtype=int)
        self.is_world = wp.array((self.cpu_model.geom_bodyid == 0).astype(np.int32), dtype=int)
        self.upload_reference(env.task.reference)
        self.infer()
        actual = self.action.numpy()
        expected = policy(initial_obs)
        self.policy_error = float(np.max(np.abs(actual - expected)))
        if self.policy_error > 0.0001:
            raise RuntimeError(f"GPU policy mismatch: {self.policy_error}")
        with wp.ScopedCapture() as capture:
            self._control_step()
        self.graph = capture.graph
        print(f"CUDA physics/controller ready; policy error={self.policy_error:.3g}", flush=True)

    def infer(self):
        w, h = self.weights, self.h
        wp.launch(linear, 256, [self.obs, w["w1"], w["b1"], h[0], 0])
        wp.launch(norm_tanh, 256, [h[0], w["ln_scale"], w["ln_offset"], h[1]])
        wp.launch(linear, 256, [h[1], w["w2"], w["b2"], h[2], 1])
        wp.launch(linear, 256, [h[2], w["w3"], w["b3"], h[3], 1])
        wp.launch(linear, 12, [h[3], w["w_mean"], w["b_mean"], self.action, 2])

    def _gather(self):
        wp.launch(gather_observation, 1, [
            self.data.qpos, self.data.qvel, self.data.xmat, self.root_body,
            self.qadr, self.dadr, self.sensors, self.refs, self.quats, self.clock, self.obs])

    def _control_step(self):
        self._gather()
        self.infer()
        wp.launch(wing_control, 1, [
            self.action, self.data.qpos, self.wing_qadr, self.ranges, self.freqs,
            self.lengths, self.phases, self.patterns, self.wpg_int, self.wpg_freq,
            self.rate, self.data.ctrl])
        wp.launch(clear_sensors, 9, [self.sensors])
        for _ in range(4):
            mjw.step2(self.model, self.data)
            mjw.step1(self.model, self.data)
            wp.launch(accumulate_sensors, 9, [self.data.sensordata, self.sensors])
            wp.launch(contact_watch, 1, [
                self.data.nacon, self.data.contact.geom, self.data.contact.dist,
                self.is_world, self.stats])
        wp.launch(advance_clock, 1, [self.clock, self.data.time])

    def upload_reference(self, reference):
        times = (self.steps + np.arange(self.block + 7)) * CONTROL_DT
        pos, quat = reference.sample(times)
        self.refs.assign(np.asarray(pos[None], np.float32))
        self.quats.assign(np.asarray(quat[None], np.float32))
        self.clock.assign(np.array([self.steps, 0], np.int32))

    def step(self):
        wp.capture_launch(self.graph)
        self.steps += 1

    def state(self):
        return self.data.qpos.numpy()[0].copy(), self.data.qvel.numpy()[0].copy()

    def sync_for_render(self):
        """GPU -> CPU display buffer only; never feeds state back to physics."""
        qpos, qvel = self.state()
        self.cpu_data.qpos[:] = qpos
        self.cpu_data.qvel[:] = qvel
        if self.cpu_model.na:
            self.cpu_data.act[:] = self.data.act.numpy()[0]
        self.cpu_data.time = self.steps * CONTROL_DT
        mujoco.mj_forward(self.cpu_model, self.cpu_data)
        return qpos, qvel

    def health(self):
        return dict(world_contacts=int(self.stats.numpy()[0]),
                    overflow=self.data.overflow.numpy().tolist())
