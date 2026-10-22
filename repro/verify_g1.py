"""Minimal standalone G1 reproduction.

Checks, without running the 4,920-frame experiment:

1. pixel-area integration: discrete sum vs continuous total;
2. independent Gauss-Legendre quadrature of sampled pixels;
3. noise statistics of one pixel (Poisson + read) at n=4,000;
4. sub-pixel accuracy of the 2-D estimator on a noise-free frame;
5. two-parameter system calibration recovery;
6. split manifest counts and disjointness.

Run from the project root:
    python repro/verify_g1.py
"""

from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402

from optisys.calibration.system import fit_distance_calibration  # noqa: E402
from optisys.config_g1 import SensorSpec, load_config_g1  # noqa: E402
from optisys.errors import Status  # noqa: E402
from optisys.estimators import Gaussian2DEstimator  # noqa: E402
from optisys.evaluation.splits import make_distance_splits  # noqa: E402
from optisys.imaging.roi import detect_roi  # noqa: E402
from optisys.imaging.sensor import render_frame, sample_pixel, stable_seed  # noqa: E402
from optisys.imaging.spot import (  # noqa: E402
    SpotSpec,
    integrated_weights,
    pixel_weight_numeric,
)


def main() -> int:
    config = load_config_g1(ROOT / "configs" / "triangulation_g1_l0.yaml")
    results = {}

    total = 40_000.0
    spot = SpotSpec((config.cx_px + 0.37, config.cy_px + 0.37), config.imaging.sigma_px, total)
    weights = integrated_weights(config.width_px, config.height_px, spot)
    energy_rel = abs(float(weights.sum()) - total) / total
    results["energy_rel"] = energy_rel

    quadrature = max(
        abs(weights[row, col] - pixel_weight_numeric(col, row, spot, nodes=24)) / weights[row, col]
        for row, col in ((512, 640), (512, 641), (511, 640), (513, 639))
    )
    results["quadrature_rel"] = float(quadrature)

    sensor = replace(config.sensor, read_noise_e=4.0, dark_rate_e_per_s=0.0)
    samples = sample_pixel(500.0, 100.0, sensor, 4000, stable_seed(config.seed, "repro-noise"))
    expected_mean, expected_var = 600.0, 600.0 + 16.0
    mean_z = abs(float(samples.mean()) - expected_mean) / np.sqrt(expected_var / samples.size)
    var_ratio = float(samples.var(ddof=1)) / expected_var
    results["noise_mean_z"] = float(mean_z)
    results["noise_var_ratio"] = var_ratio

    quiet = SensorSpec(0.0, 0.0, 2.0, 60000.0, 14, 1.0, 100, 16383)
    offset = 0.37
    frame = render_frame(
        integrated_weights(config.width_px, config.height_px,
                           SpotSpec((500.0 + offset, 300.0 + offset), config.imaging.sigma_px, 200_000.0)),
        0.0, quiet, stable_seed(config.seed, "repro-estimator"), noise=False,
    )
    roi = detect_roi(frame.image_adu, quiet)
    estimate = Gaussian2DEstimator().estimate(frame.image_adu, roi.roi, quiet)
    estimator_error = (
        abs(estimate.u_hat_px - (500.0 + offset)) if estimate.status is Status.OK else float("inf")
    )
    results["estimator_error_px"] = float(estimator_error)

    distances = np.array([100.0, 125.0, 150.0, 200.0, 250.0, 300.0])
    a_true = config.fx_px * config.baseline_mm
    b_true = config.cx_px - config.fx_px * np.tan(config.theta_rad)
    fit = fit_distance_calibration(distances, a_true / distances + b_true)
    a_rel = abs(fit.a_px_mm / a_true - 1.0) if fit.a_px_mm else float("inf")
    b_abs = abs(fit.b_px - b_true) if fit.b_px is not None else float("inf")
    results["calibration_a_rel"] = float(a_rel)
    results["calibration_b_abs_px"] = float(b_abs)

    manifest = make_distance_splits(
        config.distances_mm,
        config.dataset.validation_distances,
        config.dataset.test_distances,
    )
    split_ok = (
        len(manifest.calib_distances) == 27
        and len(manifest.validation_distances) == 7
        and len(manifest.test_distances) == 7
    )
    results["split_ok"] = bool(split_ok)

    ok = (
        energy_rel <= 1e-9
        and quadrature <= 1e-9
        and abs(mean_z) <= 4.0
        and 0.9 <= var_ratio <= 1.1
        and estimator_error <= 0.01
        and a_rel <= 1e-6
        and b_abs <= 1e-6
        and split_ok
    )

    print(f"config                 : {config.path}")
    print(f"energy relative error  : {energy_rel:.3e}")
    print(f"quadrature max rel err : {quadrature:.3e}")
    print(f"noise mean z-score     : {mean_z:.3f} (|z| <= 4)")
    print(f"noise variance ratio   : {var_ratio:.4f} (0.9-1.1)")
    print(f"2-D estimator error    : {estimator_error:.3e} px (<= 0.01)")
    print(f"calibration a rel err  : {a_rel:.3e}")
    print(f"calibration b abs err  : {b_abs:.3e} px")
    print(f"split 27/7/7           : {split_ok}")
    print("REPRO_STATUS           :", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
