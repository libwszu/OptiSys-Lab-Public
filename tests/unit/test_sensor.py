"""Sensor-chain tests: deterministic sampling, ADC mapping, saturation."""

from __future__ import annotations

from dataclasses import replace

import numpy as np
import pytest

from optisys.config_g1 import SensorSpec, load_config_g1
from optisys.imaging.sensor import (
    render_frame,
    sample_pixel,
    stable_seed,
    to_electrons,
)

ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def config():
    return load_config_g1(ROOT / "configs" / "triangulation_g1_l0.yaml")


@pytest.fixture()
def sensor(config) -> SensorSpec:
    return replace(config.sensor, read_noise_e=3.0)


def test_stable_seed_is_deterministic_and_distinct() -> None:
    assert stable_seed(1, "a") == stable_seed(1, "a")
    assert stable_seed(1, "a") != stable_seed(1, "b")
    assert stable_seed(2, "a") != stable_seed(1, "a")


def test_noise_free_frame_equals_expectation(config, sensor) -> None:
    signal = np.full((8, 8), 100.0)
    frame = render_frame(signal, 50.0, sensor, 123, noise=False)
    assert np.allclose(frame.analog_e, 150.0 + sensor.dark_e_per_px)
    assert frame.saturation_fraction == 0.0
    assert frame.flags == ()


def test_same_seed_reproduces_frame(config, sensor) -> None:
    signal = np.full((16, 16), 200.0)
    first = render_frame(signal, 50.0, sensor, 42)
    second = render_frame(signal, 50.0, sensor, 42)
    np.testing.assert_array_equal(first.image_adu, second.image_adu)
    np.testing.assert_array_equal(first.analog_e, second.analog_e)


def test_different_seed_changes_noise(config, sensor) -> None:
    signal = np.full((16, 16), 200.0)
    first = render_frame(signal, 50.0, sensor, 42)
    second = render_frame(signal, 50.0, sensor, 43)
    assert not np.array_equal(first.image_adu, second.image_adu)


def test_adc_mapping_includes_black_level(config) -> None:
    sensor = replace(config.sensor, read_noise_e=0.0, dark_rate_e_per_s=0.0)
    signal = np.full((4, 4), 300.0)  # 300 e / 3 e per ADU = 100 codes
    frame = render_frame(signal, 0.0, sensor, 1, noise=False)
    assert int(frame.image_adu[0, 0]) == sensor.black_level_adu + 100


def test_saturation_clips_at_full_well_and_adc(config) -> None:
    sensor = replace(config.sensor, read_noise_e=0.0)
    signal = np.full((4, 4), 5.0 * sensor.full_well_e)
    frame = render_frame(signal, 0.0, sensor, 1, noise=False)
    assert frame.saturation_fraction == 1.0
    assert "SATURATED_PIXELS" in frame.flags
    assert frame.analog_e.max() == pytest.approx(sensor.full_well_e)
    assert int(frame.image_adu.max()) <= sensor.adc_limit


def test_adc_clipping_is_flagged_when_full_well_exceeds_adc(config) -> None:
    sensor = replace(config.sensor, full_well_e=1e6, read_noise_e=0.0,
                     adc_max_adu=255, bit_depth=12)
    signal = np.full((4, 4), 1e5)
    frame = render_frame(signal, 0.0, sensor, 1, noise=False)
    assert "ADC_CLIPPED" in frame.flags
    assert int(frame.image_adu.max()) == 255


def test_to_electrons_inverts_gain_and_black_level(config, sensor) -> None:
    image = np.array([[sensor.black_level_adu, sensor.black_level_adu + 10]], dtype=np.uint16)
    electrons = to_electrons(image, sensor)
    assert electrons.tolist() == [[0.0, 30.0]]


def test_sample_pixel_matches_declared_statistics(config) -> None:
    sensor = replace(config.sensor, read_noise_e=4.0, dark_rate_e_per_s=0.0)
    samples = sample_pixel(500.0, 100.0, sensor, 200_000, 7)
    assert np.mean(samples) == pytest.approx(600.0, abs=1.0)
    assert np.var(samples, ddof=1) == pytest.approx(600.0 + 16.0, rel=0.03)


def test_negative_signal_is_rejected(config, sensor) -> None:
    with pytest.raises(ValueError):
        render_frame(np.full((2, 2), -1.0), 10.0, sensor, 1)
