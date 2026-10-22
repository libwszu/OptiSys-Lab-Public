"""P0 vectorized thin-lens ray model for a two-lens pump beamline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

from optisys.sources.multimode_fiber import RayBundle

RAY_STATES = {
    "OK", "INVALID_SOURCE", "INVALID_GEOMETRY", "NO_INTERSECTION",
    "VIGNETTED", "APERTURE_BLOCKED", "TRACE_FAILED", "OUTSIDE_TARGET",
    "NONFINITE", "INSUFFICIENT_RAY_STATISTICS", "MODEL_UNAVAILABLE",
}


@dataclass(frozen=True)
class ThinLensPlane:
    focal_length_mm: float
    z_mm: float
    aperture_diameter_mm: float
    decenter_x_mm: float = 0.0
    decenter_y_mm: float = 0.0
    tilt_x_rad: float = 0.0
    tilt_y_rad: float = 0.0

    def validate(self) -> None:
        values = (self.focal_length_mm, self.z_mm, self.aperture_diameter_mm,
                  self.decenter_x_mm, self.decenter_y_mm, self.tilt_x_rad, self.tilt_y_rad)
        if not all(np.isfinite(v) for v in values):
            raise ValueError("lens geometry must be finite")
        if self.focal_length_mm <= 0.0 or self.aperture_diameter_mm <= 0.0:
            raise ValueError("lens focal length and aperture diameter must be positive")


@dataclass(frozen=True)
class BeamlineConfig:
    l1: ThinLensPlane
    l2: ThinLensPlane
    target_z_mm: float
    target_radius_mm: float
    lens_clearance_mm: float = 0.0

    def validate(self) -> None:
        self.l1.validate()
        self.l2.validate()
        if not np.isfinite(self.target_z_mm) or not np.isfinite(self.target_radius_mm):
            raise ValueError("target geometry must be finite")
        if self.target_radius_mm <= 0.0:
            raise ValueError("target radius must be positive")
        if self.l2.z_mm <= self.l1.z_mm + self.lens_clearance_mm:
            raise ValueError("lens order invalid or lenses overlap")
        if self.target_z_mm <= self.l2.z_mm:
            raise ValueError("target plane must be downstream of L2")


@dataclass
class BeamlineTrace:
    ray_id: np.ndarray
    weight: np.ndarray
    status: np.ndarray
    blocked_at: np.ndarray
    l1_x_mm: np.ndarray
    l1_y_mm: np.ndarray
    l2_x_mm: np.ndarray
    l2_y_mm: np.ndarray
    target_x_mm: np.ndarray
    target_y_mm: np.ndarray
    target_z_mm: np.ndarray
    direction_out: np.ndarray
    ledger: dict[str, float]
    metadata: dict[str, Any] = field(default_factory=dict)


def _rotation_basis(tilt_x: float, tilt_y: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    cx, sx = np.cos(tilt_x), np.sin(tilt_x)
    cy, sy = np.cos(tilt_y), np.sin(tilt_y)
    rx = np.array([[1.0, 0.0, 0.0], [0.0, cx, -sx], [0.0, sx, cx]])
    ry = np.array([[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]])
    rot = ry @ rx
    return rot[:, 0], rot[:, 1], rot[:, 2]


def _trace_lens(
    position: np.ndarray,
    direction: np.ndarray,
    alive: np.ndarray,
    lens: ThinLensPlane,
    lens_name: str,
    status: np.ndarray,
    blocked_at: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    ex, ey, normal = _rotation_basis(lens.tilt_x_rad, lens.tilt_y_rad)
    center = np.array([lens.decenter_x_mm, lens.decenter_y_mm, lens.z_mm])
    denom = direction @ normal
    eligible = alive.copy()
    parallel = eligible & (np.abs(denom) <= 1e-14)
    status[parallel] = "NO_INTERSECTION"
    blocked_at[parallel] = lens_name
    eligible[parallel] = False
    distance = np.zeros(len(alive), dtype=float)
    distance[eligible] = ((center - position[eligible]) @ normal) / denom[eligible]
    behind = eligible & (distance < -1e-12)
    status[behind] = "NO_INTERSECTION"
    blocked_at[behind] = lens_name
    eligible[behind] = False
    hit = position.copy()
    hit[eligible] += distance[eligible, None] * direction[eligible]
    local = hit - center
    lx = local @ ex
    ly = local @ ey
    aperture = lens.aperture_diameter_mm / 2.0
    clipped = eligible & (lx * lx + ly * ly > aperture * aperture + 1e-12)
    status[clipped] = "APERTURE_BLOCKED"
    blocked_at[clipped] = lens_name
    passed = eligible & ~clipped
    dz_local = direction @ normal
    bad = passed & (~np.isfinite(dz_local) | (dz_local <= 1e-14))
    status[bad] = "TRACE_FAILED"
    blocked_at[bad] = lens_name
    passed[bad] = False

    if np.any(passed):
        ux = (direction[passed] @ ex) / dz_local[passed] - lx[passed] / lens.focal_length_mm
        uy = (direction[passed] @ ey) / dz_local[passed] - ly[passed] / lens.focal_length_mm
        out = ux[:, None] * ex + uy[:, None] * ey + normal
        out /= np.linalg.norm(out, axis=1)[:, None]
        direction[passed] = out
        position[passed] = hit[passed]
    return position, direction, passed, np.column_stack((lx, ly))


def trace_thin_lens(bundle: RayBundle, config: BeamlineConfig) -> BeamlineTrace:
    """Trace all rays; unsuccessful weights remain in the original denominator."""

    config.validate()
    if bundle.n_rays == 0 or bundle.total_weight <= 0.0:
        raise ValueError("source bundle must contain positive total weight")
    position = np.asarray(bundle.origin_mm, dtype=float).copy()
    direction = np.asarray(bundle.direction, dtype=float).copy()
    n = bundle.n_rays
    status = np.full(n, "OK", dtype=object)
    blocked_at = np.full(n, "", dtype=object)
    alive = np.ones(n, dtype=bool)
    bad_source = (~np.all(np.isfinite(position), axis=1)
                  | ~np.all(np.isfinite(direction), axis=1)
                  | (direction[:, 2] <= 0.0))
    status[bad_source] = "INVALID_SOURCE"
    alive[bad_source] = False

    position, direction, alive, p1 = _trace_lens(
        position, direction, alive, config.l1, "L1", status, blocked_at)
    l1_x, l1_y = p1[:, 0], p1[:, 1]
    position, direction, alive, p2 = _trace_lens(
        position, direction, alive, config.l2, "L2", status, blocked_at)
    l2_x, l2_y = p2[:, 0], p2[:, 1]

    target_x = np.full(n, np.nan, dtype=float)
    target_y = np.full(n, np.nan, dtype=float)
    target_z = np.full(n, config.target_z_mm, dtype=float)
    parallel = alive & (np.abs(direction[:, 2]) <= 1e-14)
    status[parallel] = "NO_INTERSECTION"
    blocked_at[parallel] = "TARGET"
    alive[parallel] = False
    t = np.zeros(n, dtype=float)
    t[alive] = (config.target_z_mm - position[alive, 2]) / direction[alive, 2]
    behind = alive & (t < -1e-12)
    status[behind] = "NO_INTERSECTION"
    blocked_at[behind] = "TARGET"
    alive[behind] = False
    target_x[alive] = position[alive, 0] + t[alive] * direction[alive, 0]
    target_y[alive] = position[alive, 1] + t[alive] * direction[alive, 1]
    nonfinite = alive & (~np.isfinite(target_x) | ~np.isfinite(target_y))
    status[nonfinite] = "NONFINITE"
    blocked_at[nonfinite] = "TARGET"
    alive[nonfinite] = False
    outside = alive & (target_x * target_x + target_y * target_y > config.target_radius_mm**2 + 1e-12)
    status[outside] = "OUTSIDE_TARGET"
    blocked_at[outside] = "TARGET"
    status[alive & ~outside] = "OK"

    w = np.asarray(bundle.weight, dtype=float)
    masks = {
        "transmitted_weight": status == "OK",
        "outside_target_weight": status == "OUTSIDE_TARGET",
        "l1_blocked_weight": (status == "APERTURE_BLOCKED") & (blocked_at == "L1"),
        "l2_blocked_weight": (status == "APERTURE_BLOCKED") & (blocked_at == "L2"),
        "no_intersection_weight": status == "NO_INTERSECTION",
        "trace_failed_weight": np.isin(status, ["TRACE_FAILED", "NONFINITE", "INVALID_SOURCE"]),
    }
    ledger = {name: float(np.sum(w[mask], dtype=np.float64)) for name, mask in masks.items()}
    ledger["source_weight_total"] = bundle.total_weight
    ledger["aperture_blocked_weight"] = ledger["l1_blocked_weight"] + ledger["l2_blocked_weight"]
    ledger["lost_or_invalid_weight"] = (ledger["outside_target_weight"]
                                        + ledger["no_intersection_weight"]
                                        + ledger["trace_failed_weight"])
    ledger["balance_residual"] = ledger["source_weight_total"] - sum(
        ledger[k] for k in ("transmitted_weight", "outside_target_weight",
                            "l1_blocked_weight", "l2_blocked_weight",
                            "no_intersection_weight", "trace_failed_weight"))
    return BeamlineTrace(
        ray_id=np.asarray(bundle.ray_id).copy(), weight=w.copy(), status=status,
        blocked_at=blocked_at, l1_x_mm=l1_x, l1_y_mm=l1_y,
        l2_x_mm=l2_x, l2_y_mm=l2_y, target_x_mm=target_x,
        target_y_mm=target_y, target_z_mm=target_z, direction_out=direction,
        ledger=ledger,
        metadata={"model_level": "P0_ANALYTIC", "evidence": "SIMULATED",
                  "target_radius_mm": float(config.target_radius_mm),
                  "units": {"position": "mm", "direction": "unitless", "angle": "rad"},
                  "transmission_name": "geometric_transmission_fraction",
                  "normalization": "total source weight; no survivor renormalization"},
    )


def trace_thin_lens_scalar_reference(bundle: RayBundle, config: BeamlineConfig) -> dict[str, np.ndarray]:
    """Independent scalar ABCD-style reference for aligned, untilted lenses."""

    if abs(config.l1.tilt_x_rad) + abs(config.l1.tilt_y_rad) + abs(config.l2.tilt_x_rad) + abs(config.l2.tilt_y_rad) > 0:
        raise ValueError("scalar reference is registered only for untilted lens planes")
    config.validate()
    n = bundle.n_rays
    tx = np.full(n, np.nan)
    ty = np.full(n, np.nan)
    out_direction = np.full((n, 3), np.nan)
    states = np.full(n, "OK", dtype=object)
    blocked = np.full(n, "", dtype=object)
    for i in range(n):
        x, y, z = bundle.origin_mm[i]
        dx, dy, dz = bundle.direction[i]
        if not np.all(np.isfinite((x, y, z, dx, dy, dz))) or dz <= 0:
            states[i] = "INVALID_SOURCE"
            continue
        for lens, label in ((config.l1, "L1"), (config.l2, "L2")):
            distance = (lens.z_mm - z) / dz
            if distance < -1e-12:
                states[i], blocked[i] = "NO_INTERSECTION", label
                break
            x += distance * dx
            y += distance * dy
            z = lens.z_mm
            xloc, yloc = x - lens.decenter_x_mm, y - lens.decenter_y_mm
            if xloc * xloc + yloc * yloc > (lens.aperture_diameter_mm / 2.0) ** 2 + 1e-12:
                states[i], blocked[i] = "APERTURE_BLOCKED", label
                break
            ux = dx / dz - xloc / lens.focal_length_mm
            uy = dy / dz - yloc / lens.focal_length_mm
            norm = np.sqrt(ux * ux + uy * uy + 1.0)
            dx, dy, dz = ux / norm, uy / norm, 1.0 / norm
        else:
            distance = (config.target_z_mm - z) / dz
            if distance < -1e-12:
                states[i], blocked[i] = "NO_INTERSECTION", "TARGET"
                continue
            tx[i], ty[i] = x + distance * dx, y + distance * dy
            out_direction[i] = (dx, dy, dz)
            if tx[i] * tx[i] + ty[i] * ty[i] > config.target_radius_mm**2 + 1e-12:
                states[i], blocked[i] = "OUTSIDE_TARGET", "TARGET"
    return {"target_x_mm": tx, "target_y_mm": ty, "target_direction": out_direction,
            "status": states, "blocked_at": blocked}
