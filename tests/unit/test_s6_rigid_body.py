"""Independent S6 local/world rigid-body sphere and Snell checks."""

from __future__ import annotations

import csv
import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
import yaml

from optisys.optics.s5_reference import build_model
from optisys.optics.s6_rigid_body import (
    LensPose,
    S6GeometryError,
    compare_references,
    invalid_geometry_reason,
    lens_pose_transform,
    rotation_matrix,
    trace_local,
    trace_world,
)
from optisys.sources.multimode_fiber import sample_multimode_fiber

ROOT = Path(__file__).resolve().parents[2]
S5 = ROOT / "runs/20261020_210201_S5_HNA"
G4 = ROOT / "runs/20261020_133555_G4_ec3e2813_0e48"


def _model():
    optics = json.loads((G4 / "optics_model.json").read_text(encoding="utf-8"))
    config = yaml.safe_load((ROOT / "configs/pump976_g4_l0.yaml").read_text(encoding="utf-8"))
    return build_model(optics, config)


def _sample(n: int = 512):
    return sample_multimode_fiber(n, 0.105, 0.22, seed=8065001)


def test_rigid_transform_is_proper_and_pivots_at_front_vertex() -> None:
    model = _model()
    pose = LensPose(0.12, -0.08, 0.3, 0.2, -0.17, 19.0)
    r, t = lens_pose_transform(model.lenses[0], pose)
    assert np.max(np.abs(r.T @ r - np.eye(3))) <= 1e-12
    assert abs(np.linalg.det(r) - 1.0) <= 1e-12
    assert t == pytest.approx([0.12, -0.08, model.lenses[0].front_vertex_z_mm + 0.3])
    local = np.array([1.1, -0.7, 2.0])
    world = r @ local + t
    assert r.T @ (world - t) == pytest.approx(local, abs=1e-12)
    assert r.T @ (r @ np.array([0.2, 0.1, 1.0])) == pytest.approx([0.2, 0.1, 1.0])


@pytest.mark.parametrize(
    "poses",
    [
        (LensPose(dx_mm=0.15), LensPose()),
        (LensPose(dx_mm=-0.15), LensPose()),
        (LensPose(dy_mm=0.15), LensPose()),
        (LensPose(dy_mm=-0.15), LensPose()),
        (LensPose(), LensPose(dx_mm=0.15)),
        (LensPose(), LensPose(dx_mm=-0.15)),
        (LensPose(tilt_x_deg=0.30), LensPose()),
        (LensPose(tilt_x_deg=-0.30), LensPose()),
        (LensPose(), LensPose(tilt_y_deg=0.30)),
        (LensPose(), LensPose(tilt_y_deg=-0.30)),
        (LensPose(0.08, -0.04, 0.2, 0.18, -0.12), LensPose(-0.06, 0.07, -0.3, -0.21, 0.13)),
        (LensPose(-0.09, 0.03, -0.4, -0.15, 0.22), LensPose(0.10, -0.05, 0.5, 0.24, -0.18)),
    ],
)
def test_independent_local_and_world_paths_match_for_noncoaxial_poses(poses) -> None:
    model = _model()
    rays = _sample(256)
    local = trace_local(model, rays.ray_id, rays.origin_mm, rays.direction, rays.weight, poses)
    world = trace_world(model, rays.ray_id, rays.origin_mm, rays.direction, rays.weight, poses)
    comp = compare_references(local, world)
    assert comp.status == "PASS"
    assert comp.terminal_mismatch_count == 0
    assert comp.hit_mismatch_count == 0
    assert comp.max_hit_delta_mm <= 1e-7
    assert comp.max_direction_delta <= 1e-8
    assert local.ledger["balance_residual"] == pytest.approx(0.0, abs=1e-12)
    assert world.ledger["balance_residual"] == pytest.approx(0.0, abs=1e-12)


