"""Auditable target-plane metrics for weighted geometric rays."""

from __future__ import annotations

from typing import Any

import numpy as np

from optisys.optics.pump_beamline import BeamlineTrace


def _weighted_quantile(values: np.ndarray, weights: np.ndarray, q: float) -> float | None:
    if values.size == 0 or weights.size != values.size or np.sum(weights) <= 0.0:
        return None
    order = np.argsort(values, kind="mergesort")
    v, w = values[order], weights[order]
    cumulative = np.cumsum(w, dtype=np.float64)
    threshold = q * cumulative[-1]
    index = int(np.searchsorted(cumulative, threshold, side="left"))
    return float(v[min(index, len(v) - 1)])


def target_plane_metrics(trace: BeamlineTrace, *, grid_size: int = 101) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    """Compute source-denominated transmission and conditional spot metrics."""

    if isinstance(grid_size, bool) or int(grid_size) != grid_size or grid_size < 3:
        raise ValueError("grid_size must be an integer >= 3")
    source_total = float(trace.ledger["source_weight_total"])
    if source_total <= 0.0:
        return {"status": "NOT_EVALUABLE", "source_weight_total": source_total,
                "geometric_transmission_fraction": None, "rms_radius_mm": None,
                "r80_mm": None, "r90_mm": None}, {}
    good = trace.status == "OK"
    x, y, w = trace.target_x_mm[good], trace.target_y_mm[good], trace.weight[good]
    transmitted = float(np.sum(w, dtype=np.float64))
    stats: dict[str, Any] = {
        "status": "OK" if transmitted > 0.0 else "NOT_EVALUABLE",
        "n_source": int(trace.ray_id.size),
        "n_transmitted_to_target": int(np.count_nonzero(good)),
        **trace.ledger,
        "geometric_transmission_fraction": transmitted / source_total,
        "transmission_denominator": "all source ray weights",
        "spot_conditioning": "transmitted weight inside target active circle",
        "spot_reference_center": "transmitted-weight centroid",
        "units": {"position": "mm", "radius": "mm", "density": "weight_fraction/mm^2"},
    }
    target_radius = float(trace.metadata.get("target_radius_mm", np.nan))
    # Trace metadata may be absent for imported traces; the grid extent is set
    # from the actual target points, while the orchestrator provides radius.
    if transmitted <= 0.0:
        stats.update({"centroid_x_mm": None, "centroid_y_mm": None,
                      "rms_radius_mm": None, "r80_mm": None, "r90_mm": None,
                      "density_status": "NOT_EVALUABLE"})
        return stats, {}

    cx = float(np.sum(x * w, dtype=np.float64) / transmitted)
    cy = float(np.sum(y * w, dtype=np.float64) / transmitted)
    radius = np.hypot(x - cx, y - cy)
    rms = float(np.sqrt(np.sum(w * radius * radius, dtype=np.float64) / transmitted))
    r80 = _weighted_quantile(radius, w, 0.80)
    r90 = _weighted_quantile(radius, w, 0.90)
    stats.update({"centroid_x_mm": cx, "centroid_y_mm": cy,
                  "rms_radius_mm": rms, "r80_mm": r80, "r90_mm": r90,
                  "max_radius_from_centroid_mm": float(radius.max()),
                  "density_status": "OK"})

    # Extent is the target circle; infer it conservatively from recorded target
    # positions and the declared active radius in metadata if supplied.
    extent = target_radius if np.isfinite(target_radius) and target_radius > 0 else max(
        float(np.max(np.abs(np.r_[x, y]))) * 1.05, 1e-6)
    edges = np.linspace(-extent, extent, int(grid_size) + 1)
    hist, x_edges, y_edges = np.histogram2d(x, y, bins=(edges, edges), weights=w)
    cell_area = float((x_edges[1] - x_edges[0]) * (y_edges[1] - y_edges[0]))
    density_input = hist / (source_total * cell_area)
    density_conditional = hist / (transmitted * cell_area)
    density = {
        "weight_histogram": hist,
        "x_edges_mm": x_edges,
        "y_edges_mm": y_edges,
        "cell_area_mm2": np.asarray(cell_area),
        "weight_fraction_per_mm2_input_denominator": density_input,
        "conditional_density_per_mm2_transmitted": density_conditional,
    }
    stats["density_integral_input_denominator"] = float(np.sum(density_input) * cell_area)
    stats["density_integral_conditional"] = float(np.sum(density_conditional) * cell_area)
    stats["density_normalization"] = "raw cell weight / cell area; input and conditional variants"
    stats["density_grid_shape"] = [int(grid_size), int(grid_size)]
    return stats, density


def source_distribution_summary(bundle, *, core_radius_mm: float, theta_max_rad: float) -> dict[str, Any]:
    pos_r = np.hypot(bundle.origin_mm[:, 0], bundle.origin_mm[:, 1])
    theta = np.arccos(np.clip(bundle.direction[:, 2], -1.0, 1.0))
    radial_u = (pos_r / core_radius_mm) ** 2 if core_radius_mm > 0 else np.zeros_like(pos_r)
    if theta_max_rad > 0:
        if "edge_biased_sin_theta" in bundle.distribution_id:
            angular_u = (np.sin(theta) / np.sin(theta_max_rad)) ** 3
            angular_measure = "q_cubed_cdf_uniformized_for_edge_biased_distribution"
        else:
            angular_u = (1.0 - np.cos(theta)) / (1.0 - np.cos(theta_max_rad))
            angular_measure = "cos_theta_cdf_uniformized_for_uniform_solid_angle"
    else:
        angular_u = np.zeros_like(theta)
        angular_measure = "degenerate_zero_na"
    def uniform_ks_d(sample: np.ndarray) -> float:
        s = np.sort(sample)
        n = len(s)
        if n == 0:
            return float("nan")
        upper = np.arange(1, n + 1) / n
        lower = np.arange(0, n) / n
        return float(max(np.max(upper - s), np.max(s - lower)))
    return {
        "n_rays": bundle.n_rays,
        "seed": bundle.seed,
        "distribution_id": bundle.distribution_id,
        "source_weight_total": bundle.total_weight,
        "position_radius_mean_mm": float(np.mean(pos_r)),
        "position_radius_max_mm": float(np.max(pos_r)),
        "position_r2_over_R2_mean": float(np.mean(radial_u)) if core_radius_mm > 0 else None,
        "position_r2_over_R2_ks_d": uniform_ks_d(radial_u) if core_radius_mm > 0 else None,
        "theta_mean_deg": float(np.rad2deg(np.mean(theta))),
        "theta_median_deg": float(np.rad2deg(np.median(theta))),
        "theta_max_sample_deg": float(np.rad2deg(np.max(theta))),
        "theta_max_declared_deg": float(np.rad2deg(theta_max_rad)),
        "angular_cdf_test": angular_measure,
        "angular_cdf_ks_d": uniform_ks_d(angular_u) if theta_max_rad > 0 else None,
        "evidence": "ASSUMED_SIMULATED",
    }
