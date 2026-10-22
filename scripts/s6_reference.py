"""Run S6-A's frozen dual-reference and adversarial geometry matrix."""

from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
import sys
import time
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from optisys.optics.s5_reference import build_model  # noqa: E402
from optisys.optics.s6_rigid_body import (  # noqa: E402
    LensPose,
    S6GeometryError,
    _refract_local,
    _refract_world,
    compare_references,
    invalid_geometry_reason,
    trace_local,
    trace_world,
)
from optisys.sources.multimode_fiber import sample_multimode_fiber  # noqa: E402

RUN_ID = "20261021_024715_S6_P1"
S5 = ROOT / "runs/20261020_210201_S5_HNA"
G4 = ROOT / "runs/20261020_133555_G4_ec3e2813_0e48"


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise ValueError(f"refusing to write empty evidence: {path}")
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                fields.append(key)
                seen.add(key)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _load_model():
    optics_path = G4 / "optics_model.json"
    config_path = ROOT / "configs/pump976_g4_l0.yaml"
    optics = json.loads(optics_path.read_text(encoding="utf-8"))
    config = yaml.safe_load(config_path.read_text(encoding="utf-8-sig"))
    return build_model(optics, config)


def _source_arrays(rows: list[dict[str, str]]):
    ids = np.asarray([int(row["ray_id"]) for row in rows], dtype=np.int64)
    origins = np.asarray([[float(row[f"{axis}0_mm"]) for axis in "xyz"] for row in rows], dtype=float)
    directions = np.asarray([[float(row[f"d{axis}"]) for axis in "xyz"] for row in rows], dtype=float)
    weights = np.asarray([float(row["weight"]) for row in rows], dtype=float)
    return ids, origins, directions, weights


def _capture_n(result) -> int:
    return int(result.ledger["terminal_count"].get("CAPTURED", 0))


def _pose_cases() -> list[tuple[str, tuple[LensPose, LensPose]]]:
    cases: list[tuple[str, tuple[LensPose, LensPose]]] = [("zero", (LensPose(), LensPose()))]
    for lens_id in (1, 2):
        for axis, field in (("x", "dx_mm"), ("y", "dy_mm")):
            for sign in (-1, 1):
                poses = [LensPose(), LensPose()]
                poses[lens_id - 1] = replace(poses[lens_id - 1], **{field: sign * 0.15})
                cases.append((f"L{lens_id}_decenter_{axis}_{'plus' if sign > 0 else 'minus'}",
                              (poses[0], poses[1])))
        for axis, field in (("x", "tilt_x_deg"), ("y", "tilt_y_deg")):
            for sign in (-1, 1):
                poses = [LensPose(), LensPose()]
                poses[lens_id - 1] = replace(poses[lens_id - 1], **{field: sign * 0.30})
                cases.append((f"L{lens_id}_tilt_{axis}_{'plus' if sign > 0 else 'minus'}",
                              (poses[0], poses[1])))
        for sign in (-1, 1):
            poses = [LensPose(), LensPose()]
            poses[lens_id - 1] = LensPose(dz_mm=sign * 0.90)
            cases.append((f"L{lens_id}_axial_{'plus' if sign > 0 else 'minus'}",
                          (poses[0], poses[1])))
    cases.extend([
        ("composite_1", (LensPose(0.08, -0.04, 0.20, 0.18, -0.12),
                          LensPose(-0.06, 0.07, -0.30, -0.21, 0.13))),
        ("composite_2", (LensPose(-0.09, 0.03, -0.40, -0.15, 0.22),
                          LensPose(0.10, -0.05, 0.50, 0.24, -0.18))),
        ("composite_3", (LensPose(0.12, 0.02, 0.60, -0.22, -0.16),
                          LensPose(-0.11, -0.08, -0.70, 0.17, 0.25))),
        ("composite_4", (LensPose(-0.07, -0.12, -0.80, 0.26, 0.09),
                          LensPose(0.05, 0.13, 0.80, -0.25, -0.11))),
    ])
    return cases


