"""Build an unsigned Windows x64 portable folder with Python and Chromium included."""
from __future__ import annotations
import hashlib
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(*args: str) -> None:
    subprocess.run([sys.executable, *args], cwd=ROOT, check=True)


def main() -> int:
    if sys.platform != "win32" or platform.machine().lower() not in {"amd64", "x86_64"}:
        raise SystemExit("Build this target on Windows x64, not by renaming a Linux or Mac binary.")
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "0"
    run("-m", "playwright", "install", "chromium", "--no-shell")
    run("scripts/run_tests.py", "--require-browser")
    run("-m", "PyInstaller", "--noconfirm", "--clean", "--onedir", "--console", "--name", "Therein",
        "--add-data", f"{ROOT / 'web'}{os.pathsep}web",
        "--add-data", f"{ROOT / 'examples'}{os.pathsep}examples", "recorder.py")
    target = ROOT / "dist/Therein"
    subprocess.run([str(target / "Therein.exe"), "--self-test"], cwd=ROOT, check=True)
    run("scripts/smoke_app.py", "--exe", str(target / "Therein.exe"))
    shutil.copy2(ROOT / "docs/WINDOWS.md", target / "START_HERE.md")
    shutil.copy2(ROOT / "LICENSE", target / "LICENSE.txt")
    (target / "Start_Demo.bat").write_text('@echo off\r\ncd /d "%~dp0"\r\nTherein.exe --demo\r\n', encoding="utf-8", newline="")
    with (target / "DEPENDENCIES.txt").open("w", encoding="utf-8") as handle:
        subprocess.run([sys.executable, "-m", "pip", "freeze"], check=True, stdout=handle)
    bundle = Path(shutil.make_archive(str(ROOT / "dist/Therein-Windows-x64"), "zip", ROOT / "dist", "Therein"))
    digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
    bundle.with_suffix(".zip.sha256").write_text(f"{digest}  {bundle.name}\n", encoding="ascii")
    print(f"Built and smoke-tested: {bundle.name}")
    print(f"SHA256: {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
