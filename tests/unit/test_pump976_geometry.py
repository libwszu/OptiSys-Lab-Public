"""G4 P0 thin-lens geometry and weight-accounting checks."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from optisys.config_g4 import PumpConfigError, load_pump976_config
from optisys.evaluation.pump_metrics import target_plane_metrics
from optisys.optics.pump_beamline import BeamlineConfig, trace_thin_lens, trace_thin_lens_scalar_reference
from optisys.sources.multimode_fiber import sample_multimode_fiber

ROOT = Path(__file__).resolve().parents[2]


def _baseline():
    return load_pump976_config(ROOT / "configs/pump976_g4_l0.yaml")


def test_vectorized_p0_matches_independent_scalar_reference() -> None:
    config = _baseline()
    bundle = sample_multimode_fiber(4096, 0.105, 0.22, seed=37)
    vector = trace_thin_lens(bundle, config.beamline)
    scalar = trace_thin_lens_scalar_reference(bundle, config.beamline)
    valid = np.isin(vector.status, ["OK", "OUTSIDE_TARGET"])
    np.testing.assert_allclose(vector.target_x_mm[valid], scalar["target_x_mm"][valid], atol=1e-10, rtol=0)
    np.testing.assert_allclose(vector.target_y_mm[valid], scalar["target_y_mm"][valid], atol=1e-10, rtol=0)
    np.testing.assert_allclose(vector.direction_out[valid], scalar["target_direction"][valid], atol=1e-12, rtol=0)


def test_aperture_loss_keeps_original_source_denominator() -> None:
    config = _baseline()
    bundle = sample_multimode_fiber(8192, 0.105, 0.22, seed=72)
    open_trace = trace_thin_lens(bundle, config.beamline)
    closed_l1 = replace(config.beamline.l1, aperture_diameter_mm=8.0)
    blocked_trace = trace_thin_lens(bundle, replace(config.beamline, l1=closed_l1))
    assert blocked_trace.ledger["l1_blocked_weight"] > 0.0
    assert blocked_trace.ledger["transmitted_weight"] < open_trace.ledger["transmitted_weight"]
    assert blocked_trace.ledger["source_weight_total"] == pytest.approx(1.0, abs=1e-12)
    assert blocked_trace.ledger["balance_residual"] == pytest.approx(0.0, abs=1e-12)


def test_target_metrics_density_and_energy_ledger_close() -> None:
    config = _baseline()
    bundle = sample_multimode_fiber(4096, 0.105, 0.22, seed=73)
    trace = trace_thin_lens(bundle, config.beamline)
    metrics, density = target_plane_metrics(trace)
    assert metrics["geometric_transmission_fraction"] == pytest.approx(1.0)
    assert metrics["density_integral_input_denominator"] == pytest.approx(
        metrics["geometric_transmission_fraction"], abs=1e-8)
    assert metrics["r80_mm"] <= metrics["r90_mm"]
    assert abs(trace.ledger["balance_residual"]) <= 1e-10
    assert metrics["units"]["density"] == "weight_fraction/mm^2"
    assert density["weight_histogram"].sum() == pytest.approx(1.0, abs=1e-12)


def test_zero_transmitted_weight_is_not_reported_as_zero_spot() -> None:
    config = _baseline()
    tiny_target = replace(config.beamline, target_radius_mm=1e-6)
    bundle = sample_multimode_fiber(64, 0.105, 0.22, seed=75)
    trace = trace_thin_lens(bundle, tiny_target)
    assert not np.any(trace.status == "OK")
    metrics, density = target_plane_metrics(trace)
    assert metrics["status"] == "NOT_EVALUABLE"
    assert metrics["r80_mm"] is None and metrics["r90_mm"] is None
    assert density == {}


def test_invalid_geometry_and_order_are_rejected() -> None:
    config = _baseline()
    invalid = replace(config.beamline, target_z_mm=config.beamline.l2.z_mm)
    with pytest.raises(ValueError, match="downstream"):
        invalid.validate()
    invalid_lens = replace(config.beamline.l2, z_mm=config.beamline.l1.z_mm - 1)
    with pytest.raises(ValueError, match="overlap"):
        BeamlineConfig(config.beamline.l1, invalid_lens,
                       config.beamline.target_z_mm, config.beamline.target_radius_mm).validate()


def test_pump_config_rejects_wrong_units_and_unsupported_na(tmp_path) -> None:
    path = ROOT / "configs/pump976_g4_l0.yaml"
    text = path.read_text(encoding="utf-8")
    bad_units = tmp_path / "bad_units.yaml"
    bad_units.write_text(text.replace("distance: mm", "distance: cm"), encoding="utf-8")
    with pytest.raises(PumpConfigError, match="core units"):
        load_pump976_config(bad_units)
    bad_na = tmp_path / "bad_na.yaml"
    bad_na.write_text(text.replace("numerical_aperture: 0.22", "numerical_aperture: 1.1"), encoding="utf-8")
    with pytest.raises(PumpConfigError, match="NA"):
        load_pump976_config(bad_na)
