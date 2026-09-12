"""One explicit engineered MN9-to-rostrum link over the verified FlyWire graph."""
import ast
import json
from pathlib import Path
import time

import mujoco
import numpy as np

from fetch_neural_reference import sha256
from neural_reference import LIF, PARAMETERS, poisson_events
from passive_fly import FLY_ID

TICKS = 5000
STIMULUS_TICKS = 3000
RATE_HZ = 200
SEED = 20260912
FILTER_MS = 30.
FULL_DRIVE_HZ = 100.
WALL_LIMIT = 90.
CPU_LIMIT = 10.
SPIKE_LIMIT = 100000
MODES = ("stimulus", "baseline", "blocked")
STIMULI = {"sugar": 21, "water": 18, "bitter": 21}
SOURCE = Path(__file__).resolve().parents[1]/"data/neural-reference/figures.ipynb"


def feeding_identifiers(graph, source=SOURCE):
    """Read literal published IDs; never execute notebook cells."""
    expected = graph.manifest["source_files"]["figures.ipynb"]["sha256"]
    if sha256(source) != expected:
        raise ValueError("Feeding protocol source checksum mismatch")
    found = {}
    for cell in json.loads(source.read_text())["cells"]:
        if cell["cell_type"] != "code":
            continue
        tree = ast.parse("".join(cell["source"]))
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in ("neu_sugar", "neu_water", "neu_bitter", "ids_mn9"):
                    values = ast.literal_eval(node.value)
                    if (not isinstance(values, list) or not all(type(x) is int for x in values)
                            or target.id in found and found[target.id] != values):
                        raise ValueError("Ambiguous feeding neuron identifiers")
                    found[target.id] = values
    if (any(len(found.get(f"neu_{name}", [])) != count for name, count in STIMULI.items())
            or len(found.get("ids_mn9", [])) != 2):
        raise ValueError("Published feeding neuron groups are missing")
    # IDs exceed JavaScript's safe integer range. Expose their strings, not numbers.
    lookup = {int(value): i for i, value in enumerate(graph.ids)}
    return {key: [{"id": str(value), "index": lookup[value]} for value in values]
            for key, values in found.items()}


