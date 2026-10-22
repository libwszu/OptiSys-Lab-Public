"""Nominal and robust objectives, evaluated on the frozen panels.

Units
-----
Errors are in **mm**; failure rate is dimensionless.  The objective divides
each term by a pre-registered reference scale so no term dominates because of
its unit.  A raw weighted sum in mixed units would be meaningless.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Sequence

import numpy as np

from optisys.calibration.assembly_strategies import CalibrationFit, fit_calibration
from optisys.config_g2 import ResolvedG2Config
from optisys.evaluation.metrics import BLOCKING_FLAGS, parse_flags
from optisys.errors import Status
from optisys.optimization.search_space import Design
from optisys.tolerance.perturbations import AssemblyState


@dataclass
class DesignMetrics:
    design: Design
    feasible: bool
    reason: str
    n_attempted: int = 0
    n_valid: int = 0
    failure_rate: float = 1.0
    rmse_mm: float | None = None
    p95_mm: float | None = None
    bias_mm: float | None = None
    mean_assembly_rmse_mm: float | None = None
    j_value: float | None = None
    frames: int = 0
    wall_s: float = 0.0
    calibration_params: dict[str, list[float]] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_row(self) -> dict[str, Any]:
        return {
            **self.design.as_row(),
            "feasible": self.feasible,
            "reason": self.reason,
            "n_attempted": self.n_attempted,
            "n_valid": self.n_valid,
            "failure_rate": self.failure_rate,
            "rmse_mm": self.rmse_mm,
            "p95_mm": self.p95_mm,
            "bias_mm": self.bias_mm,
            "mean_assembly_rmse_mm": self.mean_assembly_rmse_mm,
            "j_value": self.j_value,
            "frames": self.frames,
            "wall_s": self.wall_s,
        }


def _valid(estimate: dict[str, Any], z_hat: float | None) -> bool:
    if estimate.get("status") != Status.OK.value:
        return False
    if z_hat is None or not np.isfinite(z_hat):
        return False
    flags = parse_flags(estimate.get("flags"))
    return not (flags & BLOCKING_FLAGS)


class DesignEvaluator:
    """Evaluate one design under strategy A (factory nominal calibration)."""

    def __init__(self, config: ResolvedG2Config, runner, *,
                 calibration_distances: Sequence[float],
                 evaluation_distances: Sequence[float],
                 conditions: Sequence[str],
                 estimator: str = "gaussian_2d") -> None:
        self.config = config
        self.runner = runner
        self.calibration_distances = tuple(float(v) for v in calibration_distances)
        self.evaluation_distances = tuple(float(v) for v in evaluation_distances)
        self.conditions = tuple(conditions)
        self.estimator = estimator
        self.frame_count = 0
        self.calibration_calls = 0

    # ------------------------------------------------------------------
    def _condition(self, name: str):
        match = [c for c in self.config.dataset.conditions if c.name == name]
        if not match:
            raise ValueError(f"unknown condition {name!r}")
        return match[0]

    def fit_factory_calibration(self, design: Design,
                                assembly: AssemblyState) -> dict[str, CalibrationFit]:
        """Fit on the **nominal** unit of this design, medium condition."""

        condition = self._condition("medium")
        z_values, u_values = [], []
        for distance in self.calibration_distances:
            outcome = self.runner.run_scene(
                assembly, distance, condition, repeat=0,
                seed_namespace=f"G2C|{design.key()}", collect_estimates=True,
            )
            self.frame_count += 1
            self.calibration_calls += 1
            estimate = outcome.estimates[self.estimator]
            if estimate["status"] == Status.OK.value and estimate["u_hat_px"] is not None:
                z_values.append(distance)
                u_values.append(float(estimate["u_hat_px"]))
        fit = fit_calibration(np.array(z_values), np.array(u_values),
                              model=self.config.calibration.model,
                              estimator=self.estimator, assembly_id=assembly.assembly_id)
        return {self.estimator: fit}

    def _score(self, fit: CalibrationFit, outcomes: list[tuple[float, Any]]
               ) -> tuple[np.ndarray, np.ndarray, int]:
        errors: list[float] = []
        assembly_ids: list[str] = []
        attempted = 0
        for distance, outcome in outcomes:
            estimate = outcome.estimates[self.estimator]
            attempted += 1
            z_hat, status, _ = fit.inverse(estimate["u_hat_px"]) \
                if estimate["u_hat_px"] is not None else (None, Status.NOT_ESTIMABLE, "")
            ok = _valid(estimate, z_hat)
            if ok:
                errors.append(float(z_hat - distance))
                assembly_ids.append(outcome.assembly_id)
        return np.array(errors, dtype=float), np.array(assembly_ids), attempted

    def _metrics(self, design: Design, fit: CalibrationFit,
                 outcomes: list[tuple[float, Any]], fallback_reason: str,
                 wall_s: float) -> DesignMetrics:
        errors, assembly_ids, attempted = self._score(fit, outcomes)
        n_valid = int(errors.size)
        failure = 1.0 - n_valid / attempted if attempted else 1.0
        if n_valid == 0:
            return DesignMetrics(
                design=design, feasible=True, reason="NO_VALID_FRAMES",
                n_attempted=attempted, n_valid=0, failure_rate=1.0,
                frames=self.frame_count, wall_s=wall_s,
                calibration_params={self.estimator: list(fit.params)},
            )
        rmse = float(np.sqrt(np.mean(errors**2)))
        p95 = float(np.percentile(np.abs(errors), 95))
        by_assembly = {}
        for value, assembly_id in zip(errors, assembly_ids):
            by_assembly.setdefault(assembly_id, []).append(value)
        per_unit = [float(np.sqrt(np.mean(np.array(values) ** 2)))
                    for values in by_assembly.values()]
        return DesignMetrics(
            design=design, feasible=True, reason=fallback_reason,
            n_attempted=attempted, n_valid=n_valid, failure_rate=failure,
            rmse_mm=rmse, p95_mm=p95, bias_mm=float(np.mean(errors)),
            mean_assembly_rmse_mm=float(np.mean(per_unit)),
            frames=self.frame_count, wall_s=wall_s,
            calibration_params={self.estimator: list(fit.params)},
        )

    # ------------------------------------------------------------------
    def evaluate_nominal(self, design: Design, assembly: AssemblyState) -> DesignMetrics:
        started = time.perf_counter()
        self.frame_count = 0
        fits = self.fit_factory_calibration(design, assembly)
        fit = fits[self.estimator]
        outcomes: list[tuple[float, Any]] = []
        for condition_name in self.conditions:
            condition = self._condition(condition_name)
            for distance in self.evaluation_distances:
                outcomes.append((
                    distance,
                    self.runner.run_scene(assembly, distance, condition, repeat=0,
                                          seed_namespace=f"G2S|{design.key()}"),
                ))
                self.frame_count += 1
        metrics = self._metrics(design, fit, outcomes, "FEASIBLE", time.perf_counter() - started)
        if metrics.rmse_mm is not None:
            obj = self.config.objective
            metrics.j_value = metrics.rmse_mm / obj.rmse_ref_mm
        return metrics

    def evaluate_robust(self, design: Design, assemblies: list[AssemblyState],
                        nominal: AssemblyState) -> DesignMetrics:
        started = time.perf_counter()
        self.frame_count = 0
        fits = self.fit_factory_calibration(design, nominal)
        fit = fits[self.estimator]
        outcomes: list[tuple[float, Any]] = []
        for assembly in assemblies:
            for condition_name in self.conditions:
                condition = self._condition(condition_name)
                for distance in self.evaluation_distances:
                    outcomes.append((
                        distance,
                        self.runner.run_scene(assembly, distance, condition, repeat=0,
                                              seed_namespace=f"G2S|{design.key()}"),
                    ))
                    self.frame_count += 1
        metrics = self._metrics(design, fit, outcomes, "FEASIBLE", time.perf_counter() - started)
        if metrics.rmse_mm is not None:
            obj = self.config.objective
            mean_rmse = metrics.mean_assembly_rmse_mm or metrics.rmse_mm
            metrics.j_value = (
                obj.w_mean_rmse * mean_rmse / obj.rmse_ref_mm
                + obj.w_p95 * metrics.p95_mm / obj.p95_ref_mm
                + obj.w_failure * metrics.failure_rate / obj.failure_ref
            )
        return metrics
