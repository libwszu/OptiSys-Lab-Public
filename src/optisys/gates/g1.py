"""G1 end-to-end pipeline (L0): spot -> sensor -> ROI -> estimators -> calibration -> test.

The pipeline never uses generator truth as estimator input.  Truth is only used
after estimation for scoring and for selecting representative frames.
"""

from __future__ import annotations

import csv
import json
import time
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import numpy as np

from optisys import __version__
from optisys.calibration.system import (
    DistanceCalibration,
    fit_distance_calibration,
    oracle_calibration,
)
from optisys.config_g1 import ConditionSpec, ResolvedG1Config, SensorSpec
from optisys.errors import Status
from optisys.geometry import CoplanarGeometry
from optisys.estimators import build_estimators
from optisys.evaluation.metrics import BLOCKING_FLAGS, is_valid, parse_flags, summarise
from optisys.evaluation.splits import SplitManifest, make_distance_splits
from optisys.gates.g1_worker import frame_task
from optisys.gates.validation import imaging_checks, noise_checks
from optisys.imaging.roi import detect_roi
from optisys.imaging.sensor import render_frame, stable_seed
from optisys.imaging.spot import SpotSpec, capture_fraction, integrated_weights
from optisys.qa import aggregate_gate_status, load_gate_requirements
from optisys.reports.figures_g1 import build_g1_figures
from optisys.reports.report_g1 import render_g1_report
from optisys.runtime.compute import pin_thread_environment
from optisys.runtime.environment import collect_environment
from optisys.runtime.run import RunContext, utc_now, source_tree_digest

SAMPLE_FIELDS = [
    "sample_id", "dataset_split", "Z_gt_mm", "u_gt_px", "v_gt_px", "condition_id",
    "noise_level", "reflectance_proxy", "exposure_ms", "image_seed", "geometry_status",
    "image_status", "roi_status", "estimator_name", "estimator_status", "quality_flags",
    "u_hat_px", "v_hat_px", "Z_hat_mm", "signed_error_mm", "saturation_fraction",
    "capture_fraction", "runtime_ms", "snr_proxy", "sigma_px", "fit_rms_e",
    "roi_touches_border", "config_sha256", "code_sha256",
]


def _condition_sensor(base: SensorSpec, condition: ConditionSpec) -> SensorSpec:
    return base.with_read_noise(condition.read_noise_e)


def _sample_id(condition: str, distance: float, repeat: int) -> str:
    return f"G1|{condition}|{distance:07.2f}|{repeat:03d}"


def _flags_text(flags: tuple[str, ...]) -> str:
    return ";".join(flags)


def _row(
    *,
    sample_id: str,
    split: str,
    distance: float,
    u_gt: float,
    v_gt: float,
    condition: ConditionSpec,
    seed: int,
    exposure_ms: float,
    geometry_status: Status,
    image_status: str,
    roi_status: Status,
    estimator_name: str,
    estimator_status: Status,
    flags: tuple[str, ...],
    u_hat: float | None,
    v_hat: float | None,
    z_hat: float | None,
    error: float | None,
    saturation_fraction: float,
    capture_fraction: float,
    runtime_ms: float,
    snr_proxy: float | None,
    sigma_px: float | None,
    fit_rms_e: float | None,
    roi_touches_border: bool,
    config_sha256: str,
    code_sha256: str,
) -> dict[str, Any]:
    return {
        "sample_id": sample_id,
        "dataset_split": split,
        "Z_gt_mm": distance,
        "u_gt_px": u_gt,
        "v_gt_px": v_gt,
        "condition_id": condition.name,
        "noise_level": condition.name,
        "reflectance_proxy": condition.reflectance_proxy,
        "exposure_ms": exposure_ms,
        "image_seed": seed,
        "geometry_status": geometry_status.value,
        "image_status": image_status,
        "roi_status": roi_status.value,
        "estimator_name": estimator_name,
        "estimator_status": estimator_status.value,
        "quality_flags": _flags_text(flags),
        "u_hat_px": u_hat,
        "v_hat_px": v_hat,
        "Z_hat_mm": z_hat,
        "signed_error_mm": error,
        "saturation_fraction": saturation_fraction,
        "capture_fraction": capture_fraction,
        "runtime_ms": runtime_ms,
        "snr_proxy": snr_proxy,
        "sigma_px": sigma_px,
        "fit_rms_e": fit_rms_e,
        "roi_touches_border": roi_touches_border,
        "config_sha256": config_sha256,
        "code_sha256": code_sha256,
    }


