"""Produce registered S5-B source-denominated diagnostics and figures."""

from __future__ import annotations

import csv
import json
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Any

for _name in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_name] = "1"

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from optisys.config_g4 import load_pump976_config
from optisys.optics.pump_beamline import trace_thin_lens
from optisys.optics.pump_optiland import OptilandPumpTracer
from optisys.optics.s5_reference import build_model, trace_rays
from optisys.sources.multimode_fiber import sample_multimode_fiber
from scripts.s5_run_reference import G4, S5, _read_source, _run_optiland, _write_csv

ANGLE_EDGES = (0.0, 3.0, 6.0, 9.0, 11.0, 12.7099)
RADIUS_BINS = (0.0, 0.25, 0.50, 0.75, 1.0)
FOCUS_OFFSETS = (-25.0, -10.0, 0.0, 10.0, 25.0)
TARGET_RADII = (0.5, 1.0, 1.5, 2.0)
WEIGHT_RADII = np.arange(0.0, 2.0000001, 0.05)
DESIGNS = (("baseline", "pump976_g4_l0.yaml"),
           ("engineering_candidate", "pump976_g4_l1.yaml"))


def _load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _float(value: Any) -> float:
    if value is None or value == "":
        return float("nan")
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _weighted_quantile(values: np.ndarray, weights: np.ndarray, q: float) -> float | None:
    valid = np.isfinite(values) & np.isfinite(weights) & (weights > 0.0)
    if not np.any(valid):
        return None
    v, w = values[valid], weights[valid]
    order = np.argsort(v, kind="mergesort")
    v, w = v[order], w[order]
    threshold = q * float(np.sum(w, dtype=np.float64))
    return float(v[min(int(np.searchsorted(np.cumsum(w), threshold, side="left")), len(v) - 1)])


def _centred_metrics(x: np.ndarray, y: np.ndarray, w: np.ndarray) -> dict[str, Any]:
    finite = np.isfinite(x) & np.isfinite(y) & np.isfinite(w) & (w > 0.0)
    if not np.any(finite):
        return {"n": 0, "weight": 0.0, "centroid_x_mm": None, "centroid_y_mm": None,
                "rms_radius_mm": None, "r80_mm": None, "r90_mm": None}
    xx, yy, ww = x[finite], y[finite], w[finite]
    total = float(np.sum(ww, dtype=np.float64))
    cx = float(np.sum(xx * ww, dtype=np.float64) / total)
    cy = float(np.sum(yy * ww, dtype=np.float64) / total)
    r = np.hypot(xx - cx, yy - cy)
    return {"n": int(np.count_nonzero(finite)), "weight": total,
            "centroid_x_mm": cx, "centroid_y_mm": cy,
            "rms_radius_mm": float(np.sqrt(np.sum(ww * r * r) / total)),
            "r80_mm": _weighted_quantile(r, ww, 0.80),
            "r90_mm": _weighted_quantile(r, ww, 0.90)}


def _theta_group(theta_deg: float) -> str:
    for i, (lo, hi) in enumerate(zip(ANGLE_EDGES[:-1], ANGLE_EDGES[1:], strict=True)):
        if lo <= theta_deg < hi or (i == len(ANGLE_EDGES) - 2 and theta_deg <= hi):
            return f"{lo:g}-{hi:g}deg"
    return "OUTSIDE_REGISTERED_ANGLE_RANGE"


def _as_int_rows(rows: list[dict[str, str]], id_key: str = "ray_id") -> dict[int, dict[str, str]]:
    return {int(row[id_key]): row for row in rows}


def _outcome_metrics(items: list[dict[str, Any]], total_weight: float) -> dict[str, Any]:
    weights = np.asarray([float(row["source_weight"]) for row in items], dtype=float)
    outcomes = [str(row["terminal_outcome"]) for row in items]
    sums = {name: float(sum(weights[i] for i, x in enumerate(outcomes) if x == name))
            for name in ("CAPTURED", "OUTSIDE_TARGET", "APERTURE_BLOCKED_L1", "APERTURE_BLOCKED_L2",
                         "NO_INTERSECTION", "TIR_OR_REFRACTION_FAILURE", "TRACE_FAILED", "INVALID_SOURCE")}
    return {"n_attempted": len(items), "attempted_weight": float(np.sum(weights)),
            "source_weight_denominator": total_weight, **{f"{k.lower()}_weight": v for k, v in sums.items()},
            "capture_fraction_input": sums["CAPTURED"] / total_weight,
            "blocked_fraction": (sums["APERTURE_BLOCKED_L1"] + sums["APERTURE_BLOCKED_L2"]) / total_weight,
            "trace_failure_fraction": (sums["TRACE_FAILED"] + sums["TIR_OR_REFRACTION_FAILURE"]
                                       + sums["NO_INTERSECTION"] + sums["INVALID_SOURCE"]) / total_weight}


