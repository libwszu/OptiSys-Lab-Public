"""Estimator tests: uniform contract, accuracy, bad-frame handling."""

from __future__ import annotations

import inspect
from dataclasses import replace

import numpy as np
import pytest

from optisys.config_g1 import SensorSpec, load_config_g1
from optisys.estimators import CentroidEstimator, Gaussian1DEstimator, Gaussian2DEstimator
from optisys.estimators.base import extract_roi
from optisys.errors import Status
from optisys.imaging.roi import detect_roi
from optisys.imaging.sensor import render_frame, stable_seed
from optisys.imaging.spot import SpotSpec, integrated_weights

ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]
QUIET = SensorSpec(0.0, 0.0, 2.0, 60000.0, 14, 1.0, 100, 16383)


@pytest.fixture(scope="module")
def config():
    return load_config_g1(ROOT / "configs" / "triangulation_g1_l0.yaml")


def _frame(config, center, total=200_000.0, noise=False):
    weights = integrated_weights(config.width_px, config.height_px,
                                 SpotSpec(center, config.imaging.sigma_px, total))
    return render_frame(weights, 0.0, QUIET, stable_seed(1, "est"), noise=noise)


def test_estimator_signatures_do_not_accept_truth() -> None:
    for cls in (CentroidEstimator, Gaussian1DEstimator, Gaussian2DEstimator):
        parameters = list(inspect.signature(cls.estimate).parameters)
        assert parameters == ["self", "image_adu", "roi", "sensor"]


@pytest.mark.parametrize("offset", [0.25, 0.37, 0.50])
def test_noise_free_accuracy(config, offset: float) -> None:
    frame = _frame(config, (500.0 + offset, 300.0 + offset))
    roi = detect_roi(frame.image_adu, QUIET)
    assert roi.roi is not None
    for estimator, tolerance in ((CentroidEstimator(), 0.05),
                                 (Gaussian1DEstimator(), 0.02),
                                 (Gaussian2DEstimator(), 0.01)):
        result = estimator.estimate(frame.image_adu, roi.roi, QUIET)
        assert result.status is Status.OK
        assert abs(result.u_hat_px - (500.0 + offset)) <= tolerance
        assert abs(result.v_hat_px - (300.0 + offset)) <= tolerance


def test_uniform_image_returns_no_signal(config) -> None:
    image = np.full((64, 64), QUIET.black_level_adu + 10, dtype=np.uint16)
    for estimator in (CentroidEstimator(), Gaussian1DEstimator(), Gaussian2DEstimator()):
        result = estimator.estimate(image, (0, 64, 0, 64), QUIET)
        assert result.status is not Status.OK


def test_empty_roi_is_invalid(config) -> None:
    image = np.zeros((32, 32), dtype=np.uint16)
    result = CentroidEstimator().estimate(image, (5, 6, 5, 6), QUIET)
    assert result.status in (Status.NO_SIGNAL, Status.INVALID_ROI, Status.NUMERICAL_FAILURE)


def test_saturated_frame_is_flagged(config) -> None:
    sensor = replace(config.sensor, read_noise_e=0.0)
    signal = np.full((32, 32), 5.0 * sensor.full_well_e)
    frame = render_frame(signal, 0.0, sensor, 1, noise=False)
    result = Gaussian2DEstimator().estimate(frame.image_adu, (0, 32, 0, 32), sensor)
    assert "SATURATED" in result.flags


def test_border_roi_is_flagged(config) -> None:
    frame = _frame(config, (8.0, 8.0))
    roi = detect_roi(frame.image_adu, QUIET)
    result = Gaussian2DEstimator().estimate(frame.image_adu, roi.roi, QUIET)
    assert "ROI_AT_BORDER" in result.flags


def test_bimodal_spot_marks_model_mismatch(config) -> None:
    weights = integrated_weights(config.width_px, config.height_px,
                                 SpotSpec((500.0, 300.0), 2.5, 200_000.0))
    weights += integrated_weights(config.width_px, config.height_px,
                                  SpotSpec((514.0, 300.0), 2.5, 150_000.0))
    frame = render_frame(weights, 0.0, QUIET, 1, noise=False)
    roi = detect_roi(frame.image_adu, QUIET)
    result = Gaussian2DEstimator().estimate(frame.image_adu, roi.roi, QUIET)
    assert "MODEL_MISMATCH" in result.flags or result.residual_rms_e > 0.1 * 1e4


def test_estimators_are_deterministic(config) -> None:
    frame = _frame(config, (400.0, 400.0), noise=True)
    roi = detect_roi(frame.image_adu, QUIET)
    first = Gaussian2DEstimator().estimate(frame.image_adu, roi.roi, QUIET)
    second = Gaussian2DEstimator().estimate(frame.image_adu, roi.roi, QUIET)
    assert first.u_hat_px == second.u_hat_px
    assert first.v_hat_px == second.v_hat_px


def test_extract_roi_returns_global_coordinates(config) -> None:
    image = np.full((100, 120), 100, dtype=np.uint16)
    data = extract_roi(image, (10, 20, 30, 50), QUIET)
    assert data.row0 == 10 and data.col0 == 30
    assert data.electrons.shape == (10, 20)
