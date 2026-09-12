"""Causal world-contact checks using the real anatomy, graph and motor bridge."""
import argparse
import json
from pathlib import Path
import resource
import time

import mujoco
import numpy as np

from fetch_neural_reference import sha256
from habitat import CAPACITY
from serve_environment import Environment


def validate():
    env = Environment()
    model, data, habitat, motor = env.model, env.data, env.habitat, env.motor
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
        # Independent fixtures only. Runtime object commands never reset the fly.
        mujoco.mj_copyData(data, model, resting)

    def place(kind, **kwargs):
        before = data.qpos.copy(), data.qvel.copy(), data.time
        env.command({"action": "object_place", "kind": kind, **kwargs})
        np.testing.assert_array_equal(data.qpos, before[0])
        np.testing.assert_array_equal(data.qvel, before[1])
        assert data.time == before[2]
        return habitat.objects[-1]["id"]

    def sense():
        habitat.next_sample = 0.
        habitat.sample(motor, False, bool(data.tree_asleep[env.fly_tree] >= 0))

    # No contact, no chemosensory input. Neutral contact also evokes no trial.
    mouth = data.geom_xpos[habitat.mouth].copy()
    object_id = place("fruit", position=(mouth+[0, .2, 0]).tolist())
    sense()
    assert not habitat.touching(object_id) and not motor.active
    reset()
    object_id = place("neutral")
    sense()
    assert habitat.touching(object_id) and habitat.objects[0]["used"] and not motor.active
    reset()
    object_id = place("fruit")
    env.command({"action": "reactive_senses", "enabled": False})
    sense()
    assert not motor.active and not habitat.objects[0]["used"]
    env.command({"action": "reactive_senses", "enabled": True})
    habitat.sample(motor, True, True)
    assert not motor.active, "World input overlapped an antennal trial"

    results = {}
    for kind, cutoff in (("fruit", None), ("water", None), ("bitter", None),
                         ("fruit", "remove"), ("fruit", "disable")):
        reset()
        object_id = place(kind)
        assert habitat.touching(object_id)
        sense()
        assert motor.active and motor.state["source"]["object_id"] == object_id
        started = time.thread_time()
        other_force = 0.
        while motor.active:
            if cutoff and motor.neurons.tick == 500:
                before = data.qpos.copy()
                env.command({"action": "object_remove", "id": object_id}
                            if cutoff == "remove" else
                            {"action": "reactive_senses", "enabled": False})
                np.testing.assert_array_equal(data.qpos, before)
            motor.step()
            other_force = max(other_force, float(np.max(np.abs(
                np.delete(data.actuator_force, motor.actuator)))))
        result = motor.state
        assert result["status"] == "complete", result
        assert abs(result["physical_ms"]-result["simulated_ms"]) < 1e-5
        assert len(result["history"]) == 100 and other_force == 0
        assert not data.warning.number.any()
        if cutoff:
            assert not result["sensory_contact"]
            assert all(not item["sensory_contact"] for item in result["history"] if item["ms"] > 50)
            assert result["input_spikes"] < results["fruit"]["input_spikes"]
        elif kind == "bitter":
            assert result["peak_force"] == result["peak_excursion_deg"] == 0
            assert result["downstream_spikes"] > 0
        else:
            assert result["peak_excursion_deg"] > 5
        key = kind if cutoff is None else f"fruit_{cutoff}_at_50ms"
        results[key] = {name: result[name] for name in
                        ("input_spikes", "downstream_spikes", "peak_excursion_deg",
                         "sensory_contact", "physical_ms", "simulated_ms")}
        results[key]["cpu_seconds"] = time.thread_time()-started
        print(key, json.dumps(results[key]), flush=True)
        # A consumed source never starts an endless sequence of reset trials.
        trial_id = result["trial"]
        for _ in range(10):
            habitat.sample(motor, False, True)
        assert motor.state["trial"] == trial_id

    reset()
    for _ in range(CAPACITY):
        place("neutral")
    before = data.qpos.copy()
    try:
        place("fruit")
        raise AssertionError("Capacity limit was ignored")
    except ValueError:
        pass
    reset()
    invalid = [
        {"action": "object_remove", "id": True},
        {"action": "object_remove", "id": -1},
        {"action": "reactive_senses", "enabled": "true"},
        {"action": "object_place", "kind": "fruit", "neurons": [1]},
    ]
    invalid += [{"action": "object_place", "kind": kind}
                for kind in ("odor", [], {"rate": 200})]
    invalid += [{"action": "object_place", "kind": "fruit", "position": point}
                for point in ([0, 0], [True, 0, 0], [0, float("nan"), 0],
                              [0, float("inf"), 0], [0, 0, 0])]
    for command in invalid:
        try:
            env.command(command)
            raise AssertionError(f"Invalid object command accepted: {command}")
        except ValueError:
            pass
    np.testing.assert_array_equal(data.qpos, before)
    first = env.snapshot()
    delta = env.snapshot(habitat_revision=first["habitat_revision"])
    assert "habitat" not in delta
    env.stop.set()
    root = Path(__file__).resolve().parents[1]
    return {
        "schema": 1, "passed": True, "results": results,
        "code_sha256": {name: sha256(root/"scripts"/name) for name in
                        ("habitat.py", "motor_bridge.py", "serve_environment.py", "validate_habitat.py")},
        "cache_manifest_sha256": sha256(root/"out/neural-reference/manifest.json"),
        "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
        "checks": ["contact required", "neutral control", "senses off", "single neural trial",
                   "shared clock", "object removal gates input", "disable gates input",
                   "no pose writes", "one response per placement", "bounded object commands",
                   "actuator allowlist", "delta transport"],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = validate()
    args.output.write_text(json.dumps(report, indent=2)+"\n")
    print(f"Habitat validation passed; peak RSS {report['peak_rss_mib']:.1f} MiB", flush=True)
