"""Spot kernels: geometric footprint convolved with a scalar Airy limit.

Terminology is enforced here, not left to prose:

* ``geometric``  — a histogram of traced image-plane intersections.  A ray
  footprint, **not** a diffraction PSF.
* ``airy``       — the scalar diffraction limit of a circular aperture,
  ``[2 J1(v)/v]^2`` with first zero at ``1.22 λ F/#``.  A *model*.
* ``combined``   — geometric ⊛ airy.  The production kernel.  It is labelled
  ``L1-approximate`` and must never be called a wavefront PSF.

The kernel is normalised **once**, over the window, and is never re-normalised
after clipping: energy that leaves the sensor is lost, not redistributed.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.special import j0, j1

from optisys.errors import Status

KERNEL_KIND_GEOMETRIC = "geometric_footprint"
KERNEL_KIND_COMBINED = "geometric_footprint_x_airy"
KERNEL_KIND_AIRY = "airy_limit_model"


@dataclass(frozen=True)
class KernelSpec:
    #: Must be odd: with an even sub-pixel count the Airy sample that sits at
    #: the exact centre does not exist, and any centred convolution shifts the
    #: kernel by half a sub-pixel.  That is a constant bias, i.e. exactly the
    #: kind of error that hides inside a calibration afterwards.
    subpixel: int = 5
    max_half_px: int = 40
    airy_radius_margin: float = 4.0
    include_airy: bool = True

    def __post_init__(self) -> None:
        if self.subpixel < 1 or self.subpixel > 16:
            raise ValueError("subpixel must be in [1, 16]")
        if self.subpixel % 2 == 0:
            raise ValueError("subpixel must be odd so the kernel centre is a sample")
        if self.max_half_px < 4 or self.max_half_px > 256:
            raise ValueError("max_half_px must be in [4, 256]")


@dataclass
class SpotKernel:
    data: np.ndarray
    half_px: int
    center_px: tuple[float, float]
    kind: str
    support_fraction: float
    airy_fraction: float
    status: Status
    message: str = ""

    @property
    def shape(self) -> tuple[int, int]:
        return self.data.shape

    @property
    def total(self) -> float:
        return float(self.data.sum())


def airy_radius_px(wavelength_nm: float, f_number: float, pixel_size_mm: float) -> float:
    """Radius of the first Airy zero, in pixels."""

    if f_number <= 0:
        raise ValueError("f_number must be > 0")
    radius_mm = 1.22 * (wavelength_nm * 1e-6) * f_number
    return float(radius_mm / pixel_size_mm)


def airy_encircled_fraction(radius_px: float, half_px: int) -> float:
    """Analytic enclosed energy of the Airy pattern inside ``half_px`` radius.

    ``E(r)/E_total = 1 - J0(v)^2 - J1(v)^2`` with ``v = 3.8317 r / r0``.
    Uses the inscribed radius ``half_px - 1`` so the value is conservative for
    a square window.
    """

    if radius_px <= 0:
        return 1.0
    r = max(float(half_px) - 1.0, 0.0)
    v = 3.8317059702075125 * r / radius_px
    fraction = 1.0 - j0(v) ** 2 - j1(v) ** 2
    return float(np.clip(fraction, 0.0, 1.0))


def airy_kernel_px(radius_px: float, half_px: int, subpixel: int) -> np.ndarray:
    """Sampled Airy intensity on a ``subpixel`` grid, normalised to sum 1."""

    n = (2 * half_px + 1) * subpixel
    coords = (np.arange(n) + 0.5 - n / 2.0) / subpixel  # pixel units, centre at 0
    xx, yy = np.meshgrid(coords, coords)
    r = np.hypot(xx, yy)
    v = 3.8317059702075125 * r / max(radius_px, 1e-9)
    with np.errstate(divide="ignore", invalid="ignore"):
        amplitude = np.where(v < 1e-9, 1.0, 2.0 * j1(v) / np.where(v < 1e-9, 1.0, v))
    intensity = amplitude**2
    intensity[~np.isfinite(intensity)] = 0.0
    total = intensity.sum()
    if total <= 0:
        raise ValueError("degenerate Airy kernel")
    return intensity / total


def build_kernel(
    u_px: np.ndarray,
    v_px: np.ndarray,
    weights: np.ndarray,
    center_px: tuple[float, float],
    *,
    airy_radius: float,
    spec: KernelSpec,
    kind: str = KERNEL_KIND_COMBINED,
) -> SpotKernel:
    """Histogram the footprint and (optionally) convolve with the Airy model."""

    u = np.asarray(u_px, dtype=float)
    v = np.asarray(v_px, dtype=float)
    w = np.asarray(weights, dtype=float)
    if u.shape != v.shape or u.shape != w.shape:
        raise ValueError("u, v and weights must share a shape")
    finite = np.isfinite(u) & np.isfinite(v) & np.isfinite(w) & (w > 0)
    if not np.any(finite):
        return SpotKernel(
            data=np.zeros((1, 1)), half_px=0, center_px=center_px, kind=kind,
            support_fraction=0.0, airy_fraction=0.0,
            status=Status.ALL_RAYS_BLOCKED, message="no finite, positive-weight rays",
        )
    u, v, w = u[finite], v[finite], w[finite]
    total_weight = float(w.sum())

    du = u - center_px[0]
    dv = v - center_px[1]
    margin = spec.airy_radius_margin * max(airy_radius, 0.5) if spec.include_airy else 0.0
    half = int(np.ceil(max(np.abs(du).max(), np.abs(dv).max()) + margin + 1.0))
    half = max(half, 3)
    if half > spec.max_half_px:
        return SpotKernel(
            data=np.zeros((1, 1)), half_px=half, center_px=center_px, kind=kind,
            support_fraction=0.0, airy_fraction=0.0,
            status=Status.INSUFFICIENT_PSF_SUPPORT,
            message=f"required half-width {half} px exceeds cap {spec.max_half_px} px",
        )
    if kind == KERNEL_KIND_AIRY:
        data_sub = airy_kernel_px(airy_radius, half, spec.subpixel) * total_weight
        geom_frac = 1.0
    else:
        n_sub = (2 * half + 1) * spec.subpixel
        hist = np.zeros((n_sub, n_sub), dtype=float)
        # Pixel cells are centred on integer indices, so a ray at du = 0 belongs
        # to the cell spanning [-0.5, +0.5).  Omitting the +0.5 term shifts the
        # whole kernel by half a pixel - a bias that would be absorbed by the
        # calibration and silently bias every reported depth.
        col = np.floor((du + half + 0.5) * spec.subpixel).astype(int)
        row = np.floor((dv + half + 0.5) * spec.subpixel).astype(int)
        inside = (col >= 0) & (col < n_sub) & (row >= 0) & (row < n_sub)
        np.add.at(hist, (row[inside], col[inside]), w[inside])
        geom_frac = float(hist.sum() / total_weight) if total_weight else 0.0
        # Deliberately NOT re-normalised: energy that leaves the window is lost
        # and must be reported, never redistributed onto the remaining pixels.
        if spec.include_airy and kind == KERNEL_KIND_COMBINED:
            airy = airy_kernel_px(airy_radius, half, spec.subpixel)
            data_sub = _convolve_same(hist, airy)
        else:
            data_sub = hist
    data = _block_sum(data_sub, spec.subpixel)

    ray_frac = float(np.sum(w[(np.abs(du) <= half + 0.5) & (np.abs(dv) <= half + 0.5)])
                     / total_weight)
    airy_frac = airy_encircled_fraction(radius_px=airy_radius, half_px=half)
    if not spec.include_airy:
        airy_frac = 1.0

    support = float(geom_frac * airy_frac) if spec.include_airy else float(geom_frac)
    status = Status.OK
    message = "ok"
    if kind != KERNEL_KIND_AIRY and ray_frac < 0.999:
        status = Status.INSUFFICIENT_PSF_SUPPORT
        message = f"only {ray_frac:.4f} of the ray weight lies inside the window"
    return SpotKernel(
        data=data, half_px=half, center_px=center_px, kind=kind,
        support_fraction=support, airy_fraction=airy_frac,
        status=status, message=message,
    )


def _convolve_same(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Centred 2-D convolution with the output shape of ``a``.

    ``scipy.signal.fftconvolve(mode="same")`` is used on purpose: for an
    **even**-sized kernel the centre lies between samples, and a hand-written
    ``b.shape // 2`` crop shifts the result by half a subpixel.  That is small,
    but it is a constant bias that would be absorbed by the calibration and
    then look like a real systematic error.
    """

    from scipy.signal import fftconvolve

    return fftconvolve(a, b, mode="same")


