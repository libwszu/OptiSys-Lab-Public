"""Optiland 0.6.3 adapter for a centered two-singlet 976 nm pump train.

This backend is intentionally scoped to centered spherical singlets and
geometric aperture losses. It does not model coating/Fresnel losses, coatings,
scatter, diffraction, coherence, or tilted/decentered coordinate breaks.
"""

from __future__ import annotations

import importlib.metadata
import warnings
from dataclasses import dataclass
from typing import Any

import numpy as np

from optisys.optics.pump_beamline import BeamlineConfig
from optisys.sources.multimode_fiber import RayBundle


@dataclass
class OptilandPumpResult:
    x_mm: np.ndarray
    y_mm: np.ndarray
    weight_out: np.ndarray
    valid: np.ndarray
    n_launched: int
    n_valid: int
    backend_version: str
    lens_models: list[dict[str, Any]]
    status: str
    blocked_at: np.ndarray
    ledger: dict[str, float]
    message: str = ""


def sellmeier_n_bk7(wavelength_nm: float) -> float:
    """SCHOTT N-BK7 Sellmeier index; wavelength is vacuum nm.

    The installed Optiland 0.6.3 catalog records the N-BK7 formula over
    0.3--2.5 um. Keep the local adapter inside that declared range.
    """

    if not np.isfinite(wavelength_nm) or not 300.0 <= wavelength_nm <= 2500.0:
        raise ValueError("N-BK7 wavelength must be within the verified 300-2500 nm range")
    lam_um2 = (float(wavelength_nm) / 1000.0) ** 2
    b = (1.03961212, 0.231792344, 1.01046945)
    c = (0.00600069867, 0.0200179144, 103.560653)
    n2 = 1.0 + sum(bi * lam_um2 / (lam_um2 - ci) for bi, ci in zip(b, c))
    return float(np.sqrt(n2))


