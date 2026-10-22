"""Adapter around the Optiland 0.6.3 sequential ray tracer.

Design rules
------------
* The third-party engine performs the ray trace.  Everything else (pupil
  sampling, footprint reduction, energy bookkeeping, pixel mapping) is ours
  and is version-independent.
* No other module imports Optiland types.  This file is the only boundary.
* Rays are launched explicitly with :class:`optiland.rays.RealRays`, so the
  pupil sampling and the per-ray weights are under our control and auditable.
* Blocked rays are reported, never dropped silently: a ray clipped by an
  aperture returns ``intensity == 0`` and stays in the arrays.
"""

from __future__ import annotations

import hashlib
import warnings
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from optisys.errors import Status
from optisys.optics.reference_thin_lens import ThinLensReference

BACKEND_NAME = "optiland"
SUPPORTED_BACKEND_VERSIONS = ("0.6.3",)


class OpticsBackendError(RuntimeError):
    """Raised when the optical backend is missing or cannot execute."""


class BackendNameError(ValueError):
    """Raised when a configuration requests an unknown optical backend."""


def backend_info() -> dict[str, Any]:
    """Import Optiland and report its real version. Never fabricates success."""

    info: dict[str, Any] = {
        "backend": BACKEND_NAME,
        "importable": False,
        "version": None,
        "version_supported": False,
        "error": None,
    }
    try:
        import importlib.metadata as md

        import optiland  # noqa: F401

        version = md.version("optiland")
        info["importable"] = True
        info["version"] = version
        info["version_supported"] = version in SUPPORTED_BACKEND_VERSIONS
        info["module_file"] = getattr(optiland, "__file__", None)
    except Exception as exc:  # pragma: no cover - depends on the environment
        info["error"] = f"{type(exc).__name__}: {exc}"
    return info


def _require_backend():
    try:
        import optiland.backend as be

        be.set_backend("numpy")
    except Exception as exc:  # pragma: no cover
        raise OpticsBackendError(f"optiland backend unavailable: {exc}") from exc
    from optiland.optic import Optic
    from optiland.physical_apertures import RadialAperture
    from optiland.rays import RealRays

    return Optic, RadialAperture, RealRays


