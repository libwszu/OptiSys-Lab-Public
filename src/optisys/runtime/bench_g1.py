"""Worker entry point for the G1 parallel benchmark (Windows ``spawn`` safe)."""

from __future__ import annotations

from optisys.config_g1 import SensorSpec
from optisys.estimators import build_estimators
from optisys.imaging.roi import detect_roi
from optisys.imaging.sensor import render_frame
from optisys.imaging.spot import SpotSpec, integrated_weights


def frame_job(payload: tuple) -> tuple[float, float]:
    (width, height, u, v, sigma, total, background, read_noise, dark_rate, exposure_ms,
     full_well, bit_depth, e_per_adu, black_level, adc_max, seed) = payload
    sensor = SensorSpec(
        read_noise_e=read_noise,
        dark_rate_e_per_s=dark_rate,
        exposure_ms=exposure_ms,
        full_well_e=full_well,
        bit_depth=bit_depth,
        e_per_adu=e_per_adu,
        black_level_adu=black_level,
        adc_max_adu=adc_max,
    )
    spot = SpotSpec((u, v), sigma, total)
    weights = integrated_weights(width, height, spot)
    frame = render_frame(weights, background, sensor, seed)
    roi = detect_roi(frame.image_adu, sensor)
    u_sum = 0.0
    if roi.roi is not None:
        for estimator in build_estimators():
            result = estimator.estimate(frame.image_adu, roi.roi, sensor)
            u_sum += float(result.u_hat_px or 0.0)
    return float(weights.sum()), u_sum