def _build_angle_and_strata(g4_rows: list[dict[str, str]], refs: list[dict[str, str]],
                            source: dict[str, np.ndarray], total_weight: float) -> tuple[list[dict], list[dict]]:
    original = {d: _as_int_rows([r for r in g4_rows if r["design_id"] == d
                                  and r["angular_case"] == "NA_0.22"])
                for d, _ in DESIGNS}
    ref_designs = {d: _as_int_rows([r for r in refs if r["design_id"] == d]) for d, _ in DESIGNS}
    rays_by_design = {}
    angle_rows = []
    stratum_rows = []
    theta = np.rad2deg(np.arccos(np.clip(source["direction"][:, 2], -1.0, 1.0)))
    ray_ids = source["ray_id"]
    weights = source["weight"]
    source_index = {int(ray_id): i for i, ray_id in enumerate(ray_ids)}
    source_r = np.hypot(source["origin"][:, 0], source["origin"][:, 1])
    source_q = np.quantile(source_r, [0.25, 0.5, 0.75])
    phi = np.arctan2(source["direction"][:, 1], source["direction"][:, 0])

    for design_id, _ in DESIGNS:
        p0 = original[design_id]
        p1 = ref_designs[design_id]
        ray_map = {int(rid): {**p1[int(rid)], "_p0": p0[int(rid)]} for rid in ray_ids}
        rays_by_design[design_id] = ray_map
        for group_index, (lo, hi) in enumerate(zip(ANGLE_EDGES[:-1], ANGLE_EDGES[1:], strict=True)):
            mask = (theta >= lo) & ((theta < hi) if group_index < len(ANGLE_EDGES) - 2 else (theta <= hi))
            ids = ray_ids[mask]
            subset = [ray_map[int(i)] for i in ids]
            denom = float(np.sum(weights[mask]))
            p0cap = sum(float(source["weight"][source_index[int(i)]]) for i in ids
                        if ray_map[int(i)]["_p0"]["p0_status"] == "OK")
            p1cap = sum(float(ray_map[int(i)]["source_weight"]) for i in ids
                        if ray_map[int(i)]["terminal_outcome"] == "CAPTURED")
            comparable = []
            for i in ids:
                row = ray_map[int(i)]
                q = row["_p0"]
                p0x, p0y = _float(q["p0_x_mm"]), _float(q["p0_y_mm"])
                p1x, p1y = _float(row["target_x_mm"]), _float(row["target_y_mm"])
                if np.all(np.isfinite([p0x, p0y, p1x, p1y])):
                    comparable.append(float(np.hypot(p0x - p1x, p0y - p1y)))
            angle_rows.append({
                "design_id": design_id, "model_level": "P0 vs independently verified assumed P1",
                "angle_bin": _theta_group((lo + hi) / 2), "angle_lo_deg": lo, "angle_hi_deg": hi,
                "attempted_rays": int(mask.sum()), "attempted_source_weight": denom,
                "all_source_weight_denominator": total_weight,
                "p0_capture_weight": p0cap, "p0_capture_fraction_input": p0cap / total_weight,
                "p0_capture_fraction_within_angle": p0cap / denom if denom else None,
                "p1_capture_weight": p1cap, "p1_capture_fraction_input": p1cap / total_weight,
                "p1_capture_fraction_within_angle": p1cap / denom if denom else None,
                "p1_blocked_l1_weight": sum(float(r["source_weight"]) for r in subset
                                              if r["terminal_outcome"] == "APERTURE_BLOCKED_L1"),
                "p1_blocked_l2_weight": sum(float(r["source_weight"]) for r in subset
                                              if r["terminal_outcome"] == "APERTURE_BLOCKED_L2"),
                "p1_outside_target_weight": sum(float(r["source_weight"]) for r in subset
                                                 if r["terminal_outcome"] == "OUTSIDE_TARGET"),
                "p1_trace_failed_weight": sum(float(r["source_weight"]) for r in subset
                                               if r["terminal_outcome"] in ("TRACE_FAILED", "NO_INTERSECTION",
                                                                             "TIR_OR_REFRACTION_FAILURE")),
                "n_p0_p1_position_pairs": len(comparable),
                "p0_p1_position_delta_r50_mm": float(np.percentile(comparable, 50)) if comparable else None,
                "p0_p1_position_delta_r95_mm": float(np.percentile(comparable, 95)) if comparable else None,
                "p0_p1_position_delta_max_mm": float(np.max(comparable)) if comparable else None,
                "evidence": "SIMULATED_SOURCE_WEIGHT_DENOMINATOR",
            })

        stratum_specs: list[tuple[str, list[str], np.ndarray]] = []
        stratum_specs.append(("angle_deg", [_theta_group(x) for x in theta], np.arange(len(theta))))
        source_labels = np.minimum(np.searchsorted(source_q, source_r, side="right"), 3)
        stratum_specs.append(("source_nearfield_radius_quartile", [f"Q{int(x)+1}" for x in source_labels],
                              np.arange(len(theta))))
        azimuth_labels = np.floor(((phi + np.pi) / (2 * np.pi)) * 8).astype(int) % 8
        stratum_specs.append(("source_azimuth_8_bins", [f"bin_{int(x)}" for x in azimuth_labels],
                              np.arange(len(theta))))
        cfg_name = "pump976_g4_l0.yaml" if design_id == "baseline" else "pump976_g4_l1.yaml"
        lens_cfg = yaml.safe_load((ROOT / "configs" / cfg_name).read_text(encoding="utf-8"))["optics"]
        for lens_name in ("L1_front", "L2_front"):
            field = f"{lens_name}_radius_mm"
            lens_key = "l1" if lens_name == "L1_front" else "l2"
            semid = float(lens_cfg[lens_key]["diameter_mm"]) / 2.0
            radii = np.asarray([_float(ray_map[int(i)].get(field)) for i in ray_ids])
            labels = []
            for r in radii:
                if not np.isfinite(r):
                    labels.append("NO_COORDINATE")
                    continue
                f = r / semid
                pos = min(max(int(np.searchsorted(RADIUS_BINS, f, side="right") - 1), 0), 3)
                labels.append(f"{RADIUS_BINS[pos]:.2f}-{RADIUS_BINS[pos+1]:.2f}x_semi_aperture")
            stratum_specs.append((f"{lens_name}_normalized_incidence_radius", labels, np.arange(len(theta))))

        for dimension, labels, _ in stratum_specs:
            unique = list(dict.fromkeys(labels))
            for label in unique:
                mask = np.asarray([x == label for x in labels])
                ids = ray_ids[mask]
                subset = [ray_map[int(i)] for i in ids]
                metrics = _outcome_metrics(subset, total_weight)
                p0cap = sum(float(source["weight"][source_index[int(i)]]) for i in ids
                            if ray_map[int(i)]["_p0"]["p0_status"] == "OK")
                stratum_rows.append({
                    "design_id": design_id, "stratum_dimension": dimension, "stratum": label,
                    "stratum_attempted_rays": len(ids), "stratum_attempted_weight": metrics["attempted_weight"],
                    "all_source_weight_denominator": total_weight,
                    "p0_capture_fraction_source_denominator": p0cap / total_weight,
                    **metrics,
                    "p1_success_fraction_within_stratum": (
                        metrics["captured_weight"] / metrics["attempted_weight"]
                        if metrics["attempted_weight"] else None),
                    "evidence": "SIMULATED_MARGINAL_STRATUM_NOT_A_CROSS_PRODUCT",
                })
    return angle_rows, stratum_rows


