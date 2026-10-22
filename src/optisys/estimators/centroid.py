"""Algorithm 1: background-subtracted threshold-weighted centroid."""

from __future__ import annotations

import time

import numpy as np

from optisys.config_g1 import SensorSpec
from optisys.errors import Status
from optisys.estimators.base import EstimateResult, common_flags, extract_roi, peak_snr


class CentroidEstimator:
    name = "centroid"

    def __init__(self, k_sigma: float = 3.0) -> None:
        self.k_sigma = float(k_sigma)

    def estimate(self, image_adu: np.ndarray, roi: tuple[int, int, int, int],
                 sensor: SensorSpec) -> EstimateResult:
        started = time.perf_counter()
        data = extract_roi(image_adu, roi, sensor)
        threshold = data.background_e + self.k_sigma * data.noise_e
        weights = np.clip(data.electrons - threshold, 0.0, None)

        total = float(weights.sum())
        elapsed = (time.perf_counter() - started) * 1e3
        if not np.isfinite(total) or total <= 0.0:
            return EstimateResult(
                self.name, None, None, Status.NO_SIGNAL,
                quality={"total_weight_e": total, "background_e": data.background_e},
                flags=("NO_SIGNAL",), runtime_ms=elapsed,
            )

        rows, cols = np.indices(weights.shape, dtype=float)
        u = float((weights * (cols + data.col0)).sum() / total)
        v = float((weights * (rows + data.row0)).sum() / total)

        flags = common_flags(data, peak_snr(data, sensor))
        return EstimateResult(
            estimator=self.name,
            u_hat_px=u,
            v_hat_px=v,
            status=Status.OK,
            quality={
                "total_weight_e": total,
                "background_e": data.background_e,
                "noise_e": data.noise_e,
                "threshold_e": threshold,
                "peak_e": data.peak_e,
                "snr_proxy": peak_snr(data, sensor),
                "saturation_fraction": data.saturation_fraction,
                "roi_touches_border": data.touches_border,
            },
            flags=tuple(flags),
            runtime_ms=elapsed,
        )
