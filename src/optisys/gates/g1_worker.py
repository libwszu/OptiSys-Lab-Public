"""Frame-level worker for the G1 pipeline (Windows ``spawn`` safe).

Each task is fully specified by its payload: frame size, spot parameters,
condition/sensor parameters, geometry truth, seed, sample id and hashes.  No
shared RNG state is used, so results do not depend on process scheduling.
"""

from __future__ import annotations

from typing import Any

from optisys.config_g1 import SensorSpec
from optisys.estimators import build_estimators
from optisys.imaging.roi import detect_roi
from optisys.imaging.sensor import render_frame
from optisys.imaging.spot import SpotSpec, integrated_weights


def frame_task(payload: tuple) -> list[dict[str, Any]]:
    (width, height, sigma, total, background, read_noise, dark_rate, exposure_ms,
     full_well, bit_depth, e_per_adu, black_level, adc_max, u_gt, v_gt, distance,
     condition_name, reflectance, seed, sample_id, config_sha, code_sha, split,
     capture_fraction) = payload

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
    weights = integrated_weights(width, height, SpotSpec((u_gt, v_gt), sigma, total))
    frame = render_frame(weights, background, sensor, seed)
    roi = detect_roi(frame.image_adu, sensor)
    image_status = ";".join(frame.flags) if frame.flags else "OK"

    rows: list[dict[str, Any]] = []
    for estimator in build_estimators():
        if roi.roi is None:
            u_hat = v_hat = None
            status = roi.status
            flags = ("INVALID_ROI",)
            runtime = 0.0
            snr = None
            sigma_hat = None
            rms = None
        else:
            result = estimator.estimate(frame.image_adu, roi.roi, sensor)
            u_hat, v_hat = result.u_hat_px, result.v_hat_px
            status = result.status
            flags = result.flags
            runtime = result.runtime_ms
            snr = result.quality.get("snr_proxy")
            sigma_hat = result.quality.get("sigma_px", result.quality.get("sigma_u_px"))
            rms = result.residual_rms_e

        rows.append({
            "sample_id": f"{sample_id}|{estimator.name}",
            "dataset_split": split,
            "Z_gt_mm": distance,
            "u_gt_px": u_gt,
            "v_gt_px": v_gt,
            "condition_id": condition_name,
            "noise_level": condition_name,
            "reflectance_proxy": reflectance,
            "exposure_ms": exposure_ms,
            "image_seed": seed,
            "geometry_status": "OK",
            "image_status": image_status,
            "roi_status": roi.status.value,
            "estimator_name": estimator.name,
            "estimator_status": status.value,
            "quality_flags": ";".join(flags),
            "u_hat_px": u_hat,
            "v_hat_px": v_hat,
            "Z_hat_mm": None,
            "signed_error_mm": None,
            "saturation_fraction": frame.saturation_fraction,
            "capture_fraction": capture_fraction,
            "runtime_ms": runtime,
            "snr_proxy": snr,
            "sigma_px": sigma_hat,
            "fit_rms_e": rms,
            "roi_touches_border": roi.touches_border,
            "config_sha256": config_sha,
            "code_sha256": code_sha,
        })
    return rows