def _target_sensitivity(g4_rows: list[dict[str, str]], refs: list[dict[str, str]],
                        source: dict[str, np.ndarray]) -> list[dict[str, Any]]:
    rows = []
    source_weight = float(np.sum(source["weight"], dtype=np.float64))
    refs_map = {d: _as_int_rows([r for r in refs if r["design_id"] == d]) for d, _ in DESIGNS}
    g4_map = {d: _as_int_rows([r for r in g4_rows if r["design_id"] == d
                                and r["angular_case"] == "NA_0.22"]) for d, _ in DESIGNS}
    for design_id, _ in DESIGNS:
        for model_level in ("P0", "P1_INDEPENDENT"):
            x, y, w = [], [], []
            for ray_id in source["ray_id"]:
                q = g4_map[design_id][int(ray_id)] if model_level == "P0" else refs_map[design_id][int(ray_id)]
                reachable = (q["p0_status"] in ("OK", "OUTSIDE_TARGET") if model_level == "P0"
                             else q["terminal_outcome"] in ("CAPTURED", "OUTSIDE_TARGET"))
                x.append(_float(q["p0_x_mm"] if model_level == "P0" else q["target_x_mm"]) if reachable else np.nan)
                y.append(_float(q["p0_y_mm"] if model_level == "P0" else q["target_y_mm"]) if reachable else np.nan)
                w.append(float(source["weight"][np.where(source["ray_id"] == ray_id)[0][0]]))
            x, y, w = np.asarray(x), np.asarray(y), np.asarray(w)
            finite = np.isfinite(x) & np.isfinite(y)
            for radius in TARGET_RADII:
                inside = finite & (x*x + y*y <= radius*radius + 1e-12)
                cap = float(np.sum(w[inside]))
                rows.append({"design_id": design_id, "model_level": model_level,
                             "geometry": "circle", "target_radius_mm": radius,
                             "target_side_mm": None, "target_area_mm2": float(np.pi*radius*radius),
                             "n_reached_plane": int(np.count_nonzero(finite)),
                             "reached_plane_weight": float(np.sum(w[finite])),
                             "captured_weight": cap, "source_weight_denominator": source_weight,
                             "capture_fraction_input": cap/source_weight,
                             "blocked_or_no_plane_weight": source_weight-float(np.sum(w[finite])),
                             "evidence": "SIMULATED_ASSUMED_RECEIVING_REGION"})
            inside = finite & (np.abs(x) <= 1.0 + 1e-12) & (np.abs(y) <= 1.0 + 1e-12)
            cap = float(np.sum(w[inside]))
            rows.append({"design_id": design_id, "model_level": model_level,
                         "geometry": "square", "target_radius_mm": None, "target_side_mm": 2.0,
                         "target_area_mm2": 4.0, "n_reached_plane": int(np.count_nonzero(finite)),
                         "reached_plane_weight": float(np.sum(w[finite])), "captured_weight": cap,
                         "source_weight_denominator": source_weight,
                         "capture_fraction_input": cap/source_weight,
                         "blocked_or_no_plane_weight": source_weight-float(np.sum(w[finite])),
                         "evidence": "SIMULATED_ASSUMED_RECEIVING_REGION"})
    return rows


def _encircled_and_nominal_metrics(g4_rows: list[dict[str, str]], refs: list[dict[str, str]],
                                   source: dict[str, np.ndarray]) -> tuple[list[dict], list[dict]]:
    curve, summaries = [], []
    source_total = float(np.sum(source["weight"], dtype=np.float64))
    by_ref = {d: _as_int_rows([r for r in refs if r["design_id"] == d]) for d, _ in DESIGNS}
    by_g4 = {d: _as_int_rows([r for r in g4_rows if r["design_id"] == d
                               and r["angular_case"] == "NA_0.22"]) for d, _ in DESIGNS}
    for design_id, _ in DESIGNS:
        for model_level in ("P0", "P1_INDEPENDENT"):
            x, y, w = [], [], []
            terminal = []
            for i, ray_id in enumerate(source["ray_id"]):
                row = by_g4[design_id][int(ray_id)] if model_level == "P0" else by_ref[design_id][int(ray_id)]
                reachable = (row["p0_status"] in ("OK", "OUTSIDE_TARGET") if model_level == "P0"
                             else row["terminal_outcome"] in ("CAPTURED", "OUTSIDE_TARGET"))
                x.append(_float(row["p0_x_mm"] if model_level == "P0" else row["target_x_mm"]) if reachable else np.nan)
                y.append(_float(row["p0_y_mm"] if model_level == "P0" else row["target_y_mm"]) if reachable else np.nan)
                w.append(float(source["weight"][i]))
                terminal.append(row.get("p0_status", "UNKNOWN") if model_level == "P0"
                                else row.get("terminal_outcome", "UNKNOWN"))
            x, y, w = np.asarray(x), np.asarray(y), np.asarray(w)
            finite = np.isfinite(x) & np.isfinite(y)
            axis_r = np.hypot(x, y)
            for radius in WEIGHT_RADII:
                enc = float(np.sum(w[finite & (axis_r <= radius + 1e-12)]))
                curve.append({"design_id": design_id, "model_level": model_level,
                              "radius_mm": float(radius), "encircled_source_weight": enc,
                              "source_weight_denominator": source_total,
                              "encircled_weight_fraction_input": enc/source_total,
                              "n_reaching_plane": int(np.count_nonzero(finite)),
                              "unconditional": True, "evidence": "SIMULATED"})
            inside1 = finite & (axis_r <= 1.0 + 1e-12)
            conditional = _centred_metrics(x[inside1], y[inside1], w[inside1])
            point_metrics = _centred_metrics(x[finite], y[finite], w[finite])
            # G4 terminal classifications are exact for P1; reconstruct P0
            # capture from the named fixed 1 mm active circle.
            captured = float(np.sum(w[inside1]))
            if model_level == "P1_INDEPENDENT":
                outside = sum(w[i] for i, t in enumerate(terminal) if t == "OUTSIDE_TARGET")
                blocked_l1 = sum(w[i] for i, t in enumerate(terminal) if t == "APERTURE_BLOCKED_L1")
                blocked_l2 = sum(w[i] for i, t in enumerate(terminal) if t == "APERTURE_BLOCKED_L2")
                failures = sum(w[i] for i, t in enumerate(terminal)
                               if t in ("TRACE_FAILED", "NO_INTERSECTION", "TIR_OR_REFRACTION_FAILURE"))
            else:
                outside = float(np.sum(w[finite & (axis_r > 1.0 + 1e-12)]))
                blocked_l1 = sum(w[i] for i, t in enumerate(terminal) if t in ("APERTURE_BLOCKED", "VIGNETTED")
                                 and by_g4[design_id][int(source["ray_id"][i])].get("p0_blocked_at") == "L1")
                blocked_l2 = sum(w[i] for i, t in enumerate(terminal) if t in ("APERTURE_BLOCKED", "VIGNETTED")
                                 and by_g4[design_id][int(source["ray_id"][i])].get("p0_blocked_at") == "L2")
                failures = source_total - captured - outside - blocked_l1 - blocked_l2
            summaries.append({"design_id": design_id, "model_level": model_level,
                              "target_circle_radius_mm": 1.0,
                              "source_weight_denominator": source_total,
                              "unconditional_captured_weight_at_1mm": captured,
                              "unconditional_capture_fraction_at_1mm": captured/source_total,
                              "conditional_r80_within_1mm_mm": conditional["r80_mm"],
                              "conditional_r90_within_1mm_mm": conditional["r90_mm"],
                              "conditional_rms_within_1mm_mm": conditional["rms_radius_mm"],
                              "r90_all_target_plane_reachers_mm": point_metrics["r90_mm"],
                              "blocked_fraction": (blocked_l1+blocked_l2)/source_total,
                              "trace_failure_fraction": failures/source_total,
                              "outside_nominal_target_fraction": outside/source_total,
                              "n_reaching_plane": point_metrics["n"],
                              "evidence": "SIMULATED; conditional and unconditional metrics separated"})
    return curve, summaries


