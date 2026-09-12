"""Compare physical outcomes with avoidance off and an obstacle moved."""
import argparse
import json
from pathlib import Path
import numpy as np


def load(path):
    return json.loads((path/"metrics.json").read_text()), np.load(path/"states.npz")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("shifted", type=Path)
    parser.add_argument("disabled", type=Path)
    args = parser.parse_args()
    base, bs = load(args.baseline)
    shift, ss = load(args.shifted)
    off, _ = load(args.disabled)
    assert base["completed"] and shift["completed"]
    assert base["seed"] == shift["seed"] == off["seed"]
    assert base["avoidance"] and shift["avoidance"] and not off["avoidance"]
    assert base["obstacle_shift"] == off["obstacle_shift"]
    assert shift["obstacle_shift"] != base["obstacle_shift"]
    assert base["world_contacts"] == shift["world_contacts"] == 0
    assert not any(base["overflow"]) and not any(shift["overflow"])
    assert off["world_contacts"] > 0 and not off["completed"]
    count = min(len(bs["time"]), len(ss["time"]))
    assert np.array_equal(bs["time"][:count], ss["time"][:count])
    delta = np.linalg.norm(bs["qpos"][:count, :3]-ss["qpos"][:count, :3], axis=1)
    assert delta[0] < 1e-6
    assert delta.max() > 2., "Moving the obstacle should materially change the physical flight"
    result = dict(passed=True, identical_initial_state=True,
        moved_obstacle_cm=shift["obstacle_shift"]-base["obstacle_shift"],
        maximum_trajectory_change_cm=float(delta.max()),
        baseline_contacts=base["world_contacts"], shifted_contacts=shift["world_contacts"],
        disabled_contacts=off["world_contacts"],
        disabled_stop_seconds=off["simulated_seconds"],
        disabled_solver_flags=off["overflow"],
        note="Negative control is rejected after impact; post-impact dynamics are not an accepted take.")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
