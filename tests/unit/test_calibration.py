"""System-calibration tests: two-parameter identifiability, diagnostics, inversion."""

from __future__ import annotations

import numpy as np
import pytest

from optisys.calibration.system import fit_distance_calibration, oracle_calibration
from optisys.errors import Status


def test_exact_two_parameter_recovery() -> None:
    z = np.array([100.0, 125.0, 150.0, 200.0, 250.0, 300.0])
    a, b = 46376.811594, 640.0
    u = a / z + b
    fit = fit_distance_calibration(z, u)
    assert fit.status is Status.OK
    assert fit.a_px_mm == pytest.approx(a, rel=1e-9)
    assert fit.b_px == pytest.approx(b, rel=1e-9)
    assert fit.residual_rms_px == pytest.approx(0.0, abs=1e-9)
    assert fit.n_points == 6


def test_too_few_distances_not_estimable() -> None:
    fit = fit_distance_calibration(np.array([100.0, 200.0]), np.array([1103.0, 871.0]))
    assert fit.status is Status.NOT_ESTIMABLE
    assert fit.a_px_mm is None


def test_decreasing_data_is_rejected() -> None:
    z = np.array([100.0, 150.0, 200.0, 250.0])
    u = 640.0 - 1000.0 / z  # a = -1000
    fit = fit_distance_calibration(z, u)
    assert fit.status is Status.NOT_ESTIMABLE


def test_identifiability_is_explicit() -> None:
    fit = fit_distance_calibration(np.array([100.0, 150.0, 200.0]), np.array([1100.0, 900.0, 800.0]))
    assert "a = fx*B" in fit.identifiability
    assert "b = cx" in fit.identifiability


def test_inverse_round_trip() -> None:
    z = np.array([100.0, 150.0, 200.0, 250.0, 300.0])
    fit = fit_distance_calibration(z, 46376.811594 / z + 640.0)
    for value in (110.0, 170.0, 290.0):
        u = 46376.811594 / value + 640.0
        depth, status, _ = fit.inverse(u)
        assert status is Status.OK
        assert depth == pytest.approx(value, rel=1e-10)


def test_inverse_singular_and_out_of_range() -> None:
    z = np.array([100.0, 150.0, 200.0, 250.0, 300.0])
    fit = fit_distance_calibration(z, 46376.811594 / z + 640.0)
    _, status, _ = fit.inverse(640.0)
    assert status is Status.SINGULAR_GEOMETRY

    u_near = 46376.811594 / 100.0 + 640.0
    _, status, _ = fit.inverse(u_near + 100.0)  # implies Z < 100 mm
    assert status is Status.OUT_OF_RANGE


def test_oracle_matches_geometry() -> None:
    oracle = oracle_calibration(2318.8405797101445, 20.0, 640.0, 0.0, 100.0, 300.0)
    assert oracle.a_px_mm == pytest.approx(46376.81159420289, rel=1e-12)
    assert oracle.b_px == pytest.approx(640.0)
    assert oracle.method == "oracle_geometry"


def test_covariance_and_condition_number_are_finite() -> None:
    z = np.array([100.0, 120.0, 150.0, 200.0, 260.0, 300.0])
    u = 46376.8 / z + 640.0 + np.array([0.01, -0.02, 0.0, 0.03, -0.01, 0.0])
    fit = fit_distance_calibration(z, u)
    assert fit.condition_number is not None and np.isfinite(fit.condition_number)
    assert fit.covariance is not None
    assert fit.a_std is not None and fit.a_std > 0


def test_not_estimable_inverse_is_refused() -> None:
    fit = fit_distance_calibration(np.array([100.0, 200.0]), np.array([1000.0, 800.0]))
    depth, status, message = fit.inverse(900.0)
    assert depth is None
    assert status is Status.NOT_ESTIMABLE
    assert "not estimable" in message
