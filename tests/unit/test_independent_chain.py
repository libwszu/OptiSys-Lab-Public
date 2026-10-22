"""V0: analytic chain versus an independent vector/matrix chain.

Deliberately independent construction:

* laser direction from a rotation matrix, no ``tan``;
* intersection by a batched 3x3 linear solve on a three-point plane;
* projection by a homogeneous 3x4 camera matrix;
* inversion by Brent root finding.

The gate tolerance is 1e-8 pixel (PDF section 8.2).  The measured residual is
roughly 1e-13 px, i.e. double-precision round-off, and is reported rather than
assumed.
"""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from optisys.evaluation.chain import U_TOLERANCE_PX, X_TOLERANCE_MM
from optisys.geometry.coplanar import CoplanarGeometry
from optisys.geometry.reference import ReferenceModel, laser_direction


@pytest.mark.parametrize("theta_deg", [-3.0, 0.0, 3.0])
def test_projection_matches_independent_chain(config, theta_deg: float) -> None:
    spec = replace(config.geometry, theta_rad=float(np.deg2rad(theta_deg)))
    geom = CoplanarGeometry(spec)
    reference = ReferenceModel(spec)

    z = np.linspace(config.z_min_mm, config.z_max_mm, config.run.distance_points)
    u_ref, v_ref = reference.forward(z)
    batch = geom.forward_many(z)
    assert np.all(batch.visible)

    max_u_error = float(np.max(np.abs(batch.u_px - u_ref)))
    assert max_u_error <= U_TOLERANCE_PX
    assert float(np.max(np.abs(batch.v_px - v_ref))) <= 1e-12


@pytest.mark.parametrize("theta_deg", [-3.0, 0.0, 3.0])
def test_intersection_matches_linear_solve(config, theta_deg: float) -> None:
    spec = replace(config.geometry, theta_rad=float(np.deg2rad(theta_deg)))
    geom = CoplanarGeometry(spec)
    reference = ReferenceModel(spec)

    z = np.linspace(config.z_min_mm, config.z_max_mm, 41)
    X_ref, Y_ref, Z_ref = reference.intersect(z)
    X_analytic = np.array([geom.forward(float(value)).X_mm for value in z])

    assert float(np.max(np.abs(X_analytic - X_ref))) <= X_TOLERANCE_MM
    assert float(np.max(np.abs(Y_ref))) == 0.0
    np.testing.assert_allclose(Z_ref, z, rtol=0, atol=1e-12)


def test_laser_direction_is_constructed_without_tangent() -> None:
    theta = np.deg2rad(3.0)
    direction = laser_direction(theta)
    assert direction[0] == pytest.approx(-np.sin(theta), rel=1e-15)
    assert direction[1] == 0.0
    assert direction[2] == pytest.approx(np.cos(theta), rel=1e-15)
    assert np.linalg.norm(direction) == pytest.approx(1.0, rel=1e-15)


@pytest.mark.parametrize("theta_deg", [-3.0, 0.0, 3.0])
def test_inverse_matches_brent_root_finding(config, theta_deg: float) -> None:
    spec = replace(config.geometry, theta_rad=float(np.deg2rad(theta_deg)))
    geom = CoplanarGeometry(spec)
    reference = ReferenceModel(spec)

    for Z in (100.0, 137.5, 200.0, 262.5, 300.0):
        u_ref = reference.forward_one(Z).u_px
        Z_reference = reference.invert(u_ref)
        Z_analytic = geom.inverse(u_ref)
        assert Z_analytic.status.value == "OK"
        assert abs(Z_analytic.Z_mm - Z) <= 1e-9 * Z
        assert abs(Z_reference - Z) <= 1e-9 * Z
        assert abs(Z_analytic.Z_mm - Z_reference) <= 1e-8


def test_reference_bracket_limits(config) -> None:
    reference = ReferenceModel(config.geometry)
    u_low = reference.forward_one(config.z_min_mm).u_px
    u_high = reference.forward_one(config.z_max_mm).u_px
    assert u_low > u_high  # spot moves toward the principal point with distance
    # The reference is a pure math inverse: it does not enforce the working
    # range, so a slightly larger u simply maps below z_min.
    assert reference.invert(u_low + 10.0) < config.z_min_mm
    with pytest.raises(ValueError, match="monotone range"):
        reference.invert(reference.forward_one(10.0).u_px)


def test_comparison_report_has_no_failures(config) -> None:
    from optisys.evaluation.chain import compare_chain

    comparison = compare_chain(config)
    assert comparison.metrics["n_points"] == 3 * config.run.distance_points
    assert all(check["pass"] for check in comparison.gate_checks.values())
    assert comparison.metrics["max_abs_u_error_px"] <= U_TOLERANCE_PX
    assert comparison.metrics["max_Z_relative_error"] <= 1e-9
