"""Run the UI AppTest suite, including all six Streamlit pages."""

from __future__ import annotations

import json
import subprocess
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
PYTHON = ROOT / ".venv_s6r_release" / "Scripts" / "python.exe"
OUT = ROOT / "artifacts" / "s6r" / "ui"
TIMEOUT_S = 120
EXPECTED_PAGES = {
    "A": "A · 项目总览与证据状态",
    "B": "B · 光斑实验台",
    "C": "C · 优化对照",
    "D": "D · 运行与证据中心",
    "E": "E · 说明与边界",
    "F": "F · 976 nm 泵浦光路",
}


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
    if not PYTHON.is_file():
        raise SystemExit(f"clean release-check Python environment is missing: {PYTHON}")
    OUT.mkdir(parents=True, exist_ok=True)
    basetemp_proc = subprocess.run([str(PYTHON), "scripts/s6r_make_basetemp.py"], cwd=ROOT, capture_output=True, text=True, timeout=30)
    if basetemp_proc.returncode:
        (OUT / "apptest_basetemp_stderr.txt").write_text(basetemp_proc.stderr, encoding="utf-8")
        raise SystemExit(basetemp_proc.returncode)
    basetemp = Path(basetemp_proc.stdout.strip())
    junit = OUT / "apptest_six_pages.xml"
    stdout_path, stderr_path = OUT / "apptest_six_pages_stdout.txt", OUT / "apptest_six_pages_stderr.txt"
    command = [str(PYTHON), "-m", "pytest", "-q", "tests/ui/test_pages_render.py", f"--basetemp={basetemp}", f"--junitxml={junit}"]
    started_at = datetime.now(timezone.utc).isoformat()
    started = time.monotonic()
    timed_out = False
    with stdout_path.open("w", encoding="utf-8", newline="") as out, stderr_path.open("w", encoding="utf-8", newline="") as err:
        process = subprocess.Popen(command, cwd=ROOT, stdout=out, stderr=err, text=True)
        try:
            code = process.wait(timeout=TIMEOUT_S)
        except subprocess.TimeoutExpired:
            timed_out = True
            kill_tree(process.pid)
            if process.poll() is None:
                process.kill()
            process.wait()
            code = 124
    page_tests = {k: {"label": v, "testcase": f"test_each_page_renders_without_exception[{k}]", "status": "NOT_REPORTED"} for k, v in EXPECTED_PAGES.items()}
    totals = {"tests": None, "passed": None, "failed": None, "errors": None, "skipped": None}
    junit_error = None
    if junit.is_file():
        try:
            root = ET.parse(junit).getroot()
            cases = root.findall(".//testcase")
            skipped = sum(tc.find("skipped") is not None for tc in cases)
            failures = sum(tc.find("failure") is not None for tc in cases)
            errors = sum(tc.find("error") is not None for tc in cases)
            totals = {"tests": len(cases), "passed": len(cases) - skipped - failures - errors, "failed": failures, "errors": errors, "skipped": skipped}
            for tc in cases:
                if "test_each_page_renders_without_exception" in tc.attrib.get("name", ""):
                    for key, entry in page_tests.items():
                        if f"[{key}]" in tc.attrib.get("name", ""):
                            entry["status"] = "PASS" if tc.find("failure") is None and tc.find("error") is None and tc.find("skipped") is None else "FAIL"
        except Exception as e:
            junit_error = str(e)
    page_pass = all(v["status"] == "PASS" for v in page_tests.values())
    status = "PASS" if code == 0 and not timed_out and totals["failed"] == 0 and totals["errors"] == 0 and totals["skipped"] == 0 and page_pass else "FAIL"
    result = {
        "schema": "optisys.s6r.apptest/1",
        "command": command,
        "basetemp": str(basetemp),
        "started_at_utc": started_at,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "wall_clock_s": time.monotonic() - started,
        "timeout_s": TIMEOUT_S,
        "timed_out": timed_out,
        "exit_code": code,
        "junit": str(junit.relative_to(ROOT)).replace("\\", "/") if junit.is_file() else None,
        "stdout": str(stdout_path.relative_to(ROOT)).replace("\\", "/"),
        "stderr": str(stderr_path.relative_to(ROOT)).replace("\\", "/"),
        "totals": totals,
        "six_page_checks": page_tests,
        "junit_parse_error": junit_error,
        "status": status,
    }
    (OUT / "apptest_six_pages.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if status == "PASS" else (124 if timed_out else int(code or 1))


if __name__ == "__main__":
    raise SystemExit(main())
