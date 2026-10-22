"""Gate aggregation rules: tests are part of the gate, not decoration."""

from __future__ import annotations

import json
from pathlib import Path

from optisys.qa import FAIL, PARTIAL, PASS, aggregate_gate_status, load_gate_requirements

ROOT = Path(__file__).resolve().parents[2]

GOOD_CHECKS = {
    "metric": {"value": 1e-13, "threshold": 1e-8, "pass": True},
}
BAD_CHECKS = {
    "metric": {"value": 1.0, "threshold": 1e-8, "pass": False},
}
GOOD_CASES = [{"case": "nominal", "pass": True}]
BAD_CASES = [{"case": "singular", "pass": False}]
GOOD_TESTS = {"totals": {"passed": 200, "failed": 0, "skipped": 0, "total": 200}}


def test_pass_requires_everything() -> None:
    result = aggregate_gate_status("G1", GOOD_CHECKS, GOOD_CASES, GOOD_TESTS)
    assert result.status == PASS
    assert result.tests_ingested


def test_missing_tests_is_partial_not_pass() -> None:
    result = aggregate_gate_status("G1", GOOD_CHECKS, GOOD_CASES, None)
    assert result.status == PARTIAL
    assert "not ingested" in result.notes[0]


def test_failed_numeric_check_blocks_gate() -> None:
    assert aggregate_gate_status("G1", BAD_CHECKS, GOOD_CASES, GOOD_TESTS).status == FAIL


def test_failed_boundary_case_blocks_gate() -> None:
    assert aggregate_gate_status("G1", GOOD_CHECKS, BAD_CASES, GOOD_TESTS).status == FAIL


def test_failed_test_blocks_gate() -> None:
    tests = {"totals": {"passed": 200, "failed": 1, "skipped": 0, "total": 201}}
    result = aggregate_gate_status("G1", GOOD_CHECKS, GOOD_CASES, tests)
    assert result.status == FAIL
    assert any("tests failed" in item for item in result.failures)


def test_skipped_test_blocks_gate() -> None:
    tests = {"totals": {"passed": 200, "failed": 0, "skipped": 1, "total": 201}}
    assert aggregate_gate_status("G1", GOOD_CHECKS, GOOD_CASES, tests).status == FAIL


def test_too_few_tests_blocks_gate() -> None:
    tests = {"totals": {"passed": 10, "failed": 0, "skipped": 0, "total": 10}}
    assert aggregate_gate_status("G1", GOOD_CHECKS, GOOD_CASES, tests).status == FAIL


def test_requirements_are_loaded_from_project_config() -> None:
    requirements = load_gate_requirements(ROOT)
    assert requirements["G1"]["min_tests_passed"] >= 150
    assert requirements["G0"]["min_tests_passed"] == 117


def test_requirements_file_is_valid_json() -> None:
    payload = json.loads((ROOT / "configs" / "gate_requirements.json").read_text(encoding="utf-8"))
    assert payload["dataset"]["frames"] == 4920
    assert payload["thresholds"]["energy_rel"] == 0.01
