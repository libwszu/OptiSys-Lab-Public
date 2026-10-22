"""Independent standard-library replay for an extracted G4 audit package.

This verifier imports no OptiSys project code and reads only siblings inside the
extracted audit package. It reconstructs the nominal P0 baseline from the
shipped source CSV and JSON inputs, then rechecks denominators, spot radii,
tolerance row counts, and the paired holdout summary.
"""

from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUN = ROOT / "run"


def _csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _float(row: dict[str, str], key: str) -> float:
    value = row.get(key, "")
    if value in (None, ""):
        raise ValueError(f"missing numeric value {key}")
    result = float(value)
    if not math.isfinite(result):
        raise ValueError(f"non-finite {key}")
    return result


def _trace_p0(ray: dict[str, str], design: dict[str, Any]) -> tuple[float, float, float, float, str]:
    x, y, z = (_float(ray, "x0_mm"), _float(ray, "y0_mm"), _float(ray, "z0_mm"))
    dx, dy, dz = (_float(ray, "dx"), _float(ray, "dy"), _float(ray, "dz"))
    for name in ("l1", "l2"):
        lens = design[name]
        distance = (float(lens["z_mm"]) - z) / dz
        if distance < -1e-12:
            return math.nan, math.nan, dx, dy, "NO_INTERSECTION"
        x += distance * dx
        y += distance * dy
        z = float(lens["z_mm"])
        if x*x + y*y > (float(lens["aperture_diameter_mm"]) / 2.0) ** 2 + 1e-12:
            return math.nan, math.nan, dx, dy, "APERTURE_BLOCKED"
        ux = dx / dz - x / float(lens["focal_length_mm"])
        uy = dy / dz - y / float(lens["focal_length_mm"])
        norm = math.sqrt(1.0 + ux*ux + uy*uy)
        dx, dy, dz = ux / norm, uy / norm, 1.0 / norm
    distance = (float(design["target_z_mm"]) - z) / dz
    if distance < -1e-12:
        return math.nan, math.nan, dx, dy, "NO_INTERSECTION"
    x += distance * dx
    y += distance * dy
    status = "OUTSIDE_TARGET" if x*x + y*y > float(design["target_radius_mm"])**2 + 1e-12 else "OK"
    return x, y, dx, dy, status


def _weighted_quantile(values: list[tuple[float, float]], q: float) -> float:
    ordered = sorted(values, key=lambda item: item[0])
    total = sum(weight for _, weight in ordered)
    if total <= 0:
        raise ValueError("weighted quantile has zero total weight")
    cutoff = q * total
    cumulative = 0.0
    for value, weight in ordered:
        cumulative += weight
        if cumulative >= cutoff:
            return value
    return ordered[-1][0]


