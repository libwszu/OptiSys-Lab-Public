"""Paired comparison with cluster bootstrap over assemblies.

Why paired
----------
``baseline``, ``nominal`` and ``robust`` see exactly the same assemblies and
the same scenes.  Comparing two independent confidence intervals is
under-powered and can hide a real difference; the paired difference on
identical units is the correct statistic.

Why clustered
-------------
Several frames share one assembly.  Resampling frames would pretend those
frames are independent units and shrink the interval artificially.  The
resampling unit here is the **assembly**; distance stratification is available
as an option.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np


@dataclass
class PairedResult:
    metric: str
    n_assemblies: int
    n_frames_a: int
    n_frames_b: int
    value_a: float
    value_b: float
    delta: float
    ci_low: float
    ci_high: float
    n_boot: int
    unit: str
    excludes_zero: bool
    direction: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "metric": self.metric,
            "n_assemblies": self.n_assemblies,
            "n_frames_a": self.n_frames_a,
            "n_frames_b": self.n_frames_b,
            "value_a": self.value_a,
            "value_b": self.value_b,
            "delta": self.delta,
            "ci_low": self.ci_low,
            "ci_high": self.ci_high,
            "n_boot": self.n_boot,
            "unit": self.unit,
            "excludes_zero": self.excludes_zero,
            "direction": self.direction,
        }


def _group(values: np.ndarray, clusters: np.ndarray) -> dict[str, np.ndarray]:
    out: dict[str, np.ndarray] = {}
    for cluster in np.unique(clusters):
        out[str(cluster)] = np.flatnonzero(clusters == cluster)
    return out


def _rmse(values: np.ndarray) -> float:
    return float(np.sqrt(np.mean(values**2))) if values.size else float("nan")


def paired_bootstrap(
    errors_a: np.ndarray,
    errors_b: np.ndarray,
    clusters: np.ndarray,
    *,
    metric: str,
    n_boot: int = 2000,
    seed: int = 20261019,
    alpha: float = 0.05,
    unit: str = "mm",
    direction: str = "lower_is_better",
) -> PairedResult:
    """Paired cluster bootstrap of ``metric(B) - metric(A)``."""

    a = np.asarray(errors_a, dtype=float)
    b = np.asarray(errors_b, dtype=float)
    c = np.asarray(clusters)
    if not (a.shape == b.shape == c.shape):
        raise ValueError("errors and clusters must share a shape")
    finite = np.isfinite(a) & np.isfinite(b)
    a, b, c = a[finite], b[finite], c[finite]
    if a.size == 0:
        raise ValueError("no paired finite samples")
    groups = _group(a, c)
    keys = sorted(groups)
    if len(keys) < 3:
        raise ValueError("cluster bootstrap needs at least 3 assemblies")

    def metric_fn(values: np.ndarray) -> float:
        if metric == "rmse":
            return _rmse(values)
        if metric == "p95_abs":
            return float(np.percentile(np.abs(values), 95))
        if metric == "bias":
            return float(np.mean(values))
        raise ValueError(f"unknown metric {metric!r}")

    value_a = metric_fn(a)
    value_b = metric_fn(b)
    rng = np.random.default_rng(seed)
    deltas = np.empty(n_boot, dtype=float)
    for index in range(n_boot):
        drawn = rng.choice(len(keys), size=len(keys), replace=True)
        idx = np.concatenate([groups[keys[j]] for j in drawn])
        deltas[index] = metric_fn(b[idx]) - metric_fn(a[idx])
    low = float(np.percentile(deltas, 100 * alpha / 2.0))
    high = float(np.percentile(deltas, 100 * (1.0 - alpha / 2.0)))
    return PairedResult(
        metric=metric, n_assemblies=len(keys), n_frames_a=int(a.size),
        n_frames_b=int(b.size), value_a=value_a, value_b=value_b,
        delta=float(value_b - value_a), ci_low=low, ci_high=high,
        n_boot=n_boot, unit=unit, excludes_zero=bool(low > 0 or high < 0),
        direction=direction,
    )


def paired_rate_difference(
    success_a: np.ndarray,
    success_b: np.ndarray,
    clusters: np.ndarray,
    *,
    n_boot: int = 2000,
    seed: int = 20261019,
    alpha: float = 0.05,
) -> PairedResult:
    """Paired cluster bootstrap of ``P(failure|B) - P(failure|A)``."""

    a = 1.0 - np.asarray(success_a, dtype=float)
    b = 1.0 - np.asarray(success_b, dtype=float)
    return paired_bootstrap(a, b, clusters, metric="bias", n_boot=n_boot, seed=seed,
                            alpha=alpha, unit="fraction", direction="lower_is_better")


def summarise_errors(rows: Sequence[dict[str, Any]], *,
                     group_keys: Sequence[str] = ("candidate",)) -> list[dict[str, Any]]:
    groups: dict[tuple, list[dict[str, Any]]] = {}
    for row in rows:
        key = tuple(row.get(name) for name in group_keys)
        groups.setdefault(key, []).append(row)
    out = []
    for key, items in sorted(groups.items(), key=lambda pair: tuple(str(v) for v in pair[0])):
        record = {name: value for name, value in zip(group_keys, key)}
        attempted = len(items)
        valid = [r for r in items if r.get("valid")]
        errors = np.array([float(r["signed_error_mm"]) for r in valid
                           if r.get("signed_error_mm") is not None], dtype=float)
        errors = errors[np.isfinite(errors)]
        record.update({
            "n_attempted": attempted,
            "n_valid": len(valid),
            "failure_rate": 1.0 - len(valid) / attempted if attempted else 1.0,
            "bias_mm": float(np.mean(errors)) if errors.size else None,
            "rmse_mm": _rmse(errors) if errors.size else None,
            "p95_abs_mm": float(np.percentile(np.abs(errors), 95)) if errors.size else None,
            "mae_mm": float(np.mean(np.abs(errors))) if errors.size else None,
        })
        out.append(record)
    return out
