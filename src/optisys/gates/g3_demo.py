"""G3 demo run: a *real* optical execution at deliberately small scale.

What this is
------------
A short, genuinely executed L1-approximate evaluation of the three frozen G2
designs on a reduced assembly panel.  It exists so that the UI has a run whose
numbers this project produced *in this round*, without re-running the 5 625 s
G2 chain.

What this is NOT
----------------
* It is **not** a G2 re-execution and it cannot confirm or refute G2.
* Its panel is smaller than G2's, so its numbers are not comparable to G2's.
  The run record says so in ``extra.demo_boundary``.
* It does not make any of the G2 inheritance problems go away.

Scoring reuse
-------------
``_score_rows`` / ``_metrics`` / ``_group_metrics`` / ``_factory_calibration``
are imported from :mod:`optisys.gates.g2` on purpose.  Re-implementing the
aggregation here would let the demo and the gate drift apart, and a demo that
scores differently from the gate is worse than no demo.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from optisys.config_g2 import ResolvedG2Config
from optisys.gates.g2 import (
    _assemble,
    _assembly_payload,
    _factory_calibration,
    _group_metrics,
    _metrics,
    _score_rows,
    _write_csv,
    _write_json,
)
from optisys.gates.g2_worker import assembly_chunk
from optisys.runtime.run import RunContext
from optisys.tolerance.assembly_model import SceneRunner
from optisys.tolerance.perturbations import AssemblyPerturbation, perturbation_sigmas
from optisys.tolerance.samplers import draw
from optisys.optimization.search_space import Design

ESTIMATORS = ("centroid", "gaussian_2d", "gaussian_2d_integrated")

#: The three frozen G2 designs.  Hard-coded because this is a demo of *those*
#: designs; it must not silently re-optimise them.
FROZEN_DESIGNS = {
    "baseline": Design(20.0, 8.0, 0.0),
    "nominal": Design(15.0, 11.1, 4.0),
    "robust": Design(34.4, 7.272384615618831, 4.0),
}


def _demo_perturbations(config: ResolvedG2Config, n: int) -> list[AssemblyPerturbation]:
    """Deterministic draw under a demo-only namespace.

    The seed is offset from the G2 final draw so a demo assembly id can never be
    mistaken for a G2 final assembly, even though the ids look similar.
    """

    sigmas = perturbation_sigmas(config.tolerance)
    draws = draw("normal", n, sigmas, seed=config.run.seed + 770_001,
                 rho=config.tolerance.rho_baseline_theta
                 if config.tolerance.correlation_enabled else None)
    physical = draws.physical()
    return [
        AssemblyPerturbation(
            assembly_id=f"DEMO{index:04d}",
            d_baseline_mm=float(physical[index, 0]),
            d_theta_rad=float(physical[index, 1]),
            d_focal_relative=float(physical[index, 2]),
            d_cx_px=float(physical[index, 3]),
            d_focus_mm=float(physical[index, 4]),
        )
        for index in range(draws.n)
    ]


def run_g3_demo(config: ResolvedG2Config, project_root: Path, *, assemblies: int = 12,
                workers: int = 1, runs_dir: Path | None = None,
                condition: str = "medium") -> tuple[RunContext, dict[str, Any]]:
    """Execute the reduced panel and write a schema-3.0 run directory."""

    root = Path(project_root)
    started = time.perf_counter()
    context = RunContext(project_root=root, gate="G3", config_sha256=config.sha256,
                         config_path=config.path, runs_dir=runs_dir)
    context.snapshot_config(config.path)
    (context.directory / "figures").mkdir(parents=True, exist_ok=True)
    context.log(f"G3 demo: assemblies={assemblies} workers={workers} "
                f"condition={condition} model={config.calibration.model}")

    runner = SceneRunner(config, estimators=_build_estimators(), max_cached_models=8)
    test_distances = tuple(config.dataset.test_distances)
    calibration_distances = _pick_calibration_distances(config)
    context.log(f"test distances: {list(test_distances)}; "
                f"calibration distances: {len(calibration_distances)} points")

    perturbations = _demo_perturbations(config, assemblies)
    scenes = [
        {"distance": float(d), "condition": condition, "repeat": 0, "namespace": "G3D"}
        for d in test_distances
    ]

    payloads = []
    for name, design in FROZEN_DESIGNS.items():
        payloads.append(_assembly_payload(
            config, _assemble(perturbations, design, config), scenes, ESTIMATORS,
            candidate=name, design=design,
        ))

    raw_rows: list[dict[str, Any]] = []
    for index, payload in enumerate(payloads, start=1):
        chunk = assembly_chunk(payload)
        raw_rows.extend(chunk)
        context.log(f"  candidate {index}/{len(payloads)} done ({len(chunk)} rows)")

    # factory calibration per candidate, medium condition, same estimator set
    per_candidate: dict[str, Any] = {}
    sample_rows: list[dict[str, Any]] = []
    for name, design in FROZEN_DESIGNS.items():
        fits = _factory_calibration(config, runner, design, ESTIMATORS,
                                    calibration_distances, condition_name=condition)
        rows = [row for row in raw_rows if row.get("candidate") == name]
        scored = _score_rows(rows, fits, strategy="A")
        for row in scored:
            sample_rows.append({
                "candidate": name,
                "assembly_id": row["assembly_id"],
                "distance_mm": row["distance_mm"],
                "condition": row["condition"],
                "estimator": row["estimator"],
                "u_gt_px": row["u_gt_px"],
                "u_hat_px": row["u_hat_px"],
                "Z_hat_mm": row["Z_hat_mm"],
                "signed_error_mm": row["signed_error_mm"],
                "valid": row["valid"],
                "qual": row["estimator_status"],
                "flags": row["quality_flags"],
                "capture_fraction": row["capture_fraction"],
                "ray_success_fraction": row["ray_success_fraction"],
                "kernel_support": row["kernel_support"],
                "saturation_full_well": row["saturation_full_well"],
                "saturation_adc": row["saturation_adc"],
            })
        per_candidate[name] = {
            "design": {
                "baseline_mm": design.baseline_mm,
                "focal_length_mm": design.focal_length_mm,
                "theta_deg": design.theta_deg,
            },
            "overall": _metrics(scored),
            "by_estimator": _group_metrics(scored, "estimator"),
            "by_distance": _group_metrics(scored, "distance_mm"),
            "calibration": {
                estimator: {
                    "model": fit.model,
                    "params": list(fit.params),
                    "rms_px": fit.residual_rms_px,
                    "n_points": fit.n_points,
                    "status": fit.status.value,
                }
                for estimator, fit in fits.items()
            },
        }

    n_frames_expected = len(perturbations) * len(test_distances)
    wall = time.perf_counter() - started

    _write_csv(context.path("independent_validation/sampled_results.csv"), sample_rows)

    summary = {
        "demo": True,
        "n_assemblies": len(perturbations),
        "n_test_distances": len(test_distances),
        "test_distances": list(test_distances),
        "n_frames_expected_per_candidate": n_frames_expected,
        "n_estimators": len(ESTIMATORS),
        "estimators": list(ESTIMATORS),
        "condition": condition,
        "candidates": {name: data["overall"] for name, data in per_candidate.items()},
        "by_estimator": {name: data["by_estimator"] for name, data in per_candidate.items()},
        "by_distance": {name: data["by_distance"] for name, data in per_candidate.items()},
        "calibration": {name: data["calibration"] for name, data in per_candidate.items()},
    }
    _write_json(context.path("independent_validation/summary.json"), summary)
    _write_json(context.path("metrics.json"), {
        "schema_version": "3.0",
        "gate": "G3",
        "report_kind": "G3_DEMO",
        "case_id": config.case_id,
        "model_level": "L1-approximate",
        "demo": summary,
        "wall_s": wall,
        "worker_count": workers,
    })

    # gate checks: only checks this demo can actually support
    observed_support = [
        row["kernel_support"] for row in sample_rows if row.get("kernel_support") is not None
    ]
    checks = {
        "D1_all_candidates_present": {
            "value": sorted(per_candidate),
            "threshold": "baseline, nominal, robust",
            "pass": sorted(per_candidate) == sorted(FROZEN_DESIGNS),
            "what": "every frozen design was executed, none silently dropped",
        },
        "D2_frame_count": {
            "value": len(sample_rows),
            "threshold": n_frames_expected * len(FROZEN_DESIGNS) * len(ESTIMATORS),
            "pass": len(sample_rows) == n_frames_expected * len(FROZEN_DESIGNS) * len(ESTIMATORS),
            "what": "rows = assemblies x distances x candidates x estimators",
        },
        "D3_failures_recorded_not_hidden": {
            "value": {name: data["overall"]["failure_rate"]
                      for name, data in per_candidate.items()},
            "threshold": "failure_rate present for every candidate",
            "pass": all(data["overall"]["failure_rate"] is not None
                        for data in per_candidate.values()),
            "what": "a demo that only reports successes is not evidence",
        },
        "D4_kernel_support_below_prereg": {
            "value": {"min": min(observed_support) if observed_support else None,
                      "max": max(observed_support) if observed_support else None,
                      "prereg_threshold": 0.999},
            "threshold": "recorded, not gated: HC3 as registered is known unreachable",
            "pass": bool(observed_support) and max(observed_support) < 0.999,
            "what": "confirms the demo inherits the G2 HC3 conflict rather than hiding it",
        },
        "D5_not_a_g2_replacement": {
            "value": {"demo_assemblies": len(perturbations),
                      "g2_assemblies": 2000},
            "threshold": "demo N < G2 N, therefore not comparable",
            "pass": len(perturbations) < 2000,
            "what": "demo numbers may never be quoted as G2 numbers",
        },
    }

    figures: list[str] = []
    # NOTE: build_g2_figures is NOT reused wholesale.  07_calibration_strategies
    # requires summary["strategy_b"], which a demo run does not have; calling it
    # would either crash or, worse, force us to invent a strategy-B block.  Each
    # figure is therefore built from data this run actually produced.
    for builder, label in (
        (_fig_demo_layout, "layout"),
        (_fig_demo_error_vs_distance, "error_vs_distance"),
        (_fig_demo_candidates, "candidates"),
        (_fig_demo_support, "support"),
    ):
        try:
            produced = builder(context.directory, config, per_candidate)
            figures.extend(produced)
            context.log(f"  figure {label}: {produced}")
        except Exception as exc:  # noqa: BLE001 - a missing figure must not kill the run
            context.log(f"  FIGURE_FAILED {label}: {type(exc).__name__}: {exc}")

    context.write_json("provenance.json", context.provenance(
        model_level="L1-approximate",
        seeds=[config.run.seed + 770_001],
        extra={
            "demo_boundary": {
                "is_g2_rerun": False,
                "n_assemblies": len(perturbations),
                "n_test_distances": len(test_distances),
                "condition": condition,
                "comparable_to_g2": False,
                "reason": "reduced assembly panel and single illumination condition; "
                          "G2 main panel is 2000 assemblies",
                "inherits_g2_hc3_conflict": True,
            },
            "reused_scoring": "optisys.gates.g2._score_rows / _metrics",
        },
    ))

    status = "PASS" if all(c["pass"] for c in checks.values()) else "FAIL"
    context.finalise(status, checks, "DEMO_ONLY_NOT_A_G2_CONFIRMATION", extra={
        "demo": True,
        "figures": figures,
        "wall_s": wall,
        "assemblies": len(perturbations),
        "not_evidence_of": [
            "G2 pre-registration compliance",
            "physical measurement",
            "any G4 claim",
        ],
    })

    result = {
        "run_id": context.run_id,
        "run_dir": str(context.directory),
        "status": status,
        "wall_s": wall,
        "assemblies": len(perturbations),
        "test_distances": list(test_distances),
        "condition": condition,
        "rows": len(sample_rows),
        "candidates": {name: data["overall"] for name, data in per_candidate.items()},
        "figures": figures,
        "gate_checks": checks,
    }
    print(f"G3 demo run: {context.directory}")
    print(f"status={status} wall={wall:.1f}s rows={len(sample_rows)}")
    return context, result


def _pick_calibration_distances(config: ResolvedG2Config) -> tuple[float, ...]:
    """Nine calibration distances, none of them a test distance."""

    test = set(config.dataset.test_distances)
    candidates = [d for d in config.calibration_distances if d not in test]
    if len(candidates) < 9:
        raise ValueError(
            f"config provides only {len(candidates)} calibration distances "
            "disjoint from the test set; at least 9 are required")
    # even spread over the available list, keeping the endpoints
    if len(candidates) == 9:
        return tuple(candidates)
    step = (len(candidates) - 1) / 8.0
    picked = sorted({candidates[min(len(candidates) - 1, round(i * step))]
                     for i in range(9)})
    return tuple(picked)


def _build_estimators():
    from optisys.estimators import build_estimators_g2

    return [e for e in build_estimators_g2() if e.name in ESTIMATORS]


# ---------------------------------------------------------------------------
# figures (built only from data this run produced)
# ---------------------------------------------------------------------------
def _style(ax, title: str, xlabel: str, ylabel: str) -> None:
    ax.set_title(title, fontsize=10)
    ax.set_xlabel(xlabel, fontsize=8)
    ax.set_ylabel(ylabel, fontsize=8)
    ax.tick_params(labelsize=7)
    ax.grid(True, color="#d8dee6", linewidth=0.6, alpha=0.8)
    ax.set_axisbelow(True)


def _fig_demo_layout(directory: Path, config: ResolvedG2Config,
                     per_candidate: dict[str, Any]) -> list[str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    fig, ax = plt.subplots(figsize=(7.2, 3.0), dpi=140)
    B = config.baseline_mm
    z0, z1 = config.z_min_mm, config.z_max_mm
    ax.plot([0], [0], marker="s", color="#1f4e79", markersize=8,
            label="camera pinhole O")
    ax.plot([B], [0], marker="o", color="#a83232", markersize=7, label="laser (B,0)")
    for z in (z0, 0.5 * (z0 + z1), z1):
        x = B - z * np.tan(config.theta_rad)
        ax.plot([B, x], [0, z], color="#a83232", linewidth=0.9, alpha=0.8)
        ax.plot([x], [z], marker="x", color="#a83232", markersize=5)
        ax.plot([0, x], [0, z], color="#1f4e79", linewidth=0.7, linestyle="--", alpha=0.7)
        ax.annotate(f"Z={z:.0f} mm", (x, z), textcoords="offset points",
                    xytext=(6, 4), fontsize=6)
    ax.plot([0, 0], [0, z1 * 0.55], color="#1f4e79", linewidth=1.6)
    ax.set_xlim(-5, B + 12)
    ax.set_ylim(-8, z1 * 0.62)
    _style(ax, "Coplanar layout: pinhole camera + laser baseline (mm)",
           "X [mm]", "Z [mm]")
    ax.legend(fontsize=6, loc="upper right")
    path = directory / "figures" / "01_optical_layout.png"
    fig.tight_layout()
    fig.savefig(path)
    plt.close(fig)
    return [path.name]


def _fig_demo_error_vs_distance(directory: Path, config: ResolvedG2Config,
                                per_candidate: dict[str, Any]) -> list[str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    fig, axes = plt.subplots(1, 2, figsize=(9.4, 3.0), dpi=140)
    colors = {"baseline": "#7f7f7f", "nominal": "#1f4e79", "robust": "#a83232"}
    produced = False
    for name, data in per_candidate.items():
        rows = data.get("by_distance") or []
        if not rows:
            continue
        z = [row["distance_mm"] for row in rows]
        rmse = [row.get("rmse_mm") if row.get("rmse_mm") is not None else np.nan
                for row in rows]
        fail = [row.get("failure_rate") if row.get("failure_rate") is not None else np.nan
                for row in rows]
        axes[0].plot(z, rmse, marker="o", markersize=3, linewidth=1.2,
                     color=colors.get(name, "#333"), label=name)
        axes[1].plot(z, fail, marker="o", markersize=3, linewidth=1.2,
                     color=colors.get(name, "#333"), label=name)
        produced = True
    if not produced:
        plt.close(fig)
        return []
    _style(axes[0], "RMSE vs distance", "Z [mm]", "RMSE [mm]")
    _style(axes[1], "Failure rate vs distance", "Z [mm]", "failure rate")
    axes[0].legend(fontsize=7)
    axes[1].legend(fontsize=7)
    fig.suptitle("G3 demo run — reduced panel, medium condition only", fontsize=9)
    fig.tight_layout()
    path = directory / "figures" / "02_error_vs_distance.png"
    fig.savefig(path)
    plt.close(fig)
    return [path.name]


def _fig_demo_candidates(directory: Path, config: ResolvedG2Config,
                         per_candidate: dict[str, Any]) -> list[str]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    names = ["baseline", "nominal", "robust"]
    if not any(name in per_candidate for name in names):
        return []
    fig, axes = plt.subplots(1, 3, figsize=(10.0, 3.0), dpi=140)
    for ax, key, label in (
        (axes[0], "rmse_mm", "RMSE [mm]"),
        (axes[1], "p95_abs_mm", "P95 |error| [mm]"),
        (axes[2], "failure_rate", "failure rate"),
    ):
        values = []
        for name in names:
            row = (per_candidate.get(name) or {}).get("overall") or {}
            value = row.get(key)
            values.append(value if value is not None else np.nan)
        ax.bar(names, values, color=["#7f7f7f", "#1f4e79", "#a83232"])
        _style(ax, label, "", label)
    # No "best" annotation on purpose: robust wins RMSE and loses failure rate.
    fig.suptitle("G3 demo — three metrics side by side, no single ranking",
                 fontsize=9)
    fig.tight_layout()
    path = directory / "figures" / "03_candidate_comparison.png"
    fig.savefig(path)
    plt.close(fig)
    return [path.name]


def _fig_demo_support(directory: Path, config: ResolvedG2Config,
                      per_candidate: dict[str, Any]) -> list[str]:
    """Kernel support vs the 0.999 pre-registered line, on purpose."""

    import csv

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    path = directory / "independent_validation" / "sampled_results.csv"
    if not path.is_file():
        return []
    values: dict[str, list[float]] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            try:
                value = float(row["kernel_support"])
            except (KeyError, TypeError, ValueError):
                continue
            values.setdefault(row["candidate"], []).append(value)
    if not values:
        return []
    fig, ax = plt.subplots(figsize=(6.4, 3.0), dpi=140)
    positions = np.arange(len(values))
    ax.boxplot([values[name] for name in values], positions=positions, widths=0.5)
    ax.set_xticks(positions)
    ax.set_xticklabels(list(values))
    ax.axhline(0.999, color="#a83232", linestyle="--", linewidth=1.0,
               label="HC3 pre-registered 0.999")
    ax.axhline(config.constraints.min_kernel_support, color="#1f4e79",
               linestyle=":", linewidth=1.0, label="HC3 as-run 0.950")
    ax.set_ylim(0.94, 1.002)
    _style(ax, "Kernel support vs the two HC3 thresholds", "", "kernel_support")
    ax.legend(fontsize=7, loc="lower right")
    fig.tight_layout()
    out = directory / "figures" / "04_kernel_support.png"
    fig.savefig(out)
    plt.close(fig)
    return [out.name]