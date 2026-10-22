"""ROI detection from the image itself (never from the generator truth)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage

from optisys.config_g1 import SensorSpec
from optisys.errors import Status
from optisys.imaging.sensor import to_electrons


@dataclass(frozen=True)
class RoiResult:
    roi: tuple[int, int, int, int] | None
    status: Status
    background_e: float
    noise_e: float
    threshold_e: float
    peak_e: float
    pixels_above: int
    touches_border: bool
    message: str

    @property
    def valid(self) -> bool:
        return self.roi is not None and self.status is Status.OK


def detect_roi(
    image_adu: np.ndarray,
    sensor: SensorSpec,
    *,
    k_sigma: float = 5.0,
    margin_px: int = 6,
) -> RoiResult:
    """Threshold + bounding box ROI detection with robust background estimate."""

    electrons = to_electrons(image_adu, sensor)
    height, width = electrons.shape

    # Robust background from a strided subsample: full-frame medians cost
    # ~40 ms per frame and do not change the detection decision.
    stride = max(1, min(electrons.shape) // 256)
    sample = electrons[::stride, ::stride]
    background = float(np.median(sample))
    mad = float(np.median(np.abs(sample - background)))
    noise = 1.4826 * mad
    if not np.isfinite(noise) or noise <= 0:
        noise = 1.0  # quantisation floor; avoids division by zero in flat frames
    threshold = background + k_sigma * noise

    mask = electrons > threshold
    pixels_above = int(mask.sum())
    if pixels_above < 3:
        return RoiResult(
            roi=None, status=Status.NO_SIGNAL, background_e=background, noise_e=noise,
            threshold_e=threshold, peak_e=float(electrons.max()) if electrons.size else 0.0,
            pixels_above=pixels_above, touches_border=False,
            message=f"only {pixels_above} pixels above threshold",
        )

    # Use the connected component that contains the brightest pixel.  A
    # global bounding box is not robust: one Poisson outlier would stretch it
    # across the whole chip.
    labels, _ = ndimage.label(mask, structure=np.ones((3, 3), dtype=int))
    peak_index = np.unravel_index(int(np.argmax(electrons)), electrons.shape)
    label_id = int(labels[peak_index])
    if label_id == 0:
        return RoiResult(
            roi=None, status=Status.NO_SIGNAL, background_e=background, noise_e=noise,
            threshold_e=threshold, peak_e=float(electrons[peak_index]),
            pixels_above=pixels_above, touches_border=False,
            message="brightest pixel is below threshold",
        )
    component = labels == label_id
    rows = np.flatnonzero(component.any(axis=1))
    cols = np.flatnonzero(component.any(axis=0))
    row0 = max(0, int(rows[0]) - margin_px)
    row1 = min(height, int(rows[-1]) + margin_px + 1)
    col0 = max(0, int(cols[0]) - margin_px)
    col1 = min(width, int(cols[-1]) + margin_px + 1)

    touches = row0 == 0 or col0 == 0 or row1 == height or col1 == width
    status = Status.ROI_TRUNCATED if touches else Status.OK
    return RoiResult(
        roi=(row0, row1, col0, col1),
        status=status,
        background_e=background,
        noise_e=noise,
        threshold_e=threshold,
        peak_e=float(electrons[row0:row1, col0:col1].max()),
        pixels_above=pixels_above,
        touches_border=touches,
        message="ok" if not touches else "ROI touches the image border",
    )
