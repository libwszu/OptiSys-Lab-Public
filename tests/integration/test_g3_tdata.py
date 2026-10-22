"""T-DATA - denominators, duplicates, truncation, hashes, traceability.

The task book requires that every published statistic be reconstructible from
the raw rows.  These tests therefore do not trust a metric field; they either
recompute it from the CSV or verify that the pipeline refuses to publish it.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
G2_RUN = ROOT / "runs" / "20261019_191117_G2_52369787"
G1_RUN = ROOT / "runs" / "20261019_145702_G1_54c9e3fb"
G0_RUN = ROOT / "runs" / "20261019_130948_G0_78fa364f"
G3_RUNS = sorted((ROOT / "runs").glob("*_G3_*"))

FROZEN = {"G0": G0_RUN, "G1": G1_RUN, "G2": G2_RUN}
BASELINE = ROOT / "docs" / "g3" / "G3_BASELINE_HASHES.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def tree_manifest(base: Path, root: Path = ROOT) -> tuple[str, int, int]:
    """Reproduce the digest used by ``scripts/g3_baseline_snapshot.py``.

    The digest folds in the sorted *relative path* of each file and its
    SHA-256, so a rename or a byte change both move the digest.  Reimplemented
    here rather than imported so the test does not follow a future refactor of
    the script it is meant to check.
    """

    files = sorted(p for p in base.rglob("*")
                   if p.is_file() and "__pycache__" not in p.parts
                   and p.suffix != ".pyc")
    digest = hashlib.sha256()
    total = 0
    for path in files:
        rel = path.relative_to(root).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256(path).encode("ascii"))
        digest.update(b"\n")
        total += path.stat().st_size
    return digest.hexdigest(), len(files), total


# --------------------------------------------------------------------------
# frozen evidence is immutable
# --------------------------------------------------------------------------
@pytest.mark.parametrize("gate", sorted(FROZEN))
def test_frozen_run_tree_matches_the_baseline_snapshot(gate: str) -> None:
    """An in-place edit of a frozen run would invalidate every downstream claim.

    The baseline snapshot records a whole-tree digest, not per-file hashes, so
    the test recomputes the tree digest.  A mismatch names the file counts and
    byte totals on both sides, because "the digest moved" alone is not enough
    to tell a legitimate new file from a corrupted old one.
    """

    run = FROZEN[gate]
    if not run.is_dir():
        pytest.skip(f"frozen {gate} run absent from this checkout")
    assert BASELINE.is_file(), f"baseline snapshot missing: {BASELINE}"
    recorded = json.loads(BASELINE.read_text(encoding="utf-8"))["frozen_runs"][gate]

    digest, count, total = tree_manifest(run)
    assert count == recorded["file_count"], (
        f"{gate}: {count} files now, {recorded['file_count']} at baseline")
    assert total == recorded["total_bytes"], (
        f"{gate}: {total} bytes now, {recorded['total_bytes']} at baseline")
    assert digest == recorded["tree_digest"], (
        f"{gate}: tree digest changed; the frozen run was modified in place")


@pytest.mark.parametrize("gate", sorted(FROZEN))
def test_frozen_run_status_file_hash_is_unchanged(gate: str) -> None:
    run = FROZEN[gate]
    if not run.is_dir():
        pytest.skip(f"frozen {gate} run absent")
    recorded = json.loads(BASELINE.read_text(encoding="utf-8"))["frozen_runs"][gate]
    actual = sha256(run / "run_status.json")
    assert actual == recorded["run_status_sha256"], (
        f"{gate} run_status.json was rewritten: {actual[:16]} != "
        f"{str(recorded['run_status_sha256'])[:16]}")


# --------------------------------------------------------------------------
# duplicates and completeness
# --------------------------------------------------------------------------
def test_g3_demo_sample_keys_are_unique() -> None:
    """A duplicated (candidate, assembly, distance, estimator) key would
    silently double-weight one assembly in the RMSE."""

    assert G3_RUNS, "no G3 run in this workspace"
    run = G3_RUNS[-1]
    rows = _read_rows(run / "independent_validation" / "sampled_results.csv")
    keys = [(r["candidate"], r["assembly_id"], r["distance_mm"], r["estimator"])
            for r in rows]
    assert len(keys) == len(set(keys)), (
        f"{len(keys) - len(set(keys))} duplicate sample keys in {run.name}")


def test_g3_demo_row_count_matches_the_declared_panel() -> None:
    run = G3_RUNS[-1]
    status = json.loads((run / "run_status.json").read_text(encoding="utf-8"))
    declared = status["gate_checks"]["D2_frame_count"]["value"]
    rows = _read_rows(run / "independent_validation" / "sampled_results.csv")
    assert len(rows) == declared, (
        f"{run.name}: CSV has {len(rows)} rows but the gate check declared {declared}")


def test_g2_sample_record_has_no_truncation_marker() -> None:
    """PRE-G3-04: the exported copy was capped at 20 000 rows.

    The full record must be present and must not end mid-line.
    """

    path = G2_RUN / "independent_validation" / "sampled_results.csv"
    if not path.is_file():
        pytest.skip("frozen G2 run absent")
    with path.open(encoding="utf-8") as handle:
        lines = handle.readlines()
    assert len(lines) - 1 == 126_000
    assert lines[-1].endswith("\n"), "record ends without a newline: possibly truncated"
    # the last row must still have the declared column count
    header = lines[0].rstrip("\n").split(",")
    tail = lines[-1].rstrip("\n").split(",")
    assert len(tail) == len(header), "truncated final row"


# --------------------------------------------------------------------------
# denominators
# --------------------------------------------------------------------------
def test_failure_rate_uses_attempts_not_valid_rows() -> None:
    """n_attempted is the failure-rate denominator; using n_valid inflates it."""

    from optisys.audit.g2_recompute import metrics_from_errors

    errors = [float("nan")] * 25 + [0.1] * 75
    metrics = metrics_from_errors(100, errors)
    assert metrics["n_attempted"] == 100
    assert metrics["n_valid"] == 75
    assert metrics["failure_rate"] == pytest.approx(0.25)
    # the RMSE must come from the 75 finite rows only, and say so
    assert metrics["n_errors"] == 75


def test_metrics_reject_a_zero_denominator() -> None:
    from optisys.audit.g2_recompute import metrics_from_errors

    metrics = metrics_from_errors(0, [])
    assert metrics["rmse_mm"] is None
    assert metrics["failure_rate"] is None


def test_nonfinite_on_a_valid_row_is_counted_not_skipped() -> None:
    """A 'valid' row with a NaN error is a data defect, not a valid sample.

    ``metrics_from_errors`` receives only finite errors, so the non-finite count
    must be accumulated by the caller.  Here we only assert that the function
    does not silently inflate ``n_valid`` by counting a NaN or an inf.
    """

    from optisys.audit.g2_recompute import metrics_from_errors

    metrics = metrics_from_errors(4, [0.1, float("inf"), 0.2, 0.3])
    assert metrics["n_valid"] == 3, "a non-finite error was counted as a valid sample"
    assert metrics["failure_rate"] == pytest.approx(0.25)


# --------------------------------------------------------------------------
# traceability: every published number names its source
# --------------------------------------------------------------------------
@pytest.mark.parametrize("gate", sorted(FROZEN))
def test_run_summary_carries_provenance_for_every_number(gate: str) -> None:
    from optisys.presentation.run_repository import load_run

    run = FROZEN[gate]
    if not run.is_dir():
        pytest.skip(f"frozen {gate} run absent")
    summary = load_run(run)
    assert summary.run_id == run.name
    assert summary.schema_version in ("1.0", "2.0", "3.0")
    assert summary.source_tree_sha256, "no source-tree hash: numbers are not traceable"
    assert summary.units, "no unit declaration"
    assert summary.evidence.evidence_level in (
        "FORMULA", "SIMULATED", "CROSS_CHECKED", "MEASURED", "VALIDATED")


def test_missing_fields_are_none_never_zero() -> None:
    """A parser that fills 0 for a missing metric would fabricate a perfect fit."""

    from optisys.presentation.run_repository import CandidateMetrics

    blank = CandidateMetrics(candidate="probe")
    assert blank.rmse_mm is None
    assert blank.failure_rate is None
    assert blank.rmse_mm != 0


# --------------------------------------------------------------------------
# schema detection
# --------------------------------------------------------------------------
@pytest.mark.parametrize("gate,expected", [("G0", "1.0"), ("G1", "2.0"), ("G2", "3.0")])
def test_schema_detection_reads_the_config_snapshot(gate: str, expected: str) -> None:
    """The G1 run_status.json says 1.0 (record format); the config says 2.0.

    Reading the status file first misroutes every G1 run to the G0 parser.
    """

    from optisys.presentation.run_repository import detect_schema

    run = FROZEN[gate]
    if not run.is_dir():
        pytest.skip(f"frozen {gate} run absent")
    assert detect_schema(run) == expected


def test_g3_demo_is_not_reported_as_a_g2_rerun() -> None:
    from optisys.presentation.run_repository import load_run

    if not G3_RUNS:
        pytest.skip("no G3 run")
    summary = load_run(G3_RUNS[-1])
    assert summary.gate == "G3"
    assert summary.counts.get("demo") is True
    assert summary.counts.get("comparable_to_g2") is False