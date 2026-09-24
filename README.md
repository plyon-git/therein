# Therein / Crash Round Recorder

Local, read-only round-history research for Windows and macOS. Version **1.1.0**.

Therein records completed multiplier history in SQLite, calculates streaks under the exact rule below, and exports cumulative Markdown/CSV notes into an existing Obsidian vault. It does **not** bet, deposit, withdraw, connect wallets, or establish a profitable edge.

## Windows

**Source edition:** Extract the entire download. Install Windows Python 3.10 or later, then double-click `01_Setup_Windows.bat` once and `02_Start_Windows.bat` to run. Setup downloads Chromium and runs tests. No administrator access or PowerShell policy changes are requested. `Setup_Windows.bat` and `Start_Windows.bat` are compatibility aliases.

**Portable executable:** The `Verify recorder and build Windows portable` Actions workflow builds `Therein-Windows-x64.zip` on a Windows runner only after automated checks pass. Open a successful run's `Therein-Windows-x64` artifact, extract the inner ZIP, keep the entire `Therein` folder together, and open `Therein.exe`. Python and Chromium are bundled. It is an unsigned executable, not an installer. Do not disable security software to run it. A workflow file alone is not proof of a successful build; inspect the run status.

See [Windows guide](docs/WINDOWS.md). The intended browser-supported desktop target is Windows 11 x64. Windows ARM and Windows 10 are not certified by this package.

## macOS

Install Python 3.10 or later. Extract the source and run `01_Setup_Mac.command`, then `02_Start_Mac.command`. If Finder does not execute them, open Terminal in the extracted folder and run:

```bash
bash 01_Setup_Mac.command
bash 02_Start_Mac.command
```

macOS 14 or later is the documented Playwright baseline. The initial setup needs internet; the source ZIP does not contain Python or Chromium.

## First run

1. Keep the app's console and its separate capture browser running. Save your **existing local Obsidian vault path** in the dashboard. No vault writes occur until you save a destination.
2. Select **Open capture browser**, and show the site's completed round-history panel in its initial tab.
3. Compare the round IDs and multipliers in the preview against the completed-history panel. Check the confirmation and select **Approve this history source** only when they match.

Use **Exit recorder** in the dashboard or Ctrl+C in the console to stop and flush exports. Accepted history persists across restarts. `03_Synthetic_Demo_Windows.bat` or `03_Synthetic_Demo.command` uses an isolated, visibly synthetic dataset and disables live capture.

## Exact research rule

- A displayed result **>=10.00x** anchors the qualification search.
- Wait for **three consecutive completed results <2.00x**. A result >=2.00 breaks the waiting streak. Another >=10.00 replaces the anchor.
- Begin counting on the **next** round. Do not count the three qualifying reds as active losses.
- While active, classify >=2.00 as W and <2.00 as L. Ordinary wins reset loss streaks but do not stop the active window.
- The next >=10.00 counts as the active window's final W, closes it, and anchors a new search. Streaks do not join across resets.

Example: `10, 1, 1, 1, 1, 1, 2, 10` produces active results `L L W W`, maximum loss streak 2, maximum win streak 2, and one complete window.

The result-at-2x classification is not a claim about actual cashout execution or settlement at equality. No stakes or account returns are collected.

## Integrity and live integration boundary

**The live EtherCrash DOM has not been certified.** The previous build encountered an access block. The default reader requires visible links matching `a[href*="/game/"]`, ending in `/game/NUMERIC_ID`, with only a multiplier as their text. It reads permitted page content, not hidden APIs, OCR, player balances, or wallet data. A blank preview can require opening the history panel or an actual site-specific selector/adapter. No anti-bot bypass is implemented.

A candidate must appear unchanged in two consecutive scans **and have a newer visible round ID** before finalization. Therefore the dashboard trails history by approximately one round and is **not an immediate entry signal**. IDs are assumed to increase by one per site round. Duplicates are deduplicated; conflicting IDs are excluded. Missing IDs or conflicts break continuity and invalidate eligibility until a new observed >=10x anchor. Complete CSV backfills rebuild the ordered analysis. Open or interrupted streaks are censored, not assumed finished.

The computer must remain awake, online, and running the recorder and its capture browser. Another ordinary browser being online is insufficient. Only history still exposed by the site can be recovered after an interruption.

## Data and Obsidian

Authoritative data stays outside the vault:

- Windows: `%LOCALAPPDATA%\CrashRoundRecorder`
- macOS: `~/Library/Application Support/CrashRoundRecorder`
- Linux: `~/.local/share/CrashRoundRecorder`

The vault receives only a recorder-owned `Crash Round Research` folder, updated every 30 seconds. It contains a dashboard, daily raw CSV shards, window/streak/conditional tables, gaps, conflicts, pending candidates, capture sessions, and a JSON report. Dates on raw shards are first-observed/imported UTC dates, not invented venue times. The dashboard's all-round CSV is globally ordered by numeric ID.

Existing unrelated notes are not edited. An existing same-named export folder without the ownership marker is rejected. Keep personal notes outside the generated subfolder and use only one recorder writer per export destination. Back up the local data folder **after stopping the app**, so the SQLite WAL is not accidentally omitted. Do not share a browser profile, local settings, database, or dashboard token. Your own Obsidian syncing/publishing settings also apply to generated notes.

The local server binds to 127.0.0.1, authenticates API calls using a per-run token, and rejects unexpected Host/Origin headers. It has no telemetry or upload function. Browser profiles may retain logins you perform manually, as a normal browser would.

## CSV and developer tools

Import CSV columns `round_id,crash` (or `round_id,multiplier`). Optional `site` must match the database. Imports are sorted, batch-validated, and capped at 25 MB. Never invent round IDs from screenshots. The sample CSV is labeled synthetic and cannot silently mix with EtherCrash data.

```bash
python recorder.py --demo
python recorder.py --self-test
python scripts/run_tests.py --require-browser
python scripts/smoke_app.py
# Optional alternate local storage and automatically selected port:
python recorder.py --data-dir /your/local/folder --port 0
```

Windows developers can run `05_Build_Portable_Windows.bat` after setup to build and smoke-test the portable ZIP. The GitHub workflow runs the tests on Windows, macOS, and Linux before the native Windows build. See [validation scope](docs/VALIDATION.md) and [primary-source documentation](docs/SOURCES.md).

Observed maxima do not cap future streaks. The Wilson intervals are descriptive, fixed-time intervals, not an anytime-valid edge test or permission to bet.
