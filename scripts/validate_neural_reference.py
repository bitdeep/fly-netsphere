"""Bounded numerical comparison against Brian2 and real-graph intervention trials."""
import argparse
import json
from pathlib import Path
import resource
import time
from types import SimpleNamespace

import numpy as np

from fetch_neural_reference import sha256
from neural_reference import CACHE, Graph, LIF, PARAMETERS, poisson_events


def fixture_graph(n=12):
    pre = np.array([0, 0, 1, 1, 2, 3, 3, 4, 5, 6, 7, 9], dtype=np.int64)
    post = np.array([2, 3, 2, 4, 5, 2, 6, 5, 6, 7, 2, 10], dtype=np.uint32)
    weights = np.array([90, 150, 120, 80, 190, -160, -60, 180, 140, 120, -95, 110], dtype=np.int32)
    return SimpleNamespace(size=n, ids=np.arange(n), indices=post, counts=weights,
                           indptr=np.concatenate(([0], np.cumsum(np.bincount(pre, minlength=n)))))


def brian_reference(graph, events, inputs, silenced):
    import brian2 as b
    b.prefs.codegen.target = "numpy"
    p = PARAMETERS
    clock = b.Clock(dt=p.dt_ms*b.ms)
    neurons = b.NeuronGroup(
        graph.size,
        """dv/dt = (-52*mV - v + g)/(20*ms) : volt (unless refractory)
           dg/dt = -g/(5*ms) : volt (unless refractory)
           rfc : second""",
        threshold="v > -45*mV", reset="v = -52*mV; g = 0*mV",
        refractory="rfc", method="linear", clock=clock)
    neurons.v = -52*b.mV
    neurons.g = 0*b.mV
    neurons.rfc = 2.2*b.ms
    neurons.rfc[np.array(inputs, dtype=np.int64)] = 0*b.ms
    pre = np.repeat(np.arange(graph.size), np.diff(graph.indptr).astype(np.int64))
    synapses = b.Synapses(neurons, neurons, "w : volt", on_pre="g += w",
                         delay=1.8*b.ms, clock=clock)
    synapses.connect(i=pre, j=np.asarray(graph.indices, dtype=np.int32))
    weights = graph.counts.astype(np.float64)*.275
    weights[np.isin(pre, silenced)] = 0
    synapses.w = weights*b.mV
    table = np.zeros((len(events), graph.size))
    for tick, indices in enumerate(events):
        table[tick, indices] = 1
    neurons.namespace["injected"] = b.TimedArray(table, dt=clock.dt)
    drive = neurons.run_regularly("v += injected(t, i)*68.75*mV",
                                  when="synapses", order=0)
    states = b.StateMonitor(neurons, ["v", "g"], record=True, when="end", clock=clock)
    spikes = b.SpikeMonitor(neurons)
    network = b.Network(neurons, synapses, drive, states, spikes)
    network.run(len(events)*clock.dt)
    return (np.asarray(states.v/b.mV).T, np.asarray(states.g/b.mV).T,
            np.rint(np.asarray(spikes.t/b.ms)/p.dt_ms).astype(int),
            np.asarray(spikes.i).astype(int), b.__version__)


def compare(graph, events, inputs, silenced=()):
    ref_v, ref_g, ref_t, ref_i, version = brian_reference(graph, events, inputs, silenced)
    model = LIF(graph, inputs, silenced)
    vs, gs, ticks, indices = [], [], [], []
    for tick, external in enumerate(events):
        spikes = model.step(external)
        vs.append(model.v.copy())
        gs.append(model.g.copy())
        ticks.extend([tick]*len(spikes))
        indices.extend(spikes)
    error_v = float(np.max(np.abs(ref_v-np.array(vs))))
    error_g = float(np.max(np.abs(ref_g-np.array(gs))))
    np.testing.assert_allclose(vs, ref_v, rtol=0, atol=1e-8)
    np.testing.assert_allclose(gs, ref_g, rtol=0, atol=1e-8)
    np.testing.assert_array_equal(ticks, ref_t)
    np.testing.assert_array_equal(indices, ref_i)
    # Incremental API boundaries must not reset refractoriness or delayed spikes.
    continued = LIF(graph, inputs, silenced)
    for chunk in np.array_split(np.arange(len(events)), 7):
        continued.advance([events[tick] for tick in chunk])
    np.testing.assert_array_equal(continued.v, model.v)
    np.testing.assert_array_equal(continued.g, model.g)
    np.testing.assert_array_equal(continued.spike_counts, model.spike_counts)
    dense = LIF(graph, inputs, silenced, sparse=False)
    dense.advance(events)
    np.testing.assert_array_equal(dense.v, model.v)
    np.testing.assert_array_equal(dense.g, model.g)
    return {"brian2": version, "steps": len(events), "spikes": len(ticks),
            "max_v_error_mv": error_v, "max_g_error_mv": error_g,
            "spike_times_identical": True, "chunked_and_dense_identical": True}


