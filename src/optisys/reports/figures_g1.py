"""G1 figures (6-8) with the numeric data used to draw them.

Every figure is labelled SIMULATED / L0; no measured data is implied.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

from optisys.config_g1 import ResolvedG1Config
from optisys.imaging.spot import SpotSpec, capture_fraction, integrated_weights

_COLORS = {"centroid": "#1f77b4", "gaussian_1d": "#d62728", "gaussian_2d": "#2ca02c"}
_NAMES = {"centroid": "centroid", "gaussian_1d": "1-D Gaussian", "gaussian_2d": "2-D robust"}


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _save(fig: plt.Figure, path: Path) -> None:
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor="white")
    plt.close(fig)


def figure_spot(config: ResolvedG1Config, directory: Path) -> Path:
    total = 40_000.0
    spot = SpotSpec((config.cx_px, config.cy_px), config.imaging.sigma_px, total)
    weights = integrated_weights(config.width_px, config.height_px, spot)
    half = 24
    cx, cy = int(round(config.cx_px)), int(round(config.cy_px))
    crop = weights[cy - half:cy + half, cx - half:cx + half]

    u = np.arange(cx - half, cx + half, dtype=float)
    # Continuous *per-pixel* value of the 2-D Gaussian at v = cy, i.e. the
    # same quantity the pixel-integrated samples approximate.  Using the 1-D
    # marginal density here would overstate the peak by sqrt(2*pi)*sigma.
    continuous = total / (2 * np.pi * config.imaging.sigma_px**2) * np.exp(
        -0.5 * ((u - config.cx_px) / config.imaging.sigma_px) ** 2
    )
    discrete = weights[cy, cx - half:cx + half]

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.4))
    image = axes[0].imshow(crop, cmap="viridis", origin="upper",
                           extent=(cx - half - 0.5, cx + half - 0.5,
                                   cy + half - 0.5, cy - half - 0.5))
    axes[0].set_title("Pixel-integrated expected signal [e]  (L0, simulated)")
    axes[0].set_xlabel("u [pixel]")
    axes[0].set_ylabel("v [pixel]")
    fig.colorbar(image, ax=axes[0], fraction=0.046, pad=0.03)

    axes[1].plot(u, continuous, "k-", lw=1.6, label="continuous Gaussian profile")
    axes[1].plot(u, discrete, "o", ms=4, color="#1f77b4", label="pixel-integrated values")
    axes[1].set_xlabel("u [pixel]")
    axes[1].set_ylabel("electrons per pixel")
    axes[1].set_title(f"Total = {total:,.0f} e, capture = {weights.sum()/total:.6f}")
    axes[1].grid(alpha=0.3)
    axes[1].legend(fontsize=8)
    path = directory / "fig1_spot_and_pixel_integration.png"
    _save(fig, path)
    _write_csv(directory / "fig1_spot_and_pixel_integration.csv", [
        {"u_px": float(x), "continuous_profile_e_per_px": float(c),
         "pixel_integrated_e": float(d)}
        for x, c, d in zip(u, continuous, discrete)
    ])
    return path


def figure_capture(config: ResolvedG1Config, directory: Path) -> Path:
    offsets = np.arange(0, 36, 1.0)
    total = 40_000.0
    capture = [
        capture_fraction(
            config.width_px, config.height_px,
            SpotSpec((config.width_px - 6 + offset, config.cy_px),
                     config.imaging.sigma_px, total),
        )
        for offset in offsets
    ]
    fig, ax = plt.subplots(figsize=(7.6, 4.4))
    ax.plot(offsets, capture, "-o", ms=3.5, color="#d62728")
    ax.set_xlabel("spot centre offset beyond u = W-6 [pixel]")
    ax.set_ylabel("capture fraction (signal on chip / total)")
    ax.set_title("Edge clipping: capture decreases, no re-normalisation (L0)")
    ax.grid(alpha=0.3)
    ax.set_ylim(0, 1.05)
    path = directory / "fig2_edge_capture.png"
    _save(fig, path)
    _write_csv(directory / "fig2_edge_capture.csv", [
        {"offset_px": float(o), "capture_fraction": float(c)} for o, c in zip(offsets, capture)
    ])
    return path


def figure_noise(metrics: dict[str, Any], directory: Path) -> Path:
    rows = metrics["v2"]["v2"]
    names = [row["scenario"] for row in rows]
    means = np.array([row["sample_mean"] for row in rows])
    mean_theory = np.array([row["theoretical_mean"] for row in rows])
    mean_ci = np.array([row["mean_ci"] for row in rows])
    variances = np.array([row["sample_variance"] for row in rows])
    var_theory = np.array([row["theoretical_variance"] for row in rows])
    var_low = np.array([row["var_low"] for row in rows])
    var_high = np.array([row["var_high"] for row in rows])

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    x = np.arange(len(names))
    axes[0].errorbar(x, means, yerr=mean_ci, fmt="o", color="#1f77b4", capsize=4, label="sample mean ± 99% CI")
    axes[0].plot(x, mean_theory, "k_", ms=18, mew=2, label="theory")
    axes[0].set_xticks(x, names, rotation=20, ha="right", fontsize=8)
    axes[0].set_ylabel("electrons")
    axes[0].set_title("Mean: 3 × 10,000 pooled samples")
    axes[0].legend(fontsize=8)
    axes[0].grid(alpha=0.3)

    axes[1].errorbar(x, variances, yerr=[variances - var_low, var_high - variances],
                     fmt="s", color="#d62728", capsize=4, label="sample variance, 99% CI")
    axes[1].plot(x, var_theory, "k_", ms=18, mew=2, label="theory")
    axes[1].set_xticks(x, names, rotation=20, ha="right", fontsize=8)
    axes[1].set_ylabel("electrons²")
    axes[1].set_title("Variance: Poisson + read noise")
    axes[1].legend(fontsize=8)
    axes[1].grid(alpha=0.3)
    path = directory / "fig3_noise_statistics.png"
    _save(fig, path)
    _write_csv(directory / "fig3_noise_statistics.csv", [
        {"scenario": row["scenario"], "n": row["n"], "theoretical_mean": row["theoretical_mean"],
         "sample_mean": row["sample_mean"], "mean_ci": row["mean_ci"],
         "theoretical_variance": row["theoretical_variance"],
         "sample_variance": row["sample_variance"], "var_low": row["var_low"],
         "var_high": row["var_high"], "pass": row["pass"]}
        for row in rows
    ])
    return path


def figure_estimators(config: ResolvedG1Config, rows: list[dict[str, Any]],
                      directory: Path, run_dir: Path) -> Path:
    index_path = run_dir / "representative_frames" / "index.json"
    index = json.loads(index_path.read_text(encoding="utf-8"))["frames"]
    entry = next(item for item in index if item["name"] == "valid_strong")
    data = np.load(run_dir / "representative_frames" / entry["file"])
    image = data["image_adu"].astype(float)
    roi = entry["roi"]
    row0, row1, col0, col1 = roi
    crop = image[row0:row1, col0:col1]

    fig, ax = plt.subplots(figsize=(7.4, 5.2))
    ax.imshow(crop, cmap="gray", origin="upper")
    markers = {"centroid": ("o", "#1f77b4"), "gaussian_1d": ("s", "#d62728"),
               "gaussian_2d": ("^", "#2ca02c")}
    output_rows = []
    for name, (marker, color) in markers.items():
        subset = [r for r in rows if r["estimator_name"] == name and r["sample_id"].startswith("G1|strong|0200.00|001")]
        if not subset or subset[0]["u_hat_px"] is None:
            continue
        row = subset[0]
        ax.plot(row["u_hat_px"] - col0, row["v_hat_px"] - row0, marker, ms=9,
                mfc="none", mec=color, mew=1.8,
                label=f"{_NAMES[name]}: u={row['u_hat_px']:.3f}")
        output_rows.append({"estimator": name, "u_hat_px": row["u_hat_px"],
                            "v_hat_px": row["v_hat_px"], "true_u_px": row["u_gt_px"],
                            "error_px": row["u_hat_px"] - row["u_gt_px"]})
    if output_rows:
        ax.legend(fontsize=8, loc="upper right")
    ax.set_title("Three estimators on the same frame (L0 simulated)")
    ax.set_xlabel("column in ROI")
    ax.set_ylabel("row in ROI")
    path = directory / "fig4_estimators_same_frame.png"
    _save(fig, path)
    _write_csv(directory / "fig4_estimators_same_frame.csv", output_rows)
    return path


def figure_calibration(config: ResolvedG1Config, rows: list[dict[str, Any]],
                       calibration: dict[str, Any], directory: Path) -> Path:
    all_medium = [r for r in rows if r["condition_id"] == "medium" and r["u_hat_px"] is not None]
    subset = [r for r in all_medium if r["estimator_name"] == "gaussian_2d"]
    fit = calibration["fits"].get("gaussian_2d", {})
    a, b = fit.get("a_px_mm"), fit.get("b_px")

    fig, axes = plt.subplots(1, 2, figsize=(11, 4.3))
    marker_by_split = {"calib": ("o", "#1f77b4"), "validation": ("s", "#ff7f0e"), "test": ("^", "#d62728")}
    for split_name, (marker, color) in marker_by_split.items():
        points = [row for row in subset if row["dataset_split"] == split_name]
        axes[0].plot([p["Z_gt_mm"] for p in points], [p["u_hat_px"] for p in points],
                     marker, ms=4, color=color, ls="none", label=split_name)
    z_curve = np.linspace(config.z_min_mm, config.z_max_mm, 200)
    if a and b:
        axes[0].plot(z_curve, a / z_curve + b, "k-", lw=1.2,
                     label=f"fit: a/Z + b (a={a:.1f}, b={b:.2f})")
    axes[0].set_xlabel("Z [mm]")
    axes[0].set_ylabel("u_hat [pixel]")
    axes[0].set_title("System calibration (medium condition) — 2-D estimator")
    axes[0].legend(fontsize=7)
    axes[0].grid(alpha=0.3)

    residual_rows = []
    for name in ("centroid", "gaussian_1d", "gaussian_2d"):
        point_rows = [r for r in all_medium if r["estimator_name"] == name]
        fit_name = calibration["fits"].get(name, {})
        if not point_rows or not fit_name.get("a_px_mm"):
            continue
        errors = [r["u_hat_px"] - (fit_name["a_px_mm"] / r["Z_gt_mm"] + fit_name["b_px"])
                  for r in point_rows]
        axes[1].plot([r["Z_gt_mm"] for r in point_rows], errors, "o", ms=3,
                     color=_COLORS[name], label=_NAMES[name])
        residual_rows.extend({"estimator": name, "Z_mm": r["Z_gt_mm"], "residual_px": e}
                             for r, e in zip(point_rows, errors))
    axes[1].axhline(0, color="k", lw=0.8)
    if not residual_rows:
        axes[1].text(0.5, 0.5, "no calibration data in this run", ha="center", va="center",
                     transform=axes[1].transAxes, fontsize=9, color="#666666")
    axes[1].set_xlabel("Z [mm]")
    axes[1].set_ylabel("u residual [pixel]")
    axes[1].set_title("Calibration residuals")
    if residual_rows:
        axes[1].legend(fontsize=7)
    axes[1].grid(alpha=0.3)
    path = directory / "fig5_calibration_and_residuals.png"
    _save(fig, path)
    _write_csv(directory / "fig5_calibration_residuals.csv", residual_rows)
    return path


def figure_error_by_distance(metrics: dict[str, Any], directory: Path) -> Path:
    rows = metrics["distance_metrics"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.3))
    for name in ("centroid", "gaussian_1d", "gaussian_2d"):
        subset = [r for r in rows if r["estimator_name"] == name and r["condition_id"] == "medium"]
        subset.sort(key=lambda r: r["Z_gt_mm"])
        z = [r["Z_gt_mm"] for r in subset]
        rmse = [r["rmse_mm"] if r["rmse_mm"] is not None else np.nan for r in subset]
        p95 = [r["p95_abs_mm"] if r["p95_abs_mm"] is not None else np.nan for r in subset]
        axes[0].plot(z, rmse, "-o", ms=3, color=_COLORS[name], label=_NAMES[name])
        axes[1].plot(z, p95, "-o", ms=3, color=_COLORS[name], label=_NAMES[name])
    for ax, title in zip(axes, ("RMSE vs distance (medium)", "P95 |error| vs distance (medium)")):
        ax.set_xlabel("Z [mm]")
        ax.set_ylabel("mm")
        ax.set_title(title + " — SIMULATED / L0")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)
    path = directory / "fig6_error_vs_distance.png"
    _save(fig, path)
    data = [
        {"estimator": r["estimator_name"], "condition": r["condition_id"], "Z_mm": r["Z_gt_mm"],
         "rmse_mm": r["rmse_mm"], "p95_mm": r["p95_abs_mm"], "n_valid": r["n_valid"],
         "n_attempted": r["n_attempted"]}
        for r in rows
    ]
    _write_csv(directory / "fig6_error_vs_distance.csv", data)
    return path


def figure_failure_and_timing(metrics: dict[str, Any], directory: Path) -> Path:
    failures = metrics["failures"]
    conditions = sorted({row["condition_id"] for row in failures})
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.2))
    width = 0.25
    for index, name in enumerate(("centroid", "gaussian_1d", "gaussian_2d")):
        rates = []
        for condition in conditions:
            match = [r for r in failures if r["estimator_name"] == name and r["condition_id"] == condition]
            rates.append(match[0]["failure_rate"] if match else np.nan)
        axes[0].bar(np.arange(len(conditions)) + (index - 1) * width, rates, width,
                    color=_COLORS[name], label=_NAMES[name])
    axes[0].set_xticks(np.arange(len(conditions)), conditions)
    axes[0].set_ylabel("failure rate (all attempted frames)")
    axes[0].set_title("Failure rate by condition")
    axes[0].legend(fontsize=8)
    axes[0].grid(axis="y", alpha=0.3)

    summary = metrics["summaries"]["by_estimator"]
    names = [row["estimator_name"] for row in summary]
    medians = [row["runtime_median_ms"] or 0 for row in summary]
    p95 = [row["runtime_p95_ms"] or 0 for row in summary]
    x = np.arange(len(names))
    axes[1].bar(x - 0.18, medians, 0.36, label="median", color="#4c72b0")
    axes[1].bar(x + 0.18, p95, 0.36, label="P95", color="#dd8452")
    axes[1].set_xticks(x, [_NAMES.get(n, n) for n in names], fontsize=8)
    axes[1].set_ylabel("ms per estimate")
    axes[1].set_title("Estimator runtime (measured)")
    axes[1].legend(fontsize=8)
    axes[1].grid(axis="y", alpha=0.3)
    path = directory / "fig7_failure_and_timing.png"
    _save(fig, path)
    _write_csv(directory / "fig7_failure_and_timing.csv", [
        {"group": "failure", **row} for row in failures
    ] + [
        {"group": "timing", "estimator_name": row["estimator_name"],
         "runtime_median_ms": row["runtime_median_ms"], "runtime_p95_ms": row["runtime_p95_ms"]}
        for row in summary
    ])
    return path


def build_g1_figures(run_dir: Path, config: ResolvedG1Config, metrics: dict[str, Any],
                     rows: list[dict[str, Any]], calibration: dict[str, Any]) -> list[Path]:
    directory = Path(run_dir) / "figures"
    directory.mkdir(parents=True, exist_ok=True)
    return [
        figure_spot(config, directory),
        figure_capture(config, directory),
        figure_noise(metrics, directory),
        figure_estimators(config, rows, directory, Path(run_dir)),
        figure_calibration(config, rows, calibration, directory),
        figure_error_by_distance(metrics, directory),
        figure_failure_and_timing(metrics, directory),
    ]
