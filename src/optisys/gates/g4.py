"""G4 976 nm multimode fiber pump case: P0 analysis and qualified P1 trace."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import platform
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import yaml

from optisys.config_g4 import (
    Pump976Config,
    PumpConfigError,
    PumpToleranceConfig,
    load_pump976_config,
    load_pump_tolerance_config,
)
from optisys.evaluation.pump_metrics import source_distribution_summary, target_plane_metrics
from optisys.optics.pump_beamline import BeamlineConfig, BeamlineTrace, ThinLensPlane
from optisys.optics.pump_beamline import trace_thin_lens, trace_thin_lens_scalar_reference
from optisys.optics.pump_optiland import OptilandPumpTracer
from optisys.runtime.environment import collect_environment
from optisys.sources.multimode_fiber import RayBundle, sample_multimode_fiber

PREREG_HASHES_PATH = Path("docs/g4/G4_FREEZE_HASHES.json")
FROZEN_HASH_MANIFEST_SHA256 = "de1a77448ea6879d8a60fdba1f276f904b83f2ceeedf17ac52127600f4eb18b3"
STAGE_TIMEOUT_S = 180.0
RUN_TIMEOUT_S = 300.0
CHECKPOINT_CHUNK_ASSEMBLIES = 10


class G4RunError(RuntimeError):
    """A G4 run cannot safely continue with its current evidence state."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _git_commit(root: Path) -> str:
    try:
        result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root,
                                capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return "NO_COMMIT"
    return result.stdout.strip() if result.returncode == 0 else "NO_COMMIT"


