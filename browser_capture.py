"""A separate, visible Chromium session; read-only, user-calibrated DOM capture.

No hidden network endpoint, OCR, anti-bot bypass, stealth patch, or wager click.
Playwright is imported lazily so CSV analysis works without a browser install.
"""
from __future__ import annotations

import json
import sys
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlparse

from core import Store, utc_now

ALLOWED_HOSTS = {"ethercrash.io", "www.ethercrash.io"}
DEFAULT_SELECTOR = 'a[href*="/game/"]'


def validate_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS or parsed.username or parsed.password or parsed.port not in (None,443):
        raise ValueError("Live capture URL must be an HTTPS EtherCrash page, without embedded credentials.")
    if parsed.query or parsed.fragment:
        raise ValueError("Use a plain page URL without tokens, query strings, or fragments.")
    return url


class FinalityGuard:
    """Two identical consecutive snapshots AND a higher visible round ID.

    The latest ID is never promoted by this class. This is a conservative delay,
    not cryptographic proof. Correct completed-history calibration is still required.
    """
    def __init__(self):
        self.previous: dict[int,int] = {}

    def process(self, rows: list[dict]) -> tuple[list[dict], dict | None]:
        current = {}
        for r in rows:
            rid, cents = r["round_id"], r["cents"]
            if rid in current and current[rid] != cents:
                raise ValueError("Conflicting candidate values; nothing promoted")
            current[rid] = cents
        if not current:
            self.previous = {}
            return [],None
        latest = max(current)
        ready = [{"round_id":rid,"cents":cents} for rid,cents in sorted(current.items())
                 if rid < latest and self.previous.get(rid) == cents]
        self.previous = current
        return ready,{"round_id": latest,"cents":current[latest]}