@dataclass(frozen=True)
class SingletModel:
    """Declared single-element lens plus the detector placement."""

    focal_length_mm: float
    aperture_mm: float
    thickness_mm: float
    material: str
    index: float
    wavelength_nm: float
    rear_aperture_clearance_mm: float
    focus_distance_mm: float
    #: pupil grid: number of points per axis over the diameter
    pupil_side: int = 17
    #: axial offset of the detector from the paraxial focus (mm)
    sensor_offset_mm: float = 0.0

    reference: ThinLensReference = field(init=False)
    sensor_distance_mm: float = field(init=False)
    radius_mm: float = field(init=False)

    def __post_init__(self) -> None:
        ref = ThinLensReference(
            focal_length_mm=self.focal_length_mm,
            aperture_mm=self.aperture_mm,
            thickness_mm=self.thickness_mm,
            index=self.index,
        )
        object.__setattr__(self, "reference", ref)
        object.__setattr__(self, "radius_mm", ref.radius_mm)
        object.__setattr__(
            self,
            "sensor_distance_mm",
            ref.sensor_distance_mm(self.focus_distance_mm) + float(self.sensor_offset_mm),
        )

    # -- identity ------------------------------------------------------
    @property
    def config_hash(self) -> str:
        payload = "|".join(
            f"{key}={value!r}"
            for key, value in (
                ("f", round(self.focal_length_mm, 12)),
                ("D", round(self.aperture_mm, 12)),
                ("t", round(self.thickness_mm, 12)),
                ("n", round(self.index, 12)),
                ("lambda", round(self.wavelength_nm, 12)),
                ("rear_clearance", round(self.rear_aperture_clearance_mm, 12)),
                ("focus", round(self.focus_distance_mm, 12)),
                ("sensor_offset", round(self.sensor_offset_mm, 12)),
                ("pupil", self.pupil_side),
                ("model", "singlet_equiconvex"),
            )
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    @property
    def working_f_number(self) -> float:
        return float(self.sensor_distance_mm / self.aperture_mm)

    def describe(self) -> dict[str, Any]:
        return {
            "model": "singlet_equiconvex",
            "material": self.material,
            "design_index": self.index,
            "wavelength_nm": self.wavelength_nm,
            "focal_length_mm": self.focal_length_mm,
            "radius_1_mm": self.radius_mm,
            "radius_2_mm": -self.radius_mm,
            "element_thickness_mm": self.thickness_mm,
            "aperture_stop_mm": self.aperture_mm,
            "rear_clear_aperture_mm": self.rear_clear_aperture_mm,
            "rear_aperture_clearance_mm": self.rear_aperture_clearance_mm,
            "focus_distance_mm": self.focus_distance_mm,
            "sensor_distance_from_rear_vertex_mm": self.sensor_distance_mm,
            "sensor_offset_mm": self.sensor_offset_mm,
            "efl_mm_from_matrix": self.reference.efl_mm,
            "bfl_mm_from_matrix": self.reference.bfl_mm,
            "rear_principal_offset_mm": self.rear_principal_offset_mm,
            "working_f_number": self.working_f_number,
            "pupil_side": self.pupil_side,
            "config_hash": self.config_hash,
            "provenance": "ASSUMED design; no vendor part number, no measured data",
        }

    @property
    def rear_principal_offset_mm(self) -> float:
        return float(self.reference.rear_principal_offset_mm)

    @property
    def rear_clear_aperture_mm(self) -> float:
        """Mechanical clear radius at the rear surface.

        The barrel has a fixed clearance around the stop, it is **not**
        proportional to the stop diameter: an off-axis chief ray is displaced by
        ``t * tan(u')`` inside the element regardless of how small the stop is,
        so a proportional aperture would clip the beam as the stop closes.
        """

        return float(self.aperture_mm / 2.0 + self.rear_aperture_clearance_mm)

    def with_offsets(self, *, focal_length_mm: float | None = None,
                     focus_distance_mm: float | None = None,
                     aperture_mm: float | None = None) -> "SingletModel":
        return SingletModel(
            focal_length_mm=self.focal_length_mm if focal_length_mm is None else focal_length_mm,
            aperture_mm=self.aperture_mm if aperture_mm is None else aperture_mm,
            thickness_mm=self.thickness_mm,
            material=self.material,
            index=self.index,
            wavelength_nm=self.wavelength_nm,
            rear_aperture_clearance_mm=self.rear_aperture_clearance_mm,
            focus_distance_mm=(
                self.focus_distance_mm if focus_distance_mm is None else focus_distance_mm
            ),
            pupil_side=self.pupil_side,
            sensor_offset_mm=self.sensor_offset_mm,
        )


@dataclass
class Footprint:
    """Intensity-weighted image-plane intersection set for one object point."""

    x_mm: np.ndarray
    y_mm: np.ndarray
    intensity: np.ndarray
    valid: np.ndarray
    chief_x_mm: float
    chief_y_mm: float
    n_launched: int
    n_valid: int
    z_image_mm: float
    status: Status
    message: str = ""

    @property
    def ray_success_fraction(self) -> float:
        return float(self.n_valid / self.n_launched) if self.n_launched else 0.0

    @property
    def energy_fraction(self) -> float:
        total = float(self.intensity.sum())
        return total

    @property
    def centroid_mm(self) -> tuple[float, float]:
        w = self.intensity
        if w.sum() <= 0:
            return float("nan"), float("nan")
        return (
            float(np.sum(self.x_mm * w) / np.sum(w)),
            float(np.sum(self.y_mm * w) / np.sum(w)),
        )

    @property
    def second_moments_mm(self) -> tuple[float, float, float]:
        cx, cy = self.centroid_mm
        w = self.intensity
        total = float(w.sum())
        if total <= 0:
            return float("nan"), float("nan"), float("nan")
        sxx = float(np.sum((self.x_mm - cx) ** 2 * w) / total)
        syy = float(np.sum((self.y_mm - cy) ** 2 * w) / total)
        sxy = float(np.sum((self.x_mm - cx) * (self.y_mm - cy) * w) / total)
        return sxx, syy, sxy

    def peak_to_valley_mm(self) -> tuple[float, float]:
        v = self.valid
        if not np.any(v):
            return float("nan"), float("nan")
        return (
            float(self.x_mm[v].max() - self.x_mm[v].min()),
            float(self.y_mm[v].max() - self.y_mm[v].min()),
        )


class OptilandTracer:
    """Thin wrapper that turns one object point into an image-plane footprint."""

    def __init__(self, model: SingletModel) -> None:
        self.model = model
        self._optic_cache: dict[float, Any] = {}
        self._pupil = self._make_pupil()

    # ------------------------------------------------------------------
    def _make_pupil(self) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Uniform-area cartesian pupil grid plus one explicit chief ray.

        Returns ``(px, py, is_chief)``.  The chief ray is the first entry and is
        excluded from the energy sum by the caller.
        """

        side = int(self.model.pupil_side)
        if side < 3:
            raise ValueError("pupil_side must be >= 3")
        grid = np.linspace(-1.0, 1.0, side)
        gx, gy = np.meshgrid(grid, grid)
        radius = np.hypot(gx, gy)
        inside = radius <= 0.999
        px = gx[inside] * (self.model.aperture_mm / 2.0)
        py = gy[inside] * (self.model.aperture_mm / 2.0)
        px = np.concatenate([[0.0], px])
        py = np.concatenate([[0.0], py])
        is_chief = np.zeros(px.size, dtype=bool)
        is_chief[0] = True
        return px, py, is_chief

    # ------------------------------------------------------------------
    def _build(self, object_distance_mm: float):
        Optic, RadialAperture, _ = _require_backend()
        m = self.model
        optic = Optic(name=f"singlet_f{m.focal_length_mm:.4f}")
        optic.set_aperture("EPD", m.aperture_mm)
        optic.wavelengths.add(m.wavelength_nm / 1000.0, is_primary=True)
        optic.fields.set_type("object_height")
        optic.fields.add(y=1.0)
        optic.surfaces.add(index=0, radius=np.inf, thickness=object_distance_mm,
                           material="air", comment="object plane")
        optic.surfaces.add(index=1, radius=m.radius_mm, thickness=m.thickness_mm,
                           material=m.material, comment="singlet front (stop)", is_stop=True)
        optic.surfaces.surfaces[1].aperture = RadialAperture(m.aperture_mm / 2.0)
        optic.surfaces.add(index=2, radius=-m.radius_mm, thickness=m.sensor_distance_mm,
                           material="air", comment="singlet rear")
        optic.surfaces.surfaces[2].aperture = RadialAperture(m.rear_clear_aperture_mm)
        optic.surfaces.add(index=3, radius=np.inf, thickness=0.0,
                           material="air", comment="detector")
        return optic

    def _optic(self, object_distance_mm: float):
        key = round(float(object_distance_mm), 9)
        cached = self._optic_cache.get(key)
        if cached is None:
            cached = self._build(key)
            self._optic_cache[key] = cached
        return cached

    # ------------------------------------------------------------------
    def trace(self, object_distance_mm: float, object_height_mm: float,
              *, keep_cache: bool = True) -> Footprint:
        """Trace one object point ``(X, 0, Z)`` onto the detector."""

        Optic, RadialAperture, RealRays = _require_backend()
        m = self.model
        optic = self._optic(object_distance_mm)
        px, py, is_chief = self._pupil
        n = px.size

        z_obj = -float(object_distance_mm)
        x0 = np.zeros(n)
        y0 = np.full(n, float(object_height_mm))
        z0 = np.full(n, z_obj)
        dx = px - x0
        dy = py - y0
        dz = np.zeros(n) - z0
        norm = np.sqrt(dx * dx + dy * dy + dz * dz)
        if not np.all(np.isfinite(norm)) or np.any(norm <= 0):
            return Footprint(
                x_mm=np.zeros(0), y_mm=np.zeros(0), intensity=np.zeros(0),
                valid=np.zeros(0, dtype=bool), chief_x_mm=float("nan"),
                chief_y_mm=float("nan"), n_launched=n, n_valid=0, z_image_mm=float("nan"),
                status=Status.OPTICS_TRACE_FAILED, message="invalid launch geometry",
            )

        rays = RealRays(
            x0, y0, z0, dx / norm, dy / norm, dz / norm,
            intensity=np.ones(n), wavelength=np.full(n, m.wavelength_nm / 1000.0),
        )
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            try:
                out = optic.surfaces.trace(rays, record=False)
            except Exception as exc:  # pragma: no cover - engine failure path
                return Footprint(
                    x_mm=np.zeros(0), y_mm=np.zeros(0), intensity=np.zeros(0),
                    valid=np.zeros(0, dtype=bool), chief_x_mm=float("nan"),
                    chief_y_mm=float("nan"), n_launched=n, n_valid=0,
                    z_image_mm=float("nan"), status=Status.OPTICS_TRACE_FAILED,
                    message=f"{type(exc).__name__}: {exc}",
                )

        xi = np.asarray(out.x, dtype=float).ravel()
        yi = np.asarray(out.y, dtype=float).ravel()
        zi = np.asarray(out.z, dtype=float).ravel()
        ii = np.asarray(out.i, dtype=float).ravel()

        finite = np.isfinite(xi) & np.isfinite(yi) & np.isfinite(ii)
        valid = finite & (ii > 0.0)
        if not np.any(valid):
            return Footprint(
                xi, yi, ii, valid, float("nan"), float("nan"), n, 0,
                float(np.nanmedian(zi)) if zi.size else float("nan"),
                Status.ALL_RAYS_BLOCKED, "every launched ray was blocked or invalid",
            )

        chief_idx = int(np.flatnonzero(is_chief & valid)[0]) if np.any(is_chief & valid) else -1
        chief_x = float(xi[chief_idx]) if chief_idx >= 0 else float("nan")
        chief_y = float(yi[chief_idx]) if chief_idx >= 0 else float("nan")

        if not keep_cache:
            self._optic_cache.clear()

        return Footprint(
            x_mm=xi, y_mm=yi, intensity=ii, valid=valid,
            chief_x_mm=chief_x, chief_y_mm=chief_y,
            n_launched=n, n_valid=int(valid.sum()),
            z_image_mm=float(np.nanmedian(zi[valid])),
            status=Status.OK, message="ok",
        )

    # ------------------------------------------------------------------
    def clear_cache(self) -> None:
        self._optic_cache.clear()


def trace_summary(footprint: Footprint, pixel_size_mm: float, cx_px: float,
                  cy_px: float) -> dict[str, Any]:
    """Reduce a footprint to scalar diagnostics used by the gate checks.

    Axis contract
    -------------
    The object height ``X_L`` is launched along the Optiland ``y`` axis, so the
    real image height ``y'`` is the quantity that maps to the sensor *column*.
    A real lens inverts the image, while the L0 contract places its virtual
    image plane in front of the pinhole without a flip, hence::

        u = cx - y'/p        v = cy + x'/p

    ``v`` stays at ``cy`` for the coplanar case because the object has no
    out-of-plane component.
    """

    cx_mm, cy_mm = footprint.centroid_mm
    sxx, syy, sxy = footprint.second_moments_mm
    px, py = footprint.peak_to_valley_mm()
    return {
        "n_launched": footprint.n_launched,
        "n_valid": footprint.n_valid,
        "ray_success_fraction": footprint.ray_success_fraction,
        "chief_u_px": cx_px - footprint.chief_y_mm / pixel_size_mm,
        "chief_v_px": cy_px + footprint.chief_x_mm / pixel_size_mm,
        "centroid_u_px": cx_px - cy_mm / pixel_size_mm,
        "centroid_v_px": cy_px + cx_mm / pixel_size_mm,
        "rms_radius_mm": float(np.sqrt(max(sxx + syy, 0.0))),
        "sigma_u_mm": float(np.sqrt(max(syy, 0.0))),
        "sigma_v_mm": float(np.sqrt(max(sxx, 0.0))),
        "cov_uv_mm2": sxy,
        "peak_to_valley_u_mm": py,
        "peak_to_valley_v_mm": px,
        "chief_u_centroid_offset_px": float(
            (cx_px - footprint.chief_y_mm / pixel_size_mm)
            - (cx_px - cy_mm / pixel_size_mm)
        ),
        "status": footprint.status.value,
    }
