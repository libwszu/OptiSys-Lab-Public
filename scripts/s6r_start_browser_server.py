"""Start an isolated Streamlit instance for a verified localhost browser run."""

from __future__ import annotations

import argparse
import http.client
import json
import socket
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv_s6r_release" / "Scripts" / "python.exe"
OUT = ROOT / "artifacts" / "s6r" / "ui"


def request(port: int, path: str) -> tuple[int, bytes]:
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
    try:
        conn.request("GET", path)
        response = conn.getresponse()
        return response.status, response.read(65536)
    finally:
        conn.close()


def stop_tree(pid: int) -> None:
    try:
        parent = psutil.Process(pid)
        children = parent.children(recursive=True)
        for child in reversed(children):
            try:
                child.terminate()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        try:
            parent.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
        _, alive = psutil.wait_procs(children + [parent], timeout=5)
        for proc in alive:
            try:
                proc.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8508)
    parser.add_argument("--timeout", type=float, default=45.0)
    args = parser.parse_args()
    if not PYTHON.is_file():
        raise SystemExit(f"clean release-check Python environment is missing: {PYTHON}")
    OUT.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        try:
            sock.bind(("127.0.0.1", args.port))
        except OSError as e:
            raise SystemExit(f"requested localhost port {args.port} is already in use: {e}")
    log_path = OUT / "browser_streamlit.log"
    cmd = [str(PYTHON), "-m", "streamlit", "run", str(ROOT / "app/main.py"), "--server.port", str(args.port), "--server.address", "127.0.0.1", "--server.headless", "true", "--browser.gatherUsageStats", "false"]
    log = log_path.open("w", encoding="utf-8", errors="replace")
    proc = subprocess.Popen(cmd, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    start_utc = datetime.now(timezone.utc).isoformat()
    deadline = time.monotonic() + args.timeout
    health = None
    root = None
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            log.flush()
            stop_tree(proc.pid)
            log.close()
            raise SystemExit(f"Streamlit exited during startup with code {proc.returncode}; log: {log_path}")
        try:
            status, body = request(args.port, "/_stcore/health")
            if status == 200 and body == b"ok":
                health = {"status": status, "body": body.decode("ascii")}
                status2, body2 = request(args.port, "/")
                if status2 == 200 and b"streamlit" in body2.lower():
                    root = {"status": status2, "bytes": len(body2), "streamlit_shell": True}
                    break
        except OSError:
            pass
        time.sleep(0.25)
    if health is None or root is None:
        stop_tree(proc.pid)
        log.close()
        raise SystemExit(f"Streamlit failed loopback verification on {args.port}; log: {log_path}")
    payload = {
        "schema": "optisys.s6r.browser_server/1",
        "command": cmd,
        "pid": proc.pid,
        "port": args.port,
        "url": f"http://127.0.0.1:{args.port}/",
        "started_at_utc": start_utc,
        "health": health,
        "root": root,
        "log": str(log_path.relative_to(ROOT)).replace("\\", "/"),
        "status": "PASS",
        "shutdown": "PENDING_BROWSER_E2E",
    }
    record = OUT / "browser_server.json"
    record.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log.close()
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
