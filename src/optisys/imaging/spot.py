"""L0 spot model: circular 2-D Gaussian integrated over pixel areas.

Amplitude convention
--------------------
The Gaussian is parameterised by the **total** expected signal over the
infinite plane, ``total_electrons``:

    G(x, y) = total / (2*pi*sigma^2) * exp(-((x-u)^2 + (y-v)^2) / (2*sigma^2))

so that the continuous integral is exactly ``total_electrons``.  The peak
value is ``total / (2*pi*sigma^2)`` electrons per pixel; this is NOT the
``peak_electrons`` field of the schema-1.0 configuration, which is not reused.

Pixel ``(row=i, col=j)`` covers ``[j-0.5, j+0.5] x [i-0.5, i+0.5]`` in pixel
centre coordinates, matching the geometry contract of G0 (pixel centres at
integer indices).  The integrated weight is the product of normal-CDF
differences, which is exact for a separable Gaussian.

No re-normalisation is ever applied after clipping: ``capture_fraction`` reports
how much of the continuous signal actually lands on the chip / ROI.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.special import ndtr


@dataclass(frozen=True)
class SpotSpec:
    center_px: tuple[float, float]
    sigma_px: float
    total_electrons: float

    def __post_init__(self) -> None:
        if not np.isfinite(self.sigma_px) or self.sigma_px <= 0:
            raise ValueError("sigma_px must be positive and finite")
        if not np.isfinite(self.total_electrons) or self.total_electrons < 0:
            raise ValueError("total_electrons must be non-negative and finite")
        for value in self.center_px:
            if not np.isfinite(value):
                raise ValueError("center_px must be finite")

    @property
    def peak_e_per_px(self) -> float:
        return float(self.total_electrons / (2.0 * np.pi * self.sigma_px**2))


def marginal_edges(n_pixels: int) -> np.ndarray:
    """Pixel boundaries in centre coordinates: -0.5, 0.5, ..., n-0.5."""

    return np.arange(n_pixels + 1, dtype=float) - 0.5


def marginal_probabilities(n_pixels: int, center: float, sigma: float) -> np.ndarray:
    """Probability mass of each pixel column for a 1-D normal."""

    edges = marginal_edges(n_pixels)
    return np.diff(ndtr((edges - center) / sigma))


def integrated_weights(width: int, height: int, spot: SpotSpec) -> np.ndarray:
    """Expected electrons per pixel over the full chip, shape ``(height, width)``."""

    u0, v0 = spot.center_px
    px = marginal_probabilities(width, u0, spot.sigma_px)
    py = marginal_probabilities(height, v0, spot.sigma_px)
    return spot.total_electrons * np.outer(py, px)


def capture_fraction(width: int, height: int, spot: SpotSpec) -> float:
    """Fraction of the continuous total that lands on the chip."""

    u0, v0 = spot.center_px
    px = marginal_probabilities(width, u0, spot.sigma_px).sum()
    py = marginal_probabilities(height, v0, spot.sigma_px).sum()
    return float(px * py)


def pixel_weight_numeric(u_index: int, v_index: int, spot: SpotSpec,
                         nodes: int = 16) -> float:
    """Independent Gauss-Legendre integration of one pixel (verification only)."""

    nodes, weights = np.polynomial.legendre.leggauss(nodes)
    # Map [-1, 1] to each pixel edge interval.
    def integrate_axis(index: int, center: float) -> float:
        lo, hi = index - 0.5, index + 0.5
        points = 0.5 * (hi - lo) * nodes + 0.5 * (hi + lo)
        values = np.exp(-0.5 * ((points - center) / spot.sigma_px) ** 2)
        return float(0.5 * (hi - lo) * np.dot(weights, values))

    normalisation = 2.0 * np.pi * spot.sigma_px**2
    return float(
        spot.total_electrons / normalisation
        * integrate_axis(u_index, spot.center_px[0])
        * integrate_axis(v_index, spot.center_px[1])
    )


def window_bounds(spot: SpotSpec, width: int, height: int, n_sigma: float = 8.0
                  ) -> tuple[int, int, int, int]:
    """Bounding window ``(row0, row1, col0, col1)`` covering ``n_sigma``."""

    u0, v0 = spot.center_px
    half = n_sigma * spot.sigma_px
    col0 = max(0, int(np.floor(u0 - half)))
    col1 = min(width, int(np.ceil(u0 + half)) + 1)
    row0 = max(0, int(np.floor(v0 - half)))
    row1 = min(height, int(np.ceil(v0 + half)) + 1)
    return row0, row1, col0, col1