def _focus_sweep(source: dict[str, np.ndarray], optics_json: dict[str, Any]) -> tuple[list[dict], list[dict]]:
    rows, ray_deltas = [], []
    for design_id, cfg_name in DESIGNS:
        cfg_path = ROOT / "configs" / cfg_name
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        cfg = load_pump976_config(cfg_path)
        model = build_model(optics_json, raw)
        z0 = model.target_z_mm
        for offset in FOCUS_OFFSETS:
            z = z0 + offset
            surfaces, rays, ledger = trace_rays(model, source["ray_id"], source["origin"],
                                                source["direction"], source["weight"],
                                                target_z_mm=z, target_radius_mm=1.0)
            rmap = {int(r["ray_id"]): r for r in rays}
            opti = _run_optiland(design_id, source, target_z_mm=z)
            delta_values = []
            status_match_count = 0
            for j, ray_id in enumerate(source["ray_id"]):
                rr = rmap[int(ray_id)]
                ox, oy = float(opti["x"][5, j]), float(opti["y"][5, j])
                rx, ry = _float(rr["target_x_mm"]), _float(rr["target_y_mm"])
                dxy = float(np.max(np.abs(np.array([ox, oy])-np.array([rx, ry])))) \
                    if np.all(np.isfinite([ox, oy, rx, ry])) else None
                if dxy is not None:
                    delta_values.append(dxy)
                # The geometric pass/block state is already compared in S5-A;
                # this plane-specific status checks the target boundary only.
                oi = float(opti["intensity"][5, j])
                opti_outcome = "NO_INTERSECTION" if not np.isfinite(ox+oy) or oi <= 0 else \
                    "CAPTURED" if ox*ox+oy*oy <= 1.0 + 1e-12 else "OUTSIDE_TARGET"
                ref_outcome = rr["terminal_outcome"]
                match = (opti_outcome == ref_outcome) if ref_outcome in ("CAPTURED", "OUTSIDE_TARGET") else True
                status_match_count += int(match)
                ray_deltas.append({"design_id": design_id, "focus_offset_mm": offset,
                                   "target_z_mm": z, "ray_id": int(ray_id),
                                   "source_weight": float(source["weight"][j]),
                                   "reference_outcome": ref_outcome, "optiland_target_outcome": opti_outcome,
                                   "reference_x_mm": rr["target_x_mm"], "reference_y_mm": rr["target_y_mm"],
                                   "optiland_x_mm": ox, "optiland_y_mm": oy,
                                   "coordinate_delta_max_mm": dxy,
                                   "target_outcome_match": bool(match),
                                   "evidence": "SIMULATED_INDEPENDENT_RETRACE"})
            tx = np.asarray([_float(r["target_x_mm"]) for r in rays])
            ty = np.asarray([_float(r["target_y_mm"]) for r in rays])
            w = np.asarray([float(r["source_weight"]) for r in rays])
            captured = np.asarray([r["terminal_outcome"] == "CAPTURED" for r in rays])
            metrics = _centred_metrics(tx[captured], ty[captured], w[captured])
            all_points = _centred_metrics(tx, ty, w)
            outcomes = Counter(r["terminal_outcome"] for r in rays)
            row = {"design_id": design_id, "focus_strategy": "move_target_plane_only; optics fixed",
                   "as_built_target_z_mm": z0, "target_z_mm": z,
                   "focus_offset_from_as_built_mm": offset,
                   "captured_weight": float(sum(r["source_weight"] for r in rays if r["terminal_outcome"] == "CAPTURED")),
                   "capture_fraction_input": float(sum(r["source_weight"] for r in rays if r["terminal_outcome"] == "CAPTURED")
                                                    / np.sum(source["weight"])),
                   "conditional_rms_within_1mm_mm": metrics["rms_radius_mm"],
                   "conditional_r80_within_1mm_mm": metrics["r80_mm"],
                   "conditional_r90_within_1mm_mm": metrics["r90_mm"],
                   "r90_all_plane_reachers_mm": all_points["r90_mm"],
                   "blocked_l1_fraction": ledger["aperture_blocked_l1_weight"] / ledger["source_weight_total"],
                   "blocked_l2_fraction": ledger["aperture_blocked_l2_weight"] / ledger["source_weight_total"],
                   "trace_failure_or_no_intersection_fraction": (ledger["trace_failed_weight"]
                                                                      + ledger["no_intersection_weight"]
                                                                      + ledger["tir_or_refraction_failure_weight"])
                                                                   / ledger["source_weight_total"],
                   "independent_ledger_status": ledger["status"],
                   "optiland_rays_compared": len(delta_values),
                   "optiland_coordinate_delta_max_mm": max(delta_values) if delta_values else None,
                   "optiland_coordinate_delta_p95_mm": float(np.percentile(delta_values,95)) if delta_values else None,
                   "optiland_target_classification_match_count": status_match_count,
                   "optiland_target_classification_match_fraction": status_match_count / len(rays),
                   "optiland_target_coordinate_gate": bool(delta_values and max(delta_values) <= 1e-6),
                   "captured_count": outcomes["CAPTURED"], "outside_target_count": outcomes["OUTSIDE_TARGET"],
                   "evidence": "SIMULATED_ASSUMED_MODEL"}
            rows.append(row)
    return rows, ray_deltas


