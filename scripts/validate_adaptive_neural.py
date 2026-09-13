"""Independent Brian2 fixtures for the experimental adaptive threshold model."""
import argparse
from dataclasses import asdict
import json
from pathlib import Path

import numpy as np

from adaptive_neural import Adaptation, AdaptiveLIF
from fetch_neural_reference import sha256
from neural_reference import LIF, poisson_events
from validate_neural_reference import fixture_graph


def compare(adaptation, silenced=()):
    import brian2 as b
    b.prefs.codegen.target = "numpy"
    graph, inputs = fixture_graph(), np.array([0, 1])
    events = poisson_events(inputs, 2000, rate_hz=220, seed=41, stimulus_ticks=1000)
    for tick in [0, 1, 18, 21, 22, 23, 44, 45]:
        events[tick] = inputs
    clock = b.Clock(dt=.1*b.ms)
    neurons = b.NeuronGroup(
        graph.size,
        """dv/dt = (-52*mV - v + g)/(20*ms) : volt (unless refractory)
           dg/dt = -g/(5*ms) : volt (unless refractory)
           da/dt = -a/tau : volt
           jump : volt (constant)
           rfc : second (constant)""",
        threshold="v > -45*mV + a", reset="v = -52*mV; g = 0*mV; a += jump",
        refractory="rfc", method="linear", clock=clock,
        namespace={"tau": adaptation.tau_ms*b.ms})
    neurons.v, neurons.g, neurons.a = -52*b.mV, 0*b.mV, 0*b.mV
    neurons.jump, neurons.rfc = adaptation.jump_mv*b.mV, 2.2*b.ms
    neurons.jump[inputs], neurons.rfc[inputs] = 0*b.mV, 0*b.ms
    pre = np.repeat(np.arange(graph.size), np.diff(graph.indptr).astype(np.int64))
    synapses = b.Synapses(neurons, neurons, "w : volt", on_pre="g += w",
                         delay=1.8*b.ms, clock=clock)
    synapses.connect(i=pre, j=graph.indices.astype(np.int32))
    weights = graph.counts.astype(np.float64)*.275
    weights[np.isin(pre, silenced)] = 0
    synapses.w = weights*b.mV
    table = np.zeros((len(events), graph.size))
    for tick, event in enumerate(events):
        table[tick, event] = 1
    neurons.namespace["injected"] = b.TimedArray(table, dt=clock.dt)
    drive = neurons.run_regularly("v += injected(t, i)*68.75*mV", when="synapses", order=0)
    states = b.StateMonitor(neurons, ["v", "g", "a"], record=True, when="end", clock=clock)
    monitor = b.SpikeMonitor(neurons)
    b.Network(neurons, synapses, drive, states, monitor).run(len(events)*clock.dt)
    brain = AdaptiveLIF(graph, inputs, silenced, adaptation=adaptation)
    expected = {key: [] for key in ("v", "g", "a")}
    ticks, ids = [], []
    original = LIF(graph, inputs, silenced) if adaptation.jump_mv == 0 else None
    for tick, event in enumerate(events):
        spikes = brain.step(event)
        ticks.extend([tick]*len(spikes))
        ids.extend(spikes)
        for key in expected:
            expected[key].append(getattr(brain, key).copy())
        if original is not None:
            np.testing.assert_array_equal(original.step(event), spikes)
            for key in ("v", "g", "last_spike"):
                np.testing.assert_array_equal(getattr(brain, key), getattr(original, key))
    errors = {}
    for key, values in expected.items():
        actual = np.asarray(getattr(states, key)/b.mV).T
        np.testing.assert_allclose(values, actual, rtol=0, atol=1e-8)
        errors[key] = float(np.max(np.abs(values-actual)))
    np.testing.assert_array_equal(ids, np.asarray(monitor.i))
    np.testing.assert_array_equal(ticks, np.rint(monitor.t/b.ms/.1).astype(int))
    for dense in (False, True):
        continued = AdaptiveLIF(graph, inputs, silenced, sparse=not dense, adaptation=adaptation)
        for chunk in np.array_split(np.arange(len(events)), 7):
            continued.advance([events[t] for t in chunk])
        for key in ("v", "g", "a", "last_spike", "spike_counts"):
            np.testing.assert_array_equal(getattr(continued, key), getattr(brain, key))
        for actual, expected_queue in zip(continued.pending, brain.pending):
            np.testing.assert_array_equal(actual, expected_queue)
    if adaptation.jump_mv and not np.max(states.a/b.mV) > adaptation.jump_mv:
        raise AssertionError("Fixture failed to exercise accumulating adaptation")
    return {"adaptation": asdict(adaptation), "silenced": list(silenced),
            "spikes": len(ids), "brian_version": b.__version__, "max_error_mv": errors,
            "exact_spike_ids_and_ticks": True, "chunked_and_dense_identical": True,
            "zero_adaptation_matches_original": original is not None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results = [compare(Adaptation(jump, tau), silenced) for jump, tau, silenced in (
        (0., 100., ()), (1., 100., ()), (5., 100., ()),
        (5., 500., ()), (20., 200., ()), (5., 100., (3,)))]
    report = {"scope": __doc__, "passed": True, "fixtures": results,
              "sources": {name: sha256(Path(__file__).with_name(name)) for name in (
                  "adaptive_neural.py", "neural_reference.py", "validate_adaptive_neural.py",
                  "validate_neural_reference.py")}}
    args.output.write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report), flush=True)


if __name__ == "__main__":
    main()
