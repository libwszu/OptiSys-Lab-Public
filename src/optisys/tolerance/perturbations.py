"""Assembly-level perturbations and their physical mapping.

Two random layers are kept strictly separate:

* ``assembly_id``  - one set of ``ΔB, Δθ, Δf/f, Δcx, Δz_focus`` per virtual unit,
  shared by every scene and repeat of that unit.
* ``frame_id``     - independent noise per exposure.

Conflating the two would understate the tail and is forbidden by
``docs/g2/G2_PRE_REGISTRATION.md`` section 8.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from optisys.config_g2 import ResolvedG2Config, ToleranceSpec
from optisys.optics.optiland_adapter import SingletModel


@dataclass(frozen=True)
class AssemblyPerturbation:
    """One virtual unit's fabrication/assembly offsets, in internal units."""

    assembly_id: str
    d_baseline_mm: float = 0.0
    d_theta_rad: float = 0.0
    d_focal_relative: float = 0.0
    d_cx_px: float = 0.0
    d_focus_mm: float = 0.0

    @property
    def is_nominal(self) -> bool:
        return (
            self.d_baseline_mm == 0.0
            and self.d_theta_rad == 0.0
            and self.d_focal_relative == 0.0
            and self.d_cx_px == 0.0
            and self.d_focus_mm == 0.0
        )

    def as_row(self) -> dict[str, Any]:
        return {
            "assembly_id": self.assembly_id,
            "d_baseline_mm": self.d_baseline_mm,
            "d_theta_rad": self.d_theta_rad,
            "d_theta_deg": float(np.rad2deg(self.d_theta_rad)),
            "d_focal_relative": self.d_focal_relative,
            "d_cx_px": self.d_cx_px,
            "d_focus_mm": self.d_focus_mm,
        }

    def signature(self) -> str:
        payload = "|".join(
            f"{value:.15g}"
            for value in (
                self.d_baseline_mm, self.d_theta_rad, self.d_focal_relative,
                self.d_cx_px, self.d_focus_mm,
            )
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class AssemblyState:
    """Resolved physical parameters of one virtual unit."""

    assembly_id: str
    perturbation: AssemblyPerturbation
    baseline_mm: float
    theta_rad: float
    focal_length_mm: float
    cx_px: float
    focus_mm: float
    aperture_mm: float
    sensor_offset_mm: float = 0.0
    notes: tuple[str, ...] = field(default_factory=tuple)

    def object_height_mm(self, distance_mm: float) -> float:
        return float(self.baseline_mm - distance_mm * np.tan(self.theta_rad))

    def lens(self, config: ResolvedG2Config) -> SingletModel:
        return SingletModel(
            focal_length_mm=self.focal_length_mm,
            aperture_mm=self.aperture_mm,
            thickness_mm=config.optics.element_thickness_mm,
            material=config.optics.material,
            index=config.optics.design_index,
            wavelength_nm=config.wavelength_nm,
            rear_aperture_clearance_mm=config.optics.rear_aperture_clearance_mm,
            focus_distance_mm=self.focus_mm,
            pupil_side=config.optics.pupil_side,
            sensor_offset_mm=self.sensor_offset_mm,
        )

    def describe(self) -> dict[str, Any]:
        return {
            "assembly_id": self.assembly_id,
            "baseline_mm": self.baseline_mm,
            "theta_rad": self.theta_rad,
            "theta_deg": float(np.rad2deg(self.theta_rad)),
            "focal_length_mm": self.focal_length_mm,
            "cx_px": self.cx_px,
            "focus_mm": self.focus_mm,
            "sensor_offset_mm": self.sensor_offset_mm,
            "aperture_mm": self.aperture_mm,
            "perturbation": self.perturbation.as_row(),
            "notes": list(self.notes),
        }


def perturbation_sigmas(tolerance: ToleranceSpec) -> dict[str, float]:
    """Standard deviations in internal units (mm, rad, dimensionless, px)."""

    out: dict[str, float] = {}
    for variable in tolerance.variables:
        if variable.name == "baseline_mm":
            out["d_baseline_mm"] = variable.sigma
        elif variable.name == "theta_deg":
            out["d_theta_rad"] = float(np.deg2rad(variable.sigma))
        elif variable.name == "focal_relative":
            out["d_focal_relative"] = variable.sigma
        elif variable.name == "cx_px":
            out["d_cx_px"] = variable.sigma
        elif variable.name == "focus_mm":
            out["d_focus_mm"] = variable.sigma
    return out


def make_assembly(perturbation: AssemblyPerturbation,
                  config: ResolvedG2Config) -> AssemblyState:
    """Map a perturbation vector onto the physical design.

    ``Δf/f`` is relative, so the design focal length is the base value; the
    focal-length *and* the derived radii change together, because the radius
    solver runs on the perturbed focal length.
    """

    notes = []
    f0 = config.focal_length_mm
    f = f0 * (1.0 + perturbation.d_focal_relative)
    if f <= config.focal_length_mm * 0.5 or f >= config.focal_length_mm * 1.5:
        notes.append("focal_length_out_of_plausible_range")
    return AssemblyState(
        assembly_id=perturbation.assembly_id,
        perturbation=perturbation,
        baseline_mm=config.baseline_mm + perturbation.d_baseline_mm,
        theta_rad=config.theta_rad + perturbation.d_theta_rad,
        focal_length_mm=f,
        cx_px=config.cx_px + perturbation.d_cx_px,
        focus_mm=config.optics.focus_distance_mm,
        sensor_offset_mm=perturbation.d_focus_mm,
        aperture_mm=config.optics.aperture_diameter_mm,
        notes=tuple(notes),
    )


def make_design_assembly(perturbation: AssemblyPerturbation,
                          config: ResolvedG2Config, *,
                          baseline_mm: float,
                          theta_rad: float,
                          focal_length_mm: float) -> AssemblyState:
    """Apply one perturbation vector to a **candidate design**, not to the baseline.

    This distinction is essential for a fair comparison: every candidate must
    see the same random offsets applied to *its own* nominal geometry.
    Applying the offsets to the baseline design and then evaluating a different
    candidate silently measures a mismatched instrument.
    """

    f = float(focal_length_mm) * (1.0 + perturbation.d_focal_relative)
    notes = []
    if f <= 0 or not np.isfinite(f):
        notes.append("nonphysical_focal_length")
    return AssemblyState(
        assembly_id=perturbation.assembly_id,
        perturbation=perturbation,
        baseline_mm=float(baseline_mm) + perturbation.d_baseline_mm,
        theta_rad=float(theta_rad) + perturbation.d_theta_rad,
        focal_length_mm=f,
        cx_px=config.cx_px + perturbation.d_cx_px,
        focus_mm=config.optics.focus_distance_mm,
        sensor_offset_mm=perturbation.d_focus_mm,
        aperture_mm=config.optics.aperture_diameter_mm,
        notes=tuple(notes),
    )


NOMINAL_ASSEMBLY_ID = "NOMINAL"
