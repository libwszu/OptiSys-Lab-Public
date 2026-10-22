"""Profile the actual S6 noncoaxial P1 tracer on Windows spawn workers."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import hashlib
import json
import multiprocessing as mp
import os
import platform
import subprocess
import sys
import threading
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
from optisys.optics.s6_rigid_body import LensPose, trace_local  # noqa: E402
from optisys.sources.multimode_fiber import sample_multimode_fiber  # noqa: E402

RUN_ID = "20261021_024715_S6_P1"
G4 = ROOT / "runs/20261020_133555_G4_ec3e2813_0e48"
SIZES = (256, 512, 2048)
WORKERS = (1, 2, 4)
TASK_TIMEOUT_S = 120


def _load_model():
    optics = json.loads((G4 / "optics_model.json").read_text(encoding="utf-8"))
    config = yaml.safe_load((ROOT / "configs/pump976_g4_l0.yaml").read_text(encoding="utf-8-sig"))
    return build_model(optics, config)


def _trace_chunk(payload: tuple[Any, ...]) -> dict[str, Any]:
    model, ids, origins, directions, weights, poses = payload
    started = time.perf_counter()
    result = trace_local(model, ids, origins, directions, weights, poses)
    wall = time.perf_counter() - started
    rows = []
    for row in result.ray_rows:
        rows.append({k: row.get(k) for k in (
            "ray_id", "terminal_outcome", "target_x", "target_y", "target_z_mm",
            "exit_dx", "exit_dy", "exit_dz")})
    canonical = json.dumps(rows, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return {"n_rays": len(rows), "trace_wall_s": wall,
            "rays_per_s": len(rows) / max(wall, 1e-12),
            "source_weight_total": result.ledger["source_weight_total"],
            "ledger_status": result.ledger["status"],
            "process_rss_mb": psutil.Process().memory_info().rss / (1024 * 1024),
            "output_sha256": hashlib.sha256(canonical).hexdigest(), "rows": rows}


class _TreeRssSampler:
    def __init__(self, pid: int):
        self.parent = psutil.Process(pid)
        self.peak_mb = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self) -> None:
        while not self._stop.is_set():
            total = 0
            try:
                procs = [self.parent, *self.parent.children(recursive=True)]
                for proc in procs:
                    try:
                        total += proc.memory_info().rss
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
                self.peak_mb = max(self.peak_mb, total / (1024 * 1024))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            self._stop.wait(0.02)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> float:
        self._stop.set()
        self._thread.join(timeout=2)
        return self.peak_mb


def _kill_children() -> None:
    try:
        parent = psutil.Process()
        children = parent.children(recursive=True)
    except psutil.Error:
        return
    for proc in reversed(children):
        try:
            proc.terminate()
        except psutil.Error:
            pass
    _, alive = psutil.wait_procs(children, timeout=3)
    for proc in alive:
        try:
            proc.kill()
        except psutil.Error:
            pass


def _run_batch(pool: concurrent.futures.ProcessPoolExecutor, model,
               n_rays: int, workers: int, seed: int, poses: tuple[LensPose, LensPose]
               ) -> dict[str, Any]:
    rays = sample_multimode_fiber(n_rays, 0.105, 0.22, seed=seed)
    chunks = [x for x in np.array_split(np.arange(n_rays), workers) if x.size]
    payloads = [(model, rays.ray_id[ix], rays.origin_mm[ix], rays.direction[ix], rays.weight[ix], poses)
                for ix in chunks]
    sampler = _TreeRssSampler(os.getpid())
    sampler.start()
    started = time.perf_counter()
    futures = [pool.submit(_trace_chunk, payload) for payload in payloads]
    try:
        chunks_out = [future.result(timeout=TASK_TIMEOUT_S) for future in futures]
    except concurrent.futures.TimeoutError:
        for future in futures:
            future.cancel()
        _kill_children()
        raise TimeoutError(f"S6 profile batch exceeded hard timeout {TASK_TIMEOUT_S}s")
    scheduler_wall = time.perf_counter() - started
    peak_tree_mb = sampler.stop()
    rows = sorted((row for chunk in chunks_out for row in chunk["rows"]), key=lambda r: r["ray_id"])
    canonical = json.dumps(rows, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    return {
        "n_rays": n_rays, "workers": workers, "scheduler_wall_s": scheduler_wall,
        "throughput_rays_s": n_rays / max(scheduler_wall, 1e-12),
        "worker_trace_wall_s": [x["trace_wall_s"] for x in chunks_out],
        "worker_throughput_rays_s": [x["rays_per_s"] for x in chunks_out],
        "worker_rss_mb": [x["process_rss_mb"] for x in chunks_out],
        "peak_process_tree_rss_mb": peak_tree_mb,
        "source_weight_total": rays.total_weight,
        "all_ledgers_pass": all(x["ledger_status"] == "PASS" for x in chunks_out),
        "output_sha256": hashlib.sha256(canonical).hexdigest(),
    }


def _gpu_probe() -> dict[str, Any]:
    try:
        p = subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True, timeout=5)
        return {"command_exit_code": p.returncode,
                "device_list": p.stdout.strip(), "status": "DETECTED_NOT_TESTED" if p.returncode == 0 else "NOT_AVAILABLE"}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"status": "NOT_AVAILABLE", "error": f"{type(exc).__name__}: {exc}"}


def run() -> dict[str, Any]:
    run_dir = ROOT / "runs" / RUN_ID
    out = run_dir / "compute_profile"
    if out.exists():
        raise FileExistsError(f"refusing to overwrite profile output {out}")
    out.mkdir(parents=True)
    model = _load_model()
    poses = (LensPose(dx_mm=0.05, dy_mm=-0.02, dz_mm=0.15,
                      tilt_x_deg=0.10, tilt_y_deg=-0.04),
             LensPose(dx_mm=-0.03, dy_mm=0.02, dz_mm=-0.10,
                      tilt_x_deg=-0.03, tilt_y_deg=0.10))
    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[key] = "1"
    mem = psutil.virtual_memory()
    rss_soft_mb = min(8192.0, mem.available * 0.5 / (1024 * 1024))
    env_threads = {k: os.environ.get(k) for k in
                   ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")}
    profiles: list[dict[str, Any]] = []
    hash_by_size: dict[int, set[str]] = {n: set() for n in SIZES}
    overall_start = time.perf_counter()
    for worker_count in WORKERS:
        setup_started = time.perf_counter()
        rss_sampler = _TreeRssSampler(os.getpid())
        rss_sampler.start()
        pool = concurrent.futures.ProcessPoolExecutor(
            max_workers=worker_count, mp_context=mp.get_context("spawn"))
        profile: dict[str, Any] = {"workers": worker_count}
        try:
            cold = _run_batch(pool, model, 256, worker_count, 8068001, poses)
            cold["phase"] = "cold_first_batch_256"
            profile["pool_start_and_first_batch_wall_s"] = time.perf_counter() - setup_started
            profile["cold_call"] = {k: v for k, v in cold.items() if k != "rows"}
            warmup = _run_batch(pool, model, 256, worker_count, 8068001, poses)
            profile["warmup"] = {**{k: v for k, v in warmup.items() if k != "rows"},
                                  "phase": "warmup_256"}
            profile["warm_by_size"] = []
            for n_rays in SIZES:
                repeats = [_run_batch(pool, model, n_rays, worker_count, 8068001, poses)
                           for _ in range(3)]
                times = [x["scheduler_wall_s"] for x in repeats]
                p50 = float(np.percentile(times, 50))
                p95 = float(np.percentile(times, 95))
                hashes = {x["output_sha256"] for x in repeats}
                hash_by_size[n_rays].update(hashes)
                profile["warm_by_size"].append({
                    "n_rays": n_rays, "warm_repeats": len(repeats),
                    "wall_p50_s": p50, "wall_p95_s": p95,
                    "throughput_p50_rays_s": n_rays / max(p50, 1e-12),
                    "output_sha256": sorted(hashes), "output_hashes_identical": len(hashes) == 1,
                    "worker_rss_peak_mb": max(max(x["worker_rss_mb"], default=0.0) for x in repeats),
                    "process_tree_rss_peak_mb": max(x["peak_process_tree_rss_mb"] for x in repeats),
                    "source_weight_total": repeats[-1]["source_weight_total"],
                    "ledgers_pass": all(x["all_ledgers_pass"] for x in repeats),
                })
        finally:
            pool.shutdown(wait=True, cancel_futures=True)
            profile["worker_pool_total_wall_s"] = time.perf_counter() - setup_started
            profile["peak_process_tree_rss_mb"] = rss_sampler.stop()
        profiles.append(profile)
    speedup_2048: dict[int, float] = {}
    ref = next(p for p in profiles if p["workers"] == 1)
    ref_rate = next(x["throughput_p50_rays_s"] for x in ref["warm_by_size"] if x["n_rays"] == 2048)
    for profile in profiles:
        rate = next(x["throughput_p50_rays_s"] for x in profile["warm_by_size"] if x["n_rays"] == 2048)
        speedup_2048[profile["workers"]] = rate / ref_rate
    best = max(profiles, key=lambda x: next(y["throughput_p50_rays_s"]
                                             for y in x["warm_by_size"] if y["n_rays"] == 2048))
    best_rss = best["peak_process_tree_rss_mb"]
    chosen_workers = best["workers"] if speedup_2048[best["workers"]] >= 1.3 and best_rss <= rss_soft_mb else 1
    hashes_consistent = all(len(values) == 1 for values in hash_by_size.values())
    status = "PASS" if hashes_consistent and all(
        x["ledgers_pass"] and x["output_hashes_identical"]
        for p in profiles for x in p["warm_by_size"]) else "FAIL"
    record = {
        "schema": "optisys.s6.compute_profile/1", "run_id": RUN_ID,
        "status": status, "profile_input": "actual S6 local-frame P1 tracer; both lenses noncoaxial",
        "python": sys.version, "platform": platform.platform(), "cpu_name": platform.processor()
        or os.environ.get("PROCESSOR_IDENTIFIER", "UNKNOWN"),
        "logical_processors": psutil.cpu_count(logical=True),
        "memory_total_mb": mem.total / (1024 * 1024),
        "memory_available_at_start_mb": mem.available / (1024 * 1024),
        "rss_soft_cap_mb": rss_soft_mb, "thread_environment": env_threads,
        "task_timeout_s": TASK_TIMEOUT_S, "rays_per_size": list(SIZES),
        "workers_tested": list(WORKERS), "warm_repeats_per_size": 3,
        "mp_start_method": "spawn", "speedup_at_2048": speedup_2048,
        "selected_workers_by_frozen_rule": chosen_workers,
        "outputs_identical_across_workers_for_each_size": hashes_consistent,
        "gpu": _gpu_probe(), "profiles": profiles,
        "outer_wall_s": time.perf_counter() - overall_start,
        "measured_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (out / "compute_profile.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                                               encoding="utf-8")
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    result = run()
    print(json.dumps({k: result[k] for k in (
        "status", "cpu_name", "logical_processors", "memory_available_at_start_mb",
        "rss_soft_cap_mb", "speedup_at_2048", "selected_workers_by_frozen_rule",
        "outputs_identical_across_workers_for_each_size", "gpu", "outer_wall_s")},
        ensure_ascii=False, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
