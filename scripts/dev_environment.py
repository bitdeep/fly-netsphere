"""Container-owned development supervisor; no dependencies or host watcher."""
import argparse
from pathlib import Path
import signal
import subprocess
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
WATCHED = [
    "serve_environment.py", "passive_fly.py", "city_world.py",
    "prepare_browser_fly.py", "fetch_neural_reference.py",
    "neural_reference.py", "neural_lab.py",
]


def versions():
    return {name: (ROOT/"scripts"/name).stat().st_mtime_ns
            for name in WATCHED if (ROOT/"scripts"/name).is_file()}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8089)
    args = parser.parse_args()
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())
    child = None

    def shutdown():
        if child is not None and child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()

    def launch():
        print(f"Development server: port {args.port}; backend watcher active", flush=True)
        return subprocess.Popen([sys.executable, "scripts/serve_environment.py",
                                 "--port", str(args.port)], cwd=ROOT)

    previous = versions()
    try:
        child = launch()
        while not stop.wait(1):
            current = versions()
            if current == previous:
                continue
            previous = current
            try:
                for name in current:
                    path = ROOT/"scripts"/name
                    compile(path.read_bytes(), name, "exec")
            except SyntaxError as exc:
                print(f"Reload postponed: {exc}", flush=True)
                continue
            shutdown()
            child = launch()
    finally:
        shutdown()


if __name__ == "__main__":
    main()
