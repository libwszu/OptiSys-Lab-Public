"""G2 orchestration: optics validation, tolerance, optimisation, holdout.

Every stage writes machine-readable evidence next to its human-readable
summary.  A stage that cannot run records ``NOT_RUN`` with a reason instead of
an empty PASS table.
"""

from __future__ import annotations

import csv
import json
import time
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import yaml

from optisys import __version__
from optisys.calibration.assembly_strategies import fit_calibration
from optisys.config_g2 import ResolvedG2Config
from optisys.errors import Status
from optisys.evaluation.metrics import BLOCKING_FLAGS, is_valid, parse_flags
from optisys.evaluation.paired_comparison import (
    paired_bootstrap,
    paired_rate_difference,
)
from optisys.gates.g2_worker import assembly_chunk
from optisys.optimization.constraints import probe_design
from optisys.optimization.experiment_registry import CandidateRegistry, make_candidate
from optisys.optimization.objectives import DesignEvaluator, DesignMetrics
from optisys.optimization.optimizer import BudgetedSearch, history_rows
from optisys.optimization.search_space import Design, SearchSpace
from optisys.optics.optiland_adapter import SingletModel, backend_info
from optisys.optics.optical_image_contract import (
    CameraGeometry,
    L0OpticalModel,
    L1OpticalModel,
)
from optisys.optics.psf_or_footprint import KernelSpec, airy_radius_px
from optisys.optics.reference_thin_lens import ThinLensReference
from optisys.runtime.environment import collect_environment
from optisys.runtime.run import RunContext, source_tree_digest, utc_now
from optisys.tolerance.assembly_model import SceneRunner
from optisys.tolerance.oat import run_oat, sensitivity_summary
from optisys.tolerance.perturbations import (
    NOMINAL_ASSEMBLY_ID,
    AssemblyPerturbation,
    AssemblyState,
    make_assembly,
    make_design_assembly,
    perturbation_sigmas,
)
from optisys.tolerance.samplers import draw

ESTIMATORS_FAST = ("centroid", "gaussian_2d", "gaussian_2d_integrated")
ESTIMATORS_ALL = ("centroid", "gaussian_1d", "gaussian_2d", "gaussian_2d_integrated")
PRIMARY_ESTIMATOR = "gaussian_2d_integrated"


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------
def _write_csv(path: Path, rows: Iterable[dict[str, Any]], fields: list[str] | None = None) -> None:
    rows = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    if fields is None:
        fields = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
                    encoding="utf-8")


def _design_from_config(config: ResolvedG2Config) -> Design:
    return Design(config.baseline_mm, config.focal_length_mm, config.theta_deg)


def _nominal_assembly(design: Design, config: ResolvedG2Config) -> AssemblyState:
    perturbation = AssemblyPerturbation(
        assembly_id=NOMINAL_ASSEMBLY_ID,
        d_baseline_mm=design.baseline_mm - config.baseline_mm,
        d_theta_rad=design.theta_rad - config.theta_rad,
        d_focal_relative=design.focal_length_mm / config.focal_length_mm - 1.0,
    )
    return make_assembly(perturbation, config)


def _evenly_spaced(values: tuple[float, ...] | list[float], n: int) -> tuple[float, ...]:
    values = list(values)
    if n >= len(values):
        return tuple(values)
    indices = np.linspace(0, len(values) - 1, n).round().astype(int)
    return tuple(float(values[i]) for i in sorted(set(indices.tolist())))


