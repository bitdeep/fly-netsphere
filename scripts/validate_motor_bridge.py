"""Bounded causal checks of the real graph, native actuator and shared clock."""
import argparse
import json
from pathlib import Path
import resource
import time

import mujoco
import numpy as np

from fetch_neural_reference import sha256
from motor_bridge import TICKS, PARAMETERS
from serve_environment import Environment


def validate():
    env = Environment()
    bridge, model, data = env.motor, env.model, env.data
    assert bridge and bridge.descriptor["available"], "Validated neural cache required"
    # Independent test initial state. Runtime trials never reset the animal.
    for _ in range(60):
        mujoco.mj_step(model, data, nstep=1000)
        if data.tree_asleep[env.fly_tree] >= 0:
            break
    assert data.tree_asleep[env.fly_tree] >= 0
    resting = mujoco.MjData(model)
    mujoco.mj_copyData(resting, model, data)
    other = np.arange(model.nu) != bridge.actuator
    results = {}
    for mode in ("baseline", "blocked", "stimulus"):
        bridge.disable()
        mujoco.mj_copyData(data, model, resting)
        before = data.qpos.copy(), data.qvel.copy(), data.time
        started, cpu_started = time.monotonic(), time.thread_time()
        env.command({"action": "motor_trial", "mode": mode})
        np.testing.assert_array_equal(before[0], data.qpos)
        np.testing.assert_array_equal(before[1], data.qvel)
        assert before[2] == data.time
        for command in ({"action": "motor_trial", "mode": "stimulus"},
                        {"action": "neural_trial", "mode": "stimulus"}):
            try:
                env.command(command)
                raise AssertionError("Concurrent assay accepted")
            except ValueError:
                pass
        first_motor_tick = first_force_tick = None
        peak_other = 0.
        for tick in range(TICKS):
            bridge.step()
            peak_other = max(peak_other, float(np.max(np.abs(data.actuator_force[other]))))
            if first_force_tick is None and data.actuator_force[bridge.actuator] != 0:
                first_force_tick = tick
            if bridge.active and first_motor_tick is None and bridge.neurons.spike_counts[bridge.motor_indices].any():
                first_motor_tick = tick
            if mode == "stimulus" and first_motor_tick is None:
                np.testing.assert_array_equal(data.qpos, resting.qpos)
        result = bridge.state
        assert result["status"] == "complete", result
        assert not bridge.active and bridge.events is None
        assert model.opt.disableflags & int(mujoco.mjtDisableBit.mjDSBL_ACTUATION)
        assert not result["drive_enabled"]
        assert abs(result["physical_ms"]-500) < 1e-5
        assert result["simulated_ms"] == 500
        assert len(result["history"]) == 100
        assert peak_other == 0, "A non-allowlisted actuator generated force"
        assert not data.warning.number.any() and np.isfinite(data.qpos).all()
        counts = [item["spikes"] for item in result["readouts"]]
        if mode == "baseline":
            assert counts == [0, 0] and result["total_spikes"] == 0
        else:
            assert counts == [30, 17] and result["total_spikes"] == 5076
        if mode != "stimulus":
            assert result["peak_force"] == 0 and result["peak_excursion_deg"] == 0
            np.testing.assert_array_equal(data.qpos, resting.qpos)
        else:
            assert first_force_tick == first_motor_tick == 255
            assert result["peak_excursion_deg"] > 10
            assert 0 < result["peak_force"] <= .1
            assert data.tree_asleep[env.fly_tree] < 0, "Sleeping animal did not wake"
        results[mode] = {
            key: result[key] for key in ("total_spikes", "input_spikes", "downstream_spikes",
                                        "peak_force", "peak_excursion_deg", "physical_ms", "simulated_ms")
        }
        results[mode].update(mn9_spikes=counts, other_actuator_peak_force=peak_other,
                             first_force_ms=None if first_force_tick is None else first_force_tick*PARAMETERS.dt_ms,
                             wall_seconds=time.monotonic()-started,
                             cpu_seconds=time.thread_time()-cpu_started)
        print(mode, json.dumps(results[mode]), flush=True)
    # Cancellation must remove actuator authority, including after it has fired.
    bridge.start("stimulus")
    for _ in range(400):
        bridge.step()
    assert bridge.state["drive_enabled"] or data.actuator_force[bridge.actuator] != 0
    env.command({"action": "pause", "paused": True})
    # The gravity control also resumes the environment; both clocks must resume.
    fly_qpos = data.qpos[:env.probe_qpos].copy()
    env.command({"action": "drop"})
    assert not env.paused and not bridge.state["paused"] and bridge.paused_at is None
    np.testing.assert_array_equal(data.qpos[:env.probe_qpos], fly_qpos)
    env.command({"action": "pause", "paused": True})
    frozen = data.time, bridge.neurons.tick
    env.command({"action": "motor_stop"})
    assert (data.time, round(bridge.state["simulated_ms"]/PARAMETERS.dt_ms)) == frozen
    assert not bridge.active and not bridge.state["drive_enabled"]
    assert model.opt.disableflags & int(mujoco.mjtDisableBit.mjDSBL_ACTUATION)
    assert not np.signbit(data.qfrc_applied[bridge.dof])
    first = env.snapshot()
    delta = env.snapshot(neural_revision=first["neural_revision"], motor_revision=first["motor_revision"])
    assert "neural" not in delta and "motor" not in delta
    try:
        env.command({"action": "motor_trial", "mode": "stimulus"})
        raise AssertionError("Motor trial started while paused")
    except ValueError:
        pass
    env.command({"action": "pause", "paused": False})
    try:
        env.command({"action": "motor_trial", "mode": "stimulus"})
        raise AssertionError("Motor trial started before physical rest")
    except ValueError:
        pass
    # Enforced clock mismatch fails closed and reports an incomplete result.
    bridge.start("baseline")
    bridge.physical_start -= .001
    try:
        bridge.step()
        raise AssertionError("Clock divergence was accepted")
    except RuntimeError:
        pass
    assert bridge.state["status"] == "error" and not bridge.active
    assert model.opt.disableflags & int(mujoco.mjtDisableBit.mjDSBL_ACTUATION)
    env.stop.set()
    root = Path(__file__).resolve().parents[1]
    return {
        "schema": 1, "passed": True,
        "code_sha256": {name: sha256(root/"scripts"/name) for name in
                        ("motor_bridge.py", "serve_environment.py", "neural_reference.py",
                         "validate_motor_bridge.py")},
        "cache_manifest_sha256": sha256(root/"out/neural-reference/manifest.json"),
        "protocol": bridge.descriptor, "results": results,
        "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
        "checks": ["shared clock", "native wake", "no pre-spike movement",
                   "motor block", "zero-input baseline", "actuator allowlist",
                   "concurrent assay rejection", "cancel while paused", "clock mismatch fails closed"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = validate()
    args.output.write_text(json.dumps(report, indent=2)+"\n")
    print(f"Motor validation passed; peak RSS {report['peak_rss_mib']:.1f} MiB", flush=True)
