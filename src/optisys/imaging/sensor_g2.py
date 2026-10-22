"""G2 sensor renderer: distribution-equivalent to G1, but faster.

Why a second renderer
---------------------
G1's :func:`optisys.imaging.sensor.render_frame` draws ``Poisson(mu)`` with
``mu`` a full-size *array*.  NumPy's array-``lambda`` Poisson path costs about
110 ms for 1280x1024.  The background is spatially uniform, so it can be drawn
with a scalar ``lambda`` (fast) and only the sparse signal support needs an
array draw.  The two are statistically identical: independent Poisson draws
over disjoint pixel sets.

G1's function is **not modified** - its frozen evidence and source hash must
stay valid.  This module is the G2-only path and is checked against G1 by a
KS/mean/variance test in ``tests/unit/test_sensor_g2.py``.

Two distinct saturation mechanisms are reported separately:

* ``FULL_WELL_SATURATION`` - the analog chain reaches ``full_well_e``.
* ``ADC_CLIPPING``          - the 12-bit code saturates at
  ``(adc_limit - black_level) * e_per_adu``, which is **lower** than the full
  well for the frozen sensor settings (11 985 e vs 15 000 e).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from optisys.config_g1 import SensorSpec


@dataclass
class RenderResultG2:
    image_adu: np.ndarray
    analog_e: np.ndarray
    expected_e: np.ndarray
    signal_e: np.ndarray
    background_e: float
    dark_e: float
    seed: int
    full_well_saturation_fraction: float
    adc_clipping_fraction: float
    any_saturation_fraction: float
    flags: tuple[str, ...]

    @property
    def peak_expected_e(self) -> float:
        return float(self.signal_e.max()) if self.signal_e.size else 0.0

    @property
    def saturation_fraction(self) -> float:
        """Union of both saturation mechanisms, for legacy reporting code."""

        return float(self.any_saturation_fraction)


def adc_ceiling_e(sensor: SensorSpec) -> float:
    """Analog electrons at which the 12-bit code saturates."""

    return float(sensor.adc_limit - sensor.black_level_adu) * sensor.e_per_adu


def render_frame_g2(
    signal_e: np.ndarray,
    background_e_per_px: float,
    sensor: SensorSpec,
    seed: int,
    *,
    noise: bool = True,
) -> RenderResultG2:
    signal = np.asarray(signal_e, dtype=np.float64)
    if signal.ndim != 2:
        raise ValueError("signal_e must be 2-D")
    if not np.all(np.isfinite(signal)) or np.any(signal < 0):
        raise ValueError("signal_e must be finite and non-negative")
    background = float(background_e_per_px)
    if not np.isfinite(background) or background < 0:
        raise ValueError("background must be finite and non-negative")

    dark = sensor.dark_e_per_px
    bg = background + dark
    rng = np.random.default_rng(seed)

    if noise:
        photoelectrons = rng.poisson(bg, size=signal.shape).astype(np.float64)
        support = signal > 0.0
        if np.any(support):
            photoelectrons[support] = rng.poisson(
                bg + signal[support]
            ).astype(np.float64)
        read = rng.normal(0.0, sensor.read_noise_e, size=signal.shape)
        analog = photoelectrons + read
    else:
        analog = signal + bg

    full_well = analog >= sensor.full_well_e
    analog = np.minimum(analog, sensor.full_well_e)
    codes = np.floor(analog / sensor.e_per_adu).astype(np.int64) + sensor.black_level_adu
    adc_clipped = (codes < 0) | (codes > sensor.adc_limit)
    codes = np.clip(codes, 0, sensor.adc_limit).astype(np.uint16)

    fw_fraction = float(np.mean(full_well)) if full_well.size else 0.0
    adc_fraction = float(np.mean(adc_clipped)) if adc_clipped.size else 0.0
    any_fraction = float(np.mean(full_well | adc_clipped)) if full_well.size else 0.0
    flags: list[str] = []
    if fw_fraction > 0:
        flags.append("FULL_WELL_SATURATION")
    if adc_fraction > 0:
        flags.append("ADC_CLIPPING")
    if flags:
        flags.append("SATURATED")

    return RenderResultG2(
        image_adu=codes,
        analog_e=analog,
        expected_e=signal + bg,
        signal_e=signal,
        background_e=background,
        dark_e=dark,
        seed=int(seed),
        full_well_saturation_fraction=fw_fraction,
        adc_clipping_fraction=adc_fraction,
        any_saturation_fraction=any_fraction,
        flags=tuple(flags),
    )