def _block_sum(a: np.ndarray, factor: int) -> np.ndarray:
    if factor == 1:
        return a.copy()
    rows = a.shape[0] // factor
    cols = a.shape[1] // factor
    trimmed = a[: rows * factor, : cols * factor]
    return trimmed.reshape(rows, factor, cols, factor).sum(axis=(1, 3))


def place_kernel(kernel: SpotKernel, width: int, height: int,
                 center_px: tuple[float, float]) -> tuple[np.ndarray, float]:
    """Place a kernel into a full-chip array without re-normalising.

    Returns ``(image, placed_fraction)`` where ``placed_fraction`` is the part
    of the kernel that landed on the chip.
    """

    data = kernel.data
    half = kernel.half_px
    col0 = int(round(center_px[0])) - half
    row0 = int(round(center_px[1])) - half
    canvas = np.zeros((height, width), dtype=float)
    placed = 0.0
    r_src0 = max(0, -row0)
    c_src0 = max(0, -col0)
    r_dst0 = max(0, row0)
    c_dst0 = max(0, col0)
    r_dst1 = min(height, row0 + data.shape[0])
    c_dst1 = min(width, col0 + data.shape[1])
    if r_dst1 <= r_dst0 or c_dst1 <= c_dst0:
        return canvas, 0.0
    r_src1 = r_src0 + (r_dst1 - r_dst0)
    c_src1 = c_src0 + (c_dst1 - c_dst0)
    block = data[r_src0:r_src1, c_src0:c_src1]
    canvas[r_dst0:r_dst1, c_dst0:c_dst1] = block
    placed = float(block.sum())
    return canvas, placed
