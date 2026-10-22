"""Frozen S6 assumed tolerance draws and assembly-cluster statistics."""

from __future__ import annotations

from typing import Any, Sequence

import numpy as np
from scipy.special import ndtr, ndtri

from optisys.optics.s6_rigid_body import LensPose

PARAMETER_ORDER = (
    "L1_dx_mm", "L1_dy_mm", "L1_tilt_x_deg", "L1_tilt_y_deg", "L1_dz_mm",
    "L2_dx_mm", "L2_dy_mm", "L2_tilt_x_deg", "L2_tilt_y_deg", "L2_dz_mm",
)
NOMINAL_SIGMA = np.asarray([0.05, 0.05, 0.10, 0.10, 0.30,
                            0.05, 0.05, 0.10, 0.10, 0.30], dtype=float)
TRUNCATION_SIGMA = 3.0
SCENARIO_SCALE = {"zero": 0.0, "tight_0p5x": 0.5, "nominal_1x": 1.0, "stress_2x": 2.0}


def truncated_standard_normal_latents(n: int, seed: int) -> np.ndarray:
    """Draw independent N(0,1) latents truncated to [-3,+3] by inverse CDF."""
    if isinstance(n, bool) or int(n) != n or n < 1:
        raise ValueError("n must be a positive integer")
    if isinstance(seed, bool) or int(seed) != seed or seed < 0:
        raise ValueError("seed must be a non-negative integer")
    rng = np.random.default_rng(int(seed))
    lo, hi = float(ndtr(-TRUNCATION_SIGMA)), float(ndtr(TRUNCATION_SIGMA))
    u = rng.uniform(lo, hi, size=(int(n), len(PARAMETER_ORDER)))
    z = ndtri(u)
    if not np.all(np.isfinite(z)) or np.max(np.abs(z)) > TRUNCATION_SIGMA:
        raise ArithmeticError("truncated-normal inverse-CDF draw escaped declared bounds")
    return z


def perturbation_vector(latent_z: Sequence[float], scenario: str) -> dict[str, float]:
    """Scale one shared latent draw into a declared tolerance scenario."""
    if scenario not in SCENARIO_SCALE:
        raise ValueError(f"unknown S6 tolerance scenario: {scenario!r}")
    z = np.asarray(latent_z, dtype=float)
    if z.shape != (len(PARAMETER_ORDER),) or not np.all(np.isfinite(z)):
        raise ValueError("latent_z must be a finite vector with ten parameters")
    if np.max(np.abs(z)) > TRUNCATION_SIGMA + 1e-12:
        raise ValueError("latent_z exceeds registered +/-3 sigma truncation")
    physical = z * NOMINAL_SIGMA * SCENARIO_SCALE[scenario]
    return {name: float(value) for name, value in zip(PARAMETER_ORDER, physical, strict=True)}


def poses_from_perturbation(vector: dict[str, float]) -> tuple[LensPose, LensPose]:
    """Convert the registered perturbation vector to two front-vertex poses."""
    if set(vector) != set(PARAMETER_ORDER):
        raise ValueError("perturbation vector has missing or unexpected fields")
    if not all(np.isfinite(float(vector[k])) for k in PARAMETER_ORDER):
        raise ValueError("perturbation vector contains NaN or infinity")
    return (
        LensPose(dx_mm=vector["L1_dx_mm"], dy_mm=vector["L1_dy_mm"],
                 tilt_x_deg=vector["L1_tilt_x_deg"], tilt_y_deg=vector["L1_tilt_y_deg"],
                 dz_mm=vector["L1_dz_mm"]),
        LensPose(dx_mm=vector["L2_dx_mm"], dy_mm=vector["L2_dy_mm"],
                 tilt_x_deg=vector["L2_tilt_x_deg"], tilt_y_deg=vector["L2_tilt_y_deg"],
                 dz_mm=vector["L2_dz_mm"]),
    )


def paired_cluster_bootstrap(
    assembly_ids: Sequence[str],
    baseline_capture: Sequence[float],
    candidate_capture: Sequence[float],
    *,
    n_replicates: int = 2000,
    seed: int = 8064001,
) -> list[dict[str, Any]]:
    """Bootstrap paired captures by resampling assemblies, never individual rays."""
    ids = [str(x) for x in assembly_ids]
    base = np.asarray(baseline_capture, dtype=float)
    cand = np.asarray(candidate_capture, dtype=float)
    if len(ids) == 0 or base.shape != (len(ids),) or cand.shape != (len(ids),):
        raise ValueError("assembly IDs and paired captures must have equal non-zero lengths")
    if len(set(ids)) != len(ids):
        raise ValueError("assembly IDs must be unique; duplicate assembly would corrupt the cluster unit")
    if not np.all(np.isfinite(base)) or not np.all(np.isfinite(cand)):
        raise ValueError("paired captures must be finite; NaN assembly result cannot be dropped")
    if np.any((base < 0.0) | (base > 1.0)) or np.any((cand < 0.0) | (cand > 1.0)):
        raise ValueError("assembly capture fractions must lie in [0,1]")
    if isinstance(n_replicates, bool) or int(n_replicates) != n_replicates or n_replicates < 1:
        raise ValueError("n_replicates must be a positive integer")
    if isinstance(seed, bool) or int(seed) != seed or seed < 0:
        raise ValueError("seed must be a non-negative integer")
    rng = np.random.default_rng(int(seed))
    n = len(ids)
    records: list[dict[str, Any]] = []
    for replicate in range(int(n_replicates)):
        sampled_assemblies = rng.integers(0, n, size=n)
        b, c = base[sampled_assemblies], cand[sampled_assemblies]
        diff = c - b
        records.append({
            "replicate": replicate,
            "resampling_unit": "assembly_id",
            "n_assemblies_resampled": n,
            "mean_delta_capture": float(np.mean(diff)),
            "p05_baseline_capture": float(np.quantile(b, 0.05)),
            "p05_candidate_capture": float(np.quantile(c, 0.05)),
            "p05_delta_capture": float(np.quantile(diff, 0.05)),
            "p50_delta_capture": float(np.quantile(diff, 0.50)),
            "p95_delta_capture": float(np.quantile(diff, 0.95)),
        })
    return records

