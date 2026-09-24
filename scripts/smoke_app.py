"""Start, query, stop and restart source or executable using isolated synthetic data."""
from __future__ import annotations
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def run_once(command: list[str], data: Path, log: Path) -> dict:
    with log.open("w", encoding="utf-8") as output:
        proc = subprocess.Popen(command + ["--demo", "--data-dir", str(data), "--no-open", "--port", "0"],
                                cwd=ROOT, stdout=output, stderr=subprocess.STDOUT,
                                env={**os.environ, "PYTHONUNBUFFERED": "1", "PYTHONUTF8": "1"})
        try:
            endpoint = None
            for _ in range(300):
                text = log.read_text(encoding="utf-8", errors="replace")
                match = re.search(r"Dashboard: (http://127\.0\.0\.1:\d+)/#([A-Za-z0-9_-]+)", text)
                if match:
                    endpoint = match.groups()
                    break
                if proc.poll() is not None:
                    raise RuntimeError("App exited before startup: " + text[-3000:])
                time.sleep(0.1)
            if not endpoint:
                raise RuntimeError("Dashboard startup exceeded 30 seconds")
            base, token = endpoint
            def request(path: str, body=None):
                headers = {"X-Recorder-Token": token}
                payload = None
                if body is not None:
                    headers["Content-Type"] = "application/json"
                    payload = json.dumps(body).encode()
                with urlopen(Request(base + path, data=payload, headers=headers), timeout=15) as response:
                    return response.read()
            state = json.loads(request("/api/status"))
            if not state["demo"] or state["report"]["total_rounds"] == 0:
                raise RuntimeError("Synthetic fixture was not loaded")
            if b"Crash Round Recorder" not in request("/"):
                raise RuntimeError("Dashboard resource missing")
            request("/api/shutdown", {"confirmed": True})
            if proc.wait(timeout=30) != 0:
                raise RuntimeError("App did not exit cleanly")
            return state["report"]
        finally:
            if proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--exe", type=Path)
    args = parser.parse_args()
    command = [str(args.exe.resolve())] if args.exe else [sys.executable, "-u", str(ROOT / "recorder.py")]
    with tempfile.TemporaryDirectory(prefix="therein-smoke-") as tmp:
        folder = Path(tmp)
        first = run_once(command, folder / "data folder", folder / "first.log")
        second = run_once(command, folder / "data folder", folder / "second.log")
        for key in ("total_rounds", "max_loss_streak", "max_win_streak", "complete_windows"):
            if first[key] != second[key]:
                raise RuntimeError("Restart changed cumulative field: " + key)
    print("PASS: startup, local authenticated API, dashboard, shutdown and restart persistence; synthetic data only.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
