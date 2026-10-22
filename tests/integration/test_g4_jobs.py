"""G4 JobService watchdog negative control."""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import psutil

from optisys.jobs.service import JobService, JobSpec, JobState, default_jobs
ROOT = Path(__file__).resolve().parents[2]


def test_parent_watchdog_terminates_sleeping_child_and_records_timeout(tmp_path) -> None:
    service = JobService(ROOT, jobs_dir=tmp_path / "job_records")
    spec = JobSpec(
        job_id="g4-sleep-timeout", label="G4 timeout control",
        description="negative control: must be terminated by parent watchdog",
        build_argv=lambda params, root: [sys.executable, "-c", "__import__('time').sleep(10)"],
        estimated_wall_s=10.0, timeout_s=0.25,
    )
    record = service.start(spec, {}, background=False)
    assert record.state is JobState.TIMEOUT
    assert record.wall_s is not None and record.wall_s < 3.0
    assert record.exit_code is not None
    if record.pid:
        assert not psutil.pid_exists(record.pid)
    assert "process tree terminated" in record.history[-1].get("note", "").lower()


def test_whitelisted_g4_job_runs_the_real_pump_cli(tmp_path) -> None:
    service = JobService(ROOT, python=sys.executable, jobs_dir=tmp_path / "g4_jobs")
    spec = default_jobs(python=sys.executable)["pump976"]
    runs_rel = f"artifacts/g4/tests/job_runs_{uuid.uuid4().hex[:6]}"
    record = service.start(spec, {
        "config": "configs/pump976_g4_l0.yaml",
        "candidate": "configs/pump976_g4_l1.yaml",
        "tolerance": "configs/pump976_g4_tolerance.yaml",
        "rays": 512,
        "assemblies": 2,
        "runs_dir": runs_rel,
    }, background=False)
    assert record.state is JobState.PASS
    assert record.exit_code == 0
    candidates = list((ROOT / runs_rel).glob("*_G4_*/run_status.json"))
    assert len(candidates) == 1
    status = __import__("json").loads(candidates[0].read_text(encoding="utf-8"))
    assert status["status"] == "PARTIAL"
    assert status["G4_ENGINEERING_EXECUTION_STATUS"] == "PARTIAL"
    assert record.run_dir == ""  # the test intentionally writes outside runs/ to avoid a false discovery
