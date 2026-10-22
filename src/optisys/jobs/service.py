"""Controlled background job execution.

Design
------
* The UI never calls a heavy simulation loop directly.  It submits a *named*
  job with a validated parameter set; this module resolves the name to a
  whitelisted CLI command, spawns it as a subprocess, and streams the log.
* No shell is involved: ``subprocess`` is called with an argument list, so a
  user-supplied path cannot become a command.  Paths are additionally checked
  against the project root.
* Every job gets a durable record under ``artifacts/g3/jobs/<job_id>/`` with
  the command, the input hashes, start/end time, exit code and the state
  transition history.  Restarting the UI rebuilds history from those records
  and marks jobs with no live process as ``ORPHANED`` instead of pretending
  they are still running.
* A cancelled or failed job is never reported as ``PASS``.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Sequence

# States required by the task book, plus ORPHANED for restart recovery.
STATES = ("QUEUED", "RUNNING", "PASS", "FAIL", "PARTIAL", "CANCELLED",
          "TIMEOUT", "DEPENDENCY_UNAVAILABLE", "ORPHANED")


class JobState(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    PASS = "PASS"
    FAIL = "FAIL"
    PARTIAL = "PARTIAL"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"
    DEPENDENCY_UNAVAILABLE = "DEPENDENCY_UNAVAILABLE"
    ORPHANED = "ORPHANED"


TERMINAL = {JobState.PASS, JobState.FAIL, JobState.PARTIAL,
            JobState.CANCELLED, JobState.TIMEOUT,
            JobState.DEPENDENCY_UNAVAILABLE, JobState.ORPHANED}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class JobSpec:
    """A whitelisted job definition.

    ``build_argv`` receives only validated, typed parameters and returns the
    argument list.  It must not interpolate anything into a shell string.
    """

    job_id: str
    label: str
    description: str
    build_argv: Callable[[dict[str, Any], Path], list[str]]
    estimated_wall_s: float
    requires: tuple[str, ...] = ()
    produces_run: bool = False
    timeout_s: float = 600.0


@dataclass
class JobRecord:
    job_id: str
    spec_id: str
    label: str
    state: JobState
    parameters: dict[str, Any]
    argv: list[str]
    started_at_utc: str = ""
    finished_at_utc: str = ""
    exit_code: int | None = None
    pid: int | None = None
    log_path: str = ""
    run_dir: str = ""
    wall_s: float | None = None
    ram_peak_mb: float | None = None
    notes: list[str] = field(default_factory=list)
    history: list[dict[str, str]] = field(default_factory=list)

    def transition(self, state: JobState, note: str = "") -> None:
        self.state = state
        self.history.append({"at_utc": utc_now(), "state": state.value, "note": note})

    def as_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "spec_id": self.spec_id,
            "label": self.label,
            "state": self.state.value,
            "parameters": self.parameters,
            "argv": self.argv,
            "started_at_utc": self.started_at_utc,
            "finished_at_utc": self.finished_at_utc,
            "exit_code": self.exit_code,
            "pid": self.pid,
            "log_path": self.log_path,
            "run_dir": self.run_dir,
            "wall_s": self.wall_s,
            "ram_peak_mb": self.ram_peak_mb,
            "notes": self.notes,
            "history": self.history,
        }


class JobService:
    """Create, run, cancel and reload jobs."""

    def __init__(self, project_root: Path, python: str | None = None,
                 jobs_dir: Path | None = None) -> None:
        self.root = Path(project_root).resolve()
        self.python = python or sys.executable
        self.jobs_dir = (jobs_dir or self.root / "artifacts" / "g3" / "jobs").resolve()
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self._procs: dict[str, subprocess.Popen] = {}
        self._records: dict[str, JobRecord] = {}
        self._lock = threading.Lock()
        self._reload()

    # -- persistence ----------------------------------------------------
    def _record_path(self, job_id: str) -> Path:
        return self.jobs_dir / job_id / "job.json"

    def _save(self, record: JobRecord) -> None:
        path = self._record_path(record.job_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(record.as_dict(), indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")

    def _reload(self) -> None:
        for path in sorted(self.jobs_dir.glob("*/job.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            record = JobRecord(
                job_id=payload["job_id"], spec_id=payload.get("spec_id", ""),
                label=payload.get("label", ""), state=JobState(payload.get("state", "FAIL")),
                parameters=payload.get("parameters", {}), argv=payload.get("argv", []),
                started_at_utc=payload.get("started_at_utc", ""),
                finished_at_utc=payload.get("finished_at_utc", ""),
                exit_code=payload.get("exit_code"), pid=payload.get("pid"),
                log_path=payload.get("log_path", ""), run_dir=payload.get("run_dir", ""),
                wall_s=payload.get("wall_s"), ram_peak_mb=payload.get("ram_peak_mb"),
                notes=list(payload.get("notes", [])),
                history=list(payload.get("history", [])),
            )
            if record.state in (JobState.RUNNING, JobState.QUEUED):
                # the process cannot survive a UI restart; do not fake progress
                record.transition(JobState.ORPHANED,
                                  "UI restarted and no live process was found; "
                                  "the run directory (if any) must be inspected manually")
                self._save(record)
            self._records[record.job_id] = record

    # -- public API -----------------------------------------------------
    def list_jobs(self) -> list[JobRecord]:
        with self._lock:
            return sorted(self._records.values(),
                          key=lambda item: item.started_at_utc or "", reverse=True)

    def get(self, job_id: str) -> JobRecord | None:
        return self._records.get(job_id)

    def estimate(self, spec: JobSpec) -> dict[str, Any]:
        return {
            "job": spec.job_id,
            "label": spec.label,
            "estimated_wall_s": spec.estimated_wall_s,
            "timeout_s": spec.timeout_s,
            "requires": list(spec.requires),
            "produces_run": spec.produces_run,
            "note": "estimate only; the measured wall time is recorded in the job record",
        }

    def check_dependencies(self, spec: JobSpec) -> list[str]:
        missing = []
        for module in spec.requires:
            try:
                __import__(module)
            except ImportError:
                missing.append(module)
        return missing

    def start(self, spec: JobSpec, parameters: dict[str, Any],
              background: bool = True) -> JobRecord:
        missing = self.check_dependencies(spec)
        job_id = (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
                  + "_" + uuid.uuid4().hex[:6])
        record = JobRecord(
            job_id=job_id, spec_id=spec.job_id, label=spec.label,
            state=JobState.QUEUED, parameters=dict(parameters), argv=[],
        )
        record.transition(JobState.QUEUED, "submitted")
        if missing:
            record.notes.append(f"missing modules: {', '.join(missing)}")
            record.transition(JobState.DEPENDENCY_UNAVAILABLE,
                              "required modules are not importable")
            record.finished_at_utc = utc_now()
            self._save(record)
            self._records[job_id] = record
            return record

        argv = spec.build_argv(dict(parameters), self.root)
        _reject_unsafe(argv, self.root)
        record.argv = argv
        record.log_path = str(self.jobs_dir / job_id / "job.log")
        self._save(record)
        self._records[job_id] = record

        if background:
            thread = threading.Thread(target=self._run, args=(record, spec, argv),
                                      daemon=True)
            thread.start()
        else:
            self._run(record, spec, argv)
        return record

    def cancel(self, job_id: str, grace_s: float = 3.0) -> JobRecord | None:
        record = self._records.get(job_id)
        if record is None:
            return None
        process = self._procs.get(job_id)
        if process is None or process.poll() is not None:
            if record.state not in TERMINAL:
                record.transition(JobState.CANCELLED, "no live process to stop")
                self._save(record)
            return record
        record.transition(record.state, f"cancel requested (grace {grace_s} s)")
        _terminate_tree(process, grace_s)
        record.exit_code = process.returncode
        record.finished_at_utc = utc_now()
        record.transition(JobState.CANCELLED,
                          "terminated on request; a partial run directory must not "
                          "be treated as PASS")
        self._save(record)
        return record

    def tail_log(self, job_id: str, lines: int = 200) -> str:
        record = self._records.get(job_id)
        if record is None or not record.log_path:
            return ""
        path = Path(record.log_path)
        if not path.is_file():
            return ""
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(content[-lines:])

    def wait(self, job_id: str, timeout: float = 600.0) -> JobRecord | None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            record = self._records.get(job_id)
            if record is not None and record.state in TERMINAL:
                return record
            time.sleep(0.1)
        return self._records.get(job_id)

    # -- execution ------------------------------------------------------
    def _run(self, record: JobRecord, spec: JobSpec, argv: list[str]) -> None:
        log_dir = Path(record.log_path).parent
        log_dir.mkdir(parents=True, exist_ok=True)
        record.started_at_utc = utc_now()
        record.transition(JobState.RUNNING, f"exec {argv[1:3]}")
        self._save(record)

        started = time.perf_counter()
        env = _child_env()
        with open(record.log_path, "w", encoding="utf-8") as log:
            log.write(f"# job {record.job_id} ({spec.job_id})\n")
            log.write(f"# argv: {argv}\n")
            log.write(f"# cwd: {self.root}\n")
            log.flush()
            try:
                process = subprocess.Popen(
                    argv, cwd=self.root, stdout=log, stderr=subprocess.STDOUT,
                    text=True, env=env,
                )
            except OSError as exc:
                record.transition(JobState.FAIL, f"spawn failed: {exc}")
                record.finished_at_utc = utc_now()
                self._save(record)
                return
            record.pid = process.pid
            self._procs[record.job_id] = process
            peak = 0.0
            timed_out = False
            sampler = _RssSampler(process.pid)
            sampler.start()
            try:
                while process.poll() is None:
                    if time.perf_counter() - started > spec.timeout_s:
                        timed_out = True
                        _terminate_tree(process, 3.0)
                        break
                    time.sleep(0.2)
            finally:
                sampler.stop()
                peak = sampler.peak_mb

        record.wall_s = time.perf_counter() - started
        record.ram_peak_mb = peak
        record.exit_code = process.returncode
        record.finished_at_utc = utc_now()
        self._procs.pop(record.job_id, None)

        if timed_out:
            record.transition(JobState.TIMEOUT,
                              f"exceeded {spec.timeout_s:.0f} s; process tree terminated")
        elif record.state is JobState.CANCELLED:
            record.transition(JobState.CANCELLED, "cancelled")
        elif process.returncode == 0:
            record.transition(JobState.PASS, "exit 0")
            record.run_dir = self._discover_run(record)
        elif process.returncode == 3:
            record.transition(JobState.DEPENDENCY_UNAVAILABLE,
                              "exit 3: NOT_IMPLEMENTED / dependency unavailable")
        elif process.returncode == 2:
            record.transition(JobState.FAIL, "exit 2: configuration rejected")
        else:
            record.transition(JobState.FAIL, f"exit {process.returncode}")
        self._save(record)

    def _discover_run(self, record: JobRecord) -> str:
        """Newest run directory created after the job started, if any."""

        runs = self.root / "runs"
        if not runs.is_dir():
            return ""
        candidates = [p for p in runs.iterdir()
                      if p.is_dir() and not p.name.startswith("_")]
        if not candidates:
            return ""
        try:
            started = datetime.fromisoformat(record.started_at_utc).timestamp()
        except (TypeError, ValueError, OSError):
            return ""
        candidates = [p for p in candidates if p.stat().st_mtime >= started - 1.0]
        if not candidates:
            return ""
        newest = max(candidates, key=lambda p: p.stat().st_mtime)
        return str(newest)


class _RssSampler:
    """Sample process-tree RSS in a background thread."""

    def __init__(self, pid: int, interval: float = 0.25) -> None:
        self.pid = pid
        self.interval = interval
        self.peak_mb = 0.0
        self.failed = False
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)

    def _loop(self) -> None:
        try:
            import psutil
        except ImportError:
            self.failed = True
            return
        try:
            parent = psutil.Process(self.pid)
        except Exception:
            self.failed = True
            return
        while not self._stop.wait(self.interval):
            try:
                processes = [parent, *parent.children(recursive=True)]
                total = 0
                for proc in processes:
                    try:
                        total += proc.memory_info().rss
                    except Exception:
                        continue
                self.peak_mb = max(self.peak_mb, total / (1024 * 1024))
            except Exception:
                self.failed = True
                return


def _terminate_tree(process: subprocess.Popen, grace_s: float) -> None:
    """Gentle interrupt first, hard kill only as a fallback."""

    try:
        import psutil
    except ImportError:
        process.terminate()
        try:
            process.wait(timeout=grace_s)
        except subprocess.TimeoutExpired:
            process.kill()
            try:
                process.wait(timeout=grace_s)
            except subprocess.TimeoutExpired:
                pass
        return
    try:
        parent = psutil.Process(process.pid)
        children = parent.children(recursive=True)
        for child in children:
            try:
                child.terminate()
            except Exception:
                pass
        try:
            parent.terminate()
        except Exception:
            pass
        _, alive = psutil.wait_procs([*children, parent], timeout=grace_s)
        for proc in alive:
            try:
                proc.kill()
            except Exception:
                pass
        try:
            process.wait(timeout=grace_s)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
                process.wait(timeout=grace_s)
            except (OSError, subprocess.TimeoutExpired):
                pass
    except Exception:
        try:
            process.kill()
        except Exception:
            pass


def _child_env() -> dict[str, str]:
    """Cap BLAS/OpenMP threads so a worker pool cannot oversubscribe."""

    env = dict(os.environ)
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                 "NUMEXPR_NUM_THREADS"):
        env.setdefault(name, "1")
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _reject_unsafe(argv: Sequence[str], root: Path) -> None:
    """Refuse shell metacharacters and paths outside the project."""

    banned = (";", "&&", "||", "|", "`", "$(", ">", "<", "\n")
    if argv[0] != sys.executable and not Path(argv[0]).name.lower().endswith("python.exe"):
        # only the interpreter binary may head the list
        raise ValueError(f"job must start with a python interpreter, got {argv[0]!r}")
    for token in argv:
        if any(bad in token for bad in banned):
            raise ValueError(f"shell metacharacter in argument: {token!r}")
        if token.startswith("-"):
            continue
        path = Path(token)
        if path.is_absolute() or ".." in path.parts:
            resolved = (root / path).resolve() if not path.is_absolute() else path.resolve()
            try:
                resolved.relative_to(root)
            except ValueError as exc:
                raise ValueError(f"path escapes the project root: {token}") from exc


# ---------------------------------------------------------------------------
# whitelisted jobs
# ---------------------------------------------------------------------------
def default_jobs(python: str | None = None) -> dict[str, JobSpec]:
    exe = python or sys.executable

    def _validate(argv: list[str], root: Path) -> list[str]:
        return [exe, "-m", "optisys", "validate", "--config", *argv]

    return {
        "validate-g2": JobSpec(
            job_id="validate-g2",
            label="校验 G2 配置",
            description="schema 3.0 配置校验，不跑光学",
            build_argv=lambda params, root: [exe, "-m", "optisys", "validate",
                                             "--config", str(params["config"])],
            estimated_wall_s=3.0,
            timeout_s=60.0,
        ),
        "optics-smoke": JobSpec(
            job_id="optics-smoke",
            label="光学 smoke",
            description="V4-A/V4-B 光学后端 smoke（真实光线追迹，短时）",
            build_argv=lambda params, root: [exe, "-m", "optisys", "optics-smoke",
                                             "--config", str(params["config"])],
            estimated_wall_s=30.0,
            requires=("optiland",),
            timeout_s=300.0,
        ),
        "g3-demo": JobSpec(
            job_id="g3-demo",
            label="G3 演示 run",
            description="短时真实小工况，生成独立新 run、图与报告",
            build_argv=lambda params, root: [
                exe, "-m", "optisys", "g3-demo",
                "--config", str(params.get("config", "configs/g3_demo.yaml")),
                "--assemblies", str(int(params.get("assemblies", 12))),
                "--workers", str(int(params.get("workers", 1))),
            ],
            estimated_wall_s=120.0,
            requires=("optiland",),
            produces_run=True,
            timeout_s=420.0,
        ),
        "pump976": JobSpec(
            job_id="pump976",
            label="G4 976 nm 泵浦案例",
            description="多模源、双透镜光路、OAT 与小规模公差；父进程实施 300 s watchdog",
            build_argv=lambda params, root: (
                [exe, "-m", "optisys", "pump976",
                 "--config", str(params.get("config", "configs/pump976_g4_l0.yaml")),
                 "--candidate", str(params.get("candidate", "configs/pump976_g4_l1.yaml")),
                 "--tolerance", str(params.get("tolerance", "configs/pump976_g4_tolerance.yaml")),
                 "--rays", str(int(params.get("rays", 1024))),
                 "--assemblies", str(int(params.get("assemblies", 10))),
                 "--timeout", "300"]
                + (["--runs-dir", str(params["runs_dir"])] if params.get("runs_dir") else [])
            ),
            estimated_wall_s=60.0,
            produces_run=True,
            timeout_s=300.0,
        ),
        "report-g2": JobSpec(
            job_id="report-g2",
            label="重建 G2 报告",
            description="只读冻结 run，报告写入 runs/_derived/",
            build_argv=lambda params, root: [exe, "-m", "optisys", "report",
                                             "--run", str(params["run"])],
            estimated_wall_s=5.0,
            timeout_s=120.0,
        ),
        "pytest-fast": JobSpec(
            job_id="pytest-fast",
            label="快速测试",
            description="单元与非光学回归测试",
            build_argv=lambda params, root: [exe, "-m", "pytest", "-q",
                                             "tests/unit", "tests/reference"],
            estimated_wall_s=45.0,
            timeout_s=300.0,
        ),
    }


def profile_estimate(n_assemblies: int, n_distances: int, n_estimators: int,
                     n_conditions: int = 1, seconds_per_frame: float = 0.35) -> dict[str, Any]:
    """Frames/wall estimate shown before a job is started.

    ``seconds_per_frame`` is a declared planning constant, not a measurement.
    The measured value is written into the job record; the UI labels the two
    differently so an estimate is never presented as profiling data.
    """

    frames = n_assemblies * n_distances * n_estimators * n_conditions
    return {
        "frames": frames,
        "estimated_wall_s": frames * seconds_per_frame,
        "basis": {"seconds_per_frame": seconds_per_frame,
                  "kind": "DECLARED_PLANNING_CONSTANT",
                  "note": "not a measurement; measured wall time comes from the job record"},
    }