def _git_dirty(root: Path) -> bool | str:
    try:
        result = subprocess.run(["git", "status", "--porcelain=v1"], cwd=root,
                                capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return "UNKNOWN"
    return bool(result.stdout.strip()) if result.returncode == 0 else "UNKNOWN"


def _csv_write(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _csv_read(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _json_write(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                    encoding="utf-8")


def _json_read(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _run_id(root: Path, config_hash: str) -> str:
    stamp = datetime.now(timezone.utc).astimezone().strftime("%Y%m%d_%H%M%S")
    return f"{stamp}_G4_{config_hash[:8]}_{uuid.uuid4().hex[:4]}"


def _bundle(config: Pump976Config, n_rays: int, seed: int, *,
            angular_distribution: str | None = None,
            core_diameter_mm: float | None = None) -> RayBundle:
    return sample_multimode_fiber(
        n_rays=n_rays,
        core_diameter_mm=(config.core_diameter_mm if core_diameter_mm is None else core_diameter_mm),
        numerical_aperture=config.numerical_aperture,
        output_index=config.output_index,
        seed=seed,
        angular_distribution=angular_distribution or config.angular_distribution,
    )


def _source_row(bundle: RayBundle) -> dict[str, Any]:
    radius = float(bundle.metadata["core_radius_mm"])
    theta_max = float(bundle.metadata["theta_max_rad"])
    return source_distribution_summary(bundle, core_radius_mm=radius, theta_max_rad=theta_max)


def _ray_count_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault((str(row["design_id"]), int(row["n_rays"])), []).append(row)
    ci_rows = []
    for (design, n_rays), group in sorted(grouped.items()):
        for metric in ("geometric_transmission_fraction", "r80_mm", "r90_mm"):
            values = np.asarray([float(item[metric]) for item in group if item.get(metric) is not None], dtype=float)
            if not values.size:
                ci_rows.append({"design_id": design, "n_rays": n_rays, "metric": metric,
                                "n_seeds": 0, "mean": None, "ci95_low": None, "ci95_high": None})
                continue
            mean = float(np.mean(values))
            half = float(4.303 * np.std(values, ddof=1) / np.sqrt(values.size)) if values.size > 1 else None
            ci_rows.append({"design_id": design, "n_rays": n_rays, "metric": metric,
                            "n_seeds": int(values.size), "mean": mean,
                            "ci95_low": max(0.0, mean - half) if half is not None else None,
                            "ci95_high": mean + half if half is not None else None,
                            "ci_method": "t interval, df=2 for 3 independent seeds"})
    relative_changes = {}
    for design in sorted({str(row["design_id"]) for row in rows}):
        medians = {}
        for n_rays in (8000, 32000):
            values = [float(r["r80_mm"]) for r in rows if r["design_id"] == design
                      and int(r["n_rays"]) == n_rays and r.get("r80_mm") is not None]
            medians[n_rays] = float(np.median(values)) if values else None
        if medians[8000] and medians[32000] is not None:
            relative_changes[design] = abs(medians[32000] - medians[8000]) / medians[8000]
        else:
            relative_changes[design] = None
    valid = all(v is not None and v <= 0.05 for v in relative_changes.values())
    return {"status": "PASS" if valid else "NOT_CONVERGED",
            "criterion": "median r80 relative change from 8k to 32k <= 5%",
            "relative_change_8k_to_32k": relative_changes,
            "confidence_interval_rows": ci_rows,
            "note": "Sampling convergence is numerical uncertainty only; it does not increase physical model accuracy."}


def _flatten_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in metrics.items() if not isinstance(v, (dict, list, tuple))}


def _trace_p1_as_beamline(bundle: RayBundle, result, beamline: BeamlineConfig) -> BeamlineTrace:
    n = bundle.n_rays
    status = np.full(n, "TRACE_FAILED", dtype=object)
    blocked = np.asarray(result.blocked_at, dtype=object).copy()
    status[blocked == "L1"] = "APERTURE_BLOCKED"
    status[blocked == "L2"] = "APERTURE_BLOCKED"
    status[blocked == "TARGET"] = "OUTSIDE_TARGET"
    status[blocked == "TRACE"] = "TRACE_FAILED"
    status[result.valid] = "OK"
    nan = np.full(n, np.nan, dtype=float)
    return BeamlineTrace(
        ray_id=bundle.ray_id.copy(), weight=bundle.weight.copy(), status=status,
        blocked_at=blocked, l1_x_mm=nan.copy(), l1_y_mm=nan.copy(),
        l2_x_mm=nan.copy(), l2_y_mm=nan.copy(),
        target_x_mm=np.asarray(result.x_mm, dtype=float).copy(),
        target_y_mm=np.asarray(result.y_mm, dtype=float).copy(),
        target_z_mm=np.full(n, beamline.target_z_mm),
        direction_out=np.full((n, 3), np.nan), ledger=dict(result.ledger),
        metadata={"model_level": "P1_OPTILAND_0.6.3_QUALIFIED",
                  "target_radius_mm": beamline.target_radius_mm,
                  "evidence": "SIMULATED", "normalization": "all source weights"},
    )


def _metric_row(design_id: str, backend: str, angular_case: str,
                metrics: dict[str, Any]) -> dict[str, Any]:
    return {"design_id": design_id, "backend": backend, "angular_case": angular_case,
            **_flatten_metrics(metrics)}


def _density_key(design: str, backend: str, angular_case: str) -> str:
    angle = angular_case.replace(".", "p")
    return f"{design}__{backend}__NA_{angle}"


def _oat_rows(config: Pump976Config, source: RayBundle) -> list[dict[str, Any]]:
    base = config.beamline
    rows: list[dict[str, Any]] = []
    factors: list[tuple[str, str, Iterable[float], Any]] = [
        ("l1_focal_length_mm", "mm", (15.0, 20.0, 25.0, 35.0, 45.0),
         lambda b, v: replace(b, l1=replace(b.l1, focal_length_mm=v))),
        ("l2_axial_position_mm", "mm", (123.0, 124.0, 125.0, 126.0, 127.0),
         lambda b, v: replace(b, l2=replace(b.l2, z_mm=v))),
        ("l1_aperture_diameter_mm", "mm", (8.0, 10.0, 12.0, 14.0, 16.0),
         lambda b, v: replace(b, l1=replace(b.l1, aperture_diameter_mm=v))),
        ("l1_decenter_x_mm", "mm", (-0.2, -0.1, 0.0, 0.1, 0.2),
         lambda b, v: replace(b, l1=replace(b.l1, decenter_x_mm=v))),
        ("l2_tilt_y_deg", "deg", (-0.5, -0.25, 0.0, 0.25, 0.5),
         lambda b, v: replace(b, l2=replace(b.l2, tilt_y_rad=float(np.deg2rad(v))))),
        ("l2_aperture_diameter_mm", "mm", (8.0, 10.0, 12.0, 14.0, 16.0),
         lambda b, v: replace(b, l2=replace(b.l2, aperture_diameter_mm=v))),
    ]
    for name, unit, values, transform in factors:
        for index, value in enumerate(values):
            try:
                varied = transform(base, float(value))
                trace = trace_thin_lens(source, varied)
                metrics, _ = target_plane_metrics(trace)
                row = {"factor": name, "level_index": index, "value": value,
                       "unit": unit, "design_id": config.design_id,
                       "seed": source.seed, "n_rays": source.n_rays,
                       "status": metrics.get("status", "UNKNOWN"),
                       "geometric_transmission_fraction": metrics.get("geometric_transmission_fraction"),
                       "rms_radius_mm": metrics.get("rms_radius_mm"),
                       "r80_mm": metrics.get("r80_mm"), "r90_mm": metrics.get("r90_mm"),
                       "l1_blocked_weight": trace.ledger.get("l1_blocked_weight"),
                       "l2_blocked_weight": trace.ledger.get("l2_blocked_weight"),
                       "outside_target_weight": trace.ledger.get("outside_target_weight"),
                       "model_level": "P0_ANALYTIC", "evidence": "SIMULATED"}
            except (ValueError, FloatingPointError) as exc:
                row = {"factor": name, "level_index": index, "value": value,
                       "unit": unit, "design_id": config.design_id,
                       "seed": source.seed, "n_rays": source.n_rays,
                       "status": "INVALID_GEOMETRY", "failure_reason": str(exc),
                       "geometric_transmission_fraction": None, "rms_radius_mm": None,
                       "r80_mm": None, "r90_mm": None, "model_level": "P0_ANALYTIC",
                       "evidence": "SIMULATED"}
            rows.append(row)
    return rows


def _draw_perturbations(tol: PumpToleranceConfig, n: int, seed: int) -> list[dict[str, float]]:
    rng = np.random.default_rng(seed)
    out = []
    names = list(tol.perturbations)
    draws = {name: rng.uniform(float(tol.perturbations[name]["lower"]),
                               float(tol.perturbations[name]["upper"]), n)
             for name in names}
    for i in range(n):
        out.append({name: float(draws[name][i]) for name in names})
    return out


def _perturbed_beamline(config: Pump976Config, p: dict[str, float]) -> BeamlineConfig:
    b = config.beamline
    l1 = replace(
        b.l1,
        focal_length_mm=b.l1.focal_length_mm * (1.0 + p["focal_relative"]),
        z_mm=b.l1.z_mm + p["l1_axial_mm"],
        aperture_diameter_mm=b.l1.aperture_diameter_mm + p["l1_diameter_mm"],
        decenter_x_mm=p["l1_decenter_x_mm"],
        decenter_y_mm=p["l1_decenter_y_mm"],
        tilt_y_rad=p["l1_tilt_rad"],
    )
    l2 = replace(
        b.l2,
        focal_length_mm=b.l2.focal_length_mm * (1.0 + p["focal_relative"]),
        z_mm=b.l2.z_mm + p["l2_axial_mm"],
        aperture_diameter_mm=b.l2.aperture_diameter_mm + p["l2_diameter_mm"],
        decenter_x_mm=p["l2_decenter_x_mm"],
        decenter_y_mm=p["l2_decenter_y_mm"],
        tilt_y_rad=p["l2_tilt_rad"],
    )
    return replace(b, l1=l1, l2=l2)


def _tolerance_record(phase: str, assembly_id: int, design: str,
                      perturb: dict[str, float], perturbation_seed: int, ray_seed: int,
                      bundle: RayBundle, trace: BeamlineTrace,
                      metrics: dict[str, Any]) -> dict[str, Any]:
    row = {
        "phase": phase, "sample_id": f"{phase}_{assembly_id:04d}_{design}",
        "assembly_id": assembly_id, "design_id": design,
        "perturbation_seed": perturbation_seed, "ray_seed": bundle.seed,
        "n_rays": bundle.n_rays, "status": metrics.get("status", "UNKNOWN"),
        "source_weight_total": trace.ledger.get("source_weight_total"),
        "geometric_transmission_fraction": metrics.get("geometric_transmission_fraction"),
        "aperture_blocked_weight": trace.ledger.get("aperture_blocked_weight"),
        "l1_blocked_weight": trace.ledger.get("l1_blocked_weight"),
        "l2_blocked_weight": trace.ledger.get("l2_blocked_weight"),
        "outside_target_weight": trace.ledger.get("outside_target_weight"),
        "trace_failed_weight": trace.ledger.get("trace_failed_weight"),
        "balance_residual": trace.ledger.get("balance_residual"),
        "rms_radius_mm": metrics.get("rms_radius_mm"),
        "r80_mm": metrics.get("r80_mm"), "r90_mm": metrics.get("r90_mm"),
        "model_level": "P0_ANALYTIC", "evidence": "SIMULATED",
    }
    row.update(perturb)
    return row


def _deduplicate_tolerance_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (str(row.get("phase")), str(row.get("assembly_id")), str(row.get("design_id")))
        seen[key] = row
    return list(seen.values())


def _checkpoint_hashes(root: Path, inputs: dict[str, str]) -> dict[str, Any]:
    code = [
        "src/optisys/config_g4.py", "src/optisys/sources/multimode_fiber.py",
        "src/optisys/optics/pump_beamline.py", "src/optisys/optics/pump_optiland.py",
        "src/optisys/evaluation/pump_metrics.py", "src/optisys/gates/g4.py",
        "src/optisys/reports/report_g4.py", "src/optisys/reports/report_service.py",
        "src/optisys/cli.py", "src/optisys/jobs/service.py",
        "app/main.py", "app/pages/page_f_pump976.py",
    ]
    code_hashes = {name: _sha256_file(root / name) for name in code}
    canonical = "".join(f"{name}\0{digest}\n" for name, digest in sorted(code_hashes.items()))
    return {"input_hashes": inputs, "code_hashes": code_hashes,
            "source_tree_sha256": _sha256_bytes(canonical.encode("utf-8"))}


def _paired_bootstrap(rows: list[dict[str, Any]], *, seed: int,
                      replicates: int = 5000) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    by_phase: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}
    for row in rows:
        by_phase.setdefault(str(row["phase"]), {}).setdefault(str(row["assembly_id"]), {})[
            str(row["design_id"])] = row
    phase = "holdout"
    assemblies = by_phase.get(phase, {})
    pairs = [v for _, v in sorted(assemblies.items(), key=lambda item: int(item[0]))
             if "baseline" in v and "engineering_candidate" in v]
    if not pairs:
        return ({"status": "NOT_EVALUABLE", "n_attempted_pairs": len(assemblies),
                 "n_complete_pairs": 0, "bootstrap_seed": seed}, [])
    tx_diff = np.asarray([
        float(p["engineering_candidate"].get("geometric_transmission_fraction") or 0.0)
        - float(p["baseline"].get("geometric_transmission_fraction") or 0.0)
        for p in pairs], dtype=float)
    valid_spot_pairs = [p for p in pairs if p["baseline"].get("r90_mm") not in (None, "")
                        and p["engineering_candidate"].get("r90_mm") not in (None, "")]
    r90_diff = np.asarray([
        float(p["engineering_candidate"]["r90_mm"]) - float(p["baseline"]["r90_mm"])
        for p in valid_spot_pairs], dtype=float)
    rng = np.random.default_rng(seed)
    def bootstrap_means(values: np.ndarray) -> tuple[list[float], list[float] | None]:
        if values.size == 0:
            return [], None
        samples = rng.integers(0, values.size, size=(replicates, values.size))
        means = values[samples].mean(axis=1)
        return means.tolist(), [float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))]
    tx_replicates, tx_ci = bootstrap_means(tx_diff)
    r90_replicates, r90_ci = bootstrap_means(r90_diff)
    replicate_rows = [
        {"replicate_id": i,
         "delta_transmission": tx_replicates[i],
         "delta_r90_mm_valid_pairs": r90_replicates[i] if r90_replicates else None}
        for i in range(max(len(tx_replicates), len(r90_replicates)))
    ]
    summary = {
        "status": "OK",
        "bootstrap_unit": "paired assembly",
        "bootstrap_seed": seed,
        "replicates": replicates,
        "n_attempted_pairs": len(pairs),
        "n_valid_r90_pairs": int(r90_diff.size),
        "delta_transmission_candidate_minus_baseline_mean": float(np.mean(tx_diff)),
        "delta_transmission_95_ci": tx_ci,
        "delta_r90_mm_candidate_minus_baseline_valid_pairs_mean": (
            float(np.mean(r90_diff)) if r90_diff.size else None),
        "delta_r90_mm_95_ci_valid_pairs": r90_ci,
        "r90_ci_scope": "conditional on both designs reaching the active target; full failures remain in tolerance_samples.csv",
    }
    return summary, replicate_rows


