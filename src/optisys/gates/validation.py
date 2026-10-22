"""V1/V2 scientific checks for G1 (imaging, integration, noise statistics)."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import numpy as np
from scipy import stats

from optisys.config_g1 import ResolvedG1Config, SensorSpec
from optisys.errors import Status
from optisys.imaging.roi import detect_roi
from optisys.imaging.sensor import render_frame, sample_pixel, stable_seed
from optisys.imaging.spot import (
    SpotSpec,
    capture_fraction,
    integrated_weights,
    pixel_weight_numeric,
)
from optisys.estimators import build_estimators

QUIET_SENSOR = SensorSpec(
    read_noise_e=0.0,
    dark_rate_e_per_s=0.0,
    exposure_ms=2.0,
    full_well_e=60000.0,
    bit_depth=14,
    e_per_adu=1.0,
    black_level_adu=100,
    adc_max_adu=16383,
)


def _quiet_sensor() -> SensorSpec:
    return QUIET_SENSOR


def imaging_checks(config: ResolvedG1Config) -> tuple[dict[str, Any], dict[str, Any]]:
    """V1-A energy/integration and V1-B subpixel checks."""

    width, height = config.width_px, config.height_px
    sigma = config.imaging.sigma_px
    total = 200_000.0
    center = (config.cx_px, config.cy_px)
    spot = SpotSpec(center, sigma, total)
    weights = integrated_weights(width, height, spot)
    discrete_sum = float(weights.sum())
    energy_rel = abs(discrete_sum - total) / total
    capture = capture_fraction(width, height, spot)

    # Independent Gauss-Legendre quadrature at 16 sampled pixels.
    rng = np.random.default_rng(config.seed)
    rows = rng.integers(int(config.cy_px) - 8, int(config.cy_px) + 9, size=16)
    cols = rng.integers(int(config.cx_px) - 8, int(config.cx_px) + 9, size=16)
    quadrature_errors = []
    for row, col in zip(rows, cols):
        analytic = float(weights[row, col])
        numeric = pixel_weight_numeric(int(col), int(row), spot, nodes=24)
        quadrature_errors.append(abs(analytic - numeric) / analytic)

    # Edge capture must decrease without renormalisation.
    edge_center = (float(width - 6), config.cy_px)
    offsets = (0.0, 5.0, 10.0, 20.0, 30.0)
    captures = [capture_fraction(width, height,
                                 SpotSpec((edge_center[0] + offset, edge_center[1]), sigma, total))
                for offset in offsets]
    monotone = all(captures[i] >= captures[i + 1] - 1e-15 for i in range(len(captures) - 1))

    # V1-B subpixel bias on noise-free frames.
    subpixel = []
    for offset in (0.25, 0.37, 0.50):
        spot_shift = SpotSpec((500.0 + offset, 300.0 + offset), sigma, total)
        frame = render_frame(
            integrated_weights(width, height, spot_shift),
            0.0, _quiet_sensor(), stable_seed(config.seed, f"subpixel-{offset}"), noise=False,
        )
        roi = detect_roi(frame.image_adu, _quiet_sensor())
        for estimator in build_estimators():
            result = estimator.estimate(frame.image_adu, roi.roi, _quiet_sensor())
            if result.status is not Status.OK:
                subpixel.append({"offset_px": offset, "estimator": estimator.name,
                                 "error_px": None, "status": result.status.value})
                continue
            subpixel.append({
                "offset_px": offset,
                "estimator": estimator.name,
                "error_px": float(result.u_hat_px - (500.0 + offset)),
                "v_error_px": float(result.v_hat_px - (300.0 + offset)),
                "status": result.status.value,
            })

    def worst(prefix: str) -> float:
        values = [abs(item["error_px"]) for item in subpixel
                  if item["estimator"] == prefix and item["error_px"] is not None]
        return float(max(values)) if values else float("inf")

    details = {
        "v1": {
            "discrete_sum_e": discrete_sum,
            "continuous_total_e": total,
            "energy_relative_deviation": energy_rel,
            "capture_fraction_centered": capture,
            "quadrature_pixels": int(len(quadrature_errors)),
            "quadrature_max_relative_error": float(max(quadrature_errors)),
            "edge_offsets_px": list(offsets),
            "edge_capture_fractions": captures,
            "edge_capture_monotone": bool(monotone),
            "subpixel": subpixel,
        }
    }
    checks = {
        "v1_energy_conservation": {
            "value": energy_rel,
            "threshold": 0.01,
            "pass": bool(energy_rel <= 0.01 and capture >= 0.999),
            "what": "discrete pixel integral vs continuous total, uncropped spot",
        },
        "v1_independent_quadrature": {
            "value": float(max(quadrature_errors)),
            "threshold": 1e-6,
            "pass": bool(max(quadrature_errors) <= 1e-6),
            "what": "erf/CDF weights vs Gauss-Legendre quadrature",
        },
        "v1_edge_capture_without_renormalisation": {
            "value": {"monotone": bool(monotone), "captures": [round(v, 6) for v in captures]},
            "threshold": "monotone non-increasing",
            "pass": bool(monotone and captures[-1] < captures[0]),
            "what": "capture fraction decreases at the chip edge; no rescaling",
        },
        "v1_subpixel_centroid": {
            "value": worst("centroid"), "threshold": 0.05,
            "pass": bool(worst("centroid") <= 0.05),
            "what": "noise-free subpixel scan, u error",
        },
        "v1_subpixel_gaussian_1d": {
            "value": worst("gaussian_1d"), "threshold": 0.02,
            "pass": bool(worst("gaussian_1d") <= 0.02),
            "what": "noise-free subpixel scan, u error",
        },
        "v1_subpixel_gaussian_2d": {
            "value": worst("gaussian_2d"), "threshold": 0.01,
            "pass": bool(worst("gaussian_2d") <= 0.01),
            "what": "noise-free subpixel scan, u error",
        },
    }
    return details, checks


def noise_checks(config: ResolvedG1Config, n_samples: int = 10_000,
                 z_value: float = 2.576) -> tuple[dict[str, Any], dict[str, Any]]:
    """V2-A single-pixel statistics and V2-B exposure/saturation checks."""

    base = config.sensor
    rows: list[dict[str, Any]] = []
    checks: dict[str, Any] = {}

    scenarios = [
        ("dark_field", 0.0, 100.0, 3.0, "dark"),
        ("signal_poisson", 500.0, 100.0, 3.0, "combined"),
        ("read_only", 0.0, 0.0, 5.0, "read"),
        ("combined", 2000.0, 150.0, 4.0, "combined"),
        ("zero_read", 800.0, 50.0, 0.0, "poisson"),
    ]
    n_replicates = 3
    for name, signal, background, read, kind in scenarios:
        sensor = replace(base, read_noise_e=read)
        mu = signal + background + sensor.dark_e_per_px
        variance = mu + read**2
        replicates = []
        pooled = []
        for replicate in range(n_replicates):
            samples = sample_pixel(
                signal, background, sensor, n_samples,
                stable_seed(config.seed, f"noise-{name}-{replicate}"),
            )
            replicates.append(_statistics(f"{name}-r{replicate}", samples, mu, variance,
                                          n_samples, z_value))
            pooled.append(samples)
        # Pre-declared robustness rule: three independent 10k replicates are
        # pooled (n=30k) for the gate.  Individual replicates are reported
        # as-is so a chance rejection cannot be hidden.
        row = _statistics(name, np.concatenate(pooled), mu, variance,
                          n_samples * n_replicates, z_value)
        replicate_passes = sum(1 for item in replicates if item["pass"])
        row.update({
            "signal_e": signal, "background_e": background, "read_noise_e": read,
            "kind": kind, "replicates": replicates, "n_replicates": n_replicates,
            "replicate_passes": replicate_passes,
            "pooled_n": n_samples * n_replicates,
        })
        rows.append(row)
        checks[f"v2_{name}"] = {
            "value": {"mean": row["sample_mean"], "variance": row["sample_variance"],
                      "replicate_passes": replicate_passes},
            "threshold": {"mean": row["mean_ci"], "variance": [row["var_low"], row["var_high"]]},
            "pass": bool(row["pass"] and replicate_passes >= 2),
            "what": (f"{n_replicates} x {n_samples} single-pixel samples, pooled n="
                     f"{n_samples * n_replicates}, 99% intervals"),
        }

    # Dark-current exposure slope (5000 e/s/px).
    dark_sensor = replace(base, dark_rate_e_per_s=5000.0, read_noise_e=2.0)
    exposures = (1.0, 2.0, 5.0, 10.0, 20.0)
    measured = []
    for exposure in exposures:
        sensor = replace(dark_sensor, exposure_ms=exposure)
        samples = sample_pixel(0.0, 0.0, sensor, 20_000,
                               stable_seed(config.seed, f"dark-{exposure}"))
        measured.append(float(np.mean(samples)))
    slope = float(np.polyfit(np.array(exposures) * 1e-3, np.array(measured), 1)[0])
    slope_error = abs(slope - 5000.0) / 5000.0
    checks["v2b_dark_slope"] = {
        "value": {"slope_e_per_s": slope, "relative_error": slope_error},
        "threshold": 0.05,
        "pass": bool(slope_error <= 0.05),
        "what": "dark current mean vs exposure, 1-20 ms",
    }
    checks["v2b_dark_slope"]["measured"] = measured

    # Saturation behaviour: signal above full well must flag and clip.
    saturated_sensor = replace(base, read_noise_e=0.0)
    saturated_signal = np.full((16, 16), 3.0 * base.full_well_e)
    frame = render_frame(saturated_signal, 0.0, saturated_sensor,
                         stable_seed(config.seed, "saturation"), noise=False)
    saturation_ok = (
        frame.saturation_fraction == 1.0
        and "SATURATED_PIXELS" in frame.flags
        and int(frame.image_adu.max()) <= saturated_sensor.adc_limit
        and float(frame.analog_e.max()) <= saturated_sensor.full_well_e
    )
    checks["v2b_saturation"] = {
        "value": {
            "saturation_fraction": frame.saturation_fraction,
            "max_adu": int(frame.image_adu.max()),
            "adc_limit": saturated_sensor.adc_limit,
            "max_analog_e": float(frame.analog_e.max()),
        },
        "threshold": "flag set, clipped at full well and ADC limit",
        "pass": bool(saturation_ok),
        "what": "over-full-well frame",
    }

    details = {
        "v2": rows,
        "v2b": {
            "dark_exposures_ms": list(exposures),
            "dark_means_e": measured,
            "dark_slope_e_per_s": slope,
            "saturation_fraction": frame.saturation_fraction,
            "saturation_flags": list(frame.flags),
            "max_adu": int(frame.image_adu.max()),
        },
    }
    return details, checks


def _statistics(name: str, samples: np.ndarray, mu: float, variance: float,
                n: int, z_value: float) -> dict[str, Any]:
    sample_mean = float(np.mean(samples))
    sample_variance = float(np.var(samples, ddof=1))
    mean_ci = z_value * float(np.sqrt(variance / n))
    dof = n - 1
    chi_low = stats.chi2.ppf(0.005, dof)
    chi_high = stats.chi2.ppf(0.995, dof)
    var_low = dof * sample_variance / chi_high
    var_high = dof * sample_variance / chi_low
    mean_ok = abs(sample_mean - mu) <= mean_ci
    var_ok = var_low <= variance <= var_high
    return {
        "scenario": name,
        "n": n,
        "theoretical_mean": mu,
        "theoretical_variance": variance,
        "sample_mean": sample_mean,
        "sample_variance": sample_variance,
        "mean_ci": mean_ci,
        "var_low": float(var_low),
        "var_high": float(var_high),
        "mean_pass": bool(mean_ok),
        "variance_pass": bool(var_ok),
        "pass": bool(mean_ok and var_ok),
    }
