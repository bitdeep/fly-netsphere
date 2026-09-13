"""Bounded sensory feasibility measurements; no body or live-service authority."""
import argparse
import ast
import csv
import json
from pathlib import Path
import resource
import time
import urllib.request

import numpy as np

from fetch_neural_reference import sha256
from neural_reference import CACHE, Graph, LIF, PARAMETERS

ROOT = Path(__file__).resolve().parents[1]
ANNOTATIONS = ROOT/"data/neural-reference/walking-annotations-630.tsv"
ANNOTATION_COMMIT = "df6bb136f5b3d91c3992df4e8de2642329e2a384"
ANNOTATION_URL = (
    "https://raw.githubusercontent.com/flyconnectome/flywire_annotations/"
    f"{ANNOTATION_COMMIT}/supplemental_files/Supplemental_file1_annotations.tsv")
ANNOTATION_BYTES = 21714061
ANNOTATION_SHA256 = "55c99c61eecf8db6cc36f1a684b35e4c4208afbab02197d753ccc8dc2a6e2e76"
SEED = 20260913
TICKS = 8000
CPU_LIMIT, WALL_LIMIT, SPIKE_LIMIT = 20., 60., 200000


def verify_annotations(path):
    if path.stat().st_size != ANNOTATION_BYTES or sha256(path) != ANNOTATION_SHA256:
        raise ValueError("Sensory annotation source checksum mismatch")