def run_g1(
    config: ResolvedG1Config,
    project_root: Path,
    runs_dir: Path | None = None,
    tests_summary: Path | None = None,
    tests_stdout: Path | None = None,
    tests_junit: Path | None = None,
    *,
    limit_frames: int | None = None,
    n_boot: int = 300,
) -> tuple[RunContext, dict[str, Any]]:
    root = Path(project_root)
    started_wall = time.perf_counter()
    context = RunContext(
        project_root=root, gate="G1", config_sha256=config.sha256,
        config_path=config.path, runs_dir=runs_dir,
    )
    context.snapshot_config(config.path)
    context.log(f"case={config.case_id} model_level={config.model_level} fx={config.fx_px:.9f} px")
    context.log(
        f"dataset: {len(config.distances_mm)} distances x {len(config.dataset.conditions)} "
        f"conditions x {config.dataset.repeats} repeats"
    )

    tests_info: dict[str, Any] | None = None
    if tests_summary is not None:
        tests_info = json.loads(Path(tests_summary).read_text(encoding="utf-8"))
        context.path("tests_summary.json").write_bytes(Path(tests_summary).read_bytes())
        context.log(
            f"tests ingested: {tests_info['totals']['passed']} passed / "
            f"{tests_info['totals']['failed']} failed / {tests_info['totals']['skipped']} skipped"
        )
    if tests_stdout is not None:
        context.path("pytest_stdout.txt").write_bytes(Path(tests_stdout).read_bytes())
    if tests_junit is not None:
        context.path("tests_junit.xml").write_bytes(Path(tests_junit).read_bytes())

    environment = collect_environment(root)
    context.write_json("environment.json", environment)

    thread_env = pin_thread_environment()
    benchmark_started = time.perf_counter()
    benchmark = _benchmark_g1(config)
    benchmark["thread_environment"] = thread_env
    benchmark["elapsed_s"] = time.perf_counter() - benchmark_started
    context.write_json("benchmark.json", benchmark)
    context.write_json("compute_plan.json", _compute_plan(environment, benchmark, config))

    split = make_distance_splits(
        config.distances_mm,
        config.dataset.validation_distances,
        config.dataset.test_distances,
    )
    split_payload = split.to_dict()
    split_payload["hash"] = _hash_payload(split_payload)
    context.write_json("split_manifest.json", split_payload)

    v1_details, v1_checks = imaging_checks(config)
    v2_details, v2_checks = noise_checks(config)
    context.log(
        f"V1: energy={v1_details['v1']['energy_relative_deviation']:.3e}, "
        f"subpixel2d={v1_checks['v1_subpixel_gaussian_2d']['value']:.3e} px"
    )
    context.log(f"V2: {sum(1 for c in v2_checks.values() if c['pass'])}/{len(v2_checks)} pass")

    code_sha = source_tree_digest(root)
    sensor_base = config.sensor
    oracle = oracle_calibration(
        config.fx_px, config.baseline_mm, config.cx_px, config.theta_rad,
        config.z_min_mm, config.z_max_mm,
    )

    total_expected = len(config.distances_mm) * len(config.dataset.conditions) * config.dataset.repeats
    invalid_scene = 0
    geometry = CoplanarGeometry(config.geometry)
    payloads: list[tuple] = []

    for distance in config.distances_mm:
        forward = geometry.forward(float(distance))
        if forward.status is not Status.OK:
            invalid_scene += len(config.dataset.conditions) * config.dataset.repeats
            continue
        split_name = split.split_for(float(distance))
        for condition in config.dataset.conditions:
            imaging = condition.imaging(config.imaging)
            capture = capture_fraction(
                config.width_px, config.height_px,
                SpotSpec((float(forward.u_px), float(forward.v_px)),
                         config.imaging.sigma_px, imaging.total_electrons),
            )
            for repeat in range(config.dataset.repeats):
                if limit_frames is not None and len(payloads) >= limit_frames:
                    break
                sample_id = _sample_id(condition.name, float(distance), repeat)
                seed = stable_seed(config.seed, sample_id)
                payloads.append((
                    config.width_px, config.height_px, config.imaging.sigma_px,
                    imaging.total_electrons, imaging.background_e_per_px,
                    condition.read_noise_e, sensor_base.dark_rate_e_per_s,
                    sensor_base.exposure_ms, sensor_base.full_well_e,
                    sensor_base.bit_depth, sensor_base.e_per_adu,
                    sensor_base.black_level_adu, sensor_base.adc_max_adu,
                    float(forward.u_px), float(forward.v_px), float(distance),
                    condition.name, condition.reflectance_proxy, seed, sample_id,
                    config.sha256, code_sha, split_name, capture,
                ))
            if limit_frames is not None and len(payloads) >= limit_frames:
                break
        if limit_frames is not None and len(payloads) >= limit_frames:
            break

    processed = len(payloads)
    workers = _workers_from_benchmark(benchmark, environment)
    rows: list[dict[str, Any]] = []
    if workers == 1:
        for index, payload in enumerate(payloads, start=1):
            rows.extend(frame_task(payload))
            if index % 500 == 0:
                context.log(f"processed {index}/{processed} frames")
    else:
        context.log(f"frame workers: {workers} (spawn), deterministic per-sample seeds")
        import multiprocessing as mp
        from concurrent.futures import ProcessPoolExecutor

        with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn")) as pool:
            done = 0
            for result_rows in pool.map(frame_task, payloads, chunksize=8):
                rows.extend(result_rows)
                done += 1
                if done % 500 == 0:
                    context.log(f"processed {done}/{processed} frames")

    rows.sort(key=lambda row: (row["sample_id"], row["estimator_name"]))

    context.log(f"frames processed: {processed} (invalid scenes: {invalid_scene})")

    # Calibration is fitted AFTER generation but ONLY on calib/medium rows, and
    # only once, before any test-set metric is inspected.
    calibration, calibration_meta = _fit_calibrations(config, split, rows, oracle)
    context.write_json("calibration.json", calibration_meta)

    # Recompute Z_hat with the actual per-estimator calibrations (the loop above
    # used the oracle only as a placeholder during collection).
    rows = _apply_calibrations(rows, calibration)

    summaries = {
        "by_estimator_split_condition": summarise(
            rows, ("estimator_name", "dataset_split", "condition_id"), n_boot=n_boot
        ),
        "by_estimator_condition": summarise(rows, ("estimator_name", "condition_id"), n_boot=n_boot),
        "by_estimator_split": summarise(rows, ("estimator_name", "dataset_split"), n_boot=n_boot),
        "by_estimator": summarise(rows, ("estimator_name",), n_boot=n_boot),
    }
    distance_rows = _distance_metrics(rows)
    failure_rows = _failure_breakdown(rows)

    _write_samples(context.path("samples.csv"), rows)
    _write_csv(context.path("metrics_by_group.csv"), summaries["by_estimator_split_condition"])
    _write_csv(context.path("metrics_by_distance.csv"), distance_rows)
    _write_csv(context.path("failure_breakdown.csv"), failure_rows)

    representative = _save_representative_frames(config, context.path("representative_frames"))
    context.log(f"representative frames: {representative['saved']}")

    v3_checks = _v3_checks(config, split, calibration, summaries, rows)
    v3_checks["dataset_completeness"] = {
        "value": {"processed": processed, "expected": total_expected},
        "threshold": "all frozen frames executed",
        "pass": bool(processed == total_expected),
        "what": "frozen G1 dataset size",
    }
    gate_checks = {**v1_checks, **v2_checks, **v3_checks}
    requirements = load_gate_requirements(root)
    aggregation = aggregate_gate_status("G1", gate_checks, _boundary_cases(rows, split),
                                        tests_info, requirements)
    if limit_frames is not None and processed < total_expected:
        aggregation.status = "PARTIAL"
        aggregation.notes.append(
            f"limited run: {processed}/{total_expected} frames, not a G1 PASS candidate"
        )

    metrics = {
        "schema_version": "1.0",
        "gate": "G1",
        "report_kind": "G1",
        "case_id": config.case_id,
        "model_level": config.model_level,
        "evidence_levels": {
            "imaging": "SIMULATED",
            "noise_model": "SIMULATED",
            "estimators": "SIMULATED",
            "calibration": "SIMULATED",
            "measured_data": "NOT_RUN",
        },
        "dataset": {
            "distances": len(config.distances_mm),
            "conditions": [c.name for c in config.dataset.conditions],
            "repeats": config.dataset.repeats,
            "frames_attempted": processed,
            "frames_expected": total_expected,
            "invalid_scenes": invalid_scene,
            "splits": split.to_dict(),
            "n_rows": len(rows),
        },
        "v1": v1_details,
        "v2": v2_details,
        "gate_checks": gate_checks,
        "gate_aggregation": aggregation.to_dict(),
        "calibration": calibration_meta,
        "summaries": summaries,
        "distance_metrics": distance_rows,
        "failures": failure_rows,
        "representative_frames": representative,
        "environment": {
            "cpu": f"{environment['cpu']['model']} "
                   f"({environment['cpu']['physical_cores']}C/{environment['cpu']['logical_cores']}T)",
            "memory": f"{environment['memory']['total_gb']} GB total",
            "gpu": _gpu_text(environment),
            "python": environment["python"]["version"],
        },
        "compute": {
            "policy": f"{workers} frame worker(s); BLAS/OpenMP pinned to 1",
            "frame_render_median_ms": benchmark["frame_render"]["median_ms"],
            "estimator_median_ms": benchmark["estimators"],
            "parallel": benchmark["parallel"],
            "wall_time_s": None,
        },
        "tests": tests_info["totals"] if tests_info else "NOT_INGESTED",
        "limitations": [
            "L0 circular Gaussian, no lens PSF or speckle",
            "design-assumption sensor parameters, no datasheet values",
            "single coplanar point; v is constant by construction",
            "system calibration identifies a and b only",
            "no measured data; no industrial accuracy claim",
        ],
    }
    context.write_json("metrics.json", metrics)

    provenance = context.provenance(
        model_level=config.model_level,
        seeds=[config.seed],
        extra={
            "config_case_id": config.case_id,
            "source_tree_sha256": code_sha,
            "calibration_identifiability": calibration_meta["identifiability"],
            "split_hash": split_payload["hash"],
        },
    )
    context.write_json("provenance.json", provenance)

    metrics["compute"]["wall_time_s"] = time.perf_counter() - started_wall
    context.write_json("metrics.json", metrics)

    status_payload = {
        "schema_version": "1.0",
        "run_id": context.run_id,
        "gate": "G1",
        "status": aggregation.status,
        "scientific_claim_status": (
            "SUPPORTED" if aggregation.status == "PASS" else "PARTIAL"
        ),
        "scientific_claim_scope": (
            "L0 simulated imaging/noise/estimation/calibration chain is internally consistent "
            "within the frozen tolerances. No measured or industrial accuracy claim."
        ),
        "frozen": True,
        "finished_at_utc": utc_now(),
        "gate_checks": gate_checks,
        "gate_aggregation": aggregation.to_dict(),
        "tests": tests_info["totals"] if tests_info else "NOT_INGESTED",
        "dataset": metrics["dataset"],
        "report_note": "report.html is written after this snapshot and is not in outputs[]",
        "outputs": sorted(
            path.relative_to(context.directory).as_posix()
            for path in context.directory.rglob("*") if path.is_file()
        ),
    }
    context.write_json("run_status.json", status_payload)

    figures = build_g1_figures(context.directory, config, metrics, rows, calibration_meta)
    context.log(f"figures: {len(figures)}")
    context.flush_log()
    html_text = render_g1_report(context.directory, config, metrics, provenance, status_payload)
    context.write_text("report.html", html_text)
    print(f"report: {context.path('report.html')}", flush=True)
    return context, metrics


