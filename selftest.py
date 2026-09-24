"""Offline diagnostics for both source and frozen distributions. No venue calls."""
from __future__ import annotations

import json
import os
import platform
import shutil
import sys
import tempfile
from pathlib import Path

from browser_capture import FinalityGuard
from core import VERSION, Store, analyze, export_to_vault


def run_self_test(root: Path) -> int:
    checks: dict[str, object] = {}
    try:
        required = ["web/index.html", "web/extractor.js", "examples/synthetic_rounds.csv"]
        for name in required:
            if not (root / name).is_file():
                raise RuntimeError(f"Missing bundled resource: {name}")
        checks["resources"] = "pass"
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            executable = None
            if not getattr(sys, "frozen", False):
                executable = os.environ.get("RECORDER_TEST_CHROMIUM") or shutil.which("chromium")
            opts = {"executable_path": executable} if executable else {"channel": "chromium"}
            browser = pw.chromium.launch(headless=True, **opts)
            try:
                page = browser.new_page()
                page.route("**/*", lambda route: route.abort())
                values = [10, 1, 1, 1, 1, 1, 2, 10, 1]
                html = '<base href="https://www.ethercrash.io/">' + "".join(
                    f'<a href="/game/{100+i}">{value:.2f}x</a>' for i, value in enumerate(values)
                )
                page.set_content(html)
                parsed = page.evaluate((root / "web/extractor.js").read_text(encoding="utf-8"),
                                       {"selector": 'a[href*="/game/"]', "testMode": True})
                if not parsed["ok"] or len(parsed["rows"]) != 9:
                    raise RuntimeError("Synthetic DOM parse did not return nine rounds")
                checks["headless_browser_and_dom"] = "pass"
            finally:
                browser.close()
        guard = FinalityGuard()
        if guard.process(parsed["rows"])[0]:
            raise RuntimeError("Finality guard accepted a first scan")
        accepted, pending = guard.process(parsed["rows"])
        with tempfile.TemporaryDirectory(prefix="therein-selftest-") as tmp:
            data = Path(tmp) / "local data"
            vault = Path(tmp) / "Obsidian Vault"
            vault.mkdir()
            store = Store(data / "rounds.sqlite3")
            try:
                store.ingest("synthetic_demo", accepted, source="synthetic_selftest")
                _, rows = store.snapshot("synthetic_demo")
                report = analyze(rows, "synthetic_demo")
                if report["max_loss_streak"] != 2 or report["complete_windows"] != 1:
                    raise RuntimeError("Rule replay result differs from fixture")
                export_to_vault(vault, rows, report, store.diagnostics("synthetic_demo", full=True))
                if not (vault / "Crash Round Research/synthetic_demo Dashboard.md").is_file():
                    raise RuntimeError("Vault export missing")
                checks["sqlite_rule_and_vault_export"] = "pass"
                checks["latest_round_buffered"] = pending["round_id"] == 108
            finally:
                store.close()
        result = {"ok": True, "version": VERSION, "platform": platform.platform(),
                  "frozen": bool(getattr(sys, "frozen", False)), "checks": checks,
                  "scope": "Offline synthetic fixtures only; live venue capture is not certified."}
        print(json.dumps(result, indent=2), flush=True)
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "version": VERSION, "checks": checks,
                          "error": str(exc), "scope": "Offline diagnostics"}, indent=2), flush=True)
        return 1
