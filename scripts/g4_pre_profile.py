"""PRE-only Optiland workload profile for G4, before science runs.

Profiles real 512-ray, two-singlet traces for 1/2/4/6 workers. The sample
metrics are discarded; this file only reports timing, process count, and peak
RSS so the compute budget can be checked before the registered analysis.
"""

from __future__ import annotations

import concurrent.futures
from dataclasses import replace
import json
import os
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

for _key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_key] = "1"

ROOT = Path(__file__).resolve().parents[1]


def _profile_one(task: tuple[str, str, float, int]) -> dict[str, Any]:
    config_name, condition, na, seed = task
    from optisys.config_g4 import load_pump976_config
    from optisys.optics.pump_optiland import OptilandPumpTracer
    from optisys.sources.multimode_fiber import sample_multimode_fiber

    config = load_pump976_config(ROOT / config_name)
    beamline = config.beamline
    if condition == "aperture_offset_bad":
        beamline = replace(
            beamline,
            l1=replace(beamline.l1, aperture_diameter_mm=8.0),
            l2=replace(beamline.l2, aperture_diameter_mm=8.0, z_mm=beamline.l2.z_mm + 1.0),
        )
    rays = sample_multimode_fiber(
        512, config.core_diameter_mm, na,
        output_index=config.output_index, seed=seed,
        angular_distribution="uniform_solid_angle",
    )
    tracer = OptilandPumpTracer(beamline, wavelength_nm=config.wavelength_nm)
    started = time.perf_counter()
    result = tracer.trace(rays)
    wall = time.perf_counter() - started
    return {"condition": condition, "na": na, "n_rays": rays.n_rays,
            "status": result.status, "wall_s": round(wall, 6)}


def _peak_rss_mb(stop: threading.Event, peak: list[float]) -> None:
    import psutil

    parent = psutil.Process()
    while not stop.is_set():
        total = 0
        try:
            processes = [parent, *parent.children(recursive=True)]
            for process in processes:
                try:
                    total += process.memory_info().rss
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            peak[0] = max(peak[0], total / 1024**2)
        except psutil.Error:
            pass
        stop.wait(0.05)


def run_profile() -> dict[str, Any]:
    from optisys.runtime.environment import collect_environment

    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    configs = ["configs/pump976_g4_l0.yaml", "configs/pump976_g4_l1.yaml"]
    tasks = []
    seed = 976100
    for repeat in range(3):
        for config_name, design in ((configs[0], "baseline"),
                                    (configs[1], "engineering_candidate")):
            for na in (0.05, 0.22):
                tasks.append((config_name, design, na, seed + repeat))
        for na in (0.05, 0.22):
            tasks.append((configs[0], "aperture_offset_bad", na, seed + repeat))
    groups = []
    for workers in (1, 2, 4, 6):
        stop = threading.Event()
        peak = [0.0]
        sampler = threading.Thread(target=_peak_rss_mb, args=(stop, peak), daemon=True)
        sampler.start()
        start = time.perf_counter()
        with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as pool:
            results = list(pool.map(_profile_one, tasks))
        wall = time.perf_counter() - start
        stop.set()
        sampler.join(timeout=2.0)
        groups.append({
            "workers": workers,
            "n_tasks": len(tasks),
            "total_rays": len(tasks) * 512,
            "wall_s": round(wall, 3),
            "throughput_rays_s": round(len(tasks) * 512 / wall, 2),
            "peak_process_tree_rss_mb": round(peak[0], 1),
            "task_wall_s": results,
            "all_trace_calls_returned": all(r["status"] in ("OK", "TRACE_FAILED") for r in results),
        })
    return {
        "schema": "g4.pre_profile/1",
        "purpose": "PRE performance profile only; numerical metrics discarded and not used as scientific G4 results",
        "started_at_utc": started,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_rays_per_trace": 512,
        "conditions": ["baseline/candidate/aperture-offset bad case", "NA 0.05/0.22", "3 repeat seeds"],
        "thread_environment": {k: os.environ.get(k) for k in
                               ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")},
        "environment": collect_environment(ROOT),
        "profiles": groups,
    }


def main() -> int:
    result = run_profile()
    out = ROOT / "artifacts" / "g4" / "pre" / "compute_profile.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for row in result["profiles"]:
        print(json.dumps({k: row[k] for k in ("workers", "n_tasks", "total_rays", "wall_s",
                                               "throughput_rays_s", "peak_process_tree_rss_mb",
                                               "all_trace_calls_returned")}, ensure_ascii=False))
    print(f"PROFILE_JSON: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
