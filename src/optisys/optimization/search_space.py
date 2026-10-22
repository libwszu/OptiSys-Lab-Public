"""Frozen 3-variable design space and deterministic screening designs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from optisys.config_g2 import ResolvedG2Config


@dataclass(frozen=True)
class Design:
    baseline_mm: float
    focal_length_mm: float
    theta_deg: float

    @property
    def theta_rad(self) -> float:
        return float(np.deg2rad(self.theta_deg))

    def key(self) -> str:
        return f"B{self.baseline_mm:.4f}_f{self.focal_length_mm:.4f}_t{self.theta_deg:.4f}"

    def as_row(self) -> dict[str, Any]:
        return {
            "baseline_mm": self.baseline_mm,
            "focal_length_mm": self.focal_length_mm,
            "theta_deg": self.theta_deg,
        }

    def clip(self, space: "SearchSpace") -> "Design":
        return Design(
            baseline_mm=float(np.clip(self.baseline_mm, *space.bounds[0])),
            focal_length_mm=float(np.clip(self.focal_length_mm, *space.bounds[1])),
            theta_deg=float(np.clip(self.theta_deg, *space.bounds[2])),
        )


@dataclass(frozen=True)
class SearchSpace:
    bounds: tuple[tuple[float, float], ...]
    names: tuple[str, ...] = ("baseline_mm", "focal_length_mm", "theta_deg")

    @classmethod
    def from_config(cls, config: ResolvedG2Config) -> "SearchSpace":
        return cls(
            bounds=((15.0, 35.0), (6.0, 12.0), (-4.0, 4.0)),
        )

    def decode(self, vector: np.ndarray) -> Design:
        v = np.asarray(vector, dtype=float)
        return Design(float(v[0]), float(v[1]), float(v[2]))

    def encode(self, design: Design) -> np.ndarray:
        return np.array([design.baseline_mm, design.focal_length_mm, design.theta_deg])

    def contains(self, design: Design, tol: float = 1e-9) -> bool:
        for value, (low, high) in zip(self.encode(design), self.bounds):
            if value < low - tol or value > high + tol:
                return False
        return True

    def lhs(self, n: int, seed: int) -> list[Design]:
        rng = np.random.default_rng(seed)
        dims = len(self.bounds)
        cut = (np.arange(n)[:, None] + rng.random((n, dims))) / n
        for j in range(dims):
            cut[:, j] = cut[rng.permutation(n), j]
        lows = np.array([b[0] for b in self.bounds])
        highs = np.array([b[1] for b in self.bounds])
        points = lows + cut * (highs - lows)
        return [self.decode(row) for row in points]

    def describe(self) -> dict[str, Any]:
        return {
            "variables": list(self.names),
            "bounds": [list(b) for b in self.bounds],
            "units": ["mm", "mm", "deg"],
        }
