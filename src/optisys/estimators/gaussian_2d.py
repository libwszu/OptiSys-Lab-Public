"""Algorithm 3: robust 2-D circular Gaussian fit."""

from __future__ import annotations

import time

import numpy as np
from scipy.optimize import least_squares

from optisys.config_g1 import SensorSpec
from optisys.errors import Status
from optisys.estimators.base import EstimateResult, common_flags, extract_roi, peak_snr


class Gaussian2DEstimator:
    name = "gaussian_2d"

    def __init__(self, loss: str = "soft_l1") -> None:
        self.loss = loss

    def estimate(self, image_adu: np.ndarray, roi: tuple[int, int, int, int],
                 sensor: SensorSpec) -> EstimateResult:
        started = time.perf_counter()
        data = extract_roi(image_adu, roi, sensor)
        electrons = data.electrons
        rows, cols = np.indices(electrons.shape, dtype=float)
        x = cols + data.col0
        y = rows + data.row0

        background = data.background_e
        if data.peak_e <= background + data.noise_e:
            saturated_only = data.saturation_fraction > 0
            return EstimateResult(
                self.name, None, None,
                Status.SATURATED if saturated_only else Status.NO_SIGNAL,
                quality={"peak_e": data.peak_e, "background_e": background},
                flags=("SATURATED",) if saturated_only else ("NO_SIGNAL",),
                runtime_ms=(time.perf_counter() - started) * 1e3,
            )
        index = np.unravel_index(int(np.argmax(electrons)), electrons.shape)
        amplitude0 = float(max(electrons[index] - background, 1.0))
        u0 = float(x[index])
        v0 = float(y[index])

        def model(params: np.ndarray) -> np.ndarray:
            amp, uc, vc, sigma, base = params
            return base + amp * np.exp(
                -0.5 * (((x - uc) ** 2 + (y - vc) ** 2) / sigma**2)
            )

        def residual(params: np.ndarray) -> np.ndarray:
            return (model(params) - electrons).ravel()

        lower = [0.0, x.min() - 1.0, y.min() - 1.0, 0.6, background - 20.0 * max(data.noise_e, 1.0)]
        upper = [20.0 * amplitude0 + 1.0, x.max() + 1.0, y.max() + 1.0, 8.0,
                 background + 20.0 * max(data.noise_e, 1.0)]
        p0 = np.clip(
            np.array([amplitude0, u0, v0, min(max(2.5, 0.6), 7.5), background]),
            np.array(lower) + 1e-9,
            np.array(upper) - 1e-9,
        )

        try:
            solution = least_squares(
                residual, p0, bounds=(lower, upper), loss=self.loss,
                f_scale=max(data.noise_e, 1e-6), max_nfev=300,
            )
        except (ValueError, RuntimeError) as exc:
            return EstimateResult(
                self.name, None, None, Status.NUMERICAL_FAILURE,
                quality={"error": str(exc)[:200]},
                flags=("NUMERICAL_FAILURE",),
                runtime_ms=(time.perf_counter() - started) * 1e3,
            )

        amp, uc, vc, sigma, base = solution.x
        rms = float(np.sqrt(np.mean(solution.fun**2)))
        elapsed = (time.perf_counter() - started) * 1e3

        if not solution.success or not np.isfinite(uc) or not np.isfinite(vc):
            return EstimateResult(
                self.name, None, None, Status.FIT_NOT_CONVERGED,
                quality={"rms_e": rms, "solution_success": bool(solution.success)},
                flags=("FIT_NOT_CONVERGED",), runtime_ms=elapsed,
            )

        mismatch = rms > 0.08 * max(amp, 1.0) or not (1.0 <= sigma <= 8.0)
        flags = common_flags(data, peak_snr(data, sensor))
        if mismatch:
            flags.append("MODEL_MISMATCH")

        return EstimateResult(
            estimator=self.name,
            u_hat_px=float(uc),
            v_hat_px=float(vc),
            status=Status.OK,
            quality={
                "amplitude_e": float(amp),
                "sigma_px": float(sigma),
                "background_e": float(base),
                "rms_e": rms,
                "snr_proxy": peak_snr(data, sensor),
                "saturation_fraction": data.saturation_fraction,
                "roi_touches_border": data.touches_border,
                "peak_e": data.peak_e,
                "n_residuals": int(solution.fun.size),
            },
            flags=tuple(flags),
            residual_rms_e=rms,
            runtime_ms=elapsed,
        )
