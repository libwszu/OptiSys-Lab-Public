"""Algorithm 2: separable 1-D Gaussian fits on row/column projections."""

from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
from scipy.optimize import least_squares
from scipy.special import ndtr

_SQRT_2PI = float(np.sqrt(2.0 * np.pi))

from optisys.config_g1 import SensorSpec
from optisys.errors import Status
from optisys.estimators.base import EstimateResult, common_flags, extract_roi, peak_snr


@dataclass
class _ProfileFit:
    amplitude: float
    center: float
    sigma: float
    baseline: float
    rms: float
    success: bool


def _fit_profile(profile: np.ndarray, coords: np.ndarray, noise: float) -> _ProfileFit:
    baseline = float(np.median(profile))
    index = int(np.argmax(profile))
    amplitude = float(max(profile[index] - baseline, 1.0))
    center = float(coords[index])

    def model_from(params: np.ndarray) -> np.ndarray:
        amp, cen, sig, base = params
        # Pixel-integrated Gaussian: normal-CDF difference over each bin.  A
        # point-sampled model would bias the centre by hundredths of a pixel.
        return base + amp * (
            ndtr((coords + 0.5 - cen) / sig) - ndtr((coords - 0.5 - cen) / sig)
        )

    def residual(params: np.ndarray) -> np.ndarray:
        return model_from(params) - profile

    def jacobian(params: np.ndarray) -> np.ndarray:
        amp, cen, sig, base = params
        z_hi = (coords + 0.5 - cen) / sig
        z_lo = (coords - 0.5 - cen) / sig
        phi_hi = np.exp(-0.5 * z_hi**2) / _SQRT_2PI
        phi_lo = np.exp(-0.5 * z_lo**2) / _SQRT_2PI
        d_amp = ndtr(z_hi) - ndtr(z_lo)
        d_cen = amp * (phi_lo - phi_hi) / sig
        d_sig = amp * (phi_lo * z_lo - phi_hi * z_hi) / sig
        d_base = np.ones_like(coords)
        return np.column_stack([d_amp, d_cen, d_sig, d_base])

    lower = [0.0, coords[0] - 1.0, 0.7, baseline - 20.0 * max(noise, 1.0)]
    upper = [20.0 * amplitude + 1.0, coords[-1] + 1.0, 8.0, baseline + 20.0 * max(noise, 1.0)]
    p0 = np.array([amplitude, center, min(max(2.5, 0.5), 7.5), baseline])
    p0 = np.clip(p0, np.array(lower) + 1e-9, np.array(upper) - 1e-9)
    try:
        solution = least_squares(
            residual, p0, jac=jacobian, bounds=(lower, upper), loss="soft_l1",
            f_scale=max(noise, 1e-3 * amplitude), max_nfev=200,
        )
    except (ValueError, RuntimeError):
        return _ProfileFit(amplitude, center, float("nan"), baseline, float("nan"), False)

    amp, cen, sig, base = solution.x
    rms = float(np.sqrt(np.mean(solution.fun**2)))
    success = bool(solution.success) and np.isfinite(sig) and 0.7 <= sig <= 8.0 and amp > 0
    return _ProfileFit(float(amp), float(cen), float(sig), float(base), rms, success)


class Gaussian1DEstimator:
    name = "gaussian_1d"

    def estimate(self, image_adu: np.ndarray, roi: tuple[int, int, int, int],
                 sensor: SensorSpec) -> EstimateResult:
        started = time.perf_counter()
        data = extract_roi(image_adu, roi, sensor)
        electrons = data.electrons
        if electrons.size == 0 or data.peak_e <= data.background_e:
            return EstimateResult(self.name, None, None, Status.NO_SIGNAL,
                                  flags=("NO_SIGNAL",),
                                  runtime_ms=(time.perf_counter() - started) * 1e3)

        profile_u = electrons.sum(axis=0)
        profile_v = electrons.sum(axis=1)
        coords_u = np.arange(electrons.shape[1], dtype=float) + data.col0
        coords_v = np.arange(electrons.shape[0], dtype=float) + data.row0

        fit_u = _fit_profile(profile_u, coords_u, data.noise_e)
        # v is obtained from the row-profile centroid: the 1-D estimator is
        # defined for u only, and this keeps its cost comparable to the others.
        weights_v = np.clip(profile_v - data.background_e, 0.0, None)
        total_v = float(weights_v.sum())
        v_centroid = (
            float((weights_v * coords_v).sum() / total_v) if total_v > 0 else float("nan")
        )
        fit_v = _ProfileFit(float(weights_v.max()), v_centroid, float("nan"),
                            data.background_e, 0.0, bool(np.isfinite(v_centroid)))
        elapsed = (time.perf_counter() - started) * 1e3

        if not fit_u.success:
            return EstimateResult(
                self.name, None, None, Status.FIT_NOT_CONVERGED,
                quality={"u_fit": fit_u.__dict__, "v_method": "centroid_of_rows"},
                flags=("FIT_NOT_CONVERGED",), runtime_ms=elapsed,
            )

        peak = max(fit_u.amplitude, 1.0)
        mismatch = fit_u.rms > 0.15 * peak or not (1.0 <= fit_u.sigma <= 8.0)
        flags = common_flags(data, peak_snr(data, sensor))
        if mismatch:
            flags.append("MODEL_MISMATCH")

        return EstimateResult(
            estimator=self.name,
            u_hat_px=fit_u.center,
            v_hat_px=fit_v.center,
            status=Status.OK,
            quality={
                "sigma_u_px": fit_u.sigma,
                "v_method": "centroid_of_rows",
                "amplitude_u_e": fit_u.amplitude,
                "rms_u_e": fit_u.rms,
                "rms_v_e": None,
                "snr_proxy": peak_snr(data, sensor),
                "saturation_fraction": data.saturation_fraction,
                "roi_touches_border": data.touches_border,
                "background_e": data.background_e,
                "peak_e": data.peak_e,
            },
            flags=tuple(flags),
            residual_rms_e=float(fit_u.rms),
            runtime_ms=elapsed,
        )
