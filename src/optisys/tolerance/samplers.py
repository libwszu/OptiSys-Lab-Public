"""Tolerance sampling: plain normal draws and correct Latin hypercube.

The LHS path is the one that is easy to get wrong.  What is implemented here is
the standard recipe:

1. draw a Latin hypercube in the unit cube (one stratified sample per axis per
   stratum, randomly permuted);
2. map each margin through the **inverse normal CDF**, which is the correct
   transform for a normal target distribution.  Feeding the uniform draw
   straight into the physics as if it were a normal deviate - the common
   mistake - is never done.

Correlation is injected with a Cholesky factor and checked for positive
definiteness before use.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import stats

VARIABLE_ORDER = ("d_baseline_mm", "d_theta_rad", "d_focal_relative", "d_cx_px", "d_focus_mm")


@dataclass(frozen=True)
class DrawSet:
    """Standardised draws ``z`` (n, 5) plus the sigma vector used to scale them."""

    z: np.ndarray
    sigmas: np.ndarray
    method: str
    seed: int

    def physical(self) -> np.ndarray:
        return self.z * self.sigmas

    @property
    def n(self) -> int:
        return int(self.z.shape[0])


def sigma_vector(sigmas: dict[str, float]) -> np.ndarray:
    missing = [name for name in VARIABLE_ORDER if name not in sigmas]
    if missing:
        raise ValueError(f"missing sigma for: {missing}")
    values = np.array([sigmas[name] for name in VARIABLE_ORDER], dtype=float)
    if not np.all(np.isfinite(values)):
        raise ValueError("every sigma must be finite")
    if np.any(values <= 0.0):
        bad = [name for name, value in zip(VARIABLE_ORDER, values) if value <= 0.0]
        raise ValueError(f"sigma must be > 0 for: {bad}")
    return values


def latin_hypercube(n: int, dims: int, seed: int) -> np.ndarray:
    """Stratified unit-cube samples with one point per stratum per axis."""

    if n < 2:
        raise ValueError("LHS requires n >= 2")
    rng = np.random.default_rng(seed)
    cut = (np.arange(n)[:, None] + rng.random((n, dims))) / n
    for j in range(dims):
        cut[:, j] = cut[rng.permutation(n), j]
    return cut


def inverse_normal(u: np.ndarray) -> np.ndarray:
    """Standard normal quantile of a unit-cube sample (clipped away from 0/1)."""

    clipped = np.clip(u, 1e-12, 1.0 - 1e-12)
    return stats.norm.ppf(clipped)


def correlation_matrix(rho_baseline_theta: float) -> np.ndarray:
    """5x5 correlation matrix with a single non-zero B-theta correlation."""

    if not (-0.99 < rho_baseline_theta < 0.99):
        raise ValueError("rho must lie in (-0.99, 0.99)")
    matrix = np.eye(len(VARIABLE_ORDER))
    matrix[0, 1] = matrix[1, 0] = rho_baseline_theta
    eigenvalues = np.linalg.eigvalsh(matrix)
    if np.min(eigenvalues) <= 0:
        raise ValueError("correlation matrix is not positive definite")
    return matrix


def draw_normal(n: int, sigmas: dict[str, float], seed: int,
                rho: float | None = None) -> DrawSet:
    rng = np.random.default_rng(seed)
    z = rng.standard_normal((n, len(VARIABLE_ORDER)))
    if rho is not None:
        chol = np.linalg.cholesky(correlation_matrix(rho))
        z = z @ chol.T
    return DrawSet(z=z, sigmas=sigma_vector(sigmas), method="normal", seed=seed)


def draw_lhs(n: int, sigmas: dict[str, float], seed: int,
             rho: float | None = None) -> DrawSet:
    u = latin_hypercube(n, len(VARIABLE_ORDER), seed)
    z = inverse_normal(u)
    if rho is not None:
        chol = np.linalg.cholesky(correlation_matrix(rho))
        z = z @ chol.T
    return DrawSet(z=z, sigmas=sigma_vector(sigmas), method="latin_hypercube", seed=seed)


def draw(method: str, n: int, sigmas: dict[str, float], seed: int,
         rho: float | None = None) -> DrawSet:
    if method == "normal":
        return draw_normal(n, sigmas, seed, rho)
    if method == "latin_hypercube":
        return draw_lhs(n, sigmas, seed, rho)
    raise ValueError(f"unknown sampling method {method!r}")
