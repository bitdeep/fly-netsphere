"""Lock already inspected/resolved wheels; execute only inside the project image."""
import importlib.metadata
import json
from pathlib import Path
from urllib.parse import urlparse


def main():
    root = Path("/app")
    report = json.loads((root/"out/dependency-report.json").read_text())
    entries, provenance = [], []
    for package in report["install"]:
        meta, download = package["metadata"], package["download_info"]
        name, version = meta["name"], meta["version"]
        url = download["url"]
        if urlparse(url).hostname != "files.pythonhosted.org" or not url.endswith(".whl"):
            raise ValueError(f"Unapproved artifact origin/type: {name}")
        if importlib.metadata.version(name) != version:
            raise ValueError(f"Version differs from tested image: {name}")
        digest = download["archive_info"]["hashes"]["sha256"]
        entries.append(f"{name}=={version} --hash=sha256:{digest}")
        provenance.append(dict(name=name, version=version, wheel=url, sha256=digest,
            homepage=meta.get("home_page"), project_urls=meta.get("project_url", [])))
    header = ("# Generated from pip's wheel report and checked against the tested image.\n"
              "# Target: CPython 3.10, Linux x86_64. No source distributions.\n"
              "# Regenerate in Docker with scripts/lock_dependencies.py after review.\n")
    with (root/"requirements.lock").open("x") as stream:
        stream.write(header+"\n".join(sorted(entries, key=str.lower))+"\n")
    (root/"docs").mkdir(exist_ok=True)
    with (root/"docs/dependency-provenance.json").open("x") as stream:
        json.dump(provenance, stream, indent=2)
        stream.write("\n")
    print(f"Locked {len(entries)} verified-origin wheels matching the running image.")


if __name__ == "__main__":
    main()
