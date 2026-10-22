"""Benchmark-driven compute planning.

Rules implemented here (master prompt section 2):

* measure before scaling;
* test 1/2/4/6 worker processes on a workload that is representative of the
  gate, using median wall time;
* pin BLAS/OpenMP thread counts to 1 whenever process parallelism is used so
  that nested oversubscription cannot inflate or deflate the comparison;
* keep GPU disabled unless a GPU path exists, is numerically identical and is
  measurably faster.  At G0 no GPU path exists, so the honest state is
  ``NOT_TESTED``/``DISABLED``.

The benchmark uses a 200k-sample vectorised geometry sweep as a *proxy* for
the Monte-Carlo workload of G1/G2.  It is a timing proxy only: it produces no
scientific tolerance result.
"""

from __future__ import annotations

import json
import os
import platform
import statistics
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import numpy as np
import psutil

from optisys.geometry.coplanar import CoplanarGeometry, CoplanarSpec
from optisys.geometry.reference import ReferenceModel

_THREAD_ENV_KEYS = (
    "OMP_NUM_THREADS",
    "OPENBLAS_NUM_THREADS",
    "MKL_NUM_THREADS",
    "NUMEXPR_NUM_THREADS",
)

MC_PROXY_SAMPLES = 200_000
PARALLEL_WORKERS = (1, 2, 4, 6)
PARALLEL_REPS = 3


def pin_thread_environment() -> dict[str, str]:
    """Force single-threaded BLAS/OpenMP in this process and its children."""

    for key in _THREAD_ENV_KEYS:
        os.environ[key] = "1"
    return {key: os.environ[key] for key in _THREAD_ENV_KEYS}


def _spec_kwargs(spec: CoplanarSpec) -> dict[str, Any]:
    return asdict(spec)


def _forward_chunk(payload: tuple[dict[str, Any], np.ndarray]) -> tuple[float, int, int]:
    """Worker entry point (module level so that Windows ``spawn`` can pickle it)."""

    spec_kwargs, z_values = payload
    geometry = CoplanarGeometry(CoplanarSpec(**spec_kwargs))
    batch = geometry.forward_many(z_values)
    u_sum = float(np.nansum(batch.u_px))
    visible = int(np.count_nonzero(batch.visible))
    return u_sum, visible, int(z_values.size)


def _rss_mb() -> float:
    return psutil.Process().memory_info().rss / 1024**2


def _time_call(func: Callable[[], Any], reps: int) -> tuple[list[float], Any]:
    durations: list[float] = []
    result: Any = None
    for _ in range(reps):
        start = time.perf_counter()
        result = func()
        durations.append(time.perf_counter() - start)
    return durations, result


def _summarise(durations: list[float], n_items: int) -> dict[str, Any]:
    median = statistics.median(durations)
    return {
        "reps": len(durations),
        "median_s": median,
        "min_s": min(durations),
        "max_s": max(durations),
        "stdev_s": statistics.pstdev(durations) if len(durations) > 1 else 0.0,
        "items": n_items,
        "items_per_s": n_items / median if median > 0 else None,
    }


def _parallel_case(
    spec: CoplanarSpec,
    z_values: np.ndarray,
    workers: int,
    chunks: int,
    reps: int,
) -> dict[str, Any]:
    import multiprocessing as mp

    payloads = [
        (_spec_kwargs(spec), chunk)
        for chunk in np.array_split(z_values, chunks)
    ]
    total_items = int(z_values.size)

    if workers == 1:
        durations = []
        checksum = None
        for _ in range(reps):
            start = time.perf_counter()
            results = [_forward_chunk(item) for item in payloads]
            durations.append(time.perf_counter() - start)
            checksum = _combine(results)
        return {
            "workers": 1,
            "mode": "in_process_chunked",
            "pool_setup_s": 0.0,
            **_summarise(durations, total_items),
            "checksum": checksum,
        }

    context = mp.get_context("spawn")
    setup_start = time.perf_counter()
    executor = ProcessPoolExecutor(max_workers=workers, mp_context=context)
    durations = []
    checksum = None
    try:
        list(executor.map(_forward_chunk, payloads))  # warm-up / worker start
        setup_s = time.perf_counter() - setup_start
        for _ in range(reps):
            start = time.perf_counter()
            results = list(executor.map(_forward_chunk, payloads))
            durations.append(time.perf_counter() - start)
            checksum = _combine(results)
    finally:
        executor.shutdown(wait=True)
    summary = _summarise(durations, total_items)
    summary.update(
        {
            "workers": workers,
            "mode": "process_spawn",
            "pool_setup_s": setup_s,
            "check_consistency": checksum,
        }
    )
    return summary


