"""Independent S5 sphere/Snell reference and adversarial checks."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest
import yaml

from optisys.optics.s5_reference import (
    MaterialNotVerified,
    ReferenceModelError,
    Singlet,
    _snell,
    _sphere_intersection,
    build_model,
    lens_geometry_rows,
    n_bk7_sellmeier,
    singlet_edge_thickness_mm,
    spherical_sag_mm,
    trace_rays,
)

ROOT = Path(__file__).resolve().parents[2]
G4 = ROOT / "runs/20261020_133555_G4_ec3e2813_0e48"


def _model(design: str = "baseline"):
    optics = json.loads((G4 / "optics_model.json").read_text(encoding="utf-8"))
    cfg_name = "pump976_g4_l0.yaml" if design == "baseline" else "pump976_g4_l1.yaml"
    config = yaml.safe_load((ROOT / "configs" / cfg_name).read_text(encoding="utf-8"))
    return build_model(optics, config)


def test_bk7_index_and_frozen_geometry_reconciliation() -> None:
    assert n_bk7_sellmeier(976.0) == pytest.approx(1.5078427267710073, abs=1e-14)
    model = _model()
    assert [x.surface_id for x in model.surfaces] == [
        "L1_FRONT", "L1_REAR", "L2_FRONT", "L2_REAR"
    ]
    assert model.surfaces[0].vertex_z_mm == pytest.approx(24.32776280278125)
    rows = lens_geometry_rows(model)
    assert rows[0]["edge_thickness_mm"] == pytest.approx(0.5416935, abs=1e-6)
    assert rows[0]["status"] == "GEOMETRY_VALID_ASSUMED"
    candidate = lens_geometry_rows(_model("engineering_candidate"))
    assert candidate[0]["edge_thickness_mm"] == pytest.approx(0.1581931, abs=1e-6)
    assert candidate[0]["status"] == "EDGE_THICKNESS_ASSUMED_LOW"
    assert candidate[0]["outer_diameter_mm"] == "UNSPECIFIED"


def test_material_and_dispersion_range_are_explicitly_rejected() -> None:
    with pytest.raises(MaterialNotVerified, match="MATERIAL_NOT_VERIFIED"):
        n_bk7_sellmeier(976.0, "BK7-alias")
    with pytest.raises(ReferenceModelError, match="300-2500"):
        n_bk7_sellmeier(2600.0)


def test_vector_snell_normal_incidence_oblique_and_total_internal_reflection() -> None:
    out, k, status = _snell(np.array([0.0, 0.0, 1.0]), np.array([0.0, 0.0, -1.0]), 1.0, 1.5)
    assert status == "PASS" and k == pytest.approx(1.0)
    assert out == pytest.approx([0.0, 0.0, 1.0])

    theta_air = np.deg2rad(30.0)
    direction = np.array([np.sin(theta_air), 0.0, np.cos(theta_air)])
    out, _, status = _snell(direction, np.array([0.0, 0.0, -1.0]), 1.0, 1.5)
    assert status == "PASS"
    assert 1.0 * np.sin(theta_air) == pytest.approx(1.5 * np.sin(np.arctan2(out[0], out[2])))

    theta_glass = np.deg2rad(50.0)
    incoming = np.array([np.sin(theta_glass), 0.0, np.cos(theta_glass)])
    out, k, status = _snell(incoming, np.array([0.0, 0.0, -1.0]), 1.5, 1.0)
    assert out is None and k < 0 and status == "TIR_OR_REFRACTION_FAILURE"


def test_sphere_axis_and_off_axis_hits_residual_and_wrong_hemisphere_rejection() -> None:
    surface = _model().surfaces[0]
    t, hit, residual, discriminant, status = _sphere_intersection(
        np.array([0.0, 0.0, 0.0]), np.array([0.0, 0.0, 1.0]), surface
    )
    assert status == "PASS" and t == pytest.approx(surface.vertex_z_mm)
    assert hit == pytest.approx([0.0, 0.0, surface.vertex_z_mm])
    assert residual <= 1e-12 and discriminant > 0

    theta = np.deg2rad(11.0)
    t, hit, residual, _, status = _sphere_intersection(
        np.array([0.03, -0.02, 0.0]), np.array([np.sin(theta), 0.0, np.cos(theta)]), surface
    )
    assert status == "PASS" and t > 0 and residual <= 1e-8
    assert hit[0]**2 + hit[1]**2 <= surface.semi_aperture_mm**2

    no_forward, no_hit, _, _, status = _sphere_intersection(
        np.array([0.0, 0.0, surface.vertex_z_mm + 1.0]), np.array([0.0, 0.0, 1.0]), surface
    )
    assert no_forward is None and no_hit is None and status == "NO_INTERSECTION"


def test_full_path_ray_ledger_and_rejection_of_invalid_inputs() -> None:
    model = _model()
    angles = np.deg2rad([0.0, 3.0, 6.0, 9.0, 11.0, 12.7099])
    origins = np.zeros((len(angles), 3))
    directions = np.column_stack((np.sin(angles), np.zeros(len(angles)), np.cos(angles)))
    weights = np.full(len(angles), 1.0 / len(angles))
    surface_rows, ray_rows, ledger = trace_rays(model, range(len(angles)), origins, directions, weights)
    assert len(surface_rows) == len(angles) * 4
    assert len(ray_rows) == len(angles)
    assert ledger["status"] == "PASS"
    assert ledger["classified_ray_count"] == len(angles)
    assert ledger["unique_ray_count"] == len(angles)
    assert ledger["balance_residual"] == pytest.approx(0.0, abs=1e-12)
    assert sum(row["source_weight"] for row in ray_rows) == pytest.approx(1.0)

    with pytest.raises(ReferenceModelError, match="strictly positive"):
        trace_rays(model, range(2), np.zeros((2, 3)), np.tile([0, 0, 1], (2, 1)),
                   np.array([1.0, -0.1]))
    with pytest.raises(ReferenceModelError, match="unique ray IDs"):
        trace_rays(model, [0, 0], np.zeros((2, 3)), np.tile([0, 0, 1], (2, 1)),
                   np.array([0.5, 0.5]))
    with pytest.raises(ReferenceModelError, match="downstream"):
        trace_rays(model, [0], np.zeros((1, 3)), np.array([[0.0, 0.0, 1.0]]),
                   np.array([1.0]), target_z_mm=1.0)


def test_aperture_blocks_are_mutually_exclusive_and_ledger_closes() -> None:
    model = _model()
    l1_small = replace(model.lenses[0], clear_aperture_mm=0.05)
    l1_block_model = replace(model, lenses=(l1_small, model.lenses[1]))
    surface_rows, rays, ledger = trace_rays(
        l1_block_model, [11], np.array([[0.06, 0.0, 0.0]]),
        np.array([[0.0, 0.0, 1.0]]), np.array([1.0])
    )
    assert rays[0]["terminal_outcome"] == "APERTURE_BLOCKED_L1"
    assert ledger["captured_weight"] == 0.0
    assert ledger["aperture_blocked_l1_weight"] == 1.0
    assert ledger["balance_residual"] == pytest.approx(0.0, abs=1e-12)
    assert sum(row["status"] == "APERTURE_BLOCKED_L1" for row in surface_rows) == 1
    assert sum(row["status"] == "NOT_REACHED_AFTER_APERTURE_BLOCKED_L1" for row in surface_rows) == 3

    l2_small = replace(model.lenses[1], clear_aperture_mm=0.10)
    l2_block_model = replace(model, lenses=(model.lenses[0], l2_small))
    theta = np.deg2rad(6.0)
    _, rays, ledger = trace_rays(
        l2_block_model, [12], np.zeros((1, 3)),
        np.array([[np.sin(theta), 0.0, np.cos(theta)]]), np.array([1.0])
    )
    assert rays[0]["terminal_outcome"] == "APERTURE_BLOCKED_L2"
    assert ledger["aperture_blocked_l2_weight"] == 1.0
    assert ledger["balance_residual"] == pytest.approx(0.0, abs=1e-12)


def test_non_forward_direction_is_classified_as_invalid_source() -> None:
    _, rays, ledger = trace_rays(
        _model(), [1], np.zeros((1, 3)), np.array([[0.0, 0.0, -1.0]]), np.array([1.0])
    )
    assert rays[0]["terminal_outcome"] == "INVALID_SOURCE"
    assert ledger["invalid_source_weight"] == 1.0
    assert ledger["balance_residual"] == pytest.approx(0.0, abs=1e-12)


def test_geometry_rejects_radius_at_or_inside_semi_aperture() -> None:
    with pytest.raises(ReferenceModelError, match="semi-aperture"):
        spherical_sag_mm(5.0, 5.0)
    lens = Singlet("invalid", 20.0, 10.0, 0.1, "N-BK7", 1.5,
                   6.0, -6.0, 0.0, 0.1)
    assert singlet_edge_thickness_mm(lens) < 0.0
