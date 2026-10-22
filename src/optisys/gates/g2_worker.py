"""Worker entry points for parallel scene execution.

Each worker rebuilds its own :class:`SceneRunner` from the configuration path,
because the Optiland system objects are not picklable.  A worker handles a
*chunk* of assemblies so the per-assembly optical cache is reused.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import numpy as np

from optisys.calibration.assembly_strategies import fit_calibration
from optisys.config_g2 import load_config_g2
from optisys.errors import Status
from optisys.tolerance.assembly_model import SceneRunner
from optisys.tolerance.perturbations import (
    AssemblyPerturbation,
    make_design_assembly,
)


@lru_cache(maxsize=4)
def _config(path: str):
    return load_config_g2(path)


@lru_cache(maxsize=4)
def _runner(path: str, estimator_names: tuple[str, ...]):
    from optisys.estimators import build_estimators_g2

    config = _config(path)
    estimators = [e for e in build_estimators_g2() if e.name in estimator_names]
    return SceneRunner(config, estimators=estimators, max_cached_models=8)


def _perturbation(spec: dict[str, Any]) -> AssemblyPerturbation:
    return AssemblyPerturbation(
        assembly_id=spec["assembly_id"],
        d_baseline_mm=spec["d_baseline_mm"],
        d_theta_rad=spec["d_theta_rad"],
        d_focal_relative=spec["d_focal_relative"],
        d_cx_px=spec["d_cx_px"],
        d_focus_mm=spec["d_focus_mm"],
    )


def assembly_chunk(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Run every scene of every assembly in the chunk, in order."""

    config = _config(payload["config_path"])
    runner = _runner(payload["config_path"], tuple(payload["estimators"]))
    scenes = payload["scenes"]
    estimator_names = list(payload["estimators"])
    primary = payload.get("estimator", estimator_names[-1])
    rows: list[dict[str, Any]] = []

    design_base = payload.get("design", {})
    for spec in payload["assemblies"]:
        perturbation = _perturbation(spec)
        assembly = make_design_assembly(
            perturbation, config,
            baseline_mm=design_base.get("baseline_mm", config.baseline_mm),
            theta_rad=design_base.get("theta_rad", config.theta_rad),
            focal_length_mm=design_base.get("focal_length_mm", config.focal_length_mm),
        )

        if payload.get("calibration_distances"):
            z_values: list[float] = []
            u_values: list[float] = []
            condition = next(c for c in config.dataset.conditions
                             if c.name == payload["calibration_condition"])
            for distance in payload["calibration_distances"]:
                outcome = runner.run_scene(
                    assembly, float(distance), condition, repeat=0,
                    seed_namespace=payload["calibration_namespace"],
                )
                estimate = outcome.estimates[primary]
                if estimate["status"] == Status.OK.value and estimate["u_hat_px"] is not None:
                    z_values.append(float(distance))
                    u_values.append(float(estimate["u_hat_px"]))
            fit = fit_calibration(
                np.array(z_values), np.array(u_values), model=payload["calibration_model"],
                estimator=primary, assembly_id=assembly.assembly_id,
            )
            rows.append({
                "candidate": payload.get("candidate", ""),
                "assembly_id": assembly.assembly_id,
                "row_kind": "calibration",
                "calibration_model": fit.model,
                "calibration_params": list(fit.params),
                "calibration_status": fit.status.value,
                "calibration_rms_px": fit.residual_rms_px,
                "calibration_n_points": fit.n_points,
                "calibration_z_min_mm": fit.z_min_mm,
                "calibration_z_max_mm": fit.z_max_mm,
                "estimator": primary,
            })

        for scene in scenes:
            distance = float(scene["distance"])
            condition = next(c for c in config.dataset.conditions
                             if c.name == scene["condition"])
            outcome = runner.run_scene(
                assembly, distance, condition, repeat=int(scene.get("repeat", 0)),
                seed_namespace=scene["namespace"],
            )
            for name, estimate in outcome.estimates.items():
                rows.append({
                    "candidate": payload.get("candidate", ""),
                    "assembly_id": outcome.assembly_id,
                    "distance_mm": distance,
                    "condition": outcome.condition,
                    "repeat": outcome.repeat,
                    "estimator": name,
                    "image_seed": outcome.seed,
                    "optical_status": outcome.optical_status,
                    "roi_status": outcome.roi_status,
                    "capture_fraction": outcome.capture_fraction,
                    "ray_success_fraction": outcome.ray_success_fraction,
                    "kernel_support": outcome.kernel_support,
                    "transmitted_fraction": outcome.transmitted_fraction,
                    "peak_expected_e": outcome.peak_expected_e,
                    "expected_sum_e": outcome.expected_sum_e,
                    "saturation_full_well": outcome.saturation_full_well,
                    "saturation_adc": outcome.saturation_adc,
                    "u_gt_px": outcome.u_gt_px,
                    "u_hat_px": estimate["u_hat_px"],
                    "v_hat_px": estimate["v_hat_px"],
                    "estimator_status": estimate["status"],
                    "quality_flags": ";".join(estimate["flags"]),
                    "sigma_px": estimate["sigma_px"],
                    "fit_rms_e": estimate["fit_rms_e"],
                    "snr_proxy": estimate["snr_proxy"],
                    "runtime_ms": estimate["runtime_ms"],
                    "roi_touches_border": estimate["roi_touches_border"],
                })
    return rows


def probe_chunk(payload: dict[str, Any]) -> dict[str, Any]:
    """Constraint probe for one design (used by the search)."""

    from optisys.optimization.constraints import probe_design
    from optisys.optimization.search_space import Design, SearchSpace

    config = _config(payload["config_path"])
    runner = _runner(payload["config_path"], tuple(payload["estimators"]))
    design = Design(payload["baseline_mm"], payload["focal_length_mm"], payload["theta_deg"])
    report = probe_design(design, config, SearchSpace.from_config(config), runner)
    return report.to_dict()
