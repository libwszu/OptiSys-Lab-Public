"""Execute the frozen S6-C assembly pilot and paired holdout."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import multiprocessing as mp
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import psutil
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from optisys.optics.s5_reference import build_model  # noqa: E402
from optisys.optics.s6_rigid_body import (  # noqa: E402
    LensPose,
    invalid_geometry_reason,
    trace_local,
)
from optisys.sources.multimode_fiber import sample_multimode_fiber  # noqa: E402
from optisys.tolerance.s6_assembly import (  # noqa: E402
    PARAMETER_ORDER,
    SCENARIO_SCALE,
    paired_cluster_bootstrap,
    perturbation_vector,
    poses_from_perturbation,
    truncated_standard_normal_latents,
)

RUN_ID = "20261021_024715_S6_P1"
G4 = ROOT / "runs/20261020_133555_G4_ec3e2813_0e48"
S5_HOLDOUT_SEED_FORBIDDEN = 976053
TARGET_Z_MM = 225.0
TARGET_RADIUS_MM = 1.0
CORE_DIAMETER_MM = 0.105
NA = 0.22
WORKERS = 4
CHUNK_ASSEMBLIES = 32
TASK_TIMEOUT_S = 120
BOOTSTRAP_REPLICATES = 2000
TOTAL_SCIENCE_BUDGET_S = 1500.0
HOLDOUT_HARD_CAP_S = 1200.0
HOLDOUT_POSTPROCESS_RESERVE_S = 30.0
OUTCOME_CATEGORIES = (
    "CAPTURED", "OUTSIDE_TARGET", "L1_APERTURE_BLOCK", "L2_APERTURE_BLOCK",
    "TRACE_FAIL", "NO_INTERSECTION", "TIR", "INVALID_SOURCE", "INVALID_ASSEMBLY",
)

_WORKER_MODEL = None
_WORKER_BACKEND_HASH = ""
_WORKER_CONFIG_HASH = ""


def _sha_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _canonical_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")
    return _sha_bytes(raw)


def _hash_ray_bundle(bundle) -> str:
    h = hashlib.sha256()
    for array, dtype in ((bundle.ray_id, "<i8"), (bundle.origin_mm, "<f8"),
                         (bundle.direction, "<f8"), (bundle.weight, "<f8")):
        h.update(np.asarray(array, dtype=dtype).tobytes(order="C"))
    return h.hexdigest()


def _load_model():
    optics = json.loads((G4 / "optics_model.json").read_text(encoding="utf-8"))
    cfg = yaml.safe_load((ROOT / "configs/pump976_g4_l0.yaml").read_text(encoding="utf-8-sig"))
    return build_model(optics, cfg)


def _model_hashes() -> dict[str, str]:
    hashes = {
        "g4_optics_model_sha256": _sha_file(G4 / "optics_model.json"),
        "g4_baseline_config_sha256": _sha_file(ROOT / "configs/pump976_g4_l0.yaml"),
        "s6_reference_backend_sha256": _sha_file(ROOT / "src/optisys/optics/s6_rigid_body.py"),
        "s5_prescription_sha256": _sha_file(ROOT / "src/optisys/optics/s5_reference.py"),
        "fiber_sampler_sha256": _sha_file(ROOT / "src/optisys/sources/multimode_fiber.py"),
        "tolerance_sampler_sha256": _sha_file(ROOT / "src/optisys/tolerance/s6_assembly.py"),
        "assembly_runner_sha256": _sha_file(ROOT / "scripts/s6_assembly.py"),
    }
    run_dir = ROOT / "runs" / RUN_ID
    hashes.update({
        "s6_prereg_freeze_sha256": _sha_file(ROOT / "docs/s6/S6_FREEZE_HASHES.json"),
        "s6_profile_amendment_hashes_sha256": _sha_file(ROOT / "docs/s6/S6_AMENDMENT_01_HASHES.json"),
        "s6_compute_plan_sha256": _sha_file(run_dir / "compute_plan.json"),
        "s6_assumed_config_snapshot_sha256": _sha_file(run_dir / "config_snapshot.yaml"),
        "s6_a_reference_summary_sha256": _sha_file(run_dir / "s6_a_reference/s6_a_reference_summary.json"),
        "s6_preholdout_science_ledger_sha256": _sha_file(run_dir / "compute_measured_preholdout.json"),
        "s6_budget_amendment_sha256": _sha_file(ROOT / "docs/s6/S6_AMENDMENT_02.md"),
        "s6_budget_amendment_hashes_sha256": _sha_file(ROOT / "docs/s6/S6_AMENDMENT_02_HASHES.json"),
        "s6_holdout_code_freeze_sha256": _sha_file(run_dir / "S6_C_CODE_FREEZE_02.json"),
        "s6_holdout_freeze_sha256": _sha_file(run_dir / "S6_C_HOLDOUT_FREEZE_02.json"),
    })
    return hashes


def _config_hashes(mode: str, n_rays: int, n_assemblies: int, scenarios: list[dict[str, Any]],
                   seed_info: dict[str, Any]) -> tuple[str, dict[str, str]]:
    hashes = _model_hashes()
    contract = {
        "mode": mode, "wavelength_nm": 976.0, "core_diameter_mm": CORE_DIAMETER_MM,
        "NA": NA, "target_z_mm": TARGET_Z_MM, "target_radius_mm": TARGET_RADIUS_MM,
        "rays_per_design": n_rays, "assemblies_per_scenario": n_assemblies,
        "scenarios": scenarios, "seed_info": seed_info, "workers": WORKERS,
        "backend_hashes": hashes,
    }
    return _canonical_hash(contract), hashes


def _worker_init(model, backend_hash: str, config_hash: str) -> None:
    global _WORKER_MODEL, _WORKER_BACKEND_HASH, _WORKER_CONFIG_HASH
    _WORKER_MODEL = model
    _WORKER_BACKEND_HASH = backend_hash
    _WORKER_CONFIG_HASH = config_hash
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[key] = "1"


def _weighted_quantile(values: np.ndarray, weights: np.ndarray, q: float) -> float | None:
    if values.size == 0 or values.size != weights.size:
        return None
    order = np.argsort(values, kind="mergesort")
    v, w = values[order], weights[order]
    if float(np.sum(w)) <= 0.0:
        return None
    k = int(np.searchsorted(np.cumsum(w), q * float(np.sum(w)), side="left"))
    return float(v[min(k, len(v) - 1)])


def _design_metrics(design_id: str, poses: tuple[LensPose, LensPose], dz_candidate: float,
                    source, model) -> dict[str, Any]:
    applied = poses
    if dz_candidate:
        p1, p2 = poses
        applied = (p1, LensPose(dx_mm=p2.dx_mm, dy_mm=p2.dy_mm,
                                dz_mm=p2.dz_mm + dz_candidate,
                                tilt_x_deg=p2.tilt_x_deg, tilt_y_deg=p2.tilt_y_deg,
                                roll_z_deg=p2.roll_z_deg))
    geometry_reason = invalid_geometry_reason(model, applied, target_z_mm=TARGET_Z_MM)
    if geometry_reason:
        weights_by = {name: (1.0 if name == "INVALID_ASSEMBLY" else 0.0)
                      for name in OUTCOME_CATEGORIES}
        counts_by = {name: (source.n_rays if name == "INVALID_ASSEMBLY" else 0)
                     for name in OUTCOME_CATEGORIES}
        return {
            "design_id": design_id, "design_status": "INVALID_ASSEMBLY",
            "geometry_reason": geometry_reason, "assembly_valid": False,
            "source_ray_count": source.n_rays,
            "source_weight_denominator": source.total_weight,
            "captured_count": 0, "captured_weight": 0.0,
            "capture_fraction_input": 0.0,
            "plane_reacher_count": 0, "r80_all_plane_reachers_mm": None,
            "r90_all_plane_reachers_mm": None, "rms_all_plane_reachers_mm": None,
            "conditional_r90_within_1mm_mm": None,
            "terminal_counts": counts_by, "terminal_weights": weights_by,
            "ledger_status": "PASS_INVALID_ASSEMBLY_WEIGHTED_ZERO",
            "trace_wall_s": 0.0,
        }
    started = time.perf_counter()
    trace = trace_local(model, source.ray_id, source.origin_mm,
                        source.direction, source.weight, applied,
                        target_z_mm=TARGET_Z_MM, target_radius_mm=TARGET_RADIUS_MM)
    wall = time.perf_counter() - started
    all_r, all_w, inside_r, inside_w = [], [], [], []
    for row in trace.ray_rows:
        if row["target_x"] is None:
            continue
        radius = float(np.hypot(row["target_x"], row["target_y"]))
        all_r.append(radius); all_w.append(float(row["source_weight"]))
        if row["terminal_outcome"] == "CAPTURED":
            inside_r.append(radius); inside_w.append(float(row["source_weight"]))
    radii = np.asarray(all_r, dtype=float); plane_weights = np.asarray(all_w, dtype=float)
    r_inside = np.asarray(inside_r, dtype=float); w_inside = np.asarray(inside_w, dtype=float)
    rms = (float(np.sqrt(np.average(radii * radii, weights=plane_weights)))
           if radii.size else None)
    terminal_counts = {name: int(trace.ledger["terminal_count"].get(name, 0))
                       for name in OUTCOME_CATEGORIES}
    terminal_weights = {name: float(trace.ledger["terminal_weight"].get(name, 0.0))
                        for name in OUTCOME_CATEGORIES}
    return {
        "design_id": design_id, "design_status": "COMPLETE",
        "geometry_reason": "", "assembly_valid": True,
        "source_ray_count": source.n_rays,
        "source_weight_denominator": trace.ledger["source_weight_total"],
        "captured_count": int(trace.ledger["terminal_count"].get("CAPTURED", 0)),
        "captured_weight": float(trace.ledger["captured_weight"]),
        "capture_fraction_input": float(trace.ledger["capture_fraction_input"]),
        "plane_reacher_count": int(radii.size),
        "r80_all_plane_reachers_mm": _weighted_quantile(radii, plane_weights, 0.80),
        "r90_all_plane_reachers_mm": _weighted_quantile(radii, plane_weights, 0.90),
        "rms_all_plane_reachers_mm": rms,
        "conditional_r90_within_1mm_mm": _weighted_quantile(r_inside, w_inside, 0.90),
        "terminal_counts": terminal_counts, "terminal_weights": terminal_weights,
        "ledger_status": trace.ledger["status"], "trace_wall_s": wall,
    }


def _evaluate_assembly(job: dict[str, Any]) -> dict[str, Any]:
    started = time.perf_counter()
    if _WORKER_MODEL is None:
        raise RuntimeError("S6 worker was not initialized")
    source = sample_multimode_fiber(job["rays_per_design"], CORE_DIAMETER_MM, NA,
                                    seed=job["source_seed"])
    source_hash = _hash_ray_bundle(source)
    if source_hash != job["expected_source_bundle_sha256"]:
        raise RuntimeError("source bundle hash differs from precomputed deterministic input")
    vector = perturbation_vector(job["latent_z"], job["tolerance_key"])
    poses = poses_from_perturbation(vector)
    results = [
        _design_metrics("baseline125", poses, 0.0, source, _WORKER_MODEL),
        _design_metrics("s5_position135", poses, 10.0, source, _WORKER_MODEL),
    ]
    status = "COMPLETE" if all(r["ledger_status"].startswith("PASS") for r in results) else "FAILED_LEDGER"
    return {
        "assembly_id": job["assembly_id"], "scenario": job["scenario"],
        "tolerance_key": job["tolerance_key"], "latent_id": job["latent_id"],
        "latent_z": job["latent_z"], "perturbation_vector": vector,
        "source_seed": job["source_seed"], "source_bundle_sha256": source_hash,
        "config_hash": _WORKER_CONFIG_HASH, "backend_hash": _WORKER_BACKEND_HASH,
        "input_hash": job["input_hash"], "status": status,
        "design_results": results,
        "worker_wall_s": time.perf_counter() - started,
    }


class _RssSampler:
    def __init__(self):
        self._stop = __import__("threading").Event()
        self.peak_mb = 0.0
        self._thread = __import__("threading").Thread(target=self._run, daemon=True)
        self.parent = psutil.Process()

    def _run(self):
        while not self._stop.is_set():
            total = 0
            try:
                for process in [self.parent, *self.parent.children(recursive=True)]:
                    try:
                        total += process.memory_info().rss
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                self.peak_mb = max(self.peak_mb, total / (1024 * 1024))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            self._stop.wait(0.02)

    def start(self):
        self._thread.start()

    def stop(self) -> float:
        self._stop.set(); self._thread.join(timeout=2)
        return self.peak_mb


def _terminate_executor(pool: concurrent.futures.ProcessPoolExecutor) -> None:
    processes = list(getattr(pool, "_processes", {}).values())
    for proc in processes:
        try:
            if proc.is_alive(): proc.terminate()
        except Exception:
            pass
    for proc in processes:
        try:
            proc.join(timeout=2)
            if proc.is_alive(): proc.kill()
        except Exception:
            pass
    pool.shutdown(wait=False, cancel_futures=True)


def _json_write_atomic(path: Path, value: Any) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True,
                              allow_nan=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _source_hash(seed: int, n: int) -> str:
    return _hash_ray_bundle(sample_multimode_fiber(n, CORE_DIAMETER_MM, NA, seed=seed))


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty S6-C evidence CSV: {path}")
    fields: list[str] = []; seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                fields.append(key); seen.add(key)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({k: (json.dumps(v, ensure_ascii=False, sort_keys=True)
                                 if isinstance(v, (dict, list)) else v) for k, v in row.items()})


def _load_existing_checkpoints(checkpoint_dir: Path, jobs: list[dict[str, Any]],
                               config_hash: str, resume: bool) -> dict[str, dict[str, Any]]:
    if not resume:
        if checkpoint_dir.exists() and any(checkpoint_dir.iterdir()):
            raise FileExistsError("checkpoint directory is non-empty; use --resume after validating hashes")
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        return {}
    if not checkpoint_dir.is_dir():
        raise FileNotFoundError("--resume requested but no checkpoint directory exists")
    expected = {j["assembly_id"]: j for j in jobs}
    found: dict[str, dict[str, Any]] = {}
    for path in sorted(checkpoint_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        aid = data.get("assembly_id")
        if aid not in expected or aid in found:
            raise ValueError(f"unexpected or duplicate checkpoint assembly: {aid}")
        job = expected[aid]
        if data.get("config_hash") != config_hash or data.get("input_hash") != job["input_hash"]:
            raise ValueError(f"checkpoint input/config/backend hash mismatch: {aid}")
        if data.get("source_bundle_sha256") != job["expected_source_bundle_sha256"]:
            raise ValueError(f"checkpoint source bundle hash mismatch: {aid}")
        found[aid] = data
    return found


def _save_result_checkpoint(checkpoint_dir: Path, result: dict[str, Any]) -> None:
    path = checkpoint_dir / f"{result['assembly_id']}.json"
    _json_write_atomic(path, result)


def _run_tasks(out: Path, jobs: list[dict[str, Any]], model,
               config_hash: str, backend_hash: str, resume: bool,
               budget_s: float) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    checkpoint_dir = out / "checkpoints"
    completed = _load_existing_checkpoints(checkpoint_dir, jobs, config_hash, resume)
    pending = [j for j in jobs if j["assembly_id"] not in completed]
    sampler = _RssSampler(); sampler.start()
    started = time.perf_counter()
    launch_wall = 0.0
    max_chunk_wall = 0.0
    timed_out_ids: set[str] = set()
    failed: dict[str, str] = {}
    not_started: set[str] = set()
    pool = concurrent.futures.ProcessPoolExecutor(
        max_workers=WORKERS, mp_context=mp.get_context("spawn"),
        initializer=_worker_init, initargs=(model, backend_hash, config_hash))
    stop_after_timeout = False
    stop_reason = ""
    try:
        for offset in range(0, len(pending), CHUNK_ASSEMBLIES):
            elapsed = time.perf_counter() - started
            remaining_budget = float(budget_s) - elapsed
            if remaining_budget <= 0.0:
                stop_after_timeout = True
                stop_reason = "GLOBAL_HOLDOUT_BUDGET_EXHAUSTED"
                _terminate_executor(pool)
                break
            chunk = pending[offset:offset + CHUNK_ASSEMBLIES]
            chunk_start = time.perf_counter()
            chunk_timeout = min(TASK_TIMEOUT_S, remaining_budget)
            futures = {pool.submit(_evaluate_assembly, job): job for job in chunk}
            try:
                for future in concurrent.futures.as_completed(futures, timeout=chunk_timeout):
                    job = futures[future]
                    try:
                        result = future.result()
                        if (result.get("input_hash") != job["input_hash"]
                                or result.get("config_hash") != config_hash
                                or result.get("source_bundle_sha256") != job["expected_source_bundle_sha256"]):
                            raise ValueError("worker returned mismatched input/config/source hash")
                        completed[result["assembly_id"]] = result
                        _save_result_checkpoint(checkpoint_dir, result)
                    except Exception as exc:
                        failed[job["assembly_id"]] = f"{type(exc).__name__}: {exc}"
                        result = {
                            "assembly_id": job["assembly_id"], "scenario": job["scenario"],
                            "latent_id": job["latent_id"], "latent_z": job["latent_z"],
                            "perturbation_vector": job["perturbation_vector"],
                            "source_seed": job["source_seed"],
                            "source_bundle_sha256": job["expected_source_bundle_sha256"],
                            "input_hash": job["input_hash"], "config_hash": config_hash,
                            "backend_hash": backend_hash, "status": "FAILED",
                            "error": failed[job["assembly_id"]], "design_results": [],
                        }
                        completed[job["assembly_id"]] = result
                        _save_result_checkpoint(checkpoint_dir, result)
                    _json_write_atomic(out / "progress.json", {
                        "attempted": len(completed), "planned": len(jobs),
                        "completed": sum(r.get("status") == "COMPLETE" for r in completed.values()),
                        "failed": max(len(failed), sum(r.get("status") in {"FAILED", "FAILED_LEDGER"}
                                                       for r in completed.values())),
                        "timed_out": max(len(timed_out_ids), sum(r.get("status") == "TIMEOUT"
                                                                  for r in completed.values())),
                        "updated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    })
            except concurrent.futures.TimeoutError:
                global_budget_expired = chunk_timeout < TASK_TIMEOUT_S
                stop_reason = ("GLOBAL_HOLDOUT_BUDGET_EXHAUSTED" if global_budget_expired
                               else "TASK_HARD_TIMEOUT")
                for future, job in futures.items():
                    if future.done() and job["assembly_id"] not in completed:
                        try:
                            result = future.result()
                            if (result.get("input_hash") != job["input_hash"]
                                    or result.get("config_hash") != config_hash
                                    or result.get("source_bundle_sha256") != job["expected_source_bundle_sha256"]):
                                raise ValueError("worker returned mismatched input/config/source hash")
                            completed[result["assembly_id"]] = result
                            _save_result_checkpoint(checkpoint_dir, result)
                        except Exception as exc:
                            failed[job["assembly_id"]] = f"{type(exc).__name__}: {exc}"
                            result = {"assembly_id": job["assembly_id"], "scenario": job["scenario"],
                                      "latent_id": job["latent_id"], "latent_z": job["latent_z"],
                                      "perturbation_vector": job["perturbation_vector"],
                                      "source_seed": job["source_seed"],
                                      "source_bundle_sha256": job["expected_source_bundle_sha256"],
                                      "input_hash": job["input_hash"], "config_hash": config_hash,
                                      "backend_hash": backend_hash, "status": "FAILED",
                                      "error": failed[job["assembly_id"]], "design_results": []}
                            completed[job["assembly_id"]] = result
                            _save_result_checkpoint(checkpoint_dir, result)
                    elif not future.done():
                        cancelled_before_start = future.cancel()
                        if cancelled_before_start and global_budget_expired:
                            task_status = "CANCELLED"
                        else:
                            task_status = "TIMEOUT"
                            timed_out_ids.add(job["assembly_id"])
                        result = {"assembly_id": job["assembly_id"], "scenario": job["scenario"],
                                  "latent_id": job["latent_id"], "latent_z": job["latent_z"],
                                  "perturbation_vector": job["perturbation_vector"],
                                  "source_seed": job["source_seed"],
                                  "source_bundle_sha256": job["expected_source_bundle_sha256"],
                                  "input_hash": job["input_hash"], "config_hash": config_hash,
                                  "backend_hash": backend_hash, "status": task_status,
                                  "error": f"{stop_reason}; chunk_wait_s={chunk_timeout:.6f}",
                                  "design_results": []}
                        completed[job["assembly_id"]] = result
                        _save_result_checkpoint(checkpoint_dir, result)
                max_chunk_wall = max(max_chunk_wall, time.perf_counter() - chunk_start)
                stop_after_timeout = True
                _terminate_executor(pool)
                break
            max_chunk_wall = max(max_chunk_wall, time.perf_counter() - chunk_start)
            if stop_after_timeout:
                break
    finally:
        if not stop_after_timeout:
            pool.shutdown(wait=True, cancel_futures=True)
        sampler.stop()
    launch_wall = time.perf_counter() - started
    for job in jobs:
        if job["assembly_id"] not in completed:
            not_started.add(job["assembly_id"])
    measured = {
        "workers": WORKERS, "mp_start_method": "spawn", "chunks": int(np.ceil(len(pending) / CHUNK_ASSEMBLIES)),
        "chunk_assemblies_max": CHUNK_ASSEMBLIES, "task_hard_timeout_s": TASK_TIMEOUT_S,
        "science_wall_budget_s": float(budget_s), "stop_reason": stop_reason,
        "wall_s": launch_wall, "max_chunk_wall_s": max_chunk_wall,
        "peak_process_tree_rss_mb": sampler.peak_mb,
        "attempted_or_checkpointed": len(completed),
        "complete": sum(r.get("status") == "COMPLETE" for r in completed.values()),
        "failed": max(len(failed), sum(r.get("status") in {"FAILED", "FAILED_LEDGER"}
                                       for r in completed.values())),
        "timed_out": max(len(timed_out_ids), sum(r.get("status") == "TIMEOUT"
                                                  for r in completed.values())),
        "cancelled": sum(r.get("status") == "CANCELLED" for r in completed.values()),
        "not_started": len(not_started), "over_budget": launch_wall > float(budget_s),
    }
    return completed, measured


def _parameter_registry(mode: str) -> dict[str, Any]:
    return {
        "schema": "optisys.s6.assembly_parameter_registry/1", "run_id": RUN_ID,
        "evidence": "SIMULATED_ASSUMED_TOLERANCE_UNVERIFIED",
        "model_level": "ASSUMED_MODEL",
        "nominal_distribution": "independent zero-mean truncated normal, inverse-CDF truncated at +/-3 sigma",
        "parameter_order": list(PARAMETER_ORDER),
        "nominal_sigma": {"decenter_x_mm": 0.05, "decenter_y_mm": 0.05,
                          "tilt_x_deg": 0.10, "tilt_y_deg": 0.10,
                          "axial_z_mm": 0.30},
        "scenarios": {"zero": 0.0, "tight_0p5x": 0.5,
                      "nominal_1x": 1.0, "stress_2x": 2.0},
        "correlation_assumption": "independent across axes and lenses; same latent draw scaled across scenarios",
        "pivot": "each lens front vertex; active extrinsic Rz@Ry@Rx rotation",
        "paired_policy": "apply identical relative pose vector and source rays to baseline125 and s5_position135",
        "target": {"z_mm": TARGET_Z_MM, "active_radius_mm": TARGET_RADIUS_MM, "moves_with_lenses": False},
        "lens_geometry": {"material": "N-BK7 assumed", "clear_aperture_mm": 12.0,
                          "center_thickness_mm": 2.0, "vendor_part": "NOT_VERIFIED"},
        "invalid_assembly_policy": "attempted denominator retained; invalid design capture is zero and reason is recorded; no redraw",
        "source": {"core_diameter_mm": CORE_DIAMETER_MM, "NA": NA,
                   "near_field": "uniform_area_disk_assumed",
                   "far_field": "uniform_solid_angle_assumed", "absolute_power": "UNKNOWN"},
        "bootstrap": {"replicates": BOOTSTRAP_REPLICATES,
                      "resampling_unit": "assembly_id", "seed": 8064001},
        "mode": mode,
    }


def _manifest_record(job: dict[str, Any], result: dict[str, Any] | None,
                     status: str, error: str = "") -> dict[str, Any]:
    record = {k: job.get(k) for k in (
        "assembly_id", "scenario", "latent_id", "source_seed", "source_bundle_sha256",
        "input_hash", "config_hash", "backend_hash", "assembly_seed")}
    record.update({k: job["perturbation_vector"].get(k) for k in PARAMETER_ORDER})
    record["latent_z_json"] = json.dumps(job["latent_z"], separators=(",", ":"))
    record["perturbation_vector_json"] = json.dumps(job["perturbation_vector"], sort_keys=True,
                                                     separators=(",", ":"))
    record["baseline_design_config_hash"] = _canonical_hash({
        "input_hash": job["input_hash"], "design_id": "baseline125", "nominal_l2_z_mm": 125.0})
    record["candidate_design_config_hash"] = _canonical_hash({
        "input_hash": job["input_hash"], "design_id": "s5_position135", "nominal_l2_z_mm": 135.0})
    record["status"] = status
    record["worker_wall_s"] = None if result is None else result.get("worker_wall_s")
    record["error"] = error or ("" if result is None else result.get("error", ""))
    if result:
        for design in result.get("design_results", []):
            record[f"{design['design_id']}_status"] = design.get("design_status")
            record[f"{design['design_id']}_geometry_reason"] = design.get("geometry_reason")
    return record


def _sample_rows(jobs: list[dict[str, Any]], results: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for job in jobs:
        result = results.get(job["assembly_id"])
        status = "NOT_STARTED" if result is None else result.get("status", "FAILED")
        designs = {} if result is None else {x["design_id"]: x for x in result.get("design_results", [])}
        for design_id, nominal_l2 in (("baseline125", 125.0), ("s5_position135", 135.0)):
            row = {"assembly_id": job["assembly_id"], "scenario": job["scenario"],
                   "latent_id": job["latent_id"], "source_seed": job["source_seed"],
                   "design_id": design_id, "nominal_l2_z_mm": nominal_l2,
                   "rays_per_design": job["rays_per_design"], "assembly_status": status,
                   "input_hash": job["input_hash"], "source_bundle_sha256": job["source_bundle_sha256"],
                   "design_config_hash": _canonical_hash({"input_hash": job["input_hash"],
                       "design_id": design_id, "nominal_l2_z_mm": nominal_l2})}
            row.update({k: job["perturbation_vector"][k] for k in PARAMETER_ORDER})
            values = designs.get(design_id)
            if values is None:
                row.update({"design_status": status, "geometry_reason": "",
                            "assembly_valid": None, "source_ray_count": 0,
                            "source_weight_denominator": None, "captured_count": None,
                            "captured_weight": None, "capture_fraction_input": None,
                            "plane_reacher_count": None, "r80_all_plane_reachers_mm": None,
                            "r90_all_plane_reachers_mm": None, "rms_all_plane_reachers_mm": None,
                            "conditional_r90_within_1mm_mm": None,
                            "terminal_counts_json": "{}", "terminal_weights_json": "{}",
                            "ledger_status": "NOT_RUN", "trace_wall_s": None})
            else:
                for key, value in values.items():
                    if key not in {"terminal_counts", "terminal_weights"}:
                        row[key] = value
                row["terminal_counts_json"] = json.dumps(values["terminal_counts"], sort_keys=True)
                row["terminal_weights_json"] = json.dumps(values["terminal_weights"], sort_keys=True)
            rows.append(row)
    return rows


def _paired_rows(sample_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, dict[str, Any]]] = {}
    for row in sample_rows:
        by_id.setdefault(row["assembly_id"], {})[row["design_id"]] = row
    out = []
    for assembly_id, designs in by_id.items():
        if set(designs) != {"baseline125", "s5_position135"}:
            raise ValueError(f"paired design row missing for {assembly_id}")
        b, c = designs["baseline125"], designs["s5_position135"]
        out.append({
            "assembly_id": assembly_id, "scenario": b["scenario"], "latent_id": b["latent_id"],
            "source_seed": b["source_seed"], "baseline_status": b["design_status"],
            "candidate_status": c["design_status"],
            "baseline_valid": b["assembly_valid"], "candidate_valid": c["assembly_valid"],
            "baseline_capture": b["capture_fraction_input"],
            "candidate_capture": c["capture_fraction_input"],
            "paired_delta_capture": (None if b["capture_fraction_input"] is None
                                     or c["capture_fraction_input"] is None
                                     else float(c["capture_fraction_input"])-float(b["capture_fraction_input"])),
            "baseline_p05_metric_r90_mm": b["r90_all_plane_reachers_mm"],
            "candidate_p05_metric_r90_mm": c["r90_all_plane_reachers_mm"],
            "both_designs_complete": b["assembly_status"] == c["assembly_status"] == "COMPLETE",
            "input_hash": b["input_hash"],
            **{k: b[k] for k in PARAMETER_ORDER},
        })
    out.sort(key=lambda x: (x["scenario"], int(x["latent_id"])))
    if len({x["assembly_id"] for x in out}) != len(out):
        raise ValueError("duplicate assembly IDs in paired table")
    return out


def _failure_rows(sample_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    agg: dict[tuple[str, str, str], dict[str, float]] = {}
    for row in sample_rows:
        if row["design_status"] in {"NOT_STARTED", "FAILED", "TIMEOUT", "CANCELLED"}:
            key = (row["scenario"], row["design_id"], str(row["design_status"]))
            entry = agg.setdefault(key, {"assemblies": 0, "source_rays": 0,
                                         "source_weight": 0.0})
            entry["assemblies"] += 1
            entry["source_rays"] += int(row["rays_per_design"] if row["design_status"] != "NOT_STARTED" else 0)
            continue
        counts = json.loads(row["terminal_counts_json"])
        weights = json.loads(row["terminal_weights_json"])
        for outcome in OUTCOME_CATEGORIES:
            key = (row["scenario"], row["design_id"], outcome)
            entry = agg.setdefault(key, {"assemblies": 0, "source_rays": 0,
                                         "source_weight": 0.0})
            entry["assemblies"] += int(counts.get(outcome, 0) > 0)
            entry["source_rays"] += int(counts.get(outcome, 0))
            entry["source_weight"] += float(weights.get(outcome, 0.0))
    return [{"scenario": k[0], "design_id": k[1], "outcome": k[2], **v}
            for k, v in sorted(agg.items())]


def _scenario_statistics(scenario: str, paired: list[dict[str, Any]],
                         sample_rows: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    data = [r for r in paired if r["scenario"] == scenario and r["both_designs_complete"]]
    ids = [str(r["assembly_id"]) for r in data]
    base = np.asarray([float(r["baseline_capture"]) for r in data], dtype=float)
    cand = np.asarray([float(r["candidate_capture"]) for r in data], dtype=float)
    if len(data) == 0:
        return {"scenario": scenario, "n_complete_pairs": 0, "status": "NO_COMPLETE_PAIRS"}, []
    boot = paired_cluster_bootstrap(ids, base, cand,
                                    n_replicates=BOOTSTRAP_REPLICATES,
                                    seed=8064001)
    delta_mean = float(np.mean(cand - base))
    mean_boot = np.asarray([r["mean_delta_capture"] for r in boot])
    p05_boot = np.asarray([r["p05_delta_capture"] for r in boot])
    base_rows = [r for r in sample_rows if r["scenario"] == scenario and r["design_id"] == "baseline125"]
    cand_rows = [r for r in sample_rows if r["scenario"] == scenario and r["design_id"] == "s5_position135"]
    valid_base = [bool(r["assembly_valid"]) for r in base_rows if r["assembly_valid"] is not None]
    valid_cand = [bool(r["assembly_valid"]) for r in cand_rows if r["assembly_valid"] is not None]
    def p05_for(rows):
        vals = [float(r["capture_fraction_input"]) for r in rows if r["capture_fraction_input"] is not None]
        return float(np.quantile(vals, 0.05)) if vals else None
    def metric_quantile(rows, field, q):
        vals = [float(r[field]) for r in rows if r.get(field) is not None]
        return float(np.quantile(vals, q)) if vals else None
    failure_categories = ("L1_APERTURE_BLOCK", "L2_APERTURE_BLOCK", "TRACE_FAIL",
                          "NO_INTERSECTION", "TIR", "INVALID_SOURCE", "INVALID_ASSEMBLY")
    failure_mean: dict[str, dict[str, float]] = {}
    for design_id, rows in (("baseline125", base_rows), ("s5_position135", cand_rows)):
        by_category = {category: [] for category in failure_categories}
        for row in rows:
            try:
                weights_by = json.loads(row["terminal_weights_json"])
            except (TypeError, json.JSONDecodeError):
                continue
            for category in failure_categories:
                by_category[category].append(float(weights_by.get(category, 0.0)))
        failure_mean[design_id] = {
            category: float(np.mean(vals)) if vals else 0.0
            for category, vals in by_category.items()
        }
    failure_deltas = {category: failure_mean["s5_position135"][category]
                       - failure_mean["baseline125"][category]
                       for category in failure_categories}
    stats = {
        "scenario": scenario, "n_planned_assemblies": len(base_rows),
        "n_complete_pairs": len(data), "resampling_unit": "assembly_id",
        "bootstrap_replicates": BOOTSTRAP_REPLICATES,
        "mean_capture_baseline125": float(np.mean(base)),
        "mean_capture_candidate135": float(np.mean(cand)),
        "mean_delta_capture_candidate_minus_baseline": delta_mean,
        "paired_mean_delta_capture_ci95": [float(np.quantile(mean_boot, 0.025)),
                                             float(np.quantile(mean_boot, 0.975))],
        "p05_capture_baseline125": p05_for(base_rows),
        "p05_capture_candidate135": p05_for(cand_rows),
        "p05_paired_delta_capture": float(np.quantile(cand - base, 0.05)),
        "p05_paired_delta_bootstrap_ci95": [float(np.quantile(p05_boot, 0.025)),
                                              float(np.quantile(p05_boot, 0.975))],
        "p50_capture_baseline125": float(np.quantile(base, 0.50)),
        "p50_capture_candidate135": float(np.quantile(cand, 0.50)),
        "p95_capture_baseline125": float(np.quantile(base, 0.95)),
        "p95_capture_candidate135": float(np.quantile(cand, 0.95)),
        "all_plane_r90_median_mm_baseline125": metric_quantile(base_rows, "r90_all_plane_reachers_mm", 0.50),
        "all_plane_r90_median_mm_candidate135": metric_quantile(cand_rows, "r90_all_plane_reachers_mm", 0.50),
        "all_plane_r90_p95_mm_baseline125": metric_quantile(base_rows, "r90_all_plane_reachers_mm", 0.95),
        "all_plane_r90_p95_mm_candidate135": metric_quantile(cand_rows, "r90_all_plane_reachers_mm", 0.95),
        "failure_weight_mean_by_design": failure_mean,
        "failure_weight_mean_delta_candidate_minus_baseline": failure_deltas,
        "invalid_assembly_rate_baseline125": 1.0 - float(np.mean(valid_base)) if valid_base else None,
        "invalid_assembly_rate_candidate135": 1.0 - float(np.mean(valid_cand)) if valid_cand else None,
        "n_both_valid": sum(bool(x["baseline_valid"]) and bool(x["candidate_valid"]) for x in data),
        "n_only_baseline_valid": sum(bool(x["baseline_valid"]) and not bool(x["candidate_valid"]) for x in data),
        "n_only_candidate_valid": sum(not bool(x["baseline_valid"]) and bool(x["candidate_valid"]) for x in data),
        "status": "COMPLETE" if len(data) == len(base_rows) else "PARTIAL",
    }
    return stats, boot


def _markdown_audit(stats: dict[str, Any], run_info: dict[str, Any]) -> str:
    nominal = stats.get("nominal_1x", {})
    delta = nominal.get("mean_delta_capture_candidate_minus_baseline")
    ci = nominal.get("paired_mean_delta_capture_ci95")
    p05 = nominal.get("p05_paired_delta_capture")
    claim = run_info["S6_C_ASSEMBLY_CLAIM"]
    return f"""# S6 装配级统计审计