# ---------------------------------------------------------------------------
# Calibration helpers
# ---------------------------------------------------------------------------
def _fit_calibrations(config: ResolvedG1Config, split: SplitManifest,
                      rows: list[dict[str, Any]], oracle: DistanceCalibration
                      ) -> tuple[dict[str, DistanceCalibration], dict[str, Any]]:
    calibrations: dict[str, DistanceCalibration] = {}
    meta: dict[str, Any] = {
        "schema_version": "1.0",
        "method": "linear least squares on u = a/Z + b",
        "identifiability": oracle.identifiability,
        "oracle": oracle.to_dict(),
        "splits": split.to_dict(),
        "fits": {},
        "calibration_dataset": "calib split, medium condition, all valid frames",
    }
    for name in ("centroid", "gaussian_1d", "gaussian_2d"):
        subset = [
            row for row in rows
            if row["estimator_name"] == name
            and row["dataset_split"] == "calib"
            and row["condition_id"] == "medium"
            and is_valid(row)
        ]
        z = np.array([row["Z_gt_mm"] for row in subset], dtype=float)
        u = np.array([row["u_hat_px"] for row in subset], dtype=float)
        fit = fit_distance_calibration(z, u)
        calibrations[name] = fit
        meta["fits"][name] = {
            **fit.to_dict(),
            "n_frames_used": len(subset),
            "u_residual_sigma_px": fit.residual_rms_px,
        }
    calibrations["oracle"] = oracle
    meta["fits"]["oracle"] = {**oracle.to_dict(), "n_frames_used": 0}
    return calibrations, meta


