"""Run tests with an optional mandatory browser coverage for browser-capable CI."""
from __future__ import annotations
import argparse
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-browser", action="store_true")
    args = parser.parse_args()
    os.chdir(ROOT)
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.discover("tests"))
    browser_skips = [(test, reason) for test, reason in result.skipped
                     if "test_browser" in str(test)]
    if args.require_browser and browser_skips:
        print("FAILED: browser tests were skipped in browser-required verification.", file=sys.stderr)
        return 1
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