def _probe_tangent(model) -> tuple[np.ndarray, np.ndarray]:
    lens = model.lenses[0]
    rad = lens.radius_front_mm
    aperture_edge = lens.clear_aperture_mm / 2.0 * 0.98
    z = rad - math.sqrt(rad * rad - aperture_edge * aperture_edge)
    hit = np.array([aperture_edge, 0.0, z])
    normal = (hit - np.array([0.0, 0.0, rad])) / abs(rad)
    direction = np.array([-normal[2], 0.0, normal[0]])
    direction /= np.linalg.norm(direction)
    world_hit_z = lens.front_vertex_z_mm + hit[2]
    origin = np.array([hit[0] - (world_hit_z / direction[2]) * direction[0],
                       0.0, 0.0])
    return origin, direction


def _negative_controls(model, s5_source_rows: list[dict[str, str]],
                       s5_pairs: dict[int, dict[str, str]]) -> list[dict[str, Any]]:
    controls: list[dict[str, Any]] = []

    def trace_probe(name: str, origin: np.ndarray, direction: np.ndarray,
                    expected: str, *, note: str = "full ray trace") -> None:
        ids = np.array([0], dtype=np.int64)
        org = origin.reshape(1, 3)
        dirs = direction.reshape(1, 3)
        w = np.array([1.0])
        try:
            a = trace_local(model, ids, org, dirs, w)
            b = trace_world(model, ids, org, dirs, w)
            cmp = compare_references(a, b)
            got = a.ray_rows[0]["terminal_outcome"]
            ill_count = sum(bool(x.get("ill_conditioned")) for x in a.surface_rows)
            ok = ((expected == "ILL_CONDITIONED" and ill_count > 0)
                  or got == expected)
            controls.append({"case_id": name, "scope": note, "expected": expected,
                             "local_outcome": got,
                             "world_outcome": b.ray_rows[0]["terminal_outcome"],
                             "independent_paths_match": cmp.status,
                             "ill_conditioned_surfaces": ill_count,
                             "weight_balance_local": a.ledger["balance_residual"],
                             "result": "PASS" if ok and cmp.status == "PASS" else "FAIL"})
        except Exception as exc:  # diagnostic failures are recorded, not hidden
            controls.append({"case_id": name, "scope": note, "expected": expected,
                             "error": f"{type(exc).__name__}: {exc}", "result": "FAIL"})

    trace_probe("outside_sphere_no_intersection", np.array([100.0, 0.0, 0.0]),
                np.array([0.0, 0.0, 1.0]), "NO_INTERSECTION")
    trace_probe("edge_clear_aperture_block", np.array([6.2, 0.0, 0.0]),
                np.array([0.0, 0.0, 1.0]), "L1_APERTURE_BLOCK")
    trace_probe("negative_z_source", np.zeros(3), np.array([0.0, 0.0, -1.0]), "INVALID_SOURCE")
    tangent_o, tangent_d = _probe_tangent(model)
    trace_probe("near_tangent_front_surface", tangent_o, tangent_d, "ILL_CONDITIONED",
                note="synthetic geometry diagnostic outside the registered fiber launch distribution")

    outside = next(row for row in s5_source_rows
                   if s5_pairs[int(row["ray_id"])]["baseline_capture"] == "0")
    trace_probe("fixed_target_outside", np.asarray([float(outside[f"{a}0_mm"]) for a in "xyz"]),
                np.asarray([float(outside[f"d{a}"]) for a in "xyz"]), "OUTSIDE_TARGET",
                note="S5 source ray reused only as a terminal-classification control")

    # Direct glass-to-air critical-angle probes exercise TIR in each independent Snell formula.
    theta = np.deg2rad(50.0)
    direction = np.array([np.sin(theta), 0.0, np.cos(theta)])
    normal = np.array([0.0, 0.0, -1.0])
    local_out, local_k, local_status = _refract_local(
        direction, normal, model.refractive_index, 1.0)
    world_out, world_k, world_status = _refract_world(
        direction, normal, model.refractive_index, 1.0)
    controls.append({"case_id": "snell_glass_to_air_tir", "scope": "interface-level synthetic Snell probe",
                     "expected": "TIR", "local_outcome": local_status, "world_outcome": world_status,
                     "local_k": local_k, "world_k": world_k,
                     "result": "PASS" if local_status == world_status == "TIR"
                     and local_out is None and world_out is None else "FAIL"})

    try:
        trace_local(model, [0], np.zeros((1, 3)), np.array([[0.0, 0.0, 1.0]]),
                    np.array([1.0]), target_z_mm=120.0)
        target_result = "FAIL"
    except S6GeometryError as exc:
        target_result = "PASS" if "TARGET_NOT_DOWNSTREAM" in str(exc) else "FAIL"
    controls.append({"case_id": "target_before_l2", "scope": "invalid geometry gate",
                     "expected": "INVALID_GEOMETRY", "result": target_result})

    bad_material = replace(model, lenses=(replace(model.lenses[0], material_id="BK7"), model.lenses[1]))
    try:
        trace_local(bad_material, [0], np.zeros((1, 3)), np.array([[0.0, 0.0, 1.0]]), np.array([1.0]))
        material_result = "FAIL"
    except S6GeometryError as exc:
        material_result = "PASS" if "MATERIAL_NOT_VERIFIED" in str(exc) else "FAIL"
    controls.append({"case_id": "unverified_material", "scope": "invalid model gate",
                     "expected": "REJECT", "result": material_result})

    overlap = invalid_geometry_reason(model, (LensPose(), LensPose(dz_mm=-100.0)))
    controls.append({"case_id": "l2_shift_through_l1", "scope": "clear-aperture envelope gate",
                     "expected": "INVALID_ASSEMBLY", "geometry_reason": overlap,
                     "result": "PASS" if overlap in {"SURFACE_SEQUENCE_OR_INTERSECTION",
                                                       "CLEAR_APERTURE_ENVELOPE_INTERSECTION"}
                     else "FAIL"})

    try:
        trace_local(model, [0], np.zeros((1, 3)), np.array([[0.0, 0.0, 1.0]]),
                    np.array([float("nan")]))
        weight_result = "FAIL"
    except S6GeometryError:
        weight_result = "PASS"
    controls.append({"case_id": "nan_weight", "scope": "invalid input gate",
                     "expected": "REJECT", "result": weight_result})
    return controls


