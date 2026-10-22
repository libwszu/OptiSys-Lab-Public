"""Reproducible geometric-ray model for a multimode fiber end face.

The distributions here are declared sampling assumptions. They do not solve
fiber modes, coherence, speckle, or an experimentally measured far field.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np

AngularDistribution = Literal["uniform_solid_angle", "edge_biased_sin_theta"]


@dataclass(frozen=True)
class RayBundle:
    """Vectorized rays emitted from z=0, with dimensionless source weights."""

    ray_id: np.ndarray
    origin_mm: np.ndarray
    direction: np.ndarray
    weight: np.ndarray
    seed: int
    distribution_id: str
    metadata: dict[str, Any]

    def __post_init__(self) -> None:
        ids = np.asarray(self.ray_id)
        origins = np.asarray(self.origin_mm, dtype=float)
        directions = np.asarray(self.direction, dtype=float)
        weights = np.asarray(self.weight, dtype=float)
        n = ids.size
        if ids.ndim != 1 or n < 1:
            raise ValueError("ray_id must be a non-empty one-dimensional array")
        if origins.shape != (n, 3) or directions.shape != (n, 3) or weights.shape != (n,):
            raise ValueError("ray arrays must have shapes (N,3), (N,3), and (N,)")
        if len(np.unique(ids)) != n:
            raise ValueError("ray_id values must be unique")
        if not (np.all(np.isfinite(origins)) and np.all(np.isfinite(directions))
                and np.all(np.isfinite(weights))):
            raise ValueError("ray bundle contains non-finite values")
        if np.any(weights < 0.0):
            raise ValueError("ray weights must be non-negative")
        norms = np.linalg.norm(directions, axis=1)
        if np.any(norms <= 0.0) or not np.allclose(norms, 1.0, rtol=0.0, atol=1e-12):
            raise ValueError("ray directions must be normalized")
        if np.any(directions[:, 2] <= 0.0):
            raise ValueError("all source rays must propagate toward +z")

    @property
    def n_rays(self) -> int:
        return int(self.ray_id.size)

    @property
    def total_weight(self) -> float:
        return float(np.sum(self.weight, dtype=np.float64))


def sample_multimode_fiber(
    n_rays: int,
    core_diameter_mm: float,
    numerical_aperture: float,
    *,
    output_index: float = 1.0,
    seed: int = 976051,
    angular_distribution: AngularDistribution = "uniform_solid_angle",
) -> RayBundle:
    """Sample a uniform-area core and a declared angular probability measure.

    Baseline angular sampling is uniform per unit solid angle over a forward
    cone.  The sensitivity alternative uses ``F(q)=q**3`` for
    ``q=sin(theta)/sin(theta_max)`` and is explicitly not a measured profile.
    Equal weights sum to one so results remain dimensionless when source power
    is unknown.
    """

    if isinstance(n_rays, bool) or int(n_rays) != n_rays or n_rays <= 0:
        raise ValueError("n_rays must be a positive integer")
    vals = (core_diameter_mm, numerical_aperture, output_index)
    if not all(np.isfinite(v) for v in vals):
        raise ValueError("source parameters must be finite")
    if core_diameter_mm < 0.0:
        raise ValueError("core_diameter_mm must be non-negative")
    if numerical_aperture < 0.0:
        raise ValueError("numerical_aperture must be non-negative")
    if output_index <= 0.0:
        raise ValueError("output_index must be positive")
    if numerical_aperture > output_index:
        raise ValueError("NA exceeds output refractive index")
    if angular_distribution not in ("uniform_solid_angle", "edge_biased_sin_theta"):
        raise ValueError(f"unsupported angular distribution {angular_distribution!r}")

    n = int(n_rays)
    rng = np.random.default_rng(int(seed))
    radius_mm = core_diameter_mm / 2.0
    radial_u = rng.random(n)
    position_phi = rng.uniform(0.0, 2.0 * np.pi, n)
    radius = radius_mm * np.sqrt(radial_u)
    x = radius * np.cos(position_phi)
    y = radius * np.sin(position_phi)

    sin_theta_max = numerical_aperture / output_index
    theta_max = float(np.arcsin(sin_theta_max))
    angular_u = rng.random(n)
    direction_phi = rng.uniform(0.0, 2.0 * np.pi, n)
    if angular_distribution == "uniform_solid_angle":
        # dP/dOmega is constant; cos(theta) is uniform on the cone interval.
        cos_theta = 1.0 - angular_u * (1.0 - np.cos(theta_max))
        sin_theta = np.sqrt(np.maximum(0.0, 1.0 - cos_theta * cos_theta))
    else:
        # q has CDF q^3, hence sin(theta)=sin(theta_max)*U^(1/3).
        sin_theta = sin_theta_max * np.cbrt(angular_u)
        cos_theta = np.sqrt(np.maximum(0.0, 1.0 - sin_theta * sin_theta))

    direction = np.column_stack((
        sin_theta * np.cos(direction_phi),
        sin_theta * np.sin(direction_phi),
        cos_theta,
    ))
    direction /= np.linalg.norm(direction, axis=1)[:, None]
    origin = np.column_stack((x, y, np.zeros(n, dtype=float)))
    weight = np.full(n, 1.0 / n, dtype=float)
    return RayBundle(
        ray_id=np.arange(n, dtype=np.int64),
        origin_mm=origin,
        direction=direction,
        weight=weight,
        seed=int(seed),
        distribution_id=f"uniform_area_disk+{angular_distribution}/v1",
        metadata={
            "core_diameter_mm": float(core_diameter_mm),
            "core_radius_mm": radius_mm,
            "numerical_aperture": float(numerical_aperture),
            "output_index": float(output_index),
            "theta_max_rad": theta_max,
            "theta_max_deg": float(np.rad2deg(theta_max)),
            "position_measure": "uniform area; r=R*sqrt(U), phi~Uniform(0,2pi)",
            "angular_measure": (
                "uniform solid angle; cos(theta) uniform on [cos(theta_max),1]"
                if angular_distribution == "uniform_solid_angle"
                else "edge biased; q=sin(theta)/sin(theta_max), F(q)=q^3"
            ),
            "independence_assumption": "position and direction samples independent; not measured",
            "weight_semantics": "dimensionless equal weights normalized to sum 1; absolute power UNKNOWN",
            "evidence": "ASSUMED_SIMULATED",
        },
    )
