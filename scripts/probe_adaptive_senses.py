"""Bounded adaptive full-graph sensory screen, separate from the live animal."""
import argparse
from dataclasses import asdict
from functools import partial
import json
from pathlib import Path
import resource

from adaptive_neural import Adaptation, AdaptiveLIF
from fetch_neural_reference import sha256
from foraging_feasibility import (
    ANNOTATIONS, CPU_LIMIT, WALL_LIMIT, SPIKE_LIMIT, SEED,
    load_groups, run_case, source_record,
)
from neural_reference import CACHE, Graph

VARIANTS = ((1., 100.), (5., 100.), (5., 500.), (20., 200.))


def assess(result):
    """Declared screening criteria, not a biological or foraging acceptance gate."""
    bins = result["bins"]
    if result["limit"] is not None or len(bins) != 8:
        return {"completed": False, "recovered": False, "directional_pairs": []}
    downstream = [b["spikes"]-b["input_spikes"] for b in bins]
    recovered = downstream[-1] <= max(5, .05*max(downstream[:4]))
    # Require a measurable sign reversal, using the last 100 ms of each cue.
    # Readout definitions and 3-spike floor are fixed before screening.
    pairs = sorted({name.rsplit(":", 1)[0] for name in bins[1]["readouts"]})
    directional = []
    for pair in pairs:
        signals = []
        for item in (bins[1], bins[3]):
            left, right = (item["readouts"][pair+":"+side] for side in ("left", "right"))
            toward = left-right if item["input_side"] == "left" else right-left
            signals.append(left+right >= 3 and toward > 0)
        if all(signals):
            directional.append(pair)
    return {"completed": True, "recovered": recovered,
            "last_100ms_downstream": downstream[-1],
            "peak_driven_100ms_downstream": max(downstream[:4]),
            "directional_pairs": directional}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=CACHE)
    parser.add_argument("--annotations", type=Path, default=ANNOTATIONS)
    parser.add_argument("--variant", type=int, choices=range(len(VARIANTS)))
    parser.add_argument("--confirm", action="store_true",
                        help="Three seeds, both cue orders, and zero/blocked controls")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.confirm and args.variant is None:
        parser.error("--confirm requires a single --variant")
    graph = Graph(args.cache)
    groups, readouts = load_groups(graph, annotations=args.annotations)
    results = []
    for index in range(len(VARIANTS)) if args.variant is None else (args.variant,):
        adaptation = Adaptation(*VARIANTS[index])
        factory = partial(AdaptiveLIF, adaptation=adaptation)
        cases = [(SEED, ("left", "right"), 50, False)]
        if args.confirm:
            cases = [(seed, order, 50, False)
                     for seed in (SEED, SEED+1, SEED+2)
                     for order in (("left", "right"), ("right", "left"))]
            cases += [(SEED, ("left", "right"), 0, False),
                      (SEED, ("left", "right"), 50, True)]
        for seed, order, hz, blocked in cases:
            result = run_case(graph, groups, readouts, hz, blocked,
                              factory=factory, seed=seed, order=order)
            result.update(variant=index, adaptation=asdict(adaptation),
                          assessment=assess(result))
            results.append(result)
            print(json.dumps({k: v for k, v in result.items() if k != "bins"}), flush=True)
    driven = [r for r in results if r["hz"] and not r["blocked"]]
    common_pairs = set.intersection(*(set(r["assessment"]["directional_pairs"]) for r in driven))
    controls = [r for r in results if not r["hz"] or r["blocked"]]
    controls_passed = (all(r["limit"] is None and r["downstream_spikes"] == 0
                           and (r["hz"] != 0 or r["total_spikes"] == 0) for r in controls)
                       if controls else None)
    report = {
        "schema": 1, "scope": "Experimental odor screen; no learned motor or body coupling",
        "sources": source_record(graph),
        "experimental_sources": {name: sha256(Path(__file__).with_name(name)) for name in (
            "adaptive_neural.py", "probe_adaptive_senses.py")},
        "neuron_count": graph.size, "edge_count": len(graph.indices),
        "input_ids": {k: [str(graph.ids[i]) for i in v] for k, v in groups.items()},
        "readout_ids": {k: [str(graph.ids[i]) for i in v] for k, v in readouts.items()},
        "variants": [asdict(Adaptation(*v)) for v in VARIANTS],
        "segments_ms": [200, 200, 400], "confirm": args.confirm,
        "recovery_criterion": "last 100 ms downstream <= max(5, 5% peak driven 100 ms)",
        "direction_criterion": "ipsilateral sign and >=3 pair spikes in each late cue bin",
        "per_case_limits": {"cpu_seconds": CPU_LIMIT, "wall_seconds": WALL_LIMIT,
                            "spikes": SPIKE_LIMIT},
        "results": results,
        "measurement_completed": all(r["limit"] is None for r in results),
        "controls_passed": controls_passed,
        "common_directional_pairs": sorted(common_pairs),
        "confirmation_passed": bool(args.confirm and controls_passed and common_pairs
                                   and all(r["assessment"]["recovered"] for r in driven)),
        "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
    }
    args.output.write_text(json.dumps(report, indent=2)+"\n")
    # Successful execution can document a rejected candidate; the behavioral
    # decision is explicit in confirmation_passed, not inferred from exit status.
    if any(r["limit"] for r in results) or controls_passed is False:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