def run() -> int:
    out = ROOT / "runs" / RUN_ID / "s6_a_reference"
    if out.exists():
        raise FileExistsError(f"refusing to overwrite existing S6-A evidence: {out}")
    out.mkdir(parents=True)
    model = _load_model()
    optics_bytes = (G4 / "optics_model.json").read_bytes()
    (out / "optics_model_snapshot.json").write_bytes(optics_bytes)
    (out / "baseline_design_config.yaml").write_bytes(
        (ROOT / "configs/pump976_g4_l0.yaml").read_bytes())

    # S5's 4,096-ray holdout is reused only for the frozen zero/axial reference gate.
    s5_source = _read_csv(S5 / "design_holdout_source_samples.csv")
    s5_pairs = {int(r["ray_id"]): r for r in _read_csv(S5 / "paired_samples.csv")}
    s5_ref = {(r["design_id"], int(r["ray_id"])): r
              for r in _read_csv(S5 / "design_holdout_ray_results.csv")}
    shutil.copyfile(S5 / "design_holdout_source_samples.csv", out / "source_samples_976053.csv")
    shutil.copyfile(S5 / "paired_samples.csv", out / "s5_paired_reference_976053.csv")
    shutil.copyfile(S5 / "design_holdout_ray_results.csv", out / "s5_ray_reference_976053.csv")
    ids, origins, directions, weights = _source_arrays(s5_source)
    zero_local = trace_local(model, ids, origins, directions, weights)
    zero_world = trace_world(model, ids, origins, directions, weights)
    plus10_pose = (LensPose(), LensPose(dz_mm=10.0))
    plus10_local = trace_local(model, ids, origins, directions, weights,
                               plus10_pose, target_z_mm=225.0)
    plus10_world = trace_world(model, ids, origins, directions, weights,
                               plus10_pose, target_z_mm=225.0)
    cmp_zero = compare_references(zero_local, zero_world)
    cmp_plus10 = compare_references(plus10_local, plus10_world)
    zero_mismatch = 0
    plus10_mismatch = 0
    max_s5_target_delta = 0.0
    reconciliation: list[dict[str, Any]] = []
    world_zero_by_id = {r["ray_id"]: r for r in zero_world.ray_rows}
    world_135_by_id = {r["ray_id"]: r for r in plus10_world.ray_rows}
    for a, b in zip(zero_local.ray_rows, plus10_local.ray_rows, strict=True):
        rid = a["ray_id"]
        expected = s5_pairs[rid]
        s5_base = s5_ref[("baseline", rid)]
        s5_135 = s5_ref[("s5_equal_aperture_candidate", rid)]
        zero_mismatch += int(a["terminal_outcome"] != expected["baseline_terminal_outcome"])
        plus10_mismatch += int(b["terminal_outcome"] != expected["candidate_terminal_outcome"])
        if a["target_x"] is not None:
            max_s5_target_delta = max(max_s5_target_delta,
                abs(a["target_x"] - float(s5_base["target_x_mm"])),
                abs(a["target_y"] - float(s5_base["target_y_mm"])))
        if b["target_x"] is not None:
            max_s5_target_delta = max(max_s5_target_delta,
                abs(b["target_x"] - float(s5_135["target_x_mm"])),
                abs(b["target_y"] - float(s5_135["target_y_mm"])))
        reconciliation.append({
            "ray_id": rid, "source_weight": float(a["source_weight"]),
            "s5_baseline_outcome": expected["baseline_terminal_outcome"],
            "s6_local_baseline_outcome": a["terminal_outcome"],
            "s6_world_baseline_outcome": world_zero_by_id[rid]["terminal_outcome"],
            "s5_135_outcome": expected["candidate_terminal_outcome"],
            "s6_local_135_outcome": b["terminal_outcome"],
            "s6_world_135_outcome": world_135_by_id[rid]["terminal_outcome"],
            "baseline_target_x_mm": a["target_x"], "baseline_target_y_mm": a["target_y"],
            "candidate_target_x_mm": b["target_x"], "candidate_target_y_mm": b["target_y"],
            "fixed_target_z_mm": 225.0,
        })
    _write_csv(out / "s5_zero_and_axial_reconciliation.csv", reconciliation)

    # Synthetic new source and explicit axis/field/NA probes; no 976053 holdout reuse here.
    new_rays = sample_multimode_fiber(512, 0.105, 0.22, seed=8065001)
    matrix_rows: list[dict[str, Any]] = []
    matrix_ray_rows: list[dict[str, Any]] = []
    representative_surfaces: list[dict[str, Any]] = []
    for case_id, poses in _pose_cases():
        local = trace_local(model, new_rays.ray_id, new_rays.origin_mm,
                            new_rays.direction, new_rays.weight, poses)
        world = trace_world(model, new_rays.ray_id, new_rays.origin_mm,
                            new_rays.direction, new_rays.weight, poses)
        comparison = compare_references(local, world)
        matrix_rows.append({"case_id": case_id, "poses_json": json.dumps([asdict(p) for p in poses], sort_keys=True),
                            "n_rays": new_rays.n_rays, "comparison": asdict(comparison),
                            "capture_local": local.ledger["capture_fraction_input"],
                            "capture_world": world.ledger["capture_fraction_input"],
                            "terminal_counts_local": json.dumps(local.ledger["terminal_count"], sort_keys=True),
                            "terminal_counts_world": json.dumps(world.ledger["terminal_count"], sort_keys=True),
                            "source_weight_total": local.ledger["source_weight_total"],
                            "ledger_status_local": local.ledger["status"],
                            "ledger_status_world": world.ledger["status"]})
        for route, result in (("local", local), ("world", world)):
            for row in result.ray_rows:
                matrix_ray_rows.append({"case_id": case_id, **row})
        chosen = set(int(x) for x in new_rays.ray_id[:12])
        for route, result in (("local", local), ("world", world)):
            representative_surfaces.extend({"case_id": case_id, **r}
                                           for r in result.surface_rows if r["ray_id"] in chosen)
    _write_csv(out / "noncoaxial_matrix_rays.csv", matrix_ray_rows)
    _write_csv(out / "representative_surface_traces.csv", representative_surfaces)

    controls = _negative_controls(model, s5_source, s5_pairs)
    _write_csv(out / "adversarial_controls.csv", controls)
    # Store nested pose/result objects as canonical JSON cells for CSV portability.
    for row in matrix_rows:
        row["poses_json"] = json.dumps(json.loads(row["poses_json"]), sort_keys=True)
        row["comparison"] = json.dumps(row["comparison"], sort_keys=True)
    _write_csv(out / "noncoaxial_reference_matrix.csv", matrix_rows)

    matrix_statuses = [json.loads(r["comparison"])['status'] for r in matrix_rows]
    max_hit = max(json.loads(r["comparison"])['max_hit_delta_mm'] for r in matrix_rows)
    max_direction = max(json.loads(r["comparison"])['max_direction_delta'] for r in matrix_rows)
    controls_pass = all(r["result"] == "PASS" for r in controls)
    status = ("PASS" if zero_mismatch == 0 and plus10_mismatch == 0
              and max_s5_target_delta <= 1e-6 and cmp_zero.status == "PASS"
              and cmp_plus10.status == "PASS" and all(x == "PASS" for x in matrix_statuses)
              and controls_pass else "FAIL")
    summary = {
        "schema": "optisys.s6.a_reference_summary/1", "run_id": RUN_ID,
        "status": status, "evidence_level": "MODEL_CROSS_CHECKED" if status == "PASS" else "ASSUMED_MODEL",
        "reference_routes": {
            "local": "local sphere roots + local normal + independent local Snell; transform output to world",
            "world": "transformed sphere center/axis + world sphere roots + independent world Snell",
            "shared": "prescription inputs, rigid-pose definition, terminal state names and weight ledger only",
        },
        "s5_holdout_reference_only": {
            "source_rays": int(ids.size), "seed": 976053, "use": "zero/axial equivalence only; excluded from B/C",
            "baseline_local_s5_outcome_mismatches": zero_mismatch,
            "position135_local_s5_outcome_mismatches": plus10_mismatch,
            "max_target_coordinate_delta_mm": max_s5_target_delta,
            "captured_baseline": _capture_n(zero_local), "captured_position135": _capture_n(plus10_local),
            "fixed_target_z_mm": 225.0,
            "baseline_capture_fraction": zero_local.ledger["capture_fraction_input"],
            "position135_capture_fraction": plus10_local.ledger["capture_fraction_input"],
            "paired_capture_delta": plus10_local.ledger["capture_fraction_input"] - zero_local.ledger["capture_fraction_input"],
        },
        "zero_reference_local_world": asdict(cmp_zero),
        "l2_plus_10_local_world": asdict(cmp_plus10),
        "noncoaxial_matrix": {"case_count": len(matrix_rows), "rays_per_case": new_rays.n_rays,
                              "all_statuses_pass": all(x == "PASS" for x in matrix_statuses),
                              "max_hit_delta_mm": max_hit,
                              "max_direction_delta": max_direction},
        "adversarial_controls": {"count": len(controls), "pass": sum(x["result"] == "PASS" for x in controls),
                                 "fail": sum(x["result"] != "PASS" for x in controls)},
        "outputs": ["s5_zero_and_axial_reconciliation.csv", "noncoaxial_reference_matrix.csv",
                    "noncoaxial_matrix_rays.csv", "representative_surface_traces.csv",
                    "adversarial_controls.csv"],
        "model_limits": ["assumed N-BK7 geometry; not vendor lens qualification",
                         "clear-aperture envelope overlap is conservative, not mechanical collision proof",
                         "TIR control is an interface-level synthetic Snell probe"],
        "finished_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (out / "s6_a_reference_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"S6_A_RIGID_BODY_REFERENCE": status,
                      "s5_zero_mismatches": zero_mismatch, "s5_135_mismatches": plus10_mismatch,
                      "s5_baseline_capture": summary["s5_holdout_reference_only"]["baseline_capture_fraction"],
                      "s5_135_capture": summary["s5_holdout_reference_only"]["position135_capture_fraction"],
                      "matrix_cases": len(matrix_rows), "matrix_max_hit_delta_mm": max_hit,
                      "matrix_max_direction_delta": max_direction,
                      "negative_controls": summary["adversarial_controls"]}, ensure_ascii=False, indent=2))
    return 0 if status == "PASS" else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args()
    start = time.perf_counter()
    code = run()
    print(f"outer_wall_s={time.perf_counter() - start:.3f}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