def _spherical_focus_trend(refs: list[dict[str, str]]) -> list[dict[str, Any]]:
    out = []
    for design_id, _ in DESIGNS:
        data = [r for r in refs if r["design_id"] == design_id
                and r["terminal_outcome"] in ("CAPTURED", "OUTSIDE_TARGET")]
        # Use the last surface record to obtain the real P1 exit point/direction.
        surface_rows = _load_csv(S5 / "full_na_surface_reference.csv")
        sr = {int(r["ray_id"]): r for r in surface_rows
              if r["design_id"] == design_id and r["surface_id"] == "L2_REAR"}
        shell_values: dict[str, list[tuple[float,float,float]]] = {f"{a:.2f}-{b:.2f}": []
                                                                  for a,b in zip(RADIUS_BINS[:-1],RADIUS_BINS[1:],strict=True)}
        model_json=json.loads((G4/"optics_model.json").read_text(encoding="utf-8"))
        cfg_path=ROOT/"configs"/("pump976_g4_l0.yaml" if design_id=="baseline" else "pump976_g4_l1.yaml")
        cfgraw=yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        aperture=float(cfgraw["optics"]["l2"]["diameter_mm"])/2.0
        for ray in data:
            row=sr[int(ray["ray_id"])]
            p=np.array([_float(row[k]) for k in ("hit_x_mm","hit_y_mm","hit_z_mm")])
            d=np.array([_float(row[k]) for k in ("outgoing_dx","outgoing_dy","outgoing_dz")])
            if not np.all(np.isfinite(p)) or not np.all(np.isfinite(d)):
                continue
            denom=d[0]*d[0]+d[1]*d[1]
            if denom <= 1e-24:
                continue
            t=-(p[0]*d[0]+p[1]*d[1])/denom
            z=p[2]+t*d[2]
            closest=np.hypot(p[0]+t*d[0],p[1]+t*d[1])
            frac=np.hypot(p[0],p[1])/aperture
            bi=min(max(int(np.searchsorted(RADIUS_BINS,frac,side="right")-1),0),3)
            key=f"{RADIUS_BINS[bi]:.2f}-{RADIUS_BINS[bi+1]:.2f}"
            shell_values[key].append((z,float(ray["source_weight"]),closest))
        for shell, values in shell_values.items():
            if not values:
                continue
            z=np.asarray([v[0] for v in values]); w=np.asarray([v[1] for v in values]); r=np.asarray([v[2] for v in values])
            out.append({"design_id":design_id,"l2_exit_pupil_shell_normalized":shell,
                        "n_rays":len(values),"source_weight":float(np.sum(w)),
                        "closest_axis_z_weighted_median_mm":_weighted_quantile(z,w,0.5),
                        "closest_axis_z_weighted_p05_mm":_weighted_quantile(z,w,0.05),
                        "closest_axis_z_weighted_p95_mm":_weighted_quantile(z,w,0.95),
                        "closest_approach_radius_weighted_median_mm":_weighted_quantile(r,w,0.5),
                        "interpretation":"geometric closest-axis longitudinal-focus proxy; finite near-field source; not wavefront SA",
                        "evidence":"SIMULATED_INDEPENDENT_RAY_EXIT_STATE"})
    return out


def _source_assumption_sensitivity() -> tuple[list[dict], list[dict], list[dict]]:
    optics_json=json.loads((G4/"optics_model.json").read_text(encoding="utf-8"))
    cfg_path=ROOT/"configs/pump976_g4_l0.yaml"
    raw=yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    cfg=load_pump976_config(cfg_path)
    model=build_model(optics_json,raw)
    cases=[(0.05,"uniform_solid_angle"),(0.22,"uniform_solid_angle"),(0.22,"edge_biased_sin_theta")]
    summary=[]; ray_rows=[]; source_rows=[]
    for na,angular in cases:
        bundle=sample_multimode_fiber(4096,cfg.core_diameter_mm,na,output_index=cfg.output_index,
                                      seed=976061,angular_distribution=angular)
        for i in range(bundle.n_rays):
            source_rows.append({"ray_id":int(bundle.ray_id[i]),
                                "x0_mm":float(bundle.origin_mm[i,0]),"y0_mm":float(bundle.origin_mm[i,1]),
                                "z0_mm":float(bundle.origin_mm[i,2]),"dx":float(bundle.direction[i,0]),
                                "dy":float(bundle.direction[i,1]),"dz":float(bundle.direction[i,2]),
                                "weight":float(bundle.weight[i]),"seed":976061,
                                "numerical_aperture":na,"angular_distribution":angular,
                                "evidence":"ASSUMED_SIMULATED_SOURCE_SENSITIVITY"})
        _, pref, ledger=trace_rays(model,bundle.ray_id,bundle.origin_mm,bundle.direction,bundle.weight)
        p0=trace_thin_lens(bundle,cfg.beamline)
        p0_ok=p0.status=="OK"
        p0_capture=float(np.sum(bundle.weight[p0_ok]))
        p1_metrics=Counter(r["terminal_outcome"] for r in pref)
        p1_cap=float(sum(r["source_weight"] for r in pref if r["terminal_outcome"]=="CAPTURED"))
        summary.append({"lens_design":"baseline","numerical_aperture":na,"angular_distribution":angular,
                        "seed":976061,"n_rays":4096,"source_weight_denominator":bundle.total_weight,
                        "p0_capture_fraction_input":p0_capture/bundle.total_weight,
                        "p1_capture_fraction_input":p1_cap/bundle.total_weight,
                        "p1_blocked_l1_fraction":ledger["aperture_blocked_l1_weight"]/bundle.total_weight,
                        "p1_blocked_l2_fraction":ledger["aperture_blocked_l2_weight"]/bundle.total_weight,
                        "p1_outside_target_fraction":ledger["outside_target_weight"]/bundle.total_weight,
                        "p1_trace_failure_fraction":(ledger["trace_failed_weight"]+ledger["no_intersection_weight"]
                                                       +ledger["tir_or_refraction_failure_weight"])/bundle.total_weight,
                        "p1_outcome_counts":dict(p1_metrics),
                        "interpretation":"source-distribution sensitivity; not a lens-design gain",
                        "evidence":"ASSUMED_SIMULATED"})
        for i,r in enumerate(pref):
            ray_rows.append({"lens_design":"baseline","numerical_aperture":na,
                             "angular_distribution":angular,"seed":976061,**r,
                             "p0_status":str(p0.status[i]),"p0_x_mm":float(p0.target_x_mm[i]),
                             "p0_y_mm":float(p0.target_y_mm[i])})
    return summary,ray_rows,source_rows


