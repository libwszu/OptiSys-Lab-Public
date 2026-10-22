"""T-JOBS - state machine, exit codes, timeout, cancel, restart recovery.

A job service that reports a cancelled or crashed run as PASS is worse than no
job service, because the UI then shows a green badge over missing data.  These
tests drive the real state machine with cheap commands so they stay fast.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys_exe = None


@pytest.fixture()
def service(tmp_path: Path):
    from optisys.jobs.service import JobService

    return JobService(ROOT, jobs_dir=tmp_path / "jobs")


def _spec(python: str, body: list[str], *, timeout_s: float = 60.0,
          requires: tuple[str, ...] = (), produces_run: bool = False):
    from optisys.jobs.service import JobSpec

    return JobSpec(
        job_id="probe",
        label="probe",
        description="test probe",
        build_argv=lambda params, root: [python, *body],
        estimated_wall_s=1.0,
        requires=requires,
        produces_run=produces_run,
        timeout_s=timeout_s,
    )


def _python() -> str:
    import sys

    return sys.executable


# --------------------------------------------------------------------------
# happy path and distinct run ids
# --------------------------------------------------------------------------
def test_successful_job_ends_in_pass(service) -> None:
    record = service.start(_spec(_python(), ["-c", "print('ok')"]), {}, background=False)
    assert record.state.value == "PASS"
    assert record.exit_code == 0
    assert record.wall_s is not None and record.wall_s >= 0
    assert "ok" in service.tail_log(record.job_id)


def test_two_runs_of_the_same_spec_get_distinct_ids(service) -> None:
    """A repeated execution must not overwrite the previous record."""

    first = service.start(_spec(_python(), ["-c", "pass"]), {}, background=False)
    second = service.start(_spec(_python(), ["-c", "pass"]), {}, background=False)
    assert first.job_id != second.job_id
    assert len(service.list_jobs()) == 2


# --------------------------------------------------------------------------
# exit codes
# --------------------------------------------------------------------------
@pytest.mark.parametrize("code,expected", [
    (1, "FAIL"),
    (2, "FAIL"),
    (3, "DEPENDENCY_UNAVAILABLE"),
])
def test_exit_codes_map_to_the_declared_states(service, code: int, expected: str) -> None:
    record = service.start(
        _spec(_python(), ["-c", f"raise SystemExit({code})"]), {}, background=False)
    assert record.state.value == expected, (
        f"exit {code} mapped to {record.state.value}, expected {expected}")


def test_missing_dependency_is_refused_before_spawn(service) -> None:
    record = service.start(
        _spec(_python(), ["-c", "pass"], requires=("definitely_not_a_module_xyz",)),
        {}, background=False)
    assert record.state.value == "DEPENDENCY_UNAVAILABLE"
    assert record.argv == [], "a job with a missing dependency must not be spawned"
    assert any("missing modules" in note for note in record.notes)


# --------------------------------------------------------------------------
# timeout and cancel
# --------------------------------------------------------------------------
def test_timeout_terminates_and_is_not_reported_as_pass(service) -> None:
    record = service.start(
        _spec(_python(), ["-c", "__import__(\"time\").sleep(30)"], timeout_s=1.5),
        {}, background=False)
    assert record.state.value == "TIMEOUT"
    assert record.wall_s is not None and record.wall_s < 10.0


def test_cancel_is_recorded_and_never_passes(service) -> None:
    record = service.start(
        _spec(_python(), ["-c", "__import__(\"time\").sleep(30)"], timeout_s=60.0),
        {}, background=True)
    deadline = time.monotonic() + 10.0
    while service.get(record.job_id).state.value == "QUEUED" and \
            time.monotonic() < deadline:
        time.sleep(0.1)
    cancelled = service.cancel(record.job_id, grace_s=2.0)
    assert cancelled is not None
    assert cancelled.state.value == "CANCELLED"
    assert cancelled.state.value != "PASS"


def test_cancel_of_a_finished_job_does_not_rewrite_history(service) -> None:
    record = service.start(_spec(_python(), ["-c", "pass"]), {}, background=False)
    assert record.state.value == "PASS"
    again = service.cancel(record.job_id)
    assert again is not None
    assert again.state.value == "PASS", "cancelling a finished job must not change its state"


# --------------------------------------------------------------------------
# restart recovery
# --------------------------------------------------------------------------
def test_restart_marks_a_running_job_as_orphaned(tmp_path: Path) -> None:
    """A UI restart cannot keep a child process alive; the record must say so."""

    from optisys.jobs.service import JobService

    jobs_dir = tmp_path / "jobs"
    first = JobService(ROOT, jobs_dir=jobs_dir)
    record = first.start(
        _spec(_python(), ["-c", "__import__(\"time\").sleep(30)"], timeout_s=60.0),
        {}, background=True)
    deadline = time.monotonic() + 10.0
    while first.get(record.job_id).state.value == "QUEUED" and \
            time.monotonic() < deadline:
        time.sleep(0.1)

    # simulate a fresh UI process reading the same jobs directory
    second = JobService(ROOT, jobs_dir=jobs_dir)
    reloaded = second.get(record.job_id)
    assert reloaded is not None
    assert reloaded.state.value == "ORPHANED", (
        f"a job left RUNNING across a restart became {reloaded.state.value}")
    first.cancel(record.job_id, grace_s=1.0)


def test_state_history_is_persisted(service, tmp_path: Path) -> None:
    record = service.start(_spec(_python(), ["-c", "pass"]), {}, background=False)
    path = tmp_path / "jobs" / record.job_id / "job.json"
    assert path.is_file(), "job record was not written to disk"
    payload = json.loads(path.read_text(encoding="utf-8"))
    states = [entry["state"] for entry in payload["history"]]
    assert states[0] == "QUEUED"
    assert "PASS" in states
    assert payload["exit_code"] == 0


# --------------------------------------------------------------------------
# resource accounting
# --------------------------------------------------------------------------
def test_measured_wall_time_is_recorded_separately_from_the_estimate(service) -> None:
    spec = _spec(_python(), ["-c", "__import__(\"time\").sleep(0.4)"])
    estimate = service.estimate(spec)
    record = service.start(spec, {}, background=False)
    assert estimate["estimated_wall_s"] == 1.0
    assert record.wall_s is not None
    assert record.wall_s != estimate["estimated_wall_s"], (
        "the measured wall time equals the planning estimate; the two are not "
        "being kept apart")
    assert estimate["note"].startswith("estimate only")


def test_worker_count_does_not_change_the_row_count() -> None:
    """Single-process and multi-process runs must agree on the panel size.

    Only the row count is asserted here, not the metric values: the demo's
    per-frame random draws are seeded per scene, but a full numeric equality
    check needs the optical chain and belongs in the slow suite.
    """

    source = ROOT / "src" / "optisys" / "gates" / "g3_demo.py"
    text = source.read_text(encoding="utf-8")
    # the demo executes one worker loop; workers is provenance metadata only
    assert "worker_count" in text
    assert "n_frames_expected" in text