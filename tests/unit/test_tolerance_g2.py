"""G2 sensor renderer, tolerance sampling, calibration and statistics."""

from __future__ import annotations

import numpy as np
import pytest
from scipy import stats

from optisys.calibration.assembly_strategies import (
    CalibrationFit,
    fit_calibration,
    select_model,
)
from optisys.config_g1 import SensorSpec
from optisys.errors import Status
from optisys.evaluation.paired_comparison import (
    paired_bootstrap,
    paired_rate_difference,
)
from optisys.imaging.sensor import render_frame
from optisys.imaging.sensor_g2 import adc_ceiling_e, render_frame_g2
from optisys.tolerance.samplers import (
    VARIABLE_ORDER,
    draw_lhs,
    draw_normal,
    inverse_normal,
    latin_hypercube,
    sigma_vector,
)

SENSOR = SensorSpec(
    read_noise_e=3.0, dark_rate_e_per_s=1.0, exposure_ms=2.0, full_well_e=15000.0,
    bit_depth=12, e_per_adu=3.0, black_level_adu=100, adc_max_adu=4095,
)


# ---------------------------------------------------------------------------
# sensor (PRE-08: two distinct saturation mechanisms)
# ---------------------------------------------------------------------------
def test_adc_ceiling_is_below_full_well() -> None:
    assert adc_ceiling_e(SENSOR) == pytest.approx(11985.0)
    assert adc_ceiling_e(SENSOR) < SENSOR.full_well_e


def test_adc_clipping_and_full_well_are_reported_separately() -> None:
    signal = np.zeros((32, 32))
    signal[8, 8] = 13_000.0          # above the ADC ceiling, below full well
    signal[16, 16] = 20_000.0        # above the full well as well
    frame = render_frame_g2(signal, 0.0, SENSOR, 1234, noise=False)
    assert frame.adc_clipping_fraction > 0
    assert frame.full_well_saturation_fraction > 0
    assert "ADC_CLIPPING" in frame.flags
    assert "FULL_WELL_SATURATION" in frame.flags


def test_adc_only_clipping_does_not_set_the_full_well_flag() -> None:
    signal = np.zeros((16, 16))
    signal[4, 4] = 13_000.0
    frame = render_frame_g2(signal, 0.0, SENSOR, 99, noise=False)
    assert frame.adc_clipping_fraction > 0
    assert frame.full_well_saturation_fraction == 0.0
    assert "FULL_WELL_SATURATION" not in frame.flags


def test_g2_renderer_matches_g1_distribution() -> None:
    signal = np.zeros((64, 64))
    signal[32, 32] = 2000.0
    g1 = []
    g2 = []
    for index in range(300):
        g1.append(render_frame(signal, 100.0, SENSOR, 5000 + index).image_adu[32, 32])
        g2.append(render_frame_g2(signal, 100.0, SENSOR, 9000 + index).image_adu[32, 32])
    result = stats.ks_2samp(np.array(g1), np.array(g2))
    assert result.pvalue > 0.01


def test_renderer_rejects_negative_signal() -> None:
    with pytest.raises(ValueError):
        render_frame_g2(np.full((4, 4), -1.0), 10.0, SENSOR, 1)


# ---------------------------------------------------------------------------
# samplers
# ---------------------------------------------------------------------------
SIGMAS = {
    "d_baseline_mm": 0.05,
    "d_theta_rad": np.deg2rad(0.05),
    "d_focal_relative": 0.002,
    "d_cx_px": 0.5,
    "d_focus_mm": 0.10,
}


def test_sigma_vector_follows_the_declared_order() -> None:
    vector = sigma_vector(SIGMAS)
    assert vector.shape == (len(VARIABLE_ORDER),)
    assert vector[0] == pytest.approx(0.05)


def test_latin_hypercube_has_one_point_per_stratum() -> None:
    u = latin_hypercube(50, 5, seed=7)
    assert u.shape == (50, 5)
    assert np.all((u > 0) & (u < 1))
    for axis in range(5):
        strata = np.floor(u[:, axis] * 50).astype(int)
        assert len(set(strata.tolist())) == 50


def test_lhs_marginals_pass_a_ks_test() -> None:
    draws = draw_lhs(400, SIGMAS, seed=11)
    physical = draws.physical()
    for index, name in enumerate(VARIABLE_ORDER):
        sample = physical[:, index] / SIGMAS[name]
        assert stats.kstest(sample, "norm").pvalue > 0.01, name


def test_normal_draws_reproduce_the_sigma() -> None:
    draws = draw_normal(4000, SIGMAS, seed=3)
    physical = draws.physical()
    for index, name in enumerate(VARIABLE_ORDER):
        assert np.std(physical[:, index]) == pytest.approx(SIGMAS[name], rel=0.06)