def fetch_annotations(path):
    """Explicit data download, capped in size and rate; never execute its contents."""
    if path.exists():
        verify_annotations(path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    pending = path.with_suffix(".part")
    if pending.exists():
        raise FileExistsError("A pending annotation download already exists")
    started, total = time.monotonic(), 0
    with urllib.request.urlopen(ANNOTATION_URL, timeout=20) as response, pending.open("xb") as stream:
        while block := response.read(256*1024):
            total += len(block)
            if total > ANNOTATION_BYTES:
                raise ValueError("Annotation download exceeded its byte ceiling")
            stream.write(block)
            time.sleep(max(0, total/(4*1024*1024)-(time.monotonic()-started)))
    verify_annotations(pending)
    pending.rename(path)


def load_groups(graph, family="odor", annotations=ANNOTATIONS):
    """Keep annotation columns distinct; an old hemibrain label is not a cell type."""
    if family not in ("odor", "taste"):
        raise ValueError("Unknown sensory family")
    verify_annotations(annotations)
    lookup = {int(identifier): i for i, identifier in enumerate(graph.ids)}
    groups, readouts = {"left": [], "right": []}, {}
    with annotations.open() as stream:
        for row in csv.DictReader(stream, delimiter="\t"):
            identifier = int(row["root_id"])
            if identifier not in lookup:
                continue
            side = row["side"]
            if row["hemibrain_type"] in ("ORN_DM1", "ORN_VA2"):
                groups[side].append(lookup[identifier])
            if (row["cell_type"] in ("DNa01", "DNae003", "DNpe060")
                    or row["hemibrain_type"] in ("DNa02", "DNp09")):
                name = (row["cell_type"] or "hemibrain:"+row["hemibrain_type"])+":"+side
                readouts.setdefault(name, []).append(lookup[identifier])
    if tuple(map(len, (groups["left"], groups["right"]))) != (69, 66):
        raise ValueError("Olfactory cohorts differ from the pinned graph/annotations")
    if len(readouts) != 10 or any(len(v) != 1 for v in readouts.values()):
        raise ValueError("Candidate descending readouts are missing or ambiguous")
    if family == "taste":
        notebook = ROOT/"data/neural-reference/figures.ipynb"
        if sha256(notebook) != graph.manifest["source_files"]["figures.ipynb"]["sha256"]:
            raise ValueError("Taste notebook checksum mismatch")
        found = {}
        for cell in json.loads(notebook.read_text())["cells"]:
            if cell["cell_type"] != "code":
                continue
            for node in ast.parse("".join(cell["source"])).body:
                if not isinstance(node, ast.Assign):
                    continue
                for target in node.targets:
                    if not isinstance(target, ast.Name) or target.id not in (
                            "neu_sugar", "neu_sugar_left", "ids_mn9"):
                        continue
                    value = ast.literal_eval(node.value)
                    if (not isinstance(value, list) or not all(type(i) is int for i in value)
                            or target.id in found and found[target.id] != value):
                        raise ValueError("Ambiguous published taste identifiers")
                    found[target.id] = value
        if [len(found.get(k, [])) for k in ("neu_sugar_left", "neu_sugar", "ids_mn9")] != [10, 21, 2]:
            raise ValueError("Published bilateral taste groups are missing")
        sugar_ids = set(found["neu_sugar_left"]+found["neu_sugar"])
        if len(sugar_ids) != 31:
            raise ValueError("Published taste cohorts overlap or contain duplicates")
        groups = {"left": [], "right": []}
        # The notebook's hemisphere labels oppose the annotation's sensory
        # nerve-entry sides. Use annotation sides consistently for inputs/outputs.
        # Notebook MN9 list order likewise does not establish anatomical side.
        with annotations.open() as stream:
            for row in csv.DictReader(stream, delimiter="\t"):
                identifier = int(row["root_id"])
                if identifier in sugar_ids:
                    if row["side"] not in groups:
                        raise ValueError("Published sugar neuron has no annotated side")
                    groups[row["side"]].append(lookup[identifier])
                if identifier not in found["ids_mn9"]:
                    continue
                side = row["side"]
                if side not in groups or "MN9:"+side in readouts:
                    raise ValueError("Published MN9 sides are missing or ambiguous")
                readouts["MN9:"+side] = [lookup[identifier]]
        if not all("MN9:"+side in readouts for side in groups):
            raise ValueError("Published MN9 neurons are missing from the annotations")
        if (len(groups["left"]), len(groups["right"])) != (21, 10):
            raise ValueError("Taste cohort sides differ from the pinned annotations")
    groups = {side: np.asarray(sorted(ids), dtype=np.int64) for side, ids in groups.items()}
    if len(np.unique(np.concatenate(list(groups.values())))) != sum(map(len, groups.values())):
        raise ValueError("Sensory groups overlap or contain duplicate identifiers")
    return groups, readouts


def source_record(graph):
    return {
        "annotation_commit": ANNOTATION_COMMIT,
        "annotation_sha256": ANNOTATION_SHA256,
        "annotation_url": ANNOTATION_URL,
        "graph_commit": graph.manifest["reference_commit"],
        "graph_files": graph.manifest["files"],
        "core_sha256": sha256(Path(__file__).with_name("neural_reference.py")),
        "probe_sha256": sha256(Path(__file__)),
    }


def run_case(graph, groups, readouts, hz, blocked=False, *, factory=LIF,
             seed=SEED, order=("left", "right")):
    inputs = np.concatenate((groups["left"], groups["right"]))
    brain = factory(graph, inputs, inputs if blocked else ())
    rng = np.random.default_rng(seed)
    started_cpu, started_wall = time.thread_time(), time.monotonic()
    result = {"hz": hz, "blocked": blocked, "seed": seed, "order": list(order),
              "bins": [], "limit": None}
    previous = np.zeros(graph.size, dtype=np.uint32)
    total = 0
    for tick in range(TICKS):
        side = order[0] if tick < 2000 else order[1] if tick < 4000 else "none"
        events = (groups[side][rng.random(len(groups[side])) < hz*PARAMETERS.dt_ms/1000]
                  if side != "none" else ())
        total += len(brain.step(events))
        if (tick+1) % 1000 == 0:
            delta = brain.spike_counts-previous
            result["bins"].append({
                "end_ms": (tick+1)*PARAMETERS.dt_ms, "input_side": side,
                "spikes": int(delta.sum()), "input_spikes": int(delta[inputs].sum()),
                "readouts": {k: int(delta[v].sum()) for k, v in readouts.items()},
            })
            previous[:] = brain.spike_counts
        if (tick+1) % 25 == 0:
            for label, actual, limit in (
                    ("cpu", time.thread_time()-started_cpu, CPU_LIMIT),
                    ("wall", time.monotonic()-started_wall, WALL_LIMIT),
                    ("spikes", total, SPIKE_LIMIT)):
                if actual >= limit:
                    result["limit"] = label
                    break
            if result["limit"]:
                break
    result.update(
        simulated_ms=brain.tick*PARAMETERS.dt_ms, total_spikes=total,
        downstream_spikes=total-int(brain.spike_counts[inputs].sum()),
        cpu_seconds=time.thread_time()-started_cpu,
        wall_seconds=time.monotonic()-started_wall, active_neurons=len(brain.active),
        final_readouts={k: int(brain.spike_counts[v].sum()) for k, v in readouts.items()},
    )
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--family", choices=("odor", "taste"), default="odor")
    parser.add_argument("--annotations", type=Path, default=ANNOTATIONS)
    parser.add_argument("--fetch-annotations", action="store_true")
    parser.add_argument("--cache", type=Path, default=CACHE)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.fetch_annotations:
        fetch_annotations(args.annotations)
    graph = Graph(args.cache)
    groups, readouts = load_groups(graph, args.family, args.annotations)
    report = {
        "schema": 1, "scope": "Bounded sensory feasibility; no body coupling or foraging acceptance",
        "sources": source_record(graph), "family": args.family, "seed": SEED,
        "neuron_count": graph.size, "edge_count": len(graph.indices),
        "input_column": "hemibrain_type" if args.family == "odor" else "notebook literals",
        "input_ids": {k: [str(graph.ids[i]) for i in v] for k, v in groups.items()},
        "readout_ids": {k: [str(graph.ids[i]) for i in v] for k, v in readouts.items()},
        "segments_ms": [["left", 200], ["right", 200], ["none", 400]],
        "per_case_limits": {"cpu_seconds": CPU_LIMIT, "wall_seconds": WALL_LIMIT,
                            "spikes": SPIKE_LIMIT},
        "results": [],
    }
    for hz, blocked in ((0, False), (10, False), (50, False), (150, False), (50, True)):
        result = run_case(graph, groups, readouts, hz, blocked)
        report["results"].append(result)
        print(json.dumps({k: v for k, v in result.items() if k != "bins"}), flush=True)
    report["controls_passed"] = (
        report["results"][0]["total_spikes"] == 0
        and report["results"][-1]["downstream_spikes"] == 0
        and report["results"][0]["limit"] is None
        and report["results"][-1]["limit"] is None)
    report["all_cases_completed"] = all(r["limit"] is None for r in report["results"])
    report["peak_rss_mib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024
    args.output.write_text(json.dumps(report, indent=2)+"\n")
    # Writing a report, including negative evidence, does not mean the cases passed.
    if not report["controls_passed"] or not report["all_cases_completed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