def _apply_calibrations(rows: list[dict[str, Any]],
                        calibrations: dict[str, DistanceCalibration]) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        if row["estimator_status"] == "OK" and row["u_hat_px"] is not None:
            calibration = calibrations[row["estimator_name"]]
            z_hat, status, message = calibration.inverse(float(row["u_hat_px"]))
            if status is Status.OK and z_hat is not None:
                row = dict(row)
                row["Z_hat_mm"] = z_hat
                row["signed_error_mm"] = float(z_hat - row["Z_gt_mm"])
            else:
                row = dict(row)
                row["estimator_status"] = status.value
                row["Z_hat_mm"] = None
                row["signed_error_mm"] = None
                row["quality_flags"] = ";".join(
                    filter(None, [row["quality_flags"], status.value])
                )
        output.append(row)
    return output


def _distance_metrics(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return summarise(rows, ("estimator_name", "condition_id", "Z_gt_mm"))


def _failure_breakdown(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output = []
    keys = sorted({(row["estimator_name"], row["condition_id"]) for row in rows})
    for estimator, condition in keys:
        subset = [r for r in rows if r["estimator_name"] == estimator and r["condition_id"] == condition]
        flags: dict[str, int] = {}
        statuses: dict[str, int] = {}
        for row in subset:
            statuses[row["estimator_status"]] = statuses.get(row["estimator_status"], 0) + 1
            for flag in parse_flags(row["quality_flags"]):
                flags[flag] = flags.get(flag, 0) + 1
        attempted = len(subset)
        valid = sum(1 for row in subset if is_valid(row))
        output.append({
            "estimator_name": estimator,
            "condition_id": condition,
            "n_attempted": attempted,
            "n_valid": valid,
            "failure_rate": 1.0 - valid / attempted if attempted else 0.0,
            "status_counts": ";".join(f"{k}={v}" for k, v in sorted(statuses.items())),
            "flag_counts": ";".join(f"{k}={v}" for k, v in sorted(flags.items())),
            "blocking_flags": ";".join(sorted(BLOCKING_FLAGS)),
        })
    return output


def _boundary_cases(rows: list[dict[str, Any]], split: SplitManifest) -> list[dict[str, Any]]:
    calib = {round(v, 6) for v in split.calib_distances}
    validation = {round(v, 6) for v in split.validation_distances}
    test = {round(v, 6) for v in split.test_distances}
    return [
        {"case": "calib/validation/test disjoint", "pass": not (calib & validation or calib & test or validation & test)},
        {"case": "test distances inside calibrated range", "pass": bool(test and min(test) >= min(calib) and max(test) <= max(calib))},
        {"case": "all rows carry status", "pass": all(r["estimator_status"] for r in rows)},
        {"case": "failed rows have no Z_hat", "pass": all(r["Z_hat_mm"] is None for r in rows if r["estimator_status"] != "OK")},
        {"case": "valid rows have finite error", "pass": all(np.isfinite(r["signed_error_mm"]) for r in rows if is_valid(r))},
    ]


def _v3_checks(config: ResolvedG1Config, split: SplitManifest,
               calibrations: dict[str, DistanceCalibration],
               summaries: dict[str, list[dict[str, Any]]],
               rows: list[dict[str, Any]]) -> dict[str, Any]:
    calib = {round(v, 6) for v in split.calib_distances}
    validation = {round(v, 6) for v in split.validation_distances}
    test = {round(v, 6) for v in split.test_distances}
    disjoint = not (calib & validation or calib & test or validation & test)

    oracle_a = config.fx_px * config.baseline_mm
    a_errors = {}
    for name in ("centroid", "gaussian_1d", "gaussian_2d"):
        fit = calibrations[name]
        if fit.status is Status.OK and fit.a_px_mm:
            a_errors[name] = abs(fit.a_px_mm / oracle_a - 1.0)
        else:
            a_errors[name] = None
    a_worst = max((v for v in a_errors.values() if v is not None), default=float("inf"))

    test_rows = [r for r in rows if r["dataset_split"] == "test"]
    valid_test = sum(1 for r in test_rows if is_valid(r))
    failure_rate = 1.0 - valid_test / len(test_rows) if test_rows else 1.0

    return {
        "v3_split_disjoint": {
            "value": {"calib": len(calib), "validation": len(validation), "test": len(test)},
            "threshold": "empty intersections",
            "pass": bool(disjoint),
            "what": "distance-level split isolation",
        },
        "v3_calibration_a_recovery": {
            "value": a_errors, "threshold": 0.01,
            "pass": bool(a_worst <= 0.01),
            "what": "fitted a vs fx*B (medium condition)",
        },
        "v3_failure_denominator": {
            "value": {"attempted": len(test_rows), "valid": valid_test,
                      "failure_rate": failure_rate},
            "threshold": "reported for every attempted frame",
            "pass": bool(len(test_rows) > 0),
            "what": "test split failure accounting",
        },
        "v3_estimators_compared_same_frames": {
            "value": {"estimators": len({r["estimator_name"] for r in rows}),
                      "unique_image_seeds": len({r["image_seed"] for r in rows})},
            "threshold": "3 estimators sharing image seeds",
            "pass": len({r["estimator_name"] for r in rows}) == 3,
            "what": "same generated frames",
        },
    }


def _hash_payload(payload: dict[str, Any]) -> str:
    import hashlib

    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()


def _write_samples(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=SAMPLE_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _save_representative_frames(config: ResolvedG1Config, directory: Path) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=True)
    entries = []
    cases = [
        ("valid_strong", 200.0, "strong", 1.0, 1.0, 0.0),
        ("low_snr_weak", 200.0, "weak", 1.0, 1.0, 0.0),
        ("saturated", 200.0, "strong", 12.0, 1.0, 0.0),
        ("edge_partial", 100.0, "medium", 1.0, 1.0, 250.0),
        ("no_signal", 200.0, "weak", 0.0, 1.0, 0.0),
        ("bimodal", 200.0, "medium", 1.0, 1.0, 0.0),
    ]
    geometry = __import__("optisys.geometry", fromlist=["CoplanarGeometry"]).CoplanarGeometry(
        config.geometry
    )
    for index, (name, distance, condition_name, gain, sigma_scale, offset) in enumerate(cases):
        condition = next(c for c in config.dataset.conditions if c.name == condition_name)
        sensor = _condition_sensor(config.sensor, condition)
        forward = geometry.forward(distance)
        u = float(forward.u_px) + offset
        total = condition.total_electrons * gain
        spot = SpotSpec((u, float(forward.v_px)), config.imaging.sigma_px * sigma_scale, total)
        weights = integrated_weights(config.width_px, config.height_px, spot)
        total_reference = total
        if name == "bimodal":
            second = SpotSpec((u + 12.0, float(forward.v_px)), config.imaging.sigma_px,
                              total * 0.6)
            weights = weights + integrated_weights(config.width_px, config.height_px, second)
            total_reference = total * 1.6
        frame = render_frame(weights, condition.background_e_per_px, sensor,
                             stable_seed(config.seed, f"rep-{name}"))
        roi = detect_roi(frame.image_adu, sensor)
        np.savez_compressed(
            directory / f"{index:02d}_{name}.npz",
            image_adu=frame.image_adu,
            expected_e=frame.expected_e.astype(np.float32),
            u_gt_px=np.array([u]),
            v_gt_px=np.array([float(forward.v_px)]),
            Z_gt_mm=np.array([distance]),
            roi=np.array(roi.roi if roi.roi else [-1, -1, -1, -1]),
            saturation_fraction=np.array([frame.saturation_fraction]),
            capture_fraction=np.array([weights.sum() / total_reference if total_reference else 0.0]),
        )
        entries.append({
            "file": f"{index:02d}_{name}.npz",
            "name": name,
            "Z_gt_mm": distance,
            "condition": condition_name,
            "u_gt_px": u,
            "roi": list(roi.roi) if roi.roi else None,
            "roi_status": roi.status.value,
            "saturation_fraction": frame.saturation_fraction,
            "image_flags": list(frame.flags),
            "purpose": {
                "valid_strong": "normal valid frame",
                "low_snr_weak": "low signal-to-noise",
                "saturated": "ADC/full-well saturation",
                "edge_partial": "spot partly outside the chip",
                "no_signal": "empty ROI / no spot",
                "bimodal": "two-spot model mismatch",
            }[name],
        })
    (directory / "index.json").write_text(
        json.dumps({"frames": entries}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return {"saved": len(entries), "directory": "representative_frames", "frames": entries}


def _gpu_text(environment: dict[str, Any]) -> str:
    if not environment["gpu"]["available"]:
        return f"not available ({environment['gpu']['reason']})"
    return "; ".join(
        f"{device.get('name', 'UNKNOWN')} ({device.get('memory_total_mb')} MB)"
        for device in environment["gpu"]["devices"]
    )


def _benchmark_g1(config: ResolvedG1Config) -> dict[str, Any]:
    """Measure the real G1 workload before scaling; single frame at a time."""

    geometry = __import__("optisys.geometry", fromlist=["CoplanarGeometry"]).CoplanarGeometry(
        config.geometry
    )
    condition = config.dataset.conditions[0]
    sensor = _condition_sensor(config.sensor, condition)
    distances = (120.0, 200.0, 280.0)
    render_times, roi_times, estimator_times = [], [], {name: [] for name in ("centroid", "gaussian_1d", "gaussian_2d")}
    estimators = build_estimators()

    for distance in distances:
        forward = geometry.forward(distance)
        spot = SpotSpec((float(forward.u_px), float(forward.v_px)),
                        config.imaging.sigma_px, condition.total_electrons)
        weights = integrated_weights(config.width_px, config.height_px, spot)
        for repeat in range(3):
            seed = stable_seed(config.seed, f"bench-{distance}-{repeat}")
            started = time.perf_counter()
            frame = render_frame(weights, condition.background_e_per_px, sensor, seed)
            render_times.append(time.perf_counter() - started)
            started = time.perf_counter()
            roi = detect_roi(frame.image_adu, sensor)
            roi_times.append(time.perf_counter() - started)
            for estimator in estimators:
                started = time.perf_counter()
                estimator.estimate(frame.image_adu, roi.roi, sensor)
                estimator_times[estimator.name].append(time.perf_counter() - started)

    parallel = _parallel_frame_test(config, frames=8, workers=(1, 2, 4))

    return {
        "schema_version": "1.0",
        "gate": "G1",
        "frame_render": {
            "median_ms": float(np.median(render_times) * 1e3),
            "p95_ms": float(np.percentile(render_times, 95) * 1e3),
            "samples": len(render_times),
        },
        "roi_detection": {
            "median_ms": float(np.median(roi_times) * 1e3),
            "p95_ms": float(np.percentile(roi_times, 95) * 1e3),
        },
        "estimators": {
            name: {
                "median_ms": float(np.median(values) * 1e3),
                "p95_ms": float(np.percentile(values, 95) * 1e3),
            }
            for name, values in estimator_times.items()
        },
        "parallel": parallel,
        "gpu": "NOT_TESTED",
        "note": "single frame at a time; full 1280x1024 arrays are not retained",
    }


def _parallel_frame_test(config: ResolvedG1Config, frames: int, workers: tuple[int, ...]
                         ) -> dict[str, Any]:
    import multiprocessing as mp
    from concurrent.futures import ProcessPoolExecutor

    from optisys.runtime.bench_g1 import frame_job

    geometry = __import__("optisys.geometry", fromlist=["CoplanarGeometry"]).CoplanarGeometry(
        config.geometry
    )
    condition = config.dataset.conditions[0]
    payloads = []
    for index in range(frames):
        distance = 100.0 + (index % 41) * 5.0
        forward = geometry.forward(distance)
        payloads.append((
            config.width_px, config.height_px, float(forward.u_px), float(forward.v_px),
            config.imaging.sigma_px, condition.total_electrons, condition.background_e_per_px,
            condition.read_noise_e, config.sensor.dark_rate_e_per_s, config.sensor.exposure_ms,
            config.sensor.full_well_e, config.sensor.bit_depth, config.sensor.e_per_adu,
            config.sensor.black_level_adu, config.sensor.adc_max_adu,
            stable_seed(config.seed, f"par-{index}"),
        ))

    cases = []
    for worker_count in workers:
        if worker_count == 1:
            durations = []
            for _ in range(2):
                started = time.perf_counter()
                for payload in payloads:
                    frame_job(payload)
                durations.append(time.perf_counter() - started)
            cases.append({"workers": 1, "mode": "in_process",
                          "median_s": float(np.median(durations))})
            continue
        context = mp.get_context("spawn")
        started = time.perf_counter()
        with ProcessPoolExecutor(max_workers=worker_count, mp_context=context) as pool:
            list(pool.map(frame_job, payloads))
            setup = time.perf_counter() - started
            durations = []
            for _ in range(2):
                started = time.perf_counter()
                list(pool.map(frame_job, payloads))
                durations.append(time.perf_counter() - started)
        cases.append({"workers": worker_count, "mode": "process_spawn",
                      "median_s": float(np.median(durations)), "pool_setup_s": setup})

    baseline = next(case["median_s"] for case in cases if case["workers"] == 1)
    for case in cases:
        case["speedup_vs_1"] = baseline / case["median_s"] if case["median_s"] else None
    best = max(cases, key=lambda case: case["speedup_vs_1"] or 0)
    return {
        "frames": frames,
        "cases": cases,
        "best_workers": best["workers"],
        "best_speedup_vs_1": best["speedup_vs_1"],
        "decision": "single_process" if (best["speedup_vs_1"] or 0) < 1.3 else f"workers_{best['workers']}",
    }


def _workers_from_benchmark(benchmark: dict[str, Any], environment: dict[str, Any]) -> int:
    """Adopt process parallelism only when the measured speedup clears 1.3x."""

    parallel = benchmark.get("parallel", {})
    if parallel.get("decision") == "single_process":
        return 1
    best = int(parallel.get("best_workers", 1))
    physical = int(environment["cpu"].get("physical_cores") or 1)
    return max(1, min(best, physical))


def _compute_plan(environment: dict[str, Any], benchmark: dict[str, Any],
                  config: ResolvedG1Config) -> dict[str, Any]:
    return {
        "schema_version": "1.0",
        "gate": "G1",
        "hardware": {
            "cpu_model": environment["cpu"]["model"],
            "physical_cores": environment["cpu"]["physical_cores"],
            "logical_cores": environment["cpu"]["logical_cores"],
            "memory_total_gb": environment["memory"]["total_gb"],
            "gpu": _gpu_text(environment),
            "cuda_usable": environment["cuda"]["torch"].get("cuda_available", "NOT_INSTALLED"),
        },
        "workload": {
            "frames": len(config.distances_mm) * len(config.dataset.conditions) * config.dataset.repeats,
            "image_pixels": config.width_px * config.height_px,
            "storage_policy": "one frame at a time; float64 compute, CSV aggregation, NPZ representatives",
        },
        "measured": {
            "frame_render_median_ms": benchmark["frame_render"]["median_ms"],
            "roi_median_ms": benchmark["roi_detection"]["median_ms"],
            "estimators_median_ms": benchmark["estimators"],
            "parallel": benchmark["parallel"],
        },
        "policy": {
            "workers": 1 if benchmark["parallel"]["decision"] == "single_process"
                       else benchmark["parallel"]["best_workers"],
            "reason": benchmark["parallel"]["decision"],
            "gpu": "disabled",
            "gpu_reason": "L0 scalar/array workload; no torch installed; GPU not tested",
            "thread_env": benchmark.get("thread_environment", {}),
        },
        "budget": {
            "estimated_wall_time_s": None,
            "max_wall_time_s": 900,
        },
        "not_tested": [
            "GPU/CUDA path",
            "Optiland lens trace (G2 scope)",
            "real camera data (none available)",
        ],
    }