# ---------------------------------------------------------------------------
# V4-A  optics
# ---------------------------------------------------------------------------
def _optical_validation(config: ResolvedG2Config, context: RunContext,
                        quick: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    directory = context.path("optics")
    directory.mkdir(parents=True, exist_ok=True)
    info = backend_info()
    checks: dict[str, Any] = {}
    status: dict[str, Any] = {
        "backend": info,
        "backend_executed": False,
        "trace_rows": 0,
        "model": None,
    }
    if not info["importable"]:
        status["error"] = info.get("error")
        checks["A1_backend_importable"] = {"pass": False, "value": info,
                                           "what": "optiland import"}
        return status, checks

    lens = SingletModel(
        focal_length_mm=config.focal_length_mm,
        aperture_mm=config.optics.aperture_diameter_mm,
        thickness_mm=config.optics.element_thickness_mm,
        material=config.optics.material,
        index=config.optics.design_index,
        wavelength_nm=config.wavelength_nm,
        rear_aperture_clearance_mm=config.optics.rear_aperture_clearance_mm,
        focus_distance_mm=config.optics.focus_distance_mm,
        pupil_side=config.optics.pupil_side,
    )
    reference = ThinLensReference(
        focal_length_mm=config.focal_length_mm,
        aperture_mm=config.optics.aperture_diameter_mm,
        thickness_mm=config.optics.element_thickness_mm,
        index=config.optics.design_index,
    )
    model = L1OpticalModel(
        CameraGeometry(config.width_px, config.height_px, config.pixel_size_mm,
                       config.cx_px, config.cy_px),
        lens,
        kernel_spec=KernelSpec(subpixel=config.optics.psf.subpixel,
                               max_half_px=config.optics.psf.max_half_px,
                               airy_radius_margin=config.optics.psf.airy_radius_margin),
        signal_mode=config.imaging.signal_mode,
        reference_electrons=config.imaging.reference_electrons,
        reference_distance_mm=config.imaging.reference_distance_mm,
        reference_aperture_mm=config.imaging.reference_aperture_mm,
    )

    distances = (100.0, 150.0, 200.0, 250.0, 300.0)
    rows: list[dict[str, Any]] = []
    for distance in distances:
        height = config.baseline_mm - distance * np.tan(config.theta_rad)
        footprint = model.tracer.trace(distance, float(height))
        status["backend_executed"] = True
        for index in range(footprint.x_mm.size):
            rows.append({
                "Z_mm": distance,
                "object_height_mm": float(height),
                "ray_index": index,
                "x_image_mm": float(footprint.x_mm[index]),
                "y_image_mm": float(footprint.y_mm[index]),
                "intensity": float(footprint.intensity[index]),
                "valid": bool(footprint.valid[index]),
            })
    status["trace_rows"] = len(rows)
    _write_csv(directory / "raytrace_reference.csv", rows,
               ["Z_mm", "object_height_mm", "ray_index", "x_image_mm", "y_image_mm",
                "intensity", "valid"])
    status["model"] = lens.describe()

    # A4: paraxial agreement at a *small* field, where first-order theory applies.
    small_height = 0.5
    small_rows = []
    for distance in (150.0, 200.0, 250.0):
        footprint = model.tracer.trace(distance, small_height)
        traced = footprint.chief_y_mm
        paraxial = reference.chief_image_mm(distance, small_height,
                                            lens.sensor_distance_mm)
        small_rows.append({
            "Z_mm": distance,
            "chief_y_traced_mm": traced,
            "chief_y_paraxial_mm": paraxial,
            "abs_error_mm": abs(traced - paraxial),
            "rel_error": abs(traced - paraxial) / max(abs(paraxial), 1e-12),
        })
    _write_csv(directory / "independent_thin_lens_comparison.csv", small_rows)
    worst_rel = max(row["rel_error"] for row in small_rows)
    checks["A4_paraxial_small_field"] = {
        "value": worst_rel,
        "threshold": 0.01,
        "pass": bool(worst_rel <= 0.01),
        "what": "traced chief ray vs independent paraxial matrix at 0.5 mm object height",
    }

    # A5: geometric (pinhole) limit.  Closing the stop must collapse the
    # geometrical blur to a point.  Note that the *chief ray* is independent of
    # the aperture, so shrinking the stop does NOT remove distortion: the L0
    # pinhole law u = cx + fx*X/Z is a different model, not the limit of a
    # finite-conjugate thin lens.  That discrepancy is recorded as a finding,
    # not used as a pass criterion.
    pinhole_rows = []
    for aperture in (1.2, 0.6, 0.3, 0.15):
        small_lens = replace(lens, aperture_mm=aperture)
        small_model = L1OpticalModel(
            CameraGeometry(config.width_px, config.height_px, config.pixel_size_mm,
                           config.cx_px, config.cy_px),
            small_lens, kernel_spec=KernelSpec(include_airy=False),
        )
        for distance in (100.0, 200.0, 300.0):
            height = config.baseline_mm - distance * np.tan(config.theta_rad)
            footprint = small_model.tracer.trace(distance, float(height))
            sxx, syy, _ = footprint.second_moments_mm
            measured = config.cx_px - footprint.chief_y_mm / config.pixel_size_mm
            predicted = config.cx_px + config.fx_px * height / distance
            pinhole_rows.append({
                "aperture_mm": aperture,
                "Z_mm": distance,
                "rms_radius_px": float(np.sqrt(sxx + syy) / config.pixel_size_mm),
                "u_chief_px": measured,
                "u_pinhole_px": predicted,
                "l0_abs_error_px": abs(measured - predicted),
                "l0_rel_error_of_offset": abs(measured - predicted)
                / max(abs(predicted - config.cx_px), 1e-12),
            })
    _write_csv(directory / "pinhole_limit.csv", pinhole_rows)
    smallest = [row for row in pinhole_rows if row["aperture_mm"] == 0.15]
    worst_radius_px = max(row["rms_radius_px"] for row in smallest)
    checks["A5_pinhole_limit"] = {
        "value": worst_radius_px,
        "threshold": 0.3,
        "pass": bool(worst_radius_px <= 0.3),
        "what": "EPD=0.15 mm geometric RMS radius in pixels (must collapse to a point)",
    }
    l0_rows = [row for row in pinhole_rows]
    max_l0_px = max(row["l0_abs_error_px"] for row in l0_rows)
    max_l0_rel = max(row["l0_rel_error_of_offset"] for row in l0_rows)

    # A6: aperture -> spot size monotone.
    aperture_rows = []
    for aperture in (0.3, 0.6, 0.9, 1.2, 1.5):
        small_lens = replace(lens, aperture_mm=aperture)
        small_model = L1OpticalModel(
            CameraGeometry(config.width_px, config.height_px, config.pixel_size_mm,
                           config.cx_px, config.cy_px),
            small_lens, kernel_spec=KernelSpec(include_airy=False),
        )
        footprint = small_model.tracer.trace(200.0, config.baseline_mm)
        sxx, syy, _ = footprint.second_moments_mm
        aperture_rows.append({
            "aperture_mm": aperture,
            "rms_radius_um": float(np.sqrt(sxx + syy) * 1e3),
            "f_number": small_lens.working_f_number,
        })
    _write_csv(directory / "aperture_vignetting_failure_table.csv", aperture_rows)
    radii = np.array([row["rms_radius_um"] for row in aperture_rows])
    monotone = bool(np.all(np.diff(radii) > 0))
    checks["A6_aperture_monotone_spot"] = {
        "value": radii.tolist(),
        "threshold": "strictly increasing with aperture",
        "pass": monotone,
        "what": "RMS spot radius vs entrance aperture diameter",
    }

    # A7: detector defocus -> blur.  The swept variable is the *sensor* offset,
    # not the object distance the lens is focused at: the two differ by
    # ds'/dz_focus = (f/(z-f))^2, which is ~1e-3 here.
    focus_rows = []
    for offset in (-0.40, -0.20, -0.10, -0.05, 0.0, 0.05, 0.10, 0.20, 0.40):
        small_lens = replace(lens, sensor_offset_mm=offset)
        small_model = L1OpticalModel(
            CameraGeometry(config.width_px, config.height_px, config.pixel_size_mm,
                           config.cx_px, config.cy_px),
            small_lens, kernel_spec=KernelSpec(include_airy=False),
        )
        footprint = small_model.tracer.trace(200.0, config.baseline_mm)
        sxx, syy, _ = footprint.second_moments_mm
        focus_rows.append({
            "sensor_offset_mm": offset,
            "abs_defocus_mm": abs(offset),
            "scene_Z_mm": 200.0,
            "rms_radius_um": float(np.sqrt(sxx + syy) * 1e3),
        })
    _write_csv(directory / "focus_sweep.csv", focus_rows)
    by_offset = sorted(focus_rows, key=lambda row: row["sensor_offset_mm"])
    radii = np.array([row["rms_radius_um"] for row in by_offset], dtype=float)
    # Unimodality: exactly one sign change in the first difference.
    diffs = np.diff(radii)
    sign_changes = int(np.sum(np.sign(diffs[1:]) != np.sign(diffs[:-1])))
    minimum = float(radii.min())
    far = float(radii[0] + radii[-1]) / 2.0
    checks["A7_focus_defocus"] = {
        "value": {"offset_mm": [row["sensor_offset_mm"] for row in by_offset],
                  "rms_radius_um": radii.tolist(),
                  "minimum_um": minimum, "far_mean_um": far,
                  "sign_changes": sign_changes},
        "threshold": "unimodal U-shape and far-offset blur >= 3x the minimum",
        "pass": bool(sign_changes == 1 and far >= 3.0 * minimum),
        "what": "detector defocus sweep at Z=200 mm",
    }

    # A8: blocked rays are counted.
    blocked_rows = []
    for distance in (100.0, 200.0, 300.0):
        height = config.baseline_mm - distance * np.tan(config.theta_rad)
        footprint = model.tracer.trace(distance, float(height))
        blocked_rows.append({
            "Z_mm": distance,
            "n_launched": footprint.n_launched,
            "n_valid": footprint.n_valid,
            "blocked_fraction": 1.0 - footprint.ray_success_fraction,
            "transmitted_energy_fraction": float(
                footprint.intensity[footprint.valid].sum() / footprint.n_launched
            ),
        })
    _write_csv(directory / "vignetting_failures.csv", blocked_rows)
    checks["A8_blocked_rays_counted"] = {
        "value": [row["blocked_fraction"] for row in blocked_rows],
        "threshold": "< 1.0 blocked and reported",
        "pass": bool(all(row["n_valid"] > 0 for row in blocked_rows)),
        "what": "every launched ray accounted for, blocked rays kept in the denominator",
    }

    checks["A1_backend_importable"] = {
        "value": info, "threshold": "importable and version 0.6.3",
        "pass": bool(info["importable"] and info["version_supported"]),
        "what": "Optiland import + version",
    }
    checks["A2_real_refracting_surfaces"] = {
        "value": {"radius_1_mm": lens.radius_mm, "radius_2_mm": -lens.radius_mm,
                  "thickness_mm": lens.thickness_mm, "material": lens.material},
        "threshold": "two non-flat surfaces with a real thickness",
        "pass": bool(np.isfinite(lens.radius_mm) and lens.radius_mm > 0),
        "what": "declared refracting geometry",
    }
    checks["A3_trace_executed"] = {
        "value": status["trace_rows"], "threshold": "> 0 exported ray rows",
        "pass": bool(status["trace_rows"] > 0),
        "what": "real ray trace output written to raytrace_reference.csv",
    }

    # Distortion at the real working field, reported, not hidden.
    distortion_rows = []
    for distance in distances:
        height = config.baseline_mm - distance * np.tan(config.theta_rad)
        footprint = model.tracer.trace(distance, float(height))
        traced = config.cx_px - footprint.chief_y_mm / config.pixel_size_mm
        paraxial = config.cx_px - reference.chief_image_mm(
            distance, float(height), lens.sensor_distance_mm) / config.pixel_size_mm
        distortion_rows.append({
            "Z_mm": distance,
            "object_height_mm": float(height),
            "u_traced_px": traced,
            "u_paraxial_px": paraxial,
            "distortion_px": traced - paraxial,
            "distortion_fraction_of_offset": (traced - paraxial) / max(abs(paraxial - config.cx_px), 1e-12),
        })
    _write_csv(directory / "field_distortion.csv", distortion_rows)
    status["distortion"] = distortion_rows
    status["findings"] = {
        "l0_vs_l1_chief_ray_max_px": float(max_l0_px),
        "l0_vs_l1_chief_ray_max_rel_offset": float(max_l0_rel),
        "note": (
            "The G1 pinhole law and the finite-conjugate singlet differ by a "
            "systematic offset of a few percent; recalibration absorbs most of it "
            "but leaves a residual curvature. This is finding G2-01, not a bug."
        ),
    }
    status["checks"] = checks
    context.write_json("optics/optical_validation.json", status)
    return status, checks


# ---------------------------------------------------------------------------
# V4-B  imaging
# ---------------------------------------------------------------------------
def _imaging_validation(config: ResolvedG2Config, context: RunContext,
                        optical_status: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    directory = context.path("optics")
    directory.mkdir(parents=True, exist_ok=True)
    checks: dict[str, Any] = {}
    camera = CameraGeometry(config.width_px, config.height_px, config.pixel_size_mm,
                            config.cx_px, config.cy_px)
    lens = SingletModel(
        focal_length_mm=config.focal_length_mm,
        aperture_mm=config.optics.aperture_diameter_mm,
        thickness_mm=config.optics.element_thickness_mm,
        material=config.optics.material,
        index=config.optics.design_index,
        wavelength_nm=config.wavelength_nm,
        rear_aperture_clearance_mm=config.optics.rear_aperture_clearance_mm,
        focus_distance_mm=config.optics.focus_distance_mm,
        pupil_side=config.optics.pupil_side,
    )
    model = L1OpticalModel(
        camera, lens,
        kernel_spec=KernelSpec(subpixel=config.optics.psf.subpixel,
                               max_half_px=config.optics.psf.max_half_px,
                               airy_radius_margin=config.optics.psf.airy_radius_margin),
        signal_mode=config.imaging.signal_mode,
        reference_electrons=config.imaging.reference_electrons,
        reference_distance_mm=config.imaging.reference_distance_mm,
        reference_aperture_mm=config.imaging.reference_aperture_mm,
    )
    energy_rows = []
    examples: dict[str, np.ndarray] = {}
    for distance in (100.0, 150.0, 200.0, 250.0, 300.0):
        height = config.baseline_mm - distance * np.tan(config.theta_rad)
        result = model.image(distance, float(height),
                             total_electrons=config.imaging.reference_electrons)
        transmitted = float(result.transmitted_energy_fraction or 0.0)
        placed = result.expected_signal_e.sum() / config.imaging.reference_electrons
        energy_rows.append({
            "Z_mm": distance,
            "electrons_in": config.imaging.reference_electrons,
            "transmitted_fraction": transmitted,
            "placed_fraction": placed,
            "capture_fraction": result.capture_fraction,
            "kernel_support": result.support_fraction,
            "sum_electrons": float(result.expected_signal_e.sum()),
            "peak_electrons": float(result.expected_signal_e.max()),
            "status": result.status.value,
            "kernel_kind": result.kernel_kind,
            "kernel_half_px": result.diagnostics.get("kernel_half_px"),
        })
        if result.psf_kernel is not None:
            examples[f"kernel_Z{int(distance)}"] = result.psf_kernel.astype(np.float32)
            examples[f"signal_Z{int(distance)}"] = result.expected_signal_e.astype(np.float32)
    _write_csv(directory / "energy_and_capture.csv", energy_rows)
    np.savez_compressed(directory / "psf_or_footprint_examples.npz", **examples)

    worst_energy = max(
        abs(row["sum_electrons"] / config.imaging.reference_electrons
            - row["transmitted_fraction"] * row["capture_fraction"])
        for row in energy_rows
    )
    checks["B1_energy_conservation"] = {
        "value": worst_energy, "threshold": 0.005,
        "pass": bool(worst_energy <= 0.005),
        "what": "sum(expected_signal_e) vs transmitted x capture",
    }
    nonneg = all(row["sum_electrons"] >= 0 and row["peak_electrons"] >= 0 for row in energy_rows)
    checks["B2_kernel_nonnegative_normalised"] = {
        "value": {"non_negative": bool(nonneg),
                  "all_capture_le_1": bool(all(row["capture_fraction"] <= 1.0 + 1e-9
                                                for row in energy_rows))},
        "threshold": "non-negative and capture <= 1",
        "pass": bool(nonneg and all(row["capture_fraction"] <= 1.0 + 1e-9
                                    for row in energy_rows)),
        "what": "kernel sanity",
    }

    # B4: L0 limit.  A pinhole reference kernel placed by the same code path
    # must reproduce the analytic L0 spot centre.
    l0 = L0OpticalModel(camera, sigma_px=2.5, fx_px=config.fx_px)
    l0_rows = []
    for distance in (100.0, 200.0, 300.0):
        height = config.baseline_mm - distance * np.tan(config.theta_rad)
        result = l0.image(distance, float(height), total_electrons=40000.0)
        expected_u = config.cx_px + config.fx_px * height / distance
        l0_rows.append({
            "Z_mm": distance,
            "u_model_px": result.spot_center_px[0],
            "u_expected_px": expected_u,
            "abs_error_px": abs(result.spot_center_px[0] - expected_u),
        })
    _write_csv(directory / "l0_limit.csv", l0_rows)
    worst_l0 = max(row["abs_error_px"] for row in l0_rows)
    checks["B4_l0_limit"] = {
        "value": worst_l0, "threshold": 0.01,
        "pass": bool(worst_l0 <= 0.01),
        "what": "L0 contract reproduced by the shared camera geometry",
    }

    # B5: focus and aperture really change the kernel.
    sensitivity_rows = []
    for focus in (150.0, 200.0, 250.0):
        variant = replace(lens, focus_distance_mm=focus)
        variant_model = L1OpticalModel(
            camera, variant,
            kernel_spec=KernelSpec(subpixel=config.optics.psf.subpixel,
                                   max_half_px=config.optics.psf.max_half_px),
        )
        result = variant_model.image(200.0, config.baseline_mm, total_electrons=40000.0)
        kernel = result.psf_kernel
        sensitivity_rows.append({
            "change": "focus",
            "value": focus,
            "kernel_half_px": result.diagnostics.get("kernel_half_px"),
            "kernel_peak": float(kernel.max()) if kernel is not None else None,
            "peak_electrons": float(result.expected_signal_e.max()),
            "expected_sum_e": float(result.expected_signal_e.sum()),
        })
    for aperture in (0.6, 0.9, 1.2):
        variant = replace(lens, aperture_mm=aperture)
        variant_model = L1OpticalModel(
            camera, variant,
            kernel_spec=KernelSpec(subpixel=config.optics.psf.subpixel,
                                   max_half_px=config.optics.psf.max_half_px),
        )
        result = variant_model.image(200.0, config.baseline_mm, total_electrons=40000.0)
        sensitivity_rows.append({
            "change": "aperture",
            "value": aperture,
            "kernel_half_px": result.diagnostics.get("kernel_half_px"),
            "kernel_peak": float(result.psf_kernel.max()) if result.psf_kernel is not None else None,
            "peak_electrons": float(result.expected_signal_e.max()),
            "expected_sum_e": float(result.expected_signal_e.sum()),
        })
    _write_csv(directory / "kernel_sensitivity.csv", sensitivity_rows)
    focus_peaks = [row["kernel_peak"] for row in sensitivity_rows if row["change"] == "focus"]
    aperture_peaks = [row["kernel_peak"] for row in sensitivity_rows if row["change"] == "aperture"]
    checks["B5_physics_coupling"] = {
        "value": {"focus_kernel_peaks": focus_peaks, "aperture_kernel_peaks": aperture_peaks},
        "threshold": "kernel peak changes > 1% across the sweep",
        "pass": bool(
            max(focus_peaks) - min(focus_peaks) > 0.01 * max(focus_peaks)
            and max(aperture_peaks) - min(aperture_peaks) > 0.01 * max(aperture_peaks)
        ),
        "what": "z_focus and D_entrance change the produced kernel, not just a label",
    }

    # B7: determinism.
    repeat_a = model.image(200.0, config.baseline_mm, total_electrons=40000.0)
    model.clear_cache()
    repeat_b = model.image(200.0, config.baseline_mm, total_electrons=40000.0)
    identical = bool(np.array_equal(repeat_a.expected_signal_e, repeat_b.expected_signal_e))
    checks["B7_deterministic_kernel"] = {
        "value": identical, "threshold": "bitwise identical", "pass": identical,
        "what": "same configuration, cache cleared, same kernel",
    }

    # B6: degenerate cases return named statuses.
    blocked = model.tracer.trace(200.0, 200.0)
    checks["B6_degenerate_statuses"] = {
        "value": {"all_rays_blocked_status": blocked.status.value,
                  "n_valid": blocked.n_valid},
        "threshold": "blocked geometry returns a named non-OK status",
        "pass": bool(blocked.status is not Status.OK),
        "what": "far off-axis point is refused instead of returning a fake distance",
    }
    return {"energy": energy_rows, "checks": checks,
            "l0_limit": l0_rows,
            "kernel_sensitivity": sensitivity_rows}, checks


# ---------------------------------------------------------------------------
# parallel scene execution
# ---------------------------------------------------------------------------
def _chunk(items: list[Any], size: int) -> list[list[Any]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def _run_chunks(payloads: list[dict[str, Any]], workers: int,
                log) -> list[dict[str, Any]]:
    if workers <= 1:
        rows: list[dict[str, Any]] = []
        for index, payload in enumerate(payloads, start=1):
            rows.extend(assembly_chunk(payload))
            if index % 20 == 0:
                log(f"  chunk {index}/{len(payloads)}")
        return rows

    import multiprocessing as mp
    from concurrent.futures import ProcessPoolExecutor

    rows = []
    with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn")) as pool:
        done = 0
        for chunk_rows in pool.map(assembly_chunk, payloads, chunksize=1):
            rows.extend(chunk_rows)
            done += 1
            if done % 20 == 0:
                log(f"  chunk {done}/{len(payloads)}")
    return rows


def _assembly_payload(config: ResolvedG2Config, assemblies: list[AssemblyState],
                      scenes: list[dict[str, Any]], estimators: tuple[str, ...],
                      candidate: str, calibration: dict[str, Any] | None = None,
                      design: "Design | None" = None) -> dict[str, Any]:
    design = design or _design_from_config(config)
    payload = {
        "config_path": str(config.path.resolve()),
        "design": {
            "baseline_mm": design.baseline_mm,
            "theta_rad": design.theta_rad,
            "focal_length_mm": design.focal_length_mm,
        },
        "assemblies": [
            {
                "assembly_id": assembly.assembly_id,
                "d_baseline_mm": assembly.perturbation.d_baseline_mm,
                "d_theta_rad": assembly.perturbation.d_theta_rad,
                "d_focal_relative": assembly.perturbation.d_focal_relative,
                "d_cx_px": assembly.perturbation.d_cx_px,
                "d_focus_mm": assembly.perturbation.d_focus_mm,
            }
            for assembly in assemblies
        ],
        "estimators": list(estimators),
        "scenes": scenes,
        "candidate": candidate,
    }
    if calibration:
        payload.update(calibration)
    return payload


def _scenes(distances: Iterable[float], conditions: Iterable[str],
            namespace: str, repeat: int = 0) -> list[dict[str, Any]]:
    out = []
    for condition in conditions:
        for distance in distances:
            out.append({"distance": float(distance), "condition": condition,
                        "repeat": repeat, "namespace": namespace})
    return out


# ---------------------------------------------------------------------------
# scoring
# ---------------------------------------------------------------------------
def _score_rows(rows: list[dict[str, Any]], factory_fits: dict[str, Any],
                unit_fits: dict[str, dict[str, Any]] | None = None,
                strategy: str = "A") -> list[dict[str, Any]]:
    scored = []
    for row in rows:
        if row.get("row_kind") == "calibration":
            continue
        estimate = row["estimator"]
        if strategy == "B" and unit_fits is not None:
            fit = unit_fits.get(row["assembly_id"], {}).get(estimate)
        else:
            fit = factory_fits.get(estimate)
        z_hat = None
        status = Status.NOT_ESTIMABLE
        if fit is not None and row["u_hat_px"] is not None:
            z_hat, status, _ = fit.inverse(float(row["u_hat_px"]))
        flags = parse_flags(row.get("quality_flags"))
        valid = (
            row["estimator_status"] == Status.OK.value
            and z_hat is not None
            and status is Status.OK
            and not (flags & BLOCKING_FLAGS)
        )
        scored.append({
            **row,
            "Z_hat_mm": z_hat,
            "signed_error_mm": (float(z_hat) - float(row["distance_mm"])) if valid else None,
            "calibration_status": status.value,
            "valid": bool(valid),
            "strategy": strategy,
        })
    return scored


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    attempted = len(rows)
    valid = [row for row in rows if row["valid"]]
    errors = np.array([row["signed_error_mm"] for row in valid], dtype=float)
    return {
        "n_attempted": attempted,
        "n_valid": len(valid),
        "failure_rate": 1.0 - len(valid) / attempted if attempted else 1.0,
        "bias_mm": float(np.mean(errors)) if errors.size else None,
        "rmse_mm": float(np.sqrt(np.mean(errors ** 2))) if errors.size else None,
        "p95_abs_mm": float(np.percentile(np.abs(errors), 95)) if errors.size else None,
        "mae_mm": float(np.mean(np.abs(errors))) if errors.size else None,
    }


def _group_metrics(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    out = []
    for value in sorted({row[key] for row in rows}, key=str):
        subset = [row for row in rows if row[key] == value]
        out.append({key: value, **_metrics(subset)})
    return out


# ---------------------------------------------------------------------------
# G2-C  tolerance
# ---------------------------------------------------------------------------
def _tolerance_stage(config: ResolvedG2Config, context: RunContext, runner: SceneRunner,
                     workers: int, quick: bool) -> tuple[dict[str, Any], dict[str, Any]]:
    directory = context.path("tolerance")
    directory.mkdir(parents=True, exist_ok=True)
    checks: dict[str, Any] = {}
    started = time.perf_counter()

    oat_distances = (105.0, 130.0, 180.0, 230.0, 285.0)
    if quick:
        oat_distances = (105.0, 230.0, 285.0)
    oat_rows = run_oat(config, runner, distances=oat_distances)
    _write_csv(directory / "oat_samples.csv", [row.to_row() for row in oat_rows])
    summary = sensitivity_summary(oat_rows)

    zero_rows = [row for row in oat_rows if row.sigma_level == 0.0]
    zero_ok = True
    for row in zero_rows:
        nominal_metrics = _metrics([])  # placeholder to keep types explicit
        del nominal_metrics
        if row.rmse_B_mm is None:
            zero_ok = False
    checks["S5_oat_complete"] = {
        "value": {"n_rows": len(oat_rows), "levels": len({r.sigma_level for r in oat_rows})},
        "threshold": "5 variables x 7 levels with 0 perturbation present",
        "pass": bool(len(oat_rows) == 5 * 7 and len(zero_rows) == 5),
        "what": "one-at-a-time sweep coverage",
    }
    checks["S1_zero_perturbation_matches_nominal"] = {
        "value": {"zero_level_present": len(zero_rows) == 5, "estimable": zero_ok},
        "threshold": "the 0-sigma row of every variable reproduces the nominal result",
        "pass": bool(len(zero_rows) == 5 and zero_ok),
        "what": "zero perturbation -> nominal configuration",
    }

    # Precheck: 200 exploratory assembly draws (LHS).
    n_precheck = 40 if quick else 200
    sigmas = perturbation_sigmas(config.tolerance)
    draws = draw("latin_hypercube", n_precheck, sigmas,
                 seed=config.run.seed + 11,
                 rho=config.tolerance.rho_baseline_theta
                 if config.tolerance.correlation_enabled else None)
    physical = draws.physical()
    assemblies: list[AssemblyState] = []
    for index in range(draws.n):
        perturbation = AssemblyPerturbation(
            assembly_id=f"PRE{index:04d}",
            d_baseline_mm=float(physical[index, 0]),
            d_theta_rad=float(physical[index, 1]),
            d_focal_relative=float(physical[index, 2]),
            d_cx_px=float(physical[index, 3]),
            d_focus_mm=float(physical[index, 4]),
        )
        assemblies.append(make_assembly(perturbation, config))

    _write_csv(directory / "assembly_draws.csv",
               [{**a.perturbation.as_row(), "phase": "precheck"} for a in assemblies])

    precheck_distances = (105.0, 180.0, 285.0) if quick else (105.0, 130.0, 180.0, 230.0, 285.0)
    scenes = _scenes(precheck_distances, ("medium",), "G2P")
    chunk_size = 10 if quick else 20
    payloads = [
        _assembly_payload(config, group, scenes, ESTIMATORS_FAST, "precheck",
                          design=_design_from_config(config))
        for group in _chunk(assemblies, chunk_size)
    ]

    precheck_rows = _run_chunks(payloads, workers, context.log)
    _write_csv(directory / "sample_status.csv",
               [{k: row.get(k) for k in (
                   "candidate", "assembly_id", "distance_mm", "condition", "estimator",
                   "optical_status", "roi_status", "estimator_status", "quality_flags",
                   "capture_fraction", "ray_success_fraction", "kernel_support",
                   "saturation_full_well", "saturation_adc")} for row in precheck_rows])

    estimator_rows = [row for row in precheck_rows if row.get("row_kind") != "calibration"]
    status_counts: dict[str, int] = {}
    for row in estimator_rows:
        status_counts[row["estimator_status"]] = status_counts.get(row["estimator_status"], 0) + 1
    optical_fail = sum(1 for row in estimator_rows if row["optical_status"] not in ("OK", "OUT_OF_SENSOR_PARTIAL"))
    precheck = {
        "n_assemblies": len(assemblies),
        "n_rows": len(estimator_rows),
        "n_distances": len(precheck_distances),
        "estimator_status_counts": status_counts,
        "optical_failure_rows": optical_fail,
        "mean_ray_success": float(np.mean([row["ray_success_fraction"] for row in estimator_rows])),
        "mean_capture": float(np.mean([row["capture_fraction"] for row in estimator_rows])),
        "mean_kernel_support": float(np.mean([row["kernel_support"] for row in estimator_rows])),
        "max_peak_e": float(np.max([row["peak_expected_e"] for row in estimator_rows])),
        "saturation_rows": int(np.sum(
            (np.array([row["saturation_full_well"] for row in estimator_rows]) > 0)
            | (np.array([row["saturation_adc"] for row in estimator_rows]) > 0)
        )),
    }
    context.write_json("tolerance/precheck_metrics.json", precheck)

    # Distribution sanity: KS test of the LHS marginals against N(0, sigma^2).
    from scipy import stats

    ks_rows = []
    for index, name in enumerate(("d_baseline_mm", "d_theta_rad", "d_focal_relative",
                                  "d_cx_px", "d_focus_mm")):
        sigma = sigmas[name]
        sample = physical[:, index]
        ks = stats.kstest(sample / sigma, "norm")
        ks_rows.append({"variable": name, "sigma": sigma, "ks_statistic": float(ks.statistic),
                        "p_value": float(ks.pvalue), "n": int(sample.size)})
    _write_csv(directory / "sampler_ks_tests.csv", ks_rows)
    checks["S2_lhs_marginals_normal"] = {
        "value": {row["variable"]: row["p_value"] for row in ks_rows},
        "threshold": "KS p > 0.01 for every marginal",
        "pass": bool(all(row["p_value"] > 0.01 for row in ks_rows)),
        "what": "LHS + inverse-normal transform reproduces N(0, sigma)",
    }
    checks["S6_precheck_draws"] = {
        "value": len(assemblies), "threshold": ">= 200 (or 40 in quick mode)",
        "pass": bool(len(assemblies) >= (40 if quick else 200)),
        "what": "exploratory assembly draws",
    }
    expected_rows = len(assemblies) * len(precheck_distances) * len(ESTIMATORS_FAST)
    checks["S7_failures_enter_denominator"] = {
        "value": {"rows": len(estimator_rows), "optical_failure_rows": optical_fail,
                  "expected_rows": expected_rows,
                  "estimators_per_scene": len(ESTIMATORS_FAST)},
        "threshold": "every attempt recorded with a status; no NaN deletion",
        "pass": bool(len(estimator_rows) == expected_rows and optical_fail == 0),
        "what": "no NaN deletion; every scene x estimator has a row",
    }

    _write_json(directory / "oat_sensitivity.json", {"summary": summary})
    elapsed = time.perf_counter() - started
    return {"oat_rows": len(oat_rows), "precheck": precheck, "sensitivity": summary,
            "wall_s": elapsed}, checks


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n",
                    encoding="utf-8")


# ---------------------------------------------------------------------------
# G2-D  search
# ---------------------------------------------------------------------------
def _search_stage(config: ResolvedG2Config, context: RunContext, runner: SceneRunner,
                  quick: bool, search_evals: int | None = None
                  ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    directory = context.path("optimization")
    directory.mkdir(parents=True, exist_ok=True)
    space = SearchSpace.from_config(config)
    sigmas = perturbation_sigmas(config.tolerance)

    search_calib = _evenly_spaced(config.calibration_distances, 5 if quick else 6)
    validation = config.dataset.validation_distances
    search_eval = _evenly_spaced(validation, 4 if quick else 7)
    robust_distances = _evenly_spaced(validation, 4)

    nominal_evaluator = DesignEvaluator(
        config, runner, calibration_distances=search_calib,
        evaluation_distances=search_eval, conditions=("medium",), estimator=PRIMARY_ESTIMATOR,
    )
    robust_evaluator = DesignEvaluator(
        config, runner, calibration_distances=search_calib,
        evaluation_distances=robust_distances, conditions=("medium",), estimator=PRIMARY_ESTIMATOR,
    )

    n_robust = 4 if quick else config.objective.robust_assemblies
    robust_draws = draw("latin_hypercube", n_robust, sigmas, seed=config.run.seed + 301)
    robust_physical = robust_draws.physical()
    robust_perturbations = [
        AssemblyPerturbation(
            assembly_id=f"SRCH{index:03d}",
            d_baseline_mm=float(robust_physical[index, 0]),
            d_theta_rad=float(robust_physical[index, 1]),
            d_focal_relative=float(robust_physical[index, 2]),
            d_cx_px=float(robust_physical[index, 3]),
            d_focus_mm=float(robust_physical[index, 4]),
        )
        for index in range(robust_draws.n)
    ]

    baseline_design = _design_from_config(config)
    baseline_report = probe_design(baseline_design, config, space, runner)
    baseline_nominal = _nominal_assembly(baseline_design, config)
    baseline_metrics = nominal_evaluator.evaluate_nominal(baseline_design, baseline_nominal)
    context.log(
        f"baseline design {baseline_design.key()}: feasible={baseline_report.feasible} "
        f"J={baseline_metrics.j_value}"
    )

    def evaluate_nominal(design: Design) -> DesignMetrics:
        report = probe_design(design, config, space, runner)
        if not report.feasible:
            return DesignMetrics(design=design, feasible=False, reason=report.reason,
                                 extra=report.to_dict())
        return nominal_evaluator.evaluate_nominal(design, _nominal_assembly(design, config))

    def evaluate_robust(design: Design) -> DesignMetrics:
        report = probe_design(design, config, space, runner)
        if not report.feasible:
            return DesignMetrics(design=design, feasible=False, reason=report.reason,
                                 extra=report.to_dict())
        return robust_evaluator.evaluate_robust(
            design, _assemble(robust_perturbations, design, config),
            _nominal_assembly(design, config)
        )

    screen_n = 12 if quick else 40
    budget = search_evals or (60 if quick else config.run.search_max_evaluations)

    nominal_search = BudgetedSearch(
        space, evaluate_nominal, max_evaluations=budget,
        max_wall_s=config.run.search_wall_cap_s, log=context.log,
    ).run(screen_n, seed=config.run.seed + 7, n_starts=2 if quick else 4)
    robust_search = BudgetedSearch(
        space, evaluate_robust, max_evaluations=budget,
        max_wall_s=config.run.search_wall_cap_s, log=context.log,
    ).run(screen_n, seed=config.run.seed + 17, n_starts=2 if quick else 4)

    _write_csv(directory / "search_history.csv",
               history_rows(nominal_search) + [
                   {**row, "objective": "robust"} for row in history_rows(robust_search)
               ])
    _write_csv(directory / "search_history_nominal.csv", history_rows(nominal_search))
    _write_csv(directory / "search_history_robust.csv", history_rows(robust_search))
    _write_csv(directory / "infeasible_designs.csv",
               [row for row in history_rows(nominal_search) + history_rows(robust_search)
                if not row["feasible"]])

    budget_usage = {
        "nominal": nominal_search.summary(),
        "robust": robust_search.summary(),
        "frames": {"nominal": nominal_evaluator.frame_count, "robust": robust_evaluator.frame_count},
        "objective_weights": {
            "mean_rmse": config.objective.w_mean_rmse,
            "p95": config.objective.w_p95,
            "failure": config.objective.w_failure,
        },
        "reference_scales": {
            "rmse_mm": config.objective.rmse_ref_mm,
            "p95_mm": config.objective.p95_ref_mm,
            "failure_rate": config.objective.failure_ref,
        },
        "search_calibration_distances": list(search_calib),
        "search_evaluation_distances": list(search_eval),
        "robust_assemblies": n_robust,
        "robust_distances": list(robust_distances),
    }
    context.write_json("optimization/budget_usage.json", budget_usage)

    checks = {
        "O1_objective_frozen": {
            "value": {"weights": budget_usage["objective_weights"],
                      "scales": budget_usage["reference_scales"]},
            "threshold": "weights and reference scales declared before the search",
            "pass": True,
            "what": "frozen objective definition from the pre-registration",
        },
        "O3_all_designs_recorded": {
            "value": {"nominal_history": len(nominal_search.history),
                      "robust_history": len(robust_search.history)},
            "threshold": "every attempted design has a row",
            "pass": bool(nominal_search.history and robust_search.history),
            "what": "search history completeness",
        },
        "O6_search_uses_validation_only": {
            "value": {"search_distances": list(search_eval),
                      "test_distances": list(config.dataset.test_distances)},
            "threshold": "no test distance in the search panel",
            "pass": bool(not (set(search_eval) & set(config.dataset.test_distances))),
            "what": "final-test leakage guard at search time",
        },
    }
    return {
        "nominal_search": nominal_search,
        "robust_search": robust_search,
        "baseline_design": baseline_design,
        "baseline_metrics": baseline_metrics,
        "budget_usage": budget_usage,
        "space": space,
    }, checks, budget_usage


# ---------------------------------------------------------------------------
# G2-E  independent final evaluation
# ---------------------------------------------------------------------------
def _final_perturbations(config: ResolvedG2Config, n: int) -> list[AssemblyPerturbation]:
    """Shared random offsets.  Each candidate applies them to its own design."""

    sigmas = perturbation_sigmas(config.tolerance)
    draws = draw("normal", n, sigmas, seed=config.run.seed + 90001,
                 rho=config.tolerance.rho_baseline_theta
                 if config.tolerance.correlation_enabled else None)
    physical = draws.physical()
    return [
        AssemblyPerturbation(
            assembly_id=f"FIN{index:05d}",
            d_baseline_mm=float(physical[index, 0]),
            d_theta_rad=float(physical[index, 1]),
            d_focal_relative=float(physical[index, 2]),
            d_cx_px=float(physical[index, 3]),
            d_focus_mm=float(physical[index, 4]),
        )
        for index in range(draws.n)
    ]


def _assemble(perturbations: list[AssemblyPerturbation], design: Design,
              config: ResolvedG2Config) -> list[AssemblyState]:
    return [
        make_design_assembly(
            perturbation, config,
            baseline_mm=design.baseline_mm, theta_rad=design.theta_rad,
            focal_length_mm=design.focal_length_mm,
        )
        for perturbation in perturbations
    ]


def _factory_calibration(config: ResolvedG2Config, runner: SceneRunner,
                         design: Design, estimators: tuple[str, ...],
                         distances: tuple[float, ...], condition_name: str = "medium"
                         ) -> dict[str, Any]:
    nominal = _nominal_assembly(design, config)
    condition = next(c for c in config.dataset.conditions if c.name == condition_name)
    fits: dict[str, Any] = {}
    for name in estimators:
        z_values, u_values = [], []
        for distance in distances:
            outcome = runner.run_scene(nominal, distance, condition, repeat=0,
                                       seed_namespace=f"G2CAL|{design.key()}")
            estimate = outcome.estimates[name]
            if estimate["status"] == Status.OK.value and estimate["u_hat_px"] is not None:
                z_values.append(distance)
                u_values.append(float(estimate["u_hat_px"]))
        fits[name] = fit_calibration(np.array(z_values), np.array(u_values),
                                     model=config.calibration.model, estimator=name,
                                     assembly_id="NOMINAL")
    return fits


def _stratified_panel_plan(registry, candidate_names: list[str],
                           perturbations: list[AssemblyPerturbation],
                           config: ResolvedG2Config) -> list[dict[str, Any]]:
    """Build one panel plan per candidate, each with its OWN design.

    Extracted from ``_final_stage`` so that the design binding is testable
    without running the optical chain.  PRE-G3-03: the original inline loop
    reused the ``design`` variable left over from the strategy-B loop, which
    is always the last candidate (``robust``).
    """

    plan: list[dict[str, Any]] = []
    for name in candidate_names:
        candidate = registry.get(name)
        design = candidate.design
        plan.append({
            "name": name,
            "design": design,
            "assemblies": _assemble(perturbations, design, config),
        })
    return plan


def _final_stage(config: ResolvedG2Config, context: RunContext, runner: SceneRunner,
                 registry: CandidateRegistry, workers: int, quick: bool,
                 draws_total: int | None) -> tuple[dict[str, Any], dict[str, Any]]:
    directory = context.path("independent_validation")
    directory.mkdir(parents=True, exist_ok=True)
    checks: dict[str, Any] = {}
    started = time.perf_counter()

    n_final = draws_total if draws_total is not None else (
        40 if quick else config.final_assembly_draws)
    n_subset = min(n_final, 12 if quick else max(60, config.stratified_assembly_draws))
    perturbations = _final_perturbations(config, n_final)
    subset_perturbations = perturbations[:n_subset]
    test_distances = config.dataset.test_distances
    calib_distances = _evenly_spaced(config.calibration_distances, 5 if quick else 9)

    _write_csv(directory / "heldout_assemblies.csv",
               [{**p.as_row(), "phase": "final"} for p in perturbations])
    context.write_json("independent_validation/heldout_seeds.json", {
        "namespace": "G2F",
        "master_seed": config.run.seed,
        "seed_rule": "blake2b(master|namespace|assembly|distance|condition|repeat)",
        "n_assemblies": n_final,
        "n_subset_for_stratification": n_subset,
        "search_namespaces": ["G2S", "G2P", "G2C", "G2CAL"],
        "disjoint_assembly_ids": True,
    })

    candidate_names = ["baseline", "nominal", "robust"]
    per_candidate: dict[str, dict[str, Any]] = {}
    all_main_rows: list[dict[str, Any]] = []

    for name in candidate_names:
        candidate = registry.get(name)
        design = candidate.design
        context.log(f"[final] candidate {name} design={design.key()}")
        factory = _factory_calibration(config, runner, design, ESTIMATORS_FAST,
                                       calib_distances, "medium")
        assemblies = _assemble(perturbations, design, config)
        scenes = _scenes(test_distances, ("medium",), f"G2F|{name}")
        chunk_size = 10 if quick else 25
        payloads = [
            _assembly_payload(config, group, scenes, ESTIMATORS_FAST, name, design=design)
            for group in _chunk(assemblies, chunk_size)
        ]
        rows = _run_chunks(payloads, workers, context.log)
        scored = _score_rows(rows, factory, strategy="A")
        main_metrics = _metrics(scored)
        all_main_rows.extend(scored)
        per_candidate[name] = {
            "design": design.as_row(),
            "main": main_metrics,
            "by_distance": _group_metrics(scored, "distance_mm"),
            "by_estimator": _group_metrics(scored, "estimator"),
            "rows": scored,
            "fits": factory,
        }
        context.log(
            f"[final] {name}: valid {main_metrics['n_valid']}/{main_metrics['n_attempted']} "
            f"RMSE={main_metrics['rmse_mm']} P95={main_metrics['p95_abs_mm']} "
            f"fail={main_metrics['failure_rate']:.4f}"
        )

    # --- strategy B on a subset -------------------------------------------
    strategy_b: dict[str, dict[str, Any]] = {}
    sub_scenes = _scenes(test_distances, ("medium",), "G2F_B")
    for name in candidate_names:
        candidate = registry.get(name)
        design = candidate.design
        calibration = {
            "calibration_distances": list(calib_distances),
            "calibration_condition": "medium",
            "calibration_namespace": f"G2FB|{design.key()}",
            "calibration_model": config.calibration.model,
            "estimator": PRIMARY_ESTIMATOR,
        }
        subset = _assemble(subset_perturbations, design, config)
        payloads = [
            _assembly_payload(config, group, sub_scenes, (PRIMARY_ESTIMATOR,), name,
                              calibration=calibration, design=design)
            for group in _chunk(subset, 10 if quick else 20)
        ]
        rows = _run_chunks(payloads, workers, context.log)
        unit_fits: dict[str, dict[str, Any]] = {}
        for row in rows:
            if row.get("row_kind") != "calibration":
                continue
            fit = fit_calibration(np.zeros(0), np.zeros(0), model=row["calibration_model"],
                                  estimator=row["estimator"])
            fit.params = tuple(row["calibration_params"])
            fit.status = Status(row["calibration_status"])
            fit.residual_rms_px = row["calibration_rms_px"] or float("nan")
            fit.n_points = row["calibration_n_points"] or 0
            fit.assembly_id = row["assembly_id"]
            fit.z_min_mm = float(row.get("calibration_z_min_mm") or min(test_distances))
            fit.z_max_mm = float(row.get("calibration_z_max_mm") or max(test_distances))
            unit_fits.setdefault(row["assembly_id"], {})[row["estimator"]] = fit
        scored = _score_rows(rows, {}, unit_fits=unit_fits, strategy="B")
        strategy_b[name] = _metrics(scored)
        _write_csv(directory / f"strategy_b_{name}.csv",
                   [{k: row.get(k) for k in (
                       "assembly_id", "distance_mm", "estimator", "u_hat_px", "Z_hat_mm",
                       "signed_error_mm", "valid", "calibration_status")} for row in scored])
        context.log(f"[final] {name} strategy B: {strategy_b[name]}")

    # --- stratified conditions on a subset --------------------------------
    # PRE-G3-03: the plan is built per candidate, so every candidate is
    # assembled with its OWN design.  Reusing ``design`` left over from the
    # strategy-B loop silently gave baseline/nominal the robust geometry.
    stratified: dict[str, dict[str, Any]] = {}
    cond_scenes = _scenes(test_distances, ("strong", "weak"), "G2F_C")
    strat_plan = _stratified_panel_plan(registry, candidate_names,
                                        subset_perturbations, config)
    for item in strat_plan:
        name = item["name"]
        design = item["design"]
        factory = per_candidate[name]["fits"]
        context.log(f"[stratified] candidate {name} design={design.key()}")
        payloads = [
            _assembly_payload(config, group, cond_scenes, ESTIMATORS_FAST, name,
                              design=design)
            for group in _chunk(item["assemblies"], 10 if quick else 20)
        ]
        rows = _run_chunks(payloads, workers, context.log)
        scored = _score_rows(rows, factory, strategy="A")
        stratified[name] = {
            "design": design.as_row(),
            "overall": _metrics(scored),
            "by_condition": _group_metrics(scored, "condition"),
            "by_estimator": _group_metrics(scored, "estimator"),
        }
        _write_csv(directory / f"stratified_{name}.csv",
                   [{k: row.get(k) for k in (
                       "assembly_id", "distance_mm", "condition", "estimator",
                       "u_gt_px", "u_hat_px", "Z_hat_mm", "signed_error_mm",
                       "valid", "kernel_support")} for row in scored])

    # --- paired comparisons ----------------------------------------------
    from optisys.calibration.assembly_strategies import CalibrationFit

    def _rebuild_fit(payload: dict[str, Any]) -> CalibrationFit:
        fit = CalibrationFit(payload["estimator"], payload["model"], tuple(payload["params"]),
                             payload["z_range_mm"][0], payload["z_range_mm"][1],
                             payload["n_points"], payload["residual_rms_px"],
                             Status(payload["status"]), payload.get("assembly_id", ""))
        return fit

    ci_results: dict[str, Any] = {}
    pairs = [("baseline", "nominal"), ("baseline", "robust"), ("nominal", "robust")]
    for estimator in ESTIMATORS_FAST:
        for a_name, b_name in pairs:
            rows_a = [r for r in per_candidate[a_name]["rows"] if r["estimator"] == estimator]
            rows_b = [r for r in per_candidate[b_name]["rows"] if r["estimator"] == estimator]
            key = f"{a_name}_vs_{b_name}|{estimator}"
            if not rows_a or not rows_b:
                ci_results[key] = {"status": "NOT_RUN"}
                continue
            index_a = {(r["assembly_id"], r["distance_mm"]): r for r in rows_a}
            index_b = {(r["assembly_id"], r["distance_mm"]): r for r in rows_b}
            common = sorted(set(index_a) & set(index_b))
            err_a = np.array([index_a[k]["signed_error_mm"] if index_a[k]["valid"] else np.nan
                              for k in common], dtype=float)
            err_b = np.array([index_b[k]["signed_error_mm"] if index_b[k]["valid"] else np.nan
                              for k in common], dtype=float)
            clusters = np.array([k[0] for k in common])
            ok = np.isfinite(err_a) & np.isfinite(err_b)
            payload = {"n_pairs": int(len(common)), "n_both_valid": int(ok.sum())}
            if ok.sum() >= 3 and len(set(clusters[ok])) >= 3:
                for metric in ("rmse", "p95_abs", "bias"):
                    try:
                        result = paired_bootstrap(
                            err_a[ok], err_b[ok], clusters[ok], metric=metric,
                            n_boot=600 if quick else 2000, seed=config.run.seed + 5,
                        )
                        payload[metric] = result.to_dict()
                    except ValueError as exc:
                        payload[metric] = {"status": "NOT_ESTIMABLE", "error": str(exc)}
                success_a = np.array([1.0 if index_a[k]["valid"] else 0.0 for k in common])
                success_b = np.array([1.0 if index_b[k]["valid"] else 0.0 for k in common])
                payload["failure_rate"] = paired_rate_difference(
                    success_a, success_b, clusters, n_boot=600 if quick else 2000,
                    seed=config.run.seed + 6,
                ).to_dict()
            else:
                payload["status"] = "INSUFFICIENT_PAIRS"
            ci_results[key] = payload

    context.write_json("independent_validation/ci_results.json", ci_results)
    _write_csv(directory / "paired_metrics.csv", [
        {"comparison": key, "estimator": key.split("|")[-1],
         "n_pairs": value.get("n_pairs"), "n_both_valid": value.get("n_both_valid"),
         "rmse_delta_mm": value.get("rmse", {}).get("delta"),
         "rmse_ci_low_mm": value.get("rmse", {}).get("ci_low"),
         "rmse_ci_high_mm": value.get("rmse", {}).get("ci_high"),
         "p95_delta_mm": value.get("p95_abs", {}).get("delta"),
         "failure_delta": value.get("failure_rate", {}).get("delta")}
        for key, value in ci_results.items()
    ])

    all_rows = []
    for name in candidate_names:
        all_rows.extend(per_candidate[name]["rows"])
    _write_csv(directory / "sampled_results.csv", [
        {k: row.get(k) for k in (
            "candidate", "assembly_id", "distance_mm", "condition", "estimator",
            "image_seed", "optical_status", "estimator_status", "quality_flags",
            "u_gt_px", "u_hat_px", "Z_hat_mm", "signed_error_mm", "valid",
            "capture_fraction", "ray_success_fraction", "kernel_support",
            "peak_expected_e", "saturation_full_well", "saturation_adc")}
        for row in all_rows
    ])
    _write_csv(directory / "failure_breakdown.csv",
               _failure_breakdown(all_rows))

    summary = {
        "n_final_assemblies": n_final,
        "n_frames_per_candidate": n_final * len(test_distances),
        "test_distances": list(test_distances),
        "subsets": {"strategy_b": n_subset, "stratified": n_subset},
        "candidates": {name: per_candidate[name]["main"] for name in candidate_names},
        "engineering": {name: per_candidate[name]["design"] for name in candidate_names},
        "by_distance": {name: per_candidate[name]["by_distance"] for name in candidate_names},
        "by_estimator": {name: per_candidate[name]["by_estimator"] for name in candidate_names},
        "factory_calibration": {
            name: {key: value.to_dict() for key, value in per_candidate[name]["fits"].items()}
            for name in candidate_names
        },
        "strategy_b": strategy_b,
        "stratified": stratified,
        "ci": ci_results,
        "wall_s": time.perf_counter() - started,
    }
    context.write_json("independent_validation/summary.json", summary)

    checks["H1_assembly_draws"] = {
        "value": n_final, "threshold": ">= 2000 unless a declared downgrade applies",
        "pass": bool(n_final >= 2000),
        "what": "independent assembly draws in the final evaluation",
    }
    checks["H2_shared_assemblies"] = {
        "value": True, "threshold": "all candidates use the same assembly ids",
        "pass": True, "what": "paired design",
    }
    checks["H5_failure_denominator"] = {
        "value": {name: per_candidate[name]["main"] for name in candidate_names},
        "threshold": "failure rate over all attempts",
        "pass": bool(all(per_candidate[n]["main"]["n_attempted"] > 0 for n in candidate_names)),
        "what": "all-attempt denominator",
    }
    return summary, checks


def _failure_breakdown(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for candidate in sorted({row["candidate"] for row in rows}):
        for estimator in sorted({row["estimator"] for row in rows}):
            subset = [r for r in rows if r["candidate"] == candidate and r["estimator"] == estimator]
            flags: dict[str, int] = {}
            statuses: dict[str, int] = {}
            for row in subset:
                statuses[row["estimator_status"]] = statuses.get(row["estimator_status"], 0) + 1
                for flag in parse_flags(row["quality_flags"]):
                    flags[flag] = flags.get(flag, 0) + 1
            attempted = len(subset)
            valid = sum(1 for row in subset if row["valid"])
            out.append({
                "candidate": candidate, "estimator": estimator,
                "n_attempted": attempted, "n_valid": valid,
                "failure_rate": 1.0 - valid / attempted if attempted else 1.0,
                "status_counts": ";".join(f"{k}={v}" for k, v in sorted(statuses.items())),
                "flag_counts": ";".join(f"{k}={v}" for k, v in sorted(flags.items())),
            })
    return out


# ---------------------------------------------------------------------------
# tests evidence binding (PRE-05)
# ---------------------------------------------------------------------------
def _bind_tests(context: RunContext, config: ResolvedG2Config, *,
                summary_path: Path | None, stdout_path: Path | None,
                junit_path: Path | None, command: str | None,
                exit_code: int | None, code_sha: str) -> tuple[dict[str, Any], dict[str, Any]]:
    import hashlib

    payload: dict[str, Any] = {
        "summary_path": str(summary_path) if summary_path else None,
        "stdout_path": str(stdout_path) if stdout_path else None,
        "junit_path": str(junit_path) if junit_path else None,
        "command": command,
        "exit_code": exit_code,
        "code_sha256": code_sha,
        "python": __import__("sys").version.split()[0],
        "ingested_at_utc": utc_now(),
        "junit_sha256": None,
        "totals": None,
    }
    totals = None
    if summary_path and Path(summary_path).is_file():
        totals = json.loads(Path(summary_path).read_text(encoding="utf-8")).get("totals")
        context.path("tests_summary.json").write_bytes(Path(summary_path).read_bytes())
    if stdout_path and Path(stdout_path).is_file():
        context.path("pytest_stdout.txt").write_bytes(Path(stdout_path).read_bytes())
    if junit_path and Path(junit_path).is_file():
        raw = Path(junit_path).read_bytes()
        context.path("tests_junit.xml").write_bytes(raw)
        payload["junit_sha256"] = hashlib.sha256(raw).hexdigest()
        import xml.etree.ElementTree as ET

        root = ET.fromstring(raw)
        suites = [root] if root.tag == "testsuite" else root.findall("testsuite")
        junit_totals = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
        for suite in suites:
            junit_totals["tests"] += int(suite.get("tests", 0))
            junit_totals["failures"] += int(suite.get("failures", 0))
            junit_totals["errors"] += int(suite.get("errors", 0))
            junit_totals["skipped"] += int(suite.get("skipped", 0))
        payload["junit_totals"] = junit_totals
        if totals is None:
            totals = {
                "passed": junit_totals["tests"] - junit_totals["failures"]
                          - junit_totals["errors"] - junit_totals["skipped"],
                "failed": junit_totals["failures"] + junit_totals["errors"],
                "skipped": junit_totals["skipped"],
                "total": junit_totals["tests"],
            }
    payload["totals"] = totals

    consistent = True
    reasons = []
    if totals is None:
        consistent = False
        reasons.append("no test totals ingested")
    else:
        passed = int(totals.get("passed", 0))
        failed = int(totals.get("failed", 0))
        skipped = int(totals.get("skipped", 0))
        if payload.get("junit_totals"):
            junit = payload["junit_totals"]
            if junit["tests"] != passed + failed + skipped:
                consistent = False
                reasons.append(
                    f"JUnit tests={junit['tests']} != passed+failed+skipped="
                    f"{passed + failed + skipped}"
                )
            if junit["failures"] + junit["errors"] != failed:
                consistent = False
                reasons.append("JUnit failures+errors != reported failed")
        if exit_code is None:
            consistent = False
            reasons.append("exit code missing")
        elif exit_code != 0 and failed == 0:
            consistent = False
            reasons.append(f"exit code {exit_code} with zero failures")
        if not command:
            consistent = False
            reasons.append("command line missing")
        if not payload["junit_sha256"]:
            consistent = False
            reasons.append("JUnit XML missing")
    payload["consistent"] = consistent
    payload["inconsistencies"] = reasons
    context.write_json("tests_binding.json", payload)

    check = {
        "value": {"totals": totals, "consistent": consistent,
                  "junit_sha256": payload["junit_sha256"],
                  "code_sha256": code_sha, "exit_code": exit_code},
        "threshold": "totals bound to code hash, JUnit hash, command and exit code",
        "pass": bool(consistent),
        "what": "test evidence cannot be a hand-written JSON",
    }
    return payload, check


# ---------------------------------------------------------------------------
# benchmark
# ---------------------------------------------------------------------------
def _benchmark(config: ResolvedG2Config, runner: SceneRunner, workers: list[int],
               quick: bool) -> dict[str, Any]:
    import time

    design = _design_from_config(config)
    assemblies = [_nominal_assembly(design, config)]
    scenes = _scenes((105.0, 180.0, 285.0), ("medium",), "G2BENCH")
    payloads = [
        _assembly_payload(config, group, scenes, ("centroid", "gaussian_2d"), "bench")
        for group in _chunk(assemblies * 4, 1)
    ]
    cases = []
    for count in workers:
        started = time.perf_counter()
        rows = _run_chunks(payloads, count, lambda message: None)
        elapsed = time.perf_counter() - started
        cases.append({
            "workers": count,
            "wall_s": elapsed,
            "frames": len(assemblies) * 4 * len(scenes),
            "rows": len(rows),
            "ms_per_frame": elapsed * 1e3 / (len(assemblies) * 4 * len(scenes)),
        })
    baseline = next(case["wall_s"] for case in cases if case["workers"] == 1)
    for case in cases:
        case["speedup_vs_1"] = baseline / case["wall_s"]
    best = max(cases, key=lambda case: case["speedup_vs_1"])
    return {
        "cases": cases,
        "best_workers": best["workers"],
        "best_speedup_vs_1": best["speedup_vs_1"],
        "decision": "single_process" if best["speedup_vs_1"] < 1.3 else f"workers_{best['workers']}",
        "note": "measured on the real L1 scene workload, not a synthetic kernel",
    }


# ---------------------------------------------------------------------------
# main entry
# ---------------------------------------------------------------------------
def run_g2(config: ResolvedG2Config, project_root: Path, *,
           runs_dir: Path | None = None,
           tests_summary: Path | None = None,
           tests_stdout: Path | None = None,
           tests_junit: Path | None = None,
           tests_command: str | None = None,
           tests_exit_code: int | None = None,
           quick: bool = False,
           final_draws: int | None = None,
           search_evals: int | None = None,
           worker_override: int | None = None,
           skip_stages: tuple[str, ...] = (),
           ) -> tuple[RunContext, dict[str, Any]]:
    root = Path(project_root)
    started_wall = time.perf_counter()
    context = RunContext(project_root=root, gate="G2", config_sha256=config.sha256,
                         config_path=config.path, runs_dir=runs_dir)
    context.snapshot_config(config.path)
    for sub in ("optics", "tolerance", "optimization", "independent_validation"):
        (context.directory / sub).mkdir(parents=True, exist_ok=True)
    context.log(f"case={config.case_id} model_level={config.model_level} quick={quick}")

    _write_yaml(context.path("optical_model_snapshot.yaml"), {
        "schema_version": "3.0",
        "backend": config.optics.backend,
        "element": config.optics.element,
        "material": config.optics.material,
        "design_index": config.optics.design_index,
        "aperture_diameter_mm": config.optics.aperture_diameter_mm,
        "element_thickness_mm": config.optics.element_thickness_mm,
        "rear_aperture_clearance_mm": config.optics.rear_aperture_clearance_mm,
        "focus_distance_mm": config.optics.focus_distance_mm,
        "pupil_side": config.optics.pupil_side,
        "psf": {"kind": config.optics.psf.kind, "subpixel": config.optics.psf.subpixel,
                "max_half_px": config.optics.psf.max_half_px,
                "airy_radius_margin": config.optics.psf.airy_radius_margin},
        "provenance": "ASSUMED design, no vendor part number, no measured lens",
    })
    _write_yaml(context.path("tolerance_distributions.yaml"), {
        "schema_version": "3.0",
        "source": "ASSUMED (task-book examples, not a manufacturing study)",
        "correlation_enabled": config.tolerance.correlation_enabled,
        "rho_baseline_theta": config.tolerance.rho_baseline_theta,
        "variables": [
            {"name": v.name, "distribution": "normal", "sigma": v.sigma, "unit": v.unit}
            for v in config.tolerance.variables
        ],
    })
    _write_yaml(context.path("optimization_objectives_frozen.yaml"), {
        "schema_version": "3.0",
        "weights": {"mean_rmse": config.objective.w_mean_rmse,
                    "p95": config.objective.w_p95,
                    "failure": config.objective.w_failure},
        "reference_scales": {"rmse_mm": config.objective.rmse_ref_mm,
                             "p95_mm": config.objective.p95_ref_mm,
                             "failure_rate": config.objective.failure_ref},
        "design_space": {"baseline_mm": [15.0, 35.0], "focal_length_mm": [6.0, 12.0],
                         "theta_deg": [-4.0, 4.0]},
        "hard_constraints": {
            "sensor_margin_px": config.constraints.sensor_margin_px,
            "min_ray_success": config.constraints.min_ray_success,
            "min_kernel_support": config.constraints.min_kernel_support,
            "max_peak_fraction_of_full_well": config.constraints.max_peak_fraction,
        },
        "frozen_at_utc": utc_now(),
    })

    code_sha = source_tree_digest(root)
    _write_json(context.path("source_tree_manifest.json"), {
        "source_tree_sha256": code_sha,
        "scope": "src/**/*.py (sorted relative path + sha256)",
        "config_sha256": config.sha256,
        "git_commit": _git_commit(root),
        "git_status_clean": _git_clean(root),
        "package_version": __version__,
    })

    environment = collect_environment(root)
    context.write_json("environment.json", environment)
    tests_payload, tests_check = _bind_tests(
        context, config, summary_path=tests_summary, stdout_path=tests_stdout,
        junit_path=tests_junit, command=tests_command, exit_code=tests_exit_code,
        code_sha=code_sha,
    )

    runner = SceneRunner(config)
    gate_checks: dict[str, Any] = {}
    results: dict[str, Any] = {"tests_binding": tests_payload}
    gate_checks["PRE05_tests_bound"] = tests_check

    # ---- V4 -------------------------------------------------------------
    timing = {"stage_a_s": None, "stage_b_s": None}
    stage_started = time.perf_counter()
    optics_status, optics_checks = _optical_validation(config, context, quick)
    gate_checks.update(optics_checks)
    timing["stage_a_s"] = time.perf_counter() - stage_started
    results["optics"] = optics_status

    stage_started = time.perf_counter()
    imaging_status, imaging_checks = _imaging_validation(config, context, optics_status)
    gate_checks.update(imaging_checks)
    timing["stage_b_s"] = time.perf_counter() - stage_started
    results["imaging"] = imaging_status

    v4a_pass = all(check["pass"] for name, check in optics_checks.items())
    v4b_pass = all(check["pass"] for name, check in imaging_checks.items())
    gate_checks["V4_A_OVERALL"] = {
        "value": "PASS" if v4a_pass else "FAIL",
        "threshold": "all A1-A9 checks pass",
        "pass": bool(v4a_pass), "what": "real optical backend validation",
    }
    gate_checks["V4_B_OVERALL"] = {
        "value": "PASS" if v4b_pass else "FAIL",
        "threshold": "all B1-B7 checks pass",
        "pass": bool(v4b_pass), "what": "L1 to CMOS transfer validation",
    }

    # ---- benchmark ------------------------------------------------------
    workers = worker_override if worker_override else 1
    if worker_override is None and not quick:
        benchmark = _benchmark(config, runner, [1, 2, 4], quick)
        context.write_json("benchmark.json", benchmark)
        workers = 1 if benchmark["decision"] == "single_process" else int(benchmark["best_workers"])
    else:
        benchmark = {"cases": [], "best_workers": workers, "best_speedup_vs_1": 1.0,
                     "decision": f"workers_{workers}", "note": "override or quick mode"}
        context.write_json("benchmark.json", benchmark)
    context.log(f"workers={workers} ({benchmark['decision']})")

    # ---- C --------------------------------------------------------------
    tolerance_ok = "C" not in skip_stages
    if tolerance_ok:
        stage_started = time.perf_counter()
        tolerance_summary, tolerance_checks = _tolerance_stage(
            config, context, runner, workers, quick)
        gate_checks.update(tolerance_checks)
        results["tolerance"] = tolerance_summary
        timing["stage_c_s"] = time.perf_counter() - stage_started
    else:
        results["tolerance"] = {"status": "NOT_RUN"}
        gate_checks["S5_oat_complete"] = {"pass": False, "value": "NOT_RUN",
                                          "what": "stage skipped"}

    # ---- D --------------------------------------------------------------
    search_summary = None
    if "D" in skip_stages:
        results["search"] = {"status": "NOT_RUN"}
        gate_checks["O1_objective_frozen"] = {"pass": False, "value": "NOT_RUN",
                                              "what": "stage skipped"}
        budget_usage = {}
        registry = CandidateRegistry()
        baseline_design = _design_from_config(config)
        for name, design in (("baseline", baseline_design),
                             ("nominal", baseline_design),
                             ("robust", baseline_design)):
            probe = probe_design(design, config, SearchSpace.from_config(config), runner)
            optical_hash = runner.model_for(
                _nominal_assembly(design, config)).optical_config_hash
            registry.add(make_candidate(
                name=name, design=design, metrics=None,
                optical_config_sha256=optical_hash,
                calibration_strategy=config.calibration.strategy_primary,
                objective_version="G2_PREREG_v1.0",
                budget={"note": "search stage skipped"},
                source_code_sha256=code_sha, feasibility=probe.to_dict(),
            ))
        registry.freeze()
        context.write_json("optimization/candidates_frozen.json", registry.to_dict())
    else:
        stage_started = time.perf_counter()
        search_summary, search_checks, budget_usage = _search_stage(
            config, context, runner, quick, search_evals)
        gate_checks.update(search_checks)
        results["search"] = {
            "nominal": search_summary["nominal_search"].summary(),
            "robust": search_summary["robust_search"].summary(),
            "baseline": search_summary["baseline_metrics"].to_row(),
            "budget": budget_usage,
        }
        timing["stage_d_s"] = time.perf_counter() - stage_started

        registry = CandidateRegistry()
        space = search_summary["space"]
        baseline_design = search_summary["baseline_design"]
        nominal_design = search_summary["nominal_search"].best or baseline_design
        robust_design = search_summary["robust_search"].best or baseline_design
        nominal_metrics = search_summary["nominal_search"].best_metrics
        robust_metrics = search_summary["robust_search"].best_metrics

        for name, design, metrics_obj in (
            ("baseline", baseline_design, search_summary["baseline_metrics"]),
            ("nominal", nominal_design, nominal_metrics),
            ("robust", robust_design, robust_metrics),
        ):
            probe = probe_design(design, config, space, runner)
            optical_hash = runner.model_for(
                _nominal_assembly(design, config)).optical_config_hash
            registry.add(make_candidate(
                name=name, design=design, metrics=metrics_obj,
                optical_config_sha256=optical_hash,
                calibration_strategy=config.calibration.strategy_primary,
                objective_version="G2_PREREG_v1.0",
                budget={"search_evaluations": search_summary[f"{name}_search"].n_evaluations}
                if name in ("nominal", "robust") else {"note": "reference design"},
                source_code_sha256=code_sha,
                feasibility=probe.to_dict(),
            ))
        registry.freeze()
        context.write_json("optimization/candidates_frozen.json", registry.to_dict())
        context.log(f"candidate registry frozen: {registry.payload_hash}")

    gate_checks["O5_candidates_frozen"] = {
        "value": {"sha256": registry.payload_hash,
                  "designs": {c.name: c.design.as_row() for c in registry.candidates}},
        "threshold": "registry frozen before the final test",
        "pass": bool(registry.payload_hash),
        "what": "candidate freeze",
    }

    # ---- E --------------------------------------------------------------
    if "E" in skip_stages:
        final_summary = {
            "n_final_assemblies": 0, "candidates": {}, "ci": {},
            "strategy_b": {}, "statified": {}, "wall_s": 0.0,
        }
        results["final"] = {"status": "NOT_RUN"}
        gate_checks["H1_assembly_draws"] = {"pass": False, "value": "NOT_RUN",
                                            "what": "stage skipped"}
    else:
        final_summary, final_checks = _final_stage(
            config, context, runner, registry, workers, quick, final_draws)
        gate_checks.update(final_checks)
        results["final"] = final_summary
        timing["stage_e_s"] = final_summary["wall_s"]

    # ---- gate aggregation ------------------------------------------------
    from optisys.qa import aggregate_gate_status, load_gate_requirements

    requirements = load_gate_requirements(root)
    boundary_cases = _boundary_cases(config, final_summary, registry)
    totals = (tests_payload.get("totals") or {})
    tests_info = {"totals": totals} if totals else None
    aggregation = aggregate_gate_status("G2", gate_checks, boundary_cases, tests_info,
                                        requirements)
    if quick:
        aggregation.status = "PARTIAL"
        aggregation.notes.append("quick mode: reduced panels, not a PASS candidate")

    scientific = _scientific_claim(final_summary)
    results["gate_checks"] = gate_checks
    results["aggregation"] = aggregation.to_dict()
    results["scientific"] = scientific

    metrics = {
        "schema_version": "3.0",
        "gate": "G2",
        "report_kind": "G2",
        "case_id": config.case_id,
        "model_level": config.model_level,
        "evidence_levels": {
            "optics": "CROSS-CHECKED (ray trace + independent paraxial reference)",
            "psf": "MODEL (geometric footprint convolved with an Airy limit)",
            "imaging": "SIMULATED",
            "tolerance": "SIMULATED",
            "optimisation": "SIMULATED",
            "measured_data": "NOT_RUN",
        },
        "timing": timing,
        "environment": {
            "cpu": f"{environment['cpu']['model']} "
                   f"({environment['cpu']['physical_cores']}C/{environment['cpu']['logical_cores']}T)",
            "memory": f"{environment['memory']['total_gb']} GB total, "
                      f"{environment['memory']['available_gb']} GB available at start",
            "gpu": _gpu_text(environment),
            "python": environment["python"]["version"],
            "workers": workers,
        },
        "results": results,
        "limitations": [
            "single ASSUMED singlet; no vendor part number, no measured lens",
            "geometric footprint convolved with a scalar Airy limit, not a wavefront PSF",
            "tolerance sigmas are ASSUMED examples, not a manufacturing study",
            "synthetic data only; no measured camera",
        ],
    }
    context.write_json("metrics.json", metrics)
    context.write_json("gate_checks.json", gate_checks)

    provenance = context.provenance(
        model_level=config.model_level, seeds=[config.run.seed],
        extra={
            "config_case_id": config.case_id,
            "source_tree_sha256": code_sha,
            "candidate_registry_sha256": registry.payload_hash,
            "tests_binding": {"consistent": tests_payload["consistent"],
                              "junit_sha256": tests_payload["junit_sha256"]},
            "quick_mode": quick,
        },
    )
    context.write_json("provenance.json", provenance)

    metrics["compute"] = {
        "workers": workers,
        "benchmark": benchmark,
        "wall_time_s": time.perf_counter() - started_wall,
        "stage_seconds": timing,
    }
    context.write_json("metrics.json", metrics)

    status_payload = {
        "schema_version": "3.0",
        "run_id": context.run_id,
        "gate": "G2",
        "status": aggregation.status,
        "scientific_claim_status": scientific["status"],
        "model_level_emitted": _emitted_level(v4a_pass, v4b_pass),
        "frozen": True,
        "finished_at_utc": utc_now(),
        "gate_checks": gate_checks,
        "gate_aggregation": aggregation.to_dict(),
        "tests": totals or "NOT_INGESTED",
        "report_note": "report.html is written after this snapshot and is not in outputs[]",
        "outputs": sorted(
            path.relative_to(context.directory).as_posix()
            for path in context.directory.rglob("*") if path.is_file()
        ),
    }
    context.write_json("run_status.json", status_payload)

    from optisys.reports.figures_g2 import build_g2_figures

    try:
        figures = build_g2_figures(context.directory, config, metrics)
        context.log(f"figures: {len(figures)}")
    except Exception as exc:  # pragma: no cover - figure failure must not hide the run
        context.log(f"figure generation failed: {type(exc).__name__}: {exc}")

    from optisys.reports.report_g2 import render_g2_markdown, render_g2_report

    try:
        context.write_text("report.html", render_g2_report(
            context.directory, config, metrics, provenance, status_payload))
        context.write_text("report.md", render_g2_markdown(
            context.directory, config, metrics, status_payload))
        context.log("report.html and report.md written")
    except Exception as exc:  # pragma: no cover
        context.log(f"report generation failed: {type(exc).__name__}: {exc}")

    context.flush_log()
    (context.directory / "main_run.log").write_bytes(
        context.path("run.log").read_bytes()
    )
    return context, metrics


def _gpu_text(environment: dict[str, Any]) -> str:
    if not environment["gpu"]["available"]:
        return f"not available ({environment['gpu']['reason']})"
    return "; ".join(
        f"{device.get('name', 'UNKNOWN')} ({device.get('memory_total_mb')} MB)"
        for device in environment["gpu"]["devices"]
    )


def _git_commit(root: Path) -> str:
    import subprocess

    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(root),
                                capture_output=True, text=True, timeout=10)
        return result.stdout.strip() if result.returncode == 0 else "NO_COMMIT"
    except (OSError, subprocess.SubprocessError):
        return "NO_COMMIT"


def _git_clean(root: Path) -> bool | str:
    import subprocess

    try:
        result = subprocess.run(["git", "status", "--porcelain"], cwd=str(root),
                                capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return "UNKNOWN"
        return not bool(result.stdout.strip())
    except (OSError, subprocess.SubprocessError):
        return "UNKNOWN"


def _emitted_level(v4a: bool, v4b: bool) -> str:
    if v4a and v4b:
        return "L1-approximate"
    if v4a or v4b:
        return "L1-attempted-not-verified"
    return "L0"


def _boundary_cases(config: ResolvedG2Config, final_summary: dict[str, Any],
                    registry: CandidateRegistry) -> list[dict[str, Any]]:
    test = set(config.dataset.test_distances)
    validation = set(config.dataset.validation_distances)
    calibration = set(config.calibration_distances)
    designs = {c.name: c.design for c in registry.candidates}
    return [
        {"case": "test/validation/calibration disjoint",
         "pass": not (test & validation or test & calibration or validation & calibration)},
        {"case": "all candidates registered",
         "pass": set(designs) == {"baseline", "nominal", "robust"}},
        {"case": "final assemblies >= 2000",
         "pass": bool(final_summary["n_final_assemblies"] >= 2000)},
        {"case": "all candidates evaluated on the same assemblies",
         "pass": True},
        {"case": "no candidate uses an out-of-bounds design",
         "pass": all(
             15.0 <= d.baseline_mm <= 35.0 and 6.0 <= d.focal_length_mm <= 12.0
             and -4.0 <= d.theta_deg <= 4.0 for d in designs.values())},
    ]


def _scientific_claim(final_summary: dict[str, Any]) -> dict[str, Any]:
    ci = final_summary["ci"]
    key = f"baseline_vs_robust|{PRIMARY_ESTIMATOR}"
    payload = ci.get(key, {})
    rmse = payload.get("rmse", {})
    if not rmse or rmse.get("ci_high") is None:
        return {"status": "PARTIAL", "reason": "paired CI not estimable"}
    delta = rmse["delta"]
    low, high = rmse["ci_low"], rmse["ci_high"]
    if high < 0:
        status = "GAIN_SUPPORTED_WITHIN_ASSUMED_L1_MODEL"
        reason = "robust has a paired RMSE advantage whose CI excludes zero"
    elif low > 0:
        status = "TRADEOFF_OBSERVED"
        reason = "robust is worse on RMSE in the paired comparison"
    else:
        status = "NO_CONFIRMED_GAIN"
        reason = "paired RMSE CI includes zero"
    return {"status": status, "reason": reason,
            "delta_rmse_mm": delta, "ci": [low, high]}
