#!/usr/bin/env python3
"""Local Crash Round Recorder. Python 3.10+. Run this file or a platform launcher."""
from __future__ import annotations

import argparse
import hmac
import json
import os
import secrets
import signal
import sys
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, urlparse

from browser_capture import BrowserCapture, DEFAULT_SELECTOR, validate_url
from core import (VERSION, Store, analyze, atomic_text, csv_string, export_root,
                  export_to_vault, format_crash, read_csv_text, site_slug, utc_now)

ROOT=Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
if getattr(sys, "frozen", False):
    os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "0")
MAX_BODY=26_000_000


def default_data_dir() -> Path:
    if sys.platform == "darwin":
        return Path.home()/"Library/Application Support/CrashRoundRecorder"
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home())))/"CrashRoundRecorder"
    return Path.home()/".local/share/CrashRoundRecorder"


class InstanceLock:
    """Prevent two processes sharing the same DB/profile/export paths."""
    def __init__(self,path:Path):
        path.parent.mkdir(parents=True,exist_ok=True)
        self.handle=path.open("a+")
        try:
            if os.name=="nt":
                import msvcrt
                self.handle.seek(0)
                if not self.handle.read(1):
                    self.handle.write("0"); self.handle.flush()
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(),fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError,IOError) as exc:
            self.handle.close()
            raise RuntimeError("The recorder is already running for this data folder. Use its existing dashboard.") from exc
    def close(self):
        self.handle.close()


class Application:
    def __init__(self,data_dir:Path,site:str="ethercrash",demo:bool=False):
        self.data_dir=Path(data_dir)
        self.data_dir.mkdir(parents=True,exist_ok=True)
        try:
            self.data_dir.chmod(0o700)
        except OSError:
            pass
        self.site=site_slug(site)
        self.demo=demo
        self.token=secrets.token_urlsafe(32)
        self.lock=threading.RLock()
        self.report_lock=threading.RLock()
        self.export_lock=threading.Lock()
        self.store=Store(self.data_dir/"rounds.sqlite3")
        self.capture=BrowserCapture(self.store,self.data_dir,site=site)
        self.config={"vault":"","url":"https://www.ethercrash.io/","selector":DEFAULT_SELECTOR}
        self.config_path=self.data_dir/"settings.json"
        if self.config_path.exists():
            saved=json.loads(self.config_path.read_text(encoding="utf-8"))
            self.config.update({k:v for k,v in saved.items() if k in self.config and isinstance(v,str)})
        self.cached_revision=-1
        self.cached_report=None
        self.cached_rows=[]
        self.export_status={"last_success_utc":None,"path":None,"error":None,"message":"Choose your vault to enable automatic exports."}
        self.stop_event=threading.Event()
        self.export_thread=threading.Thread(target=self._export_loop,daemon=True,name="obsidian-export")
        self.export_thread.start()

    def report(self):
        with self.report_lock:
            revision=self.store.revision()
            if revision!=self.cached_revision:
                rev,rows=self.store.snapshot(self.site)
                self.cached_report=analyze(rows,self.site)
                self.cached_rows=rows
                self.cached_revision=rev
            return self.cached_report

    def status(self):
        r=self.report()
        small={k:v for k,v in r.items() if k not in {"windows","runs","gaps"}}
        small["windows"]=list(reversed(r["windows"][-30:]))
        small["gaps"]=r["gaps"][-30:]
        small["worst_loss_runs"]=sorted((x for x in r["runs"] if x["outcome"]=="L"),key=lambda x:(-x["length"],x["start_id"]))[:12]
        with self.lock:
            config=dict(self.config)
            export=dict(self.export_status)
        suggestion=str(Path.home()/"Documents/Obsidian Vault")
        return {"version":VERSION,"site":self.site,"demo":self.demo,"config":config,
                "suggested_vault":suggestion,"suggested_vault_exists":Path(suggestion).is_dir(),
                "data_dir":str(self.data_dir),"capture":self.capture.get_status(),"report":small,
                "recent":self.store.recent(self.site),"export":export,"diagnostics":self.store.diagnostics(self.site)}

    def save_settings(self,payload:dict):
        with self.lock:
            new=dict(self.config)
        if "vault" in payload:
            if not isinstance(payload["vault"],str):
                raise ValueError("Vault path must be text")
            vault=payload["vault"].strip()
            if vault:
                export_root(vault) # An explicit save authorizes this recorder-owned subfolder only.
            new["vault"]=vault
        if "url" in payload:
            new["url"]=validate_url(payload["url"].strip())
        if "selector" in payload:
            val=payload["selector"].strip()
            if not 1 <= len(val) <= 1000:
                raise ValueError("Invalid selector length")
            new["selector"]=val
        with self.lock:
            self.config=new
            atomic_text(self.config_path,json.dumps(new,indent=2))
        return new

    def export(self):
        with self.export_lock:
            with self.lock:
                vault=self.config["vault"]
            if not vault:
                raise ValueError("Save an existing vault path first.")
            # Hold one report revision while retrieving its exact raw-record snapshot.
            with self.report_lock:
                report=self.report()
                rows=list(self.cached_rows)
            dest=export_to_vault(vault,rows,report,self.store.diagnostics(self.site,full=True))
            with self.lock:
                self.export_status={"last_success_utc":utc_now(),"path":str(dest),"error":None,
                                    "message":"Updated recorder-owned notes and CSV files."}
            return str(dest)

    def _export_loop(self):
        while not self.stop_event.wait(30):
            with self.lock:
                enabled=bool(self.config["vault"])
            if enabled:
                try:
                    self.export()
                except Exception as exc:
                    with self.lock:
                        self.export_status["error"]=str(exc)
                        self.export_status["message"]="Export failed; the SQLite source remains local."

    def import_csv(self,text:str,confirmed:bool):
        if confirmed is not True:
            raise ValueError("Confirm the CSV contains final site outcomes with real round IDs.")
        rows=read_csv_text(text,self.site)
        result=self.store.ingest(self.site,rows,source="manual_csv_user_asserted_final")
        self.store.event("csv_import",json.dumps({"site":self.site,"rows":len(rows),**result}))
        return result

    def download_csv(self,kind:str) -> str:
        if kind=="rounds":
            _,rows=self.store.snapshot(self.site)
            for r in rows:
                r["crash"]=format_crash(r["cents"])
                r["outcome_at_2x"]="EXCLUDED_CONFLICT" if r["conflicted"] else ("W" if r["cents"]>=200 else "L")
            return csv_string(rows,["site","round_id","crash","outcome_at_2x","first_seen_utc","source","conflicted"])
        report=self.report()
        if kind=="windows":
            from core import Window
            return csv_string(report["windows"],list(Window.__dataclass_fields__))
        if kind=="streaks":
            return csv_string(report["runs"],["trigger_id","outcome","start_id","end_id","length","end_reason","right_censored"])
        raise ValueError("Unknown export kind")

    def close(self):
        self.stop_event.set()
        self.capture.stop()
        # Allow a pending Playwright launch/navigation to finish before closing storage.
        if self.capture.thread and self.capture.thread.is_alive():
            self.capture.thread.join(timeout=80)
        self.export_thread.join(timeout=10)
        if self.config["vault"]:
            try:
                self.export()
            except Exception as exc:
                print(f"Final Obsidian export failed: {exc}",file=sys.stderr)
        self.store.close()


