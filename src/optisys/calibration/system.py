"""System distance calibration.

The one-dimensional data only identify the combinations

    u(Z) = a / Z + b,     a = fx * B,   b = cx - fx * tan(theta)

so this module estimates exactly two parameters.  It never claims that
``B, fx, cx, theta`` are separately identifiable from a single Z-u curve.
Camera-intrinsic calibration is a different problem and is not part of G1.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from optisys.errors import Status


@dataclass
class DistanceCalibration:
    a_px_mm: float | None
    b_px: float | None
    a_std: float | None
    b_std: float | None
    covariance: list[list[float]] | None
    condition_number: float | None
    n_points: int
    z_min_mm: float
    z_max_mm: float
    residual_rms_px: float | None
    status: Status
    method: str
    message: str = ""
    identifiability: str = (
        "Only a = fx*B [px*mm] and b = cx - fx*tan(theta) [px] are identifiable "
        "from one-dimensional Z-u data."
    )

    def inverse(self, u_px: float) -> tuple[float | None, Status, str]:
        if self.status is not Status.OK or self.a_px_mm is None or self.b_px is None:
            return None, Status.NOT_ESTIMABLE, "calibration is not estimable"
        u = float(u_px)
        if not np.isfinite(u):
            return None, Status.NONFINITE_INPUT, "u must be finite"
        denominator = u - self.b_px
        if abs(denominator) < 1e-9:
            return None, Status.SINGULAR_GEOMETRY, "u equals b; inversion is singular"
        depth = self.a_px_mm / denominator
        if not np.isfinite(depth) or depth <= 0:
            return None, Status.INVALID_DEPTH, "denominator sign implies Z <= 0"
        if not (self.z_min_mm <= depth <= self.z_max_mm):
            return None, Status.OUT_OF_RANGE, "Z outside the calibrated range"
        return float(depth), Status.OK, "ok"

    def to_dict(self) -> dict:
        return {
            "a_px_mm": self.a_px_mm,
            "b_px": self.b_px,
            "a_std": self.a_std,
            "b_std": self.b_std,
            "covariance": self.covariance,
            "condition_number": self.condition_number,
            "n_points": self.n_points,
            "z_range_mm": [self.z_min_mm, self.z_max_mm],
            "residual_rms_px": self.residual_rms_px,
            "status": self.status.value,
            "method": self.method,
            "message": self.message,
            "identifiability": self.identifiability,
        }


def fit_distance_calibration(z_mm: np.ndarray, u_px: np.ndarray,
                             method: str = "linear_1_over_z") -> DistanceCalibration:
    z = np.asarray(z_mm, dtype=float)
    u = np.asarray(u_px, dtype=float)
    if z.shape != u.shape:
        raise ValueError("z and u must have the same shape")
    finite = np.isfinite(z) & np.isfinite(u) & (z > 0)
    z, u = z[finite], u[finite]
    n = int(z.size)
    z_min = float(z.min()) if n else float("nan")
    z_max = float(z.max()) if n else float("nan")

    if n < 3 or np.unique(z).size < 3:
        return DistanceCalibration(
            None, None, None, None, None, None, n, z_min, z_max, None,
            Status.NOT_ESTIMABLE, method,
            f"need at least 3 distinct distances, got {np.unique(z).size}",
        )

    x = 1.0 / z
    design = np.column_stack([x, np.ones_like(x)])
    solution, residuals, rank, _ = np.linalg.lstsq(design, u, rcond=None)
    a, b = float(solution[0]), float(solution[1])
    if rank < 2 or a <= 0:
        return DistanceCalibration(
            a, b, None, None, None, float(np.linalg.cond(design)), n, z_min, z_max,
            float(np.sqrt(np.mean(residuals**2))) if residuals.size else None,
            Status.NOT_ESTIMABLE, method,
            "design matrix is rank deficient or a <= 0",
        )

    prediction = design @ solution
    residual = u - prediction
    dof = max(n - 2, 1)
    sigma2 = float(residual @ residual / dof)
    covariance = sigma2 * np.linalg.inv(design.T @ design)
    condition = float(np.linalg.cond(design))

    return DistanceCalibration(
        a_px_mm=a,
        b_px=b,
        a_std=float(np.sqrt(covariance[0, 0])),
        b_std=float(np.sqrt(covariance[1, 1])),
        covariance=covariance.tolist(),
        condition_number=condition,
        n_points=n,
        z_min_mm=z_min,
        z_max_mm=z_max,
        residual_rms_px=float(np.sqrt(np.mean(residual**2))),
        status=Status.OK,
        method=method,
        message="ok",
    )


def oracle_calibration(fx_px: float, baseline_mm: float, cx_px: float,
                       theta_rad: float, z_min_mm: float, z_max_mm: float
                       ) -> DistanceCalibration:
    """Simulation oracle: the known geometry parameters, never used for calibration."""

    a = fx_px * baseline_mm
    b = cx_px - fx_px * np.tan(theta_rad)
    return DistanceCalibration(
        a_px_mm=float(a),
        b_px=float(b),
        a_std=0.0,
        b_std=0.0,
        covariance=[[0.0, 0.0], [0.0, 0.0]],
        condition_number=None,
        n_points=0,
        z_min_mm=z_min_mm,
        z_max_mm=z_max_mm,
        residual_rms_px=0.0,
        status=Status.OK,
        method="oracle_geometry",
        message="known simulation parameters (baseline reference only)",
    )