class _PeakRss:
    def __init__(self, interval_s: float = 0.2) -> None:
        self.interval_s = interval_s
        self.peak_mb = 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._loop, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2.0)

    def _loop(self) -> None:
        try:
            import psutil
            process = psutil.Process()
        except Exception:
            return
        while not self._stop.is_set():
            try:
                self.peak_mb = max(self.peak_mb, process.memory_info().rss / 1024**2)
            except Exception:
                pass
            self._stop.wait(self.interval_s)


def _generate_figures(run_dir: Path, baseline_rows: list[dict[str, Any]],
                      target_density: dict[str, np.ndarray], oat_rows: list[dict[str, Any]],
                      tolerance_rows: list[dict[str, Any]]) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    figs = run_dir / "figures"
    figs.mkdir(exist_ok=True)
    baseline = next(r for r in baseline_rows if r["design_id"] == "baseline" and r["backend"] == "P0" and r["angular_case"] == "NA_0.22")
    candidate = next(r for r in baseline_rows if r["design_id"] == "engineering_candidate" and r["backend"] == "P0" and r["angular_case"] == "NA_0.22")
    fig, ax = plt.subplots(figsize=(9, 3.8))
    z = [0, baseline["l1_z_mm"], baseline["l2_z_mm"], baseline["target_z_mm"]]
    names = ["fiber", "L1", "L2", "target"]
    ax.plot([z[0], z[-1]], [0, 0], color="#365b78", lw=2)
    for zz, name, rr in zip(z, names, [0.0525, baseline["l1_aperture_diameter_mm"]/2,
                                      baseline["l2_aperture_diameter_mm"]/2, 1.0]):
        ax.scatter([zz], [0], s=30, color="#d97935")
        if name in ("L1", "L2"):
            ax.plot([zz, zz], [-rr, rr], color="#555555", lw=3)
        ax.text(zz, rr + 0.35, name, ha="center")
    ax.set(xlabel="z [mm]", ylabel="aperture radius [mm]", title="G4 P0 assumed beamline (not to scale)")
    ax.grid(alpha=0.25); fig.tight_layout(); fig.savefig(figs/"01_beamline_layout.png", dpi=150); plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    meshes = []
    for name, key in (("baseline P0", "baseline__P0__NA_0p22"),
                      ("candidate P0", "engineering_candidate__P0__NA_0p22")):
        density = target_density.get(f"{key}__conditional_density_per_mm2_transmitted")
        if density is None:
            continue
        xe = target_density[f"{key}__x_edges_mm"]
        ye = target_density[f"{key}__y_edges_mm"]
        mesh = axes[0 if name.startswith("baseline") else 1].pcolormesh(
            xe, ye, density.T, shading="auto", cmap="magma")
        meshes.append(mesh)
        axes[0 if name.startswith("baseline") else 1].set(title=name, xlabel="x [mm]", ylabel="y [mm]", aspect="equal")
    fig.suptitle("Conditional geometric ray density (P0; not W/mm²)")
    if meshes:
        fig.colorbar(meshes[-1], ax=axes.ravel().tolist(), label="normalized ray-weight density [mm^-2]")
    fig.subplots_adjust(left=0.08, right=0.87, bottom=0.12, top=0.86, wspace=0.35)
    fig.savefig(figs/"02_target_density_p0.png", dpi=150); plt.close(fig)

    factors = sorted({str(r["factor"]) for r in oat_rows})
    fig, axes = plt.subplots(2, 3, figsize=(12, 7))
    for ax, factor in zip(axes.ravel(), factors):
        selected = [r for r in oat_rows if r["factor"] == factor]
        selected.sort(key=lambda row: float(row["value"]))
        x = [float(r["value"]) for r in selected]
        y = [float(r["r90_mm"]) if r.get("r90_mm") not in (None, "") else np.nan for r in selected]
        ax.plot(x, y, marker="o", color="#315f79")
        unit = str(selected[0].get("unit", "")) if selected else ""
        ax.set(xlabel=f"{factor} [{unit}]", ylabel="r90 [mm]", title=factor)
        ax.grid(alpha=0.25)
    fig.suptitle("One-at-a-time sensitivity (P0; independent x scales)")
    fig.tight_layout()
    fig.savefig(figs/"03_oat_sensitivity.png", dpi=150); plt.close(fig)

    hold = [r for r in tolerance_rows if r["phase"] == "holdout"]
    fig, ax = plt.subplots(figsize=(7, 4))
    for design in ("baseline", "engineering_candidate"):
        vals = [float(r["r90_mm"]) for r in hold if r["design_id"] == design and r.get("r90_mm") not in (None, "")]
        if vals:
            ax.hist(vals, bins=18, alpha=0.55, label=f"{design}; valid n={len(vals)}")
    ax.set(xlabel="conditional r90 [mm]", ylabel="assembly count", title="Independent P0 tolerance holdout")
    ax.grid(alpha=0.2); ax.legend(fontsize=8); fig.tight_layout()
    fig.savefig(figs/"04_tolerance_holdout.png", dpi=150); plt.close(fig)

    source_path = run_dir / "source_samples.npz"
    if source_path.is_file():
        with np.load(source_path) as source:
            origin = source["origin_mm"]
            base_direction = source["direction"]
            alt_direction = source["alternative_direction"]
        theta_base = np.rad2deg(np.arccos(np.clip(base_direction[:, 2], -1.0, 1.0)))
        theta_alt = np.rad2deg(np.arccos(np.clip(alt_direction[:, 2], -1.0, 1.0)))
        fig, axes = plt.subplots(1, 2, figsize=(10, 4))
        axes[0].scatter(origin[:, 0], origin[:, 1], s=3, alpha=0.35, color="#315f79")
        axes[0].set(xlabel="x [mm]", ylabel="y [mm]", title="uniform-area fiber near field", aspect="equal")
        axes[0].grid(alpha=0.2)
        axes[1].hist(theta_base, bins=32, density=True, histtype="step", lw=2,
                     label="uniform solid angle")
        axes[1].hist(theta_alt, bins=32, density=True, histtype="step", lw=2,
                     label="edge-biased sensitivity")
        axes[1].set(xlabel="theta [deg]", ylabel="sample density [1/deg]",
                    title="declared far-field distributions")
        axes[1].grid(alpha=0.2); axes[1].legend(fontsize=8)
        fig.suptitle("Simulated source samples; neither curve is measured")
        fig.tight_layout(); fig.savefig(figs/"05_source_distributions.png", dpi=150); plt.close(fig)

    fig, ax = plt.subplots(figsize=(8, 4))
    for design, key in (("baseline", "baseline__P0__NA_0p22"),
                        ("candidate", "engineering_candidate__P0__NA_0p22")):
        density = target_density.get(f"{key}__weight_fraction_per_mm2_input_denominator")
        if density is None:
            continue
        xe = target_density[f"{key}__x_edges_mm"]
        ye = target_density[f"{key}__y_edges_mm"]
        xc = (xe[:-1] + xe[1:]) / 2
        yc = (ye[:-1] + ye[1:]) / 2
        midx, midy = len(xc) // 2, len(yc) // 2
        ax.plot(xc, density[:, midy], label=f"{design}: x cut")
        ax.plot(yc, density[midx, :], linestyle="--", label=f"{design}: y cut")
    ax.set(xlabel="position through beam centroid [mm]",
           ylabel="input-weight density [fraction/mm²]",
           title="P0 target-plane central cuts (not W/mm²)")
    ax.grid(alpha=0.25); ax.legend(fontsize=8); fig.tight_layout()
    fig.savefig(figs/"06_target_density_cuts.png", dpi=150); plt.close(fig)

    fig, axes = plt.subplots(1, 2, figsize=(9, 4))
    for ax, angle in zip(axes, ("NA_0.05", "NA_0.22")):
        for design in ("baseline", "engineering_candidate"):
            values = []
            labels = []
            for backend in ("P0", "P1_OPTILAND_0.6.3"):
                row = next((r for r in baseline_rows if r["design_id"] == design
                            and r["backend"] == backend and r["angular_case"] == angle), None)
                if row is not None:
                    values.append(row.get("geometric_transmission_fraction"))
                    labels.append(backend.replace("P1_OPTILAND_0.6.3", "P1"))
            if values:
                xloc = 0 if design == "baseline" else 1
                for offset, (backend, value) in enumerate(zip(labels, values)):
                    if value is not None:
                        ax.bar(xloc + (offset - 0.5) * 0.28, float(value), width=0.26,
                               label=backend if xloc == 0 else None)
        ax.set_xticks([0, 1], ["baseline", "candidate"])
        ax.set_ylim(0, 1.05); ax.set_ylabel("weight reaching active target / source weight")
        ax.set_title(angle); ax.grid(axis="y", alpha=0.2)
    axes[0].legend(fontsize=8)
    fig.suptitle("P0/P1 geometric transmission; model scope matters")
    fig.tight_layout(); fig.savefig(figs/"07_p0_p1_transmission.png", dpi=150); plt.close(fig)


