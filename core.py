"""Deterministic research recorder: storage, exact rule, and Obsidian exports.

No account, wallet, or wagering functions. Monetary performance is not inferred
from displayed crash multipliers. All analysis uses integer hundredths.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import stat
import re
import sqlite3
import threading
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

VERSION = "1.1.0"
RULE = "anchor >=10.00; then 3 consecutive <2.00; count from NEXT round; reset at >=10.00"
OWNERSHIP = "crash-obsidian-recorder-v1"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def parse_id(value: Any) -> int:
    if isinstance(value, bool) or not re.fullmatch(r"[0-9]{1,15}", str(value).strip()):
        raise ValueError("Round ID must be a positive integer with at most 15 digits.")
    n = int(value)
    if n <= 0:
        raise ValueError("Round ID must be positive.")
    return n


def parse_crash(value: Any) -> int:
    """No exponent, locale guessing, negative values, or rounding accepted."""
    s = str(value).strip().lower().removesuffix("x").strip()
    if not re.fullmatch(r"(?:[0-9]{1,10})(?:\.[0-9]{1,2})?", s):
        raise ValueError(f"Invalid multiplier {str(value)[:60]!r}; use e.g. 1.99 or 10.00.")
    try:
        d = Decimal(s)
    except InvalidOperation as exc:
        raise ValueError("Invalid multiplier") from exc
    return int(d * 100)


def format_crash(cents: int) -> str:
    return f"{cents // 100}.{cents % 100:02d}"


def site_slug(value: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", value):
        raise ValueError("Site must be a short lowercase alphanumeric name.")
    return value


def wilson(wins: int, n: int) -> dict:
    """Nominal fixed-time 95% interval, NOT an anytime-valid edge test."""
    if n == 0:
        return {"n": 0, "wins": 0, "losses": 0, "rate": None, "low": None, "high": None}
    z = 1.959963984540054
    p = wins / n
    den = 1 + z*z/n
    c = (p + z*z/(2*n))/den
    rad = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))/den
    return {"n": n, "wins": wins, "losses": n-wins, "rate": p,
            "low": max(0.0, c-rad), "high": min(1.0, c+rad)}


def read_csv_text(text: str, site: str) -> list[dict]:
    site_slug(site)
    if len(text.encode("utf-8")) > 25_000_000:
        raise ValueError("CSV exceeds the 25 MB import limit; split it into smaller files.")
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    names = set(reader.fieldnames or [])
    crash_name = "crash" if "crash" in names else "multiplier"
    if "round_id" not in names or crash_name not in names:
        raise ValueError("CSV needs round_id,crash (or round_id,multiplier).")
    out = []
    seen = {}
    for line, row in enumerate(reader, 2):
        if row.get("site") and row["site"] != site:
            raise ValueError(f"Line {line}: site does not match {site!r}. Do not mix sites.")
        try:
            rid = parse_id(row.get("round_id"))
            cents = parse_crash(row.get(crash_name))
        except ValueError as exc:
            raise ValueError(f"Line {line}: {exc}") from exc
        if rid in seen and seen[rid] != cents:
            raise ValueError(f"CSV contains conflicting multipliers for round {rid}.")
        seen[rid] = cents
    for rid, cents in sorted(seen.items()):
        out.append({"round_id": rid, "cents": cents})
    if not out:
        raise ValueError("CSV has no rounds.")
    return out


class Store:
    """One machine owns this SQLite database; never put the live DB in a sync vault."""
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS rounds (
            site TEXT NOT NULL, round_id INTEGER NOT NULL, cents INTEGER NOT NULL,
            first_seen_utc TEXT NOT NULL, last_seen_utc TEXT NOT NULL,
            source TEXT NOT NULL, source_ref TEXT NOT NULL, capture_session TEXT NOT NULL,
            conflicted INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY(site, round_id));
          CREATE TABLE IF NOT EXISTS conflicts (
            site TEXT NOT NULL, round_id INTEGER NOT NULL, original_cents INTEGER NOT NULL,
            new_cents INTEGER NOT NULL, detected_utc TEXT NOT NULL, source TEXT NOT NULL,
            UNIQUE(site, round_id, new_cents));
          CREATE TABLE IF NOT EXISTS pending (
            site TEXT NOT NULL, round_id INTEGER NOT NULL, cents INTEGER NOT NULL,
            observed_utc TEXT NOT NULL, PRIMARY KEY(site, round_id));
          CREATE TABLE IF NOT EXISTS capture_sessions (
            id TEXT PRIMARY KEY, site TEXT NOT NULL, started_utc TEXT NOT NULL,
            stopped_utc TEXT, status TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, utc TEXT NOT NULL,
            kind TEXT NOT NULL, detail TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
          INSERT OR IGNORE INTO metadata VALUES ('revision', '0');
        ''')
        # A process crash is not silently counted as continuous capture uptime.
        with self.db:
            self.db.execute("UPDATE capture_sessions SET status='interrupted' WHERE status='running'")

    def revision(self) -> int:
        with self.lock:
            return int(self.db.execute("SELECT value FROM metadata WHERE key='revision'").fetchone()[0])

    def event(self, kind: str, detail: str) -> None:
        with self.lock, self.db:
            self.db.execute("INSERT INTO events(utc,kind,detail) VALUES(?,?,?)", (utc_now(), kind, detail[:2000]))

    def ingest(self, site: str, rows: Iterable[dict], *, source: str,
               source_ref: str = "", session: str = "import") -> dict:
        """Validate the entire batch before mutation. Existing facts never silently change."""
        site_slug(site)
        vals = {}
        for row in rows:
            rid = parse_id(row["round_id"])
            cents = row.get("cents")
            if not isinstance(cents, int) or isinstance(cents, bool) or not 0 <= cents <= 999_999_999_999:
                raise ValueError("cents must be an integer within supported range")
            if rid in vals and vals[rid] != cents:
                raise ValueError("Conflicting observations in the same batch")
            vals[rid] = cents
        now = utc_now()
        inserted = duplicate = conflicts = 0
        with self.lock, self.db:
            for rid, cents in sorted(vals.items()):
                old = self.db.execute("SELECT cents,conflicted FROM rounds WHERE site=? AND round_id=?", (site, rid)).fetchone()
                if old is None:
                    self.db.execute("INSERT INTO rounds VALUES(?,?,?,?,?,?,?,?,0)",
                                    (site,rid,cents,now,now,source,source_ref[:200],session))
                    inserted += 1
                elif old["cents"] == cents:
                    duplicate += 1
                    # Keep I/O bounded: last_seen means last NEW/CONFLICT observation, not each DOM poll.
                else:
                    cur = self.db.execute("INSERT OR IGNORE INTO conflicts VALUES(?,?,?,?,?,?)",
                                         (site,rid,old["cents"],cents,now,source))
                    if cur.rowcount:
                        conflicts += 1
                    self.db.execute("UPDATE rounds SET conflicted=1,last_seen_utc=? WHERE site=? AND round_id=?", (now,site,rid))
                self.db.execute("DELETE FROM pending WHERE site=? AND round_id=?", (site,rid))
            if inserted or conflicts:
                self.db.execute("UPDATE metadata SET value=CAST(value AS INTEGER)+1 WHERE key='revision'")
        return {"inserted": inserted, "duplicates": duplicate, "conflicts": conflicts}

    def set_pending(self, site: str, row: dict | None) -> None:
        with self.lock, self.db:
            # Pending values are deliberately not promoted after restart without re-observation.
            if row and not self.db.execute("SELECT 1 FROM rounds WHERE site=? AND round_id=?",(site,row["round_id"])).fetchone():
                self.db.execute("INSERT INTO pending VALUES(?,?,?,?) ON CONFLICT(site,round_id) DO UPDATE SET cents=excluded.cents,observed_utc=excluded.observed_utc", (site,row["round_id"],row["cents"],utc_now()))

    def snapshot(self, site: str) -> tuple[int,list[dict]]:
        with self.lock:
            rev = self.revision()
            rows = [dict(r) for r in self.db.execute("SELECT * FROM rounds WHERE site=? ORDER BY round_id", (site,))]
            return rev, rows

    def recent(self, site: str, limit: int = 30) -> list[dict]:
        with self.lock:
            return [dict(r) for r in self.db.execute("SELECT * FROM rounds WHERE site=? ORDER BY round_id DESC LIMIT ?", (site,limit))]

    def diagnostics(self, site: str, full: bool = False) -> dict:
        with self.lock:
            return {
                "pending": [dict(r) for r in self.db.execute("SELECT * FROM pending WHERE site=? ORDER BY round_id DESC" + ("" if full else " LIMIT 50"), (site,))],
                "sessions": [dict(r) for r in self.db.execute("SELECT * FROM capture_sessions WHERE site=? ORDER BY started_utc DESC" + ("" if full else " LIMIT 50"), (site,))],
                "events": [dict(r) for r in self.db.execute("SELECT * FROM events ORDER BY id DESC LIMIT 20")],
                "conflicts": [dict(r) for r in self.db.execute("SELECT * FROM conflicts WHERE site=? ORDER BY round_id DESC" + ("" if full else " LIMIT 100"), (site,))],
            }

    def session_start(self, site: str, sid: str) -> None:
        with self.lock, self.db:
            self.db.execute("INSERT INTO capture_sessions VALUES(?,?,?,NULL,'running')", (sid,site,utc_now()))

    def session_stop(self, sid: str, status: str = "stopped") -> None:
        with self.lock, self.db:
            self.db.execute("UPDATE capture_sessions SET stopped_utc=?,status=? WHERE id=?", (utc_now(),status,sid))

    def close(self) -> None:
        with self.lock:
            self.db.close()


@dataclass
class Window:
    anchor_id: int
    trigger_id: int
    first_active_id: int | None = None
    last_active_id: int | None = None
    reset_id: int | None = None
    status: str = "open"
    wins: int = 0
    losses: int = 0
    max_win_streak: int = 0
    max_loss_streak: int = 0
    first_result: str = "unobserved"


def analyze(rows: Iterable[dict], site: str = "ethercrash") -> dict:
    """Replay sorted records. A gap/conflict discards eligibility until a new anchor.

    All active results, including the >=10 reset result, count at 2x. The three
    qualifying reds do not count. Win streaks never join across reset boundaries.
    """
    windows: list[Window] = []
    runs: list[dict] = []
    gaps: list[dict] = []
    by_losses: dict[int, list[int]] = defaultdict(lambda: [0,0])
    first_n = first_wins = total = usable = all_wins = anchors = conflicts = 0
    anchor = None
    red_count = 0
    active: Window | None = None
    run: dict | None = None
    prev = first_id = last_id = None
    current_state = "WAIT_ANCHOR"

    def finish_run(reason: str):
        nonlocal run
        if run:
            run["end_reason"] = reason
            run["right_censored"] = reason in ("data_end", "gap", "conflict")
            runs.append(run)
            run = None

    def finish_window(reason: str):
        nonlocal active
        finish_run(reason)
        if active:
            active.status = {"reset": "closed_reset", "gap": "censored_gap", "conflict": "censored_conflict", "data_end": "open"}[reason]
            active = None

    for row in rows:
        rid, cents = int(row["round_id"]), int(row["cents"])
        if prev is not None and rid <= prev:
            raise ValueError("Analyzer input must be unique and strictly ordered.")
        total += 1
        first_id = rid if first_id is None else first_id
        last_id = rid
        if prev is not None and rid != prev + 1:
            gaps.append({"after_id": prev, "before_id": rid, "missing_rounds": rid-prev-1})
            finish_window("gap")
            anchor = None
            red_count = 0
            current_state = "WAIT_ANCHOR_AFTER_GAP"
        prev = rid
        if row.get("conflicted", 0):
            conflicts += 1
            finish_window("conflict")
            anchor = None
            red_count = 0
            current_state = "WAIT_ANCHOR_AFTER_CONFLICT"
            continue
        usable += 1
        is_win = cents >= 200
        all_wins += int(is_win)
        if active:
            previous_losses = run["length"] if run and run["outcome"] == "L" else 0
            by_losses[previous_losses][0] += int(is_win)
            by_losses[previous_losses][1] += 1
            if active.first_active_id is None:
                active.first_active_id = rid
                active.first_result = "W" if is_win else "L"
                first_n += 1
                first_wins += int(is_win)
            active.last_active_id = rid
            active.wins += int(is_win)
            active.losses += int(not is_win)
            outcome = "W" if is_win else "L"
            if run and run["outcome"] != outcome:
                finish_run("opposite_result")
            if run is None:
                run = {"trigger_id": active.trigger_id, "outcome": outcome, "start_id": rid, "end_id": rid,
                       "length": 0, "end_reason": "", "right_censored": False}
            run["length"] += 1
            run["end_id"] = rid
            active.max_win_streak = max(active.max_win_streak, run["length"] if is_win else 0)
            active.max_loss_streak = max(active.max_loss_streak, run["length"] if not is_win else 0)
            current_state = "ACTIVE_OBSERVED"
        # Process a reset only AFTER classifying an already-active round.
        if cents >= 1000:
            anchors += 1
            if active:
                active.reset_id = rid
                finish_window("reset")
            anchor = rid
            red_count = 0
            current_state = "WAIT_THREE_REDS"
        elif active is None and anchor is not None:
            red_count = red_count + 1 if cents < 200 else 0
            current_state = f"WAIT_REDS_{red_count}_OF_3"
            if red_count == 3:
                active = Window(anchor_id=anchor, trigger_id=rid)
                windows.append(active)
                current_state = "QUALIFIED_FOR_NEXT_OBSERVED_ROUND"

    # Preserve live state before flushing the open run to the descriptive output.
    state = {"label": current_state, "anchor_id": anchor, "qualifying_reds": red_count,
             "active_trigger_id": active.trigger_id if active else None,
             "current_streak": dict(run) if run else None,
             "as_of_round_id": last_id}
    finish_run("data_end")
    wins = sum(w.wins for w in windows)
    losses = sum(w.losses for w in windows)
    completed = [w for w in windows if w.status == "closed_reset"]
    threshold = []
    for k in range(1, 16):
        threshold.append({"losses_at_least": k,
                          "all_windows_reached": sum(w.max_loss_streak >= k for w in windows),
                          "complete_windows_reached": sum(w.max_loss_streak >= k for w in completed),
                          "complete_windows_denominator": len(completed),
                          "all_windows_denominator": len(windows)})
    distribution = Counter((r["outcome"], r["length"], r["right_censored"]) for r in runs)
    return {"schema_version": 1, "site": site, "rule": RULE, "generated_utc": utc_now(),
            "scope": "Descriptive observed outcomes only. Not actual wagers or a validated edge.",
            "total_rounds": total, "usable_rounds": usable, "conflicted_rounds": conflicts,
            "first_round_id": first_id, "last_round_id": last_id, "anchor_count": anchors,
            "gap_count": len(gaps), "missing_id_count": sum(g["missing_rounds"] for g in gaps),
            "gaps": gaps, "state": state, "baseline_observed": wilson(all_wins, usable),
            "first_entries": wilson(first_wins, first_n), "active_outcomes": wilson(wins,wins+losses),
            "max_win_streak": max((w.max_win_streak for w in windows), default=0),
            "max_loss_streak": max((w.max_loss_streak for w in windows), default=0),
            "window_count": len(windows), "complete_windows": len(completed),
            "incomplete_windows": len(windows)-len(completed),
            "windows": [asdict(w) for w in windows], "runs": runs,
            "loss_thresholds": threshold,
            "conditional_after_losses": [{"preceding_active_losses": k, **wilson(v[0],v[1])} for k,v in sorted(by_losses.items())],
            "run_distribution": [{"outcome": o,"length": n,"right_censored": c,"count": count}
                                 for (o,n,c),count in sorted(distribution.items())]}


def csv_string(rows: Iterable[dict], fields: list[str]) -> str:
    out = io.StringIO(newline="")
    w = csv.DictWriter(out,fieldnames=fields,extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
    return out.getvalue()


def redirected_path(path: Path) -> bool:
    """Reject symlinks and NTFS junctions, not ordinary cloud-file placeholders."""
    if path.is_symlink():
        return True
    try:
        tag = getattr(path.lstat(), "st_reparse_tag", 0)
    except FileNotFoundError:
        return False
    return tag == getattr(stat, "IO_REPARSE_TAG_MOUNT_POINT", 0xA0000003)


def atomic_text(path: Path, text: str) -> None:
    if redirected_path(path):
        raise ValueError(f"Refusing to overwrite a redirected path: {path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    if redirected_path(tmp):
        raise ValueError("Temporary path is a symlink")
    with tmp.open("w",encoding="utf-8",newline="") as h:
        h.write(text)
        h.flush()
        os.fsync(h.fileno())
    os.replace(tmp,path)


def export_root(vault: str | Path) -> Path:
    root = Path(vault).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("Choose an existing vault folder. The recorder will not invent a missing vault.")
    dest = root / "Crash Round Research"
    if redirected_path(dest):
        raise ValueError("The export folder cannot be a symlink or junction.")
    marker = dest / ".recorder-owned.json"
    if dest.exists():
        if not marker.is_file() or redirected_path(marker):
            raise ValueError("Crash Round Research already exists and is not recorder-owned. Choose another vault or rename that folder first.")
        if json.loads(marker.read_text(encoding="utf-8"))["owner"] != OWNERSHIP:
            raise ValueError("Export folder ownership mismatch.")
    else:
        dest.mkdir()
        atomic_text(marker,json.dumps({"owner": OWNERSHIP,"created_utc":utc_now()},indent=2))
    for name in ("data", "reports"):
        p = dest/name
        if redirected_path(p):
            raise ValueError("Export subfolders cannot be symlinks or junctions.")
        p.mkdir(exist_ok=True)
    return dest


def export_to_vault(vault: str | Path, rows: list[dict], report: dict, diagnostics: dict) -> Path:
    dest = export_root(vault)
    site = site_slug(report["site"])
    daily = defaultdict(list)
    for row in rows:
        daily[row["first_seen_utc"][:10]].append({**row,"crash":format_crash(row["cents"]),
                                                "outcome_at_2x":"EXCLUDED_CONFLICT" if row["conflicted"] else ("W" if row["cents"]>=200 else "L")})
    raw_fields = ["site","round_id","crash","outcome_at_2x","first_seen_utc","last_seen_utc","source","source_ref","capture_session","conflicted"]
    hashes = {}
    for day, values in sorted(daily.items()):
        rel = f"data/{site}-rounds-{day}.csv"
        text = csv_string(values,raw_fields)
        p = dest/rel
        # Avoid repeatedly rewriting historical days in an Obsidian sync vault.
        digest = hashlib.sha256(text.encode()).hexdigest()
        if not p.is_file() or redirected_path(p) or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:
            atomic_text(p,text)
        hashes[rel]=digest
    tables = {
        "windows": (report["windows"],list(Window.__dataclass_fields__)),
        "streaks": (report["runs"],["trigger_id","outcome","start_id","end_id","length","end_reason","right_censored"]),
        "gaps": (report["gaps"],["after_id","before_id","missing_rounds"]),
        "conditional": (report["conditional_after_losses"],["preceding_active_losses","n","wins","losses","rate","low","high"]),
        "sessions": (diagnostics["sessions"],["id","site","started_utc","stopped_utc","status"]),
        "pending-candidates": (diagnostics["pending"],["site","round_id","cents","observed_utc"]),
        "conflicts": (diagnostics["conflicts"],["site","round_id","original_cents","new_cents","detected_utc","source"]),
    }
    for name,(values,fields) in tables.items():
        atomic_text(dest/f"reports/{site}-{name}.csv",csv_string(values,fields))
    atomic_text(dest/f"reports/{site}-summary.json",json.dumps(report,indent=2,allow_nan=False))
    pct = lambda x: "not available" if x is None else f"{100*x:.2f}%"
    r = report
    note = f'''---
tags: [crash-research, observed-data]
recorder_version: "{VERSION}"
site: "{site}"
updated_utc: "{r['generated_utc']}"
---
# Crash round research / {site}

> [!warning] Observational, not a betting recommendation
> Maximum observed streaks are not upper bounds on future streaks. This recorder has not established a profitable edge. Displayed outcomes are not verified wager executions. The newest captured round is buffered until a newer ID appears.

## Cumulative observations

| Metric | Value |
| --- | ---: |
| Stored final records | {r['total_rounds']} |
| Usable, non-conflicted records | {r['usable_rounds']} |
| Qualified windows | {r['window_count']} |
| Complete windows (through next >=10x) | {r['complete_windows']} |
| Open or interrupted windows | {r['incomplete_windows']} |
| Maximum observed active WIN streak | {r['max_win_streak']} |
| Maximum observed active LOSS streak | {r['max_loss_streak']} |
| Active modeled wins / losses | {r['active_outcomes']['wins']} / {r['active_outcomes']['losses']} |
| Active modeled hit rate | {pct(r['active_outcomes']['rate'])} |
| First-entry wins / opportunities | {r['first_entries']['wins']} / {r['first_entries']['n']} |
| First-entry hit rate | {pct(r['first_entries']['rate'])} |
| Nominal first-entry 95% Wilson interval | {pct(r['first_entries']['low'])} to {pct(r['first_entries']['high'])} |
| Gaps / missing IDs | {r['gap_count']} / {r['missing_id_count']} |
| Conflicted IDs excluded | {r['conflicted_rounds']} |

**Observed state:** `{r['state']['label']}` as of round `{r['last_round_id']}`. This is delayed observation, not a live entry instruction.

## Exact rule

1. A result >=10.00 anchors the next search.
2. Wait for three consecutive completed results <2.00. A result >=2.00 breaks that waiting streak; a new >=10.00 replaces the anchor.
3. Count outcomes from the NEXT round. The three qualifying reds are excluded from active results.
4. At 2.00 exactly, classify W; below 2.00, classify L. This is a hypothetical outcome classification, not a claim about venue settlement.
5. A new >=10.00 while active counts as a final W, closes that active window, and re-anchors the next search.
6. Gaps or conflicting IDs censor the active window and remove eligibility until a new observed >=10.00. Backfilling all missing IDs reconstructs the complete history.

## Evidence files

- `data/{site}-rounds-YYYY-MM-DD.csv`: all stored outcomes, ordered within first-observed UTC day. The date is capture/import date, not the venue's round time. Merge by round_id for global order.
- `reports/{site}-windows.csv`: each qualified window, closure status and maxima.
- `reports/{site}-streaks.csv`: every active run, round IDs and censoring status.
- `reports/{site}-conditional.csv`: outcome counts after each preceding active loss count.
- `reports/{site}-gaps.csv`: missing-ID ranges.
- `reports/{site}-summary.json`: complete cumulative report.
- `reports/{site}-sessions.csv`: capture session start/stop records.
- `reports/{site}-conflicts.csv`: conflicting-value evidence.
- `reports/{site}-pending-candidates.csv`: buffered/unresolved candidates, explicitly EXCLUDED from analysis until re-observed with sufficient finality evidence. `cents` is multiplier times 100.

## Interpretation

First-entry and continuation statistics are kept separate. Complete windows are separated from interrupted and still-open windows. Censored runs can be longer than observed. Neither a high hit rate nor a low maximum streak demonstrates positive expected return.

Wilson intervals are nominal fixed-time binomial intervals, not adjusted for repeated monitoring, rule selection, dependence, or site changes. Treat them as descriptive only. A future loss streak can exceed every streak observed so far.

No deposits, bets, balances, payouts, bonuses, fees, or wallet data are collected. If this vault is synced or published, these exported notes and CSVs follow your own sync/publishing configuration.
'''
    atomic_text(dest/f"{site} Dashboard.md",note)
    atomic_text(dest/"README.md", "# Crash Round Research\n\nRecorder-owned export folder. Keep personal notes outside this folder; generated files are refreshed.\n\nOpen the site Dashboard note for cumulative results. No Obsidian plugin is required. The original SQLite database and browser profile remain outside the vault.\n")
    atomic_text(dest/f"reports/{site}-manifest.json",json.dumps({"generated_utc":utc_now(),"rule":RULE,"raw_csv_sha256":hashes,
               "meaning":"Hashes detect changes to exported bytes; they do not prove the website is fair or outcomes are authentic."},indent=2))
    return dest