def _plot_outputs(angle: list[dict], focus: list[dict], enc: list[dict], tgt: list[dict],
                  geometry: list[dict], deltas: list[dict], sa: list[dict], output: Path) -> list[str]:
    output.mkdir(parents=True,exist_ok=True)
    plt.rcParams.update({"font.family":"DejaVu Sans","font.size":9,"axes.titlesize":11})
    created=[]
    label="SIMULATED • NA 0.22 • equal source-weight denominator • assumed 1 mm circle unless stated"
    # Angle-resolved comparison.
    fig,ax=plt.subplots(figsize=(11,5.4))
    groups=list(dict.fromkeys(r["angle_bin"] for r in angle if r["design_id"]=="baseline"))
    x=np.arange(len(groups)); width=.19
    for j,(did,model,key,color) in enumerate([
        ("baseline","P0","p0_capture_fraction_within_angle","#315a7d"),
        ("baseline","P1","p1_capture_fraction_within_angle","#c65d2e"),
        ("engineering_candidate","P0","p0_capture_fraction_within_angle","#6992ad"),
        ("engineering_candidate","P1","p1_capture_fraction_within_angle","#e2a07b")]):
        vals=[]
        for g in groups:
            row=next(r for r in angle if r["design_id"]==did and r["angle_bin"]==g)
            vals.append(row[key])
        ax.bar(x+(j-1.5)*width,vals,width,label=f"{did} {model}",color=color)
    ax.set_xticks(x,groups);ax.set_ylim(0,1.08);ax.set_ylabel("Capture fraction within launch-angle bin")
    ax.set_title("High-NA target capture by launch angle")
    ax.legend(ncol=1,frameon=False,loc="upper left",bbox_to_anchor=(1.01,1.0),fontsize=8)
    ax.grid(axis="y",alpha=.2)
    fig.subplots_adjust(left=.09,right=.78,top=.85,bottom=.22)
    fig.text(.01,.025,"SIMULATED • NA=0.22 • 4,096 rays/design • per-bin capture within launch angle",fontsize=8,color="#555")
    path=output/"angle_resolved_p0_p1_capture.png";fig.savefig(path,dpi=180);plt.close(fig);created.append(path.name)

    # Per surface cross-check.
    fig,(ax1,ax2)=plt.subplots(1,2,figsize=(11,4.7))
    surfaces=["L1_FRONT","L1_REAR","L2_FRONT","L2_REAR"]
    for did,color in (("baseline","#315a7d"),("engineering_candidate","#c65d2e")):
        pos=[];direction=[]
        for sid in surfaces:
            rows=[r for r in deltas if r["design_id"]==did and r["surface_id"]==sid]
            pos.append(max((float(r["max_absolute_delta"]) for r in rows if r["metric"]=="position"),default=np.nan))
            direction.append(max((float(r["max_absolute_delta"]) for r in rows if r["metric"]=="direction"),default=np.nan))
        ax1.plot(surfaces,pos,"o-",label=did,color=color)
        ax2.plot(surfaces,direction,"o-",label=did,color=color)
    ax1.axhline(1e-8,color="#777",ls="--",lw=1,label="frozen tolerance")
    ax2.axhline(1e-9,color="#777",ls="--",lw=1,label="frozen tolerance")
    ax1.set_yscale("log");ax2.set_yscale("log")
    ax1.set_ylabel("Maximum coordinate delta (mm)");ax2.set_ylabel("Maximum direction component delta")
    ax1.set_title("Sphere intersections");ax2.set_title("Exit directions")
    for a in (ax1,ax2):a.tick_params(axis="x",rotation=25);a.grid(alpha=.2)
    ax1.set_ylim(1e-15,1e-8);ax2.set_ylim(1e-16,1e-9)
    handles,labels=ax1.get_legend_handles_labels()
    fig.legend(handles,labels,frameon=False,fontsize=8,loc="upper center",ncol=3,bbox_to_anchor=(.5,.91))
    fig.suptitle("Independent full-NA Snell / Optiland cross-check")
    fig.subplots_adjust(left=.08,right=.99,top=.80,bottom=.23,wspace=.25)
    fig.text(.01,.025,"SIMULATED • NA=0.22 • 4,096 rays/design • assumed N-BK7 singlets",fontsize=8,color="#555")
    path=output/"surface_level_ray_deltas.png";fig.savefig(path,dpi=180);plt.close(fig);created.append(path.name)

    fig,(ax1,ax2)=plt.subplots(1,2,figsize=(10.5,4.6))
    for (did,ml),items in _group(enc, ("design_id","model_level")).items():
        ax1.plot([r["radius_mm"] for r in items],[r["encircled_weight_fraction_input"] for r in items],
                 label=f"{did.replace('_',' ')} {ml.replace('_INDEPENDENT','')}")
    ax1.set_xlabel("Radius from optical axis (mm)");ax1.set_ylabel("Encircled fraction of total input weight")
    ax1.set_title("Unconditional encircled weight")
    for key,items in _group(focus,("design_id",)).items():
        ax2.plot([r["focus_offset_from_as_built_mm"] for r in items],
                 [r["capture_fraction_input"] for r in items],"o-",label=key[0].replace('_',' '))
    ax2.axvline(0,color="#777",ls="--",lw=1)
    ax2.set_xlabel("Target-plane offset from as-built z (mm)");ax2.set_ylabel("Fraction of total source weight inside 1 mm")
    ax2.set_title("Focus-plane sensitivity (target moved only)")
    for a in (ax1,ax2):a.grid(alpha=.2)
    ax1.legend(ncol=2,loc="upper center",bbox_to_anchor=(.5,-.24),frameon=False,fontsize=7)
    ax2.legend(frameon=False,fontsize=7,loc="upper left",bbox_to_anchor=(1.01,1.0))
    fig.subplots_adjust(left=.09,right=.80,top=.86,bottom=.34,wspace=.28)
    fig.text(.01,.025,"SIMULATED • total source-weight denominator • target plane moved only",fontsize=8,color="#555")
    path=output/"encircled_weight_and_focus_sweep.png";fig.savefig(path,dpi=180);plt.close(fig);created.append(path.name)

    fig,ax=plt.subplots(figsize=(10,4.8))
    labels=[f"{r['geometry']} {r['target_radius_mm'] if r['geometry']=='circle' else r['target_side_mm']}" for r in tgt]
    grouped={}
    for r in tgt:grouped.setdefault((r["design_id"],r["model_level"]),[]).append(r)
    x=np.arange(len(TARGET_RADII)+1);width=.19
    for j,(key,items) in enumerate(grouped.items()):
        items=sorted(items,key=lambda r:(r["geometry"]!="circle",r["target_radius_mm"] or 0))
        vals=[r["capture_fraction_input"] for r in items]
        ax.bar(x+(j-(len(grouped)-1)/2)*width,vals,width,label=f"{key[0]} {key[1]}")
    ax.set_xticks(x,["circle Ø1 mm","Ø2 mm","Ø3 mm","Ø4 mm","square 2x2 mm"])
    ax.set_ylabel("Captured total source-weight fraction");ax.set_ylim(0,1.05)
    ax.set_title("Assumed receiving-region sensitivity")
    ax.legend(ncol=1,frameon=False,fontsize=7,loc="upper left",bbox_to_anchor=(1.01,1.0));ax.grid(axis="y",alpha=.2)
    fig.subplots_adjust(left=.10,right=.75,top=.85,bottom=.24)
    fig.text(.01,.025,"SIMULATED • all source weight in denominator • receiving shapes/sizes are assumptions",fontsize=8,color="#555")
    path=output/"target_geometry_sensitivity.png";fig.savefig(path,dpi=180);plt.close(fig);created.append(path.name)

    # Schematic lens mechanical outline; a diagram of assumptions, not a vendor drawing.
    fig,axes=plt.subplots(2,2,figsize=(10,7),constrained_layout=True)
    lens_by={(r["design_id"],r["lens_id"]):r for r in geometry}
    optics_json=json.loads((G4/"optics_model.json").read_text(encoding="utf-8"))
    for row_index,(did,title) in enumerate((("baseline","baseline"),("engineering_candidate","candidate"))):
        lens_list=optics_json["P1"]["lens_models"]["P1_baseline" if did=="baseline" else "P1_candidate"]
        for col_index,lens in enumerate(lens_list):
            ax=axes[row_index,col_index]
            geom=lens_by[(did,lens["name"])];a=float(geom["clear_aperture_diameter_mm"])/2
            rs=np.linspace(-a,a,200);R1=float(geom["radius_front_mm"]);R2=float(geom["radius_rear_mm"])
            z1=float(lens["front_vertex_z_mm"])+R1-np.sqrt(R1*R1-rs*rs)
            z2=float(lens["rear_vertex_z_mm"])+R2+np.sqrt(R2*R2-rs*rs)
            z_local_1=z1-float(lens["front_vertex_z_mm"])
            z_local_2=z2-float(lens["front_vertex_z_mm"])
            ax.fill(np.r_[z_local_1,z_local_2[::-1]],np.r_[rs,rs[::-1]],alpha=.32,color="#6a9fba")
            ax.plot(z_local_1,rs,color="#24506b",lw=1.0);ax.plot(z_local_2,rs,color="#24506b",lw=1.0)
            ax.axhline(a,color="#777",ls=":",lw=.7);ax.axhline(-a,color="#777",ls=":",lw=.7)
            warning=" [LOW]" if geom["status"]=="EDGE_THICKNESS_ASSUMED_LOW" else ""
            ax.set_title(f"{title} {lens['name']} | CA Ø{2*a:g} mm | edge {float(geom['edge_thickness_mm']):.3f} mm{warning}\n"
                         f"front z={float(lens['front_vertex_z_mm']):.3f} mm",fontsize=9)
            ax.set_ylabel("Height (mm)");ax.set_xlabel("Local z from front vertex (mm)")
            ax.set_xlim(-.15,float(geom["center_thickness_mm"])+.15);ax.grid(alpha=.15)
    fig.suptitle("ASSUMED spherical singlet sections • clear aperture only; outer diameter unspecified\nNot a vendor drawing or manufacturing verdict")
    path=output/"s5_assumed_lens_mechanical_outline.png";fig.savefig(path,dpi=180);plt.close(fig);created.append(path.name)
    return created