def run_pump976(
    config_path: str | Path,
    *,
    candidate_path: str | Path,
    tolerance_path: str | Path,
    project_root: str | Path | None = None,
    runs_dir: str | Path | None = None,
    rays_override: int | None = None,
    assemblies_override: int | None = None,
    timeout_s: float = RUN_TIMEOUT_S,
    resume_run: str | Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Produce a new immutable-style G4 run. Historical runs are never touched."""

    root = Path(project_root).resolve() if project_root else Path.cwd().resolve()
    if rays_override is not None and (isinstance(rays_override, bool) or rays_override <= 0):
        raise PumpConfigError("rays_override must be a positive integer")
    if assemblies_override is not None and (isinstance(assemblies_override, bool) or assemblies_override <= 0):
        raise PumpConfigError("assemblies_override must be a positive integer")
    if not math.isfinite(float(timeout_s)) or timeout_s <= 0.0:
        raise PumpConfigError("timeout_s must be finite and positive")
    runs_root = Path(runs_dir).resolve() if runs_dir else root / "runs"
    runs_root.mkdir(parents=True, exist_ok=True)
    config_file = (root / config_path).resolve() if not Path(config_path).is_absolute() else Path(config_path).resolve()
    candidate_file = (root / candidate_path).resolve() if not Path(candidate_path).is_absolute() else Path(candidate_path).resolve()
    tolerance_file = (root / tolerance_path).resolve() if not Path(tolerance_path).is_absolute() else Path(tolerance_path).resolve()
    for path in (config_file, candidate_file, tolerance_file):
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise PumpConfigError(f"config path escapes project root: {path}") from exc
    baseline = load_pump976_config(config_file)
    candidate = load_pump976_config(candidate_file)
    tolerance = load_pump_tolerance_config(tolerance_file)
    if baseline.design_id != "baseline" or candidate.design_id != "engineering_candidate":
        raise PumpConfigError("design IDs must match frozen baseline/candidate roles")
    # The source draw is intentionally common-random-number paired.
    for key in ("wavelength_nm", "core_diameter_mm", "numerical_aperture",
                "output_index", "angular_distribution", "seed", "n_rays"):
        if baseline.source_metadata()[key] != candidate.source_metadata()[key]:
            raise PumpConfigError(f"baseline/candidate source mismatch at {key}")

    input_hashes = {str(p.relative_to(root).as_posix()): _sha256_file(p)
                    for p in (config_file, candidate_file, tolerance_file)}
    input_hashes["run_parameters"] = _sha256_bytes(json.dumps({
        "rays_override": rays_override,
        "assemblies_override": assemblies_override,
        "timeout_s": min(float(timeout_s), RUN_TIMEOUT_S),
    }, sort_keys=True).encode("utf-8"))
    prereg_file = root / PREREG_HASHES_PATH
    if not prereg_file.is_file():
        raise G4RunError(f"frozen pre-registration hashes missing: {prereg_file}")
    if _sha256_file(prereg_file) != FROZEN_HASH_MANIFEST_SHA256:
        raise G4RunError("G4 freeze hash manifest changed after registration; new version required")
    prereg_hashes = json.loads(prereg_file.read_text(encoding="utf-8"))
    freeze_input = {r["path"]: r["sha256"] for r in prereg_hashes["inputs"]}
    for rel, expected in freeze_input.items():
        if _sha256_file(root / rel) != expected:
            raise G4RunError(f"frozen input changed after registration: {rel}")
    input_hashes["docs/g4/G4_FREEZE_HASHES.json"] = _sha256_file(prereg_file)
    combined_config_hash = _sha256_bytes(json.dumps(input_hashes, sort_keys=True).encode())

    if resume_run is not None:
        run_dir = Path(resume_run).resolve()
        try:
            run_dir.relative_to(runs_root)
        except ValueError as exc:
            raise G4RunError("resume directory must be under the selected runs directory") from exc
        if not run_dir.is_dir():
            raise G4RunError(f"resume run does not exist: {run_dir}")
        current_status = json.loads((run_dir / "run_status.json").read_text(encoding="utf-8"))
        if current_status.get("status") not in ("TIMEOUT", "PARTIAL"):
            raise G4RunError("only TIMEOUT/PARTIAL runs can be resumed")
    else:
        run_dir = runs_root / _run_id(root, combined_config_hash)
        run_dir.mkdir(parents=True, exist_ok=False)

    code_hashes = _checkpoint_hashes(root, input_hashes)
    checkpoint_path = run_dir / "checkpoint.json"
    tolerance_csv_path = run_dir / "tolerance_samples.csv"
    tolerance_rows: list[dict[str, Any]] = []
    completed: dict[str, list[int]] = {"precheck": [], "holdout": []}
    if resume_run is not None:
        if not checkpoint_path.is_file():
            raise G4RunError("resume checkpoint is missing")
        checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
        if checkpoint.get("fingerprints") != code_hashes:
            raise G4RunError("resume refused: config, preregistration, or code hashes differ")
        completed = checkpoint.get("completed_assemblies", completed)
        tolerance_rows = _csv_read(tolerance_csv_path)

    config_snapshot = {
        "schema_version": "4.0", "gate": "G4",
        "baseline": baseline.raw, "engineering_candidate": candidate.raw,
        "tolerance": tolerance.raw,
        "input_hashes": input_hashes,
        "pre_registration_sha256": _sha256_file(root / "docs/g4/G4_PRE_REGISTRATION.md"),
    }
    if resume_run is None:
        (run_dir / "config_snapshot.yaml").write_text(yaml.safe_dump(config_snapshot, sort_keys=False, allow_unicode=True), encoding="utf-8")
    start_utc = _now()
    started = time.perf_counter()
    deadline = started + min(float(timeout_s), RUN_TIMEOUT_S)
    peak = _PeakRss(); peak.start()
    run_log = run_dir / "run.log"
    with run_log.open("a", encoding="utf-8") as log:
        log.write(f"[{start_utc}] G4 {'RESUME' if resume_run else 'START'} {run_dir.name}\n")
        log.write(f"[inputs] {json.dumps(input_hashes, sort_keys=True)}\n")

    environment = collect_environment(root)
    if resume_run is None:
        _json_write(run_dir / "environment.json", environment)
        provenance = {
            "run_id": run_dir.name, "gate": "G4", "created_at_utc": start_utc,
            "project_root": str(root), "git_commit": _git_commit(root), "git_dirty": _git_dirty(root),
            "config_sha256": combined_config_hash, "input_hashes": input_hashes,
            "source_tree_sha256": code_hashes["source_tree_sha256"],
            "preregistration_sha256": _sha256_file(root / "docs/g4/G4_PRE_REGISTRATION.md"),
            "acceptance_sha256": _sha256_file(root / "docs/g4/G4_ACCEPTANCE_CRITERIA.md"),
            "compute_budget_sha256": _sha256_file(root / "docs/g4/G4_COMPUTE_BUDGET.md"),
            "source_code_sha256": code_hashes["code_hashes"],
            "command": "optisys pump976 --config ... --candidate ... --tolerance ...",
            "measured_data_used": False,
        }
        _json_write(run_dir / "provenance.json", provenance)
        run_status = {
            "schema": "g4.run_status/1", "run_id": run_dir.name, "gate": "G4",
            "case_id": "pump976_g4", "schema_version": "4.0",
            "status": "RUNNING", "scientific_claim_status": "SIMULATED_ONLY",
            "model_level_emitted": "P1_QUALIFIED" if environment.get("optiland", {}).get("version") == "0.6.3" else "P0",
            "frozen": False, "evidence_level": "SIMULATED",
            "G4_ENGINEERING_EXECUTION_STATUS": "RUNNING",
            "G4_OPTICAL_MODEL_VERIFICATION": "NOT_RUN",
            "G4_TOLERANCE_EVALUATION_STATUS": "NOT_RUN",
            "G4_EMPIRICAL_VALIDATION_STATUS": "NOT_AVAILABLE",
            "G4_PORTFOLIO_DELIVERY_STATUS": "PARTIAL",
            "G4_AUDIT_STATUS": "NOT_RUN",
            "G4_SCIENTIFIC_CLAIM": "SIMULATED_ONLY",
            "INHERITED_G2_SCIENCE_STATUS": "QUALIFIED_ONLY",
            "started_at_utc": start_utc, "input_hashes": input_hashes,
        }
        _json_write(run_dir / "run_status.json", run_status)
    else:
        run_status = json.loads((run_dir / "run_status.json").read_text(encoding="utf-8"))
        run_status.update({"status": "RUNNING", "frozen": False, "resumed_at_utc": start_utc})
        _json_write(run_dir / "run_status.json", run_status)

    compute_plan = {
        "registered_budget_version": prereg_hashes.get("compute_budget_version"),
        "run_timeout_s": min(float(timeout_s), RUN_TIMEOUT_S),
        "stage_timeout_s": STAGE_TIMEOUT_S, "workers": 1,
        "ray_counts": {"nominal": rays_override or baseline.n_rays,
                       "source_convergence": [2000, 8000, 32000],
                       "tolerance": tolerance.rays_per_assembly},
        "assemblies": {"precheck": assemblies_override or tolerance.precheck_assemblies,
                       "holdout": assemblies_override or tolerance.holdout_assemblies},
        "profile_evidence": "artifacts/g4/pre/compute_profile.json",
        "timeout_enforced_by": ["G4 stage deadline checks", "JobService parent process timeout"],
        "checkpoint_chunk_assemblies": CHECKPOINT_CHUNK_ASSEMBLIES,
    }
    _json_write(run_dir / "compute_plan.json", compute_plan)
    _json_write(run_dir / "checkpoint.json", {
        "schema": "g4.checkpoint/1", "fingerprints": code_hashes,
        "completed_assemblies": completed,
    })

    stage_times: dict[str, float] = {}
    p0_metrics: list[dict[str, Any]] = []
    density_data: dict[str, np.ndarray] = {}
    oat_rows: list[dict[str, Any]] = []
    try:
        _check_deadline(deadline, started, "source convergence")
        stage = time.perf_counter()
        source_summary_rows = []
        for distribution in ("uniform_solid_angle", "edge_biased_sin_theta"):
            for count in (2000, 8000, 32000):
                for seed in (976051, 976052, 976053):
                    b = _bundle(baseline, count, seed, angular_distribution=distribution)
                    row = _source_row(b)
                    row.update({"angular_distribution": distribution, "core_diameter_mm": baseline.core_diameter_mm,
                                "numerical_aperture": baseline.numerical_aperture,
                                "output_index": baseline.output_index,
                                "probability_measure": b.metadata["angular_measure"]})
                    source_summary_rows.append(row)
        _csv_write(run_dir / "source_distribution_summary.csv", source_summary_rows)
        ray_count_rows = []
        for design in (baseline, candidate):
            for count in (2000, 8000, 32000):
                for seed in (976051, 976052, 976053):
                    _check_deadline(deadline, started, f"ray_count_{design.design_id}_{count}_{seed}", stage)
                    rays = _bundle(design, count, seed, angular_distribution="uniform_solid_angle")
                    trace = trace_thin_lens(rays, design.beamline)
                    metrics, _ = target_plane_metrics(trace)
                    ray_count_rows.append({
                        "design_id": design.design_id, "n_rays": count, "seed": seed,
                        "distribution_id": rays.distribution_id,
                        "source_weight_total": rays.total_weight,
                        "geometric_transmission_fraction": metrics.get("geometric_transmission_fraction"),
                        "rms_radius_mm": metrics.get("rms_radius_mm"),
                        "r80_mm": metrics.get("r80_mm"), "r90_mm": metrics.get("r90_mm"),
                        "status": metrics.get("status"), "model_level": "P0_ANALYTIC",
                        "evidence": "SIMULATED",
                    })
        ray_count_convergence = _ray_count_summary(ray_count_rows)
        _csv_write(run_dir / "ray_count_convergence.csv", ray_count_rows)
        _json_write(run_dir / "ray_count_convergence_summary.json", ray_count_convergence)
        nominal_rays = rays_override or baseline.n_rays
        source_bundle = _bundle(baseline, nominal_rays, baseline.seed)
        alternative_bundle = _bundle(baseline, nominal_rays, baseline.seed,
                                     angular_distribution="edge_biased_sin_theta")
        np.savez_compressed(
            run_dir / "source_samples.npz",
            ray_id=source_bundle.ray_id, origin_mm=source_bundle.origin_mm,
            direction=source_bundle.direction, weight=source_bundle.weight,
            alternative_direction=alternative_bundle.direction,
            alternative_weight=alternative_bundle.weight,
            seed=np.asarray(source_bundle.seed),
        )
        source_sample_rows = []
        for i in range(source_bundle.n_rays):
            source_sample_rows.append({
                "ray_id": int(source_bundle.ray_id[i]),
                "x0_mm": float(source_bundle.origin_mm[i, 0]),
                "y0_mm": float(source_bundle.origin_mm[i, 1]),
                "z0_mm": float(source_bundle.origin_mm[i, 2]),
                "dx": float(source_bundle.direction[i, 0]),
                "dy": float(source_bundle.direction[i, 1]),
                "dz": float(source_bundle.direction[i, 2]),
                "weight": float(source_bundle.weight[i]),
                "seed": source_bundle.seed,
                "distribution_id": source_bundle.distribution_id,
            })
        _csv_write(run_dir / "source_samples.csv", source_sample_rows)
        _json_write(run_dir / "source_distribution.json", {
            "baseline": source_bundle.metadata,
            "alternative": alternative_bundle.metadata,
            "source_summary_rows": len(source_summary_rows),
            "ray_count_convergence_status": ray_count_convergence["status"],
            "absolute_power_w": None,
        })
        stage_times["source_convergence"] = time.perf_counter() - stage

        _check_deadline(deadline, started, "nominal optical traces")
        stage = time.perf_counter()
        designs = (baseline, candidate)
        reference_rows: list[dict[str, Any]] = []
        low_na_crosschecks: list[dict[str, Any]] = []
        ray_balance_rows: list[dict[str, Any]] = []
        for design in designs:
            for na, label in ((baseline.numerical_aperture, "NA_0.22"), (0.05, "NA_0.05")):
                _check_deadline(deadline, started, f"nominal_{design.design_id}_{label}", stage)
                rays = _bundle(design, nominal_rays, design.seed,
                               angular_distribution="uniform_solid_angle")
                if na != rays.metadata["numerical_aperture"]:
                    rays = sample_multimode_fiber(nominal_rays, design.core_diameter_mm, na,
                                                  output_index=design.output_index,
                                                  seed=design.seed,
                                                  angular_distribution=design.angular_distribution)
                p0 = trace_thin_lens(rays, design.beamline)
                p0m, p0d = target_plane_metrics(p0)
                p1_result = OptilandPumpTracer(design.beamline, wavelength_nm=design.wavelength_nm).trace(rays)
                if p1_result.status == "MODEL_UNAVAILABLE":
                    p1 = None
                    p1m = {"status": "MODEL_UNAVAILABLE",
                           "n_source": rays.n_rays,
                           "geometric_transmission_fraction": None,
                           "transmission_denominator": "all source ray weights",
                           "rms_radius_mm": None, "r80_mm": None, "r90_mm": None}
                    p1d = {}
                    p1ledger = dict(p1_result.ledger)
                else:
                    p1 = _trace_p1_as_beamline(rays, p1_result, design.beamline)
                    p1m, p1d = target_plane_metrics(p1)
                    p1ledger = dict(p1.ledger)
                geometry = {"l1_z_mm": design.beamline.l1.z_mm,
                            "l2_z_mm": design.beamline.l2.z_mm,
                            "target_z_mm": design.beamline.target_z_mm,
                            "l1_aperture_diameter_mm": design.beamline.l1.aperture_diameter_mm,
                            "l2_aperture_diameter_mm": design.beamline.l2.aperture_diameter_mm}
                p0_metrics.append({**_metric_row(design.design_id, "P0", label, p0m), **geometry})
                p0_metrics.append({**_metric_row(design.design_id, "P1_OPTILAND_0.6.3", label, p1m), **geometry})
                if label == "NA_0.05" and p1 is not None:
                    common = np.isin(p0.status, ["OK", "OUTSIDE_TARGET"]) & np.isin(
                        p1.status, ["OK", "OUTSIDE_TARGET"])
                    pos_delta = np.hypot(p1.target_x_mm[common] - p0.target_x_mm[common],
                                         p1.target_y_mm[common] - p0.target_y_mm[common])
                    delta_weights = p1.weight[common]
                    order = np.argsort(pos_delta, kind="mergesort")
                    cumulative = np.cumsum(delta_weights[order], dtype=np.float64)
                    p80_position_delta = (float(pos_delta[order][np.searchsorted(
                        cumulative, 0.8 * cumulative[-1], side="left")])
                        if cumulative.size and cumulative[-1] > 0 else None)
                    p0_r80, p1_r80 = p0m.get("r80_mm"), p1m.get("r80_mm")
                    relative_r80_delta = (abs(float(p1_r80) - float(p0_r80)) / float(p0_r80)
                                          if p0_r80 not in (None, 0) and p1_r80 is not None else None)
                    low_na_crosschecks.append({
                        "design_id": design.design_id, "backend_version": p1_result.backend_version,
                        "n_rays": rays.n_rays, "common_valid_rays": int(common.sum()),
                        "p0_r80_mm": p0_r80, "p1_r80_mm": p1_r80,
                        "relative_r80_delta": relative_r80_delta,
                        "p80_absolute_position_delta_mm": p80_position_delta,
                        "criteria_position_mm": 0.05, "criteria_r80_relative": 0.10,
                        "pass": bool(p1_result.backend_version == "0.6.3" and
                                     p80_position_delta is not None and p80_position_delta <= 0.05 and
                                     relative_r80_delta is not None and relative_r80_delta <= 0.10),
                    })
                prefix0 = _density_key(design.design_id, "P0", "0.22" if label == "NA_0.22" else "0.05")
                prefix1 = _density_key(design.design_id, "P1", "0.22" if label == "NA_0.22" else "0.05")
                density_data.update({f"{prefix0}__{k}": v for k, v in p0d.items()})
                density_data.update({f"{prefix1}__{k}": v for k, v in p1d.items()})
                for backend, metrics, ledger in (("P0", p0m, p0.ledger),
                                                  ("P1_OPTILAND_0.6.3", p1m, p1ledger)):
                    ray_balance_rows.append({"design_id": design.design_id, "backend": backend,
                                             "angular_case": label, **ledger,
                                             "geometric_transmission_fraction": metrics.get("geometric_transmission_fraction"),
                                             "balance_pass": (ledger.get("balance_residual") is not None
                                                              and abs(float(ledger["balance_residual"])) <= 1e-10),
                                             "backend_status": p1_result.status if backend.startswith("P1") else "OK",
                                             "evidence": "SIMULATED"})
                scalar = trace_thin_lens_scalar_reference(rays, design.beamline)
                vector_good = np.isin(p0.status, ["OK", "OUTSIDE_TARGET"])
                reference_good = np.isin(scalar["status"], ["OK", "OUTSIDE_TARGET"])
                comparable = vector_good & reference_good
                p1_rows = np.flatnonzero(comparable)
                for i in p1_rows:
                    p1status = ("MODEL_UNAVAILABLE" if p1 is None else
                                "OK" if p1.status[i] == "OK" else str(p1.status[i]))
                    reference_rows.append({
                        "design_id": design.design_id, "angular_case": label,
                        "ray_id": int(rays.ray_id[i]), "source_seed": rays.seed,
                        "x0_mm": float(rays.origin_mm[i, 0]), "y0_mm": float(rays.origin_mm[i, 1]),
                        "theta_rad": float(np.arccos(np.clip(rays.direction[i, 2], -1, 1))),
                        "weight": float(rays.weight[i]),
                        "p0_x_mm": float(p0.target_x_mm[i]), "p0_y_mm": float(p0.target_y_mm[i]),
                        "scalar_reference_x_mm": float(scalar["target_x_mm"][i]),
                        "scalar_reference_y_mm": float(scalar["target_y_mm"][i]),
                        "p0_scalar_delta_mm": float(np.hypot(p0.target_x_mm[i]-scalar["target_x_mm"][i],
                                                               p0.target_y_mm[i]-scalar["target_y_mm"][i])),
                        "p0_scalar_direction_delta": float(np.linalg.norm(
                            p0.direction_out[i] - scalar["target_direction"][i])),
                        "p1_x_mm": (float(p1.target_x_mm[i]) if p1 is not None and np.isfinite(p1.target_x_mm[i]) else None),
                        "p1_y_mm": (float(p1.target_y_mm[i]) if p1 is not None and np.isfinite(p1.target_y_mm[i]) else None),
                        "p1_weight_in_target": (float(p1.weight[i]) if p1 is not None and p1.status[i] == "OK" else None),
                        "p0_status": str(p0.status[i]), "p1_status": p1status,
                        "p1_blocked_at": (str(p1.blocked_at[i]) if p1 is not None else ""),
                        "evidence": "SIMULATED",
                    })
        _csv_write(run_dir / "raytrace_reference.csv", reference_rows)
        scalar_position_errors = [float(r["p0_scalar_delta_mm"]) for r in reference_rows
                                  if r["angular_case"] == "NA_0.22"]
        scalar_direction_errors = [float(r["p0_scalar_direction_delta"]) for r in reference_rows
                                   if r["angular_case"] == "NA_0.22"]
        scalar_check = {
            "status": "PASS" if scalar_position_errors and scalar_direction_errors
                      and max(scalar_position_errors) <= 1e-10
                      and max(scalar_direction_errors) <= 1e-12 else "FAIL",
            "method": "independent per-ray scalar ABCD/slope propagation vs vectorized P0",
            "n_rays": len(scalar_position_errors),
            "max_position_delta_mm": max(scalar_position_errors) if scalar_position_errors else None,
            "max_direction_delta": max(scalar_direction_errors) if scalar_direction_errors else None,
            "criteria_position_mm": 1e-10, "criteria_direction": 1e-12,
        }
        p1_crosscheck_status = ("PASS" if len(low_na_crosschecks) == 2 and
                                all(row["pass"] for row in low_na_crosschecks) else "QUALIFIED")
        _json_write(run_dir / "optical_crosscheck.json", {
            "p0_scalar_reference": scalar_check,
            "p1_low_na_reference": low_na_crosschecks,
            "p1_low_na_status": p1_crosscheck_status,
            "p1_high_na_interpretation": "P0/P1 difference is retained as model discrepancy; P0 ideal thin lens is not used as full-NA physical validation.",
        })
        _csv_write(run_dir / "ray_balance.csv", ray_balance_rows)
        _csv_write(run_dir / "target_plane_metrics.csv", p0_metrics)
        np.savez_compressed(run_dir / "target_plane_density.npz", **density_data)

        baseline_lenses = {
            "P1_baseline": OptilandPumpTracer(baseline.beamline, wavelength_nm=baseline.wavelength_nm).lens_models,
            "P1_candidate": OptilandPumpTracer(candidate.beamline, wavelength_nm=candidate.wavelength_nm).lens_models,
        }
        _json_write(run_dir / "optics_model.json", {
            "P0": {"model": "paraxial geometric rays + ideal thin lenses",
                  "aperture": "circular hard stop", "fresnel": False, "coatings": False,
                  "diffraction": False, "coherence": False},
            "P1": {"backend": "Optiland",
                  "version": environment.get("optiland", {}).get("version", "NOT_INSTALLED"),
                  "scope": "centered two equiconvex N-BK7 singlets with explicit radial apertures",
                  "limitations": ["no measured lens part", "no coating/Fresnel loss", "no decenter/tilt coordinate breaks", "no diffraction or mode interference"],
                  "lens_models": baseline_lenses},
            "source_assumptions": baseline.source_metadata(),
        })
        _json_write(run_dir / "repro_inputs.json", {
            "schema": "g4.repro_inputs/1",
            "run_id": run_dir.name,
            "units": {"position": "mm", "angle": "rad", "weight": "dimensionless"},
            "source": {"core_diameter_mm": baseline.core_diameter_mm,
                       "core_radius_mm": baseline.core_diameter_mm / 2.0,
                       "numerical_aperture": baseline.numerical_aperture,
                       "output_index": baseline.output_index,
                       "theta_max_rad": float(np.arcsin(baseline.numerical_aperture / baseline.output_index)),
                       "ray_count": nominal_rays, "seed": baseline.seed,
                       "distribution": baseline.angular_distribution},
            "designs": {
                design.design_id: {
                    "l1": {"focal_length_mm": design.beamline.l1.focal_length_mm,
                           "z_mm": design.beamline.l1.z_mm,
                           "aperture_diameter_mm": design.beamline.l1.aperture_diameter_mm},
                    "l2": {"focal_length_mm": design.beamline.l2.focal_length_mm,
                           "z_mm": design.beamline.l2.z_mm,
                           "aperture_diameter_mm": design.beamline.l2.aperture_diameter_mm},
                    "target_z_mm": design.beamline.target_z_mm,
                    "target_radius_mm": design.beamline.target_radius_mm,
                } for design in designs
            },
            "p0_equations": [
                "x_hit = x + ((z_lens-z)/dz)*dx; y_hit analogous",
                "u_x=dx/dz-(x_hit-cx)/f; u_y=dy/dz-(y_hit-cy)/f",
                "direction_out=(u_x,u_y,1)/sqrt(1+u_x^2+u_y^2)",
                "geometric transmission = transmitted source weight / total source weight",
            ],
            "p1_scope": "Optiland 0.6.3 assumed centered equiconvex N-BK7 singlets; P0/P1 comparison is condition-specific",
        })
        stage_times["nominal_traces"] = time.perf_counter() - stage

        _check_deadline(deadline, started, "OAT")
        stage = time.perf_counter()
        oat_source = _bundle(baseline, nominal_rays, int(tolerance.oat_seed))
        oat_rows = _oat_rows(baseline, oat_source)
        _csv_write(run_dir / "oat.csv", oat_rows)
        stage_times["oat"] = time.perf_counter() - stage

        _check_deadline(deadline, started, "tolerance")
        stage = time.perf_counter()
        tolerance_rows = _deduplicate_tolerance_rows(tolerance_rows)
        phases = (("precheck", assemblies_override or tolerance.precheck_assemblies, tolerance.precheck_seed),
                  ("holdout", assemblies_override or tolerance.holdout_assemblies, tolerance.holdout_seed))
        for phase, n_assemblies, phase_seed in phases:
            perturbations = _draw_perturbations(tolerance, n_assemblies, phase_seed)
            already = {int(v) for v in completed.get(phase, [])}
            for assembly_id, perturb in enumerate(perturbations):
                if assembly_id in already:
                    continue
                _check_deadline(deadline, started, f"tolerance_{phase}_{assembly_id}", stage)
                perturb_seed = int((phase_seed * 1009 + assembly_id * 9176) % (2**32 - 1))
                for design in designs:
                    beam = _perturbed_beamline(design, perturb)
                    core_diameter = design.core_diameter_mm * (1.0 + perturb["fiber_radius_relative"])
                    rays = _bundle(design, tolerance.rays_per_assembly, perturb_seed,
                                   core_diameter_mm=core_diameter)
                    trace = trace_thin_lens(rays, beam)
                    metrics, _ = target_plane_metrics(trace)
                    tolerance_rows.append(_tolerance_record(phase, assembly_id,
                                                            design.design_id, perturb,
                                                            phase_seed, perturb_seed,
                                                            rays, trace, metrics))
                completed.setdefault(phase, []).append(assembly_id)
                if (assembly_id + 1) % CHECKPOINT_CHUNK_ASSEMBLIES == 0 or assembly_id + 1 == n_assemblies:
                    tolerance_rows = _deduplicate_tolerance_rows(tolerance_rows)
                    _csv_write(tolerance_csv_path, tolerance_rows)
                    _json_write(checkpoint_path, {
                        "schema": "g4.checkpoint/1", "fingerprints": code_hashes,
                        "completed_assemblies": completed,
                        "updated_at_utc": _now(),
                        "last_checkpoint": {"phase": phase, "assembly_id": assembly_id},
                    })
        tolerance_rows = _deduplicate_tolerance_rows(tolerance_rows)
        _csv_write(tolerance_csv_path, tolerance_rows)
        stage_times["tolerance"] = time.perf_counter() - stage

        _check_deadline(deadline, started, "design comparison")
        stage = time.perf_counter()
        bootstrap, bootstrap_replicates = _paired_bootstrap(
            tolerance_rows, seed=tolerance.holdout_seed + 1)
        _json_write(run_dir / "split_manifest.json", {
            "design_selection": "predeclared engineering candidate; no random search",
            "precheck": {"seed": tolerance.precheck_seed,
                         "assemblies": assemblies_override or tolerance.precheck_assemblies,
                         "rays_per_assembly": tolerance.rays_per_assembly},
            "holdout": {"seed": tolerance.holdout_seed,
                        "assemblies": assemblies_override or tolerance.holdout_assemblies,
                        "rays_per_assembly": tolerance.rays_per_assembly,
                        "independent_from_precheck": tolerance.holdout_seed != tolerance.precheck_seed},
            "oat_seed": tolerance.oat_seed,
            "source_convergence_seeds": [976051, 976052, 976053],
            "common_random_numbers": "same perturbation vector and source seed per assembly across designs",
            "bootstrap_seed": tolerance.holdout_seed + 1,
            "holdout_opened_after_design_freeze": True,
        })
        _json_write(run_dir / "bootstrap_summary.json", bootstrap)
        _csv_write(run_dir / "bootstrap_replicates.csv", bootstrap_replicates)
        design_rows = []
        for design in ("baseline", "engineering_candidate"):
            nominal = next(r for r in p0_metrics if r["design_id"] == design and r["backend"] == "P0" and r["angular_case"] == "NA_0.22")
            hold = [r for r in tolerance_rows if r["phase"] == "holdout" and r["design_id"] == design]
            valid = [r for r in hold if r.get("r90_mm") not in (None, "")]
            design_rows.append({
                "design_id": design, "nominal_p0_geometric_transmission": nominal.get("geometric_transmission_fraction"),
                "nominal_p0_r80_mm": nominal.get("r80_mm"), "nominal_p0_r90_mm": nominal.get("r90_mm"),
                "holdout_n_attempted": len(hold), "holdout_n_valid_spot": len(valid),
                "holdout_failure_rate": (1.0 - len(valid) / len(hold)) if hold else None,
                "holdout_mean_r90_mm_valid_only": (float(np.mean([float(r["r90_mm"]) for r in valid])) if valid else None),
                "l1_aperture_diameter_mm": (baseline if design == "baseline" else candidate).beamline.l1.aperture_diameter_mm,
                "l2_aperture_diameter_mm": (baseline if design == "baseline" else candidate).beamline.l2.aperture_diameter_mm,
                "status": "SIMULATED_P0",
            })
        design_rows.append({"design_id": "paired_holdout_delta_candidate_minus_baseline",
                            **bootstrap, "overall_claim": "NO_SUPPORTED_IMPROVEMENT_UNTIL_P1_FULL_NA_AND_EMPIRICAL_SCOPE_RESOLVED"})
        _csv_write(run_dir / "design_comparison.csv", design_rows)
        stage_times["comparison"] = time.perf_counter() - stage

        _generate_figures(run_dir, p0_metrics, density_data, oat_rows, tolerance_rows)
        _json_write(run_dir / "source_distribution.json", {
            "baseline": source_bundle.metadata,
            "alternative": alternative_bundle.metadata,
            "source_summary_rows": 18,
            "absolute_power_w": None,
        })
        nominal_scale = (nominal_rays == baseline.n_rays and assemblies_override is None)
        expected_rows = (2 * tolerance.precheck_assemblies + 2 * tolerance.holdout_assemblies
                         if assemblies_override is None else 4 * assemblies_override)
        full_registered_scale = (nominal_scale and len(tolerance_rows) == expected_rows)
        status = "PASS_WITH_DECLARED_DEVIATIONS" if full_registered_scale else "PARTIAL"
        p1_qualified = len(low_na_crosschecks) == 2 and all(row["pass"] for row in low_na_crosschecks)
        model_status = "QUALIFIED" if scalar_check["status"] == "PASS" and (p1_qualified or not low_na_crosschecks) else "FAIL"
        tol_status = "PASS" if full_registered_scale else "PARTIAL"
        claim = "QUALIFIED"
        open_issues = [
            "G4-01: no vendor part numbers / measured source power / empirical pump spot; all are ASSUMED or UNKNOWN",
            "G4-02: P0 ideal thin-lens full-NA result differs materially from assumed P1 singlet trace; no full-NA physical validation",
            "G4-03: P1 adapter covers centered singlets only; tolerance/misalignment sweep is P0",
            "G4-04: no experiment; empirical validation NOT_AVAILABLE",
        ]
        if ray_count_convergence["status"] != "PASS":
            open_issues.append("G4-05: P0 ray-count convergence threshold not met; report wider sampling uncertainty")
        run_status.update({
            "status": status, "frozen": True,
            "G4_ENGINEERING_EXECUTION_STATUS": status,
            "G4_OPTICAL_MODEL_VERIFICATION": model_status,
            "G4_TOLERANCE_EVALUATION_STATUS": tol_status,
            "G4_EMPIRICAL_VALIDATION_STATUS": "NOT_AVAILABLE",
            "G4_PORTFOLIO_DELIVERY_STATUS": "PARTIAL",
            "G4_AUDIT_STATUS": "NOT_RUN",
            "G4_SCIENTIFIC_CLAIM": claim,
            "scientific_claim_status": claim,
            "model_level_emitted": "P1_QUALIFIED" if p1_qualified else "P0",
            "finished_at_utc": _now(),
            "input_hashes": input_hashes,
            "open_issues": open_issues,
            "stage_wall_s": {k: round(v, 4) for k, v in stage_times.items()},
            "ray_count_convergence_status": ray_count_convergence["status"],
            "expected_tolerance_rows": expected_rows,
            "actual_tolerance_rows": len(tolerance_rows),
            "reduced_sample_deviation": not full_registered_scale,
            "registered_sample_scale": full_registered_scale,
        })
        claim_check = validate_g4_claims(run_status, root=root, run_dir=run_dir)
        run_status["quality_gate_validation"] = claim_check
        if not claim_check["valid"]:
            run_status.update({"status": "PARTIAL", "G4_ENGINEERING_EXECUTION_STATUS": "PARTIAL",
                               "G4_TOLERANCE_EVALUATION_STATUS": "PARTIAL",
                               "critical_quality_gate_errors": claim_check["errors"]})
        _json_write(run_dir / "run_status.json", run_status)
        measured = {
            "started_at_utc": start_utc, "finished_at_utc": _now(),
            "wall_s": round(time.perf_counter() - started, 4),
            "peak_rss_mb": round(peak.peak_mb, 2), "workers": 1,
            "stage_wall_s": {k: round(v, 4) for k, v in stage_times.items()},
            "profile_workers_tested": [1, 2, 4, 6], "gpu_status": "NOT_TESTED",
            "timeout_s": min(float(timeout_s), RUN_TIMEOUT_S),
            "thread_environment": {k: os.environ.get(k, "UNSET") for k in
                                    ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")},
        }
        _json_write(run_dir / "compute_measured.json", measured)
        with run_log.open("a", encoding="utf-8") as log:
            log.write(f"[{_now()}] G4 FINISHED status={status} tolerance={tol_status} model={model_status}\n")
        _write_run_summary(run_dir, baseline, candidate, source_summary_rows, p0_metrics,
                           bootstrap, run_status, measured, open_issues)
        from optisys.reports.report_g4 import render_g4_report
        render_g4_report(run_dir, run_dir, verdict_root=root)
        return run_dir, run_status
    except TimeoutError as exc:
        tolerance_rows = _deduplicate_tolerance_rows(tolerance_rows)
        _csv_write(tolerance_csv_path, tolerance_rows)
        _json_write(checkpoint_path, {"schema": "g4.checkpoint/1", "fingerprints": code_hashes,
                                      "completed_assemblies": completed, "updated_at_utc": _now(),
                                      "timeout_reason": str(exc)})
        run_status.update({"status": "TIMEOUT", "frozen": False,
                           "G4_ENGINEERING_EXECUTION_STATUS": "PARTIAL",
                           "G4_TOLERANCE_EVALUATION_STATUS": "PARTIAL",
                           "G4_PORTFOLIO_DELIVERY_STATUS": "PARTIAL",
                           "G4_AUDIT_STATUS": "NOT_RUN", "timeout_reason": str(exc),
                           "finished_at_utc": _now(), "actual_tolerance_rows": len(tolerance_rows)})
        _json_write(run_dir / "run_status.json", run_status)
        _json_write(run_dir / "compute_measured.json", {
            "started_at_utc": start_utc, "finished_at_utc": _now(),
            "wall_s": round(time.perf_counter() - started, 4),
            "peak_rss_mb": round(peak.peak_mb, 2), "workers": 1,
            "timeout_s": min(float(timeout_s), RUN_TIMEOUT_S), "status": "TIMEOUT"})
        with run_log.open("a", encoding="utf-8") as log:
            log.write(f"[{_now()}] TIMEOUT {exc}\n")
        return run_dir, run_status
    finally:
        peak.stop()


def _check_deadline(deadline: float, started: float, stage: str,
                    stage_started: float | None = None) -> None:
    elapsed = time.monotonic() - started
    if elapsed >= RUN_TIMEOUT_S:
        raise TimeoutError(f"run exceeded {RUN_TIMEOUT_S:.0f}s watchdog before {stage}")
    if stage_started is not None and time.perf_counter() - stage_started >= STAGE_TIMEOUT_S:
        raise TimeoutError(f"stage {stage} exceeded {STAGE_TIMEOUT_S:.0f}s watchdog")
    if time.monotonic() >= deadline:
        raise TimeoutError(f"caller timeout reached after {elapsed:.2f}s before {stage}")


def validate_g4_claims(status: dict[str, Any], *, root: Path,
                       run_dir: Path | None = None) -> dict[str, Any]:
    """Reject unsupported PASS claims before they reach reports or audit packages."""

    errors: list[str] = []
    if status.get("G4_EMPIRICAL_VALIDATION_STATUS") == "PASS" and not status.get("measured_data_used"):
        errors.append("empirical PASS requires an input marked measured_data_used")
    if status.get("G4_SCIENTIFIC_CLAIM") in ("MEASURED", "VALIDATED_BY_EXPERIMENT") and not status.get("measured_data_used"):
        errors.append("measured/experimental claim requires measured_data_used")
    if status.get("G4_AUDIT_STATUS") == "PASS":
        audit = status.get("audit_verification") or {}
        if not all(audit.get(k) is True for k in ("content_integrity", "extracted_repro", "tamper_rejected")):
            errors.append("audit PASS requires content, extracted reproduction, and tamper evidence")
        if audit.get("same_env_byte_repro") is not True:
            errors.append("audit PASS requires a successful same-environment byte rebuild")
        if audit.get("cross_env_byte_repro") not in ("PASS", "NOT_GUARANTEED"):
            errors.append("audit PASS has an invalid cross-environment byte rebuild state")
    if status.get("G4_OPTICAL_MODEL_VERIFICATION") == "PASS":
        cross = _json_read((run_dir or Path()) / "optical_crosscheck.json")
        if cross.get("p0_scalar_reference", {}).get("status") != "PASS" or cross.get("p1_low_na_status") != "PASS":
            errors.append("optical verification PASS requires P0 scalar and P1 low-NA cross-checks")
    if status.get("G4_TOLERANCE_EVALUATION_STATUS") == "PASS":
        expected = status.get("expected_tolerance_rows")
        actual = status.get("actual_tolerance_rows")
        path = (run_dir or Path()) / "tolerance_samples.csv"
        if not expected or actual != expected or not path.is_file():
            errors.append("tolerance PASS requires every registered row in tolerance_samples.csv")
    if status.get("G4_ENGINEERING_EXECUTION_STATUS") == "PASS" and status.get("status") in ("TIMEOUT", "PARTIAL", "FAIL"):
        errors.append("engineering PASS conflicts with run status")
    return {"valid": not errors, "errors": errors,
            "checked_at_utc": _now(),
            "measured_data_used": bool(status.get("measured_data_used", False))}


def _write_run_summary(run_dir: Path, baseline: Pump976Config, candidate: Pump976Config,
                       source_rows: list[dict[str, Any]], metrics: list[dict[str, Any]],
                       bootstrap: dict[str, Any], status: dict[str, Any],
                       compute: dict[str, Any], issues: list[str]) -> None:
    summary = {
        "schema": "g4.metrics/1", "run_id": run_dir.name,
        "source_convergence_rows": len(source_rows),
        "nominal_metrics": metrics,
        "paired_holdout": bootstrap,
        "ray_count_convergence": _json_read(run_dir / "ray_count_convergence_summary.json"),
        "model_level": status.get("model_level_emitted"),
        "evidence": "SIMULATED",
        "source_power": "UNKNOWN",
        "absolute_irradiance_w_per_mm2": "NOT_EVALUABLE",
        "empirical_validation": "NOT_AVAILABLE",
        "inherited_g2_science": "QUALIFIED_ONLY",
        "issues": issues,
        "compute": compute,
    }
    _json_write(run_dir / "metrics.json", summary)


def validate_pump976_config(path: str | Path) -> dict[str, Any]:
    config = load_pump976_config(path)
    return {"status": "VALID", "schema_version": "4.0", "case_id": "pump976_g4",
            "design_id": config.design_id, "config_path": str(config.path),
            "source": config.source_metadata(), "model_level": "P0_ANALYTIC",
            "evidence_status": "SIMULATED", "absolute_power_w": "UNKNOWN"}
