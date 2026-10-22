"""S6 rigid-body P1 tracing with independent local- and world-sphere paths.

The two paths share only the registered prescription, rigid pose definition,
aperture/target contract, and terminal ledger.  They do not share a surface
intersection or refraction result: ``local`` solves spheres in each lens frame
and refracts there, while ``world`` solves transformed spheres in world space
and refracts with a separately implemented Snell calculation.

All prescription dimensions remain ASSUMED.  In particular, the 12 mm clear
aperture is not a verified mechanical lens diameter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Literal, Sequence

import numpy as np

from optisys.optics.s5_reference import (
    Singlet,
    SphericalModel,
    n_bk7_sellmeier,
    spherical_sag_mm,
)

Route = Literal["local", "world"]
_EPS_T = 1.0e-12


class S6GeometryError(ValueError):
    """The assumed S6 geometry or ray input is not physically defined."""


@dataclass(frozen=True)
class LensPose:
    """Rigid-body perturbation relative to the lens front-vertex pivot.

    Rotations are active extrinsic XYZ: ``Rz @ Ry @ Rx``.  Translation is
    applied to the nominal front vertex before local coordinates are rotated.
    """

    dx_mm: float = 0.0
    dy_mm: float = 0.0
    dz_mm: float = 0.0
    tilt_x_deg: float = 0.0
    tilt_y_deg: float = 0.0
    roll_z_deg: float = 0.0

    def values(self) -> tuple[float, ...]:
        return (self.dx_mm, self.dy_mm, self.dz_mm, self.tilt_x_deg,
                self.tilt_y_deg, self.roll_z_deg)


@dataclass(frozen=True)
class TraceResult:
    route: Route
    surface_rows: list[dict[str, Any]]
    ray_rows: list[dict[str, Any]]
    ledger: dict[str, Any]


@dataclass(frozen=True)
class ReferenceComparison:
    surface_count: int
    terminal_mismatch_count: int
    hit_mismatch_count: int
    max_incoming_point_delta_mm: float
    max_incoming_direction_delta: float
    max_hit_delta_mm: float
    max_normal_delta: float
    max_direction_delta: float
    max_target_delta_mm: float
    status: str


@dataclass(frozen=True)
class _Surface:
    surface_id: str
    lens_index: int
    vertex_z_local_mm: float
    radius_signed_mm: float
    semi_aperture_mm: float
    n_before: float
    n_after: float

    @property
    def center_local(self) -> np.ndarray:
        return np.array([0.0, 0.0, self.vertex_z_local_mm + self.radius_signed_mm])


def rotation_matrix(pose: LensPose) -> np.ndarray:
    """Return the declared active extrinsic XYZ rotation matrix."""
    if not all(np.isfinite(v) for v in pose.values()):
        raise S6GeometryError("pose contains non-finite values")
    ax, ay, az = np.deg2rad([pose.tilt_x_deg, pose.tilt_y_deg, pose.roll_z_deg])
    sx, cx = np.sin(ax), np.cos(ax)
    sy, cy = np.sin(ay), np.cos(ay)
    sz, cz = np.sin(az), np.cos(az)
    rx = np.array([[1.0, 0.0, 0.0], [0.0, cx, -sx], [0.0, sx, cx]])
    ry = np.array([[cy, 0.0, sy], [0.0, 1.0, 0.0], [-sy, 0.0, cy]])
    rz = np.array([[cz, -sz, 0.0], [sz, cz, 0.0], [0.0, 0.0, 1.0]])
    return rz @ ry @ rx


def lens_pose_transform(lens: Singlet, pose: LensPose) -> tuple[np.ndarray, np.ndarray]:
    """Return ``(R,t)`` for the front-vertex pivot and declared pose."""
    r = rotation_matrix(pose)
    t = np.array([pose.dx_mm, pose.dy_mm,
                  lens.front_vertex_z_mm + pose.dz_mm], dtype=float)
    return r, t


def _prescription_surfaces(model: SphericalModel) -> tuple[_Surface, ...]:
    if model.material_id != "N-BK7" or not np.isfinite(model.refractive_index):
        raise S6GeometryError("MATERIAL_NOT_VERIFIED: S6 assumes N-BK7 only")
    if model.refractive_index <= 1.0:
        raise S6GeometryError("invalid glass refractive index")
    if (len(model.lenses) != 2 or abs(model.wavelength_nm - 976.0) > 1e-12
            or not np.isclose(model.refractive_index, n_bk7_sellmeier(976.0),
                              rtol=0.0, atol=1e-12)):
        raise S6GeometryError("MATERIAL_NOT_VERIFIED: model differs from assumed 976 nm N-BK7")
    out: list[_Surface] = []
    for li, lens in enumerate(model.lenses):
        if lens.material_id != "N-BK7":
            raise S6GeometryError(f"MATERIAL_NOT_VERIFIED: {lens.name} material")
        if not (np.isfinite(lens.clear_aperture_mm + lens.center_thickness_mm)
                and lens.clear_aperture_mm > 0.0 and lens.center_thickness_mm > 0.0):
            raise S6GeometryError(f"invalid {lens.name} thickness/aperture")
        if not (lens.radius_front_mm > 0.0 and lens.radius_rear_mm < 0.0):
            raise S6GeometryError(f"invalid {lens.name} signed surface radii")
        semi = lens.clear_aperture_mm / 2.0
        if semi >= min(abs(lens.radius_front_mm), abs(lens.radius_rear_mm)):
            raise S6GeometryError(f"{lens.name} aperture reaches sphere equator")
        edge = (lens.center_thickness_mm
                - spherical_sag_mm(lens.radius_front_mm, semi)
                - spherical_sag_mm(lens.radius_rear_mm, semi))
        if edge <= 0.0:
            raise S6GeometryError(f"{lens.name} has non-positive assumed edge thickness")
        out.extend((
            _Surface(f"{lens.name}_FRONT", li, 0.0, lens.radius_front_mm,
                     semi, 1.0, model.refractive_index),
            _Surface(f"{lens.name}_REAR", li, lens.center_thickness_mm,
                     lens.radius_rear_mm, semi, model.refractive_index, 1.0),
        ))
    return tuple(out)


def _pose_frame(model: SphericalModel, poses: Sequence[LensPose]) -> tuple[list[np.ndarray], list[np.ndarray]]:
    if len(poses) != 2:
        raise S6GeometryError("exactly two lens poses are required")
    rotations: list[np.ndarray] = []
    translations: list[np.ndarray] = []
    for lens, pose in zip(model.lenses, poses, strict=True):
        r, t = lens_pose_transform(lens, pose)
        if (np.max(np.abs(r.T @ r - np.eye(3))) > 1e-12
                or abs(float(np.linalg.det(r)) - 1.0) > 1e-12):
            raise S6GeometryError("rigid rotation is not a proper orthogonal matrix")
        rotations.append(r)
        translations.append(t)
    return rotations, translations


def _lens_z_bounds(lens: Any, pose: LensPose, r: np.ndarray, t: np.ndarray) -> tuple[float, float]:
    """Conservative world-z bounds of both clear-aperture spherical caps."""
    semi = lens.clear_aperture_mm / 2.0
    local_z: list[float] = []
    for vertex, radius in ((0.0, lens.radius_front_mm),
                           (lens.center_thickness_mm, lens.radius_rear_mm)):
        sag = spherical_sag_mm(radius, semi)
        local_z.extend((vertex - sag, vertex + sag))
    z0, z1 = min(local_z), max(local_z)
    radial_world_z = semi * float(np.hypot(r[2, 0], r[2, 1]))
    ends = (t[2] + r[2, 2] * z0, t[2] + r[2, 2] * z1)
    return min(ends) - radial_world_z, max(ends) + radial_world_z


def _segment_distance(a0: np.ndarray, a1: np.ndarray,
                      b0: np.ndarray, b1: np.ndarray) -> float:
    """Shortest distance between two finite 3-D centerline segments."""
    u, v, w = a1 - a0, b1 - b0, a0 - b0
    aa, bb, cc = float(u @ u), float(u @ v), float(v @ v)
    dd, ee = float(u @ w), float(v @ w)
    denom = aa * cc - bb * bb
    if aa <= 1e-24 or cc <= 1e-24:
        raise S6GeometryError("degenerate lens axis")
    if denom <= 1e-24:
        s = 0.0
        t = np.clip(ee / cc, 0.0, 1.0)
    else:
        s = np.clip((bb * ee - cc * dd) / denom, 0.0, 1.0)
        t = np.clip((aa * ee - bb * dd) / denom, 0.0, 1.0)
        # Clamp once more after the first projection to handle an endpoint.
        s = np.clip((bb * t - dd) / aa, 0.0, 1.0)
        t = np.clip((bb * s + ee) / cc, 0.0, 1.0)
    return float(np.linalg.norm((a0 + s * u) - (b0 + t * v)))


def invalid_geometry_reason(
    model: SphericalModel,
    poses: Sequence[LensPose] = (LensPose(), LensPose()),
    *,
    target_z_mm: float | None = None,
) -> str | None:
    """Return a stable reason for invalid assumed geometry, else ``None``.

    The clear-aperture cylinder check is conservative and is not a mechanical
    collision certification because outer lens diameters are unknown.
    """
    try:
        surfaces = _prescription_surfaces(model)
        rotations, translations = _pose_frame(model, poses)
        z_target = model.target_z_mm if target_z_mm is None else float(target_z_mm)
        if not np.isfinite(z_target):
            return "INVALID_TARGET"
        bounds = [_lens_z_bounds(lens, pose, r, t)
                  for lens, pose, r, t in zip(model.lenses, poses, rotations, translations, strict=True)]
        if bounds[1][0] <= bounds[0][1]:
            return "SURFACE_SEQUENCE_OR_INTERSECTION"
        # An enclosing clear-aperture cylinder overlap is a conservative stop.
        a0 = translations[0]
        a1 = a0 + rotations[0] @ np.array([0.0, 0.0, model.lenses[0].center_thickness_mm])
        b0 = translations[1]
        b1 = b0 + rotations[1] @ np.array([0.0, 0.0, model.lenses[1].center_thickness_mm])
        gap = _segment_distance(a0, a1, b0, b1)
        clear_sum = sum(l.clear_aperture_mm / 2.0 for l in model.lenses)
        if gap <= clear_sum:
            return "CLEAR_APERTURE_ENVELOPE_INTERSECTION"
        if z_target <= bounds[1][1]:
            return "TARGET_NOT_DOWNSTREAM"
        if not surfaces:
            return "INVALID_SURFACE_MODEL"
    except (S6GeometryError, ValueError, FloatingPointError):
        return "INVALID_MODEL_OR_POSE"
    return None


def _validate_rays(ray_ids: Iterable[int], origins_mm: np.ndarray,
                   directions: np.ndarray, weights: np.ndarray
                   ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    ids = np.asarray(list(ray_ids), dtype=np.int64)
    origins = np.asarray(origins_mm, dtype=float)
    dirs = np.asarray(directions, dtype=float)
    w = np.asarray(weights, dtype=float)
    if ids.ndim != 1 or ids.size == 0 or len(np.unique(ids)) != ids.size:
        raise S6GeometryError("ray IDs must be non-empty and unique")
    if origins.shape != (ids.size, 3) or dirs.shape != origins.shape or w.shape != (ids.size,):
        raise S6GeometryError("ray arrays have inconsistent shapes")
    if not (np.all(np.isfinite(origins)) and np.all(np.isfinite(dirs))
            and np.all(np.isfinite(w))):
        raise S6GeometryError("ray input contains NaN or infinity")
    if np.any(w <= 0.0) or float(np.sum(w, dtype=np.float64)) <= 0.0:
        raise S6GeometryError("ray weights must be finite and strictly positive")
    norms = np.linalg.norm(dirs, axis=1)
    if np.any(norms <= 0.0) or np.max(np.abs(norms - 1.0)) > 1e-12:
        raise S6GeometryError("ray directions must be normalized")
    return ids, origins, dirs, w


def _intersect_local(origin: np.ndarray, direction: np.ndarray, surface: _Surface
                     ) -> tuple[float | None, np.ndarray | None, float, float]:
    center = surface.center_local
    rel = origin - center
    b = float(rel @ direction)
    c = float(rel @ rel - surface.radius_signed_mm**2)
    disc = b * b - c
    if disc < 0.0:
        return None, None, disc, float("nan")
    root = float(np.sqrt(max(0.0, disc)))
    for distance in sorted((-b - root, -b + root)):
        if distance <= _EPS_T:
            continue
        hit = origin + distance * direction
        # Keep the cap that contains the registered vertex.
        if surface.radius_signed_mm * (hit[2] - center[2]) >= 0.0:
            continue
        residual = abs(float(np.linalg.norm(hit - center)) - abs(surface.radius_signed_mm))
        return float(distance), hit, float(disc), residual
    return None, None, float(disc), float("nan")


def _refract_local(direction: np.ndarray, normal_into_incident: np.ndarray,
                   n1: float, n2: float) -> tuple[np.ndarray | None, float, str]:
    """Local-frame Snell implementation (independent of the world path)."""
    mu = float(direction @ normal_into_incident)
    if mu > 1e-12:
        return None, float("nan"), "WRONG_INTERFACE_SIDE"
    ci = -mu
    ratio = n1 / n2
    k = 1.0 - ratio * ratio * (1.0 - ci * ci)
    if k < -1e-12:
        return None, float(k), "TIR"
    q = ratio * direction + (ratio * ci - np.sqrt(max(k, 0.0))) * normal_into_incident
    norm = float(np.linalg.norm(q))
    if not np.isfinite(norm) or norm <= 0.0:
        return None, float(k), "REFRACTION_FAILURE"
    return q / norm, float(k), "PASS"


def _intersect_world(origin: np.ndarray, direction: np.ndarray, surface: _Surface,
                     rotation: np.ndarray, translation: np.ndarray
                     ) -> tuple[float | None, np.ndarray | None, np.ndarray, float, float]:
    """Independent world-coordinate solve for a transformed spherical cap."""
    center = rotation @ surface.center_local + translation
    axis = rotation[:, 2]
    offset = origin - center
    b = float(offset @ direction)
    c = float(offset @ offset - surface.radius_signed_mm**2)
    disc = b * b - c
    if disc < 0.0:
        return None, None, center, disc, float("nan")
    root = float(np.sqrt(max(0.0, disc)))
    for distance in (-b - root, -b + root):
        if distance <= _EPS_T:
            continue
        hit = origin + distance * direction
        # The near-vertex hemisphere is selected by its projection on the lens axis.
        if surface.radius_signed_mm * float((hit - center) @ axis) >= 0.0:
            continue
        residual = abs(float(np.linalg.norm(hit - center)) - abs(surface.radius_signed_mm))
        return float(distance), hit, center, float(disc), residual
    return None, None, center, float(disc), float("nan")


def _refract_world(direction: np.ndarray, normal_into_incident: np.ndarray,
                   n1: float, n2: float) -> tuple[np.ndarray | None, float, str]:
    """World-frame Snell implementation, separately coded from local Snell."""
    cosine = -float(np.dot(direction, normal_into_incident))
    if cosine < -1e-12:
        return None, float("nan"), "WRONG_INTERFACE_SIDE"
    cosine = max(0.0, cosine)
    eta = float(n1 / n2)
    discriminant = 1.0 - eta * eta * max(0.0, 1.0 - cosine * cosine)
    if discriminant < -1e-12:
        return None, float(discriminant), "TIR"
    transmitted = (eta * direction + (eta * cosine - np.sqrt(max(0.0, discriminant)))
                   * normal_into_incident)
    length = float(np.linalg.norm(transmitted))
    if not np.isfinite(length) or length <= 0.0:
        return None, float(discriminant), "REFRACTION_FAILURE"
    return transmitted / length, float(discriminant), "PASS"


def _vec_fields(prefix: str, value: np.ndarray | None) -> dict[str, Any]:
    if value is None:
        return {f"{prefix}_{axis}": None for axis in "xyz"}
    return {f"{prefix}_{axis}": float(value[i]) for i, axis in enumerate("xyz")}


def _trace(model: SphericalModel, ray_ids: Iterable[int], origins_mm: np.ndarray,
           directions: np.ndarray, weights: np.ndarray, poses: Sequence[LensPose],
           route: Route, *, target_z_mm: float | None,
           target_radius_mm: float | None) -> TraceResult:
    ids, origins, dirs, source_w = _validate_rays(ray_ids, origins_mm, directions, weights)
    surfaces = _prescription_surfaces(model)
    rotations, translations = _pose_frame(model, poses)
    z_target = model.target_z_mm if target_z_mm is None else float(target_z_mm)
    r_target = model.target_radius_mm if target_radius_mm is None else float(target_radius_mm)
    if not np.isfinite(z_target + r_target) or r_target <= 0.0:
        raise S6GeometryError("target plane/radius is invalid")
    invalid = invalid_geometry_reason(model, poses, target_z_mm=z_target)
    if invalid:
        raise S6GeometryError(invalid)

    surface_rows: list[dict[str, Any]] = []
    ray_rows: list[dict[str, Any]] = []
    for ray_id, origin0, direction0, weight in zip(ids, origins, dirs, source_w, strict=True):
        ray_surface_rows: list[dict[str, Any]] = []
        point_world = origin0.copy()
        direction_world = direction0.copy()
        terminal: str | None = None
        target_hit: np.ndarray | None = None
        if direction_world[2] <= 0.0:
            terminal = "INVALID_SOURCE"
        for surf in surfaces:
            base = {
                "route": route, "ray_id": int(ray_id), "source_weight": float(weight),
                "surface_id": surf.surface_id, "n_before": surf.n_before,
                "n_after": surf.n_after, "semi_aperture_mm": surf.semi_aperture_mm,
            }
            if terminal is not None:
                ray_surface_rows.append({**base, "status": "NOT_REACHED_AFTER_" + terminal,
                                         "ill_conditioned": False})
                continue
            li = surf.lens_index
            rmat, tvec = rotations[li], translations[li]
            in_world = direction_world.copy()
            in_point_world = point_world.copy()
            if route == "local":
                in_point_local = rmat.T @ (point_world - tvec)
                in_direction_local = rmat.T @ direction_world
                distance, hit_local, disc, residual = _intersect_local(
                    in_point_local, in_direction_local, surf)
                if hit_local is None:
                    terminal = "NO_INTERSECTION"
                    ray_surface_rows.append({**base, **_vec_fields("incoming_world", in_point_world),
                                             **_vec_fields("incoming_direction_world", in_world),
                                             **_vec_fields("incoming_local", in_point_local),
                                             **_vec_fields("incoming_direction_local", in_direction_local),
                                             "sphere_discriminant_mm2": disc, "status": terminal,
                                             "ill_conditioned": False})
                    continue
                radial = float(np.hypot(hit_local[0], hit_local[1]))
                if radial > surf.semi_aperture_mm + 1e-12:
                    terminal = f"L{li + 1}_APERTURE_BLOCK"
                    hit_world = rmat @ hit_local + tvec
                    ray_surface_rows.append({**base, **_vec_fields("incoming_world", in_point_world),
                                             **_vec_fields("incoming_direction_world", in_world),
                                             **_vec_fields("hit_local", hit_local),
                                             **_vec_fields("hit_world", hit_world),
                                             "radial_local_mm": radial, "status": terminal,
                                             "sphere_discriminant_mm2": disc,
                                             "intersection_residual_mm": residual,
                                             "ill_conditioned": False})
                    continue
                normal_local = np.sign(surf.radius_signed_mm) * (hit_local - surf.center_local)
                normal_local /= np.linalg.norm(normal_local)
                out_local, snell_k, refraction = _refract_local(
                    in_direction_local, normal_local, surf.n_before, surf.n_after)
                incidence_cos = float(-in_direction_local @ normal_local)
                ill = (disc / (surf.radius_signed_mm**2) <= 1e-10
                       or abs(incidence_cos) <= 1e-6 or snell_k <= 1e-10)
                hit_world = rmat @ hit_local + tvec
                normal_world = rmat @ normal_local
                normal_world /= np.linalg.norm(normal_world)
                out_world = None if out_local is None else rmat @ out_local
                if out_world is not None:
                    out_world /= np.linalg.norm(out_world)
                status = "TRANSMITTED" if refraction == "PASS" else refraction
                ray_surface_rows.append({
                    **base, **_vec_fields("incoming_world", in_point_world),
                    **_vec_fields("incoming_direction_world", in_world),
                    **_vec_fields("incoming_local", in_point_local),
                    **_vec_fields("incoming_direction_local", in_direction_local),
                    **_vec_fields("hit_local", hit_local), **_vec_fields("hit_world", hit_world),
                    **_vec_fields("normal_world", normal_world),
                    **_vec_fields("outgoing_direction_world", out_world),
                    "radial_local_mm": radial, "incidence_cos": incidence_cos,
                    "sphere_discriminant_mm2": disc, "snell_k": snell_k,
                    "intersection_residual_mm": residual, "status": status,
                    "ill_conditioned": bool(ill),
                })
                if out_world is None:
                    terminal = "TIR" if refraction == "TIR" else "TRACE_FAIL"
                else:
                    point_world, direction_world = hit_world, out_world
            else:
                distance, hit_world, center_world, disc, residual = _intersect_world(
                    point_world, direction_world, surf, rmat, tvec)
                if hit_world is None:
                    terminal = "NO_INTERSECTION"
                    ray_surface_rows.append({**base, **_vec_fields("incoming_world", in_point_world),
                                             **_vec_fields("incoming_direction_world", in_world),
                                             "sphere_discriminant_mm2": disc, "status": terminal,
                                             "ill_conditioned": False})
                    continue
                # Aperture is checked in the co-moving lens plane, not global x/y.
                hit_local = rmat.T @ (hit_world - tvec)
                radial = float(np.hypot(hit_local[0], hit_local[1]))
                if radial > surf.semi_aperture_mm + 1e-12:
                    terminal = f"L{li + 1}_APERTURE_BLOCK"
                    ray_surface_rows.append({**base, **_vec_fields("incoming_world", in_point_world),
                                             **_vec_fields("incoming_direction_world", in_world),
                                             **_vec_fields("hit_local", hit_local),
                                             **_vec_fields("hit_world", hit_world),
                                             "radial_local_mm": radial, "status": terminal,
                                             "sphere_discriminant_mm2": disc,
                                             "intersection_residual_mm": residual,
                                             "ill_conditioned": False})
                    continue
                normal_world = np.sign(surf.radius_signed_mm) * (hit_world - center_world)
                normal_world /= np.linalg.norm(normal_world)
                out_world, snell_k, refraction = _refract_world(
                    direction_world, normal_world, surf.n_before, surf.n_after)
                incidence_cos = float(-direction_world @ normal_world)
                ill = (disc / (surf.radius_signed_mm**2) <= 1e-10
                       or abs(incidence_cos) <= 1e-6 or snell_k <= 1e-10)
                status = "TRANSMITTED" if refraction == "PASS" else refraction
                ray_surface_rows.append({
                    **base, **_vec_fields("incoming_world", in_point_world),
                    **_vec_fields("incoming_direction_world", in_world),
                    **_vec_fields("hit_local", hit_local), **_vec_fields("hit_world", hit_world),
                    **_vec_fields("normal_world", normal_world),
                    **_vec_fields("outgoing_direction_world", out_world),
                    "radial_local_mm": radial, "incidence_cos": incidence_cos,
                    "sphere_discriminant_mm2": disc, "snell_k": snell_k,
                    "intersection_residual_mm": residual, "status": status,
                    "ill_conditioned": bool(ill),
                })
                if out_world is None:
                    terminal = "TIR" if refraction == "TIR" else "TRACE_FAIL"
                else:
                    point_world, direction_world = hit_world, out_world
        if terminal is None:
            if direction_world[2] <= 0.0:
                terminal = "NO_INTERSECTION"
            else:
                t_target = (z_target - point_world[2]) / direction_world[2]
                if t_target <= _EPS_T:
                    terminal = "NO_INTERSECTION"
                else:
                    target_hit = point_world + t_target * direction_world
                    terminal = ("CAPTURED" if np.hypot(target_hit[0], target_hit[1])
                                <= r_target + 1e-12 else "OUTSIDE_TARGET")
        row = {"ray_id": int(ray_id), "source_weight": float(weight),
               "terminal_outcome": terminal, "target_z_mm": z_target,
               "exit_dx": float(direction_world[0]), "exit_dy": float(direction_world[1]),
               "exit_dz": float(direction_world[2])}
        row.update(_vec_fields("target", target_hit))
        ray_rows.append(row)
        surface_rows.extend(ray_surface_rows)

    weights_by: dict[str, float] = {}
    counts_by: dict[str, int] = {}
    for row in ray_rows:
        status = str(row["terminal_outcome"])
        weights_by[status] = weights_by.get(status, 0.0) + float(row["source_weight"])
        counts_by[status] = counts_by.get(status, 0) + 1
    source_total = float(np.sum(source_w, dtype=np.float64))
    classified = float(sum(weights_by.values()))
    ledger = {
        "route": route, "ray_count": int(ids.size), "source_weight_total": source_total,
        "classified_weight_total": classified,
        "balance_residual": source_total - classified,
        "captured_weight": weights_by.get("CAPTURED", 0.0),
        "capture_fraction_input": weights_by.get("CAPTURED", 0.0) / source_total,
        "terminal_weight": weights_by, "terminal_count": counts_by,
        "status": "PASS" if abs(source_total - classified) <= 1e-12 else "FAIL",
    }
    return TraceResult(route, surface_rows, ray_rows, ledger)


def trace_local(model: SphericalModel, ray_ids: Iterable[int], origins_mm: np.ndarray,
                directions: np.ndarray, weights: np.ndarray,
                poses: Sequence[LensPose] = (LensPose(), LensPose()), *,
                target_z_mm: float | None = None,
                target_radius_mm: float | None = None) -> TraceResult:
    """Trace using local-frame sphere intersections and local Snell refraction."""
    return _trace(model, ray_ids, origins_mm, directions, weights, poses, "local",
                  target_z_mm=target_z_mm, target_radius_mm=target_radius_mm)


def trace_world(model: SphericalModel, ray_ids: Iterable[int], origins_mm: np.ndarray,
                directions: np.ndarray, weights: np.ndarray,
                poses: Sequence[LensPose] = (LensPose(), LensPose()), *,
                target_z_mm: float | None = None,
                target_radius_mm: float | None = None) -> TraceResult:
    """Trace transformed world spheres with an independent quadratic/Snell path."""
    return _trace(model, ray_ids, origins_mm, directions, weights, poses, "world",
                  target_z_mm=target_z_mm, target_radius_mm=target_radius_mm)


def compare_references(local: TraceResult, world: TraceResult, *,
                       hit_tolerance_mm: float = 1e-7,
                       direction_tolerance: float = 1e-8,
                       target_tolerance_mm: float = 1e-6) -> ReferenceComparison:
    """Compare two independently produced traces by ray and physical surface."""
    if local.route != "local" or world.route != "world":
        raise S6GeometryError("reference comparison requires local and world routes")
    sr_l = {(r["ray_id"], r["surface_id"]): r for r in local.surface_rows}
    sr_w = {(r["ray_id"], r["surface_id"]): r for r in world.surface_rows}
    rr_l = {r["ray_id"]: r for r in local.ray_rows}
    rr_w = {r["ray_id"]: r for r in world.ray_rows}
    if set(sr_l) != set(sr_w) or set(rr_l) != set(rr_w):
        raise S6GeometryError("reference outputs have different ray/surface keys")
    hit_delta: list[float] = []
    incoming_point_delta: list[float] = []
    incoming_direction_delta: list[float] = []
    normal_delta: list[float] = []
    direction_delta: list[float] = []
    hit_mismatch = 0
    for key in sr_l:
        a, b = sr_l[key], sr_w[key]
        for field, out in (("incoming_world", incoming_point_delta),
                           ("incoming_direction_world", incoming_direction_delta)):
            va = [a.get(f"{field}_{q}") for q in "xyz"]
            vb = [b.get(f"{field}_{q}") for q in "xyz"]
            if all(x is not None for x in va + vb):
                out.append(float(np.max(np.abs(np.asarray(va, float) - np.asarray(vb, float)))))
        ah = [a.get(f"hit_world_{q}") for q in "xyz"]
        bh = [b.get(f"hit_world_{q}") for q in "xyz"]
        if all(x is None for x in ah) and all(x is None for x in bh):
            continue
        if any(x is None for x in ah) or any(x is None for x in bh):
            hit_mismatch += 1
            continue
        hit_delta.append(float(np.max(np.abs(np.asarray(ah, float) - np.asarray(bh, float)))))
        for field, out in (("normal_world", normal_delta),
                           ("outgoing_direction_world", direction_delta)):
            va = [a.get(f"{field}_{q}") for q in "xyz"]
            vb = [b.get(f"{field}_{q}") for q in "xyz"]
            if all(x is not None for x in va + vb):
                out.append(float(np.max(np.abs(np.asarray(va, float) - np.asarray(vb, float)))))
        if a["status"] != b["status"]:
            hit_mismatch += 1
    terminal_mismatch = sum(rr_l[k]["terminal_outcome"] != rr_w[k]["terminal_outcome"]
                            for k in rr_l)
    target_delta: list[float] = []
    for key in rr_l:
        a, b = rr_l[key], rr_w[key]
        va = [a.get(f"target_{q}") for q in "xyz"]
        vb = [b.get(f"target_{q}") for q in "xyz"]
        if all(x is not None for x in va + vb):
            target_delta.append(float(np.max(np.abs(np.asarray(va, float) - np.asarray(vb, float)))))
    max_hit = max(hit_delta, default=0.0)
    max_incoming_point = max(incoming_point_delta, default=0.0)
    max_incoming_direction = max(incoming_direction_delta, default=0.0)
    max_normal = max(normal_delta, default=0.0)
    max_direction = max(direction_delta, default=0.0)
    max_target = max(target_delta, default=0.0)
    ok = (terminal_mismatch == 0 and hit_mismatch == 0
          and max_incoming_point <= hit_tolerance_mm
          and max_incoming_direction <= direction_tolerance
          and max_hit <= hit_tolerance_mm and max_normal <= direction_tolerance
          and max_direction <= direction_tolerance and max_target <= target_tolerance_mm
          and local.ledger["status"] == "PASS" and world.ledger["status"] == "PASS")
    return ReferenceComparison(len(sr_l), terminal_mismatch, hit_mismatch,
                                max_incoming_point, max_incoming_direction, max_hit,
                                max_normal, max_direction, max_target,
                                "PASS" if ok else "FAIL")
