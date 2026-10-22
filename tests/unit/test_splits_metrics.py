"""Split isolation and metric-denominator tests."""

from __future__ import annotations

import numpy as np
import pytest

from optisys.evaluation.metrics import bootstrap_rmse_ci, is_valid, summarise
from optisys.evaluation.splits import make_distance_splits

DISTANCES = tuple(float(value) for value in np.arange(100.0, 300.1, 5.0))
VALIDATION = (120.0, 150.0, 180.0, 210.0, 240.0, 270.0, 295.0)
TEST = (110.0, 140.0, 170.0, 200.0, 230.0, 260.0, 290.0)


def test_split_counts_and_disjointness() -> None:
    manifest = make_distance_splits(DISTANCES, VALIDATION, TEST)
    assert len(manifest.calib_distances) == 27
    assert len(manifest.validation_distances) == 7
    assert len(manifest.test_distances) == 7
    assert not set(manifest.calib_distances) & set(manifest.test_distances)
    assert not set(manifest.validation_distances) & set(manifest.test_distances)


def test_calibration_covers_both_ends() -> None:
    manifest = make_distance_splits(DISTANCES, VALIDATION, TEST)
    assert min(manifest.calib_distances) == 100.0
    assert max(manifest.calib_distances) == 300.0


def test_test_distances_are_internal() -> None:
    manifest = make_distance_splits(DISTANCES, VALIDATION, TEST)
    assert min(manifest.test_distances) > min(manifest.calib_distances)
    assert max(manifest.test_distances) < max(manifest.calib_distances)


def test_overlap_is_rejected() -> None:
    with pytest.raises(ValueError, match="overlap"):
        make_distance_splits(DISTANCES, VALIDATION, VALIDATION)


def test_outside_grid_is_rejected() -> None:
    with pytest.raises(ValueError, match="outside the grid"):
        make_distance_splits(DISTANCES, VALIDATION, (137.0,))


def _row(**overrides):
    base = {
        "estimator_name": "centroid",
        "dataset_split": "test",
        "condition_id": "medium",
        "Z_gt_mm": 200.0,
        "estimator_status": "OK",
        "quality_flags": "",
        "signed_error_mm": 0.0,
        "runtime_ms": 1.0,
    }
    base.update(overrides)
    return base


def test_blocking_flags_make_a_frame_invalid() -> None:
    assert is_valid(_row())
    assert not is_valid(_row(quality_flags="SATURATED"))
    assert not is_valid(_row(estimator_status="FIT_NOT_CONVERGED"))
    assert is_valid(_row(quality_flags="LOW_SNR"))


def test_failure_rate_uses_all_attempted_frames() -> None:
    rows = [
        _row(signed_error_mm=0.01),
        _row(signed_error_mm=-0.01),
        _row(estimator_status="NO_SIGNAL", signed_error_mm=None, quality_flags="NO_SIGNAL"),
    ]
    summary = summarise(rows, ("estimator_name",), bootstrap=False)[0]
    assert summary["n_attempted"] == 3
    assert summary["n_valid"] == 2
    assert summary["failure_rate"] == pytest.approx(1 / 3)
    assert summary["rmse_mm"] == pytest.approx(0.01)


def test_bias_and_p95_on_known_values() -> None:
    rows = [_row(signed_error_mm=value) for value in (1.0, -1.0, 2.0, -2.0)]
    summary = summarise(rows, ("estimator_name",), bootstrap=False)[0]
    assert summary["bias_mm"] == pytest.approx(0.0)
    assert summary["p95_abs_mm"] == pytest.approx(2.0)


def test_bootstrap_ci_is_ordered() -> None:
    errors = np.linspace(-0.1, 0.1, 40)
    clusters = np.repeat(np.linspace(100.0, 290.0, 10), 4)
    low, high = bootstrap_rmse_ci(errors, clusters, n_boot=100, seed=1)
    assert low is not None and high is not None
    assert low <= high
