"""Estimator contract: every algorithm returns position, quality, status, time."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

import numpy as np

from optisys.config_g1 import SensorSpec
from optisys.errors import Status
from optisys.imaging.sensor import to_electrons


@dataclass
class EstimateResult:
    estimator: str
    u_hat_px: float | None
    v_hat_px: float | None
    status: Status
    quality: dict[str, Any] = field(default_factory=dict)
    flags: tuple[str, ...] = ()
    residual_rms_e: float | None = None
    runtime_ms: float = 0.0

    @property
    def ok(self) -> bool:
        return self.status is Status.OK and self.u_hat_px is not None


class Estimator(Protocol):
    name: str

    def estimate(self, image_adu: np.ndarray, roi: tuple[int, int, int, int],
                 sensor: SensorSpec) -> EstimateResult: ...


@dataclass
class RoiData:
    electrons: np.ndarray
    row0: int
    col0: int
    background_e: float
    noise_e: float
    peak_e: float
    saturation_fraction: float
    touches_border: bool


def extract_roi(image_adu: np.ndarray, roi: tuple[int, int, int, int],
                sensor: SensorSpec, *, k_mad: float = 1.4826) -> RoiData:
    row0, row1, col0, col1 = roi
    crop_adu = image_adu[row0:row1, col0:col1]
    electrons = to_electrons(crop_adu, sensor)
    height, width = image_adu.shape
    border = np.concatenate([electrons[0, :], electrons[-1, :],
                             electrons[:, 0], electrons[:, -1]])
    background = float(np.median(border))
    noise = float(k_mad * np.median(np.abs(border - background)))
    if not np.isfinite(noise) or noise <= 0:
        noise = 1.0
    saturated_pixels = int(np.count_nonzero(crop_adu >= sensor.adc_limit))
    saturation_fraction = saturated_pixels / crop_adu.size if crop_adu.size else 0.0
    touches = row0 <= 0 or col0 <= 0 or row1 >= height or col1 >= width
    return RoiData(
        electrons=electrons,
        row0=row0,
        col0=col0,
        background_e=background,
        noise_e=noise,
        peak_e=float(electrons.max()) if electrons.size else 0.0,
        saturation_fraction=float(saturation_fraction),
        touches_border=bool(touches),
    )


def common_flags(data: RoiData, snr: float, low_snr_threshold: float = 5.0) -> list[str]:
    flags: list[str] = []
    if data.saturation_fraction > 0.0:
        flags.append("SATURATED")
    if data.touches_border:
        flags.append("ROI_AT_BORDER")
    if snr < low_snr_threshold:
        flags.append("LOW_SNR")
    return flags


def peak_snr(data: RoiData, sensor: SensorSpec) -> float:
    """Peak-signal-to-noise proxy in electrons (documented, not a full SNR budget)."""

    noise = np.sqrt(max(data.peak_e, 0.0) + max(data.background_e, 0.0) + sensor.read_noise_e**2)
    return float(data.peak_e / noise) if noise > 0 else 0.0