def test_zero_and_l2_plus_ten_reproduce_s5_4096_ray_holdout() -> None:
    model = _model()
    with (S5 / "design_holdout_source_samples.csv").open(encoding="utf-8-sig", newline="") as f:
        source = list(csv.DictReader(f))
    with (S5 / "paired_samples.csv").open(encoding="utf-8-sig", newline="") as f:
        paired = {int(row["ray_id"]): row for row in csv.DictReader(f)}
    with (S5 / "design_holdout_ray_results.csv").open(encoding="utf-8-sig", newline="") as f:
        reference = {(row["design_id"], int(row["ray_id"])): row for row in csv.DictReader(f)}
    ids = np.asarray([int(row["ray_id"]) for row in source], dtype=np.int64)
    origins = np.asarray([[float(row[f"{axis}0_mm"]) for axis in "xyz"] for row in source])
    directions = np.asarray([[float(row[f"d{axis}"]) for axis in "xyz"] for row in source])
    weights = np.asarray([float(row["weight"]) for row in source])

    base = trace_local(model, ids, origins, directions, weights)
    moved = trace_local(model, ids, origins, directions, weights,
                        (LensPose(), LensPose(dz_mm=10.0)), target_z_mm=225.0)
    local_world = compare_references(
        base, trace_world(model, ids, origins, directions, weights))
    assert local_world.status == "PASS"
    for ray in base.ray_rows:
        rid = ray["ray_id"]
        assert ray["terminal_outcome"] == paired[rid]["baseline_terminal_outcome"]
        old = reference[("baseline", rid)]
        if ray["target_x"] is not None:
            assert ray["target_x"] == pytest.approx(float(old["target_x_mm"]), abs=1e-6)
            assert ray["target_y"] == pytest.approx(float(old["target_y_mm"]), abs=1e-6)
    for ray in moved.ray_rows:
        rid = ray["ray_id"]
        assert ray["target_z_mm"] == pytest.approx(225.0)
        assert ray["terminal_outcome"] == paired[rid]["candidate_terminal_outcome"]
        new = reference[("s5_equal_aperture_candidate", rid)]
        if ray["target_x"] is not None:
            assert ray["target_x"] == pytest.approx(float(new["target_x_mm"]), abs=1e-6)
            assert ray["target_y"] == pytest.approx(float(new["target_y_mm"]), abs=1e-6)
    assert base.ledger["terminal_count"].get("CAPTURED", 0) == 2707
    assert moved.ledger["terminal_count"].get("CAPTURED", 0) == 3566


def test_aperture_target_and_invalid_source_remain_in_weight_ledger() -> None:
    model = _model()
    out_of_aperture = trace_local(
        model, [1], np.array([[6.2, 0.0, 0.0]]), np.array([[0.0, 0.0, 1.0]]), np.array([1.0]))
    assert out_of_aperture.ray_rows[0]["terminal_outcome"] == "L1_APERTURE_BLOCK"
    assert out_of_aperture.ledger["balance_residual"] == pytest.approx(0.0, abs=1e-12)
    reverse = trace_world(
        model, [2], np.zeros((1, 3)), np.array([[0.0, 0.0, -1.0]]), np.array([1.0]))
    assert reverse.ray_rows[0]["terminal_outcome"] == "INVALID_SOURCE"
    assert reverse.ledger["terminal_weight"]["INVALID_SOURCE"] == 1.0


def test_invalid_model_pose_target_nan_and_weight_are_rejected() -> None:
    model = _model()
    rays = _sample(4)
    with pytest.raises(S6GeometryError, match="MATERIAL_NOT_VERIFIED"):
        trace_local(replace(model, lenses=(replace(model.lenses[0], material_id="BK7"), model.lenses[1])),
                    rays.ray_id, rays.origin_mm, rays.direction, rays.weight)
    bad_pose = (LensPose(dx_mm=float("nan")), LensPose())
    assert invalid_geometry_reason(model, bad_pose) == "INVALID_MODEL_OR_POSE"
    with pytest.raises(S6GeometryError, match="non-finite"):
        trace_local(model, rays.ray_id, rays.origin_mm, rays.direction, rays.weight, bad_pose)
    with pytest.raises(S6GeometryError, match="TARGET_NOT_DOWNSTREAM"):
        trace_world(model, rays.ray_id, rays.origin_mm, rays.direction, rays.weight,
                    target_z_mm=120.0)
    with pytest.raises(S6GeometryError, match="NaN or infinity"):
        trace_local(model, rays.ray_id, rays.origin_mm, rays.direction, np.array([1.0, 1.0, np.nan, 1.0]))
    with pytest.raises(S6GeometryError, match="strictly positive"):
        trace_world(model, rays.ray_id, rays.origin_mm, rays.direction, np.array([1.0, 1.0, -0.1, 1.0]))


def test_roll_has_no_effect_on_axisymmetric_on_axis_ray() -> None:
    model = _model()
    ids = np.array([0], dtype=np.int64)
    origins = np.zeros((1, 3))
    directions = np.array([[0.0, 0.0, 1.0]])
    weights = np.array([1.0])
    plain = trace_local(model, ids, origins, directions, weights)
    rolled = trace_local(model, ids, origins, directions, weights,
                         (LensPose(roll_z_deg=37.0), LensPose(roll_z_deg=-19.0)))
    assert plain.ray_rows[0]["target_x"] == pytest.approx(rolled.ray_rows[0]["target_x"], abs=1e-12)
    assert plain.ray_rows[0]["target_y"] == pytest.approx(rolled.ray_rows[0]["target_y"], abs=1e-12)
