"""Forward-model tests against the closed-form contract.

These tests check internal consistency of the analytic chain.  Independent
verification lives in ``test_independent_chain.py``.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from optisys.geometry.coplanar import CoplanarGeometry, CoplanarSpec


@pytest.mark.parametrize("Z_mm", [100.0, 150.0, 200.0, 250.0, 300.0])
def test_theta_zero_offset_equals_fx_b_over_z(config, Z_mm: float) -> None:
    geom = CoplanarGeometry(config.geometry)
    result = geom.forward(Z_mm)
    assert result.status.value == "OK"
    assert result.u_px - config.cx_px == pytest.approx(
        config.fx_px * config.baseline_mm / Z_mm, rel=1e-14
    )
    assert result.X_mm == pytest.approx(config.baseline_mm, rel=0, abs=1e-15)


@pytest.mark.parametrize("theta_deg", [-3.0, -1.5, 0.0, 1.5, 3.0])
@pytest.mark.parametrize("Z_mm", [100.0, 200.0, 300.0])
def test_tilted_beam_matches_contract(config, theta_deg: float, Z_mm: float) -> None:
    spec = replace(config.geometry, theta_rad=float(np.deg2rad(theta_deg)))
    geom = CoplanarGeometry(spec)
    result = geom.forward(Z_mm)
    assert result.status.value == "OK"
    tan_theta = np.tan(np.deg2rad(theta_deg))
    assert result.X_mm == pytest.approx(config.baseline_mm - Z_mm * tan_theta, abs=1e-12)
    assert result.u_px == pytest.approx(
        config.cx_px + config.fx_px * (config.baseline_mm / Z_mm - tan_theta), abs=1e-10
    )


def test_v_is_constant_on_the_principal_row(config) -> None:
    geom = CoplanarGeometry(config.geometry)
    for Z in (100.0, 200.0, 300.0):
        assert geom.forward(Z).v_px == config.cy_px


def test_vectorised_matches_scalar(config) -> None:
    geom = CoplanarGeometry(config.geometry)
    z = np.linspace(config.z_min_mm, config.z_max_mm, 41)
    batch = geom.forward_many(z)
    scalar = [geom.forward(float(value)) for value in z]
    np.testing.assert_allclose(batch.u_px, [item.u_px for item in scalar], rtol=0, atol=1e-12)
    np.testing.assert_allclose(batch.X_mm, [item.X_mm for item in scalar], rtol=0, atol=1e-12)
    assert batch.statuses() == [item.status for item in scalar]
    assert np.all(batch.visible)


def test_vectorised_status_decoding(config) -> None:
    geom = CoplanarGeometry(config.geometry)
    batch = geom.forward_many(np.array([float("nan"), 0.0, -5.0, 50.0, 200.0, 301.0]))
    assert [status.value for status in batch.statuses()] == [
        "NONFINITE_INPUT", "INVALID_DEPTH", "INVALID_DEPTH", "OUT_OF_RANGE", "OK", "OUT_OF_RANGE"
    ]
    assert np.isnan(batch.u_px[0])
    assert not batch.visible[0]
    assert batch.visible[4]


def test_shapes_are_preserved(config) -> None:
    geom = CoplanarGeometry(config.geometry)
    z = np.full((3, 4), 200.0)
    batch = geom.forward_many(z)
    assert batch.u_px.shape == (3, 4)
    assert batch.status_code.shape == (3, 4)


def test_spec_rejects_nonphysical_values() -> None:
    with pytest.raises(ValueError, match="baseline_mm"):
        CoplanarSpec(
            baseline_mm=0.0, theta_rad=0.0, fx_px=2300.0, cx_px=640.0, cy_px=512.0,
            width_px=1280, height_px=1024, z_min_mm=100.0, z_max_mm=300.0,
        )
    with pytest.raises(ValueError, match="z_min_mm"):
        CoplanarSpec(
            baseline_mm=20.0, theta_rad=0.0, fx_px=2300.0, cx_px=640.0, cy_px=512.0,
            width_px=1280, height_px=1024, z_min_mm=300.0, z_max_mm=100.0,
        )
