"""Single data contract between the optical model and the CMOS chain.

Every consumer (imaging, estimation, tolerance, optimisation) sees the same
:class:`OpticalImageResult`.  No module may invent a private PSF/CMS coupling.

Contract rules
--------------
1. ``expected_signal_e`` is in **electrons per pixel**, exclusive of background,
   dark current and read noise.
2. Pixel-area integration happens exactly once: the spot kernel is built by
   area-weighted binning, so the image generator must not integrate again.
3. ``capture_fraction`` is ``placed_energy / transmitted_energy``.  Energy that
   leaves the chip is lost, never re-normalised.
4. ``psf_kernel`` is ``None`` unless a model actually produced one; the kind is
   recorded in ``kernel_kind``.  A geometric footprint is never relabelled.
5. Unknown quantities are ``None``, never ``0.0``.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from optisys.errors import Status
from optisys.optics.optiland_adapter import (
    Footprint,
    OptilandTracer,
    SingletModel,
    trace_summary,
)
from optisys.optics.psf_or_footprint import (
    KERNEL_KIND_COMBINED,
    KERNEL_KIND_GEOMETRIC,
    KernelSpec,
    SpotKernel,
    airy_radius_px,
    build_kernel,
    place_kernel,
)

MODEL_LEVEL_L0 = "L0"
MODEL_LEVEL_L1 = "L1-approximate"

SIGNAL_MODE_FIXED = "fixed_incident"
SIGNAL_MODE_BUDGET = "relative_photon_budget"
SUPPORTED_SIGNAL_MODES = (SIGNAL_MODE_FIXED, SIGNAL_MODE_BUDGET)


@dataclass(frozen=True)
class CameraGeometry:
    width_px: int
    height_px: int
    pixel_size_mm: float
    cx_px: float
    cy_px: float

    @property
    def orientation(self) -> dict[str, Any]:
        return {
            "u_axis": "sensor column, +u follows object +X after the lens flip",
            "v_axis": "sensor row, constant for the coplanar case",
            "l0_mapping": "u = cx + fx * X/Z  (virtual image plane in front of the pinhole)",
            "l1_mapping": "u = cx - y_img/p, v = cy + x_img/p  (real inverted image)",
            "length_unit": "mm",
            "pixel_unit": "pixel (centres at integer indices)",
        }


@dataclass
class OpticalImageResult:
    expected_signal_e: np.ndarray
    spot_center_px: tuple[float, float]
    capture_fraction: float
    ray_success_fraction: float | None
    vignetting_fraction: float | None
    geometric_footprint: np.ndarray | None
    psf_kernel: np.ndarray | None
    model_level: str
    optical_config_hash: str
    units_and_image_orientation: dict[str, Any]
    warnings_and_status: tuple[str, ...]
    status: Status
    kernel_kind: str | None = None
    support_fraction: float | None = None
    transmitted_energy_fraction: float | None = None
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status is Status.OK


class L1OpticalModel:
    """Real singlet + geometric footprint + Airy limit -> CMOS electrons."""

    model_level = MODEL_LEVEL_L1

    def __init__(
        self,
        camera: CameraGeometry,
        lens: SingletModel,
        *,
        kernel_spec: KernelSpec | None = None,
        signal_mode: str = SIGNAL_MODE_FIXED,
        reference_electrons: float = 40000.0,
        reference_distance_mm: float = 200.0,
        reference_aperture_mm: float | None = None,
        tracer: OptilandTracer | None = None,
    ) -> None:
        if signal_mode not in SUPPORTED_SIGNAL_MODES:
            raise ValueError(f"unsupported signal_mode {signal_mode!r}")
        self.camera = camera
        self.lens = lens
        self.kernel_spec = kernel_spec or KernelSpec()
        self.signal_mode = signal_mode
        self.reference_electrons = float(reference_electrons)
        self.reference_distance_mm = float(reference_distance_mm)
        self.reference_aperture_mm = float(
            reference_aperture_mm if reference_aperture_mm is not None else lens.aperture_mm
        )
        self.tracer = tracer or OptilandTracer(lens)
        self._airy_radius = airy_radius_px(
            lens.wavelength_nm, lens.working_f_number, camera.pixel_size_mm
        )

    # ------------------------------------------------------------------
    @property
    def optical_config_hash(self) -> str:
        payload = (
            f"{self.lens.config_hash}|{self.camera.width_px}x{self.camera.height_px}"
            f"|p={self.camera.pixel_size_mm:.12g}|cx={self.camera.cx_px:.12g}"
            f"|cy={self.camera.cy_px:.12g}|mode={self.signal_mode}"
            f"|eref={self.reference_electrons:.12g}|zref={self.reference_distance_mm:.12g}"
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @property
    def airy_radius_px(self) -> float:
        return self._airy_radius

    def collected_electrons(self, distance_mm: float) -> float:
        """Incident electrons on the receiver for this scene."""

        if self.signal_mode == SIGNAL_MODE_FIXED:
            return float(self.reference_electrons)
        ratio_aperture = (self.lens.aperture_mm / self.reference_aperture_mm) ** 2
        ratio_distance = (self.reference_distance_mm / float(distance_mm)) ** 2
        return float(self.reference_electrons * ratio_aperture * ratio_distance)

    # ------------------------------------------------------------------
    def image(self, distance_mm: float, object_height_mm: float,
              *, total_electrons: float | None = None,
              include_airy: bool | None = None) -> OpticalImageResult:
        spec = self.kernel_spec
        if include_airy is not None and include_airy != spec.include_airy:
            spec = KernelSpec(
                subpixel=spec.subpixel, max_half_px=spec.max_half_px,
                airy_radius_margin=spec.airy_radius_margin, include_airy=include_airy,
            )
        footprint = self.tracer.trace(float(distance_mm), float(object_height_mm))
        if footprint.status is not Status.OK:
            return OpticalImageResult(
                expected_signal_e=np.zeros((self.camera.height_px, self.camera.width_px)),
                spot_center_px=(float("nan"), float("nan")),
                capture_fraction=0.0,
                ray_success_fraction=footprint.ray_success_fraction,
                vignetting_fraction=1.0 - footprint.ray_success_fraction,
                geometric_footprint=None, psf_kernel=None,
                model_level=self.model_level,
                optical_config_hash=self.optical_config_hash,
                units_and_image_orientation=self.camera.orientation,
                warnings_and_status=(footprint.status.value,), status=footprint.status,
            )

        summary = trace_summary(
            footprint, self.camera.pixel_size_mm, self.camera.cx_px, self.camera.cy_px
        )
        u_px, v_px, weights = _footprint_pixels(footprint, self.camera)
        center = (summary["centroid_u_px"], summary["centroid_v_px"])
        # Build the kernel on the *pixel* grid: the fractional part of the spot
        # position must live inside the sampled kernel, otherwise rounding the
        # placement to an integer would shift the image by up to half a pixel.
        place_at = (float(round(center[0])), float(round(center[1])))
        kernel = build_kernel(
            u_px, v_px, weights, place_at,
            airy_radius=self._airy_radius,
            spec=spec,
            kind=KERNEL_KIND_COMBINED if spec.include_airy else KERNEL_KIND_GEOMETRIC,
        )
        if kernel.status is not Status.OK:
            return OpticalImageResult(
                expected_signal_e=np.zeros((self.camera.height_px, self.camera.width_px)),
                spot_center_px=center,
                capture_fraction=0.0,
                ray_success_fraction=footprint.ray_success_fraction,
                vignetting_fraction=1.0 - footprint.ray_success_fraction,
                geometric_footprint=None, psf_kernel=None,
                model_level=self.model_level,
                optical_config_hash=self.optical_config_hash,
                units_and_image_orientation=self.camera.orientation,
                warnings_and_status=(kernel.status.value, kernel.message),
                status=kernel.status, kernel_kind=kernel.kind,
            )

        transmitted = float(kernel.total)
        canvas, placed = place_kernel(kernel, self.camera.width_px, self.camera.height_px, center)
        capture = placed / transmitted if transmitted > 0 else 0.0

        e_total = self.collected_electrons(distance_mm) if total_electrons is None else float(
            total_electrons
        )
        signal = canvas * e_total

        if not np.all(np.isfinite(signal)) or np.any(signal < 0):
            return OpticalImageResult(
                expected_signal_e=np.zeros((self.camera.height_px, self.camera.width_px)),
                spot_center_px=center, capture_fraction=capture,
                ray_success_fraction=footprint.ray_success_fraction,
                vignetting_fraction=1.0 - footprint.ray_success_fraction,
                geometric_footprint=None, psf_kernel=kernel.data,
                model_level=self.model_level,
                optical_config_hash=self.optical_config_hash,
                units_and_image_orientation=self.camera.orientation,
                warnings_and_status=(Status.NONPHYSICAL_ENERGY.value,),
                status=Status.NONPHYSICAL_ENERGY, kernel_kind=kernel.kind,
            )

        status = Status.OK
        warnings_out: list[str] = []
        if capture < 0.999:
            status = Status.OUT_OF_SENSOR_PARTIAL
            warnings_out.append(f"capture_fraction={capture:.4f}")
        if kernel.support_fraction < 0.999:
            warnings_out.append(f"kernel_support={kernel.support_fraction:.4f}")

        return OpticalImageResult(
            expected_signal_e=signal,
            spot_center_px=center,
            capture_fraction=capture,
            ray_success_fraction=footprint.ray_success_fraction,
            vignetting_fraction=1.0 - footprint.ray_success_fraction,
            geometric_footprint=kernel.data if not spec.include_airy else None,
            psf_kernel=kernel.data if spec.include_airy else None,
            model_level=self.model_level,
            optical_config_hash=self.optical_config_hash,
            units_and_image_orientation=self.camera.orientation,
            warnings_and_status=tuple(warnings_out) if warnings_out else ("OK",),
            status=status,
            kernel_kind=kernel.kind,
            support_fraction=kernel.support_fraction,
            transmitted_energy_fraction=transmitted,
            diagnostics={
                "trace": summary,
                "kernel_half_px": kernel.half_px,
                "airy_radius_px": self._airy_radius,
                "f_number": self.lens.working_f_number,
                "electrons_in": e_total,
                "expected_peak_e": float(signal.max()) if signal.size else 0.0,
                "expected_sum_e": float(signal.sum()),
            },
        )

    def clear_cache(self) -> None:
        self.tracer.clear_cache()


def _footprint_pixels(footprint: Footprint, camera: CameraGeometry
                      ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Map valid image-plane hits to pixel coordinates with equal ray weights."""

    valid = footprint.valid
    n = footprint.n_launched
    u = camera.cx_px - footprint.y_mm[valid] / camera.pixel_size_mm
    v = camera.cy_px + footprint.x_mm[valid] / camera.pixel_size_mm
    w = footprint.intensity[valid] / float(n)
    return u, v, w


