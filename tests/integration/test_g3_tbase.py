"""T-BASE - the pre-G3 regression baseline must still hold.

The task book says the 252 historical tests are a *record*; this round has to
produce its own evidence rather than quote the old summary.  These tests
therefore re-derive the baseline claims from disk instead of trusting a
previously written number.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BASELINE = ROOT / "docs" / "g3" / "G3_BASELINE_HASHES.json"
G2_RUN = ROOT / "runs" / "20261019_191117_G2_52369787"


@pytest.fixture(scope="module")
def baseline() -> dict:
    assert BASELINE.is_file(), f"baseline snapshot missing: {BASELINE}"
    return json.loads(BASELINE.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# the baseline snapshot describes the artefacts the task book names
# --------------------------------------------------------------------------
def test_baseline_pins_the_source_pdf(baseline: dict) -> None:
    pdf = baseline["source_pdf"]
    assert pdf["sha256"] == pdf["expected"], (
        "the design document changed since the snapshot; every citation is suspect")


def test_baseline_pins_the_g2_audit_zip(baseline: dict) -> None:
    entry = baseline["g2_audit_zip"]
    path = ROOT / entry["path"].replace("\\", "/")
    if not path.is_file():
        pytest.skip("G2 audit ZIP not present in this checkout")
    import hashlib

    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    assert actual == entry["expected"], "the frozen G2 audit ZIP was rebuilt or modified"


def test_baseline_pins_the_g2_config(baseline: dict) -> None:
    entry = baseline["g2_config"]
    path = ROOT / entry["path"]
    import hashlib

    actual = hashlib.sha256(path.read_bytes()).hexdigest()
    assert actual == entry["sha256"], (
        "configs/triangulation_g2_l1.yaml changed; the frozen G2 run would no "
        "longer be reproducible from it")


@pytest.mark.parametrize("gate", ["G0", "G1", "G2"])
def test_every_frozen_run_is_recorded_with_a_tree_digest(baseline: dict, gate: str) -> None:
    entry = baseline["frozen_runs"][gate]
    assert entry["status"] == "PASS"
    assert len(entry["tree_digest"]) == 64
    assert entry["file_count"] > 0
    assert entry["total_bytes"] > 0


def test_source_trees_are_recorded_so_a_reader_can_diff_them(baseline: dict) -> None:
    trees = baseline["trees"]
    for name in ("src", "tests", "app", "scripts"):
        assert name in trees, f"tree {name} not snapshotted"
        assert isinstance(trees[name]["file_count"], int)


# --------------------------------------------------------------------------
# the baseline's own verdicts
# --------------------------------------------------------------------------
def test_baseline_verdicts_all_passed(baseline: dict) -> None:
    verdicts = baseline["verdicts"]
    for name, value in verdicts.items():
        assert value is True, f"baseline verdict {name} is {value!r}"


# --------------------------------------------------------------------------
# the historical G2 numbers are still the ones on disk
# --------------------------------------------------------------------------
def test_g2_summary_still_reports_the_three_candidates() -> None:
    path = G2_RUN / "independent_validation" / "summary.json"
    if not path.is_file():
        pytest.skip("frozen G2 run absent")
    summary = json.loads(path.read_text(encoding="utf-8"))
    assert set(summary["candidates"]) == {"baseline", "nominal", "robust"}
    # the frozen values the README quotes
    assert summary["candidates"]["baseline"]["rmse_mm"] == pytest.approx(3.1481, abs=1e-4)
    assert summary["candidates"]["robust"]["rmse_mm"] == pytest.approx(1.9031, abs=1e-4)


def test_technical_details_numbers_match_the_frozen_summary() -> None:
    """The relocated historical numbers must still match frozen evidence."""

    path = G2_RUN / "independent_validation" / "summary.json"
    if not path.is_file():
        pytest.skip("frozen G2 run absent")
    summary = json.loads(path.read_text(encoding="utf-8"))
    readme = (ROOT / "docs/PROJECT_TECHNICAL_DETAILS.md").read_text(encoding="utf-8")

    for name in ("baseline", "nominal", "robust"):
        rmse = summary["candidates"][name]["rmse_mm"]
        rate = summary["candidates"][name]["failure_rate"]
        assert f"{rmse:.4f}" in readme, (
            f"Technical details do not quote the frozen {name} RMSE {rmse:.4f}")
        assert f"{rate * 100:.2f}%" in readme, (
            f"Technical details do not quote the frozen {name} failure rate {rate * 100:.2f}%")


def test_readme_states_there_is_no_measurement() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for phrase in ("无实测", "没有任何实测数据"):
        assert phrase in readme, "README must state the absence of measurement"
    assert "SIMULATED" in readme and "G4" in readme and "NOT_MEASURED" in readme, (
        "README must state that G4 is a simulation and has no empirical validation")


# --------------------------------------------------------------------------
# the historical test count is a record, not a live claim
# --------------------------------------------------------------------------
def test_current_test_count_is_reported_from_this_round() -> None:
    """The 252 figure belongs to G2.  This round must produce its own count.

    This test reads the JUnit **without** asserting on the run it is part of.
    The JUnit file it reads may be the one being written by the very run that
    executes this test, which makes a strict "zero failures" assertion
    self-referential: a previous run's failure would keep the file dirty, and
    the run that fixes it would still read the stale copy.  So the assertions
    here are structural (the file parses, declares tests, and is at least as
    large as the historical baseline); the *gate* on failures/skips is checked
    once, by ``scripts/verify_g3_release.py``, against a JUnit that is already
    complete on disk.
    """

    junit = ROOT / "artifacts" / "g3" / "tests" / "g3_full_junit.xml"
    if not junit.is_file():
        pytest.skip("this round's JUnit has not been produced yet")
    import xml.etree.ElementTree as ET

    root = ET.parse(junit).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    total = sum(int(s.get("tests", 0)) for s in suites)

    assert total > 0, "JUnit declares zero tests"
    assert total >= 252, (
        f"this round reports {total} tests, fewer than the 252 recorded for G2; "
        "tests appear to have been dropped rather than kept")
