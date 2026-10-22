"""Boundary and pathological-input tests (PDF section 4.3).

Every failure path must return an explicit status and must not emit a
pseudo-precise number that a caller could mistake for a measurement.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from optisys.geometry.coplanar import CoplanarGeometry, CoplanarSpec


def test_zero_baseline_cannot_even_be_constructed(config) -> None:
    with pytest.raises(ValueError, match="B -> 0"):
        replace(config.geometry, baseline_mm=0.0)


def test_baseline_below_declared_minimum_is_rejected(config) -> None:
    spec = replace(config.geometry, baseline_mm=0.5, min_baseline_mm=1.0)
    geom = CoplanarGeometry(spec)
    assert geom.forward(200.0).status.value == "BASELINE_DEGENERATE"
    result = geom.inverse(config.cx_px + 200.0)
    assert result.status.value == "BASELINE_DEGENERATE"
    assert np.isnan(result.Z_mm)


@pytest.mark.parametrize("bad_z", [0.0, -1.0, -300.0])
def test_non_positive_depth_is_rejected(config, bad_z: float) -> None:
    geom = CoplanarGeometry(config.geometry)
    result = geom.forward(bad_z)
    assert result.status.value == "INVALID_DEPTH"
    assert np.isnan(result.u_px)


@pytest.mark.parametrize("bad_z", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_depth_is_rejected(config, bad_z: float) -> None:
    geom = CoplanarGeometry(config.geometry)
    assert geom.forward(bad_z).status.value == "NONFINITE_INPUT"


def test_outside_working_range_is_rejected_not_extrapolated(config) -> None:
    geom = CoplanarGeometry(config.geometry)
    assert geom.forward(50.0).status.value == "OUT_OF_RANGE"
    assert geom.forward(300.5).status.value == "OUT_OF_RANGE"


def test_range_boundaries_are_inclusive(config) -> None:
    geom = CoplanarGeometry(config.geometry)
    assert geom.forward(100.0).status.value == "OK"
    assert geom.forward(300.0).status.value == "OK"
    # round-off guard: a value 1e-9 mm outside is still accepted, 1e-3 mm is not
    assert geom.forward(300.0 + 1e-9).status.value == "OK"
    assert geom.forward(300.0 + 1e-3).status.value == "OUT_OF_RANGE"


def test_singular_denominator_is_refused(config) -> None:
    geom = CoplanarGeometry(config.geometry)
    singular_u = config.cx_px - config.fx_px * np.tan(config.geometry.theta_rad)
    result = geom.inverse(singular_u)
    assert result.status.value == "SINGULAR_GEOMETRY"
    assert np.isnan(result.Z_mm)
    assert np.isnan(result.candidate_Z_mm)

    nearly = geom.inverse(singular_u + 1e-9)
    assert nearly.status.value == "SINGULAR_GEOMETRY"


def test_inverse_never_returns_nan_as_success(config) -> None:
    geom = CoplanarGeometry(config.geometry)
    probes = [
        config.cx_px - config.fx_px * np.tan(config.geometry.theta_rad),
        config.cx_px - 1000.0,
        config.cx_px + 1e9,
        float("nan"),
        float("inf"),
        -1.0,
    ]
    for u in probes:
        result = geom.inverse(float(u))
        if result.status.value == "OK":
            assert np.isfinite(result.Z_mm)
        else:
            assert np.isnan(result.Z_mm)


def test_inverse_out_of_range_keeps_candidate_for_diagnostics(config) -> None:
    geom = CoplanarGeometry(config.geometry)
    u_far = geom.forward(50.0).u_px
    result = geom.inverse(float(u_far))
    assert result.status.value == "OUT_OF_RANGE"
    assert np.isnan(result.Z_mm)
    assert result.candidate_Z_mm == pytest.approx(50.0, rel=1e-12)


def test_spot_outside_sensor_is_flagged(config) -> None:
    # Working-range enforcement is disabled so the sensor check is the subject
    # rather than being pre-empted by OUT_OF_RANGE.
    geom = CoplanarGeometry(replace(config.geometry, enforce_working_range=False))
    result = geom.forward(20.0)
    assert result.status.value == "OUT_OF_SENSOR"
    assert result.visible is False
    assert result.u_px > config.width_px - 1


def test_sensor_edge_is_inclusive(config) -> None:
    geom = CoplanarGeometry(replace(config.geometry, enforce_working_range=False))
    z_edge = config.fx_px * config.baseline_mm / (config.width_px - 1 - config.cx_px)
    assert geom.forward(float(z_edge)).status.value == "OK"
    assert geom.forward(float(z_edge) - 0.01).status.value == "OUT_OF_SENSOR"


def test_sensor_margin_shrinks_valid_area(config) -> None:
    spec = replace(config.geometry, sensor_margin_px=10.0, enforce_working_range=False)
    geom = CoplanarGeometry(spec)
    z_edge = config.fx_px * config.baseline_mm / (config.width_px - 11 - config.cx_px)
    assert geom.forward(float(z_edge)).status.value == "OK"
    assert geom.forward(float(z_edge) - 0.01).status.value == "OUT_OF_SENSOR"


def test_negative_denominator_means_negative_depth(config) -> None:
    geom = CoplanarGeometry(config.geometry)
    result = geom.inverse(config.cx_px - 1000.0)
    assert result.status.value == "INVALID_DEPTH"
    assert result.candidate_Z_mm < 0.0


def test_vectorised_and_scalar_boundaries_agree(config) -> None:
    geom = CoplanarGeometry(config.geometry)
    z = np.array([float("nan"), float("inf"), 0.0, -5.0, 50.0, 99.999, 100.0, 300.0, 301.0])
    batch = geom.forward_many(z)
    for index, value in enumerate(z):
        assert batch.statuses()[index] is geom.forward(float(value)).status
        assert np.isnan(batch.u_px[index]) == np.isnan(geom.forward(float(value)).u_px)


def test_unreachable_angle_is_rejected_at_construction(config) -> None:
    with pytest.raises(ValueError, match="theta"):
        replace(config.geometry, theta_rad=float(np.pi / 2.0))


def test_inverse_rejects_spot_outside_sensor_even_when_depth_is_in_range(config) -> None:
    """Counterexample: Z = 100 mm is valid but B=35 mm, theta=-3 deg puts u off chip."""

    spec = replace(
        config.geometry,
        baseline_mm=35.0,
        theta_rad=float(np.deg2rad(-3.0)),
    )
    geom = CoplanarGeometry(spec)
    forward = geom.forward(100.0)
    assert forward.status.value == "OUT_OF_SENSOR"
    assert forward.u_px > config.width_px - 1

    scalar = geom.inverse(float(forward.u_px))
    assert scalar.status.value == "OUT_OF_SENSOR"
    assert np.isnan(scalar.Z_mm)

    batch = geom.inverse_many(np.array([forward.u_px]))
    assert batch.statuses()[0].value == "OUT_OF_SENSOR"
    assert np.isnan(batch.Z_mm[0])


def test_inverse_rejects_spot_outside_sensor_even_when_depth_is_in_range(config) -> None:
    """Counterexample: Z = 100 mm is valid but B=35 mm, theta=-3 deg puts u off chip."""

    spec = replace(
        config.geometry,
        baseline_mm=35.0,
        theta_rad=float(np.deg2rad(-3.0)),
    )
    geom = CoplanarGeometry(spec)
    forward = geom.forward(100.0)
    assert forward.status.value == "OUT_OF_SENSOR"
    assert forward.u_px > config.width_px - 1

    scalar = geom.inverse(float(forward.u_px))
    assert scalar.status.value == "OUT_OF_SENSOR"
    assert np.isnan(scalar.Z_mm)

    batch = geom.inverse_many(np.array([forward.u_px]))
    assert batch.statuses()[0].value == "OUT_OF_SENSOR"
    assert np.isnan(batch.Z_mm[0])
