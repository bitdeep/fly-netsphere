"""Experimental spike-triggered threshold adaptation; no actuator authority.

This is an engineering hypothesis, not a fitted Drosophila neuron model.
The published LIF core, graph weights, delays and sensory encoder are unchanged.
For non-input neurons: da/dt = -a/tau; threshold = threshold_mv + a;
each spike adds jump_mv to a after the threshold/reset phase. Adaptation decays
even during refractoriness. Externally encoded sensory neurons do not adapt.
"""
from dataclasses import dataclass
import math

import numpy as np

from neural_reference import LIF, PARAMETERS


@dataclass(frozen=True)
class Adaptation:
    jump_mv: float = 5.
    tau_ms: float = 100.

    def __post_init__(self):
        if not math.isfinite(self.jump_mv) or not 0 <= self.jump_mv <= 20:
            raise ValueError("Adaptation jump must be finite and within 0–20 mV")
        if not math.isfinite(self.tau_ms) or not 1 <= self.tau_ms <= 1000:
            raise ValueError("Adaptation decay must be finite and within 1–1000 ms")


class AdaptiveLIF(LIF):
    def __init__(self, graph, inputs=(), silenced=(), parameters=PARAMETERS,
                 sparse=True, adaptation=Adaptation()):
        super().__init__(graph, inputs, silenced, parameters, sparse)
        self.adaptation = adaptation
        self.a = np.zeros(graph.size, dtype=np.float64)
        self.jump = np.full(graph.size, adaptation.jump_mv, dtype=np.float64)
        self.jump[self.inputs] = 0.
        self.adaptation_decay = np.exp(-parameters.dt_ms/adaptation.tau_ms)

    def step(self, external=()):
        p, tick = self.parameters, self.tick
        self.a[self.active] *= self.adaptation_decay
        eligible = self.active[(tick-self.last_spike[self.active]) >= self.refractory[self.active]]
        self.v[eligible] = (p.rest_mv+(self.v[eligible]-p.rest_mv)*self.alpha
                            + self.g[eligible]*self.coupling)
        self.g[eligible] *= self.beta
        spikes = np.sort(eligible[self.v[eligible] > p.threshold_mv+self.a[eligible]])
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
        self.a[spikes] += self.jump[spikes]
        self.pending[(tick+self.delay) % len(self.pending)] = spikes
        self.tick += 1
        return spikes