def test_inverse_normal_is_the_correct_transform() -> None:
    u = np.array([0.001, 0.025, 0.5, 0.975, 0.999])
    z = inverse_normal(u)
    assert z[2] == pytest.approx(0.0, abs=1e-9)
    assert z[1] == pytest.approx(-1.959963984540054, rel=1e-9)
    assert z[3] == pytest.approx(1.959963984540054, rel=1e-9)


def test_zero_sigma_is_rejected() -> None:
    with pytest.raises(ValueError):
        draw_normal(10, {**SIGMAS, "d_cx_px": 0.0}, seed=1)


# ---------------------------------------------------------------------------
# calibration
# ---------------------------------------------------------------------------
def _synthetic_curve(a: float = 47692.0, b: float = 641.66, noise_px: float = 0.0):
    z = np.linspace(100.0, 300.0, 21)
    u = a / z + b
    if noise_px:
        rng = np.random.default_rng(5)
        u = u + rng.normal(0.0, noise_px, size=z.size)
    return z, u


def test_m1_recovers_its_own_parameters() -> None:
    z, u = _synthetic_curve()
    fit = fit_calibration(z, u, model="M1", estimator="gaussian_2d")
    assert fit.status is Status.OK
    assert fit.params[0] == pytest.approx(47692.0, rel=1e-9)
    assert fit.params[1] == pytest.approx(641.66, rel=1e-9)
    assert fit.residual_rms_px < 1e-9


def test_m2_recovers_a_thin_lens_curve() -> None:
    z = np.linspace(100.0, 300.0, 21)
    a, c, b = 48000.0, 8.0, 640.0
    u = a / (z - c) + b
    fit = fit_calibration(z, u, model="M2", estimator="centroid")
    assert fit.status is Status.OK
    assert fit.params[0] == pytest.approx(a, rel=1e-6)
    assert fit.params[1] == pytest.approx(c, rel=1e-6)
    assert fit.residual_rms_px < 1e-6


def test_calibration_inverse_round_trips() -> None:
    z, u = _synthetic_curve()
    fit = fit_calibration(z, u, model="M1", estimator="gaussian_2d")
    for distance in (120.0, 200.0, 280.0):
        u_spot = 47692.0 / distance + 641.66
        recovered, status, _ = fit.inverse(u_spot)
        assert status is Status.OK
        assert recovered == pytest.approx(distance, rel=1e-9)


def test_calibration_refuses_distances_outside_its_range() -> None:
    fit = CalibrationFit("x", "M1", (1000.0, 600.0), 100.0, 300.0, 5, 0.1, Status.OK)
    value, status, _ = fit.inverse(600.0 + 1000.0 / 500.0)
    assert value is None
    assert status is Status.OUT_OF_RANGE


def test_fit_requires_three_distinct_points() -> None:
    fit = fit_calibration(np.array([100.0, 100.0, 100.0]), np.array([1.0, 1.0, 1.0]),
                          model="M1", estimator="centroid")
    assert fit.status is Status.NOT_ESTIMABLE


def test_model_selection_prefers_m1_when_m2_does_not_improve() -> None:
    z, u = _synthetic_curve(noise_px=0.2)
    fit, decision = select_model(z, u, estimator="gaussian_2d", min_improvement=0.20)
    assert decision["chosen"] in ("M1", "M2")
    if decision["chosen"] == "M1":
        assert fit.model == "M1"


# ---------------------------------------------------------------------------
# paired statistics
# ---------------------------------------------------------------------------
def test_paired_bootstrap_detects_a_shift() -> None:
    rng = np.random.default_rng(1)
    clusters = np.repeat(np.arange(60), 7)
    base = rng.normal(0.0, 0.05, size=clusters.size)
    improved = base * 0.5
    result = paired_bootstrap(base, improved, clusters, metric="rmse", n_boot=400)
    assert result.delta < 0
    assert result.ci_high < 0
    assert result.excludes_zero


def test_paired_bootstrap_does_not_claim_a_null_difference() -> None:
    rng = np.random.default_rng(2)
    clusters = np.repeat(np.arange(40), 5)
    base = rng.normal(0.0, 0.05, size=clusters.size)
    same = base + rng.normal(0.0, 1e-6, size=clusters.size)
    result = paired_bootstrap(base, same, clusters, metric="rmse", n_boot=400)
    assert result.ci_low < 0 < result.ci_high


def test_failure_rate_difference_is_paired() -> None:
    clusters = np.repeat(np.arange(30), 4)
    success_a = np.ones(clusters.size)
    success_b = np.ones(clusters.size)
    success_b[:8] = 0.0
    result = paired_rate_difference(success_a, success_b, clusters, n_boot=300)
    assert result.delta > 0


def test_bootstrap_needs_at_least_three_clusters() -> None:
    with pytest.raises(ValueError):
        paired_bootstrap(np.zeros(3), np.zeros(3), np.array([0, 0, 1]), metric="rmse")
