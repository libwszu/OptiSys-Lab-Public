"""P1 optical smoke and low-angle independent cross-check."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from optisys.config_g4 import load_pump976_config
from optisys.evaluation.pump_metrics import target_plane_metrics
from optisys.optics.pump_beamline import trace_thin_lens
from optisys.optics.pump_optiland import OptilandPumpTracer
from optisys.sources.multimode_fiber import sample_multimode_fiber

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize("config_name", ["pump976_g4_l0.yaml", "pump976_g4_l1.yaml"])
def test_optiland_traces_actual_two_singlets_and_conserves_weight(config_name: str) -> None:
    config = load_pump976_config(ROOT / "configs" / config_name)
    bundle = sample_multimode_fiber(512, config.core_diameter_mm, 0.05, seed=976051)
    result = OptilandPumpTracer(config.beamline, wavelength_nm=976.0).trace(bundle)
    assert result.backend_version == "0.6.3"
    assert result.status == "OK"
    assert result.n_launched == 512
    assert result.n_valid == 512
    assert len(result.lens_models) == 2
    assert result.ledger["balance_residual"] == pytest.approx(0.0, abs=1e-10)
    p0 = trace_thin_lens(bundle, config.beamline)
    m0, _ = target_plane_metrics(p0)
    good = result.valid
    x, y, w = result.x_mm[good], result.y_mm[good], result.weight_out[good]
    total = w.sum()
    cx, cy = (w * x).sum() / total, (w * y).sum() / total
    r = np.hypot(x - cx, y - cy)
    order = np.argsort(r)
    r80 = float(r[order][np.searchsorted(np.cumsum(w[order]), 0.8 * total)])
    assert abs(r80 - m0["r80_mm"]) / m0["r80_mm"] <= 0.10


def test_high_na_p1_difference_is_retained_and_weighted_by_source() -> None:
    config = load_pump976_config(ROOT / "configs/pump976_g4_l0.yaml")
    bundle = sample_multimode_fiber(2048, config.core_diameter_mm, 0.22, seed=976051)
    result = OptilandPumpTracer(config.beamline, wavelength_nm=976.0).trace(bundle)
    assert result.status == "OK"
    assert result.ledger["source_weight_total"] == pytest.approx(1.0, abs=1e-12)
    assert result.ledger["transmitted_weight"] < 1.0
    assert result.ledger["outside_target_weight"] > 0.0
    assert result.ledger["balance_residual"] == pytest.approx(0.0, abs=1e-10)


def test_unverified_material_label_is_rejected_before_optiland_build() -> None:
    config = load_pump976_config(ROOT / "configs/pump976_g4_l0.yaml")
    with pytest.raises(ValueError, match="MATERIAL_NOT_VERIFIED"):
        OptilandPumpTracer(config.beamline, wavelength_nm=976.0, material="BK7")


def test_bk7_formula_rejects_wavelength_outside_verified_catalog_range() -> None:
    from optisys.optics.pump_optiland import sellmeier_n_bk7

    with pytest.raises(ValueError, match="verified 300-2500 nm"):
        sellmeier_n_bk7(2600.0)
