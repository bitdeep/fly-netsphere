"""On-demand, bounded neural assays; no connection to the body's actuators."""
import json
from pathlib import Path
import threading
import time

import numpy as np

from fetch_neural_reference import sha256
from neural_reference import CACHE, Graph, LIF, PARAMETERS, poisson_events

TICKS = 1500
STIMULUS_TICKS = 1000
SEED = 20260912
CPU_BUDGET = .15
WALL_LIMIT = 90.
CPU_LIMIT = 10.
SPIKE_LIMIT = 100000
MODES = ("stimulus", "baseline", "blocked")


class NeuralLab:
    def __init__(self, stop, directory=CACHE):
        self.stop = stop
        self.lock = threading.Lock()
        self.cancel = threading.Event()
        self.thread = None
        self.graph = None
        self.state = {"revision": 0, "status": "unavailable", "motor_connected": False}
        self.descriptor = {"available": False, "dataset": "FlyWire 630",
                           "motor_connected": False}
        try:
            report = json.loads((directory/"validation.json").read_text())
            if (report["schema"] != 1
                    or report["core_sha256"] != sha256(Path(__file__).with_name("neural_reference.py"))
                    or report["cache_manifest_sha256"] != sha256(directory/"manifest.json")):
                raise ValueError("Neural validation is stale; rerun the reference assay.")
            self.graph = Graph(directory)
            manifest = self.graph.manifest
            self.descriptor.update({
                "available": True, "neuron_count": self.graph.size,
                "edge_count": len(self.graph.indices), "input_count": len(manifest["inputs"]),
                "diagram": manifest["diagram"], "readouts": manifest["readouts"],
                "reference_commit": manifest["reference_commit"],
                "total_ms": TICKS*PARAMETERS.dt_ms,
                "stimulus_ms": STIMULUS_TICKS*PARAMETERS.dt_ms,
                "rate_hz": 150, "seed": SEED, "cpu_budget": CPU_BUDGET,
                "wall_limit_seconds": WALL_LIMIT,
                "numerical_reference": "Brian2 2.8.0.4",
            })
            self.state = {"revision": 1, "status": "idle", "motor_connected": False,
                          "trial": 0, "history": [], "nodes": [], "readouts": []}
        except (OSError, ValueError, KeyError) as exc:
            self.graph = None
            message = ("Neural reference cache is missing; prepare and validate it first."
                       if isinstance(exc, OSError) else str(exc))
            self.descriptor["error"] = message
            self.state["error"] = message

    def snapshot(self):
        # Published dictionaries are replaced, never modified by the worker.
        with self.lock:
            return self.state

    def start(self, mode):
        if not isinstance(mode, str) or mode not in MODES:
            raise ValueError("Neural mode must be stimulus, baseline or blocked")
        with self.lock:
            if self.graph is None:
                raise ValueError(self.state["error"])
            if self.thread is not None and self.thread.is_alive():
                raise ValueError("A neural trial is already running")
            if self.stop.is_set():
                raise ValueError("The environment is stopping")
            trial = self.state["trial"]+1
            self.cancel.clear()
            self.state = {
                "revision": self.state["revision"]+1, "status": "running",
                "motor_connected": False, "trial": trial, "mode": mode,
                "simulated_ms": 0, "wall_seconds": 0, "cpu_seconds": 0,
                "total_spikes": 0, "input_spikes": 0, "downstream_spikes": 0,
                "neurons_that_spiked": 0, "history": [], "nodes": [], "readouts": [],
            }
            self.thread = threading.Thread(target=self._run, args=(mode,),
                                           name="neural-assay", daemon=True)
            self.thread.start()

    def cancel_trial(self):
        self.cancel.set()

    def _publish(self, values):
        with self.lock:
            self.state = {**self.state, **values, "revision": self.state["revision"]+1}

    def _run(self, mode):
        started, cpu_started = time.monotonic(), time.thread_time()
        try:
            graph = self.graph
            inputs = graph.manifest["inputs"]
            model = LIF(graph, inputs, inputs if mode == "blocked" else ())
            events = poisson_events(inputs, TICKS, rate_hz=0 if mode == "baseline" else 150,
                                    seed=SEED, stimulus_ticks=STIMULUS_TICKS)
            sensory = np.zeros(graph.size, dtype=bool)
            sensory[inputs] = True
            descending = np.zeros(graph.size, dtype=bool)
            descending[[r["index"] for r in graph.manifest["readouts"]
                        if r["role"] == "descending"]] = True
            total = input_total = 0
            history = []
            bins = np.zeros(3, dtype=np.int64)
            next_publish = 0.
            for first in range(0, TICKS, 25):
                if self.stop.is_set() or self.cancel.is_set():
                    self._publish({"status": "cancelled"})
                    return
                for external in events[first:first+25]:
                    spikes = model.step(external)
                    n_input = int(np.count_nonzero(sensory[spikes]))
                    n_descending = int(np.count_nonzero(descending[spikes]))
                    total += len(spikes)
                    input_total += n_input
                    bins += (n_input, len(spikes)-n_input, n_descending)
                    if model.tick % 50 == 0:
                        history.append({"ms": model.tick*PARAMETERS.dt_ms,
                                        "input": int(bins[0]), "network": int(bins[1]),
                                        "descending": int(bins[2])})
                        bins[:] = 0
                cpu_used = time.thread_time()-cpu_started
                wall_used = time.monotonic()-started
                if total > SPIKE_LIMIT or cpu_used > CPU_LIMIT or wall_used > WALL_LIMIT:
                    raise RuntimeError("Trial stopped at its resource limit; results are incomplete.")
                # Duty-cycle one worker; unused neurons and all graph files stay
                # shared/read-only. No continuous assay runs while the UI is idle.
                if self.cancel.wait(max(0, cpu_used/CPU_BUDGET-wall_used)) or self.stop.is_set():
                    self._publish({"status": "cancelled"})
                    return
                now = time.monotonic()
                complete = model.tick == TICKS
                if now >= next_publish or complete:
                    nodes = [{"index": item["index"],
                              "spikes": int(model.spike_counts[item["index"]]),
                              "voltage_mv": round(float(model.v[item["index"]]), 4)}
                             for item in graph.manifest["diagram"]["nodes"]]
                    readouts = [{**item, "spikes": int(model.spike_counts[item["index"]]),
                                 "voltage_mv": round(float(model.v[item["index"]]), 4)}
                                for item in graph.manifest["readouts"]]
                    self._publish({
                        "status": "complete" if complete else "running",
                        "simulated_ms": model.tick*PARAMETERS.dt_ms,
                        "wall_seconds": round(now-started, 3),
                        "cpu_seconds": round(time.thread_time()-cpu_started, 4),
                        "total_spikes": total, "input_spikes": input_total,
                        "downstream_spikes": total-input_total,
                        "neurons_that_spiked": int(np.count_nonzero(model.spike_counts)),
                        "nodes": nodes, "readouts": readouts, "history": list(history),
                    })
                    next_publish = now+.1
        except Exception as exc:
            self._publish({"status": "error", "error": str(exc)})
