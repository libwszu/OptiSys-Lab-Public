"""Parent-watchdog runner for measured S5 commands and process-tree RSS."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]


def _terminate_tree(proc: subprocess.Popen) -> None:
    try:
        parent = psutil.Process(proc.pid)
        children = parent.children(recursive=True)
    except psutil.Error:
        children = []
    for child in reversed(children):
        try:
            child.terminate()
        except psutil.Error:
            pass
    try:
        proc.terminate()
    except OSError:
        pass
    gone, alive = psutil.wait_procs(children, timeout=5)
    for child in alive:
        try:
            child.kill()
        except psutil.Error:
            pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, required=True)
    parser.add_argument("--cwd", type=Path, default=ROOT)
    parser.add_argument("--stdout", type=Path, required=True)
    parser.add_argument("--stderr", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("provide a command after --")
    cwd = args.cwd.resolve()
    out = args.stdout if args.stdout.is_absolute() else ROOT / args.stdout
    err = args.stderr if args.stderr.is_absolute() else ROOT / args.stderr
    meta_path = args.metadata if args.metadata.is_absolute() else ROOT / args.metadata
    for path in (out, err, meta_path):
        path.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        env[key] = "1"
    start = time.perf_counter()
    peak_rss = 0
    timed_out = False
    with out.open("w", encoding="utf-8", errors="replace", newline="") as stdout, \
         err.open("w", encoding="utf-8", errors="replace", newline="") as stderr:
        proc = subprocess.Popen(command, cwd=cwd, env=env, stdout=stdout, stderr=stderr)
        while proc.poll() is None:
            try:
                root_proc = psutil.Process(proc.pid)
                tree = [root_proc, *root_proc.children(recursive=True)]
                rss = sum(p.memory_info().rss for p in tree if p.is_running())
                peak_rss = max(peak_rss, rss)
            except psutil.Error:
                pass
            if time.perf_counter() - start > args.timeout:
                timed_out = True
                _terminate_tree(proc)
                break
            time.sleep(0.05)
        exit_code = proc.returncode if proc.returncode is not None else 124
    wall = time.perf_counter() - start
    result = {
        "schema": "optisys.s5.process_run/1",
        "command": command,
        "cwd": str(cwd),
        "timeout_s": args.timeout,
        "timed_out": timed_out,
        "exit_code": exit_code,
        "outer_wall_s": wall,
        "peak_process_tree_rss_mb": peak_rss / 1024**2,
        "thread_environment": {key: env[key] for key in
                               ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")},
        "stdout_file": str(out),
        "stderr_file": str(err),
        "finished_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    meta_path.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 124 if timed_out else int(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