class Handler(BaseHTTPRequestHandler):
    server_version="Therein/1.1"
    def log_message(self,*args):
        # Do not log dashboard tokens, local paths or imported data.
        pass

    @property
    def app(self) -> Application:
        return self.server.app

    def valid_host(self):
        port=self.server.server_port
        return self.headers.get("Host") in {f"127.0.0.1:{port}",f"localhost:{port}"}

    def authorized(self):
        supplied=self.headers.get("X-Recorder-Token","")
        origin=self.headers.get("Origin")
        accepted_origins={f"http://127.0.0.1:{self.server.server_port}",f"http://localhost:{self.server.server_port}"}
        return self.valid_host() and (origin is None or origin in accepted_origins) and hmac.compare_digest(supplied,self.app.token)

    def send(self,status:int,body:bytes,content_type:str="application/json; charset=utf-8"):
        self.send_response(status)
        self.send_header("Content-Type",content_type)
        self.send_header("Content-Length",str(len(body)))
        self.send_header("Cache-Control","no-store")
        self.send_header("X-Content-Type-Options","nosniff")
        self.send_header("Referrer-Policy","no-referrer")
        self.send_header("Content-Security-Policy","default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(body)

    def answer(self,status:int,obj:dict):
        self.send(status,json.dumps(obj,allow_nan=False).encode())

    def do_GET(self):
        if not self.valid_host():
            return self.answer(403,{"error":"Invalid local Host header"})
        path=urlparse(self.path).path
        if path in ("/","/index.html"):
            return self.send(200,(ROOT/"web/index.html").read_bytes(),"text/html; charset=utf-8")
        if path=="/favicon.ico":
            return self.send(204,b"","image/x-icon")
        if not self.authorized():
            return self.answer(403,{"error":"Open the dashboard link printed in your recorder Terminal window."})
        try:
            if path=="/api/status":
                return self.answer(200,self.app.status())
            if path in ("/api/rounds.csv","/api/windows.csv","/api/streaks.csv"):
                kind=path.split("/")[-1].split(".")[0]
                return self.send(200,self.app.download_csv(kind).encode(),"text/csv; charset=utf-8")
            return self.answer(404,{"error":"Not found"})
        except Exception as exc:
            return self.answer(500,{"error":str(exc)[:1000]})

    def do_POST(self):
        if not self.authorized():
            return self.answer(403,{"error":"Local authentication required"})
        try:
            if self.headers.get("Content-Type","").split(";")[0] != "application/json":
                return self.answer(415,{"error":"JSON required"})
            length=int(self.headers.get("Content-Length","0"))
            if not 0 < length <= MAX_BODY:
                return self.answer(413,{"error":"Request must be between 1 byte and 26 MB"})
            data=json.loads(self.rfile.read(length))
            if not isinstance(data,dict):
                raise ValueError("Expected a JSON object")
            path=urlparse(self.path).path
            if path=="/api/settings":
                result=self.app.save_settings(data)
            elif path=="/api/capture/start":
                if self.app.demo:
                    raise ValueError("Live capture is disabled in demo mode. Start the normal recorder for real data.")
                self.app.capture.start(self.app.config["url"],self.app.config["selector"])
                result={"started":True}
            elif path=="/api/capture/stop":
                self.app.capture.stop(); result={"stopped":True}
            elif path=="/api/capture/approve":
                self.app.capture.calibrate(int(data.get("preview_version",-1)),data.get("confirmed") is True)
                result={"approved":True}
            elif path=="/api/capture/selector":
                self.app.save_settings({"selector":data.get("selector","")})
                self.app.capture.set_selector(self.app.config["selector"])
                result={"updated":True}
            elif path=="/api/import":
                result=self.app.import_csv(data.get("csv",""),data.get("confirmed") is True)
            elif path=="/api/export":
                result={"path":self.app.export()}
            elif path=="/api/shutdown":
                if data.get("confirmed") is not True:
                    raise ValueError("Confirm recorder shutdown first.")
                result={"stopping":True}
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            else:
                return self.answer(404,{"error":"Not found"})
            return self.answer(200,{"ok":True,"result":result})
        except (ValueError,KeyError,TypeError) as exc:
            return self.answer(400,{"error":str(exc)[:1000]})
        except Exception as exc:
            return self.answer(500,{"error":str(exc)[:1000]})


def make_server(app:Application,port:int=0):
    server=ThreadingHTTPServer(("127.0.0.1",port),Handler)
    server.daemon_threads=True
    server.app=app
    return server


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir",type=Path,default=None)
    parser.add_argument("--port",type=int,default=8765)
    parser.add_argument("--no-open",action="store_true")
    parser.add_argument("--self-test",action="store_true",help="Run offline bundled-resource, browser and storage diagnostics, then exit")
    parser.add_argument("--demo",action="store_true",help="Isolated synthetic example; never mixes with the real database")
    args=parser.parse_args()
    if args.self_test:
        from selftest import run_self_test
        return run_self_test(ROOT)
    if sys.version_info<(3,10):
        parser.error("Python 3.10 or later is required")
    if not 0 <= args.port <= 65535:
        parser.error("Invalid port")
    data=(args.data_dir or default_data_dir()).expanduser().resolve()
    if args.demo:
        data=data/"synthetic-demo"
    lock=InstanceLock(data/"instance.lock")
    app=Application(data,site="synthetic_demo" if args.demo else "ethercrash",demo=args.demo)
    if args.demo and app.store.revision()==0:
        text=(ROOT/"examples/synthetic_rounds.csv").read_text(encoding="utf-8")
        app.import_csv(text,True)
    try:
        server=make_server(app,args.port)
    except OSError:
        server=make_server(app,0)
    url=f"http://127.0.0.1:{server.server_port}/#{app.token}"
    print(f"\nTherein / Crash Round Recorder {VERSION}" + (" / SYNTHETIC DEMO" if args.demo else ""))
    print(f"Dashboard: {url}\nLocal database: {data/'rounds.sqlite3'}")
    print("Keep this Terminal and the capture browser open. Ctrl+C stops safely.\n",flush=True)
    if not args.no_open:
        webbrowser.open(url)
    def stop_handler(signum,frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM,stop_handler)
    try:
        server.serve_forever(poll_interval=0.5)
    except KeyboardInterrupt:
        print("\nStopping capture and flushing exports...",flush=True)
    finally:
        server.server_close()
        app.close()
        lock.close()


if __name__=="__main__":
    raise SystemExit(main())
