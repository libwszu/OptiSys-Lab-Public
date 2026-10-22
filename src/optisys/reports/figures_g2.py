"""G2 figures. Eight core panels; every panel reads from files in the run."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

from optisys.config_g2 import ResolvedG2Config  # noqa: E402

DARK = "#1b1b1b"
GRID = "#d9d9d9"

# CJK fallback: the G3 demo writes Chinese panel titles.  Without this the
# glyphs render as boxes AND U+2212 becomes a missing glyph, which would
# silently corrupt negative tick labels.
plt.rcParams["font.sans-serif"] = [
    "Microsoft YaHei", "SimHei", "Noto Sans SC", "DengXian", "DejaVu Sans",
]
plt.rcParams["font.family"] = "sans-serif"
plt.rcParams["axes.unicode_minus"] = False


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _style(ax, title: str, xlabel: str, ylabel: str) -> None:
    ax.set_title(title, fontsize=10, color=DARK)
    ax.set_xlabel(xlabel, fontsize=8)
    ax.set_ylabel(ylabel, fontsize=8)
    ax.tick_params(labelsize=7)
    ax.grid(True, color=GRID, linewidth=0.6, alpha=0.8)
    ax.set_axisbelow(True)


def build_g2_figures(directory: Path, config: ResolvedG2Config,
                     metrics: dict[str, Any]) -> list[str]:
    figures = directory / "figures"
    figures.mkdir(parents=True, exist_ok=True)
    produced: list[str] = []

    produced += _fig_layout(figures, config)
    produced += _fig_l0_vs_l1(figures, directory)
    produced += _fig_kernels(figures, directory)
    produced += _fig_distortion(figures, directory)
    produced += _fig_distortion(figures, directory)
    produced += _fig_tolerance_tail(figures, directory)
    produced += _fig_candidates(figures, directory, metrics)
    produced += _fig_strategies(figures, directory, metrics)
    return produced


# ---------------------------------------------------------------------------
def _fig_layout(figures: Path, config: ResolvedG2Config) -> list[str]:
    fig, ax = plt.subplots(figsize=(7.2, 3.4), dpi=140)
    B = config.baseline_mm
    z0, z1 = config.z_min_mm, config.z_max_mm
    ax.plot([0], [0], marker="s", color="#1f4e79", markersize=8, label="camera pinhole O")
    ax.plot([B], [0], marker="o", color="#a83232", markersize=7, label="laser exit (B,0)")
    for z in (z0, 0.5 * (z0 + z1), z1):
        x = B - z * np.tan(config.theta_rad)
        ax.plot([B, x], [0, z], color="#a83232", linewidth=0.9, alpha=0.8)
        ax.plot([x], [z], marker="x", color="#a83232", markersize=5)
        ax.plot([0, x], [0, z], color="#1f4e79", linewidth=0.7, linestyle="--", alpha=0.7)
        ax.annotate(f"Z={z:.0f} mm\nX={x:.1f} mm", (x, z), textcoords="offset points",
                    xytext=(6, 4), fontsize=6)
    ax.plot([0, 0], [0, z1 * 0.55], color="#1f4e79", linewidth=1.6)
    ax.set_xlim(-5, B + 12)
    ax.set_ylim(-8, z1 * 0.62)
    _style(ax, "Coplanar layout: pinhole camera + laser baseline (mm)",
           "X [mm]", "Z [mm]")
    ax.legend(fontsize=6, loc="upper right")
    path = figures / "01_optical_layout.png"
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return [path.name]


def _fig_l0_vs_l1(figures: Path, directory: Path) -> list[str]:
    rows = _read_csv(directory / "optics" / "field_distortion.csv")
    if not rows:
        return []
    z = np.array([float(r["Z_mm"]) for r in rows])
    traced = np.array([float(r["u_traced_px"]) for r in rows])
    paraxial = np.array([float(r["u_paraxial_px"]) for r in rows])
    fig, axes = plt.subplots(1, 2, figsize=(8.4, 3.2), dpi=140)
    axes[0].plot(z, traced, "o-", markersize=3, label="traced chief ray (L1)")
    axes[0].plot(z, paraxial, "s--", markersize=3, label="paraxial matrix reference")
    _style(axes[0], "Spot column vs working distance", "Z [mm]", "u [px]")
    axes[0].legend(fontsize=6)
    axes[1].plot(z, traced - paraxial, "o-", markersize=3, color="#a83232")
    _style(axes[1], "Traced minus paraxial (distortion)", "Z [mm]", "difference [px]")
    fig.tight_layout()
    path = figures / "02_l1_vs_paraxial.png"
    fig.savefig(path)
    plt.close(fig)
    return [path.name]


def _fig_kernels(figures: Path, directory: Path) -> list[str]:
    npz_path = directory / "optics" / "psf_or_footprint_examples.npz"
    if not npz_path.is_file():
        return []
    data = np.load(npz_path)
    keys = sorted(k for k in data.files if k.startswith("kernel_"))
    if not keys:
        return []
    fig, axes = plt.subplots(1, len(keys), figsize=(2.6 * len(keys), 2.8), dpi=140)
    if len(keys) == 1:
        axes = np.array([axes])
    for ax, key in zip(axes, keys):
        kernel = data[key]
        ax.imshow(kernel, cmap="magma", origin="lower")
        ax.set_title(key.replace("kernel_", ""), fontsize=8)
        ax.set_xticks([])
        ax.set_yticks([])
    fig.suptitle("L1 kernel: geometric footprint x Airy limit (normalised per window)",
                 fontsize=9)
    fig.tight_layout()
    path = figures / "03_l1_kernels.png"
    fig.savefig(path)
    plt.close(fig)
    return [path.name]


def _fig_distortion(figures: Path, directory: Path) -> list[str]:
    rows = _read_csv(directory / "tolerance" / "oat_samples.csv")
    if not rows:
        return []
    variables = sorted({r["variable"] for r in rows})
    fig, axes = plt.subplots(1, 2, figsize=(8.6, 3.2), dpi=140)
    for variable in variables:
        subset = [r for r in rows if r["variable"] == variable]
        subset.sort(key=lambda r: float(r["sigma_level"]))
        levels = [float(r["sigma_level"]) for r in subset]
        for ax, key in ((axes[0], "rmse_A_mm"), (axes[1], "rmse_B_mm")):
            values = [float(r[key]) if r[key] else np.nan for r in subset]
            ax.plot(levels, values, "o-", markersize=3,
                    label=variable.replace("d_", "").replace("_mm", "").replace("_rad", ""))
    _style(axes[0], "OAT: no recalibration (strategy A)", "perturbation [sigma]",
           "RMSE [mm]")
    _style(axes[1], "OAT: per-unit recalibration (strategy B)", "perturbation [sigma]",
           "RMSE [mm]")
    axes[0].legend(fontsize=6)
    fig.tight_layout()
    path = figures / "04_oat_sensitivity.png"
    fig.savefig(path)
    plt.close(fig)
    return [path.name]


def _fig_tolerance_tail(figures: Path, directory: Path) -> list[str]:
    rows = _read_csv(directory / "independent_validation" / "heldout_assemblies.csv")
    if not rows:
        return []
    fig, axes = plt.subplots(1, 2, figsize=(8.6, 3.0), dpi=140)
    b = np.array([float(r["d_baseline_mm"]) for r in rows])
    th = np.array([float(r["d_theta_deg"]) for r in rows])
    axes[0].hist(b, bins=40, color="#1f4e79", alpha=0.8)
    _style(axes[0], "Assembly draws: baseline offset", "dB [mm]", "count")
    axes[1].hist(th, bins=40, color="#a83232", alpha=0.8)
    _style(axes[1], "Assembly draws: beam tilt", "dtheta [deg]", "count")
    fig.tight_layout()
    path = figures / "05_tolerance_draws.png"
    fig.savefig(path)
    plt.close(fig)
    return [path.name]


def _fig_candidates(figures: Path, directory: Path,
                    metrics: dict[str, Any]) -> list[str]:
    summary_path = directory / "independent_validation" / "summary.json"
    if not summary_path.is_file():
        return []
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    candidates = summary.get("candidates", {})
    if not candidates:
        return []
    names = ["baseline", "nominal", "robust"]
    fig, axes = plt.subplots(1, 3, figsize=(10.0, 3.0), dpi=140)
    for ax, key, label in (
        (axes[0], "rmse_mm", "RMSE [mm]"),
        (axes[1], "p95_abs_mm", "P95 |error| [mm]"),
        (axes[2], "failure_rate", "failure rate"),
    ):
        values = [candidates[n][key] if candidates[n].get(key) is not None else np.nan
                  for n in names]
        ax.bar(names, values, color=["#7f7f7f", "#1f4e79", "#a83232"])
        _style(ax, label, "", label)
    fig.suptitle("Independent final evaluation (strategy A, same assemblies)", fontsize=9)
    fig.tight_layout()
    path = figures / "06_candidate_comparison.png"
    fig.savefig(path)
    plt.close(fig)
    return [path.name]


def _fig_strategies(figures: Path, directory: Path,
                    metrics: dict[str, Any]) -> list[str]:
    summary_path = directory / "independent_validation" / "summary.json"
    if not summary_path.is_file():
        return []
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    names = ["baseline", "nominal", "robust"]
    a = [summary["candidates"][n]["rmse_mm"] for n in names]
    b = [summary["strategy_b"].get(n, {}).get("rmse_mm") for n in names]
    fig, ax = plt.subplots(figsize=(5.6, 3.0), dpi=140)
    width = 0.36
    positions = np.arange(len(names))
    ax.bar(positions - width / 2, a, width, label="A: factory nominal", color="#1f4e79")
    ax.bar(positions + width / 2,
           [v if v is not None else np.nan for v in b], width,
           label="B: per-unit recalibration", color="#a83232")
    ax.set_xticks(positions)
    ax.set_xticklabels(names)
    _style(ax, "Calibration strategy comparison", "", "RMSE [mm]")
    ax.legend(fontsize=7)
    fig.tight_layout()
    path = figures / "07_calibration_strategies.png"
    fig.savefig(path)
    plt.close(fig)
    return [path.name]
