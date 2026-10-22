"""One-at-a-time sensitivity sweep: ``0, ±1σ, ±2σ, ±3σ`` per variable.

Two responses are reported for every level, because they answer different
questions:

* ``strategy_A`` - no recalibration.  The raw sensitivity of the instrument to
  that assembly error.
* ``strategy_B`` - per-unit recalibration.  What survives the correction.

Reporting only one of them would make either the tolerance or the calibration
look better than it is.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from optisys.calibration.assembly_strategies import fit_calibration
from optisys.config_g2 import ResolvedG2Config
from optisys.errors import Status
from optisys.evaluation.metrics import BLOCKING_FLAGS, parse_flags
from optisys.tolerance.perturbations import (
    AssemblyPerturbation,
    AssemblyState,
    NOMINAL_ASSEMBLY_ID,
    make_assembly,
    perturbation_sigmas,
)

LEVELS = (0.0, -1.0, 1.0, -2.0, 2.0, -3.0, 3.0)


@dataclass
class OatRow:
    variable: str
    sigma_level: float
    perturbation_value: float
    unit: str
    n_attempted: int
    n_valid_A: int
    rmse_A_mm: float | None
    bias_A_mm: float | None
    p95_A_mm: float | None
    n_valid_B: int
    rmse_B_mm: float | None
    bias_B_mm: float | None
    p95_B_mm: float | None
    mean_ray_success: float
    mean_capture: float
    mean_kernel_support: float
    mean_spot_sigma_px: float | None
    mean_peak_e: float
    saturation_fraction: float
    failure_rate_A: float
    failure_rate_B: float

    def to_row(self) -> dict[str, Any]:
        return {
            "variable": self.variable,
            "sigma_level": self.sigma_level,
            "perturbation_value": self.perturbation_value,
            "unit": self.unit,
            "n_attempted": self.n_attempted,
            "n_valid_A": self.n_valid_A,
            "rmse_A_mm": self.rmse_A_mm,
            "bias_A_mm": self.bias_A_mm,
            "p95_A_mm": self.p95_A_mm,
            "n_valid_B": self.n_valid_B,
            "rmse_B_mm": self.rmse_B_mm,
            "bias_B_mm": self.bias_B_mm,
            "p95_B_mm": self.p95_B_mm,
            "mean_ray_success": self.mean_ray_success,
            "mean_capture": self.mean_capture,
            "mean_kernel_support": self.mean_kernel_support,
            "mean_spot_sigma_px": self.mean_spot_sigma_px,
            "mean_peak_e": self.mean_peak_e,
            "saturation_fraction": self.saturation_fraction,
            "failure_rate_A": self.failure_rate_A,
            "failure_rate_B": self.failure_rate_B,
        }


def _perturb(variable: str, value: float) -> AssemblyPerturbation:
    kwargs = {
        "d_baseline_mm": 0.0, "d_theta_rad": 0.0, "d_focal_relative": 0.0,
        "d_cx_px": 0.0, "d_focus_mm": 0.0,
    }
    kwargs[variable] = value
    return AssemblyPerturbation(assembly_id=f"OAT_{variable}_{value:.6g}", **kwargs)


def _errors(records: list[dict[str, Any]], fit) -> tuple[list[float], int, int]:
    errors = []
    valid = 0
    for record in records:
        if record["status"] != Status.OK.value or record["u_hat_px"] is None:
            continue
        z_hat, status, _ = fit.inverse(float(record["u_hat_px"]))
        flags = parse_flags(record.get("flags"))
        if status is Status.OK and z_hat is not None and not (flags & BLOCKING_FLAGS):
            errors.append(float(z_hat - record["z_gt_mm"]))
            valid += 1
    return errors, valid, len(records)


def run_oat(config: ResolvedG2Config, runner, *,
            distances: tuple[float, ...] = (105.0, 130.0, 180.0, 230.0, 285.0),
            condition: str = "medium", estimator: str = "gaussian_2d",
            calibration_distances: tuple[float, ...] = (100.0, 150.0, 200.0, 250.0, 300.0),
            ) -> list[OatRow]:
    sigmas = perturbation_sigmas(config.tolerance)
    condition_spec = next(c for c in config.dataset.conditions if c.name == condition)

    nominal = make_assembly(AssemblyPerturbation(assembly_id=NOMINAL_ASSEMBLY_ID), config)
    nominal_fit = _fit_assembly(config, runner, nominal, condition_spec,
                                calibration_distances, estimator)

    rows: list[OatRow] = []
    for variable, sigma in sigmas.items():
        for level in LEVELS:
            value = level * sigma
            perturbation = _perturb(variable, value)
            assembly = make_assembly(perturbation, config)
            records: list[dict[str, Any]] = []
            ray_success, capture, support, peaks, saturations = [], [], [], [], []
            for distance in distances:
                outcome = runner.run_scene(
                    assembly, distance, condition_spec, repeat=0, seed_namespace="G2P",
                )
                estimate = outcome.estimates[estimator]
                records.append({
                    "z_gt_mm": distance, "u_hat_px": estimate["u_hat_px"],
                    "status": estimate["status"], "flags": estimate["flags"],
                })
                ray_success.append(outcome.ray_success_fraction)
                capture.append(outcome.capture_fraction)
                support.append(outcome.kernel_support)
                peaks.append(outcome.peak_expected_e)
                saturations.append(max(outcome.saturation_full_well, outcome.saturation_adc))
            unit_fit = _fit_assembly(config, runner, assembly, condition_spec,
                                     calibration_distances, estimator)

            errors_a, valid_a, attempted = _errors(records, nominal_fit)
            errors_b, valid_b, _ = _errors(records, unit_fit)
            rows.append(OatRow(
                variable=variable, sigma_level=level, perturbation_value=value,
                unit={"theta_deg": "rad", "focal_relative": "-", "cx_px": "px"}.get(
                    variable, "mm"),
                n_attempted=attempted, n_valid_A=valid_a,
                rmse_A_mm=_rmse(errors_a), bias_A_mm=_mean(errors_a),
                p95_A_mm=_p95(errors_a),
                n_valid_B=valid_b, rmse_B_mm=_rmse(errors_b), bias_B_mm=_mean(errors_b),
                p95_B_mm=_p95(errors_b),
                mean_ray_success=float(np.mean(ray_success)),
                mean_capture=float(np.mean(capture)),
                mean_kernel_support=float(np.mean(support)),
                mean_spot_sigma_px=None,
                mean_peak_e=float(np.mean(peaks)),
                saturation_fraction=float(np.mean(np.array(saturations) > 0)),
                failure_rate_A=1.0 - valid_a / attempted if attempted else 1.0,
                failure_rate_B=1.0 - valid_b / attempted if attempted else 1.0,
            ))
    return rows


def _fit_assembly(config, runner, assembly: AssemblyState, condition,
                  calibration_distances, estimator):
    z_values, u_values = [], []
    for distance in calibration_distances:
        outcome = runner.run_scene(assembly, distance, condition, repeat=0,
                                   seed_namespace="G2P_CAL")
        estimate = outcome.estimates[estimator]
        if estimate["status"] == Status.OK.value and estimate["u_hat_px"] is not None:
            z_values.append(distance)
            u_values.append(float(estimate["u_hat_px"]))
    return fit_calibration(np.array(z_values), np.array(u_values),
                           model=config.calibration.model, estimator=estimator,
                           assembly_id=assembly.assembly_id)


def _rmse(values: list[float]) -> float | None:
    return float(np.sqrt(np.mean(np.array(values) ** 2))) if values else None


def _mean(values: list[float]) -> float | None:
    return float(np.mean(values)) if values else None


def _p95(values: list[float]) -> float | None:
    return float(np.percentile(np.abs(values), 95)) if values else None


def sensitivity_summary(rows: list[OatRow]) -> list[dict[str, Any]]:
    """Finite-difference sensitivity from the ±1σ and ±2σ points."""

    out: list[dict[str, Any]] = []
    by_variable: dict[str, list[OatRow]] = {}
    for row in rows:
        by_variable.setdefault(row.variable, []).append(row)
    for variable, items in sorted(by_variable.items()):
        lookup = {item.sigma_level: item for item in items}
        record: dict[str, Any] = {"variable": variable}
        for tag, metric in (("A", "rmse_A_mm"), ("B", "rmse_B_mm")):
            values = []
            for level in (-2.0, -1.0, 1.0, 2.0):
                item = lookup.get(level)
                if item is not None and getattr(item, metric) is not None:
                    values.append((level, getattr(item, metric)))
            if len(values) >= 2:
                slopes = [value / level for level, value in values if level != 0]
                record[f"d_rmse_{tag}_per_sigma_mm"] = float(np.mean(slopes))
                record[f"rmse_{tag}_max_over_sweep_mm"] = float(
                    max(v for _, v in values)
                )
        record["saturation_any"] = bool(any(item.saturation_fraction > 0 for item in items))
        out.append(record)
    return out
