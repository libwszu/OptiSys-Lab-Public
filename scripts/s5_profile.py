"""Profile actual S5 high-NA Optiland traces at registered worker scales."""

from __future__ import annotations

import os

for _name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_name] = "1"

import concurrent.futures
import csv
import hashlib
import json
import multiprocessing as mp
import statistics
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np
import psutil

ROOT = Path(__file__).resolve().parents[1]
G4_RUN = ROOT / "runs/20261020_133555_G4_ec3e2813_0e48"
S5_RUN = ROOT / "runs/20261020_210201_S5_HNA"
SIZES = (256, 512, 2048)
WORKERS = (1, 2, 4)
REPEATS = 3
TIMEOUT_S = 180


def _load_payload(n: int) -> dict[str, Any]:
    with (G4_RUN / "source_samples.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    chosen = np.linspace(0, len(rows) - 1, n, dtype=int)
    selected = [rows[i] for i in chosen]
    return {
        "ray_id": np.asarray([int(r["ray_id"]) for r in selected], dtype=np.int64),
        "origin": np.asarray([[float(r[k]) for k in ("x0_mm", "y0_mm", "z0_mm")] for r in selected]),
        "direction": np.asarray([[float(r[k]) for k in ("dx", "dy", "dz")] for r in selected]),
        "weight": np.asarray([float(r["weight"]) for r in selected]),
    }


def _trace_task(payload: dict[str, Any]) -> dict[str, Any]:
    from optisys.config_g4 import load_pump976_config
    from optisys.optics.pump_optiland import OptilandPumpTracer
    from optisys.sources.multimode_fiber import RayBundle

    start = time.perf_counter()
    c = load_pump976_config(str(ROOT / "configs/pump976_g4_l0.yaml"))
    bundle = RayBundle(
        ray_id=payload["ray_id"], origin_mm=payload["origin"],
        direction=payload["direction"], weight=payload["weight"],
        seed=976051, distribution_id="S5_profile_subset_v1", metadata={},
    )
    result = OptilandPumpTracer(c.beamline, wavelength_nm=c.wavelength_nm).trace(bundle)
    elapsed = time.perf_counter() - start
    a = np.column_stack((result.x_mm, result.y_mm, result.weight_out,
                         result.valid.astype(float))).astype("<f8", copy=False)
    digest = hashlib.sha256(a.tobytes() + "|".join(map(str, result.blocked_at)).encode()).hexdigest()
    return {
        "n_rays": int(bundle.n_rays), "status": result.status,
        "n_valid": result.n_valid, "trace_wall_s": elapsed,
        "rays_per_s": float(bundle.n_rays / elapsed) if elapsed else None,
        "output_sha256": digest,
        "source_weight_total": bundle.total_weight,
        "process_rss_mb": psutil.Process().memory_info().rss / 1024**2,
    }


class RSSWatch:
    def __init__(self) -> None:
        self.peak = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self) -> None:
        parent = psutil.Process()
        while not self._stop.is_set():
            rss = 0
            try:
                procs = [parent, *parent.children(recursive=True)]
                rss = sum(p.memory_info().rss for p in procs if p.is_running())
            except (psutil.Error, OSError):
                pass
            self.peak = max(self.peak, rss)
            self._stop.wait(0.05)

    def __enter__(self):
        self._thread.start()
        return self

    def __exit__(self, *_):
        self._stop.set()
        self._thread.join(timeout=2)


def _task_with_timeout(future, timeout: float = TIMEOUT_S) -> dict[str, Any]:
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError as exc:
        raise TimeoutError(f"P1 trace exceeded {timeout}s hard task limit") from exc


def _terminate_executor(executor: concurrent.futures.ProcessPoolExecutor) -> None:
    processes = list((getattr(executor, "_processes", None) or {}).values())
    for process in processes:
        try:
            process.terminate()
        except (OSError, AttributeError):
            pass
    for process in processes:
        try:
            process.join(timeout=2)
            if process.is_alive():
                process.kill()
        except (OSError, AttributeError):
            pass


