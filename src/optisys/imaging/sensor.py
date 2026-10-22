"""L0 CMOS sensor chain: electrons -> Poisson/read noise -> gain -> ADC.

Order of operations (explicit, no hidden rescaling):

1. ``signal_mean_e`` comes from the spot integration (electrons per pixel).
2. ``dark_e = dark_rate_e_per_s * exposure_ms * 1e-3``.
3. ``mu = signal + background + dark`` is the Poisson rate.
4. ``photoelectrons ~ Poisson(mu)``; ``read_noise ~ Normal(0, sigma_read^2)``.
5. ``analog_e = photoelectrons + read_noise``, clipped at ``full_well_e``.
6. ``ADU = floor(analog_e / e_per_adu) + black_level``, clipped to the ADC range.

The ADC image is never treated as raw photoelectrons.  Both arrays are kept.
All sensor parameters are design assumptions, not datasheet values.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np

from optisys.config_g1 import SensorSpec


@dataclass
class RenderResult:
    image_adu: np.ndarray
    analog_e: np.ndarray
    expected_e: np.ndarray
    signal_e: np.ndarray
    background_e: float
    dark_e: float
    seed: int
    saturation_fraction: float
    adc_clipped_fraction: float
    flags: tuple[str, ...]

    @property
    def peak_expected_e(self) -> float:
        return float(self.signal_e.max()) if self.signal_e.size else 0.0


def stable_seed(master_seed: int, sample_id: str) -> int:
    """Deterministic 64-bit seed from a master seed and a stable sample id."""

    digest = hashlib.blake2b(f"{master_seed}|{sample_id}".encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "little")


def render_frame(
    signal_e: np.ndarray,
    background_e_per_px: float,
    sensor: SensorSpec,
    seed: int,
    *,
    noise: bool = True,
) -> RenderResult:
    """Render one frame from an expected signal map."""

    signal = np.asarray(signal_e, dtype=np.float64)
    if signal.ndim != 2:
        raise ValueError("signal_e must be 2-D")
    if not np.all(np.isfinite(signal)) or np.any(signal < 0):
        raise ValueError("signal_e must be finite and non-negative")
    background = float(background_e_per_px)
    if not np.isfinite(background) or background < 0:
        raise ValueError("background must be finite and non-negative")

    dark = sensor.dark_e_per_px
    mu = signal + background + dark
    rng = np.random.default_rng(seed)

    if noise:
        photoelectrons = rng.poisson(mu).astype(np.float64)
        read = rng.normal(0.0, sensor.read_noise_e, size=mu.shape)
        analog = photoelectrons + read
    else:
        # Noise-free evaluation path for V1-B subpixel checks.
        analog = mu.copy()

    saturated = analog >= sensor.full_well_e
    analog = np.minimum(analog, sensor.full_well_e)
    codes = np.floor(analog / sensor.e_per_adu).astype(np.int64) + sensor.black_level_adu
    adc_clipped = (codes < 0) | (codes > sensor.adc_limit)
    codes = np.clip(codes, 0, sensor.adc_limit).astype(np.uint16)

    saturation_fraction = float(np.mean(saturated)) if saturated.size else 0.0
    adc_fraction = float(np.mean(adc_clipped)) if adc_clipped.size else 0.0
    flags = []
    if saturation_fraction > 0:
        flags.append("SATURATED_PIXELS")
    if adc_fraction > 0:
        flags.append("ADC_CLIPPED")

    return RenderResult(
        image_adu=codes,
        analog_e=analog,
        expected_e=mu,
        signal_e=signal,
        background_e=background,
        dark_e=dark,
        seed=int(seed),
        saturation_fraction=saturation_fraction,
        adc_clipped_fraction=adc_fraction,
        flags=tuple(flags),
    )


def sample_pixel(
    mu_signal_e: float,
    background_e_per_px: float,
    sensor: SensorSpec,
    n_samples: int,
    seed: int,
) -> np.ndarray:
    """Independent per-pixel samples used by the V2 statistical tests.

    No clipping is applied here on purpose: the tests compare against the
    untruncated Poisson + Gaussian model.
    """

    mu = float(mu_signal_e) + float(background_e_per_px) + sensor.dark_e_per_px
    if mu < 0:
        raise ValueError("mu must be non-negative")
    rng = np.random.default_rng(seed)
    photoelectrons = rng.poisson(mu, size=n_samples).astype(np.float64)
    read = rng.normal(0.0, sensor.read_noise_e, size=n_samples)
    return photoelectrons + read


def to_electrons(image_adu: np.ndarray, sensor: SensorSpec) -> np.ndarray:
    """Convert ADU to an analog-electron estimate (for estimators)."""

    return (np.asarray(image_adu, dtype=np.float64) - sensor.black_level_adu) * sensor.e_per_adu
