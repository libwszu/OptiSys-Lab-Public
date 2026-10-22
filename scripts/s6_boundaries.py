"""Run the registered S6-B focus-plane and L2-position boundary scans."""

from __future__ import annotations

import argparse
import concurrent.futures
import csv
import json
import multiprocessing as mp
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from optisys.optics.s5_reference import build_model  # noqa: E402
from optisys.optics.s6_rigid_body import LensPose, invalid_geometry_reason, trace_local  # noqa: E402
from optisys.sources.multimode_fiber import sample_multimode_fiber  # noqa: E402

RUN_ID = "20261021_024715_S6_P1"
G4 = ROOT / "runs/20261020_133555_G4_ec3e2813_0e48"
FOCUS_OFFSETS = (-60.0, -45.0, -35.0, -25.0, -15.0, -5.0, 0.0, 10.0)
L2_POSITIONS = (125.0, 130.0, 135.0, 140.0, 145.0)
N_RAYS = 4096
SEED = 8061001


def _model():
    optics = json.loads((G4 / "optics_model.json").read_text(encoding="utf-8"))
    config = yaml.safe_load((ROOT / "configs/pump976_g4_l0.yaml").read_text(encoding="utf-8-sig"))
    return build_model(optics, config)


def _weighted_quantile(values: np.ndarray, weights: np.ndarray, q: float) -> float | None:
    if values.size == 0 or weights.size != values.size:
        return None
    order = np.argsort(values, kind="mergesort")
    v, w = values[order], weights[order]
    total = float(np.sum(w))
    if total <= 0.0:
        return None
    idx = int(np.searchsorted(np.cumsum(w), q * total, side="left"))
    return float(v[min(idx, len(v) - 1)])


def _evaluate_scan(payload: tuple[Any, ...]) -> dict[str, Any]:
    (scan_id, scope, design_id, model, ids, origins, directions, weights,
     l2_pose_dz, target_z) = payload
    poses = (LensPose(), LensPose(dz_mm=float(l2_pose_dz)))
    invalid = invalid_geometry_reason(model, poses, target_z_mm=float(target_z))
    if invalid:
        return {"scan_id": scan_id, "scope": scope, "design_id": design_id,
                "target_z_mm": target_z, "geometry_status": "INVALID_GEOMETRY",
                "geometry_reason": invalid, "ray_rows": []}
    result = trace_local(model, ids, origins, directions, weights, poses,
                         target_z_mm=float(target_z), target_radius_mm=1.0)
    ray_rows = []
    plane_r: list[float] = []
    plane_w: list[float] = []
    inside_r: list[float] = []
    inside_w: list[float] = []
    for row in result.ray_rows:
        x, y = row["target_x"], row["target_y"]
        radius = None if x is None else float(np.hypot(x, y))
        ray_rows.append({"scan_id": scan_id, "scope": scope, "design_id": design_id,
                         "ray_id": row["ray_id"], "source_weight": row["source_weight"],
                         "terminal_outcome": row["terminal_outcome"],
                         "target_x_mm": x, "target_y_mm": y, "target_z_mm": row["target_z_mm"],
                         "radius_from_fixed_axis_mm": radius})
        if radius is not None:
            plane_r.append(radius); plane_w.append(float(row["source_weight"]))
            if row["terminal_outcome"] == "CAPTURED":
                inside_r.append(radius); inside_w.append(float(row["source_weight"]))
    radii = np.asarray(plane_r, dtype=float)
    plane_weights = np.asarray(plane_w, dtype=float)
    in_r = np.asarray(inside_r, dtype=float)
    in_w = np.asarray(inside_w, dtype=float)
    rms = (float(np.sqrt(np.average(radii * radii, weights=plane_weights)))
           if radii.size else None)
    metrics = {
        "scan_id": scan_id, "scope": scope, "design_id": design_id,
        "l2_principal_z_mm": 125.0 + float(l2_pose_dz),
        "l2_pose_dz_from_125_mm": float(l2_pose_dz),
        "target_z_mm": float(target_z),
        "focus_offset_from_225_mm": float(target_z) - 225.0,
        "geometry_status": "VALID_ASSUMED",
        "source_rays": int(len(ids)), "source_weight_denominator": float(np.sum(weights)),
        "captured_count": int(result.ledger["terminal_count"].get("CAPTURED", 0)),
        "plane_reacher_count": int(radii.size),
        "captured_weight": result.ledger["captured_weight"],
        "capture_fraction_input": result.ledger["capture_fraction_input"],
        "r80_all_plane_reachers_mm": _weighted_quantile(radii, plane_weights, 0.80),
        "r90_all_plane_reachers_mm": _weighted_quantile(radii, plane_weights, 0.90),
        "rms_all_plane_reachers_mm": rms,
        "conditional_r90_within_1mm_mm": _weighted_quantile(in_r, in_w, 0.90),
        "terminal_counts": json.dumps(result.ledger["terminal_count"], sort_keys=True),
        "terminal_weights": json.dumps(result.ledger["terminal_weight"], sort_keys=True),
        "ledger_status": result.ledger["status"],
        "evidence": "S6_ASSUMED_P1_BOUNDARY_DIAGNOSTIC",
    }
    return {**metrics, "ray_rows": ray_rows}


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"refusing empty evidence CSV: {path}")
    keys: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                keys.append(key); seen.add(key)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        writer.writeheader(); writer.writerows(rows)