def main() -> int:
    S5_RUN.mkdir(parents=True, exist_ok=True)
    all_rows: list[dict[str, Any]] = []
    profiles = []
    for workers in WORKERS:
        watch = RSSWatch()
        process_setup_wall = 0.0
        cold_call = None
        warm_by_size: dict[int, list[dict[str, Any]]] = {n: [] for n in SIZES}
        if workers == 1:
            with watch:
                cold_payload = _load_payload(SIZES[0])
                t = time.perf_counter()
                cold_call = _trace_task(cold_payload)
                cold_call["scheduler_wall_s"] = time.perf_counter() - t
                cold_call["phase"] = "cold_single_process_256"
                all_rows.append({"workers": workers, **cold_call})
                for n in SIZES:
                    payload = _load_payload(n)
                    for rep in range(REPEATS):
                        row = _trace_task(payload)
                        row.update({"workers": workers, "phase": "warm", "replicate": rep + 1})
                        warm_by_size[n].append(row)
                        all_rows.append(row)
        else:
            ctx = mp.get_context("spawn")
            executor = concurrent.futures.ProcessPoolExecutor(max_workers=workers, mp_context=ctx)
            try:
                with watch:
                    t_pool = time.perf_counter()
                    first = executor.submit(_trace_task, _load_payload(SIZES[0]))
                    cold_call = _task_with_timeout(first)
                    process_setup_wall = time.perf_counter() - t_pool
                    cold_call.update({"phase": "cold_pool_start_256", "scheduler_wall_s": process_setup_wall})
                    all_rows.append({"workers": workers, **cold_call})
                    # Force each worker to initialize once; these warm-up rows
                    # are logged but not used in the warm p50/p95 summaries.
                    init_futures = [executor.submit(_trace_task, _load_payload(SIZES[0]))
                                    for _ in range(max(0, workers - 1))]
                    for future in init_futures:
                        warmup = _task_with_timeout(future)
                        all_rows.append({"workers": workers, "phase": "worker_init_warmup", **warmup})
                    for n in SIZES:
                        payload = _load_payload(n)
                        futures = [executor.submit(_trace_task, payload) for _ in range(REPEATS)]
                        for rep, future in enumerate(futures, 1):
                            row = _task_with_timeout(future)
                            row.update({"workers": workers, "phase": "warm", "replicate": rep})
                            warm_by_size[n].append(row)
                            all_rows.append(row)
            except BaseException:
                _terminate_executor(executor)
                raise
            finally:
                executor.shutdown(wait=True, cancel_futures=True)

        by_size = []
        for n in SIZES:
            rows = warm_by_size[n]
            times = [r["trace_wall_s"] for r in rows]
            throughputs = [r["rays_per_s"] for r in rows]
            by_size.append({
                "n_rays": n, "warm_repeats": len(rows),
                "wall_p50_s": float(np.percentile(times, 50)),
                "wall_p95_s": float(np.percentile(times, 95)),
                "throughput_p50_rays_s": float(np.percentile(throughputs, 50)),
                "output_hashes_identical": len({r["output_sha256"] for r in rows}) == 1,
            })
        profiles.append({
            "workers": workers, "pool_or_cold_setup_wall_s": process_setup_wall,
            "cold_call": cold_call, "warm_by_size": by_size,
            "peak_process_tree_rss_mb": watch.peak / 1024**2,
        })

    baseline_throughput = profiles[0]["warm_by_size"][-1]["throughput_p50_rays_s"]
    for profile in profiles:
        profile["speedup_vs_1_worker_at_2048"] = (
            profile["warm_by_size"][-1]["throughput_p50_rays_s"] / baseline_throughput
        )
    result = {
        "schema": "optisys.s5.compute_profile/1", "run_id": "20261020_210201_S5_HNA",
        "purpose": "actual P1 NA=0.22 scale and worker profile; not a design result",
        "profile_sizes": list(SIZES), "workers_tested": list(WORKERS),
        "warm_repeats_per_size": REPEATS, "task_timeout_s": TIMEOUT_S,
        "thread_environment": {k: os.environ.get(k) for k in
                                ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")},
        "input_ray_selection": "uniformly spaced indices from immutable G4 source_samples.csv",
        "profiles": profiles, "samples": all_rows,
    }
    (S5_RUN / "compute_measured.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                                                   encoding="utf-8")
    with (S5_RUN / "compute_profile_samples.csv").open("w", newline="", encoding="utf-8") as f:
        fields = sorted({key for row in all_rows for key in row})
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader(); writer.writerows(all_rows)
    print(json.dumps({"workers": [{"workers": p["workers"],
                                  "speedup_vs_1_worker_at_2048": p["speedup_vs_1_worker_at_2048"],
                                  "peak_process_tree_rss_mb": p["peak_process_tree_rss_mb"],
                                  "warm": p["warm_by_size"]} for p in profiles],
                      "compute_measured": str(S5_RUN / "compute_measured.json")},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
