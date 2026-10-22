"""Derivative tests: analytic versus finite differences of the reference chain.

The sign check is intentional.  PDF page 8 equation (3) prints
``dZ/du = +Z^2/(fx B)`` while equation (2) differentiates to ``-Z^2/(fx B)``.
Under the stated coordinate convention the signed derivative is negative; the
printed number is the magnitude.  See docs/SPEC_DISCREPANCIES.md (SD-001).
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from optisys.geometry.coplanar import CoplanarGeometry
from optisys.geometry.reference import ReferenceModel


@pytest.mark.parametrize("theta_deg", [-3.0, 0.0, 3.0])
@pytest.mark.parametrize("Z_mm", [100.0, 150.0, 200.0, 250.0, 300.0])
def test_du_dZ_matches_finite_difference(config, theta_deg: float, Z_mm: float) -> None:
    spec = replace(config.geometry, theta_rad=float(np.deg2rad(theta_deg)))
    geom = CoplanarGeometry(spec)
    reference = ReferenceModel(spec)

    analytic = geom.du_dZ(Z_mm)
    numeric = reference.d_u_d_Z(Z_mm)
    assert numeric == pytest.approx(analytic, rel=1e-7)


@pytest.mark.parametrize("Z_mm", [100.0, 200.0, 300.0])
def test_dZ_du_matches_inverse_finite_difference(config, Z_mm: float) -> None:
    geom = CoplanarGeometry(config.geometry)
    reference = ReferenceModel(config.geometry)

    analytic = geom.dZ_du(Z_mm)
    numeric = reference.d_Z_d_u(Z_mm, du_px=1e-3)
    assert numeric == pytest.approx(analytic, rel=1e-6)


@pytest.mark.parametrize("Z_mm", [100.0, 200.0, 300.0])
def test_derivatives_are_reciprocal(config, Z_mm: float) -> None:
    geom = CoplanarGeometry(config.geometry)
    product = geom.du_dZ(Z_mm) * geom.dZ_du(Z_mm)
    assert product == pytest.approx(1.0, rel=1e-12)


def test_signed_derivatives_are_negative_for_positive_baseline(config) -> None:
    geom = CoplanarGeometry(config.geometry)
    for Z in (100.0, 200.0, 300.0):
        assert geom.du_dZ(Z) < 0.0
        assert geom.dZ_du(Z) < 0.0
        assert geom.abs_sensitivity(Z) == pytest.approx(-geom.dZ_du(Z), rel=0)


def test_sensitivity_magnitude_matches_pdf_definition(config) -> None:
    geom = CoplanarGeometry(config.geometry)
    for Z in (100.0, 200.0, 300.0):
        expected = Z**2 / (config.fx_px * config.baseline_mm)
        assert geom.abs_sensitivity(Z) == pytest.approx(expected, rel=1e-14)


def test_sensitivity_is_independent_of_theta(config) -> None:
    """|dZ/du| = Z^2/(fx B) contains no theta; the model claims that explicitly."""

    base = CoplanarGeometry(config.geometry)
    tilted = CoplanarGeometry(replace(config.geometry, theta_rad=float(np.deg2rad(3.0))))
    for Z in (100.0, 200.0, 300.0):
        assert tilted.abs_sensitivity(Z) == pytest.approx(base.abs_sensitivity(Z), rel=1e-15)


def test_derivative_rejects_invalid_depth(config) -> None:
    geom = CoplanarGeometry(config.geometry)
    for bad in (0.0, -1.0, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            geom.du_dZ(bad)
        with pytest.raises(ValueError):
            geom.dZ_du(bad)