class L0OpticalModel:
    """G1 pinhole + circular Gaussian, exposed through the same contract.

    Used only as the L0 limiting case in V4-B4.  It never claims to be optics.
    """

    model_level = MODEL_LEVEL_L0

    def __init__(self, camera: CameraGeometry, *, sigma_px: float, fx_px: float) -> None:
        self.camera = camera
        self.sigma_px = float(sigma_px)
        self.fx_px = float(fx_px)

    @property
    def optical_config_hash(self) -> str:
        payload = f"L0|sigma={self.sigma_px}|fx={self.fx_px}|p={self.camera.pixel_size_mm}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def image(self, distance_mm: float, object_height_mm: float,
              *, total_electrons: float = 40000.0, **_ignored: Any) -> OpticalImageResult:
        from optisys.imaging.spot import SpotSpec, capture_fraction, integrated_weights

        u = self.camera.cx_px + self.fx_px * object_height_mm / float(distance_mm)
        v = self.camera.cy_px
        spot = SpotSpec((u, v), self.sigma_px, float(total_electrons))
        weights = integrated_weights(self.camera.width_px, self.camera.height_px, spot)
        return OpticalImageResult(
            expected_signal_e=weights,
            spot_center_px=(u, v),
            capture_fraction=capture_fraction(
                self.camera.width_px, self.camera.height_px, spot
            ),
            ray_success_fraction=None,
            vignetting_fraction=None,
            geometric_footprint=None,
            psf_kernel=None,
            model_level=self.model_level,
            optical_config_hash=self.optical_config_hash,
            units_and_image_orientation=self.camera.orientation,
            warnings_and_status=("L0 model: no lens, no ray trace",),
            status=Status.OK,
            kernel_kind="gaussian_area_integrated",
            support_fraction=1.0,
            transmitted_energy_fraction=1.0,
        )
