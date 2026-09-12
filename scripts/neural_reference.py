"""Incremental LIF reference using all published FlyWire 630 signed connections.

Parameters/equations: Shiu & Spiller, MIT-licensed Drosophila_brain_model.
Integration is analytic, with Brian2's groups/thresholds/synapses/resets order.
This models neural responses; it has no authority over a physical actuator.
"""
from dataclasses import dataclass
import json
from pathlib import Path

import numpy as np

from fetch_neural_reference import sha256

ROOT = Path(__file__).resolve().parents[1]
CACHE = ROOT/"out/neural-reference"


@dataclass(frozen=True)
class Parameters:
    dt_ms: float = .1
    rest_mv: float = -52.
    threshold_mv: float = -45.
    membrane_ms: float = 20.
    synapse_ms: float = 5.
    refractory_ms: float = 2.2
    delay_ms: float = 1.8
    synapse_mv: float = .275
    input_scale: float = 250.


PARAMETERS = Parameters()


class Graph:
    def __init__(self, directory=CACHE):
        self.manifest = json.loads((directory/"manifest.json").read_text())
        if self.manifest["schema"] != 1:
            raise ValueError("Unsupported neural cache")
        for name, item in self.manifest["files"].items():
            if (directory/name).stat().st_size != item["bytes"] or sha256(directory/name) != item["sha256"]:
                raise ValueError(f"Neural cache checksum mismatch: {name}")
        self.ids, self.indptr, self.indices, self.counts = (
            np.load(directory/name, mmap_mode="r", allow_pickle=False)
            for name in ("ids.npy", "indptr.npy", "indices.npy", "counts.npy"))
        self.size = len(self.ids)
        if (self.size != self.manifest["neuron_count"]
                or len(self.indices) != self.manifest["edge_count"]
                or len(self.counts) != len(self.indices) or int(self.indptr[-1]) != len(self.indices)):
            raise ValueError("Invalid neural graph dimensions")


class LIF:
    """A trial owns dynamic state; read-only connectivity can be shared."""
    def __init__(self, graph, inputs=(), silenced=(), parameters=PARAMETERS, sparse=True):
        self.graph, self.parameters = graph, parameters
        n, p = graph.size, parameters
        self.v = np.full(n, p.rest_mv, dtype=np.float64)
        self.g = np.zeros(n, dtype=np.float64)
        self.last_spike = np.full(n, -1000000, dtype=np.int64)
        self.refractory = np.full(n, round(p.refractory_ms/p.dt_ms), dtype=np.int64)
        self.inputs = np.asarray(inputs, dtype=np.int64)
        self.refractory[self.inputs] = 0
        self.silenced = np.zeros(n, dtype=bool)
        self.silenced[np.asarray(silenced, dtype=np.int64)] = True
        self.delay = round(p.delay_ms/p.dt_ms)
        self.pending = [np.empty(0, dtype=np.int64) for _ in range(self.delay+1)]
        self.tick = 0
        self.spike_counts = np.zeros(n, dtype=np.uint32)
        self.visited = np.zeros(n, dtype=bool)
        self.active = np.arange(n, dtype=np.int64) if not sparse else self.inputs.copy()
        self.visited[self.active] = True
        self.alpha = np.exp(-p.dt_ms/p.membrane_ms)
        self.beta = np.exp(-p.dt_ms/p.synapse_ms)
        self.coupling = p.synapse_ms/(p.membrane_ms-p.synapse_ms)*(self.alpha-self.beta)

    def _activate(self, indices):
        new = np.unique(indices[~self.visited[indices]])
        if len(new):
            self.visited[new] = True
            self.active = np.concatenate((self.active, new))

    def step(self, external=()):
        p, tick = self.parameters, self.tick
        eligible = self.active[(tick-self.last_spike[self.active]) >= self.refractory[self.active]]
        # Neurons never reached by an input are exactly at equilibrium, so omitting
        # their arithmetic removes no connection, neuron or nonzero dynamic state.
        self.v[eligible] = (p.rest_mv+(self.v[eligible]-p.rest_mv)*self.alpha
                            + self.g[eligible]*self.coupling)
        self.g[eligible] *= self.beta
        spikes = np.sort(eligible[self.v[eligible] > p.threshold_mv])
        self.last_spike[spikes] = tick
        self.spike_counts[spikes] += 1
        slot = tick % len(self.pending)
        arriving = self.pending[slot]
        self.pending[slot] = np.empty(0, dtype=np.int64)
        for source in arriving:
            if self.silenced[source]:
                continue
            start, end = map(int, self.graph.indptr[source:source+2])
            targets = self.graph.indices[start:end]
            receiving = (tick-self.last_spike[targets]) >= self.refractory[targets]
            targets = targets[receiving]
            weights = self.graph.counts[start:end][receiving]
            nonzero = weights != 0
            targets, weights = targets[nonzero], weights[nonzero]
            if len(targets):
                np.add.at(self.g, targets, weights*p.synapse_mv)
                self._activate(targets)
        incoming = np.asarray(external, dtype=np.int64)
        if len(incoming):
            permitted = (tick-self.last_spike[incoming]) >= self.refractory[incoming]
            incoming = incoming[permitted]
            self.v[incoming] += p.synapse_mv*p.input_scale
            self._activate(incoming)
        self.v[spikes] = p.rest_mv
        self.g[spikes] = 0.
        self.pending[(tick+self.delay) % len(self.pending)] = spikes
        self.tick += 1
        return spikes

    def advance(self, input_events):
        return [self.step(event) for event in input_events]


def poisson_events(inputs, ticks, rate_hz=150., seed=20260912, stimulus_ticks=None):
    """N=1 PoissonInput uses one Bernoulli draw per neuron per 0.1 ms step."""
    rng = np.random.default_rng(seed)
    inputs = np.asarray(inputs, dtype=np.int64)
    duration = ticks if stimulus_ticks is None else stimulus_ticks
    return [inputs[rng.random(len(inputs)) < rate_hz*PARAMETERS.dt_ms/1000]
            if tick < duration else np.empty(0, dtype=np.int64)
            for tick in range(ticks)]
