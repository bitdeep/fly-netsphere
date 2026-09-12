"""Fetch data and read-only reference text at the published model's pinned commit."""
import argparse
import ast
import csv
import hashlib
import json
from pathlib import Path
import time
import urllib.request

COMMIT = "91bdd1e7dcf193f3e7ca5a8933497fcef63b7960"
BASE = f"https://raw.githubusercontent.com/philshiu/Drosophila_brain_model/{COMMIT}/"
FILES = {
    "2023_03_23_completeness_630_final.csv": 3057611,
    "2023_03_23_connectivity_630_final.parquet": 86630944,
    "figures.ipynb": 33229,
    "model.py": 11900,
    "LICENSE": 1085,
}


def sha256(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024*1024), b""):
            value.update(block)
    return value.hexdigest()


def fetch(destination):
    destination.mkdir(parents=True, exist_ok=True)
    api = f"https://api.github.com/repos/philshiu/Drosophila_brain_model/git/trees/{COMMIT}"
    with urllib.request.urlopen(api, timeout=30) as response:
        tree = {item["path"]: item for item in json.load(response)["tree"]}
    manifest = {"dataset": "FlyWire 630", "reference_commit": COMMIT,
                "reference_url": BASE, "files": {}}
    for name, size in FILES.items():
        if tree[name]["size"] != size:
            raise ValueError(f"Unexpected source size: {name}")
        # Reference code is retained as text and is never imported or executed.
        target = destination/(name+".txt" if name.endswith(".py") else name)
        if not target.is_file():
            pending = target.with_suffix(target.suffix+".part")
            total = 0
            started = time.monotonic()
            with urllib.request.urlopen(BASE+name, timeout=30) as response, pending.open("wb") as stream:
                while block := response.read(256*1024):
                    total += len(block)
                    if total > size:
                        raise ValueError("Download exceeded its byte ceiling")
                    stream.write(block)
                    # Bound network/disk pressure to 4 MiB/s, with constant RAM.
                    time.sleep(max(0, total/(4*1024*1024)-(time.monotonic()-started)))
            if total != size:
                raise ValueError(f"Incomplete download: {name}")
            pending.replace(target)
        # A pinned Git blob also validates locally cached bytes.
        value = hashlib.sha1(f"blob {size}\0".encode())
        with target.open("rb") as stream:
            for block in iter(lambda: stream.read(1024*1024), b""):
                value.update(block)
        if target.stat().st_size != size or value.hexdigest() != tree[name]["sha"]:
            raise ValueError(f"Source blob mismatch: {name}")
        manifest["files"][name] = {"local_name": target.name, "bytes": size,
                                   "sha256": sha256(target), "git_blob": tree[name]["sha"]}
        print(f"Verified {name}: {size/1024**2:.2f} MiB", flush=True)
    (destination/"sources.json").write_text(json.dumps(manifest, indent=2)+"\n")
    return manifest


def antennal_identifiers(path):
    """Read literal identifiers from the notebook; never execute notebook cells."""
    notebook = json.loads(Path(path).read_text())
    wanted = {"neu_JON_CE", "neu_JON_F", "neu_JON_D_m",
              "id_DN1_1", "id_DN2_l", "id_aBN1", "three_inhibitory"}
    values = {}
    for cell in notebook["cells"]:
        if cell["cell_type"] != "code":
            continue
        for node in ast.parse("".join(cell["source"])).body:
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name) and target.id in wanted:
                    value = ast.literal_eval(node.value)
                    items = value if isinstance(value, list) else [value]
                    if not all(type(item) is int and 0 < item < 2**63 for item in items):
                        raise ValueError("Invalid published neuron identifiers")
                    if target.id in values and values[target.id] != value:
                        raise ValueError("Conflicting published identifiers")
                    values[target.id] = value
    if values.keys() != wanted:
        raise ValueError("Incomplete published antennal protocol")
    return values


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("/data"))
    args = parser.parse_args()
    fetch(args.output)
    protocol = antennal_identifiers(args.output/"figures.ipynb")
    (args.output/"antennal-identifiers.json").write_text(json.dumps(protocol, indent=2)+"\n")