class MotorBridge:
    """Called only under the environment lock, on its single physics thread.

    No pose writes. One neural step and one native physical step share 0.1 ms.
    All actuators except the allowlisted rostrum servo remain disabled by group.
    """
    def __init__(self, graph, model, data, fly_tree):
        self.graph, self.model, self.data = graph, model, data
        self.fly_tree = fly_tree
        self.neurons = None
        self.events = None
        self.state = {"revision": 0, "status": "unavailable", "drive_enabled": False}
        self.descriptor = {"available": False}
        self.actuator = None
        try:
            if graph is None:
                raise ValueError("Prepare and validate the neural reference first.")
            ids = feeding_identifiers(graph)
            if abs(model.opt.timestep-PARAMETERS.dt_ms/1000) > 1e-12:
                raise ValueError("Motor link requires matching 0.1 ms clocks")
            self.input_groups = {name: np.array([item["index"] for item in ids[f"neu_{name}"]])
                                 for name in STIMULI}
            self.inputs = self.input_groups["sugar"]
            self.readouts = [{**item, "label": label} for item, label in
                             zip(ids["ids_mn9"], ("MN9 left", "MN9 right"))]
            self.motor_indices = np.array([item["index"] for item in self.readouts])
            self.sensory = np.zeros(graph.size, dtype=bool)
            self.sensory[self.inputs] = True
            joint = model.joint(f"{FLY_ID}/rostrum")
            self.qpos, self.dof = int(joint.qposadr[0]), int(joint.dofadr[0])
            self.actuator = model.actuator(f"{FLY_ID}/rostrum").id
            self.minimum, self.maximum = model.actuator_ctrlrange[self.actuator]
            # Groups are runtime allowlists, not changes to anatomy/servo parameters.
            model.actuator_group[:] = 0
            model.actuator_group[self.actuator] = 1
            model.opt.disableactuator = 1
            self.disable()
            self.decay = float(np.exp(-PARAMETERS.dt_ms/FILTER_MS))
            self.descriptor = {
                "available": True, "input_count": len(self.inputs), "inputs": ids["neu_sugar"],
                "stimuli": [{"id": name, "input_count": count, "inputs": ids[f"neu_{name}"]}
                            for name, count in STIMULI.items()],
                "readouts": self.readouts, "rate_hz": RATE_HZ, "seed": SEED,
                "total_ms": TICKS*PARAMETERS.dt_ms,
                "stimulus_ms": STIMULUS_TICKS*PARAMETERS.dt_ms,
                "filter_ms": FILTER_MS, "full_drive_hz": FULL_DRIVE_HZ,
                "actuator": f"{FLY_ID}/rostrum", "control_range_rad": [self.minimum, self.maximum],
                "adapter": "Engineered firing-rate to position-servo target",
                "source_sha256": graph.manifest["source_files"]["figures.ipynb"]["sha256"],
            }
            self.state = {"revision": 1, "status": "idle", "trial": 0,
                          "drive_enabled": False, "history": [], "readouts": []}
        except (OSError, ValueError, KeyError, SyntaxError) as exc:
            self.disable()
            self.descriptor["error"] = f"Motor link unavailable: {exc}"
            self.state["error"] = self.descriptor["error"]

    @property
    def active(self):
        return self.neurons is not None

    def disable(self):
        self.model.opt.disableflags |= int(mujoco.mjtDisableBit.mjDSBL_ACTUATION)
        if self.actuator is not None:
            self.data.ctrl[self.actuator] = 0
            self.data.qfrc_applied[self.dof] = 0.
        self.model.tree_sleep_policy[self.fly_tree] = mujoco.mjtSleepPolicy.mjSLEEP_ALLOWED

    def start(self, mode, stimulus="sugar"):
        if not isinstance(mode, str) or mode not in MODES:
            raise ValueError("Motor mode must be stimulus, baseline or blocked")
        if not isinstance(stimulus, str) or stimulus not in STIMULI:
            raise ValueError("Taste stimulus must be sugar, water or bitter")
        if not self.descriptor["available"]:
            raise ValueError(self.state["error"])
        if self.active:
            raise ValueError("A motor trial is already running")
        self.disable()
        self.mode = mode
        self.inputs = self.input_groups[stimulus]
        self.sensory[:] = False
        self.sensory[self.inputs] = True
        self.neurons = LIF(self.graph, self.inputs)
        self.events = poisson_events(self.inputs, TICKS,
                                     rate_hz=0 if mode == "baseline" else RATE_HZ,
                                     seed=SEED, stimulus_ticks=STIMULUS_TICKS)
        self.started, self.physical_start = time.monotonic(), float(self.data.time)
        self.cpu_seconds = self.pause_seconds = 0.
        self.paused_at = None
        self.next_publish = 0.
        self.rate = self.activation = self.total = self.input_total = self.motor_total = 0
        self.initial_angle = float(self.data.qpos[self.qpos])
        self.peak_excursion = self.peak_force = 0.
        self.history = []
        self.state = {"revision": self.state["revision"]+1, "status": "running",
                      "trial": self.state["trial"]+1, "mode": mode, "stimulus": stimulus,
                      "input_count": len(self.inputs), "drive_enabled": False,
                      "history": [], "readouts": [], "simulated_ms": 0, "physical_ms": 0,
                      "total_spikes": 0, "downstream_spikes": 0,
                      "peak_excursion_deg": 0, "peak_force": 0}

    def set_paused(self, value):
        if not self.active:
            return
        now = time.monotonic()
        if value and self.paused_at is None:
            self.paused_at = now
        elif not value and self.paused_at is not None:
            self.pause_seconds += now-self.paused_at
            self.paused_at = None
        self.state = {**self.state, "revision": self.state["revision"]+1, "paused": value}

    def _publish(self, status="running", error=None):
        neurons = self.neurons
        now = time.monotonic()
        self.state = {
            **self.state, "revision": self.state["revision"]+1, "status": status,
            "drive_enabled": status == "running" and self.mode == "stimulus" and self.rate > 0,
            "simulated_ms": neurons.tick*PARAMETERS.dt_ms,
            "physical_ms": (self.data.time-self.physical_start)*1000,
            "wall_seconds": now-self.started, "cpu_seconds": self.cpu_seconds,
            "total_spikes": self.total, "input_spikes": self.input_total,
            "downstream_spikes": self.total-self.input_total,
            "readouts": [{**item, "spikes": int(neurons.spike_counts[item["index"]]),
                          "voltage_mv": float(neurons.v[item["index"]])}
                         for item in self.readouts],
            "activation": self.activation if status == "running" else 0.,
            "angle_deg": float(np.degrees(self.data.qpos[self.qpos])),
            "peak_excursion_deg": self.peak_excursion, "peak_force": self.peak_force,
            "history": list(self.history),
        }
        if error:
            self.state["error"] = error

    def finish(self, status="cancelled", error=None):
        self.disable()
        if self.active:
            self._publish(status, error)
        # Keep only the small measured history. Release trial state at idle.
        self.neurons = self.events = None

    def step(self):
        if not self.active:
            raise RuntimeError("No active motor trial")
        cpu_started = time.thread_time()
        try:
            spikes = self.neurons.step(self.events[self.neurons.tick])
            self.total += len(spikes)
            self.input_total += int(np.count_nonzero(self.sensory[spikes]))
            motor_total = sum(int(self.neurons.spike_counts[i]) for i in self.motor_indices)
            motor_spikes, self.motor_total = motor_total-self.motor_total, motor_total
            # Exponential spike-rate estimate, averaged across the bilateral pair.
            self.rate = self.rate*self.decay + motor_spikes*1000/(2*FILTER_MS)
            self.activation = min(1., self.rate/FULL_DRIVE_HZ)
            if self.mode == "stimulus" and self.rate > 0:
                self.model.opt.disableflags &= ~int(mujoco.mjtDisableBit.mjDSBL_ACTUATION)
                self.model.tree_sleep_policy[self.fly_tree] = mujoco.mjtSleepPolicy.mjSLEEP_NEVER
                # MuJoCo's documented bytewise wake signal: negative zero wakes
                # a sleeping actuated tree without injecting a nonzero force.
                self.data.qfrc_applied[self.dof] = -0.
                self.data.ctrl[self.actuator] = self.maximum + self.activation*(self.minimum-self.maximum)
            mujoco.mj_step(self.model, self.data)
            elapsed = (self.data.time-self.physical_start)*1000
            if abs(elapsed-self.neurons.tick*PARAMETERS.dt_ms) > 1e-5:
                raise RuntimeError("Neural and physical clocks diverged")
            angle = float(np.degrees(self.data.qpos[self.qpos]))
            excursion = abs(angle-np.degrees(self.initial_angle))
            force = float(self.data.actuator_force[self.actuator])
            self.peak_excursion = max(self.peak_excursion, excursion)
            self.peak_force = max(self.peak_force, abs(force))
            if self.neurons.tick % 50 == 0:
                self.history.append({
                    "ms": self.neurons.tick*PARAMETERS.dt_ms, "angle_deg": angle,
                    "drive": self.activation if self.mode == "stimulus" else 0.,
                    "mn9_spikes": int(self.neurons.spike_counts[self.motor_indices].sum()),
                })
            self.cpu_seconds += time.thread_time()-cpu_started
            if self.neurons.tick % 25 == 0:
                if (self.total > SPIKE_LIMIT or self.cpu_seconds > CPU_LIMIT
                        or time.monotonic()-self.started-self.pause_seconds > WALL_LIMIT):
                    raise RuntimeError("Motor trial reached its resource limit; results are incomplete.")
                if not np.isfinite(self.data.qpos).all() or self.data.warning.number.any():
                    raise RuntimeError("Motor trial stopped after a physics warning")
            if self.neurons.tick == TICKS:
                self.finish("complete")
            elif time.monotonic() >= self.next_publish:
                self._publish()
                self.next_publish = time.monotonic()+.1
        except Exception as exc:
            self.finish("error", str(exc))
            raise