class OptilandPumpTracer:
    """Run arbitrary weighted source rays through two sequential singlets."""

    EXPECTED_VERSION = "0.6.3"

    def __init__(self, beamline: BeamlineConfig, *, wavelength_nm: float,
                 lens_thickness_mm: float = 2.0, material: str = "N-BK7") -> None:
        beamline.validate()
        self.beamline = beamline
        self.wavelength_nm = float(wavelength_nm)
        self.lens_thickness_mm = float(lens_thickness_mm)
        self.material = str(material)
        if self.material != "N-BK7":
            raise ValueError(
                f"MATERIAL_NOT_VERIFIED: {self.material!r}; the current geometry and "
                "Sellmeier inputs are registered only for N-BK7"
            )
        if self.wavelength_nm <= 0.0 or self.lens_thickness_mm <= 0.0:
            raise ValueError("wavelength and lens thickness must be positive")
        self.index_976 = sellmeier_n_bk7(self.wavelength_nm)
        try:
            self.backend_version = importlib.metadata.version("optiland")
        except importlib.metadata.PackageNotFoundError:
            self.backend_version = "NOT_INSTALLED"
        self.lens_models = self._lens_models()

    def _lens_models(self) -> list[dict[str, Any]]:
        from optisys.optics.reference_thin_lens import ThinLensReference

        values = []
        for name, lens in (("L1", self.beamline.l1), ("L2", self.beamline.l2)):
            reference = ThinLensReference(
                focal_length_mm=lens.focal_length_mm,
                aperture_mm=lens.aperture_diameter_mm,
                thickness_mm=self.lens_thickness_mm,
                index=self.index_976,
            )
            front_vertex_z = lens.z_mm - reference.front_principal_offset_mm
            values.append({
                "name": name,
                "focal_length_mm": lens.focal_length_mm,
                "aperture_diameter_mm": lens.aperture_diameter_mm,
                "thickness_mm": self.lens_thickness_mm,
                "material": self.material,
                "index_sellmeier_976": self.index_976,
                "radius_1_mm": reference.radius_mm,
                "radius_2_mm": -reference.radius_mm,
                "front_vertex_z_mm": front_vertex_z,
                "rear_vertex_z_mm": front_vertex_z + self.lens_thickness_mm,
                "matrix_efl_mm": reference.efl_mm,
                "matrix_bfl_mm": reference.bfl_mm,
                "front_principal_offset_mm": reference.front_principal_offset_mm,
                "rear_principal_offset_mm": reference.rear_principal_offset_mm,
                "geometry_status": "ASSUMED_equiconvex_singlet_no_vendor_part",
            })
        if values[1]["front_vertex_z_mm"] <= values[0]["rear_vertex_z_mm"]:
            raise ValueError("P1 lens surfaces overlap or have invalid order")
        if self.beamline.target_z_mm <= values[1]["rear_vertex_z_mm"]:
            raise ValueError("P1 target plane must be downstream of L2 rear vertex")
        return values

    def _build_optiland(self):
        import optiland.backend as backend

        backend.set_backend("numpy")
        from optiland.optic import Optic
        from optiland.physical_apertures import RadialAperture

        b = self.beamline
        m1, m2 = self.lens_models
        gap = m2["front_vertex_z_mm"] - m1["rear_vertex_z_mm"]
        detector_gap = b.target_z_mm - m2["rear_vertex_z_mm"]
        if gap <= 0.0 or detector_gap <= 0.0:
            raise ValueError("non-positive sequential surface thickness")

        optic = Optic(name="OptiSys_G4_976nm_two_singlets")
        optic.set_aperture("EPD", max(b.l1.aperture_diameter_mm, b.l2.aperture_diameter_mm))
        optic.wavelengths.add(self.wavelength_nm / 1000.0, is_primary=True)
        optic.fields.set_type("object_height")
        optic.fields.add(y=0.0)
        # The source array starts on the z=0 object plane. Each surface thickness
        # advances to the next vertex; explicit apertures are installed on both
        # faces of each lens.
        optic.surfaces.add(index=0, radius=np.inf,
                           thickness=m1["front_vertex_z_mm"], material="air",
                           comment="fiber source plane")
        optic.surfaces.add(index=1, radius=m1["radius_1_mm"],
                           thickness=self.lens_thickness_mm, material=self.material,
                           comment="L1 front")
        optic.surfaces.surfaces[1].aperture = RadialAperture(b.l1.aperture_diameter_mm / 2.0)
        optic.surfaces.add(index=2, radius=m1["radius_2_mm"], thickness=gap,
                           material="air", comment="L1 rear / free-space gap")
        optic.surfaces.surfaces[2].aperture = RadialAperture(b.l1.aperture_diameter_mm / 2.0)
        optic.surfaces.add(index=3, radius=m2["radius_1_mm"],
                           thickness=self.lens_thickness_mm, material=self.material,
                           comment="L2 front")
        optic.surfaces.surfaces[3].aperture = RadialAperture(b.l2.aperture_diameter_mm / 2.0)
        optic.surfaces.add(index=4, radius=m2["radius_2_mm"], thickness=detector_gap,
                           material="air", comment="L2 rear / target distance")
        optic.surfaces.surfaces[4].aperture = RadialAperture(b.l2.aperture_diameter_mm / 2.0)
        optic.surfaces.add(index=5, radius=np.inf, thickness=0.0,
                           material="air", comment="target plane")
        return optic

    def trace(self, bundle: RayBundle) -> OptilandPumpResult:
        if self.backend_version != self.EXPECTED_VERSION:
            total = bundle.total_weight
            return OptilandPumpResult(
                np.full(bundle.n_rays, np.nan), np.full(bundle.n_rays, np.nan),
                np.zeros(bundle.n_rays), np.zeros(bundle.n_rays, dtype=bool),
                bundle.n_rays, 0, self.backend_version, self.lens_models,
                "MODEL_UNAVAILABLE", np.full(bundle.n_rays, "", dtype=object),
                {"source_weight_total": total, "transmitted_weight": None,
                 "l1_blocked_weight": None, "l2_blocked_weight": None,
                 "outside_target_weight": None, "trace_failed_weight": None,
                 "no_intersection_weight": None,
                 "aperture_blocked_weight": None, "lost_or_invalid_weight": None,
                 "balance_residual": None},
                f"expected Optiland {self.EXPECTED_VERSION}")
        try:
            from optiland.rays import RealRays

            optic = self._build_optiland()
            o = np.asarray(bundle.origin_mm, dtype=float)
            d = np.asarray(bundle.direction, dtype=float)
            # Optiland uses the first lens front vertex as its local z=0; the
            # object surface is located at -source_to_lens. Translate the
            # global source plane into that frame before tracing.
            z_origin = float(self.lens_models[0]["front_vertex_z_mm"])
            rays = RealRays(
                o[:, 0], o[:, 1], o[:, 2] - z_origin, d[:, 0], d[:, 1], d[:, 2],
                intensity=np.asarray(bundle.weight, dtype=float),
                wavelength=np.full(bundle.n_rays, self.wavelength_nm / 1000.0),
            )
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
            out = optic.surfaces.trace(rays, record=True)
            x = np.asarray(out.x, dtype=float).ravel()
            y = np.asarray(out.y, dtype=float).ravel()
            intensity = np.asarray(out.i, dtype=float).ravel()
            if x.size != bundle.n_rays or y.size != bundle.n_rays or intensity.size != bundle.n_rays:
                raise RuntimeError("Optiland returned a different ray count")
            history = np.asarray(optic.surfaces.intensity, dtype=float)
            if history.ndim != 2 or history.shape[1] != bundle.n_rays or history.shape[0] < 6:
                raise RuntimeError(f"unexpected Optiland intensity history shape {history.shape}")
            finite = np.isfinite(x) & np.isfinite(y) & np.isfinite(intensity)
            final_alive = finite & (intensity > 0.0)
            blocked_at = np.full(bundle.n_rays, "", dtype=object)
            # Locate first zero intensity after each physical aperture surface.
            l1_block = np.any(history[1:3] <= 0.0, axis=0) & (history[0] > 0.0)
            l2_block = np.any(history[3:5] <= 0.0, axis=0) & (history[2] > 0.0)
            blocked_at[l1_block] = "L1"
            blocked_at[l2_block] = "L2"
            trace_failed = ~finite
            blocked_at[trace_failed] = "TRACE"
            outside = final_alive & (x * x + y * y > self.beamline.target_radius_mm ** 2 + 1e-12)
            blocked_at[outside] = "TARGET"
            valid = final_alive & ~outside
            w = np.asarray(bundle.weight, dtype=float)
            total = float(np.sum(w, dtype=np.float64))
            l1w = float(np.sum(w[l1_block], dtype=np.float64))
            l2w = float(np.sum(w[l2_block & ~l1_block], dtype=np.float64))
            outw = float(np.sum(w[outside], dtype=np.float64))
            failw = float(np.sum(w[trace_failed], dtype=np.float64))
            txw = float(np.sum(w[valid], dtype=np.float64))
            ledger = {
                "source_weight_total": total,
                "transmitted_weight": txw,
                "l1_blocked_weight": l1w,
                "l2_blocked_weight": l2w,
                "outside_target_weight": outw,
                "no_intersection_weight": 0.0,
                "trace_failed_weight": failw,
                "aperture_blocked_weight": l1w + l2w,
                "lost_or_invalid_weight": l1w + l2w + outw + failw,
                "balance_residual": total - txw - l1w - l2w - outw - failw,
            }
            return OptilandPumpResult(
                x, y, w * valid, valid, bundle.n_rays, int(np.count_nonzero(valid)),
                self.backend_version, self.lens_models,
                "OK" if np.any(valid) else "TRACE_FAILED", blocked_at, ledger,
                "surviving-ray weights are geometric; no Fresnel/coating loss",
            )
        except Exception as exc:  # engine failures stay visible in the result
            return OptilandPumpResult(
                np.full(bundle.n_rays, np.nan), np.full(bundle.n_rays, np.nan),
                np.zeros(bundle.n_rays), np.zeros(bundle.n_rays, dtype=bool),
                bundle.n_rays, 0, self.backend_version, self.lens_models,
                "TRACE_FAILED", np.full(bundle.n_rays, "TRACE", dtype=object), {},
                f"{type(exc).__name__}: {exc}",
            )
