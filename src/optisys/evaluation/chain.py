"""G0 scientific comparison: analytic chain versus independent vector chain.

This module produces the evidence for V0.  The comparison is deliberately
strict:

* the independent chain solves a 3x3 linear system for the ray/plane
  intersection and uses a homogeneous 3x4 camera matrix for projection;
* depth inversion in the reference chain uses Brent root finding;
* derivatives are compared against central finite differences of the
  *reference* chain, not of the analytic one.

All tolerances are declared up front and are part of the gate, not tuned after
seeing the numbers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from optisys.config import ResolvedConfig
from optisys.errors import Status
from optisys.geometry.coplanar import CoplanarGeometry, CoplanarSpec
from optisys.geometry.reference import ReferenceModel

U_TOLERANCE_PX = 1.0e-8
"""PDF section 8.2 / master prompt: independent image-coordinate agreement."""

X_TOLERANCE_MM = 1.0e-9
Z_REL_TOLERANCE = 1.0e-9
DERIVATIVE_REL_TOLERANCE = 1.0e-5
"""Finite-difference limited; central differences at h = 1e-4 * Z."""


@dataclass
class ChainComparison:
    rows: list[dict[str, Any]]
    metrics: dict[str, Any]
    gate_checks: dict[str, Any]


def compare_chain(config: ResolvedConfig) -> ChainComparison:
    z_values = np.linspace(config.z_min_mm, config.z_max_mm, config.run.distance_points)
    theta_offsets_deg = (-3.0, 0.0, 3.0)
    theta_values_deg = [config.theta_deg + offset for offset in theta_offsets_deg]

    rows: list[dict[str, Any]] = []
    for theta_deg in theta_values_deg:
        spec = _spec_with_theta(config.geometry, float(np.deg2rad(theta_deg)))
        geom = CoplanarGeometry(spec)
        ref = ReferenceModel(spec)
        u_ref, v_ref = ref.forward(z_values)
        X_ref, _, _ = ref.intersect(z_values)

        for index, Z in enumerate(z_values):
            forward = geom.forward(float(Z))
            inverse = geom.inverse(float(u_ref[index]))
            analytic_du = geom.du_dZ(float(Z))
            fd_du = ref.d_u_d_Z(float(Z), h_mm=max(1e-4, 1e-6 * float(Z)))
            rows.append(
                {
                    "theta_deg": round(theta_deg, 9),
                    "Z_mm": float(Z),
                    "X_analytic_mm": forward.X_mm,
                    "X_reference_mm": float(X_ref[index]),
                    "X_abs_error_mm": abs(forward.X_mm - float(X_ref[index])),
                    "u_analytic_px": forward.u_px,
                    "u_reference_px": float(u_ref[index]),
                    "u_abs_error_px": abs(forward.u_px - float(u_ref[index])),
                    "v_analytic_px": forward.v_px,
                    "v_reference_px": float(v_ref[index]),
                    "Z_hat_mm": inverse.Z_mm,
                    "Z_abs_error_mm": abs(inverse.Z_mm - float(Z)) if inverse.status is Status.OK else np.nan,
                    "Z_rel_error": (
                        abs(inverse.Z_mm - float(Z)) / float(Z) if inverse.status is Status.OK else np.nan
                    ),
                    "du_dZ_analytic_px_per_mm": analytic_du,
                    "du_dZ_finite_difference_px_per_mm": fd_du,
                    "du_dZ_rel_error": abs(analytic_du - fd_du) / abs(analytic_du),
                    "dZ_du_analytic_mm_per_px": geom.dZ_du(float(Z)),
                    "abs_sensitivity_mm_per_px": geom.abs_sensitivity(float(Z)),
                    "status": forward.status.value,
                    "inverse_status": inverse.status.value,
                }
            )

    u_errors = np.array([row["u_abs_error_px"] for row in rows], dtype=float)
    x_errors = np.array([row["X_abs_error_mm"] for row in rows], dtype=float)
    z_rel = np.array([row["Z_rel_error"] for row in rows], dtype=float)
    inverse_ok = np.isfinite(z_rel)
    d_rel = np.array([row["du_dZ_rel_error"] for row in rows], dtype=float)
    sens = np.array([row["abs_sensitivity_mm_per_px"] for row in rows], dtype=float)
    statuses = [row["status"] for row in rows]

    u_max = float(np.max(u_errors))
    x_max = float(np.max(x_errors))
    z_max = float(np.max(z_rel[inverse_ok])) if np.any(inverse_ok) else float("nan")
    d_max = float(np.max(d_rel))

    checks = {
        "max_abs_u_error_px": {
            "value": u_max,
            "threshold": U_TOLERANCE_PX,
            "pass": bool(u_max <= U_TOLERANCE_PX),
            "what": "analytic u(Z) vs independent 3x3 ray/plane + 3x4 projection",
        },
        "max_abs_X_error_mm": {
            "value": x_max,
            "threshold": X_TOLERANCE_MM,
            "pass": bool(x_max <= X_TOLERANCE_MM),
            "what": "analytic X_L(Z) vs independent linear-system intersection",
        },
        "max_Z_relative_error": {
            "value": z_max,
            "threshold": Z_REL_TOLERANCE,
            "pass": bool(z_max <= Z_REL_TOLERANCE),
            "what": "closed-form inverse vs Brent inversion of the reference chain",
        },
        "max_du_dZ_relative_error": {
            "value": d_max,
            "threshold": DERIVATIVE_REL_TOLERANCE,
            "pass": bool(d_max <= DERIVATIVE_REL_TOLERANCE),
            "what": "analytic du/dZ vs central finite difference of reference chain",
        },
        "all_inverse_valid": {
            "value": f"{int(np.count_nonzero(inverse_ok))}/{len(rows)}",
            "threshold": "all OK",
            "pass": bool(np.all(inverse_ok)),
            "what": "closed-form inverse accepts every reference-produced spot",
        },
        "all_points_valid": {
            "value": f"{statuses.count('OK')}/{len(statuses)}",
            "threshold": "all OK",
            "pass": bool(all(status == "OK" for status in statuses)),
            "what": "no silent clipping inside the declared working range",
        },
        "sign_convention": {
            "value": {
                "du_dZ_negative": bool(all(row["du_dZ_analytic_px_per_mm"] < 0 for row in rows)),
                "dZ_du_negative": bool(all(row["dZ_du_analytic_mm_per_px"] < 0 for row in rows)),
            },
            "threshold": "both negative for B > 0",
            "pass": bool(
                all(row["du_dZ_analytic_px_per_mm"] < 0 for row in rows)
                and all(row["dZ_du_analytic_mm_per_px"] < 0 for row in rows)
            ),
            "what": "signed derivative contract (PDF eq. 3 prints the magnitude)",
        },
    }

    metrics = {
        "gate": "G0",
        "validation_layer": "V0",
        "n_points": len(rows),
        "theta_values_deg": [round(value, 9) for value in theta_values_deg],
        "z_range_mm": [config.z_min_mm, config.z_max_mm],
        "z_points": int(config.run.distance_points),
        "max_abs_u_error_px": u_max,
        "max_abs_X_error_mm": x_max,
        "max_Z_relative_error": z_max,
        "max_du_dZ_relative_error": d_max,
        "status_counts": {status: statuses.count(status) for status in sorted(set(statuses))},
        "inverse_ok_count": int(np.count_nonzero(inverse_ok)),
        "inverse_status_counts": {
            value: sum(1 for row in rows if row["inverse_status"] == value)
            for value in sorted({row["inverse_status"] for row in rows})
        },
        "sensitivity_mm_per_px": {
            "min": float(np.min(sens)),
            "max": float(np.max(sens)),
            "at_z_min": float(sens[0]),
            "at_z_max": float(sens[-1]),
        },
        "thresholds": {
            "u_abs_px": U_TOLERANCE_PX,
            "X_abs_mm": X_TOLERANCE_MM,
            "Z_rel": Z_REL_TOLERANCE,
            "du_dZ_rel": DERIVATIVE_REL_TOLERANCE,
        },
    }

    return ChainComparison(rows=rows, metrics=metrics, gate_checks=checks)


def pdf_reference_table(config: ResolvedConfig) -> list[dict[str, Any]]:
    """Compare the computed values with the numbers printed in PDF section 4.2."""

    geometry = CoplanarGeometry(config.geometry)
    fx = config.fx_px
    f_mm = config.focal_length_mm
    p_mm = config.pixel_size_mm
    B = config.baseline_mm
    theta = config.theta_rad

    u_offset = {
        Z: fx * (B / Z - np.tan(theta)) for Z in (100.0, 200.0, 300.0)
    }
    pdf_values = {
        100.0: 463.77,
        200.0: 231.88,
        300.0: 154.59,
    }
    sensitivity = {Z: abs(geometry.dZ_du(Z)) for Z in (200.0, 300.0)}
    pdf_sensitivity = {200.0: 0.8625, 300.0: 1.9406}

    rows: list[dict[str, Any]] = [
        {
            "quantity": "fx = f/p",
            "unit": "pixel",
            "pdf_printed": round(2318.84, 6),
            "computed": fx,
            "abs_difference": abs(fx - 2318.84),
            "rel_difference": abs(fx - 2318.84) / 2318.84,
            "inputs": f"f={f_mm} mm, p={p_mm} mm",
        }
    ]
    for Z in (100.0, 200.0, 300.0):
        value = float(u_offset[Z])
        rows.append(
            {
                "quantity": f"u - cx at Z={Z:.0f} mm",
                "unit": "pixel",
                "pdf_printed": pdf_values[Z],
                "computed": value,
                "abs_difference": abs(value - pdf_values[Z]),
                "rel_difference": abs(value - pdf_values[Z]) / pdf_values[Z],
                "inputs": f"B={B} mm, theta={config.theta_deg} deg",
            }
        )
    for Z in (200.0, 300.0):
        value = float(sensitivity[Z])
        rows.append(
            {
                "quantity": f"|dZ/du| at Z={Z:.0f} mm",
                "unit": "mm/pixel",
                "pdf_printed": pdf_sensitivity[Z],
                "computed": value,
                "abs_difference": abs(value - pdf_sensitivity[Z]),
                "rel_difference": abs(value - pdf_sensitivity[Z]) / pdf_sensitivity[Z],
                "inputs": f"B={B} mm, fx={fx:.6f} px",
            }
        )
    return rows


def boundary_cases(config: ResolvedConfig) -> list[dict[str, Any]]:
    """Deterministic boundary/abuse cases kept as auditable evidence."""

    spec = config.geometry
    geom = CoplanarGeometry(spec)
    cases: list[dict[str, Any]] = []

    def record(name: str, expected: str, actual: Status, detail: str) -> None:
        cases.append(
            {
                "case": name,
                "expected_status": expected,
                "actual_status": actual.value,
                "pass": actual.value == expected,
                "detail": detail,
            }
        )

    record("nominal Z = 200 mm", "OK", geom.forward(200.0).status,
           f"u = {geom.forward(200.0).u_px:.6f} px")

    record("Z below working range (50 mm)", "OUT_OF_RANGE", geom.forward(50.0).status,
           "rejected instead of extrapolating")

    record("Z = 0 mm", "INVALID_DEPTH", geom.forward(0.0).status, "division by zero refused")

    record("Z = -100 mm", "INVALID_DEPTH", geom.forward(-100.0).status, "target behind pinhole")

    record("Z = nan", "NONFINITE_INPUT", geom.forward(float("nan")).status, "non-finite input")

    degenerate = _retuned(spec, baseline_mm=0.5, min_baseline_mm=1.0)
    record("B = 0.5 mm < min_baseline 1.0 mm", "BASELINE_DEGENERATE",
           CoplanarGeometry(degenerate).forward(200.0).status,
           "tiny baseline destroys triangulation leverage")

    singular_u = spec.cx_px - spec.fx_px * np.tan(spec.theta_rad)
    record("u exactly at the singularity", "SINGULAR_GEOMETRY",
           geom.inverse(singular_u).status, f"u = {singular_u:.6f} px")

    record("u 1e-9 px from the singularity", "SINGULAR_GEOMETRY",
           geom.inverse(singular_u + 1e-9).status, "below denominator threshold 1e-6 px")

    record("u mapped to Z = 50 mm", "OUT_OF_RANGE", geom.inverse(geom.forward(50.0).u_px).status,
           "candidate depth outside declared range")

    sensor_geom = CoplanarGeometry(_retuned(spec, enforce_working_range=False))
    record("Z = 20 mm with range check disabled (u = 2958 px)", "OUT_OF_SENSOR",
           sensor_geom.forward(20.0).status,
           "near-range spot clipped by the chip; status is not silently OK")

    record("u implies negative depth", "INVALID_DEPTH",
           geom.inverse(spec.cx_px - 1000.0).status, "denominator sign check")

    return cases


def _retuned(spec: CoplanarSpec, **overrides: Any) -> CoplanarSpec:
    """Clone a spec with explicit overrides (used for boundary evidence)."""

    params: dict[str, Any] = {
        "baseline_mm": spec.baseline_mm,
        "theta_rad": spec.theta_rad,
        "fx_px": spec.fx_px,
        "cx_px": spec.cx_px,
        "cy_px": spec.cy_px,
        "width_px": spec.width_px,
        "height_px": spec.height_px,
        "z_min_mm": spec.z_min_mm,
        "z_max_mm": spec.z_max_mm,
        "min_baseline_mm": spec.min_baseline_mm,
        "singular_denominator_px": spec.singular_denominator_px,
        "sensor_margin_px": spec.sensor_margin_px,
        "enforce_working_range": spec.enforce_working_range,
        "range_epsilon_mm": spec.range_epsilon_mm,
    }
    params.update(overrides)
    return CoplanarSpec(**params)


def _spec_with_theta(spec: CoplanarSpec, theta_rad: float) -> CoplanarSpec:
    return _retuned(spec, theta_rad=theta_rad)
