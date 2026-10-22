"""Gate aggregation: numerical checks + boundary cases + required tests.

A gate is only PASS when every declared numerical check passes, every boundary
case behaves as specified, the pytest evidence was actually ingested, and no
required test failed or was skipped.  Missing test evidence is PARTIAL, never
PASS.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

PASS = "PASS"
FAIL = "FAIL"
PARTIAL = "PARTIAL"

_DEFAULT_REQUIREMENTS = {
    "G0": {"min_tests_passed": 117, "max_tests_failed": 0, "max_tests_skipped": 0},
    "G1": {"min_tests_passed": 150, "max_tests_failed": 0, "max_tests_skipped": 0},
}


@dataclass
class GateAggregation:
    status: str
    numeric_checks_pass: bool
    boundary_cases_pass: bool
    tests_ingested: bool
    tests: dict[str, Any] | None
    required_min_tests: int
    failures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "numeric_checks_pass": self.numeric_checks_pass,
            "boundary_cases_pass": self.boundary_cases_pass,
            "tests_ingested": self.tests_ingested,
            "tests": self.tests,
            "required_min_tests": self.required_min_tests,
            "failures": self.failures,
            "notes": self.notes,
            "rule": (
                "PASS requires all numeric checks, all boundary cases, ingested tests, "
                "failed==0, skipped==0 and passed>=required_min_tests"
            ),
        }


def load_gate_requirements(project_root: Path) -> dict[str, Any]:
    """Load `configs/gate_requirements.json`, falling back to conservative defaults."""

    path = Path(project_root) / "configs" / "gate_requirements.json"
    if path.is_file():
        payload = json.loads(path.read_text(encoding="utf-8"))
        requirements = payload.get("gate_requirements", {})
        if isinstance(requirements, dict) and requirements:
            return requirements
    return dict(_DEFAULT_REQUIREMENTS)


def aggregate_gate_status(
    gate: str,
    numeric_checks: Mapping[str, Mapping[str, Any]],
    boundary_cases: Iterable[Mapping[str, Any]],
    tests_info: Mapping[str, Any] | None,
    requirements: Mapping[str, Any] | None = None,
) -> GateAggregation:
    requirement = (requirements or _DEFAULT_REQUIREMENTS).get(gate, {})
    min_tests = int(requirement.get("min_tests_passed", 0))
    max_failed = int(requirement.get("max_tests_failed", 0))
    max_skipped = int(requirement.get("max_tests_skipped", 0))

    numeric_ok = all(bool(check.get("pass")) for check in numeric_checks.values())
    boundary_ok = all(bool(case.get("pass")) for case in boundary_cases)
    failures: list[str] = []
    notes: list[str] = []

    if not numeric_ok:
        failed_names = [name for name, check in numeric_checks.items() if not check.get("pass")]
        failures.append(f"numeric checks failed: {', '.join(failed_names)}")
    if not boundary_ok:
        bad = [case.get("case", "?") for case in boundary_cases if not case.get("pass")]
        failures.append(f"boundary cases failed: {', '.join(map(str, bad))}")

    tests = dict(tests_info) if tests_info else None
    totals = (tests or {}).get("totals", {}) if tests else {}
    passed = int(totals.get("passed", 0))
    failed = int(totals.get("failed", 0))
    skipped = int(totals.get("skipped", 0))

    if tests is None:
        notes.append("pytest summary not ingested; gate cannot be PASS")
    else:
        if failed > max_failed:
            failures.append(f"tests failed: {failed} > {max_failed}")
        if skipped > max_skipped:
            failures.append(f"tests skipped: {skipped} > {max_skipped}")
        if passed < min_tests:
            failures.append(f"tests passed: {passed} < required {min_tests}")

    if failures:
        status = FAIL
    elif tests is None:
        status = PARTIAL
    else:
        status = PASS

    return GateAggregation(
        status=status,
        numeric_checks_pass=numeric_ok,
        boundary_cases_pass=boundary_ok,
        tests_ingested=tests is not None,
        tests=tests,
        required_min_tests=min_tests,
        failures=failures,
        notes=notes,
    )