def _combine(results: list[tuple[float, int, int]]) -> dict[str, float | int]:
    return {
        "u_sum": round(sum(item[0] for item in results), 9),
        "visible": sum(item[1] for item in results),
        "items": sum(item[2] for item in results),
    }


def benchmark(
    spec: CoplanarSpec,
    seed: int = 20261019,
    *,
    mc_samples: int = MC_PROXY_SAMPLES,
    workers: tuple[int, ...] = PARALLEL_WORKERS,
    parallel_reps: int = PARALLEL_REPS,
    analytic_reps: int = 200,
    reference_reps: int = 20,
    mc_reps: int = 5,
) -> dict[str, Any]:
    """Run the gate-relevant micro-benchmarks and return evidence."""

    thread_env = pin_thread_environment()
    rng = np.random.default_rng(seed)

    geometry = CoplanarGeometry(spec)
    reference = ReferenceModel(spec)

    grid = np.linspace(spec.z_min_mm, spec.z_max_mm, 41)
    theta_offsets = (-3.0, 0.0, 3.0)
    theta_grids = [
        np.linspace(spec.z_min_mm, spec.z_max_mm, 41) for _ in theta_offsets
    ]

    def analytic_workload() -> dict[str, float]:
        acc = 0.0
        for z in theta_grids:
            batch = geometry.forward_many(z)
            acc += float(np.nansum(batch.u_px))
        return {"u_sum": acc}

    def reference_workload() -> dict[str, float]:
        total = 0.0
        for z in theta_grids:
            u, _ = reference.forward(z)
            total += float(np.sum(u))
        return {"u_sum": total}

    mc_z = rng.uniform(spec.z_min_mm, spec.z_max_mm, mc_samples)

    def mc_workload() -> dict[str, float]:
        batch = geometry.forward_many(mc_z)
        return {"u_sum": float(np.nansum(batch.u_px))}

    durations_analytic, analytic_result = _time_call(analytic_workload, analytic_reps)
    durations_reference, reference_result = _time_call(reference_workload, reference_reps)
    durations_mc, mc_result = _time_call(mc_workload, mc_reps)

    rss_start = _rss_mb()
    workloads = [
        {
            "id": "analytic_forward_41x3",
            "description": "Vectorised analytic forward over 3x41 working-range points",
            "backend": "numpy",
            **_summarise(durations_analytic, 3 * grid.size),
            "rss_peak_mb": round(max(rss_start, _rss_mb()), 2),
            "result": analytic_result,
        },
        {
            "id": "reference_vector_chain_41x3",
            "description": "Independent 3x3 ray/plane solve + 3x4 matrix projection",
            "backend": "numpy/scipy",
            **_summarise(durations_reference, 3 * grid.size),
            "rss_peak_mb": round(max(rss_start, _rss_mb()), 2),
            "result": reference_result,
        },
        {
            "id": f"mc_proxy_{mc_samples}",
            "description": (
                f"Vectorised forward over {mc_samples} random depths (timing proxy only)"
            ),
            "backend": "numpy",
            **_summarise(durations_mc, mc_samples),
            "rss_peak_mb": round(max(rss_start, _rss_mb()), 2),
            "result": mc_result,
        },
    ]

    parallel_cases = []
    for workers in PARALLEL_WORKERS:
        parallel_cases.append(_parallel_case(spec, mc_z, workers, chunks=8, reps=PARALLEL_REPS))

    baseline = next(case for case in parallel_cases if case["workers"] == 1)
    for case in parallel_cases:
        case["speedup_vs_1"] = (
            baseline["median_s"] / case["median_s"] if case["median_s"] > 0 else None
        )

    best = max(parallel_cases, key=lambda case: case["speedup_vs_1"] or 0.0)
    memory = psutil.virtual_memory()
    ram_budget_gb = round(memory.total * 0.75 / 1024**3, 2)

    reference_mismatch = _compare_chain(geometry, reference, seed)

    return {
        "schema_version": "1.0",
        "gate": "G0",
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "host": {
            "platform": platform.platform(),
            "logical_cores": psutil.cpu_count(logical=True),
            "physical_cores": psutil.cpu_count(logical=False),
            "memory_total_gb": round(memory.total / 1024**3, 2),
        },
        "thread_environment": thread_env,
        "note": "All timings use single-threaded BLAS/OpenMP to avoid nested oversubscription.",
        "workloads": workloads,
        "parallel_scaling": {
            "workload": f"mc_proxy_{mc_samples}",
            "chunks": 8,
            "reps": parallel_reps,
            "cases": parallel_cases,
            "best_workers": best["workers"],
            "best_speedup_vs_1": best["speedup_vs_1"],
            "reference_consistency": reference_mismatch,
        },
        "decisions": {
            "g0_execution": "single_process_numpy",
            "g0_reason": (
                "The G0 grid is 3x41 points; one vectorised call takes tens of microseconds, "
                "far below process start-up cost.  Process pools are therefore not used for G0."
            ),
            "future_mc_workers": (
                best["workers"] if (best["speedup_vs_1"] or 0.0) >= 1.3 else 1
            ),
            "future_mc_reason": (
                f"Measured best speedup {best['speedup_vs_1']:.2f}x at {best['workers']} workers "
                f"on the 200k timing proxy; threshold for adopting multiprocessing is 1.30x."
            ),
            "gpu": "DISABLED",
            "gpu_reason": (
                "No tensor/optical workload at G0; torch is not installed. GPU is NOT_TESTED, "
                "not assumed faster."
            ),
        },
        "ram_budget_gb": ram_budget_gb,
        "not_tested": [
            "GPU (CUDA) path: no G0 tensor workload and torch is not installed",
            "Optiland ray-trace path: deferred to G2 (L1) per gate boundary",
            "Long-running Monte-Carlo tolerance workload: not part of G0",
        ],
    }


