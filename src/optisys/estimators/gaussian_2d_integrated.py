"""Algorithm 4 (G2): area-integrated 2-D Gaussian fit.

Why this exists
---------------
G1's ``gaussian_2d`` fits a Gaussian **sampled at pixel centres**, while the
forward model integrates the spot over each pixel's area.  At ``sigma = 2.5 px``
the difference is negligible, which is why G1 passed.  At ``sigma ~ 1 px`` - the
L1 regime - the point-sampled model is measurably wrong, and G1's own quality
gate (``1.0 <= sigma <= 8.0``) rejects every frame.

This estimator fits the *same* model the generator uses::

    mu(i, j) = base + amp * [Phi((j+1/2-u)/s) - Phi((j-1/2-u)/s)]
                        * [Phi((i+1/2-v)/s) - Phi((i-1/2-v)/s)]

so the discretisation mismatch disappears by construction rather than by
widening a tolerance.

The G1 estimators are **not** modified or replaced; they stay in the frozen
baseline and remain the reference for the L0-vs-L1 comparison.
"""

from __future__ import annotations

import time

import numpy as np
from scipy.optimize import least_squares
from scipy.special import ndtr

from optisys.config_g1 import SensorSpec
from optisys.errors import Status
from optisys.estimators.base import EstimateResult, common_flags, extract_roi, peak_snr

SIGMA_MIN_PX = 0.30
SIGMA_MAX_PX = 8.0


def integrated_gaussian(
    u: float, v: float, sigma: float, amplitude: float, base: float,
    x: np.ndarray, y: np.ndarray,
) -> np.ndarray:
    """Pixel-area-integrated circular Gaussian, exact for a separable kernel."""

    px = ndtr((x + 0.5 - u) / sigma) - ndtr((x - 0.5 - u) / sigma)
    py = ndtr((y + 0.5 - v) / sigma) - ndtr((y - 0.5 - v) / sigma)
    return base + amplitude * np.outer(py, px)


class Gaussian2DIntegratedEstimator:
    name = "gaussian_2d_integrated"

    def __init__(self, loss: str = "soft_l1") -> None:
        self.loss = loss

    def estimate(self, image_adu: np.ndarray, roi: tuple[int, int, int, int],
                 sensor: SensorSpec) -> EstimateResult:
        started = time.perf_counter()
        data = extract_roi(image_adu, roi, sensor)
        electrons = data.electrons
        x = np.arange(electrons.shape[1], dtype=float) + data.col0
        y = np.arange(electrons.shape[0], dtype=float) + data.row0

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
        amplitude0 = float(max(electrons[index] - background, 1.0)) * 4.0
        u0 = float(x[index[1]])
        v0 = float(y[index[0]])
        # The peak of an area-integrated Gaussian is lower than its central
        # value; the factor 4 above is a deliberately loose starting point.

        def residual(params: np.ndarray) -> np.ndarray:
            amp, uc, vc, sigma, base = params
            model = integrated_gaussian(uc, vc, sigma, amp, base, x, y)
            return (model - electrons).ravel()

        lower = [0.0, x.min() - 1.0, y.min() - 1.0, SIGMA_MIN_PX,
                 background - 20.0 * max(data.noise_e, 1.0)]
        upper = [50.0 * amplitude0 + 1.0, x.max() + 1.0, y.max() + 1.0, SIGMA_MAX_PX,
                 background + 20.0 * max(data.noise_e, 1.0)]
        p0 = np.clip(
            np.array([amplitude0, u0, v0, 1.0, background]),
            np.array(lower) + 1e-9, np.array(upper) - 1e-9,
        )

        try:
            solution = least_squares(
                residual, p0, bounds=(lower, upper), loss=self.loss,
                f_scale=max(data.noise_e, 1e-6), max_nfev=400,
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

        flags = common_flags(data, peak_snr(data, sensor))
        # The residual test is on the *relative* fit error; the sigma bounds are
        # the ones this model actually supports.
        if rms > 0.15 * max(amp, 1.0) or not (SIGMA_MIN_PX <= sigma <= SIGMA_MAX_PX):
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
                "model": "area_integrated_gaussian",
            },
            flags=tuple(flags),
            residual_rms_e=rms,
            runtime_ms=elapsed,
        )