class BrowserCapture:
    def __init__(self, store: Store, data_dir: Path, *, site: str = "ethercrash"):
        self.store, self.data_dir, self.site = store, Path(data_dir), site
        self.lock = threading.RLock()
        self.thread: threading.Thread | None = None
        self.stop_event = threading.Event()
        self.approved = False
        self.selector = DEFAULT_SELECTOR
        self.preview_version = 0
        self.status = {"running":False,"approved":False,"state":"STOPPED","message":"No capture browser is running.",
                       "preview":[],"last_scan_utc":None,"last_new_utc":None,"last_final_id":None,
                       "preview_version":0,"selector":self.selector,"startup_error":None}

    def get_status(self) -> dict:
        with self.lock:
            return json.loads(json.dumps(self.status))

    def start(self, url: str = "https://www.ethercrash.io/", selector: str = DEFAULT_SELECTOR):
        url = validate_url(url)
        if not isinstance(selector,str) or not 1 <= len(selector) <= 1000:
            raise ValueError("Provide a nonempty CSS selector, at most 1,000 characters.")
        with self.lock:
            if self.thread and self.thread.is_alive():
                raise ValueError("A capture browser is already running. Stop it first.")
            self.approved=False
            self.selector=selector
            self.stop_event.clear()
            self.status.update(running=True,approved=False,state="STARTING",message="Opening a separate local Chromium profile...",preview=[],startup_error=None)
            self.thread=threading.Thread(target=self._run,args=(url,),daemon=True,name="capture-browser")
            self.thread.start()

    def calibrate(self, version: int, confirmation: bool):
        with self.lock:
            if not confirmation:
                raise ValueError("Confirm that the preview is completed site round history, not player cashouts or a running multiplier.")
            if not self.status["running"] or len(self.status["preview"]) < 2:
                raise ValueError("No valid history preview is available.")
            if version != self.status["preview_version"]:
                raise ValueError("Preview configuration changed; review the new preview before approving.")
            self.approved=True
            self.status.update(approved=True,state="RECORDING",message="Recording approved history with a one-newer-round finality delay.")
            self.store.event("calibration_approved",f"site={self.site}; selector={self.selector}")

    def set_selector(self, selector: str):
        if not isinstance(selector,str) or not 1 <= len(selector) <= 1000:
            raise ValueError("Invalid selector length")
        with self.lock:
            self.selector=selector
            self.approved=False
            self.preview_version += 1
            self.status.update(selector=selector,approved=False,preview=[],preview_version=self.preview_version,
                               state="NEEDS_REVIEW",message="Selector changed. Review a fresh preview and approve it.")

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=8)

    def _set(self, **values):
        with self.lock:
            self.status.update(values)

    def _run(self, url: str):
        session = uuid.uuid4().hex
        session_started=False
        context=None
        guard=FinalityGuard()
        old_selector=None
        old_path=None
        last_approved=False
        terminal="stopped"
        extractor=(Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))/"web/extractor.js").read_text(encoding="utf-8")
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                # Never point this at the user's ordinary Chrome/Safari profile.
                context = p.chromium.launch_persistent_context(
                    str(self.data_dir/"browser-profile"),headless=False,accept_downloads=False,
                    viewport={"width":1250,"height":850},timeout=45000)
                page=context.pages[0] if context.pages else context.new_page()
                try:
                    page.goto(url,wait_until="domcontentloaded",timeout=30000)
                except Exception:
                    self._set(message="Navigation is slow or blocked. Use the visible browser to open permitted round history; no bypass is attempted.")
                while not self.stop_event.is_set():
                    if page.is_closed():
                        break
                    with self.lock:
                        selector=self.selector
                        approved=self.approved
                    if selector != old_selector:
                        guard=FinalityGuard()
                        old_selector=selector
                    try:
                        result=page.evaluate(extractor,{"selector":selector,"testMode":False})
                    except Exception as exc:
                        guard=FinalityGuard()
                        self._set(state="NO_HISTORY",message=f"Could not read this page: {str(exc)[:180]}")
                        page.wait_for_timeout(2000)
                        continue
                    path=(result.get("origin"),result.get("path"))
                    if old_path is not None and path != old_path:
                        with self.lock:
                            self.approved=False
                            approved=False
                            self.preview_version += 1
                            self.status["preview_version"]=self.preview_version
                        guard=FinalityGuard()
                    old_path=path
                    if not result.get("ok"):
                        guard=FinalityGuard()
                        self._set(state="NO_HISTORY",message=result.get("error","No usable history."),preview=[],last_scan_utc=utc_now())
                        page.wait_for_timeout(2000)
                        continue
                    candidates=result["rows"]
                    self._set(preview=list(reversed(candidates[-16:])),last_scan_utc=utc_now(),selector=selector)
                    if not approved:
                        last_approved=False
                        self._set(state="NEEDS_REVIEW",approved=False,message="Check these game IDs and multipliers against the completed round-history panel, then approve capture.")
                    else:
                        if not last_approved:
                            guard=FinalityGuard()
                            last_approved=True
                        if not session_started:
                            self.store.session_start(self.site,session)
                            session_started=True
                        ready,pending=guard.process(candidates)
                        self.store.set_pending(self.site,pending)
                        counts=self.store.ingest(self.site,ready,source="browser_visible_history",
                                                 source_ref="https://www.ethercrash.io/",session=session)
                        msg="Recording approved completed history. Latest visible ID remains buffered."
                        if counts["conflicts"]:
                            with self.lock:
                                self.approved=False
                            self._set(approved=False,state="CONFLICT_REVIEW",message="Conflicting values were quarantined. Recording paused for review.")
                        else:
                            self._set(state="RECORDING",approved=True,message=msg)
                        if counts["inserted"]:
                            self._set(last_new_utc=utc_now(),last_final_id=max(r["round_id"] for r in ready))
                    page.wait_for_timeout(2000)
                context.close()
                context=None
        except ImportError:
            terminal="error"
            self._set(startup_error="Playwright is missing. Run the setup launcher for your platform first.",message="Browser dependency missing.")
        except Exception as exc:
            terminal="error"
            self._set(startup_error=str(exc)[:1000],message="Browser stopped. See the startup error; CSV import remains available.")
            self.store.event("browser_error",str(exc)[:1000])
        finally:
            if session_started:
                self.store.session_stop(session,terminal)
            self._set(running=False,approved=False,state="ERROR" if terminal=="error" else "STOPPED")
            if terminal != "error":
                self._set(message="Capture stopped. Accepted records remain saved; buffered candidates are not automatically finalized.")
            with self.lock:
                self.approved=False