**装配级主张：** `{claim}`  
**证据级别：** `ASSEMBLY_SAMPLED`；本统计只针对假设 P1 与本次登记的模拟误差分布。  
**装配抽样：** {run_info['completed_assemblies']} completed / {run_info['planned_assemblies']} planned；4 个情景，每情景 200 assemblies，每 design / assembly 1,024 rays。  
**非共轴参考门：** `{run_info['S6_A_RIGID_BODY_REFERENCE']}`。  
**实测状态：** `NOT_AVAILABLE`；镜片与误差分布均无厂家资格确认。

## 名义公差主估计

- `baseline125`: mean capture `{nominal.get('mean_capture_baseline125')}`；P05/P50/P95 `{nominal.get('p05_capture_baseline125')}` / `{nominal.get('p50_capture_baseline125')}` / `{nominal.get('p95_capture_baseline125')}`。
- `s5_position135`: mean capture `{nominal.get('mean_capture_candidate135')}`；P05/P50/P95 `{nominal.get('p05_capture_candidate135')}` / `{nominal.get('p50_capture_candidate135')}` / `{nominal.get('p95_capture_candidate135')}`。
- paired mean delta (135−125): `{delta}`；2,000-replicate assembly-cluster bootstrap CI95 `{ci}`。
- paired P05 delta: `{p05}`；bootstrap CI95 `{nominal.get('p05_paired_delta_bootstrap_ci95')}`。
- 配对集：`{nominal.get('n_complete_pairs')}`；both valid `{nominal.get('n_both_valid')}`，only baseline valid `{nominal.get('n_only_baseline_valid')}`，only candidate valid `{nominal.get('n_only_candidate_valid')}`。

