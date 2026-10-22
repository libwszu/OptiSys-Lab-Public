"""Run one release-check command with bounded wall time and captured output."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv_s6r_release" / "Scripts" / "python.exe"


def kill_tree(pid: int) -> None:
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
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--timeout", type=float, required=True)
    ap.add_argument("--log-dir", type=Path, default=Path("artifacts/s6r/cli"))
    ap.add_argument("command", nargs=argparse.REMAINDER)
    args = ap.parse_args()
    command = args.command[1:] if args.command and args.command[0] == "--" else args.command
    if not command:
        raise SystemExit("a command is required after --")
    if not PYTHON.is_file():
        raise SystemExit(f"clean release-check Python environment is missing: {PYTHON}")
    log_dir = (ROOT / args.log_dir).resolve()
    log_dir.mkdir(parents=True, exist_ok=True)
    stdout_path, stderr_path = log_dir / f"{args.name}_stdout.txt", log_dir / f"{args.name}_stderr.txt"
    result_path = log_dir / f"{args.name}_run.json"
    full_command = [str(PYTHON), *command]
    start_utc = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    timed_out = False
    with stdout_path.open("w", encoding="utf-8", newline="") as out, stderr_path.open("w", encoding="utf-8", newline="") as err:
        process = subprocess.Popen(full_command, cwd=ROOT, stdout=out, stderr=err, text=True)
        try:
            code = process.wait(timeout=args.timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            kill_tree(process.pid)
            if process.poll() is None:
                process.kill()
            process.wait()
            code = 124
    wall = time.monotonic() - started
    stdout = stdout_path.read_text(encoding="utf-8", errors="replace")
    run_dir = None
    reported_status = None
    for line in stdout.splitlines():
        match = re.search(r"\brun_dir[\"']?\s*[:=]\s*[\"']?(.+?)[\"']?\s*$", line, flags=re.IGNORECASE)
        if match:
            run_dir = match.group(1).strip().strip("'\"")
        demo_match = re.search(r"\b(?:G3 demo )?run\s*:\s*(.+?)\s*$", line, flags=re.IGNORECASE)
        if demo_match:
            run_dir = demo_match.group(1).strip().strip("'\"")
        status_match = re.search(r"\bstatus\s*[:=]\s*[\"']?([A-Z_]+)", line, flags=re.IGNORECASE)
        if status_match:
            reported_status = status_match.group(1).upper()
    record = {
        "schema": "optisys.s6r.command_run/1",
        "name": args.name,
        "command": full_command,
        "started_at_utc": start_utc,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "timeout_s": args.timeout,
        "wall_clock_s": wall,
        "timed_out": timed_out,
        "exit_code": code,
        "run_dir": run_dir,
        "reported_domain_status": reported_status,
        "stdout": str(stdout_path.relative_to(ROOT)).replace("\\", "/"),
        "stderr": str(stderr_path.relative_to(ROOT)).replace("\\", "/"),
        "status": "PASS" if code == 0 and not timed_out else "FAIL",
    }
    result_path.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(record, indent=2, ensure_ascii=False))
    return 0 if record["status"] == "PASS" else (124 if timed_out else int(code or 1))


if __name__ == "__main__":
    raise SystemExit(main())
