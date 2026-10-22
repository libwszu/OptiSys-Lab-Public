"""Run the full release-check suite with a hard timeout and a new basetemp."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv_s6r_release" / "Scripts" / "python.exe"
OUT = ROOT / "artifacts" / "s6r" / "tests"
TIMEOUT_S = 300


def terminate_tree(pid: int) -> None:
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
    if not PYTHON.is_file():
        raise SystemExit(f"clean release-check Python environment is missing: {PYTHON}")
    OUT.mkdir(parents=True, exist_ok=True)
    base_out = subprocess.run([str(PYTHON), "scripts/s6r_make_basetemp.py"], cwd=ROOT, capture_output=True, text=True, timeout=30)
    if base_out.returncode:
        (OUT / "basetemp_creation_stderr.txt").write_text(base_out.stderr, encoding="utf-8")
        raise SystemExit(base_out.returncode)
    basetemp = Path(base_out.stdout.strip())
    junit = OUT / "full_junit.xml"
    stdout_path, stderr_path = OUT / "full_stdout.txt", OUT / "full_stderr.txt"
    command = [str(PYTHON), "-m", "pytest", "-q", f"--basetemp={basetemp}", f"--junitxml={junit}"]
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    timed_out = False
    with stdout_path.open("w", encoding="utf-8", newline="") as out, stderr_path.open("w", encoding="utf-8", newline="") as err:
        process = subprocess.Popen(command, cwd=ROOT, stdout=out, stderr=err, text=True)
        try:
            code = process.wait(timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired:
            timed_out = True
            terminate_tree(process.pid)
            if process.poll() is None:
                process.kill()
            process.wait()
            code = 124
    wall = time.monotonic() - started
    totals = {"tests": None, "passed": None, "failed": None, "errors": None, "skipped": None, "junit_parse_error": None}
    if junit.is_file():
        try:
            root = ET.parse(junit).getroot()
            testcases = root.findall(".//testcase")
            skipped = sum(tc.find("skipped") is not None for tc in testcases)
            failures = sum(tc.find("failure") is not None for tc in testcases)
            errors = sum(tc.find("error") is not None for tc in testcases)
            totals.update({"tests": len(testcases), "passed": len(testcases) - skipped - failures - errors, "failed": failures, "errors": errors, "skipped": skipped})
        except Exception as e:
            totals["junit_parse_error"] = str(e)
    result = {
        "schema": "optisys.s6r.full_pytest/1",
        "command": command,
        "python": str(PYTHON),
        "basetemp": str(basetemp),
        "started_at_utc": started_at,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "wall_clock_s": wall,
        "timeout_s": TIMEOUT_S,
        "timed_out": timed_out,
        "exit_code": code,
        "junit": str(junit.relative_to(ROOT)).replace("\\", "/") if junit.is_file() else None,
        "stdout": str(stdout_path.relative_to(ROOT)).replace("\\", "/"),
        "stderr": str(stderr_path.relative_to(ROOT)).replace("\\", "/"),
        "totals": totals,
        "status": "PASS" if code == 0 and not timed_out and totals["failed"] == 0 and totals["errors"] == 0 and totals["skipped"] == 0 else "FAIL",
    }
    (OUT / "full_run.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else (124 if timed_out else int(code or 1))


if __name__ == "__main__":
    raise SystemExit(main())
