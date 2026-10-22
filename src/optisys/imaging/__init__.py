"""Imaging package: L0 spot formation, ROI detection and sensor rendering."""

from optisys.imaging.roi import RoiResult, detect_roi
from optisys.imaging.sensor import RenderResult, render_frame, sample_pixel, stable_seed, to_electrons
from optisys.imaging.spot import SpotSpec, capture_fraction, integrated_weights, pixel_weight_numeric

__all__ = [
    "SpotSpec",
    "capture_fraction",
    "integrated_weights",
    "pixel_weight_numeric",
    "RenderResult",
    "render_frame",
    "sample_pixel",
    "stable_seed",
    "to_electrons",
    "RoiResult",
    "detect_roi",
]