def _focus_status(rows: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    per_design: dict[str, Any] = {}
    statuses: list[str] = []
    for design in ("baseline125", "s5_position135"):
        data = sorted((r for r in rows if r["design_id"] == design and r["geometry_status"] == "VALID_ASSUMED"),
                      key=lambda r: r["target_z_mm"])
        values = np.asarray([float(r["capture_fraction_input"]) for r in data])
        maximum = float(np.max(values))
        maxima = [i for i, value in enumerate(values) if abs(float(value) - maximum) <= 1e-15]
        plateau = maximum >= 1.0 - 1e-15 and len(maxima) > 1
        status = "PLATEAU" if plateau else "OPTIMUM_NOT_BRACKETED"
        statuses.append(status)
        per_design[design] = {"max_capture": maximum,
                              "max_target_z_mm": [data[i]["target_z_mm"] for i in maxima],
                              "grid_points": [r["target_z_mm"] for r in data],
                              "status": status}
    overall = "PLATEAU" if all(x == "PLATEAU" for x in statuses) else "OPTIMUM_NOT_BRACKETED"
    return overall, per_design


def _position_status(rows: list[dict[str, Any]]) -> tuple[str, dict[str, Any]]:
    values = [r for r in rows if r["geometry_status"] == "VALID_ASSUMED"]
    max_value = max(float(r["capture_fraction_input"]) for r in values)
    maxima = [r for r in values if abs(float(r["capture_fraction_input"]) - max_value) <= 1e-15]
    positions = [float(r["l2_principal_z_mm"]) for r in maxima]
    edge = any(abs(x - min(L2_POSITIONS)) < 1e-12 or abs(x - max(L2_POSITIONS)) < 1e-12 for x in positions)
    status = "OPTIMUM_NOT_BRACKETED" if edge else "EXPLORATORY_ONLY"
    return status, {"max_capture": max_value, "max_position_mm": positions,
                    "search_grid_mm": list(L2_POSITIONS), "status": status,
                    "note": "coarse fixed-target grid; no holdout selection or fine-grid claim"}


def _plot_focus(rows: list[dict[str, Any]], path: Path) -> None:
    fig, ax = plt.subplots(figsize=(8.5, 5.2), constrained_layout=True)
    axr = ax.twinx()
    for design, label, color, marker in (("baseline125", "L2 125 mm", "#2455a4", "o"),
                                          ("s5_position135", "L2 135 mm", "#c43d32", "s")):
        data = sorted((r for r in rows if r["design_id"] == design), key=lambda r: r["focus_offset_from_225_mm"])
        x = [float(r["focus_offset_from_225_mm"]) for r in data]
        y = [float(r["capture_fraction_input"]) for r in data]
        r90 = [float(r["r90_all_plane_reachers_mm"]) for r in data]
        ax.plot(x, y, marker=marker, color=color, linewidth=2, label=f"{label} capture")
        axr.plot(x, r90, marker=marker, color=color, linestyle="--", alpha=0.8,
                 label=f"{label} all-plane r90")
    ax.set_xlabel("固定镜片时接收平面 z 偏移（mm，相对 225 mm）")
    ax.set_ylabel("输入源权重捕获率")
    axr.set_ylabel("全部到达该面的光线 r90（mm）")
    ax.set_ylim(-0.03, 1.03); ax.grid(True, alpha=0.25)
    lines = ax.get_lines() + axr.get_lines()
    ax.legend(lines, [x.get_label() for x in lines], loc="best", fontsize=8)
    ax.set_title("S6-B1 假设 P1 焦面边界诊断（非实测）")
    fig.savefig(path, dpi=160); plt.close(fig)


def _plot_position(rows: list[dict[str, Any]], path: Path) -> None:
    data = sorted(rows, key=lambda r: r["l2_principal_z_mm"])
    x = [float(r["l2_principal_z_mm"]) for r in data]
    capture = [float(r["capture_fraction_input"]) for r in data]
    r90 = [float(r["r90_all_plane_reachers_mm"]) for r in data]
    fig, ax = plt.subplots(figsize=(8.5, 5.2), constrained_layout=True)
    axr = ax.twinx()
    ax.plot(x, capture, color="#2455a4", marker="o", linewidth=2, label="输入源权重捕获率")
    axr.plot(x, r90, color="#d47a22", marker="s", linestyle="--", linewidth=2,
             label="全平面 r90（mm）")
    ax.axvline(135.0, color="#c43d32", alpha=0.65, linestyle=":", label="S5 固定候选 135 mm")
    ax.set_xlabel("L2 主平面 z（mm）；接收平面固定在 225 mm")
    ax.set_ylabel("输入源权重捕获率"); axr.set_ylabel("全部到达该面的光线 r90（mm）")
    ax.grid(True, alpha=0.25)
    lines = ax.get_lines() + axr.get_lines()
    ax.legend(lines, [x.get_label() for x in lines], loc="best", fontsize=8)
    ax.set_title("S6-B2 L2 位置边界诊断（其它处方固定）")
    fig.savefig(path, dpi=160); plt.close(fig)


def run() -> dict[str, Any]:
    out = ROOT / "runs" / RUN_ID / "s6_b_boundaries"
    if out.exists():
        raise FileExistsError(f"refusing to overwrite S6-B output {out}")
    out.mkdir(parents=True)
    model = _model()
    rays = sample_multimode_fiber(N_RAYS, 0.105, 0.22, seed=SEED)
    source_rows = [{"ray_id": int(rays.ray_id[i]), "x0_mm": float(rays.origin_mm[i, 0]),
                    "y0_mm": float(rays.origin_mm[i, 1]), "z0_mm": float(rays.origin_mm[i, 2]),
                    "dx": float(rays.direction[i, 0]), "dy": float(rays.direction[i, 1]),
                    "dz": float(rays.direction[i, 2]), "weight": float(rays.weight[i]),
                    "seed": SEED, "distribution_id": rays.distribution_id} for i in range(N_RAYS)]
    _write_csv(out / "source_samples_8061001.csv", source_rows)

    tasks: list[tuple[Any, ...]] = []
    for design, dz in (("baseline125", 0.0), ("s5_position135", 10.0)):
        for offset in FOCUS_OFFSETS:
            z = 225.0 + offset
            tasks.append((f"focus_{design}_{offset:+g}", "focus_plane", design, model,
                          rays.ray_id, rays.origin_mm, rays.direction, rays.weight, dz, z))
    for position in L2_POSITIONS:
        dz = position - 125.0
        tasks.append((f"l2_position_{position:g}", "l2_position", "exploratory_position", model,
                      rays.ray_id, rays.origin_mm, rays.direction, rays.weight, dz, 225.0))

    for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        os.environ[key] = "1"
    results: list[dict[str, Any]] = []
    wall_start = time.perf_counter()
    with concurrent.futures.ProcessPoolExecutor(max_workers=4, mp_context=mp.get_context("spawn")) as pool:
        futures = [pool.submit(_evaluate_scan, task) for task in tasks]
        for future in futures:
            results.append(future.result(timeout=120))
    outer_wall = time.perf_counter() - wall_start
    focus_rows = [{k: v for k, v in r.items() if k != "ray_rows"}
                  for r in results if r["scope"] == "focus_plane"]
    position_rows = [{k: v for k, v in r.items() if k != "ray_rows"}
                     for r in results if r["scope"] == "l2_position"]
    all_ray_rows = [ray for result in results for ray in result.get("ray_rows", [])]
    _write_csv(out / "focus_plane_extended.csv", focus_rows)
    _write_csv(out / "l2_position_extended.csv", position_rows)
    _write_csv(out / "boundary_ray_endpoints.csv", all_ray_rows)
    _plot_focus(focus_rows, out / "s6_focus_boundary.png")
    _plot_position(position_rows, out / "s6_l2_position_boundary.png")

    focus_status, focus_details = _focus_status(focus_rows)
    position_status, position_details = _position_status(position_rows)
    valid = [r for r in results if r["geometry_status"] == "VALID_ASSUMED"]
    all_ledger_pass = all(r["ledger_status"] == "PASS" for r in valid)
    summary = {
        "schema": "optisys.s6.boundary_analysis/1", "run_id": RUN_ID,
        "S6_B_FOCUS_STATUS": focus_status,
        "S6_B_L2_POSITION_STATUS": position_status,
        "focus_per_design": focus_details, "l2_position": position_details,
        "seed": SEED, "rays_per_scan": N_RAYS,
        "focus_offsets_mm": list(FOCUS_OFFSETS), "l2_positions_mm": list(L2_POSITIONS),
        "target": {"z_mm": 225.0, "active_radius_mm": 1.0,
                   "policy": "fixed world plane for L2 scan; scanned as a separate axis for focus scan"},
        "fixed_lens_policy_for_focus": "both lenses fixed at their registered 125/135 mm geometries",
        "denominator": "all input ray source weights; blocked, outside, failed and no-intersection remain in denominator",
        "radius_metrics": "r80/r90/RMS over every ray reaching the target plane, including outside the 1 mm circle; conditional r90 separately uses only captured rays",
        "valid_geometry_points": sum(r["geometry_status"] == "VALID_ASSUMED" for r in results),
        "invalid_geometry_points": sum(r["geometry_status"] != "VALID_ASSUMED" for r in results),
        "all_ledgers_pass": all_ledger_pass,
        "outer_wall_s": outer_wall,
        "outputs": ["focus_plane_extended.csv", "l2_position_extended.csv",
                    "boundary_ray_endpoints.csv", "s6_focus_boundary.png", "s6_l2_position_boundary.png"],
        "selection_limit": "No new candidate selected. 135 mm remains the S6-C fixed comparator; no boundary scan point is called globally optimal.",
        "finished_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (out / "boundary_analysis.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                                                   encoding="utf-8")
    contract = """# Ray denominator contract for S6-B\n\nCapture fraction is captured source weight divided by the weight of every input ray. Aperture blocks, outside-target rays, no-intersection, TIR, invalid source, and trace failure remain in that denominator.\n\n`r80_all_plane_reachers_mm`, `r90_all_plane_reachers_mm`, and `rms_all_plane_reachers_mm` use every ray that reaches the selected world-z plane, even when it falls outside the 1 mm active circle; their radii are measured from the fixed world-axis center (x=0,y=0). `conditional_r90_within_1mm_mm` is a separate statistic over captured rays only. It is not a replacement for all-plane focus quality. Source weights remain dimensionless; absolute power is UNKNOWN.\n\nThe focus scan changes only the target plane and keeps both lenses fixed. The L2 scan changes only L2 axial position and keeps target z=225 mm. These are separate exploratory axes.\n"""
    (out / "ray_denominator_contract.md").write_text(contract, encoding="utf-8")
    print(json.dumps({"S6_B_FOCUS_STATUS": focus_status,
                      "S6_B_L2_POSITION_STATUS": position_status,
                      "valid_geometry_points": summary["valid_geometry_points"],
                      "invalid_geometry_points": summary["invalid_geometry_points"],
                      "all_ledgers_pass": all_ledger_pass,
                      "focus_maxima": focus_details,
                      "position_maximum": position_details,
                      "outer_wall_s": outer_wall}, ensure_ascii=False, indent=2))
    return summary


def main() -> int:
    argparse.ArgumentParser(description=__doc__).parse_args()
    result = run()
    return 0 if result["invalid_geometry_points"] == 0 and result["all_ledgers_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
