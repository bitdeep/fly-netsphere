"""Stream the entire published FlyWire 630 graph into compact immutable CSR files."""
import argparse
import csv
import json
from pathlib import Path
import resource
import time

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

from fetch_neural_reference import COMMIT, antennal_identifiers, sha256

COLUMNS = ["Presynaptic_Index", "Postsynaptic_Index", "Excitatory x Connectivity"]


def prepare(source, destination):
    started = time.monotonic()
    destination.mkdir(parents=True, exist_ok=True)
    provenance = json.loads((source/"sources.json").read_text())
    if provenance["reference_commit"] != COMMIT:
        raise ValueError("Unexpected reference commit")
    for item in provenance["files"].values():
        if sha256(source/item["local_name"]) != item["sha256"]:
            raise ValueError("Reference data checksum mismatch")
    with (source/"2023_03_23_completeness_630_final.csv").open() as stream:
        reader = csv.reader(stream)
        next(reader)
        ids = np.fromiter((int(row[0]) for row in reader), dtype=np.uint64)
    count = len(ids)
    if not 100000 < count < 200000 or len(np.unique(ids)) != count:
        raise ValueError("Unexpected neuron universe")
    id_to_index = {int(value): i for i, value in enumerate(ids)}
    protocol = antennal_identifiers(source/"figures.ipynb")
    groups = {key: [id_to_index[x] for x in protocol[key]]
              for key in ("neu_JON_CE", "neu_JON_F", "neu_JON_D_m")}
    readouts = [
        {"index": id_to_index[protocol[key]], "id": str(protocol[key]), "label": label, "role": role}
        for key, label, role in [
            ("id_aBN1", "aBN1", "interneuron"),
            ("id_DN1_1", "aDN1", "descending"),
            ("id_DN2_l", "aDN2", "descending"),
        ]
    ]
    inputs = sorted({x for values in groups.values() for x in values})
    pa.set_cpu_count(1)
    pa.set_io_thread_count(1)
    parquet = pq.ParquetFile(source/"2023_03_23_connectivity_630_final.parquet")
    edges = parquet.metadata.num_rows
    if edges > 20000000:
        raise ValueError("Graph exceeds the 20-million-edge preparation ceiling")
    counts = np.zeros(count, dtype=np.uint64)
    incoming = np.zeros(count, dtype=np.float64)
    targets = np.array([item["index"] for item in readouts])
    signed_sum = absolute_sum = 0
    maximum = 0
    for batch in parquet.iter_batches(batch_size=65536, columns=COLUMNS, use_threads=False):
        pre, post, weight = [column.to_numpy() for column in batch.columns]
        if pre.min() < 0 or post.min() < 0 or max(pre.max(), post.max()) >= count:
            raise ValueError("Connection index outside the published neuron universe")
        maximum = max(maximum, int(np.abs(weight).max()))
        if maximum >= 2**31:
            raise ValueError("Signed synapse counts do not fit int32")
        counts += np.bincount(pre, minlength=count).astype(np.uint64)
        mask = np.isin(post, targets)
        np.add.at(incoming, pre[mask], np.abs(weight[mask]))
        signed_sum += int(weight.sum())
        absolute_sum += int(np.abs(weight).sum())
    pointers = np.concatenate((np.array([0], dtype=np.uint64), np.cumsum(counts)))
    if int(pointers[-1]) != edges:
        raise ValueError("Connection count changed during conversion")
    np.save(destination/"ids.npy", ids, allow_pickle=False)
    np.save(destination/"indptr.npy", pointers, allow_pickle=False)
    post_out = np.lib.format.open_memmap(destination/"indices.npy", mode="w+", dtype="<u4", shape=(edges,))
    weight_out = np.lib.format.open_memmap(destination/"counts.npy", mode="w+", dtype="<i4", shape=(edges,))
    cursor = pointers[:-1].copy()
    for batch in parquet.iter_batches(batch_size=65536, columns=COLUMNS, use_threads=False):
        pre, post, weight = [column.to_numpy() for column in batch.columns]
        order = np.argsort(pre, kind="stable")
        sorted_pre = pre[order]
        unique, first, sizes = np.unique(sorted_pre, return_index=True, return_counts=True)
        rank = np.arange(len(pre))-np.repeat(first, sizes)
        offsets = cursor[sorted_pre]+rank.astype(np.uint64)
        post_out[offsets] = post[order]
        weight_out[offsets] = weight[order]
        cursor[unique] += sizes.astype(np.uint64)
    np.testing.assert_array_equal(cursor, pointers[1:])
    post_out.flush()
    weight_out.flush()
    # The diagram is a declared selection of actual connections, not brain anatomy.
    selected = {item["index"] for item in readouts}
    relays = [int(x) for x in np.argsort(incoming)[::-1]
              if incoming[x] and x not in selected and x not in inputs][:10]
    selected.update(relays)
    input_scores = {}
    for index in inputs:
        lo, hi = map(int, pointers[index:index+2])
        mask = np.isin(post_out[lo:hi], list(selected))
        input_scores[index] = int(np.abs(weight_out[lo:hi][mask]).sum())
    display_inputs = sorted(inputs, key=lambda x: (-input_scores[x], x))[:8]
    selected.update(display_inputs)
    labels = {item["index"]: item for item in readouts}
    nodes = [
        {"index": index, "id": str(ids[index]),
         "label": labels[index]["label"] if index in labels else
                  f"JON {inputs.index(index)+1}" if index in inputs else f"…{str(ids[index])[-6:]}",
         "role": labels[index]["role"] if index in labels else
                 "sensory" if index in inputs else "interneuron"}
        for index in display_inputs+relays+[item["index"] for item in readouts]
    ]
    links = []
    for pre in selected:
        lo, hi = map(int, pointers[pre:pre+2])
        for post, weight in zip(post_out[lo:hi], weight_out[lo:hi]):
            if int(post) in selected and weight:
                links.append({"source": pre, "target": int(post), "count": int(weight)})
    del post_out, weight_out
    files = {name: {"sha256": sha256(destination/name),
                    "bytes": (destination/name).stat().st_size}
             for name in ("ids.npy", "indptr.npy", "indices.npy", "counts.npy")}
    manifest = {
        "schema": 1, "dataset": "FlyWire 630", "reference_commit": COMMIT,
        "source_files": provenance["files"], "neuron_count": count, "edge_count": edges,
        "signed_count_sum": signed_sum, "absolute_count_sum": absolute_sum,
        "max_abs_count": maximum, "inputs": inputs, "input_groups": groups,
        "readouts": readouts, "inhibitory_controls": [id_to_index[x] for x in protocol["three_inhibitory"]],
        "diagram": {"kind": "selected connections; schematic layout", "nodes": nodes, "edges": links},
        "files": files, "preparation_seconds": time.monotonic()-started,
        "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024,
    }
    pending = destination/"manifest.pending.json"
    pending.write_text(json.dumps(manifest, separators=(",", ":")))
    pending.replace(destination/"manifest.json")
    print(json.dumps({key: manifest[key] for key in (
        "neuron_count", "edge_count", "preparation_seconds", "peak_rss_mib")}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path("/data"))
    parser.add_argument("--output", type=Path, default=Path("/out"))
    args = parser.parse_args()
    prepare(args.source, args.output)
