"""Real full-graph feeding, finite sources and survival/runtime integration."""
import argparse
import json
from pathlib import Path
import resource
import time

import mujoco
import numpy as np

from fetch_neural_reference import sha256
from habitat import KINDS, RETRY_INTERVAL
from serve_environment import Environment
from survival import DRAIN, PORTION


def validate():
    env = Environment()
    model, data, motor, habitat = env.model, env.data, env.motor, env.habitat
    assert motor.descriptor["available"]
    for _ in range(60):
        mujoco.mj_step(model, data, nstep=1000)
        if data.tree_asleep[env.fly_tree] >= 0:
            break
    assert data.tree_asleep[env.fly_tree] >= 0
    resting = mujoco.MjData(model)
    mujoco.mj_copyData(resting, model, data)

    def reset():
        motor.finish()
        for item in list(habitat.objects):
            habitat.remove(item["id"])
        habitat.set_enabled(True)
        env.survival.restart()
        mujoco.mj_copyData(data, model, resting)  # Independent test fixtures only.

    def step():
        motor.step()
        env._advance_survival(model.opt.timestep)
        assert not data.warning.number.any()
        assert not np.delete(data.actuator_force, motor.actuator).any()
        if not motor.motor_total:
            assert not any(env.survival.consumed.values()), "Intake before MN9 response"

    results = {}
    for kind, mode, intervention in [
            ("fruit", "stimulus", None), ("water", "stimulus", None),
            ("bitter", "stimulus", None), ("fruit", "baseline", None),
            ("fruit", "blocked", None), ("water", "blocked", None),
            ("fruit", "stimulus", "remove"), ("fruit", "stimulus", "disable"),
            ("fruit", "stimulus", "remote"), ("fruit", "stimulus", "manual")]:
        reset()
        point = None if intervention != "remote" else (data.geom_xpos[habitat.mouth]+[0, .2, 0]).tolist()
        habitat.place(kind, point)
        item = habitat.objects[-1]
        object_id = item["id"]
        motor.start(mode, KINDS[kind]["stimulus"],
                    sensory_gate=(None if intervention == "manual" else lambda: habitat.touching(object_id)),
                    source=(None if intervention == "manual" else {"object_id": object_id, "label": KINDS[kind]["label"]}))
        started = time.thread_time()
        elapsed_start = data.time
        at_cutoff = None
        while motor.active:
            if intervention in ("remove", "disable") and motor.neurons.tick == 500:
                at_cutoff = dict(env.survival.consumed)
                if intervention == "remove":
                    habitat.remove(object_id)
                else:
                    habitat.set_enabled(False)
            step()
            if at_cutoff is not None:
                assert env.survival.consumed == at_cutoff, "Intake continued after cutoff"
        life = env.survival
        elapsed = data.time-elapsed_start
        for reserve in DRAIN:
            assert abs(getattr(life, reserve)-(.7-DRAIN[reserve]*elapsed+life.consumed[reserve])) < 1e-10
        if mode != "stimulus" or kind == "bitter" or intervention in ("remote", "manual"):
            assert not any(life.consumed.values())
        elif intervention is None:
            reserve = "energy" if kind == "fruit" else "water"
            assert life.consumed[reserve] > 0, "Measured feeding did not transfer reserves"
            assert life.consumed["water" if reserve == "energy" else "energy"] == 0
            remaining = sum(x["remaining"] for x in habitat.objects)
            assert abs(life.consumed[reserve]+remaining-PORTION) < 1e-10
            if remaining < 1e-12:
                assert not habitat.objects, "Empty portion retained a slot"
        key = f"{kind}_{mode}_{intervention or 'contact'}"
        results[key] = {"consumed": dict(life.consumed), "objects_left": len(habitat.objects),
                        "cpu_seconds": time.thread_time()-started,
                        "peak_excursion_deg": motor.state["peak_excursion_deg"],
                        "downstream_spikes": motor.state["downstream_spikes"]}
        print(key, json.dumps(results[key]), flush=True)

    # Automatic bouts respect rest, cooldown, satiety and the one-worker boundary.
    reset()
    habitat.place("fruit")
    env.survival.energy = 1.
    habitat.sample(motor, False, True, env.survival)
    assert not motor.active, "Satiated source started a bout"
    env.survival.energy = .7
    habitat.next_sample = 0
    habitat.sample(motor, False, True, env.survival)
    assert motor.active
    first_trial = motor.state["trial"]
    retry_at = habitat.objects[0]["retry_at"]
    assert abs(retry_at-data.time-RETRY_INTERVAL) < 1e-9
    # End before feeding so a known leftover remains for a real physical retry.
    motor.finish()
    while data.time < retry_at+.05:
        mujoco.mj_step(model, data, nstep=10)
        env._advance_survival(10*model.opt.timestep)
        habitat.sample(motor, False, bool(data.tree_asleep[env.fly_tree] >= 0), env.survival)
        if data.time < retry_at:
            assert not motor.active
        if motor.active:
            break
    assert motor.active and motor.state["trial"] == first_trial+1
    env.command({"action": "motor_stop"})
    assert not habitat.enabled and not motor.active, "Stop must prevent automatic retries"

    # Death cancels active motor authority, rejects new assays and cannot revive
    # on food. New life changes only the reserve state, never physical state.
    for cause in DRAIN:
        reset()
        habitat.place("fruit")
        habitat.sample(motor, False, True, env.survival)
        for _ in range(400):
            step()
        assert motor.motor_total > 0
        setattr(env.survival, cause, DRAIN[cause]*model.opt.timestep/2)
        step()
        assert not env.survival.alive and env.survival.cause == cause
        assert not motor.active and not motor.state["drive_enabled"]
        assert model.opt.disableflags & int(mujoco.mjtDisableBit.mjDSBL_ACTUATION)
        assert not np.signbit(data.qfrc_applied[motor.dof])
        for action in ("motor_trial", "neural_trial"):
            try:
                env.command({"action": action, "mode": "stimulus"})
                raise AssertionError("Dead fly accepted a neural trial")
            except ValueError:
                pass
        before = data.qpos.copy(), data.qvel.copy(), data.time
        env.command({"action": "life_restart"})
        np.testing.assert_array_equal(data.qpos, before[0])
        np.testing.assert_array_equal(data.qvel, before[1])
        assert data.time == before[2] and env.survival.alive
        try:
            env.command({"action": "life_restart"})
            raise AssertionError("Live fly accepted free reserve reset")
        except ValueError:
            pass
    reset()
    # Exercise Pause through the actual worker, not a substitute clock.
    env.command({"action": "pause", "paused": True})
    frozen = env.survival.snapshot(), data.time
    env.start()
    try:
        time.sleep(.15)
        assert (env.survival.snapshot(), data.time) == frozen
        env.command({"action": "pause", "paused": False})
        time.sleep(.15)
        env.command({"action": "pause", "paused": True})
        assert data.time > frozen[1] and env.survival.water < frozen[0]["water"]
        first = env.snapshot()
        assert "survival" not in env.snapshot(survival_revision=first["survival_revision"])
    finally:
        env.stop.set()
        env.thread.join(timeout=5)
    root = Path(__file__).resolve().parents[1]
    return {"schema": 1, "passed": True, "results": results,
            "code_sha256": {name: sha256(root/"scripts"/name) for name in (
                "survival.py", "habitat.py", "motor_bridge.py", "serve_environment.py",
                "validate_survival.py", "test_survival.py")},
            "cache_manifest_sha256": sha256(root/"out/neural-reference/manifest.json"),
            "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
            "checks": ["native feeding contact", "resource conservation", "capacity",
                       "baseline and blocked controls", "no intake from direct presets",
                       "source removal and senses disable", "no pre-spike intake",
                       "bounded automatic retry", "satiety", "Stop prevents retry",
                       "death cancels actuator authority", "no automatic revival",
                       "restart preserves physical state", "worker Pause", "delta transport"]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = validate()
    args.output.write_text(json.dumps(report, indent=2)+"\n")
    print(f"Survival validation passed; peak RSS {report['peak_rss_mib']:.1f} MiB", flush=True)
