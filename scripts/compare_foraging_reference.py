"""Compare the full neural population with Brian2 and independent CSR delivery.

Brian2 integrates the neurons. A separate Python callback delivers delayed edges
using vectorized sums, avoiding the RAM cost of a 14.7-million-edge Synapses object.
This does not benchmark Brian2's Synapses engine or establish behavioral validity.
"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import resource
import time

import numpy as np

from adaptive_neural import Adaptation, AdaptiveLIF
from fetch_neural_reference import sha256
from foraging_feasibility import ANNOTATIONS, SEED, load_groups, source_record
from neural_reference import CACHE, Graph, LIF


def compare(graph, groups, adaptation=None):
    import brian2 as b
    b.prefs.codegen.target = "numpy"
    inputs = np.concatenate((groups["left"], groups["right"]))
    rng = np.random.default_rng(SEED)
    events = []
    for tick in range(3000):
        cohort = groups["left"] if tick < 500 else groups["right"] if tick < 1000 else inputs[:0]
        events.append(cohort[rng.random(len(cohort)) < .001])

    started_cpu, started_wall = time.thread_time(), time.monotonic()
    reference = (LIF(graph, inputs) if adaptation is None
                 else AdaptiveLIF(graph, inputs, adaptation=adaptation))
    expected_ticks, expected_ids = [], []
    for tick, event in enumerate(events):
        spikes = reference.step(event)
        expected_ticks.extend([tick]*len(spikes))
        expected_ids.extend(spikes)
        if (tick+1) % 25 == 0 and (
                len(expected_ids) > 200000 or time.thread_time()-started_cpu > 20
                or time.monotonic()-started_wall > 60):
            raise RuntimeError("NumPy comparison reached its resource limit")
    numpy_cpu = time.thread_time()-started_cpu

    clock = b.Clock(dt=.1*b.ms)
    equations = """dv/dt = (-52*mV - v + g)/(20*ms) : volt (unless refractory)
           dg/dt = -g/(5*ms) : volt (unless refractory)
           rfc : second"""
    if adaptation is not None:
        equations += "\n da/dt = -a/tau : volt\n jump : volt (constant)"
    neurons = b.NeuronGroup(
        graph.size, equations,
        threshold="v > -45*mV" + (" + a" if adaptation is not None else ""),
        reset="v = -52*mV; g = 0*mV" + ("; a += jump" if adaptation is not None else ""),
        refractory="rfc", method="linear", clock=clock,
        namespace={} if adaptation is None else {"tau": adaptation.tau_ms*b.ms})
    neurons.v, neurons.g, neurons.rfc = -52*b.mV, 0*b.mV, 2.2*b.ms
    neurons.rfc[inputs] = 0*b.ms
    if adaptation is not None:
        neurons.a, neurons.jump = 0*b.mV, adaptation.jump_mv*b.mV
        neurons.jump[inputs] = 0*b.mV
    pending = [np.empty(0, dtype=np.int64) for _ in range(19)]
    counter = total = 0
    started_cpu, started_wall = time.thread_time(), time.monotonic()

    @b.network_operation(clock=clock, when="synapses", order=0)
    def deliver():
        nonlocal counter, total
        arriving = pending[counter % 19]
        pending[counter % 19] = np.empty(0, dtype=np.int64)
        if len(arriving):
            edges = np.concatenate([
                np.arange(graph.indptr[i], graph.indptr[i+1], dtype=np.int64)
                for i in arriving])
            # Integer synapse counts are summed before scaling. This deliberately
            # differs from LIF.step's per-source floating-point accumulation.
            drive = np.bincount(graph.indices[edges], weights=graph.counts[edges],
                                minlength=graph.size)*.000275
            eligible = np.asarray(neurons.not_refractory[:])
            neurons.variables["g"].get_value()[eligible] += drive[eligible]
        external = events[counter]
        if len(external):
            # This fixture's externally driven neurons have zero refractoriness.
            neurons.variables["v"].get_value()[external] += .06875
        spikes = neurons.spikes.copy()
        pending[(counter+18) % 19] = spikes
        total += len(spikes)
        counter += 1
        if counter % 25 == 0 and (
                total > 200000 or time.thread_time()-started_cpu > 30
                or time.monotonic()-started_wall > 90):
            raise RuntimeError("Brian2 comparison reached its resource limit")

    monitor = b.SpikeMonitor(neurons)
    network = b.Network(neurons, deliver, monitor)
    network.run(300*b.ms)
    actual_ticks = np.rint(np.asarray(monitor.t/b.ms)/.1).astype(np.int64)
    actual_ids = np.asarray(monitor.i).astype(np.int64)
    report = {
        "schema": 1, "scope": __doc__, "sources": source_record(graph),
        "comparator_sha256": sha256(Path(__file__)),
        "brian_version": b.__version__, "seed": SEED,
        "neuron_count": graph.size, "edge_count": len(graph.indices),
        "duration_ms": 300, "input_hz": 10,
        "segments_ms": [["left", 50], ["right", 50], ["none", 200]],
        "numpy_cpu_seconds": numpy_cpu,
        "brian_cpu_seconds": time.thread_time()-started_cpu,
        "brian_wall_seconds": time.monotonic()-started_wall,
        "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
        "expected_spikes": len(expected_ids), "brian_spikes": len(actual_ids),
        "exact_spike_ids": bool(np.array_equal(actual_ids, expected_ids)),
        "exact_spike_ticks": bool(np.array_equal(actual_ticks, expected_ticks)),
        "max_v_error_mv": float(np.max(np.abs(neurons.v[:]/b.mV-reference.v))),
        "max_g_error_mv": float(np.max(np.abs(neurons.g[:]/b.mV-reference.g))),
        "brian_50ms_bins": np.bincount(actual_ticks//500, minlength=6).tolist(),
        "adaptation": None if adaptation is None else asdict(adaptation),
    }
    if adaptation is not None:
        report["adaptive_core_sha256"] = sha256(Path(__file__).with_name("adaptive_neural.py"))
        report["max_a_error_mv"] = float(np.max(np.abs(neurons.a[:]/b.mV-reference.a)))
    report["numerical_agreement"] = (
        report["exact_spike_ids"] and report["exact_spike_ticks"]
        and report["max_v_error_mv"] <= 1e-8 and report["max_g_error_mv"] <= 1e-8
        and report.get("max_a_error_mv", 0) <= 1e-8)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", type=Path, default=ANNOTATIONS)
    parser.add_argument("--cache", type=Path, default=CACHE)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--adaptive", action="store_true",
                        help="Compare the screened 5 mV / 500 ms experimental variant")
    args = parser.parse_args()
    graph = Graph(args.cache)
    groups, _ = load_groups(graph, annotations=args.annotations)
    report = compare(graph, groups, Adaptation(5., 500.) if args.adaptive else None)
    args.output.write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report), flush=True)
    if not report["numerical_agreement"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
