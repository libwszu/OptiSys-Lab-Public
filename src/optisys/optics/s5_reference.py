"""Independent global-coordinate spherical-surface and vector-Snell reference.

This module deliberately does not import Optiland or call the project P1
adapter. It models only the assumed centered spherical N-BK7 singlets used by
the registered Stage 5 replay.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Iterable

import numpy as np


class ReferenceModelError(ValueError):
    """The registered independent reference model is not physically defined."""


class MaterialNotVerified(ReferenceModelError):
    """No validated dispersion protocol exists for the requested material."""


@dataclass(frozen=True)
class SphericalSurface:
    surface_id: str
    vertex_z_mm: float
    radius_signed_mm: float
    semi_aperture_mm: float
    n_before: float
    n_after: float

    @property
    def center_z_mm(self) -> float:
        return self.vertex_z_mm + self.radius_signed_mm


@dataclass(frozen=True)
class Singlet:
    name: str
    focal_length_mm: float
    clear_aperture_mm: float
    center_thickness_mm: float
    material_id: str
    refractive_index: float
    radius_front_mm: float
    radius_rear_mm: float
    front_vertex_z_mm: float
    rear_vertex_z_mm: float


@dataclass(frozen=True)
class SphericalModel:
    design_id: str
    wavelength_nm: float
    material_id: str
    refractive_index: float
    lenses: tuple[Singlet, Singlet]
    target_z_mm: float
    target_radius_mm: float

    @property
    def surfaces(self) -> tuple[SphericalSurface, ...]:
        n = self.refractive_index
        l1, l2 = self.lenses
        return (
            SphericalSurface("L1_FRONT", l1.front_vertex_z_mm, l1.radius_front_mm,
                             l1.clear_aperture_mm / 2.0, 1.0, n),
            SphericalSurface("L1_REAR", l1.rear_vertex_z_mm, l1.radius_rear_mm,
                             l1.clear_aperture_mm / 2.0, n, 1.0),
            SphericalSurface("L2_FRONT", l2.front_vertex_z_mm, l2.radius_front_mm,
                             l2.clear_aperture_mm / 2.0, 1.0, n),
            SphericalSurface("L2_REAR", l2.rear_vertex_z_mm, l2.radius_rear_mm,
                             l2.clear_aperture_mm / 2.0, n, 1.0),
        )


def n_bk7_sellmeier(wavelength_nm: float, material_id: str = "N-BK7") -> float:
    """Evaluate SCHOTT N-BK7 Sellmeier-2 over the registered 0.3-2.5 um range."""
    if material_id != "N-BK7":
        raise MaterialNotVerified(f"MATERIAL_NOT_VERIFIED: {material_id!r}")
    if not np.isfinite(wavelength_nm) or not 300.0 <= wavelength_nm <= 2500.0:
        raise ReferenceModelError("N-BK7 Sellmeier input must be within 300-2500 nm")
    lam_um2 = (float(wavelength_nm) / 1000.0) ** 2
    b = (1.03961212, 0.231792344, 1.01046945)
    c = (0.00600069867, 0.0200179144, 103.560653)
    n2 = 1.0 + sum(bi * lam_um2 / (lam_um2 - ci) for bi, ci in zip(b, c, strict=True))
    return float(np.sqrt(n2))


def build_model(
    optics_model: dict[str, Any], config: dict[str, Any], *,
    material_id: str = "N-BK7",
) -> SphericalModel:
    """Build the independent model by reconciling frozen run JSON and YAML."""
    if material_id != "N-BK7":
        raise MaterialNotVerified(f"MATERIAL_NOT_VERIFIED: {material_id!r}")
    source = config.get("source", {})
    optics = config.get("optics", {})
    design_id = str(config.get("design_id", ""))
    wavelength_nm = float(source.get("wavelength_nm", np.nan))
    n = n_bk7_sellmeier(wavelength_nm, material_id)
    p1 = optics_model.get("P1", {})
    key = {"baseline": "P1_baseline", "engineering_candidate": "P1_candidate"}.get(design_id)
    if key is None:
        raise ReferenceModelError(f"no frozen P1 model for design_id={design_id!r}")
    lens_specs = p1.get("lens_models", {}).get(key)
    if not isinstance(lens_specs, list) or len(lens_specs) != 2:
        raise ReferenceModelError(f"missing two-lens geometry for {key}")
    if abs(float(source.get("wavelength_nm", np.nan)) - 976.0) > 1e-12:
        raise ReferenceModelError("registered P1 geometry is specific to 976 nm")

    lenses: list[Singlet] = []
    for name, run_lens, cfg_lens in zip(("L1", "L2"), lens_specs,
                                        (optics.get("l1", {}), optics.get("l2", {})), strict=True):
        cfg_material = str(cfg_lens.get("material", ""))
        if cfg_material != material_id or str(run_lens.get("material", "")) != material_id:
            raise MaterialNotVerified(
                f"MATERIAL_NOT_VERIFIED: config/model material mismatch for {name}"
            )
        run_n = float(run_lens["index_sellmeier_976"])
        if not np.isclose(run_n, n, rtol=0.0, atol=1e-12):
            raise ReferenceModelError(f"{name} N-BK7 index disagrees with frozen Sellmeier input")
        fields = (
            ("focal_length_mm", "focal_length_mm"),
            ("aperture_diameter_mm", "diameter_mm"),
            ("thickness_mm", "thickness_mm"),
        )
        for run_key, config_key in fields:
            if not np.isclose(float(run_lens[run_key]), float(cfg_lens[config_key]),
                              rtol=0.0, atol=1e-10):
                raise ReferenceModelError(
                    f"{name} {run_key} mismatch between frozen geometry and config"
                )
        lens = Singlet(
            name=name,
            focal_length_mm=float(run_lens["focal_length_mm"]),
            clear_aperture_mm=float(run_lens["aperture_diameter_mm"]),
            center_thickness_mm=float(run_lens["thickness_mm"]),
            material_id=material_id,
            refractive_index=n,
            radius_front_mm=float(run_lens["radius_1_mm"]),
            radius_rear_mm=float(run_lens["radius_2_mm"]),
            front_vertex_z_mm=float(run_lens["front_vertex_z_mm"]),
            rear_vertex_z_mm=float(run_lens["rear_vertex_z_mm"]),
        )
        _validate_lens(lens)
        efl, bfl = singlet_abcd_efl_bfl(lens, n)
        if not np.isclose(efl, float(run_lens["matrix_efl_mm"]), rtol=0.0, atol=1e-8):
            raise ReferenceModelError(f"{name} independent ABCD EFL mismatch")
        if not np.isclose(bfl, float(run_lens["matrix_bfl_mm"]), rtol=0.0, atol=1e-8):
            raise ReferenceModelError(f"{name} independent ABCD BFL mismatch")
        lenses.append(lens)

    if lenses[1].front_vertex_z_mm <= lenses[0].rear_vertex_z_mm:
        raise ReferenceModelError("lens surfaces overlap or have invalid sequence")
    target = optics.get("target", {})
    target_z = float(target.get("z_mm", np.nan))
    target_radius = float(target.get("active_radius_mm", np.nan))
    if not np.isfinite(target_z + target_radius) or target_radius <= 0.0:
        raise ReferenceModelError("target plane/radius is invalid")
    if target_z <= lenses[1].rear_vertex_z_mm:
        raise ReferenceModelError("target is not downstream of L2 rear surface")
    return SphericalModel(design_id, wavelength_nm, material_id, n,
                          (lenses[0], lenses[1]), target_z, target_radius)


def _validate_lens(lens: Singlet) -> None:
    vals = (lens.focal_length_mm, lens.clear_aperture_mm, lens.center_thickness_mm,
            lens.radius_front_mm, lens.radius_rear_mm, lens.front_vertex_z_mm,
            lens.rear_vertex_z_mm, lens.refractive_index)
    if not all(np.isfinite(x) for x in vals):
        raise ReferenceModelError(f"{lens.name} has non-finite geometry")
    if min(lens.focal_length_mm, lens.clear_aperture_mm,
           lens.center_thickness_mm, lens.refractive_index) <= 0.0:
        raise ReferenceModelError(f"{lens.name} has non-positive physical parameter")
    if not (lens.radius_front_mm > 0.0 and lens.radius_rear_mm < 0.0):
        raise ReferenceModelError(f"{lens.name} is not an ordered equiconvex singlet")
    if not np.isclose(lens.rear_vertex_z_mm - lens.front_vertex_z_mm,
                      lens.center_thickness_mm, rtol=0.0, atol=1e-9):
        raise ReferenceModelError(f"{lens.name} vertex spacing differs from center thickness")
    if singlet_edge_thickness_mm(lens) <= 0.0:
        raise ReferenceModelError(f"{lens.name} has non-positive edge thickness")


def spherical_sag_mm(radius_signed_mm: float, semi_aperture_mm: float) -> float:
    """Positive axial sag magnitude of the near-vertex spherical cap."""
    r = abs(float(radius_signed_mm))
    a = float(semi_aperture_mm)
    if not np.isfinite(r + a) or r <= 0.0 or a < 0.0 or a >= r:
        raise ReferenceModelError("sphere requires finite radius and 0 <= semi-aperture < |R|")
    return float(r - np.sqrt((r - a) * (r + a)))


def singlet_edge_thickness_mm(lens: Singlet) -> float:
    a = lens.clear_aperture_mm / 2.0
    return float(lens.center_thickness_mm
                 - spherical_sag_mm(lens.radius_front_mm, a)
                 - spherical_sag_mm(lens.radius_rear_mm, a))


def singlet_abcd_efl_bfl(lens: Singlet, n_glass: float) -> tuple[float, float]:
    """Independent reduced-angle paraxial matrix for air/glass/air singlet."""
    r1, r2 = lens.radius_front_mm, lens.radius_rear_mm
    phi1 = (n_glass - 1.0) / r1
    phi2 = (1.0 - n_glass) / r2
    ref1 = np.array([[1.0, 0.0], [-phi1, 1.0]])
    trans = np.array([[1.0, lens.center_thickness_mm / n_glass], [0.0, 1.0]])
    ref2 = np.array([[1.0, 0.0], [-phi2, 1.0]])
    m = ref2 @ trans @ ref1
    efl = -1.0 / m[1, 0]
    bfl = -m[0, 0] / m[1, 0]
    return float(efl), float(bfl)


def lens_geometry_rows(model: SphericalModel, *, low_edge_warning_mm: float = 0.5) -> list[dict[str, Any]]:
    rows = []
    for lens in model.lenses:
        a = lens.clear_aperture_mm / 2.0
        s1 = spherical_sag_mm(lens.radius_front_mm, a)
        s2 = spherical_sag_mm(lens.radius_rear_mm, a)
        edge = lens.center_thickness_mm - s1 - s2
        efl, bfl = singlet_abcd_efl_bfl(lens, lens.refractive_index)
        if edge <= 0.0:
            status = "INVALID_EDGE_THICKNESS"
        elif edge < low_edge_warning_mm:
            status = "EDGE_THICKNESS_ASSUMED_LOW"
        else:
            status = "GEOMETRY_VALID_ASSUMED"
        rows.append({
            "design_id": model.design_id,
            "lens_id": lens.name,
            "material_id": lens.material_id,
            "dispersion_source": "SCHOTT N-BK7 Sellmeier 2; Optiland catalog at 976 nm",
            "wavelength_nm": model.wavelength_nm,
            "radius_front_mm": lens.radius_front_mm,
            "radius_rear_mm": lens.radius_rear_mm,
            "clear_aperture_diameter_mm": lens.clear_aperture_mm,
            "outer_diameter_mm": "UNSPECIFIED",
            "mechanical_envelope_mm": "UNSPECIFIED",
            "center_thickness_mm": lens.center_thickness_mm,
            "front_sag_mm": s1,
            "rear_sag_mm": s2,
            "edge_thickness_mm": edge,
            "efl_abcd_mm": efl,
            "bfl_abcd_mm": bfl,
            "surface_intersection_at_clear_aperture": a < abs(lens.radius_front_mm)
                                                       and a < abs(lens.radius_rear_mm),
            "manufacturer_feasibility": "NOT_VALIDATED_NO_VENDOR_DRAWING",
            "status": status,
            "evidence": "DERIVED_FROM_ASSUMED_G4_GEOMETRY",
        })
    return rows


def shift_lens2_principal_plane(model: SphericalModel, delta_z_mm: float) -> SphericalModel:
    """Translate L2 rigidly while keeping its optical prescription unchanged."""
    if not np.isfinite(delta_z_mm):
        raise ReferenceModelError("L2 position shift must be finite")
    l1, l2 = model.lenses
    shifted = replace(l2, front_vertex_z_mm=l2.front_vertex_z_mm + float(delta_z_mm),
                      rear_vertex_z_mm=l2.rear_vertex_z_mm + float(delta_z_mm))
    _validate_lens(shifted)
    if shifted.front_vertex_z_mm <= l1.rear_vertex_z_mm:
        raise ReferenceModelError("shifted L2 overlaps L1")
    if model.target_z_mm <= shifted.rear_vertex_z_mm:
        raise ReferenceModelError("shifted L2 is not upstream of target")
    return replace(model, lenses=(l1, shifted))


def _sphere_intersection(origin: np.ndarray, direction: np.ndarray,
                         surface: SphericalSurface) -> tuple[float | None, np.ndarray | None,
                                                              float | None, float, str]:
    center = np.array([0.0, 0.0, surface.center_z_mm])
    rel = origin - center
    b = float(np.dot(rel, direction))
    c = float(np.dot(rel, rel) - surface.radius_signed_mm**2)
    disc = b * b - c
    r = abs(surface.radius_signed_mm)
    if disc < 0.0:
        return None, None, None, disc, "NO_INTERSECTION"
    sqrt_disc = float(np.sqrt(max(disc, 0.0)))
    roots = sorted((-b - sqrt_disc, -b + sqrt_disc))
    for t in roots:
        if t <= 1e-12:
            continue
        point = origin + t * direction
        # Keep the physical cap containing the declared vertex, not the back
        # hemisphere of the mathematical sphere.
        if surface.radius_signed_mm * (point[2] - surface.center_z_mm) >= 0.0:
            continue
        residual = abs(float(np.linalg.norm(point - center)) - r)
        return float(t), point, residual, disc, "PASS"
    return None, None, None, disc, "NO_INTERSECTION"


def _snell(direction: np.ndarray, normal_incident: np.ndarray,
           n1: float, n2: float) -> tuple[np.ndarray | None, float, str]:
    """Vector Snell law; normal points into incident medium, against the ray."""
    dot = float(np.dot(direction, normal_incident))
    if dot > 1e-12:
        return None, float("nan"), "WRONG_INTERFACE_SIDE"
    cos_i = -dot
    eta = n1 / n2
    k = 1.0 - eta * eta * max(0.0, 1.0 - cos_i * cos_i)
    if k < -1e-12:
        return None, k, "TIR_OR_REFRACTION_FAILURE"
    direction_out = eta * direction + (eta * cos_i - np.sqrt(max(k, 0.0))) * normal_incident
    norm = float(np.linalg.norm(direction_out))
    if not np.isfinite(norm) or norm <= 0.0:
        return None, k, "TIR_OR_REFRACTION_FAILURE"
    return direction_out / norm, k, "PASS"


def trace_rays(
    model: SphericalModel,
    ray_ids: Iterable[int],
    origins_mm: np.ndarray,
    directions: np.ndarray,
    weights: np.ndarray,
    *,
    target_z_mm: float | None = None,
    target_radius_mm: float | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Trace rays through four global spheres and return all surface/ray rows."""
    ids = np.asarray(list(ray_ids), dtype=np.int64)
    o = np.asarray(origins_mm, dtype=float)
    d = np.asarray(directions, dtype=float)
    w = np.asarray(weights, dtype=float)
    if o.shape != (ids.size, 3) or d.shape != o.shape or w.shape != (ids.size,):
        raise ReferenceModelError("ray IDs, origins, directions, and weights have inconsistent shapes")
    if ids.size == 0 or len(np.unique(ids)) != ids.size:
        raise ReferenceModelError("ray bundle must be non-empty with unique ray IDs")
    if not np.all(np.isfinite(o)) or not np.all(np.isfinite(d)):
        raise ReferenceModelError("ray positions and directions must be finite")
    if not np.all(np.isfinite(w)) or np.any(w <= 0.0):
        raise ReferenceModelError("ray weights must be finite and strictly positive")
    norms = np.linalg.norm(d, axis=1)
    if np.any(norms <= 0.0) or np.max(np.abs(norms - 1.0)) > 1e-12:
        raise ReferenceModelError("ray directions must be unit vectors within 1e-12")
    d = d / norms[:, None]
    z_target = model.target_z_mm if target_z_mm is None else float(target_z_mm)
    r_target = model.target_radius_mm if target_radius_mm is None else float(target_radius_mm)
    if not np.isfinite(z_target + r_target) or r_target <= 0.0:
        raise ReferenceModelError("target plane and radius must be finite; radius positive")
    if z_target <= model.lenses[1].rear_vertex_z_mm:
        raise ReferenceModelError("target plane must be downstream of L2 rear vertex")

    surface_rows: list[dict[str, Any]] = []
    ray_rows: list[dict[str, Any]] = []
    surfaces = model.surfaces
    for idx, (ray_id, origin, direction, weight) in enumerate(zip(ids, o, d, w, strict=True)):
        p = origin.copy()
        v = direction.copy()
        terminal = "PASS" if direction[2] > 0.0 else "INVALID_SOURCE"
        condition = ""
        incidence: list[float | None] = [None] * len(surfaces)
        hit_radii: list[float | None] = [None] * len(surfaces)
        hits: list[np.ndarray | None] = [None] * len(surfaces)
        for si, surface in enumerate(surfaces):
            row: dict[str, Any] = {
                "ray_id": int(ray_id), "surface_index": si + 1,
                "surface_id": surface.surface_id, "source_weight": float(weight),
                "incoming_x_mm": float(p[0]) if terminal == "PASS" else None,
                "incoming_y_mm": float(p[1]) if terminal == "PASS" else None,
                "incoming_z_mm": float(p[2]) if terminal == "PASS" else None,
                "incoming_dx": float(v[0]) if terminal == "PASS" else None,
                "incoming_dy": float(v[1]) if terminal == "PASS" else None,
                "incoming_dz": float(v[2]) if terminal == "PASS" else None,
                "hit_x_mm": None, "hit_y_mm": None, "hit_z_mm": None,
                "normal_x": None, "normal_y": None, "normal_z": None,
                "outgoing_dx": None, "outgoing_dy": None, "outgoing_dz": None,
                "n_before": surface.n_before, "n_after": surface.n_after,
                "intersection_residual_mm": None, "snell_k": None,
                "incidence_cos": None, "radial_height_mm": None,
                "semi_aperture_mm": surface.semi_aperture_mm,
                "ill_conditioned": False,
            }
            if terminal != "PASS":
                row["status"] = f"NOT_REACHED_AFTER_{terminal}"
                surface_rows.append(row)
                continue
            t, hit, residual, discriminant, intersect_status = _sphere_intersection(p, v, surface)
            if intersect_status != "PASS" or t is None or hit is None:
                row["status"] = "NO_INTERSECTION"
                row["sphere_discriminant_mm2"] = discriminant
                surface_rows.append(row)
                terminal = "NO_INTERSECTION"
                continue
            row["hit_x_mm"], row["hit_y_mm"], row["hit_z_mm"] = map(float, hit)
            row["intersection_residual_mm"] = float(residual)
            row["sphere_discriminant_mm2"] = float(discriminant)
            radial = float(np.hypot(hit[0], hit[1]))
            row["radial_height_mm"] = radial
            hit_radii[si] = radial
            hits[si] = hit.copy()
            rel_z = float(hit[2] - surface.center_z_mm)
            q = np.array([hit[0], hit[1], rel_z]) / abs(surface.radius_signed_mm)
            q /= np.linalg.norm(q)
            normal = np.sign(surface.radius_signed_mm) * q
            # At a correctly sequenced interface, the ray arrives from the
            # material on the pre-surface side and N points back into it.
            if float(np.dot(v, normal)) > 1e-12:
                row["status"] = "WRONG_INTERFACE_SIDE"
                surface_rows.append(row)
                terminal = "TRACE_FAILED"
                continue
            row["normal_x"], row["normal_y"], row["normal_z"] = map(float, normal)
            row["incidence_cos"] = float(-np.dot(v, normal))
            incidence[si] = float(-np.dot(v, normal))
            ill = discriminant <= 1e-12 * max(surface.radius_signed_mm**2, 1.0)
            if ill:
                row["ill_conditioned"] = True
                condition = condition or "ILL_CONDITIONED"
            if radial * radial > surface.semi_aperture_mm**2 + 1e-12:
                row["status"] = "APERTURE_BLOCKED_L1" if si < 2 else "APERTURE_BLOCKED_L2"
                surface_rows.append(row)
                terminal = row["status"]
                continue
            out, k, snell_status = _snell(v, normal, surface.n_before, surface.n_after)
            row["snell_k"] = float(k)
            if np.isfinite(k) and abs(k) <= 1e-12:
                row["ill_conditioned"] = True
                condition = condition or "ILL_CONDITIONED"
            if snell_status != "PASS" or out is None:
                row["status"] = "TIR_OR_REFRACTION_FAILURE"
                surface_rows.append(row)
                terminal = "TIR_OR_REFRACTION_FAILURE"
                continue
            row["outgoing_dx"], row["outgoing_dy"], row["outgoing_dz"] = map(float, out)
            row["status"] = "PASS"
            surface_rows.append(row)
            p, v = hit, out

        tx = ty = None
        if terminal == "PASS":
            if v[2] <= 1e-14:
                terminal = "NO_INTERSECTION"
            else:
                t_plane = (z_target - p[2]) / v[2]
                if t_plane <= 0.0:
                    terminal = "NO_INTERSECTION"
                else:
                    tx = float(p[0] + t_plane * v[0])
                    ty = float(p[1] + t_plane * v[1])
                    if not np.isfinite(tx + ty):
                        terminal = "TRACE_FAILED"
                    elif tx * tx + ty * ty > r_target * r_target + 1e-12:
                        terminal = "OUTSIDE_TARGET"
                    else:
                        terminal = "CAPTURED"
        ray_rows.append({
            "ray_id": int(ray_id), "source_weight": float(weight),
            "theta_deg": float(np.rad2deg(np.arccos(np.clip(direction[2], -1.0, 1.0)))),
            "source_radius_mm": float(np.hypot(origin[0], origin[1])),
            "target_z_mm": z_target, "target_radius_mm": r_target,
            "target_x_mm": tx, "target_y_mm": ty,
            "target_radius_from_axis_mm": float(np.hypot(tx, ty)) if tx is not None else None,
            "exit_dx": float(v[0]) if terminal in ("CAPTURED", "OUTSIDE_TARGET") else None,
            "exit_dy": float(v[1]) if terminal in ("CAPTURED", "OUTSIDE_TARGET") else None,
            "exit_dz": float(v[2]) if terminal in ("CAPTURED", "OUTSIDE_TARGET") else None,
            "L1_front_incidence_cos": incidence[0], "L1_rear_incidence_cos": incidence[1],
            "L2_front_incidence_cos": incidence[2], "L2_rear_incidence_cos": incidence[3],
            "L1_front_radius_mm": hit_radii[0], "L1_rear_radius_mm": hit_radii[1],
            "L2_front_radius_mm": hit_radii[2], "L2_rear_radius_mm": hit_radii[3],
            "terminal_outcome": terminal,
            "condition_flag": condition,
            "evidence": "SIMULATED_INDEPENDENT_S5_REFERENCE",
        })

    total = float(np.sum(w, dtype=np.float64))
    sums = {name: float(sum(row["source_weight"] for row in ray_rows
                            if row["terminal_outcome"] == name))
            for name in ("CAPTURED", "OUTSIDE_TARGET", "APERTURE_BLOCKED_L1",
                         "APERTURE_BLOCKED_L2", "NO_INTERSECTION",
                         "TIR_OR_REFRACTION_FAILURE", "TRACE_FAILED", "INVALID_SOURCE")}
    residual = total - sum(sums.values())
    ledger = {"source_weight_total": total, **{f"{k.lower()}_weight": v for k, v in sums.items()},
              "balance_residual": residual, "n_rays": int(ids.size),
              "classified_ray_count": int(sum(1 for row in ray_rows if row["terminal_outcome"] in sums)),
              "unique_ray_count": int(len({row["ray_id"] for row in ray_rows})),
              "status": "PASS" if abs(residual) <= 1e-10 and len(ray_rows) == ids.size else "FAIL"}
    return surface_rows, ray_rows, ledger


def _blank(value: Any) -> str | float | int | bool | None:
    if value is None:
        return None
    if isinstance(value, np.generic):
        return value.item()
    return value