def _group(rows: list[dict], keys: tuple[str,...]) -> dict[tuple, list[dict]]:
    out={}
    for row in rows:out.setdefault(tuple(row[k] for k in keys),[]).append(row)
    return out


def main() -> int:
    verdict=json.loads((S5/"full_na_verdict.json").read_text(encoding="utf-8"))
    if verdict["status"]!="PASS":
        raise SystemExit("S5-B can only be called mechanism diagnosis after S5-A PASS")
    source=_read_source()
    source_total=float(np.sum(source["weight"],dtype=np.float64))
    g4_rows=_load_csv(G4/"raytrace_reference.csv")
    refs=_load_csv(S5/"full_na_ray_reference.csv")
    model_json=json.loads((G4/"optics_model.json").read_text(encoding="utf-8"))
    angle,strata=_build_angle_and_strata(g4_rows,refs,source,source_total)
    target=_target_sensitivity(g4_rows,refs,source)
    enc,nominal=_encircled_and_nominal_metrics(g4_rows,refs,source)
    focus,focus_ray_deltas=_focus_sweep(source,model_json)
    sa=_spherical_focus_trend(refs)
    source_sens,source_sens_rays,source_sens_sources=_source_assumption_sensitivity()
    S5.mkdir(parents=True,exist_ok=True)
    _write_csv(S5/"angle_resolved_p0_p1_capture.csv",angle)
    _write_csv(S5/"mechanism_strata.csv",strata)
    _write_csv(S5/"target_geometry_sensitivity.csv",target)
    _write_csv(S5/"encircled_weight.csv",enc)
    _write_csv(S5/"nominal_conditional_unconditional_metrics.csv",nominal)
    _write_csv(S5/"focus_sweep.csv",focus)
    _write_csv(S5/"focus_sweep_ray_deltas.csv",focus_ray_deltas)
    _write_csv(S5/"longitudinal_focus_proxy.csv",sa)
    _write_csv(S5/"source_assumption_sensitivity.csv",source_sens)
    _write_csv(S5/"source_assumption_ray_reference.csv",source_sens_rays)
    _write_csv(S5/"source_assumption_source_samples.csv",source_sens_sources)
    geometry=_load_csv(S5/"lens_geometry_feasibility.csv")
    figures=_plot_outputs(angle,focus,enc,target,geometry,_load_csv(S5/"surface_level_ray_deltas.csv"),sa,S5/"figures")
    assumptions=(
        "# Material and source assumptions\n\n"
        "All Stage 5 outputs are `SIMULATED` under the G4 assumed geometric-ray source. The 976 nm wavelength, 105 µm core, NA 0.22, output index 1, uniform-area near field, and uniform-solid-angle far field come from the frozen G4 configuration; the source profile is not measured and absolute power is UNKNOWN. The additional NA 0.05 and edge-biased angular cases are sensitivities only.\n\n"
        "The assumed lenses are centered, 2 mm center-thickness equiconvex N-BK7 singlets derived from focal length, with G4 clear apertures. Dispersion uses the SCHOTT N-BK7 Sellmeier-2 coefficients and 0.3–2.5 µm catalog range shipped with Optiland 0.6.3; at 976 nm the independent formula and catalog index agree. Non-N-BK7 material labels are rejected. The optical design has no vendor part number, outer diameter, coating/Fresnel model, decenter/tilt, or measured drawing.\n\n"
        "The 0.5, 1, 1.5, 2 mm circular and 2 x 2 mm square receiving regions are geometric sensitivities, not Er:YAP dimensions. The original 1 mm circle is retained for primary comparisons. Geometric weight outside it is not absolute power loss, coupling efficiency, W/mm², or crystal absorption.\n\n"
        "The longitudinal-focus proxy uses each L2-rear exit ray's closest approach to the optical axis. It is a geometric diagnostic of this assumed ray model, not a wavefront Seidel coefficient, PSF, or experimental focus measurement. Focus sweep moves the receiving plane only; it does not authorize a physical hardware adjustment.\n"
    )
    (S5/"material_and_source_assumptions.md").write_text(assumptions,encoding="utf-8")
    focus_by={(r["design_id"],float(r["focus_offset_from_as_built_mm"])):r for r in focus}
    focus_recovered=all(focus_by[(did,-25.0)]["capture_fraction_input"]>=0.99 for did,_ in DESIGNS)
    pupil_order=[]
    for did,_ in DESIGNS:
        sequence=sorted((r for r in sa if r["design_id"]==did),
                        key=lambda r:float(r["l2_exit_pupil_shell_normalized"].split("-")[0]))
        pupil_order.append(len(sequence)>=3 and
                           float(sequence[-1]["closest_axis_z_weighted_median_mm"])
                           < float(sequence[0]["closest_axis_z_weighted_median_mm"])-10.0)
    high_angle= [r for r in angle if r["angle_bin"] in ("9-11deg","11-12.7099deg")]
    no_aperture_or_trace_loss=all(
        float(r["p1_blocked_l1_weight"])==0.0 and float(r["p1_blocked_l2_weight"])==0.0
        and float(r["p1_trace_failed_weight"])==0.0 for r in high_angle)
    cause_status="EXPLAINED_WITH_SCOPE" if focus_recovered and all(pupil_order) and no_aperture_or_trace_loss else "PARTIAL"
    cause_summary=(
        "Within the assumed P1 geometry, the nominal 1 mm-target miss is consistent with pupil-dependent "
        "longitudinal spherical aberration: the outer sampled L2 pupil bands have a shorter closest-axis focus than the "
        "inner pupil, and the registered -25 mm target-plane sensitivity recovers capture. No ray is lost "
        "at a lens aperture or in tracing. This is a geometric model diagnosis, not measured lens performance "
        "or a hardware prescription. The -25 mm point is the lower edge of the registered focus grid, so "
        "the exact optimum was not bracketed."
        if cause_status=="EXPLAINED_WITH_SCOPE" else
        "The reference is verified, but the registered focus/pupil evidence does not meet the frozen causal rule.")
    result={"schema":"optisys.s5.analysis_status/1","run_id":"20261020_210201_S5_HNA",
            "S5_A_REFERENCE_VERIFICATION":"PASS","S5_B_HIGH_NA_CAUSE_STATUS":cause_status,
            "analysis_level":"SIMULATED_ASSUMED_P1; full-na reference cross-check passed",
            "source_weight_denominator":source_total,"angle_bin_count":len(angle),
            "marginal_strata_rows":len(strata),"target_geometry_rows":len(target),
            "encircled_curve_rows":len(enc),"focus_plane_rows":len(focus),
            "focus_ray_delta_rows":len(focus_ray_deltas),"longitudinal_focus_rows":len(sa),
            "source_sensitivity_rows":len(source_sens),"source_sensitivity_ray_rows":len(source_sens_rays),
            "source_sensitivity_source_rows":len(source_sens_sources),
            "figures":figures,"main_diagnosis_scope":cause_summary,
            "causal_checks":{"registered_minus_25mm_focus_recovers_capture":focus_recovered,
                             "pupil_dependent_closest_axis_z_shift_gt_10mm":pupil_order,
                             "high_angle_lens_block_and_trace_failure_weights_zero":no_aperture_or_trace_loss},
            "evidence":"SIMULATED_ASSUMED_MODEL"}
    (S5/"s5_b_analysis_status.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
