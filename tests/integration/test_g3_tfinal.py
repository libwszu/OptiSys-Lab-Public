"""T-FINAL - the published status file must match what is actually on disk.

``docs/g3/G3_FINAL_STATUS.json`` is the machine-readable summary a reviewer reads
first.  If it drifts from the artefacts it describes, it becomes a nicer-looking
lie than the code it summarises.  These tests cross-check every claim in it that
can be checked mechanically.
"""

from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
STATUS = ROOT / "docs" / "g3" / "G3_FINAL_STATUS.json"
VERDICT = ROOT / "docs" / "g3" / "G2_INHERITANCE_VERDICT.json"


@pytest.fixture(scope="module")
def status() -> dict:
    assert STATUS.is_file(), f"final status missing: {STATUS}"
    return json.loads(STATUS.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# the two verdict lines
# --------------------------------------------------------------------------
def test_status_keeps_the_two_verdict_lines_separate(status: dict) -> None:
    lines = status["verdict_lines"]
    assert lines["G3_ENGINEERING_EXECUTION_STATUS"]
    assert lines["G3_SCIENCE_HANDOFF_STATUS"]
    assert lines["G3_ENGINEERING_EXECUTION_STATUS"] != lines["G3_SCIENCE_HANDOFF_STATUS"]


def test_status_forbids_the_all_pass_token(status: dict) -> None:
    forbidden = status["verdict_lines"]["aggregate_form_forbidden"]
    assert "G3_ALL_PASS" in forbidden


def test_no_surface_emits_the_all_pass_token_unnegated() -> None:
    """Scan every published document for an unqualified all-pass claim.

    The token is allowed to appear inside an explicit ban list.  In JSON that
    means the enclosing value is an array under a key whose name contains
    ``forbidden``, and the string sits on its own line - so a line-by-line scan
    would flag the ban list itself.  The JSON file is therefore checked
    structurally, and only the prose files are checked line by line.
    """

    negations = ("不", "禁", "勿", "NOT", "never", "not ", "禁止", "不得", "不是",
                 "forbidden", "禁止")

    status_payload = json.loads(STATUS.read_text(encoding="utf-8"))
    forbidden_list = status_payload["verdict_lines"]["aggregate_form_forbidden"]
    assert "G3_ALL_PASS" in forbidden_list

    prose = [ROOT / "README.md"] + sorted(
        p for p in (ROOT / "docs" / "g3").glob("*.md"))
    offenders = []
    for path in prose:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if "G3_ALL_PASS" not in line:
                continue
            if any(word in line for word in negations):
                continue
            offenders.append(f"{path.name}: {line.strip()[:120]}")
    assert not offenders, f"unnegated all-pass claim in prose: {offenders}"


def test_all_pass_token_only_appears_as_a_prohibition(status: dict) -> None:
    """Anywhere the token survives outside the ban list must be a negation.

    Two legitimate shapes exist: the string is a member of a ``forbidden`` list,
    or the string sits inside a sentence that forbids it ("禁止压缩为 ...").
    Anything else is an actual all-pass claim and must fail.
    """

    negations = ("禁止", "不得", "不是", "不", "forbidden", "not ")

    def walk(node, path=()):
        if isinstance(node, dict):
            for key, value in node.items():
                yield from walk(value, (*path, str(key)))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                yield from walk(value, (*path, str(index)))
        elif isinstance(node, str):
            yield path, node

    for path, text in walk(status):
        if "G3_ALL_PASS" not in text:
            continue
        in_ban_list = any("forbidden" in segment.lower() for segment in path)
        negated = any(word in text for word in negations)
        assert in_ban_list or negated, (
            f"G3_ALL_PASS asserted at {path}: {text[:120]!r}")


# --------------------------------------------------------------------------
# the status echoes the verdict file exactly
# --------------------------------------------------------------------------
def test_status_matches_the_verdict_file(status: dict) -> None:
    verdict = json.loads(VERDICT.read_text(encoding="utf-8"))
    for key in ("historical_g2_execution", "original_prereg_compliance",
                "as_run_numerical_verification", "stratified_panel_repair",
                "scientific_claim_allowed"):
        assert status["g2_inheritance"][key] == verdict[key], (
            f"{key}: status says {status['g2_inheritance'][key]!r}, "
            f"verdict says {verdict[key]!r}")


def test_status_verdict_hash_matches_the_file(status: dict) -> None:
    actual = hashlib.sha256(VERDICT.read_bytes()).hexdigest()
    assert status["g2_inheritance"]["verdict_sha256"] == actual, (
        "the verdict file changed after the status was written")


def test_status_open_issue_count_matches_the_verdict(status: dict) -> None:
    verdict = json.loads(VERDICT.read_text(encoding="utf-8"))
    assert status["g2_inheritance"]["open_issue_count"] == len(verdict["open_issues"])


# --------------------------------------------------------------------------
# the run the status points at
# --------------------------------------------------------------------------
def test_status_run_exists_and_agrees(status: dict) -> None:
    run_dir = ROOT / status["g3_demo_run"]["path"]
    assert run_dir.is_dir(), f"run directory missing: {run_dir}"
    run_status = json.loads((run_dir / "run_status.json").read_text(encoding="utf-8"))
    assert run_status["run_id"] == status["g3_demo_run"]["run_id"]
    assert run_status["status"] == status["g3_demo_run"]["status"]
    for name, expected in status["g3_demo_run"]["gate_checks"].items():
        assert run_status["gate_checks"][name]["pass"] is expected, (
            f"{name}: status says {expected}, run says "
            f"{run_status['gate_checks'][name]['pass']}")


def test_status_declares_the_demo_is_not_comparable_to_g2(status: dict) -> None:
    assert status["g3_demo_run"]["comparable_to_g2"] is False
    assert status["g3_demo_run"]["inherits_g2_hc3_conflict"] is True


def test_demo_row_count_matches_the_status(status: dict) -> None:
    run_dir = ROOT / status["g3_demo_run"]["path"]
    csv_path = run_dir / "independent_validation" / "sampled_results.csv"
    with csv_path.open(encoding="utf-8") as handle:
        rows = sum(1 for _ in handle) - 1
    assert rows == status["g3_demo_run"]["rows"], (
        f"status declares {status['g3_demo_run']['rows']} rows, CSV has {rows}")


# --------------------------------------------------------------------------
# the test counts
# --------------------------------------------------------------------------
def test_status_test_counts_match_the_junit(status: dict) -> None:
    """The status must not quote a test count the JUnit contradicts.

    Only the *total* is compared against a live run.  The failure/error/skip
    counts are compared against the status's own record, because this test may
    be executing inside the very run whose JUnit is being written: asserting
    "failed == 0" here would make the file self-referential (a failure in run N
    would mark run N+1 as failing too).  The once-per-release gate on
    failures/skips lives in ``scripts/verify_g3_release.py``.
    """

    junit = ROOT / status["tests"]["junit"]
    if not junit.is_file():
        pytest.skip("JUnit not produced in this checkout")
    root = ET.parse(junit).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    total = sum(int(s.get("tests", 0)) for s in suites)

    assert total >= status["tests"]["total"], (
        f"status claims {status['tests']['total']} tests but the JUnit holds {total}; "
        "the status quotes a number the artefacts do not support")
    assert status["tests"]["failed"] == 0
    assert status["tests"]["skipped"] == 0


def test_status_test_gate_is_satisfied(status: dict) -> None:
    gate = status["tests"]["acceptance_gate"]
    assert gate["failed_zero"] and gate["skipped_zero"] and gate["passed_at_least_252"]
    assert status["tests"]["total"] >= 252


@pytest.mark.parametrize("matrix", ["T-BASE", "T-SCI", "T-DATA", "T-UI",
                                    "T-REPORT", "T-JOBS", "T-REPRO", "T-SECURITY"])
def test_every_declared_matrix_has_a_real_file(status: dict, matrix: str) -> None:
    entry = status["tests"]["matrices"][matrix]
    path = ROOT / entry["file"]
    assert path.is_file(), f"{matrix} declares {entry['file']} but it does not exist"
    assert path.stat().st_size > 0


# --------------------------------------------------------------------------
# the audit package
# --------------------------------------------------------------------------
def test_status_audit_package_exists_and_fits_the_target(status: dict) -> None:
    """The package's own size lives outside it, because it is a member of itself.

    Recording ``bytes`` inside the status file would make the recorded value
    wrong the moment the file is written into the archive, so the assertion is on
    the *target* (which is stable) and on the external hash file (which carries
    the true size).
    """

    package = status["audit_package"]
    archive = ROOT / package["path"]
    assert archive.is_file(), f"audit ZIP missing: {archive}"
    assert archive.stat().st_size < package["target_bytes"]
    assert package["within_target"] is True

    assert package["bytes"] is None, (
        "a self-referential byte size was recorded inside the package")
    assert "cannot be recorded inside" in package["bytes_note"]


def test_zip_external_hash_file_records_the_real_size(status: dict) -> None:
    hash_file = ROOT / status["audit_package"]["zip_sha256_source"]
    assert hash_file.is_file()
    lines = hash_file.read_text(encoding="utf-8").splitlines()
    recorded_bytes = next(int(line.split(":")[1]) for line in lines
                          if line.startswith("# bytes:"))
    actual = (ROOT / status["audit_package"]["path"]).stat().st_size
    assert recorded_bytes == actual, (
        f"the external hash file claims {recorded_bytes} bytes, archive is {actual}")


def test_zip_hash_lives_outside_the_archive(status: dict) -> None:
    """A ZIP cannot contain its own hash; the status must say so and point out."""

    package = status["audit_package"]
    assert package["zip_sha256"] is None, (
        "a self-referential ZIP hash was recorded inside the package")
    assert "outside" in package["zip_sha256_note"].lower()

    hash_file = ROOT / package["zip_sha256_source"]
    assert hash_file.is_file(), f"SHA256 file missing: {hash_file}"
    recorded = hash_file.read_text(encoding="utf-8").split()[0]
    actual = hashlib.sha256((ROOT / package["path"]).read_bytes()).hexdigest()
    assert recorded == actual, "the outside hash file disagrees with the ZIP"


# --------------------------------------------------------------------------
# the documents the status promises
# --------------------------------------------------------------------------
def test_every_declared_document_exists(status: dict) -> None:
    missing = [name for name, rel in status["documents"].items()
               if not (ROOT / rel).is_file()]
    assert not missing, f"documents promised but absent: {missing}"


def test_demo_video_is_declared_undelivered(status: dict) -> None:
    """No placeholder link may stand in for a video."""

    demo = (ROOT / status["documents"]["demo_script"]).read_text(encoding="utf-8")
    assert "NOT_DELIVERED" in demo
    assert "http" not in demo.lower().split("not_delivered")[0], (
        "the script section above the disclaimer contains a URL")


# --------------------------------------------------------------------------
# explicit non-claims
# --------------------------------------------------------------------------
def test_status_lists_what_was_not_done(status: dict) -> None:
    joined = " ".join(status["explicitly_not_done"]).lower()
    for topic in ("physical measurement", "g4", "976", "video", "gpu"):
        assert topic in joined, f"status does not disclaim {topic!r}"


def test_readme_does_not_claim_measurement_or_unqualified_g4() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "无实测" in readme or "没有任何实测数据" in readme
    assert "G4" in readme and "NOT_MEASURED" in readme
    assert "NOT_IMPLEMENTED" not in readme
    assert "已通过 CI" not in readme
