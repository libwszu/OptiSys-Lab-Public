"""Run the preregistered S5-A independent sphere/Snell replay and comparison."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import time
from dataclasses import replace
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

for _name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_name] = "1"

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from optisys.config_g4 import load_pump976_config
from optisys.optics.pump_optiland import OptilandPumpTracer
from optisys.optics.s5_reference import build_model, lens_geometry_rows, trace_rays
from optisys.sources.multimode_fiber import RayBundle
from optiland.rays import RealRays

_G4_CURRENT = ROOT / "runs/20261020_133555_G4_ec3e2813_0e48"
_G4_PACKAGED = ROOT / "baseline_g4"
G4 = _G4_PACKAGED if (_G4_PACKAGED / "source_samples.csv").is_file() else _G4_CURRENT
S5 = ROOT / "runs/20261020_210201_S5_HNA"
SURFACE_IDS = ("L1_FRONT", "L1_REAR", "L2_FRONT", "L2_REAR")
ANGLE_EDGES = (0.0, 3.0, 6.0, 9.0, 11.0, 12.7099)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        raise ValueError(f"refusing to write empty evidence CSV: {path}")
    fields = list(dict.fromkeys(key for row in rows for key in row.keys()))
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _read_source(limit: int | None = None) -> dict[str, np.ndarray]:
    with (G4 / "source_samples.csv").open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    if limit is not None and limit < len(rows):
        # Deterministic, broad angular/radial support for an API smoke only.
        indices = np.linspace(0, len(rows) - 1, limit, dtype=int)
        rows = [rows[i] for i in indices]
    return {
        "ray_id": np.asarray([int(row["ray_id"]) for row in rows], dtype=np.int64),
        "origin": np.asarray([[float(row[k]) for k in ("x0_mm", "y0_mm", "z0_mm")] for row in rows]),
        "direction": np.asarray([[float(row[k]) for k in ("dx", "dy", "dz")] for row in rows]),
        "weight": np.asarray([float(row["weight"]) for row in rows]),
        "source_seed": np.asarray([int(row["seed"]) for row in rows], dtype=np.int64),
    }


def _run_optiland(design_id: str, rays: dict[str, np.ndarray],
                  target_z_mm: float | None = None) -> dict[str, Any]:
    cfg_path = ROOT / "configs/pump976_g4_l0.yaml" if design_id == "baseline" else ROOT / "configs/pump976_g4_l1.yaml"
    config = load_pump976_config(cfg_path)
    beamline = config.beamline if target_z_mm is None else replace(config.beamline,
                                                                   target_z_mm=float(target_z_mm))
    tracer = OptilandPumpTracer(beamline, wavelength_nm=config.wavelength_nm,
                                lens_thickness_mm=2.0, material="N-BK7")
    optic = tracer._build_optiland()
    z_origin = float(tracer.lens_models[0]["front_vertex_z_mm"])
    real = RealRays(
        rays["origin"][:, 0], rays["origin"][:, 1], rays["origin"][:, 2] - z_origin,
        rays["direction"][:, 0], rays["direction"][:, 1], rays["direction"][:, 2],
        intensity=rays["weight"], wavelength=np.full(len(rays["ray_id"]), config.wavelength_nm / 1000.0),
    )
    output = optic.surfaces.trace(real, record=True)
    data = {}
    for name in ("x", "y", "z", "L", "M", "N", "intensity"):
        values = np.asarray(getattr(optic.surfaces, name), dtype=float)
        if values.ndim != 2 or values.shape[1] != len(rays["ray_id"]):
            raise RuntimeError(f"unexpected Optiland {name} snapshot shape {values.shape}")
        data[name] = values
    if data["x"].shape[0] < 6 or data["intensity"].shape[0] < 6:
        raise RuntimeError("Optiland trace did not record the expected six surfaces")
    data["z_world"] = data["z"].copy()
    data["z_world"][1:5] += z_origin
    data["z_world"][5] += z_origin
    data["refractive_indices"] = np.asarray(optic.surfaces.n(config.wavelength_nm / 1000.0), dtype=float).tolist()
    data["output"] = output
    data["lens_models"] = tracer.lens_models
    data["config"] = config
    data["z_origin_mm"] = z_origin
    return data


def _angle_group(theta: float) -> str:
    for i, (lo, hi) in enumerate(zip(ANGLE_EDGES[:-1], ANGLE_EDGES[1:], strict=True)):
        if lo <= theta < hi or (i == len(ANGLE_EDGES) - 2 and theta <= hi):
            return f"{lo:g}-{hi:g}deg"
    return "OUTSIDE_REGISTERED_ANGLE_RANGE"


def _compare_surface_rows(
    independent: list[dict[str, Any]], opti: dict[str, Any], rays: dict[str, np.ndarray],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    out_rows: list[dict[str, Any]] = []
    n = len(rays["ray_id"])
    stats = defaultdict(list)
    status_counts = Counter()
    id_to_col = {int(ray_id): i for i, ray_id in enumerate(rays["ray_id"])}
    for row in independent:
        sid = row["surface_id"]
        surface_num = SURFACE_IDS.index(sid) + 1
        j = id_to_col[int(row["ray_id"])]
        ref_status = str(row["status"])
        op_intensity = float(opti["intensity"][surface_num, j])
        op_pos = np.array([opti["x"][surface_num, j], opti["y"][surface_num, j],
                           opti["z_world"][surface_num, j]], dtype=float)
        op_dir = np.array([opti["L"][surface_num, j], opti["M"][surface_num, j],
                           opti["N"][surface_num, j]], dtype=float)
        rec = dict(row)
        rec["design_id"] = opti["config"].design_id
        rec["angle_bin"] = _angle_group(float(np.rad2deg(np.arccos(
            np.clip(rays["direction"][j, 2], -1.0, 1.0)))))
        rec["optiland_intensity_after_surface"] = op_intensity
        rec["optiland_passed_surface"] = bool(np.isfinite(op_intensity) and op_intensity > 0.0)
        rec["optiland_hit_x_mm"] = float(op_pos[0]) if np.all(np.isfinite(op_pos)) else None
        rec["optiland_hit_y_mm"] = float(op_pos[1]) if np.all(np.isfinite(op_pos)) else None
        rec["optiland_hit_z_world_mm"] = float(op_pos[2]) if np.all(np.isfinite(op_pos)) else None
        rec["optiland_exit_dx"] = float(op_dir[0]) if np.all(np.isfinite(op_dir)) else None
        rec["optiland_exit_dy"] = float(op_dir[1]) if np.all(np.isfinite(op_dir)) else None
        rec["optiland_exit_dz"] = float(op_dir[2]) if np.all(np.isfinite(op_dir)) else None
        rec["optiland_record_status"] = "FINITE" if np.all(np.isfinite(op_pos)) else "NONFINITE"
        pos_delta = np.nan
        dir_delta = np.nan
        if ref_status in ("PASS", "APERTURE_BLOCKED_L1", "APERTURE_BLOCKED_L2") and np.all(np.isfinite(op_pos)):
            ref_pos = np.array([row["hit_x_mm"], row["hit_y_mm"], row["hit_z_mm"]], dtype=float)
            pos_delta = float(np.max(np.abs(ref_pos - op_pos)))
            rec["surface_coordinate_delta_max_mm"] = pos_delta
            if ref_status == "PASS" and np.all(np.isfinite(op_dir)):
                ref_dir = np.array([row["outgoing_dx"], row["outgoing_dy"], row["outgoing_dz"]], dtype=float)
                dir_delta = float(np.max(np.abs(ref_dir - op_dir)))
                rec["surface_exit_direction_delta_max"] = dir_delta
            else:
                rec["surface_exit_direction_delta_max"] = None
        else:
            rec["surface_coordinate_delta_max_mm"] = None
            rec["surface_exit_direction_delta_max"] = None

        if ref_status == "PASS":
            classification_match = np.isfinite(op_intensity) and op_intensity > 0.0
        elif ref_status in ("APERTURE_BLOCKED_L1", "APERTURE_BLOCKED_L2"):
            classification_match = np.isfinite(op_intensity) and op_intensity <= 0.0
        elif ref_status.startswith("NOT_REACHED_AFTER_"):
            classification_match = True  # Optiland still records dead rays downstream.
        else:
            classification_match = False
        rec["surface_classification_match"] = bool(classification_match)
        status_counts[(sid, ref_status, bool(classification_match))] += 1
        if np.isfinite(pos_delta):
            stats[(sid, rec["angle_bin"], "position")].append(pos_delta)
        if np.isfinite(dir_delta):
            stats[(sid, rec["angle_bin"], "direction")].append(dir_delta)
        out_rows.append(rec)

    summary = []
    for (sid, group, metric), values in sorted(stats.items()):
        a = np.asarray(values, dtype=float)
        summary.append({
            "design_id": opti["config"].design_id, "surface_id": sid,
            "angle_bin": group, "metric": metric, "n_compared": int(a.size),
            "max_absolute_delta": float(np.max(a)),
            "p50_absolute_delta": float(np.percentile(a, 50)),
            "p95_absolute_delta": float(np.percentile(a, 95)),
            "p99_absolute_delta": float(np.percentile(a, 99)),
            "tolerance": 1e-8 if metric == "position" else 1e-9,
            "within_tolerance": bool(np.max(a) <= (1e-8 if metric == "position" else 1e-9)),
        })
    match_bad = sum(count for (_, _, match), count in status_counts.items() if not match)
    return out_rows, {"group_summaries": summary, "classification_mismatches": match_bad,
                      "surface_status_counts": {f"{k[0]}|{k[1]}|match={k[2]}": v for k, v in status_counts.items()}}


def _map_terminal(g4_status: str, blocked: str) -> str:
    if blocked == "L1":
        return "APERTURE_BLOCKED_L1"
    if blocked == "L2":
        return "APERTURE_BLOCKED_L2"
    if blocked == "TRACE":
        return "TRACE_FAILED"
    if g4_status == "OK":
        return "CAPTURED"
    if g4_status == "OUTSIDE_TARGET":
        return "OUTSIDE_TARGET"
    if g4_status == "TRACE_FAILED":
        return "TRACE_FAILED"
    if g4_status == "NO_INTERSECTION":
        return "NO_INTERSECTION"
    return g4_status


def _read_g4_rows(design_id: str) -> dict[int, dict[str, str]]:
    with (G4 / "raytrace_reference.csv").open(newline="", encoding="utf-8") as f:
        rows = csv.DictReader(f)
        return {int(r["ray_id"]): r for r in rows
                if r["design_id"] == design_id and r["angular_case"] == "NA_0.22"}


def _compare_terminal(ref_rays: list[dict[str, Any]], opti: dict[str, Any],
                      g4_rows: dict[int, dict[str, str]], rays: dict[str, np.ndarray]) -> dict[str, Any]:
    mismatches = []
    coordinate = []
    exit_direction = []
    by_id = {int(r["ray_id"]): r for r in ref_rays}
    for j, ray_id in enumerate(rays["ray_id"]):
        ray_id = int(ray_id)
        rr = by_id[ray_id]
        gr = g4_rows[ray_id]
        g4_terminal = _map_terminal(gr["p1_status"], gr.get("p1_blocked_at", ""))
        if rr["terminal_outcome"] != g4_terminal:
            mismatches.append({"ray_id": ray_id, "reference": rr["terminal_outcome"], "g4": g4_terminal})
        if rr["target_x_mm"] is not None and rr["target_y_mm"] is not None:
            g4xy = np.array([float(gr["p1_x_mm"]), float(gr["p1_y_mm"])])
            refxy = np.array([rr["target_x_mm"], rr["target_y_mm"]])
            coordinate.append(float(np.max(np.abs(g4xy - refxy))))
            optxy = np.array([opti["x"][5, j], opti["y"][5, j]])
            if np.all(np.isfinite(optxy)):
                coordinate.append(float(np.max(np.abs(optxy - refxy))))
            if rr["exit_dx"] is not None:
                od = np.array([opti[k][5, j] for k in ("L", "M", "N")])
                rd = np.array([rr["exit_dx"], rr["exit_dy"], rr["exit_dz"]])
                if np.all(np.isfinite(od)):
                    exit_direction.append(float(np.max(np.abs(od - rd))))
    return {
        "n_rays": len(ref_rays), "terminal_mismatch_count": len(mismatches),
        "terminal_mismatch_examples": mismatches[:20],
        "max_g4_or_optiland_target_delta_mm": float(max(coordinate)) if coordinate else None,
        "max_target_direction_delta": float(max(exit_direction)) if exit_direction else None,
        "target_coordinate_within_tolerance": bool(coordinate and max(coordinate) <= 1e-6),
        "target_direction_within_tolerance": bool(exit_direction and max(exit_direction) <= 1e-9),
    }


def _run(limit: int | None, output_dir: Path) -> dict[str, Any]:
    rays = _read_source(limit)
    model_json = json.loads((G4 / "optics_model.json").read_text(encoding="utf-8"))
    all_surfaces: list[dict[str, Any]] = []
    all_rays: list[dict[str, Any]] = []
    all_deltas: list[dict[str, Any]] = []
    design_results = []
    geometry = []
    for design_id, cfg_name in (("baseline", "pump976_g4_l0.yaml"),
                                ("engineering_candidate", "pump976_g4_l1.yaml")):
        config = yaml.safe_load((ROOT / "configs" / cfg_name).read_text(encoding="utf-8"))
        model = build_model(model_json, config)
        start = time.perf_counter()
        surface_rows, ray_rows, ledger = trace_rays(
            model, rays["ray_id"], rays["origin"], rays["direction"], rays["weight"]
        )
        independent_wall = time.perf_counter() - start
        opti = _run_optiland(design_id, rays)
        for row in surface_rows:
            row["design_id"] = design_id
        for row in ray_rows:
            row["design_id"] = design_id
        compared, surface_stats = _compare_surface_rows(surface_rows, opti, rays)
        terminal_stats = _compare_terminal(ray_rows, opti, _read_g4_rows(design_id), rays)
        all_surfaces.extend(compared)
        all_rays.extend(ray_rows)
        all_deltas.extend(surface_stats["group_summaries"])
        geometry.extend(lens_geometry_rows(model))
        design_results.append({
            "design_id": design_id, "n_rays": len(ray_rows), "independent_wall_s": independent_wall,
            "ledger": ledger, "surface_classification_mismatches": surface_stats["classification_mismatches"],
            "surface_status_counts": surface_stats["surface_status_counts"],
            "surface_delta_summaries": surface_stats["group_summaries"],
            "terminal_comparison": terminal_stats,
            "optiland_surface_refractive_indices": opti["refractive_indices"],
            "expected_n_bk7_976": model.refractive_index,
        })

    coord_values = [float(r["surface_coordinate_delta_max_mm"]) for r in all_surfaces
                    if r["surface_coordinate_delta_max_mm"] is not None]
    dir_values = [float(r["surface_exit_direction_delta_max"]) for r in all_surfaces
                  if r["surface_exit_direction_delta_max"] is not None]
    ordinary = [r for r in all_surfaces if r["status"] == "PASS"]
    ordinary_breaches = [r for r in ordinary if not r["surface_classification_match"]
                         or (r["surface_coordinate_delta_max_mm"] is not None
                             and r["surface_coordinate_delta_max_mm"] > 1e-8)
                         or (r["surface_exit_direction_delta_max"] is not None
                             and r["surface_exit_direction_delta_max"] > 1e-9)]
    terminal_mismatches = sum(r["terminal_comparison"]["terminal_mismatch_count"] for r in design_results)
    ledger_ok = all(r["ledger"]["status"] == "PASS" for r in design_results)
    surface_class_ok = all(r["surface_classification_mismatches"] == 0 for r in design_results)
    target_ok = all(r["terminal_comparison"]["target_coordinate_within_tolerance"] for r in design_results)
    full_sample = limit is None
    status = "PASS" if full_sample and ledger_ok and surface_class_ok and not ordinary_breaches \
        and terminal_mismatches == 0 and target_ok else "QUALIFIED"
    verdict = {
        "schema": "optisys.s5.full_na_verdict/1", "run_id": "20261020_210201_S5_HNA",
        "status": status if full_sample else "API_SMOKE_ONLY",
        "scope": "P1 assumed centered N-BK7 two-singlet model; 976 nm; source absolute power unknown",
        "sample_mode": "full_G4_source" if full_sample else "development_smoke_subset_not_scientific_result",
        "n_rays_per_design": len(rays["ray_id"]), "designs": design_results,
        "surface_row_count": len(all_surfaces), "ray_row_count": len(all_rays),
        "surface_coord_delta_max_mm": max(coord_values) if coord_values else None,
        "surface_exit_direction_delta_max": max(dir_values) if dir_values else None,
        "ordinary_surface_tolerance_breaches": len(ordinary_breaches),
        "ledger_closed": ledger_ok, "surface_classification_closed": surface_class_ok,
        "target_comparison_within_tolerance": target_ok,
        "terminal_mismatch_count": terminal_mismatches,
        "numerical_tolerances": {"surface_coordinate_mm": 1e-8,
                                 "surface_direction": 1e-9, "target_coordinate_mm": 1e-6},
        "evidence": "SIMULATED_ASSUMED_MODEL",
    }
    if full_sample:
        _write_csv(output_dir / "full_na_surface_reference.csv", all_surfaces)
        _write_csv(output_dir / "full_na_ray_reference.csv", all_rays)
        _write_csv(output_dir / "surface_level_ray_deltas.csv", all_deltas)
        _write_csv(output_dir / "lens_geometry_feasibility.csv", geometry)
        (output_dir / "full_na_verdict.json").write_text(json.dumps(verdict, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (output_dir / "surface_geometry.json").write_text(json.dumps({
            "schema": "optisys.s5.surface_geometry/1", "run_id": "20261020_210201_S5_HNA",
            "material_id": "N-BK7", "wavelength_nm": 976.0, "designs": design_results,
            "lens_geometry": geometry, "coordinates": "global z mm; Optiland physical-face coordinates translated from its L1-front local origin",
            "evidence": "DERIVED_FROM_ASSUMED_G4_MODEL",
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    return verdict


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=None,
                        help="development-only stratified subset; never use its output as formal evidence")
    parser.add_argument("--output-dir", type=Path, default=S5)
    args = parser.parse_args()
    if args.limit is not None and args.limit <= 0:
        parser.error("--limit must be positive")
    result = _run(args.limit, args.output_dir)
    return 0 if result["status"] in ("PASS", "API_SMOKE_ONLY") else 1


if __name__ == "__main__":
    raise SystemExit(main())