def _compare_chain(geometry: CoplanarGeometry, reference: ReferenceModel, seed: int) -> dict[str, Any]:
    """Cheap consistency guard run inside the benchmark (not a scientific gate)."""

    rng = np.random.default_rng(seed)
    z = rng.uniform(geometry.spec.z_min_mm, geometry.spec.z_max_mm, 1000)
    u_ref, _ = reference.forward(z)
    batch = geometry.forward_many(z)
    residual = float(np.max(np.abs(batch.u_px - u_ref)))
    return {
        "samples": int(z.size),
        "max_abs_u_difference_px": residual,
        "consistent": bool(residual < 1e-9),
    }


def build_compute_plan(environment: dict[str, Any], benchmark_report: dict[str, Any],
                       gate: str = "G0") -> dict[str, Any]:
    """Translate measured evidence into an explicit execution policy."""

    memory_total = environment["memory"]["total_gb"]
    memory_available = environment["memory"]["available_gb"]
    return {
        "schema_version": "1.0",
        "gate": gate,
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "hardware": {
            "cpu_model": environment["cpu"]["model"],
            "physical_cores": environment["cpu"]["physical_cores"],
            "logical_cores": environment["cpu"]["logical_cores"],
            "memory_total_gb": memory_total,
            "memory_available_gb_at_start": memory_available,
            "gpu": environment["gpu"]["devices"] if environment["gpu"]["available"] else "UNKNOWN",
            "cuda_usable": environment["cuda"]["torch"].get("cuda_available", "NOT_INSTALLED"),
        },
        "workload_classes": [
            {"class": "analytic_geometry", "backend": "numpy vectorised", "parallelism": 1,
             "reason": "tiny arrays; process overhead dominates"},
            {"class": "independent_reference", "backend": "numpy/scipy", "parallelism": 1,
             "reason": "verification-only, 123 points"},
            {"class": "image_generation_L0", "backend": "not implemented at G0",
             "parallelism": "n/a", "reason": "G1 scope"},
            {"class": "tolerance_monte_carlo", "backend": "numpy vectorised",
             "parallelism": benchmark_report["decisions"]["future_mc_workers"],
             "reason": benchmark_report["decisions"]["future_mc_reason"]},
            {"class": "ray_trace_PSF", "backend": "Optiland (optional, G2)",
             "parallelism": "not tested", "reason": "gate boundary"},
        ],
        "selected_policy": {
            "g0": "single-process NumPy, BLAS threads pinned to 1",
            "thread_env": benchmark_report["thread_environment"],
            "process_workers_for_future_mc": benchmark_report["decisions"]["future_mc_workers"],
            "gpu": "disabled",
            "spawn_safe": True,
        },
        "budget": {
            "ram_budget_gb": benchmark_report["ram_budget_gb"],
            "ram_budget_fraction": 0.75,
            "max_wall_time_s": 900,
            "max_mc_samples_without_approval": 2000,
            "note": "Larger runs require a new budget approval; see master prompt section 2.3",
        },
        "recovery": {
            "checkpointing": "not required for G0 (sub-second runs)",
            "planned": "batch checkpoints with sample IDs and RNG state at G2",
            "cache_keys": "config hash + model version + seed sequence + numeric precision",
        },
        "measured_evidence": {
            "g0_workload_median_s": benchmark_report["workloads"][0]["median_s"],
            "mc_proxy_median_s": benchmark_report["workloads"][2]["median_s"],
            "best_parallel_speedup": benchmark_report["parallel_scaling"]["best_speedup_vs_1"],
        },
        "not_tested": benchmark_report["not_tested"],
    }


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
