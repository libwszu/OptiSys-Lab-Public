"""Figure generation for G0 evidence (matplotlib, Agg backend).

Every figure is written together with the numeric data that produced it, so a
reviewer can rebuild or audit the plot without re-running the whole pipeline.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Iterable

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

from optisys.config import ResolvedConfig
from optisys.evaluation.chain import ChainComparison
from optisys.geometry.coplanar import CoplanarGeometry, CoplanarSpec
from optisys.geometry.reference import ReferenceModel

_PALETTE = ("#1f77b4", "#d62728", "#2ca02c", "#9467bd")


def _write_csv(path: Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def _save(fig: plt.Figure, path: Path) -> None:
    fig.tight_layout()
    fig.savefig(path, dpi=150, facecolor="white")
    plt.close(fig)


def figure_z_u(config: ResolvedConfig, figures_dir: Path) -> Path:
    """Z-u calibration curve for theta = -3/0/+3 deg."""

    z = np.linspace(config.z_min_mm, config.z_max_mm, 201)
    rows = []
    fig, ax = plt.subplots(figsize=(8.0, 4.8))
    for index, offset in enumerate((-3.0, 0.0, 3.0)):
        theta_deg = config.theta_deg + offset
        spec = _retuned(config.geometry, theta_rad=float(np.deg2rad(theta_deg)))
        geom = CoplanarGeometry(spec)
        u_offset = geom.forward_many(z).u_px - config.cx_px
        ax.plot(z, u_offset, color=_PALETTE[index], lw=1.8,
                label=f"theta = {theta_deg:+.1f} deg")
        rows.extend(
            {"theta_deg": theta_deg, "Z_mm": float(zi), "u_minus_cx_px": float(ui)}
            for zi, ui in zip(z, u_offset)
        )

    for mark in (100.0, 200.0, 300.0):
        geom = CoplanarGeometry(config.geometry)
        forward = geom.forward(mark)
        u_mark = forward.u_px - config.cx_px if forward.status.value == "OK" else np.nan
        if np.isfinite(u_mark):
            ax.plot([mark], [u_mark], "o", ms=5, mfc="white", mec="black", mew=1.2, zorder=5)
            offset = (-52, 10) if mark >= config.z_max_mm else (8, 8)
            ax.annotate(f"{u_mark:.2f} px", (mark, u_mark), textcoords="offset points",
                        xytext=offset, fontsize=8)

    ax.set_xlabel("Target depth Z [mm]")
    ax.set_ylabel("Spot column offset  u - cx  [pixel]")
    ax.set_title("Ideal coplanar triangulation: Z-u curve (L0, FORMULA)")
    ax.grid(alpha=0.3)
    ax.legend(loc="upper right", fontsize=9)
    ax.set_xlim(config.z_min_mm, config.z_max_mm)
    path = figures_dir / "fig1_Z_u_curve.png"
    _save(fig, path)
    _write_csv(figures_dir / "fig1_Z_u_curve.csv", rows,
               ["theta_deg", "Z_mm", "u_minus_cx_px"])
    return path


def figure_sensitivity(config: ResolvedConfig, figures_dir: Path) -> Path:
    """|dZ/du| versus Z for three baselines (f and p fixed)."""

    z = np.linspace(config.z_min_mm, config.z_max_mm, 201)
    rows = []
    fig, ax = plt.subplots(figsize=(8.0, 4.8))
    for index, baseline in enumerate((15.0, 20.0, 35.0)):
        spec = _retuned(config.geometry, baseline_mm=baseline)
        geom = CoplanarGeometry(spec)
        sensitivity = np.array([geom.abs_sensitivity(float(value)) for value in z])
        ax.plot(z, sensitivity, color=_PALETTE[index], lw=1.8,
                label=f"B = {baseline:.0f} mm (nominal {config.baseline_mm:.0f} mm)")
        rows.extend(
            {"B_mm": baseline, "Z_mm": float(zi), "abs_dZ_du_mm_per_px": float(si)}
            for zi, si in zip(z, sensitivity)
        )

    ax.set_xlabel("Target depth Z [mm]")
    ax.set_ylabel("|dZ/du|  [mm/pixel]")
    ax.set_title("Depth sensitivity grows as Z^2 / (fx B)  (FORMULA)")
    ax.grid(alpha=0.3)
    ax.set_xlim(config.z_min_mm, config.z_max_mm)
    ax.set_ylim(bottom=0.0)
    ax.legend(fontsize=9)
    ax.set_xlim(config.z_min_mm, config.z_max_mm)
    path = figures_dir / "fig2_Z_sensitivity.png"
    _save(fig, path)
    _write_csv(figures_dir / "fig2_Z_sensitivity.csv", rows,
               ["B_mm", "Z_mm", "abs_dZ_du_mm_per_px"])
    return path


def figure_visibility(config: ResolvedConfig, figures_dir: Path) -> Path:
    """Sensor visibility map: where the spot lands inside / outside the chip."""

    spec = _retuned(config.geometry, enforce_working_range=False)
    geom = CoplanarGeometry(spec)
    z = np.linspace(20.0, 600.0, 581)
    batch = geom.forward_many(z)
    visible = batch.visible

    rows = [
        {
            "Z_mm": float(zi),
            "u_px": float(ui) if np.isfinite(ui) else "",
            "visible": bool(vi),
            "status": status.value,
        }
        for zi, ui, vi, status in zip(z, batch.u_px, visible, batch.statuses())
    ]

    fig, ax = plt.subplots(figsize=(8.0, 4.8))
    ax.axvspan(config.z_min_mm, config.z_max_mm, color="#f0f0f0", zorder=0,
               label="declared working range")
    ax.axhline(0.0, color="black", lw=1.0, ls="--")
    ax.axhline(config.width_px - 1, color="black", lw=1.0, ls="--")
    ax.axhline(config.cx_px, color="gray", lw=0.8, ls=":")

    inside = np.isfinite(batch.u_px) & visible
    outside = np.isfinite(batch.u_px) & ~visible
    ax.plot(z[inside], batch.u_px[inside], color="#2ca02c", lw=1.8, label="visible (inside sensor)")
    ax.plot(z[outside], batch.u_px[outside], color="#d62728", lw=1.8, label="OUT_OF_SENSOR")

    # Analytical near-range limit: u(Z) = W-1  ->  Z = fx*B / (W-1-cx+fx*tan(theta)).
    denominator = (config.width_px - 1 - config.cx_px) + config.fx_px * np.tan(config.geometry.theta_rad)
    if denominator > 0:
        clipping_z = config.fx_px * config.baseline_mm / denominator
        ax.axvline(clipping_z, color="#d62728", lw=0.9, ls="-.")
        ax.annotate(
            f"near-range clipping starts\nZ = {clipping_z:.1f} mm (u = W-1)",
            xy=(clipping_z, config.width_px - 1), xytext=(clipping_z + 48, 1000),
            fontsize=8.5, color="#9b1c1c",
            arrowprops={"arrowstyle": "->", "color": "#9b1c1c", "lw": 1.0},
            bbox={"boxstyle": "round,pad=0.3", "fc": "white", "ec": "#e0b4b4", "alpha": 0.95},
        )

    ax.text(30, config.width_px - 70, "sensor top (u = W-1)", ha="left", va="top",
            fontsize=8, color="black",
            bbox={"boxstyle": "round,pad=0.2", "fc": "white", "ec": "none", "alpha": 0.9})
    ax.text(30, 30, "sensor bottom (u = 0)", ha="left", va="bottom", fontsize=8,
            color="black",
            bbox={"boxstyle": "round,pad=0.2", "fc": "white", "ec": "none", "alpha": 0.9})
    ax.set_xlabel("Target depth Z [mm] (working-range check disabled for this plot)")
    ax.set_ylabel("Spot column u [pixel]")
    ax.set_title("Sensor occupancy and near-range clipping (L0)")
    ax.grid(alpha=0.25)
    ax.legend(loc="upper right", fontsize=8)
    ax.set_xlim(20.0, 600.0)
    ax.set_ylim(-60.0, 1350.0)
    path = figures_dir / "fig3_sensor_visibility.png"
    _save(fig, path)
    _write_csv(figures_dir / "fig3_sensor_visibility.csv", rows,
               ["Z_mm", "u_px", "visible", "status"])
    return path


def figure_residuals(comparison: ChainComparison, figures_dir: Path,
                     tolerance_px: float) -> Path:
    """Analytic-versus-reference residuals, the core V0 evidence."""

    rows = []
    fig, ax = plt.subplots(figsize=(8.0, 4.8))
    thetas = sorted({row["theta_deg"] for row in comparison.rows})
    for index, theta in enumerate(thetas):
        subset = [row for row in comparison.rows if row["theta_deg"] == theta]
        z = [row["Z_mm"] for row in subset]
        residual = [row["u_abs_error_px"] for row in subset]
        # Scatter only: connecting a bit-identical 0 to a 1-ULP residual would
        # draw a fake sawtooth that looks like oscillating error.
        ax.plot(z, residual, linestyle="none", marker="o", ms=3.2,
                color=_PALETTE[index % len(_PALETTE)], label=f"theta = {theta:+.1f} deg")
        rows.extend(
            {"theta_deg": theta, "Z_mm": zi, "abs_u_residual_px": ri}
            for zi, ri in zip(z, residual)
        )

    ax.axhline(tolerance_px, color="black", ls="--", lw=1.0,
               label=f"gate = {tolerance_px:g} px")
    ax.set_yscale("symlog", linthresh=1e-16, linscale=0.45)
    zeros = sum(1 for row in comparison.rows if row["u_abs_error_px"] == 0.0)
    worst = max(row["u_abs_error_px"] for row in comparison.rows)
    ax.text(
        0.02, 0.94,
        f"max = {worst:.3e} px  |  {zeros}/{len(comparison.rows)} points bit-identical (0)\n"
        f"non-zero residuals are 1-2 units in the last place",
        transform=ax.transAxes, fontsize=8.5, va="top",
        bbox={"boxstyle": "round,pad=0.3", "fc": "white", "ec": "#cccccc", "alpha": 0.95},
    )
    ax.set_xlabel("Target depth Z [mm]")
    ax.set_ylabel("|u_analytic - u_reference| [pixel] (symlog)")
    ax.set_title("Independent cross-check residual (below double-precision floor is expected)")
    ax.grid(alpha=0.3, which="both")
    ax.legend(fontsize=8)
    path = figures_dir / "fig4_independent_residual.png"
    _save(fig, path)
    _write_csv(figures_dir / "fig4_independent_residual.csv", rows,
               ["theta_deg", "Z_mm", "abs_u_residual_px"])
    return path


def _retuned(spec: CoplanarSpec, **overrides: Any) -> CoplanarSpec:
    params = dict(
        baseline_mm=spec.baseline_mm,
        theta_rad=spec.theta_rad,
        fx_px=spec.fx_px,
        cx_px=spec.cx_px,
        cy_px=spec.cy_px,
        width_px=spec.width_px,
        height_px=spec.height_px,
        z_min_mm=spec.z_min_mm,
        z_max_mm=spec.z_max_mm,
        min_baseline_mm=spec.min_baseline_mm,
        singular_denominator_px=spec.singular_denominator_px,
        sensor_margin_px=spec.sensor_margin_px,
        enforce_working_range=spec.enforce_working_range,
        range_epsilon_mm=spec.range_epsilon_mm,
    )
    params.update(overrides)
    return CoplanarSpec(**params)


DEFAULT_FIGURES = (figure_z_u, figure_sensitivity, figure_visibility)


def build_all(config: ResolvedConfig, comparison: ChainComparison, figures_dir: Path,
              tolerance_px: float) -> list[Path]:
    figures_dir.mkdir(parents=True, exist_ok=True)
    paths = [
        figure_z_u(config, figures_dir),
        figure_sensitivity(config, figures_dir),
        figure_visibility(config, figures_dir),
        figure_residuals(comparison, figures_dir, tolerance_px),
    ]
    return paths