def _quantile(values: list[float], q: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("cannot take quantile of an empty list")
    position = (len(ordered) - 1) * q
    low = int(math.floor(position))
    high = int(math.ceil(position))
    if low == high:
        return ordered[low]
    fraction = position - low
    return ordered[low] * (1 - fraction) + ordered[high] * fraction


def verify() -> dict[str, Any]:
    status = json.loads((RUN / "run_status.json").read_text(encoding="utf-8"))
    inputs = json.loads((RUN / "repro_inputs.json").read_text(encoding="utf-8"))
    source_rows = _csv(RUN / "source_samples.csv")
    reference_rows = _csv(RUN / "raytrace_reference.csv")
    balances = _csv(RUN / "ray_balance.csv")
    tolerance = _csv(RUN / "tolerance_samples.csv")
    metrics = _csv(RUN / "target_plane_metrics.csv")
    comparison = _csv(RUN / "design_comparison.csv")
    bootstrap_summary = json.loads((RUN / "bootstrap_summary.json").read_text(encoding="utf-8"))
    bootstrap_rows = _csv(RUN / "bootstrap_replicates.csv")
    convergence_rows = _csv(RUN / "ray_count_convergence.csv")
    convergence_summary = json.loads((RUN / "ray_count_convergence_summary.json").read_text(encoding="utf-8"))

    if not source_rows or len(source_rows) != int(inputs["source"]["ray_count"]):
        raise ValueError("source sample count does not match repro_inputs.json")
    if any("# TRUNCATED" in value for row in source_rows for value in row.values()):
        raise ValueError("truncation marker present in source samples")
    weights = [_float(row, "weight") for row in source_rows]
    if abs(sum(weights) - 1.0) > 1e-12:
        raise ValueError(f"source weights do not sum to one: {sum(weights)}")
    direction_error = max(abs(math.sqrt(_float(r, "dx")**2 + _float(r, "dy")**2 + _float(r, "dz")**2) - 1.0)
                          for r in source_rows)
    if direction_error > 1e-12:
        raise ValueError(f"source direction norm error too large: {direction_error}")
    for design in ("baseline", "engineering_candidate"):
        for n_rays in (2000, 8000, 32000):
            samples = [row for row in convergence_rows if row["design_id"] == design
                       and int(row["n_rays"]) == n_rays]
            if len(samples) != 3 or len({int(row["seed"]) for row in samples}) != 3:
                raise ValueError(f"missing independent ray-count seeds: {design}, N={n_rays}")
    for row in convergence_summary.get("confidence_interval_rows", []):
        if int(row["n_seeds"]) != 3 or row.get("ci95_low") is None or row.get("ci95_high") is None:
            raise ValueError("ray-count convergence interval is missing its three-seed uncertainty")

    baseline = inputs["designs"]["baseline"]
    output = {}
    for source in source_rows:
        x, y, dx, dy, state = _trace_p0(source, baseline)
        output[int(source["ray_id"])] = (x, y, state)
    target = {(int(row["ray_id"]), row["design_id"], row["angular_case"]): row
              for row in reference_rows}
    deltas = []
    radial_values = []
    for ray_id, (x, y, state) in output.items():
        row = target[(ray_id, "baseline", "NA_0.22")]
        if state != row["p0_status"]:
            raise ValueError(f"P0 status mismatch ray {ray_id}: {state} vs {row['p0_status']}")
        dx = x - float(row["p0_x_mm"])
        dy = y - float(row["p0_y_mm"])
        delta = math.hypot(dx, dy)
        deltas.append(delta)
        if state == "OK":
            radial_values.append((x, y, _float(source_rows[ray_id], "weight")))
    max_position_delta = max(deltas) if deltas else 0.0
    if max_position_delta > 1e-10:
        raise ValueError(f"independent P0 replay differs by {max_position_delta} mm")

    total_w = sum(w for _, _, w in radial_values)
    cx = sum(x*w for x, _, w in radial_values) / total_w
    cy = sum(y*w for _, y, w in radial_values) / total_w
    radii = [(math.hypot(x-cx, y-cy), w) for x, y, w in radial_values]
    r80 = _weighted_quantile(radii, 0.80)
    r90 = _weighted_quantile(radii, 0.90)
    metric = next(row for row in metrics if row["design_id"] == "baseline"
                  and row["backend"] == "P0" and row["angular_case"] == "NA_0.22")
    if abs(r80 - float(metric["r80_mm"])) > 1e-10 or abs(r90 - float(metric["r90_mm"])) > 1e-10:
        raise ValueError("independent baseline spot-radius recomputation does not match CSV")

    for row in balances:
        fields = ["transmitted_weight", "outside_target_weight", "l1_blocked_weight",
                  "l2_blocked_weight", "no_intersection_weight", "trace_failed_weight"]
        pieces = [float(row.get(k) or 0.0) for k in fields]
        source_total = float(row["source_weight_total"])
        residual = source_total - sum(pieces)
        if abs(residual) > 1e-10 or abs(float(row["balance_residual"])) > 1e-10:
            raise ValueError(f"ray balance does not close for {row['design_id']} {row['backend']} {row['angular_case']}")
        if not 0.0 <= float(row["geometric_transmission_fraction"]) <= 1.0:
            raise ValueError("geometric transmission outside [0,1]")

    if len(tolerance) != int(status["expected_tolerance_rows"]):
        raise ValueError("tolerance CSV denominator does not match the run status")
    ids = [row["sample_id"] for row in tolerance]
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate tolerance sample IDs")
    by_design: dict[str, list[dict[str, str]]] = {}
    for row in tolerance:
        by_design.setdefault(row["design_id"], []).append(row)
    summary_rows = {row["design_id"]: row for row in comparison}
    for design in ("baseline", "engineering_candidate"):
        holdout = [r for r in by_design.get(design, []) if r["phase"] == "holdout"]
        valid = [r for r in holdout if r.get("r90_mm") not in (None, "")]
        summary = summary_rows[design]
        failure = 1.0 - len(valid) / len(holdout) if holdout else None
        mean_r90 = sum(float(r["r90_mm"]) for r in valid) / len(valid) if valid else None
        if int(summary["holdout_n_attempted"]) != len(holdout):
            raise ValueError(f"holdout denominator mismatch for {design}")
        if int(summary["holdout_n_valid_spot"]) != len(valid):
            raise ValueError(f"holdout valid count mismatch for {design}")
        if failure is not None and abs(float(summary["holdout_failure_rate"]) - failure) > 1e-12:
            raise ValueError(f"holdout failure rate mismatch for {design}")
        if mean_r90 is not None and abs(float(summary["holdout_mean_r90_mm_valid_only"]) - mean_r90) > 1e-10:
            raise ValueError(f"holdout mean r90 mismatch for {design}")

    if len(bootstrap_rows) != int(bootstrap_summary.get("replicates", 0)):
        raise ValueError("bootstrap replicate table size does not match summary")
    tx_boot = [_float(row, "delta_transmission") for row in bootstrap_rows]
    r90_boot = [_float(row, "delta_r90_mm_valid_pairs") for row in bootstrap_rows]
    tx_ci = bootstrap_summary["delta_transmission_95_ci"]
    r90_ci = bootstrap_summary["delta_r90_mm_95_ci_valid_pairs"]
    if abs(_quantile(tx_boot, .025) - float(tx_ci[0])) > 1e-12 or abs(_quantile(tx_boot, .975) - float(tx_ci[1])) > 1e-12:
        raise ValueError("independent bootstrap percentile calculation disagrees for transmission")
    if abs(_quantile(r90_boot, .025) - float(r90_ci[0])) > 1e-12 or abs(_quantile(r90_boot, .975) - float(r90_ci[1])) > 1e-12:
        raise ValueError("independent bootstrap percentile calculation disagrees for r90")
    paired_rows = {int(row["assembly_id"]): {} for row in tolerance}
    for row in tolerance:
        if row["phase"] == "holdout":
            paired_rows[int(row["assembly_id"])][row["design_id"]] = row
    tx_deltas = [float(p["engineering_candidate"]["geometric_transmission_fraction"])
                 - float(p["baseline"]["geometric_transmission_fraction"])
                 for p in paired_rows.values() if "baseline" in p and "engineering_candidate" in p]
    r90_deltas = [float(p["engineering_candidate"]["r90_mm"]) - float(p["baseline"]["r90_mm"])
                  for p in paired_rows.values() if "baseline" in p and "engineering_candidate" in p
                  and p["baseline"].get("r90_mm") not in (None, "")
                  and p["engineering_candidate"].get("r90_mm") not in (None, "")]
    if abs(sum(tx_deltas)/len(tx_deltas) - float(bootstrap_summary["delta_transmission_candidate_minus_baseline_mean"])) > 1e-12:
        raise ValueError("paired holdout transmission mean does not recompute")
    if abs(sum(r90_deltas)/len(r90_deltas) - float(bootstrap_summary["delta_r90_mm_candidate_minus_baseline_valid_pairs_mean"])) > 1e-10:
        raise ValueError("paired holdout r90 mean does not recompute")

    html = (RUN / "report.html").read_text(encoding="utf-8")
    if "QUALIFIED_ONLY" not in html or "NOT_AVAILABLE" not in html or "W/mm²" not in html:
        raise ValueError("report missing inherited/scientific boundary tokens")
    if "# TRUNCATED" in (RUN / "tolerance_samples.csv").read_text(encoding="utf-8"):
        raise ValueError("tolerance samples appear truncated")

    return {
        "status": "PASS", "source_rows": len(source_rows),
        "max_p0_replay_delta_mm": max_position_delta,
        "recomputed_baseline_r80_mm": r80, "recomputed_baseline_r90_mm": r90,
        "ray_balance_rows": len(balances), "tolerance_rows": len(tolerance),
        "unique_tolerance_ids": len(set(ids)), "design_comparison_rows": len(comparison),
        "bootstrap_replicates": len(bootstrap_rows),
        "absolute_power": "UNKNOWN", "external_evidence": "NOT_AVAILABLE",
    }


def main() -> int:
    try:
        result = verify()
    except Exception as exc:
        print(f"REPRO_STATUS: FAIL\n{type(exc).__name__}: {exc}")
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("REPRO_STATUS: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
