"""Independent reference implementations used to cross-check the analytic model.

These routines deliberately avoid the closed-form expressions of
``optisys.geometry.coplanar``:

1. the laser direction is produced by a rotation matrix acting on ``(0,0,1)``,
   not by ``tan(theta)``;
2. the intersection point is obtained by solving a 3x3 linear system for an
   arbitrary three-point plane representation, not by a dot-product / tangent
   formula;
3. the image coordinate is produced by a homogeneous 3x4 pinhole camera matrix
   ``K [R|t]``, not by the scalar projection equation;
4. depth inversion uses Brent root finding on the reference forward model,
   not the closed-form inverse.

They are intentionally slower than the analytic path and are used for
verification, not production.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import brentq

from optisys.geometry.coplanar import CoplanarSpec


def rotation_y(angle_rad: float) -> np.ndarray:
    """Right-handed rotation matrix about +Y."""

    c, s = np.cos(angle_rad), np.sin(angle_rad)
    return np.array([[c, 0.0, s], [0.0, 1.0, 0.0], [-s, 0.0, c]], dtype=float)


def laser_direction(theta_rad: float) -> np.ndarray:
    """Unit laser direction: ``+Z`` tilted toward ``-X`` by ``theta``.

    Uses a rotation by ``-theta`` about +Y applied to ``(0,0,1)`` so that the
    result is ``(-sin(theta), 0, cos(theta))`` without calling ``tan``.
    """

    return rotation_y(-theta_rad) @ np.array([0.0, 0.0, 1.0])


def plane_points_for_depth(Z_mm: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Three non-collinear points spanning the plane ``Z = Z_mm``.

    The in-plane basis is deliberately oblique (not axis aligned) so that the
    subsequent linear solve is a genuine 3x3 solve.
    """

    p1 = np.array([0.0, 0.0, Z_mm])
    p2 = np.array([1.0, 0.3, Z_mm])
    p3 = np.array([-0.2, 1.0, Z_mm])
    return p1, p2, p3


def intersect_ray_plane_solve(
    origin: np.ndarray,
    direction: np.ndarray,
    Z_mm: np.ndarray | float,
) -> np.ndarray:
    """Intersect one ray with planes ``Z = const`` by a batched 3x3 solve."""

    Z = np.atleast_1d(np.asarray(Z_mm, dtype=float))
    n = Z.size
    P0 = np.asarray(origin, dtype=float)
    d = np.asarray(direction, dtype=float)

    p1 = np.stack([np.zeros(n), np.zeros(n), Z], axis=1)
    p2 = np.stack([np.ones(n), np.full(n, 0.3), Z], axis=1)
    p3 = np.stack([np.full(n, -0.2), np.ones(n), Z], axis=1)

    e1 = p2 - p1
    e2 = p3 - p1
    # M [t, a, b]^T = p1 - P0, with columns (d, -e1, -e2).
    M = np.stack([np.broadcast_to(d, (n, 3)), -e1, -e2], axis=2)
    rhs = (p1 - P0).reshape(n, 3)

    # NumPy >= 2.0 treats rhs with ndim == 2 as a matrix; keep an explicit
    # trailing axis so the batched solve uses signature (m,m),(m,n)->(m,n).
    solution = np.linalg.solve(M, rhs[:, :, None])[:, :, 0]
    t = solution[:, 0]
    return P0[None, :] + t[:, None] * d[None, :]


def intrinsic_matrix(fx_px: float, fy_px: float, cx_px: float, cy_px: float) -> np.ndarray:
    """3x3 pinhole intrinsic matrix."""

    return np.array(
        [[fx_px, 0.0, cx_px], [0.0, fy_px, cy_px], [0.0, 0.0, 1.0]], dtype=float
    )


def project_points(K: np.ndarray, R: np.ndarray, tvec: np.ndarray, points: np.ndarray) -> np.ndarray:
    """Project world points through the homogeneous 3x4 camera matrix ``K [R|t]``."""

    pts = np.atleast_2d(np.asarray(points, dtype=float))
    P = np.asarray(K, dtype=float) @ np.hstack([np.asarray(R, dtype=float),
                                                np.asarray(tvec, dtype=float).reshape(3, 1)])
    homogeneous = np.hstack([pts, np.ones((pts.shape[0], 1))])
    uvw = homogeneous @ P.T
    w = uvw[:, 2]
    if np.any(w == 0.0):
        raise ZeroDivisionError("point on the camera plane (w = 0)")
    return uvw[:, :2] / w[:, None]


@dataclass(frozen=True)
class ReferenceForward:
    """Reference forward model output for one depth."""

    Z_mm: float
    X_mm: float
    Y_mm: float
    u_px: float
    v_px: float


class ReferenceModel:
    """Independent geometry chain built from vectors and matrices only."""

    def __init__(self, spec: CoplanarSpec) -> None:
        self.spec = spec
        self.origin = np.array([spec.baseline_mm, 0.0, 0.0])
        self.direction = laser_direction(spec.theta_rad)
        self.K = intrinsic_matrix(spec.fx_px, spec.fx_px, spec.cx_px, spec.cy_px)
        self.R = np.eye(3)
        self.t = np.zeros(3)

    def intersect(self, Z_mm: np.ndarray | float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        points = intersect_ray_plane_solve(self.origin, self.direction, Z_mm)
        return points[:, 0], points[:, 1], points[:, 2]

    def forward(self, Z_mm: np.ndarray | float) -> tuple[np.ndarray, np.ndarray]:
        """Return ``(u_px, v_px)`` from the matrix projection chain."""

        X, Y, Z = self.intersect(Z_mm)
        uv = project_points(self.K, self.R, self.t, np.stack([X, Y, Z], axis=1))
        return uv[:, 0], uv[:, 1]

    def forward_one(self, Z_mm: float) -> ReferenceForward:
        X, Y, Z = self.intersect(Z_mm)
        u, v = self.forward(Z_mm)
        return ReferenceForward(float(Z[0]), float(X[0]), float(Y[0]), float(u[0]), float(v[0]))

    def invert(self, u_px: float) -> float:
        """Invert one image column by Brent root finding on this forward model."""

        spec = self.spec

        def residual(Z: float) -> float:
            return float(self.forward(Z)[0][0]) - u_px

        lo, hi = 0.5 * spec.z_min_mm, 2.0 * spec.z_max_mm
        if residual(lo) * residual(hi) > 0.0:
            raise ValueError("u is outside the reference model's monotone range")
        return float(brentq(residual, lo, hi, xtol=1e-13, rtol=4.0 * np.finfo(float).eps, maxiter=200))

    def d_u_d_Z(self, Z_mm: float, h_mm: float | None = None) -> float:
        """Central finite difference of the reference forward model."""

        h = h_mm if h_mm is not None else max(1e-6, 1e-6 * abs(Z_mm))
        u_plus, _ = self.forward(Z_mm + h)
        u_minus, _ = self.forward(Z_mm - h)
        return float((u_plus[0] - u_minus[0]) / (2.0 * h))

    def d_Z_d_u(self, Z_mm: float, du_px: float = 1.0e-3) -> float:
        """Central finite difference of the reference inverse, in mm/pixel."""

        u0 = float(self.forward(Z_mm)[0][0])
        return float((self.invert(u0 + du_px) - self.invert(u0 - du_px)) / (2.0 * du_px))
