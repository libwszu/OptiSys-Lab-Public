"""Spot integration tests: exact area weighting, energy and clipping."""

from __future__ import annotations

import numpy as np
import pytest

from optisys.config_g1 import load_config_g1
from optisys.imaging.spot import (
    SpotSpec,
    capture_fraction,
    integrated_weights,
    marginal_probabilities,
    pixel_weight_numeric,
    window_bounds,
)

ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def config():
    return load_config_g1(ROOT / "configs" / "triangulation_g1_l0.yaml")


def test_marginal_probabilities_sum_to_one() -> None:
    probabilities = marginal_probabilities(1280, 640.3, 2.5)
    assert probabilities.sum() == pytest.approx(1.0, rel=0, abs=1e-12)


def test_discrete_sum_matches_continuous_total(config) -> None:
    spot = SpotSpec((config.cx_px, config.cy_px), 2.5, 40_000.0)
    weights = integrated_weights(config.width_px, config.height_px, spot)
    assert weights.sum() == pytest.approx(40_000.0, rel=1e-12)


def test_offcentre_spot_still_conserves_energy(config) -> None:
    spot = SpotSpec((300.37, 200.81), 2.5, 12_345.0)
    weights = integrated_weights(config.width_px, config.height_px, spot)
    assert weights.sum() == pytest.approx(12_345.0, rel=1e-12)


def test_quadrature_agreement_is_independent_of_the_cdf_path() -> None:
    spot = SpotSpec((100.37, 100.81), 2.5, 10_000.0)
    weights = integrated_weights(256, 256, spot)
    for u, v in ((100, 100), (101, 100), (100, 101), (99, 99)):
        analytic = weights[v, u]
        numeric = pixel_weight_numeric(u, v, spot, nodes=24)
        assert numeric == pytest.approx(analytic, rel=1e-9)


def test_peak_definition() -> None:
    spot = SpotSpec((0.0, 0.0), 2.0, 1000.0)
    assert spot.peak_e_per_px == pytest.approx(1000.0 / (2 * np.pi * 4.0))


def test_capture_fraction_decreases_at_the_edge(config) -> None:
    base = capture_fraction(config.width_px, config.height_px,
                            SpotSpec((config.width_px - 10.0, config.cy_px), 2.5, 1000.0))
    shifted = capture_fraction(config.width_px, config.height_px,
                               SpotSpec((config.width_px - 2.0, config.cy_px), 2.5, 1000.0))
    assert base > shifted
    assert shifted < 1.0


def test_window_bounds_are_inside_the_chip(config) -> None:
    spot = SpotSpec((5.0, 5.0), 2.5, 1000.0)
    row0, row1, col0, col1 = window_bounds(spot, config.width_px, config.height_px)
    assert 0 <= row0 < row1 <= config.height_px
    assert 0 <= col0 < col1 <= config.width_px


def test_invalid_spot_is_rejected() -> None:
    with pytest.raises(ValueError):
        SpotSpec((0.0, 0.0), 0.0, 1000.0)
    with pytest.raises(ValueError):
        SpotSpec((0.0, 0.0), 2.5, -1.0)
    with pytest.raises(ValueError):
        SpotSpec((float("nan"), 0.0), 2.5, 1000.0)
