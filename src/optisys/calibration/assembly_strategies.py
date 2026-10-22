"""Two strictly separated calibration strategies, plus two model families.

Strategy A - factory nominal calibration
    One fit per (design, estimator) on a *nominal* unit, frozen, then applied
    to every perturbed assembly.  Evaluators never see the assembly truth.

Strategy B - per-unit recalibration
    Every assembly is calibrated from its own generated frames.  The fitter
    only sees measured spot positions, never ``a = fx*B`` from the simulator.

Model families
    M1: ``u = a/Z + b``        (G1 baseline, 2 parameters)
    M2: ``u = a/(Z - c) + b``  (thin-lens motivated, 3 parameters)

M2 is only selected when the validation RMSE improves by the pre-registered
margin.  The choice is recorded before the final test.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

import numpy as np
from scipy.optimize import least_squares

from optisys.errors import Status

STRATEGY_FACTORY = "A"
STRATEGY_PER_UNIT = "B"


@dataclass
class CalibrationFit:
    estimator: str
    model: str
    params: tuple[float, ...]
    z_min_mm: float
    z_max_mm: float
    n_points: int
    residual_rms_px: float
    status: Status
    assembly_id: str = ""
    message: str = ""

    def inverse(self, u_px: float) -> tuple[float | None, Status, str]:
        if self.status is not Status.OK:
            return None, Status.NOT_ESTIMABLE, "calibration is not estimable"
        u = float(u_px)
        if not np.isfinite(u):
            return None, Status.NONFINITE_INPUT, "u must be finite"
        if self.model == "M1":
            a, b = self.params
            denominator = u - b
            if abs(denominator) < 1e-9:
                return None, Status.SINGULAR_GEOMETRY, "u equals b"
            depth = a / denominator
        elif self.model == "M2":
            a, c, b = self.params
            denominator = u - b
            if abs(denominator) < 1e-9:
                return None, Status.SINGULAR_GEOMETRY, "u equals b"
            depth = a / denominator + c
        else:  # pragma: no cover - guarded by construction
            return None, Status.NOT_ESTIMABLE, f"unknown model {self.model}"
        if not np.isfinite(depth) or depth <= 0:
            return None, Status.INVALID_DEPTH, "implied Z <= 0"
        if not (self.z_min_mm <= depth <= self.z_max_mm):
            return None, Status.OUT_OF_RANGE, "Z outside the calibrated range"
        return float(depth), Status.OK, "ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "estimator": self.estimator,
            "model": self.model,
            "params": list(self.params),
            "z_range_mm": [self.z_min_mm, self.z_max_mm],
            "n_points": self.n_points,
            "residual_rms_px": self.residual_rms_px,
            "status": self.status.value,
            "assembly_id": self.assembly_id,
            "message": self.message,
        }


def fit_calibration(z_mm: np.ndarray, u_px: np.ndarray, *, model: str,
                    estimator: str, assembly_id: str = "") -> CalibrationFit:
    z = np.asarray(z_mm, dtype=float)
    u = np.asarray(u_px, dtype=float)
    finite = np.isfinite(z) & np.isfinite(u) & (z > 0)
    z, u = z[finite], u[finite]
    n = int(z.size)
    z_min = float(z.min()) if n else float("nan")
    z_max = float(z.max()) if n else float("nan")
    if n < 3 or np.unique(z).size < 3:
        return CalibrationFit(estimator, model, (), z_min, z_max, n, float("nan"),
                              Status.NOT_ESTIMABLE, assembly_id,
                              f"need >= 3 distinct distances, got {np.unique(z).size}")

    if model == "M1":
        design = np.column_stack([1.0 / z, np.ones_like(z)])
        solution, _, rank, _ = np.linalg.lstsq(design, u, rcond=None)
        a, b = float(solution[0]), float(solution[1])
        if rank < 2 or not np.isfinite(a) or a <= 0:
            return CalibrationFit(estimator, model, (a, b), z_min, z_max, n, float("nan"),
                                  Status.NOT_ESTIMABLE, assembly_id,
                                  "rank deficient or a <= 0")
        residual = u - design @ solution
        return CalibrationFit(estimator, model, (a, b), z_min, z_max, n,
                              float(np.sqrt(np.mean(residual**2))), Status.OK, assembly_id, "ok")

    if model == "M2":
        # M2 degenerates to M1 as c -> 0, so the (a, c) pair is only weakly
        # separated over a 100-300 mm span.  Two things matter:
        #   * the intercept b is the asymptotic value (cx), which lies far
        #     outside the observed u range, so it must NOT be bounded by it;
        #   * c must keep every z - c positive, otherwise the model is singular.
        # A small deterministic multi-start seeded from the M1 solution is used
        # instead of a single local start.
        design = np.column_stack([1.0 / z, np.ones_like(z)])
        linear, _, _, _ = np.linalg.lstsq(design, u, rcond=None)
        a0 = float(linear[0]) if np.isfinite(linear[0]) and linear[0] > 0 else float(
            max(np.ptp(u) * np.mean(z), 1.0)
        )
        b0 = float(linear[1]) if np.isfinite(linear[1]) else float(u.mean())

        span = float(max(np.ptp(u), 1.0))
        lower = [0.0, -max(50.0, 0.5 * z_min), u.min() - 5.0 * span]
        upper = [np.inf, z_min - 1.0, u.max() + 5.0 * span]

        def residual(params: np.ndarray) -> np.ndarray:
            a, c, b = params
            return a / (z - c) + b - u

        best = None
        for c0 in (0.0, 1.0, -1.0, 5.0, -5.0):
            p0 = np.clip(np.array([a0, c0, b0]),
                         np.array(lower) + 1e-9, np.array(upper) - 1e-9)
            try:
                solution = least_squares(residual, p0, bounds=(lower, upper),
                                         max_nfev=800)
            except (ValueError, RuntimeError):  # pragma: no cover
                continue
            cost = float(np.sqrt(np.mean(solution.fun**2)))
            if not np.isfinite(cost):
                continue
            if best is None or cost < best[0]:
                best = (cost, solution)

        if best is None:
            return CalibrationFit(estimator, model, (a0, 0.0, b0), z_min, z_max, n,
                                  float("nan"), Status.NUMERICAL_FAILURE, assembly_id,
                                  "every M2 start failed")
        cost, solution = best
        if not solution.success:
            return CalibrationFit(estimator, model, tuple(float(v) for v in solution.x),
                                  z_min, z_max, n, cost, Status.FIT_NOT_CONVERGED,
                                  assembly_id, "M2 fit did not converge")
        return CalibrationFit(estimator, model, tuple(float(v) for v in solution.x),
                              z_min, z_max, n, cost, Status.OK, assembly_id, "ok")

    raise ValueError(f"unknown calibration model {model!r}")


def select_model(z: np.ndarray, u: np.ndarray, *, estimator: str,
                 min_improvement: float) -> tuple[CalibrationFit, dict[str, Any]]:
    """Compare M1 and M2 on **validation** data and pick one."""

    m1 = fit_calibration(z, u, model="M1", estimator=estimator)
    m2 = fit_calibration(z, u, model="M2", estimator=estimator)
    decision: dict[str, Any] = {
        "estimator": estimator,
        "m1_rms_px": m1.residual_rms_px,
        "m2_rms_px": m2.residual_rms_px,
        "min_improvement": min_improvement,
        "chosen": "M1",
        "reason": "M2 unavailable or not better",
    }
    if m2.status is Status.OK and m1.status is Status.OK and m1.residual_rms_px > 0:
        improvement = 1.0 - m2.residual_rms_px / m1.residual_rms_px
        decision["improvement"] = improvement
        if improvement >= min_improvement:
            decision["chosen"] = "M2"
            decision["reason"] = f"M2 improves validation RMS by {improvement:.1%}"
            return m2, decision
    elif m1.status is not Status.OK and m2.status is Status.OK:
        decision["chosen"] = "M2"
        decision["reason"] = "M1 not estimable, M2 available"
        return m2, decision
    return m1, decision


def calibration_points(records: Iterable[dict[str, Any]], estimator: str
                       ) -> tuple[np.ndarray, np.ndarray]:
    z, u = [], []
    for record in records:
        if record.get("estimator") != estimator:
            continue
        if record.get("status") != Status.OK.value:
            continue
        u_value = record.get("u_hat_px")
        if u_value is None:
            continue
        z.append(float(record["z_gt_mm"]))
        u.append(float(u_value))
    return np.array(z, dtype=float), np.array(u, dtype=float)
