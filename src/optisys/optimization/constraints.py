"""Hard constraints, evaluated before any objective value is formed.

An infeasible design returns a **reason code**, never a fabricated large
penalty.  A soft penalty can always be out-voted by a lucky accuracy term,
which would let the optimiser buy accuracy with a physically impossible
geometry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from optisys.config_g2 import ResolvedG2Config
from optisys.optimization.search_space import Design, SearchSpace
from optisys.tolerance.perturbations import AssemblyPerturbation, make_assembly

REASON_BOUNDS = "INFEASIBLE(BOUNDS)"
REASON_OUT_OF_FOV = "INFEASIBLE(OUT_OF_FOV)"
REASON_VIGNETTING = "INFEASIBLE(VIGNETTING)"
REASON_PSF_SUPPORT = "INFEASIBLE(INSUFFICIENT_PSF_SUPPORT)"
REASON_SATURATION = "INFEASIBLE(SATURATION)"
REASON_LENS_GEOMETRY = "INFEASIBLE(LENS_GEOMETRY)"


@dataclass
class ConstraintReport:
    feasible: bool
    reason: str
    details: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"feasible": self.feasible, "reason": self.reason, "details": self.details}


def design_assembly(design: Design, config: ResolvedG2Config):
    """Nominal unit of a candidate design (no perturbation)."""

    perturbation = AssemblyPerturbation(
        assembly_id="NOMINAL",
        d_baseline_mm=design.baseline_mm - config.baseline_mm,
        d_theta_rad=design.theta_rad - config.theta_rad,
        d_focal_relative=design.focal_length_mm / config.focal_length_mm - 1.0,
        d_cx_px=0.0,
        d_focus_mm=0.0,
    )
    return make_assembly(perturbation, config)


def probe_design(design: Design, config: ResolvedG2Config, space: SearchSpace,
                 runner, *, distances: tuple[float, float, float] = (100.0, 200.0, 300.0),
                 medium_condition: str = "medium") -> ConstraintReport:
    """Trace the extreme distances and check the pre-registered hard limits."""

    if not space.contains(design):
        return ConstraintReport(False, REASON_BOUNDS, {"design": design.as_row()})

    assembly = design_assembly(design, config)
    try:
        lens = assembly.lens(config)
        lens.radius_mm  # noqa: B018 - triggers the radius solver
    except ValueError as exc:
        return ConstraintReport(False, REASON_LENS_GEOMETRY, {"error": str(exc)})

    condition = next((c for c in config.dataset.conditions if c.name == medium_condition), None)
    if condition is None:
        raise ValueError(f"condition {medium_condition!r} not configured")

    model = runner.model_for(assembly)
    margin = config.constraints.sensor_margin_px
    lo = margin
    hi = config.width_px - 1 - margin
    details: dict[str, Any] = {"per_distance": {}}
    for distance in distances:
        height = assembly.object_height_mm(float(distance))
        result = model.image(float(distance), height,
                             total_electrons=runner.scene_electrons(float(distance), condition))
        entry = {
            "u_px": float(result.spot_center_px[0]),
            "ray_success_fraction": float(result.ray_success_fraction or 0.0),
            "kernel_support": float(result.support_fraction or 0.0),
            "peak_e": float(result.diagnostics.get("expected_peak_e", 0.0)),
            "status": result.status.value,
        }
        details["per_distance"][f"{distance:.0f}"] = entry
        if result.status.value in ("ALL_RAYS_BLOCKED", "OPTICS_TRACE_FAILED"):
            return ConstraintReport(False, REASON_VIGNETTING, details)
        if not np.isfinite(entry["u_px"]) or entry["u_px"] < lo or entry["u_px"] > hi:
            return ConstraintReport(False, REASON_OUT_OF_FOV, details)
        if entry["ray_success_fraction"] < config.constraints.min_ray_success:
            return ConstraintReport(False, REASON_VIGNETTING, details)
        if entry["kernel_support"] < config.constraints.min_kernel_support:
            return ConstraintReport(False, REASON_PSF_SUPPORT, details)
    peak = max(entry["peak_e"] for entry in details["per_distance"].values())
    details["peak_e_max"] = peak
    details["peak_limit_e"] = config.constraints.max_peak_fraction * config.sensor.full_well_e
    if peak > details["peak_limit_e"]:
        return ConstraintReport(False, REASON_SATURATION, details)
    return ConstraintReport(True, "FEASIBLE", details)
