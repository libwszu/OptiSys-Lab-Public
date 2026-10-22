"""Grouped metrics with explicit failure denominators.

Accuracy metrics are conditional on valid frames and are always reported next
to ``n_valid / n_attempted``.  Failure rates use every attempted frame.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

import numpy as np

BLOCKING_FLAGS = frozenset({
    "SATURATED",
    "ROI_AT_BORDER",
    "MODEL_MISMATCH",
    "NO_SIGNAL",
    "INVALID_ROI",
    "NUMERICAL_FAILURE",
    "FIT_NOT_CONVERGED",
})


def parse_flags(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, (list, tuple, set)):
        return {str(item) for item in value if item}
    text = str(value).strip()
    if not text:
        return set()
    return {part.strip() for part in text.replace(",", ";").split(";") if part.strip()}


def is_valid(row: dict[str, Any]) -> bool:
    if str(row.get("estimator_status", row.get("status", ""))) != "OK":
        return False
    flags = parse_flags(row.get("quality_flags", row.get("flags", "")))
    return not (flags & BLOCKING_FLAGS)


def _rmse(values: np.ndarray) -> float:
    return float(np.sqrt(np.mean(values**2))) if values.size else float("nan")


def _p95_abs(values: np.ndarray) -> float:
    return float(np.percentile(np.abs(values), 95)) if values.size else float("nan")


def bootstrap_rmse_ci(errors: np.ndarray, clusters: np.ndarray, n_boot: int = 500,
                      seed: int = 20261019, alpha: float = 0.05
                      ) -> tuple[float | None, float | None]:
    """Cluster bootstrap by distance: resample whole distances, not frames."""

    unique = np.unique(clusters)
    if unique.size < 3 or errors.size == 0:
        return None, None
    rng = np.random.default_rng(seed)
    stats = []
    indices_by_cluster = {value: np.flatnonzero(clusters == value) for value in unique}
    for _ in range(n_boot):
        drawn = rng.choice(unique, size=unique.size, replace=True)
        subset = np.concatenate([indices_by_cluster[value] for value in drawn])
        stats.append(_rmse(errors[subset]))
    lower = float(np.percentile(stats, 100 * alpha / 2))
    upper = float(np.percentile(stats, 100 * (1 - alpha / 2)))
    return lower, upper


def summarise(rows: Sequence[dict[str, Any]], group_keys: Iterable[str],
              *, bootstrap: bool = True, n_boot: int = 500) -> list[dict[str, Any]]:
    groups: dict[tuple, list[dict[str, Any]]] = {}
    keys = list(group_keys)
    for row in rows:
        key = tuple(row.get(name) for name in keys)
        groups.setdefault(key, []).append(row)

    output = []
    for key, items in sorted(groups.items(), key=lambda pair: tuple(str(v) for v in pair[0])):
        record = {name: value for name, value in zip(keys, key)}
        attempted = len(items)
        valid = [row for row in items if is_valid(row)]
        record["n_attempted"] = attempted
        record["n_valid"] = len(valid)
        record["valid_fraction"] = len(valid) / attempted if attempted else 0.0
        record["failure_rate"] = 1.0 - record["valid_fraction"]

        errors = np.array([float(row["signed_error_mm"]) for row in valid], dtype=float)
        errors = errors[np.isfinite(errors)]
        if errors.size:
            record["bias_mm"] = float(np.mean(errors))
            record["rmse_mm"] = _rmse(errors)
            record["p95_abs_mm"] = _p95_abs(errors)
            clusters = np.array([float(row["Z_gt_mm"]) for row in valid])[: errors.size]
            if bootstrap:
                low, high = bootstrap_rmse_ci(errors, clusters, n_boot=n_boot)
                record["rmse_ci_low_mm"] = low
                record["rmse_ci_high_mm"] = high
        else:
            record["bias_mm"] = None
            record["rmse_mm"] = None
            record["p95_abs_mm"] = None
            record["rmse_ci_low_mm"] = None
            record["rmse_ci_high_mm"] = None

        by_distance: dict[float, list[float]] = {}
        for row in valid:
            by_distance.setdefault(float(row["Z_gt_mm"]), []).append(float(row["signed_error_mm"]))
        stds = [float(np.std(values, ddof=1)) for values in by_distance.values() if len(values) > 1]
        record["repeatability_std_mm"] = float(np.mean(stds)) if stds else None

        times = np.array([float(row.get("runtime_ms", np.nan)) for row in items], dtype=float)
        times = times[np.isfinite(times)]
        record["runtime_median_ms"] = float(np.median(times)) if times.size else None
        record["runtime_p95_ms"] = float(np.percentile(times, 95)) if times.size else None
        record["evidence"] = "SIMULATED / L0"
        output.append(record)
    return output