def full_trial(graph, mode, ticks=1500):
    inputs = graph.manifest["inputs"]
    model = LIF(graph, inputs, inputs if mode == "blocked" else ())
    events = poisson_events(inputs, ticks, rate_hz=0 if mode == "baseline" else 150,
                            stimulus_ticks=1000)
    start = time.monotonic()
    cpu = time.process_time()
    for external in events:
        model.step(external)
        if time.monotonic()-start > 90:
            raise RuntimeError("Reference trial exceeded its 90-second wall ceiling")
    noninput = model.spike_counts.copy()
    noninput[inputs] = 0
    readouts = {item["label"]: int(model.spike_counts[item["index"]])
                for item in graph.manifest["readouts"]}
    return {"mode": mode, "simulated_ms": ticks*PARAMETERS.dt_ms,
            "stimulus_ms": 100, "wall_seconds": time.monotonic()-start,
            "cpu_seconds": time.process_time()-cpu,
            "total_spikes": int(model.spike_counts.sum()),
            "downstream_spikes": int(noninput.sum()),
            "neurons_that_spiked": int(np.count_nonzero(model.spike_counts)),
            "readouts": readouts}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", type=Path, default=Path("/out"))
    parser.add_argument("--fixtures-only", action="store_true")
    args = parser.parse_args()
    graph = fixture_graph()
    events = poisson_events([0, 1], 800, rate_hz=220, seed=41)
    # Include exact boundary ticks and convergent excitation/inhibition.
    for tick in [0, 1, 18, 21, 22, 23, 44, 45]:
        events[tick] = np.array([0, 1])
    results = [compare(graph, events, [0, 1]), compare(graph, events, [0, 1], [3])]
    print(json.dumps({"numerical_fixtures": results}), flush=True)
    if args.fixtures_only:
        return
    real = Graph(args.cache)
    nodes = [item["index"] for item in real.manifest["diagram"]["nodes"]]
    local = {node: i for i, node in enumerate(nodes)}
    pre, post, weights = [], [], []
    for i, node in enumerate(nodes):
        lo, hi = map(int, real.indptr[node:node+2])
        for target, weight in zip(real.indices[lo:hi], real.counts[lo:hi]):
            if int(target) in local:
                pre.append(i)
                post.append(local[int(target)])
                weights.append(int(weight))
    induced = SimpleNamespace(size=len(nodes), ids=real.ids[nodes],
                              indices=np.array(post, dtype=np.uint32),
                              counts=np.array(weights, dtype=np.int32),
                              indptr=np.concatenate(([0], np.cumsum(np.bincount(pre, minlength=len(nodes))))))
    source_inputs = [local[x] for x in real.manifest["inputs"] if x in local]
    results.append(compare(induced, poisson_events(source_inputs, 800), source_inputs))
    trials = []
    for mode in ("baseline", "stimulus", "blocked"):
        result = full_trial(real, mode)
        trials.append(result)
        print(json.dumps(result), flush=True)
    if trials[0]["total_spikes"] or trials[2]["downstream_spikes"]:
        raise AssertionError("Activity appeared without a transmitted sensory input")
    if not trials[1]["downstream_spikes"]:
        raise AssertionError("No stimulus-driven propagation in the full graph")
    report = {
        "schema": 1, "core_sha256": sha256(Path(__file__).with_name("neural_reference.py")),
        "cache_manifest_sha256": sha256(args.cache/"manifest.json"),
        "numerical_fixtures": results, "full_graph_trials": trials,
        "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
        "body_coupling": "disconnected", "biological_validation": "not established",
    }
    (args.cache/"validation.json").write_text(json.dumps(report, indent=2)+"\n")
    print("Numerical and intervention checks passed", flush=True)


if __name__ == "__main__":
    main()