## 失败与分母

每个公差情景固定尝试 200 个 assembly；无效装配以 capture=0 进入 attempted-design 主分母并按原因保留，不重抽。`failure_breakdown.csv` 提供 aperture、target、intersection、TIR、trace 与 invalid-assembly 的独立类别。`p1_assembly_samples.csv` 保留每一 assembly × design 的 source-weight 分母与互斥终端权重；不能把其中 rays 当作独立 bootstrap 样本。

## 解释边界

近场均匀面积与远场均匀立体角、N-BK7 球面、1 mm 接收区及容差 sigma 都是假设。绝对 source power=`UNKNOWN`；厂商镜片=`NOT_VERIFIED`；S6 结果不是制造良率、实物泵浦效率或实验测量。L2 135 mm 仍需额外 10 mm 名义轴向移动；无安装空间和行程数据可判断实物可装性。
"""


def _run(mode: str, resume: bool) -> dict[str, Any]:
    if mode not in {"pilot", "holdout"}:
        raise ValueError("mode must be pilot or holdout")
    invocation_started_utc = datetime.now(timezone.utc)
    invocation_start_clock = time.perf_counter()
    a_status = json.loads((ROOT / "runs" / RUN_ID / "s6_a_reference/s6_a_reference_summary.json")
                          .read_text(encoding="utf-8"))["status"]
    if mode == "holdout" and a_status != "PASS":
        raise RuntimeError("S6-C holdout blocked because S6-A reference gate is not PASS")
    if mode == "pilot":
        out = ROOT / "runs" / RUN_ID / "s6_c_pilot"
        n_rays, n_assemblies = 256, 32
        scenarios = [{"scenario": "pilot_nominal", "tolerance_key": "nominal_1x", "scale": 1.0}]
    else:
        out = ROOT / "runs" / RUN_ID / "s6_c_assemblies"
        n_rays, n_assemblies = 1024, 200
        scenarios = [{"scenario": name, "tolerance_key": key, "scale": SCENARIO_SCALE[key]}
                     for name, key in (("zero", "zero"), ("tight_0p5x", "tight_0p5x"),
                                       ("nominal_1x", "nominal_1x"), ("stress_2x", "stress_2x"))]
    if not out.exists():
        out.mkdir()
    elif not resume:
        raise FileExistsError(f"output exists; use --resume only if run contract hashes match: {out}")
    preholdout_science_wall_s = 0.0
    prior_holdout_wall_s = 0.0
    invocation_budget_s = HOLDOUT_HARD_CAP_S
    task_budget_s = HOLDOUT_HARD_CAP_S - HOLDOUT_POSTPROCESS_RESERVE_S
    invocation_number = 1
    if mode == "holdout":
        budget_path = ROOT / "runs" / RUN_ID / "compute_measured_preholdout.json"
        budget_record = json.loads(budget_path.read_text(encoding="utf-8"))
        if float(budget_record["science_wall_budget_total_s"]) != TOTAL_SCIENCE_BUDGET_S:
            raise ValueError("preholdout science budget differs from frozen 1,500 s budget")
        if float(budget_record["holdout_hard_cap_s"]) != HOLDOUT_HARD_CAP_S:
            raise ValueError("holdout hard cap differs from Amendment 02")
        preholdout_science_wall_s = float(budget_record["measured_before_holdout_s"])
        measured_paths = sorted(out.glob("compute_measured_[0-9][0-9][0-9].json"))
        measured_by_invocation = {
            int(p.stem.rsplit("_", 1)[1]): float(json.loads(p.read_text(encoding="utf-8"))["invocation_wall_s"])
            for p in measured_paths
        }
        session_paths = sorted(out.glob("compute_session_[0-9][0-9][0-9].json"))
        session_numbers = [int(p.stem.rsplit("_", 1)[1]) for p in session_paths]
        invocation_number = max(session_numbers, default=0) + 1
        now_utc = datetime.now(timezone.utc)
        for p in session_paths:
            number = int(p.stem.rsplit("_", 1)[1])
            if number in measured_by_invocation:
                prior_holdout_wall_s += measured_by_invocation[number]
            else:
                session = json.loads(p.read_text(encoding="utf-8"))
                begun = datetime.fromisoformat(session["started_at_utc"])
                prior_holdout_wall_s += max(0.0, (now_utc - begun).total_seconds())
        remaining_total = TOTAL_SCIENCE_BUDGET_S - preholdout_science_wall_s - prior_holdout_wall_s
        remaining_holdout = HOLDOUT_HARD_CAP_S - prior_holdout_wall_s
        invocation_budget_s = min(remaining_total, remaining_holdout)
        if invocation_budget_s <= 0.0:
            raise TimeoutError("S6 scientific wall budget exhausted before this holdout invocation")
        holdout_freeze_path = ROOT / "runs" / RUN_ID / "S6_C_HOLDOUT_FREEZE_02.json"
        holdout_freeze = json.loads(holdout_freeze_path.read_text(encoding="utf-8"))
        code_freeze = json.loads((ROOT / "runs" / RUN_ID / "S6_C_CODE_FREEZE_02.json")
                                 .read_text(encoding="utf-8"))
        runner_hash = _sha_file(ROOT / "scripts/s6_assembly.py")
        frozen_runner = code_freeze["hashes"]["scripts/s6_assembly.py"]["sha256"]
        if runner_hash != frozen_runner:
            raise ValueError("assembly runner changed after the pre-holdout code freeze")
        if holdout_freeze.get("formal_holdout_started") is not False:
            raise ValueError("holdout freeze record is absent or already marked as started")
        elapsed_before_workers = time.perf_counter() - invocation_start_clock
        task_budget_s = max(0.0, invocation_budget_s - elapsed_before_workers
                            - HOLDOUT_POSTPROCESS_RESERVE_S)
        if task_budget_s <= 0.0:
            raise TimeoutError("S6 science budget exhausted during holdout startup")
        _json_write_atomic(out / f"compute_session_{invocation_number:03d}.json", {
            "schema": "optisys.s6.compute_session/1", "run_id": RUN_ID,
            "invocation": invocation_number,
            "started_at_utc": invocation_started_utc.isoformat(timespec="seconds"),
            "budget_available_s": invocation_budget_s,
            "worker_task_budget_s": task_budget_s,
            "postprocess_reserve_s": HOLDOUT_POSTPROCESS_RESERVE_S,
            "science_wall_before_holdout_s": preholdout_science_wall_s,
            "prior_holdout_wall_s": prior_holdout_wall_s,
            "total_science_budget_s": TOTAL_SCIENCE_BUDGET_S,
            "holdout_hard_cap_s": HOLDOUT_HARD_CAP_S,
        })
    model = _load_model()
    seed_info = ({"assembly_seed": 8062001, "source_seed_base": 80622000} if mode == "pilot" else
                 {"assembly_seed": 8062101, "source_seed_base": 80630000,
                  "bootstrap_seed": 8064001,
                  "science_wall_budget_s": TOTAL_SCIENCE_BUDGET_S,
                  "holdout_hard_cap_s": HOLDOUT_HARD_CAP_S})
    config_hash, backend_hashes = _config_hashes(mode, n_rays, n_assemblies, scenarios, seed_info)
    backend_hash = _canonical_hash(backend_hashes)
    contract_path = out / "run_contract.json"
    if contract_path.exists():
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        if contract.get("config_hash") != config_hash or contract.get("backend_hash") != backend_hash:
            raise ValueError("existing run contract hash differs; checkpoint reuse is forbidden")
    else:
        if resume:
            raise FileNotFoundError("resume requested without run_contract.json")
        contract = {
            "schema": "optisys.s6.assembly_run_contract/1", "run_id": RUN_ID,
            "mode": mode, "config_hash": config_hash, "backend_hash": backend_hash,
            "backend_hashes": backend_hashes, "workers": WORKERS,
            "mp_start_method": "spawn", "task_timeout_s": TASK_TIMEOUT_S,
            "science_wall_budget_s": TOTAL_SCIENCE_BUDGET_S,
            "holdout_hard_cap_s": HOLDOUT_HARD_CAP_S if mode == "holdout" else None,
            "holdout_postprocess_reserve_s": HOLDOUT_POSTPROCESS_RESERVE_S if mode == "holdout" else None,
            "chunk_assemblies": CHUNK_ASSEMBLIES,
            "rays_per_design": n_rays, "planned_assemblies_per_scenario": n_assemblies,
            "scenarios": scenarios, "seed_info": seed_info,
            "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        _json_write_atomic(contract_path, contract)
    registry = _parameter_registry(mode)
    _json_write_atomic(out / "assembly_parameter_registry.json", registry)

    if mode == "holdout":
        plan_path = ROOT / "runs" / RUN_ID / "compute_plan.json"
        if not plan_path.is_file():
            raise FileNotFoundError("frozen compute_plan.json missing")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        if plan["holdout"]["assemblies_per_scenario"] != n_assemblies or plan["holdout"]["rays_per_assembly_per_design"] != n_rays:
            raise ValueError("holdout size differs from pre-result frozen compute plan")
        pilot_status_path = ROOT / "runs" / RUN_ID / "s6_c_pilot/pilot_run_status.json"
        if not pilot_status_path.is_file():
            raise RuntimeError("S6-C pilot must complete before formal holdout")
        pilot_status = json.loads(pilot_status_path.read_text(encoding="utf-8"))
        if pilot_status.get("status") != "PASS" or pilot_status.get("config_hash") is None:
            raise RuntimeError("S6-C pilot failed or lacks a run contract")

    jobs: list[dict[str, Any]] = []
    source_seed_base = seed_info["source_seed_base"]
    latents = truncated_standard_normal_latents(n_assemblies, seed_info["assembly_seed"])
    source_hash_cache: dict[int, str] = {}
    for scenario in scenarios:
        for latent_id in range(n_assemblies):
            latent = [float(x) for x in latents[latent_id]]
            source_seed = source_seed_base + latent_id
            if source_seed == S5_HOLDOUT_SEED_FORBIDDEN:
                raise ValueError("S5 holdout seed cannot enter S6-C")
            if source_seed not in source_hash_cache:
                source_hash_cache[source_seed] = _source_hash(source_seed, n_rays)
            vector = perturbation_vector(latent, scenario["tolerance_key"])
            assembly_id = f"{scenario['scenario']}_{latent_id:04d}"
            input_contract = {
                "assembly_id": assembly_id, "scenario": scenario["scenario"],
                "tolerance_key": scenario["tolerance_key"], "latent_id": latent_id,
                "latent_z": latent, "perturbation_vector": vector,
                "source_seed": source_seed,
                "source_bundle_sha256": source_hash_cache[source_seed],
                "rays_per_design": n_rays, "target_z_mm": TARGET_Z_MM,
                "target_radius_mm": TARGET_RADIUS_MM,
                "config_hash": config_hash, "backend_hash": backend_hash,
            }
            input_hash = _canonical_hash(input_contract)
            job = {**input_contract,
                   "expected_source_bundle_sha256": input_contract["source_bundle_sha256"],
                   "assembly_seed": seed_info["assembly_seed"],
                   "input_hash": input_hash,
                   **vector}
            jobs.append(job)
    if len({j["assembly_id"] for j in jobs}) != len(jobs):
        raise ValueError("duplicate assembly IDs before execution")
    _write_csv(out / "source_bundle_index.csv", [
        {"source_seed": seed, "rays_per_design": n_rays,
         "source_bundle_sha256": digest, "distribution_id": "uniform_area_disk+uniform_solid_angle/v1"}
        for seed, digest in sorted(source_hash_cache.items())])

    results, measured = _run_tasks(out, jobs, model, config_hash, backend_hash,
                                   resume, budget_s=task_budget_s)
    sample_rows = _sample_rows(jobs, results)
    paired_rows = _paired_rows(sample_rows)
    manifest_rows = []
    for job in jobs:
        result = results.get(job["assembly_id"])
        manifest_rows.append(_manifest_record(
            job, result, "NOT_STARTED" if result is None else result.get("status", "FAILED")))
    _write_csv(out / "assembly_manifest.csv", manifest_rows)
    _write_csv(out / "p1_assembly_samples.csv", sample_rows)
    _write_csv(out / "paired_assembly_comparison.csv", paired_rows)
    _write_csv(out / "failure_breakdown.csv", _failure_rows(sample_rows))

    if mode == "pilot":
        status = "PASS" if (measured["complete"] == len(jobs) and measured["failed"] == 0
                             and measured["timed_out"] == 0 and measured["not_started"] == 0
                             and all(r.get("status") == "COMPLETE" for r in results.values())) else "PARTIAL"
        pilot_status = {
            "schema": "optisys.s6.pilot_status/1", "run_id": RUN_ID, "status": status,
            "mode": "pilot_nominal_only", "config_hash": config_hash,
            "planned_assemblies": len(jobs), "completed_assemblies": measured["complete"],
            "rays_per_design": n_rays, "workers": WORKERS,
            "measured": measured, "purpose": "correctness, parameter effect, checkpoint and throughput only; excluded from holdout claim",
            "candidate_effect_used_to_change_plan": False,
            "finished_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        _json_write_atomic(out / "pilot_run_status.json", pilot_status)
        print(json.dumps(pilot_status, ensure_ascii=False, indent=2))
        return pilot_status

    scenario_stats: dict[str, Any] = {}
    bootstrap_rows: list[dict[str, Any]] = []
    for scenario in scenarios:
        name = scenario["scenario"]
        stats, boot = _scenario_statistics(name, paired_rows, sample_rows)
        scenario_stats[name] = stats
        bootstrap_rows.extend({"scenario": name, **r} for r in boot)
    if bootstrap_rows:
        _write_csv(out / "assembly_bootstrap_replicates.csv", bootstrap_rows)
    else:
        (out / "assembly_bootstrap_replicates.csv").write_text(
            "scenario,replicate,resampling_unit\n", encoding="utf-8")
    zero_rows = [r for r in paired_rows if r["scenario"] == "zero"]
    _write_csv(out / "zero_tolerance_controls.csv", [
        {**r, "all_perturbations_zero": all(float(x) == 0.0 for x in
          [r.get("L1_dx_mm", 0), r.get("L1_dy_mm", 0), r.get("L1_tilt_x_deg", 0),
           r.get("L1_tilt_y_deg", 0), r.get("L1_dz_mm", 0), r.get("L2_dx_mm", 0),
           r.get("L2_dy_mm", 0), r.get("L2_tilt_x_deg", 0), r.get("L2_tilt_y_deg", 0),
           r.get("L2_dz_mm", 0)])}
        for r in zero_rows])
    invocation_wall_s = time.perf_counter() - invocation_start_clock
    measured.update({
        "invocation_wall_s": invocation_wall_s,
        "invocation_budget_s": invocation_budget_s,
        "worker_task_budget_s": task_budget_s,
        "preholdout_science_wall_s": preholdout_science_wall_s,
        "prior_holdout_wall_s": prior_holdout_wall_s,
        "over_budget": invocation_wall_s > invocation_budget_s,
    })
    completed_all = (measured["complete"] == len(jobs) and measured["not_started"] == 0
                     and not measured["over_budget"])
    nominal = scenario_stats.get("nominal_1x", {})
    ci = nominal.get("paired_mean_delta_capture_ci95", [None, None])
    p05_ci = nominal.get("p05_paired_delta_bootstrap_ci95", [None, None])
    invalid_delta = ((nominal.get("invalid_assembly_rate_candidate135") or 0.0)
                     - (nominal.get("invalid_assembly_rate_baseline125") or 0.0))
    failure_deltas = nominal.get("failure_weight_mean_delta_candidate_minus_baseline", {})
    worse_failure_categories = sorted(k for k, v in failure_deltas.items() if float(v) > 1e-12)
    r90_tail_worse = (nominal.get("all_plane_r90_p95_mm_candidate135") is not None
                      and nominal.get("all_plane_r90_p95_mm_baseline125") is not None
                      and nominal["all_plane_r90_p95_mm_candidate135"]
                      > nominal["all_plane_r90_p95_mm_baseline125"] + 1e-12)
    tradeoff_flags = {
        "negative_or_unresolved_paired_p05_tail": (
            nominal.get("p05_paired_delta_capture", -1.0) < 0.0
            or p05_ci[0] is None or p05_ci[0] < -1e-15),
        "invalid_assembly_rate_increase": invalid_delta > 0.0,
        "failure_weight_increase_categories": worse_failure_categories,
        "all_plane_r90_p95_worse": bool(r90_tail_worse),
    }
    if not completed_all:
        claim = "PARTIAL"
    elif (ci[0] is not None and ci[0] > 0.0
          and nominal.get("p05_paired_delta_capture", -1.0) >= 0.0
          and (p05_ci[0] is None or p05_ci[0] >= -1e-15)
          and invalid_delta <= 0.0 and not worse_failure_categories and not r90_tail_worse):
        claim = "SUPPORTED_WITHIN_ASSUMED_P1_AND_TOLERANCES"
    else:
        claim = "TRADEOFF_OR_NO_SUPPORTED_GAIN"
    overall = {
        "schema": "optisys.s6.assembly_statistics/1", "run_id": RUN_ID,
        "S6_C_ASSEMBLY_CLAIM": claim,
        "S6_A_RIGID_BODY_REFERENCE": a_status,
        "status": "COMPLETE" if completed_all and measured["failed"] == 0 and measured["timed_out"] == 0 else "PARTIAL",
        "empirical_status": "NOT_AVAILABLE",
        "planned_assemblies": len(jobs), "completed_assemblies": measured["complete"],
        "failed_assemblies": measured["failed"], "timed_out_assemblies": measured["timed_out"],
        "not_started_assemblies": measured["not_started"],
        "rays_per_design_per_assembly": n_rays,
        "ray_design_trace_count_planned": len(jobs) * 2 * n_rays,
        "bootstrap_unit": "assembly_id", "bootstrap_replicates": BOOTSTRAP_REPLICATES,
        "scenarios": scenario_stats,
        "compute_measured": measured,
        "claim_rule": "mean paired assembly-cluster bootstrap CI95 lower > 0; paired P05 delta and its bootstrap CI are non-negative; invalid-assembly and other failure weights do not increase; all-plane r90 P95 does not worsen. Any observed tail/failure/r90 cost is reported as TRADEOFF_OR_NO_SUPPORTED_GAIN.",
        "tradeoff_flags": tradeoff_flags,
        "caution": "A supported result applies only to assumed P1 geometry and simulated tolerance distributions; no manufacturing or empirical claim.",
        "finished_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _json_write_atomic(out / "assembly_statistics.json", overall)
    audit = _markdown_audit(scenario_stats, {
        "S6_C_ASSEMBLY_CLAIM": claim, "S6_A_RIGID_BODY_REFERENCE": a_status,
        "completed_assemblies": measured["complete"], "planned_assemblies": len(jobs),
    })
    (out / "S6_ASSEMBLY_SCIENTIFIC_AUDIT.md").write_text(audit, encoding="utf-8")
    cumulative_holdout_wall_s = prior_holdout_wall_s + invocation_wall_s
    cumulative_science_wall_s = preholdout_science_wall_s + cumulative_holdout_wall_s
    compute_record = {
        "schema": "optisys.s6.compute_measured/1", "run_id": RUN_ID,
        "invocation": invocation_number, "invocation_wall_s": invocation_wall_s,
        "assembly_worker_wall_s": measured["wall_s"],
        "invocation_budget_s": invocation_budget_s,
        "worker_task_budget_s": task_budget_s,
        "prior_holdout_wall_s": prior_holdout_wall_s,
        "cumulative_holdout_wall_s": cumulative_holdout_wall_s,
        "preholdout_science_wall_s": preholdout_science_wall_s,
        "cumulative_science_wall_s": cumulative_science_wall_s,
        "total_science_budget_s": TOTAL_SCIENCE_BUDGET_S,
        "remaining_total_budget_s": TOTAL_SCIENCE_BUDGET_S - cumulative_science_wall_s,
        "holdout_hard_cap_s": HOLDOUT_HARD_CAP_S,
        "remaining_holdout_cap_s": HOLDOUT_HARD_CAP_S - cumulative_holdout_wall_s,
        "workers": measured["workers"], "process_tree_rss_peak_mb": measured["peak_process_tree_rss_mb"],
        "measured": measured,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _json_write_atomic(out / f"compute_measured_{invocation_number:03d}.json", compute_record)
    _json_write_atomic(out / "compute_measured.json", compute_record)
    status_record = {
        "schema": "optisys.s6.assembly_run_status/1", "run_id": RUN_ID,
        "status": overall["status"], "S6_C_ASSEMBLY_CLAIM": claim,
        "config_hash": config_hash, "backend_hash": backend_hash,
        "planned_assemblies": len(jobs), "complete": measured["complete"],
        "failed": measured["failed"], "timed_out": measured["timed_out"],
        "not_started": measured["not_started"], "outer_wall_s": measured["wall_s"],
        "invocation_wall_s": invocation_wall_s,
        "cumulative_science_wall_s": cumulative_science_wall_s,
        "remaining_total_budget_s": TOTAL_SCIENCE_BUDGET_S - cumulative_science_wall_s,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    _json_write_atomic(out / "run_status.json", status_record)
    print(json.dumps({"S6_C_ASSEMBLY_CLAIM": claim, "status": overall["status"],
                      "planned": len(jobs), "completed": measured["complete"],
                      "failed": measured["failed"], "timed_out": measured["timed_out"],
                      "not_started": measured["not_started"],
                      "nominal_mean_delta": nominal.get("mean_delta_capture_candidate_minus_baseline"),
                      "nominal_ci95": nominal.get("paired_mean_delta_capture_ci95"),
                      "nominal_p05_delta": nominal.get("p05_paired_delta_capture"),
                      "workers": measured["workers"], "peak_rss_mb": measured["peak_process_tree_rss_mb"],
                      "wall_s": measured["wall_s"]}, ensure_ascii=False, indent=2))
    return overall


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("pilot", "holdout"), default="pilot")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    result = _run(args.mode, args.resume)
    return 0 if result.get("status", result.get("status")) == "PASS" or result.get("status") == "COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
