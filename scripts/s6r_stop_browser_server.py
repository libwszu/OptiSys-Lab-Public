"""Stop the S6-R browser test server and verify its port is released."""

from __future__ import annotations

import http.client
import json
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
RECORD = ROOT / "artifacts" / "s6r" / "ui" / "browser_server.json"


def main() -> int:
    if not RECORD.is_file():
        raise SystemExit(f"browser server record is missing: {RECORD}")
    record = json.loads(RECORD.read_text(encoding="utf-8"))
    pid, port = int(record["pid"]), int(record["port"])
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
    released = False
    last_error = None
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=0.5)
            conn.request("GET", "/_stcore/health")
            response = conn.getresponse()
            response.read()
            conn.close()
            last_error = f"unexpected HTTP {response.status} from port after shutdown"
        except OSError as e:
            released = True
            last_error = None
            break
        time.sleep(0.25)
    record["shutdown"] = "PASS_PORT_RELEASED" if released else "FAIL_PORT_STILL_RESPONDS"
    record["shutdown_detail"] = last_error
    record["stopped_at_utc"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
    RECORD.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"pid": pid, "port": port, "shutdown": record["shutdown"], "detail": last_error}, indent=2))
    return 0 if released else 1


if __name__ == "__main__":
    raise SystemExit(main())
