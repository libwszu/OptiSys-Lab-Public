"""Render the cross-scenario S6-C assembly evidence without changing results."""

from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "20261021_024715_S6_P1"
OUT = ROOT / "runs" / RUN_ID / "s6_c_assemblies"
ORDER = ("zero", "tight_0p5x", "nominal_1x", "stress_2x")
LABELS = ("Zero", "Tight 0.5x", "Nominal 1x", "Stress 2x")


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_csv(path: Path, rows: list[dict]) -> None:
    fields = list(rows[0])
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader(); writer.writerows(rows)


def render() -> dict:
    stats_path = OUT / "assembly_statistics_programmatic.json"
    stats = json.loads(stats_path.read_text(encoding="utf-8"))
    scenario_stats = stats["scenarios"]
    rows = []
    for name, label in zip(ORDER, LABELS, strict=True):
        s = scenario_stats[name]
        rows.append({
            "scenario": name, "plot_label": label,
            "n_complete_pairs": s["n_complete_pairs"],
            "mean_capture_baseline125": s["mean_capture_baseline125"],
            "mean_capture_candidate135": s["mean_capture_candidate135"],
            "mean_delta_capture": s["mean_delta_capture_candidate_minus_baseline"],
            "mean_delta_ci95_low": s["paired_mean_delta_capture_ci95"][0],
            "mean_delta_ci95_high": s["paired_mean_delta_capture_ci95"][1],
            "p05_capture_baseline125": s["p05_capture_baseline125"],
            "p05_capture_candidate135": s["p05_capture_candidate135"],
            "p05_paired_delta_capture": s["p05_paired_delta_capture"],
            "p05_delta_bootstrap_ci95_low": s["p05_paired_delta_bootstrap_ci95"][0],
            "p05_delta_bootstrap_ci95_high": s["p05_paired_delta_bootstrap_ci95"][1],
            "invalid_rate_baseline125": s["invalid_assembly_rate_baseline125"],
            "invalid_rate_candidate135": s["invalid_assembly_rate_candidate135"],
            "r90_p95_baseline125_mm": s["all_plane_r90_p95_mm_baseline125"],
            "r90_p95_candidate135_mm": s["all_plane_r90_p95_mm_candidate135"],
            "failure_weight_delta_json": json.dumps(
                s["failure_weight_mean_delta_candidate_minus_baseline"], sort_keys=True),
        })
    csv_path = OUT / "assembly_robustness_plot_data.csv"
    _write_csv(csv_path, rows)
    x = np.arange(len(rows))
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.4), constrained_layout=True)
    ax = axes[0]
    base = np.asarray([r["mean_capture_baseline125"] for r in rows]) * 100.0
    cand = np.asarray([r["mean_capture_candidate135"] for r in rows]) * 100.0
    p05base = np.asarray([r["p05_capture_baseline125"] for r in rows]) * 100.0
    p05cand = np.asarray([r["p05_capture_candidate135"] for r in rows]) * 100.0
    width = 0.34
    ax.bar(x - width / 2, base, width, color="#315b9a", alpha=0.75, label="Baseline 125 mm mean")
    ax.bar(x + width / 2, cand, width, color="#c44c39", alpha=0.75, label="Candidate 135 mm mean")
    ax.scatter(x - width / 2, p05base, marker="v", color="#102b52", s=48, zorder=3,
               label="Baseline assembly P05")
    ax.scatter(x + width / 2, p05cand, marker="v", color="#7b2118", s=48, zorder=3,
               label="Candidate assembly P05")
    ax.set_xticks(x, LABELS); ax.set_ylim(0, 100)
    ax.set_ylabel("Capture fraction (% of all input source weight)")
    ax.set_title("Assembly capture distribution")
    ax.grid(axis="y", alpha=0.25); ax.legend(fontsize=8, loc="lower left")

    ax = axes[1]
    mean = np.asarray([r["mean_delta_capture"] for r in rows]) * 100.0
    mean_lo = np.asarray([r["mean_delta_ci95_low"] for r in rows]) * 100.0
    mean_hi = np.asarray([r["mean_delta_ci95_high"] for r in rows]) * 100.0
    p05 = np.asarray([r["p05_paired_delta_capture"] for r in rows]) * 100.0
    p05_lo = np.asarray([r["p05_delta_bootstrap_ci95_low"] for r in rows]) * 100.0
    p05_hi = np.asarray([r["p05_delta_bootstrap_ci95_high"] for r in rows]) * 100.0
    y1, y2 = x + 0.10, x - 0.10
    ax.errorbar(mean, y1, xerr=[mean - mean_lo, mean_hi - mean], fmt="o",
                color="#315b9a", capsize=4, label="Paired mean delta, assembly bootstrap CI95")
    ax.errorbar(p05, y2, xerr=[p05 - p05_lo, p05_hi - p05], fmt="s",
                color="#c44c39", capsize=4, label="Paired P05 delta, assembly bootstrap CI95")
    ax.axvline(0, color="black", linewidth=1, alpha=0.7)
    ax.set_yticks(x, LABELS); ax.set_xlabel("Candidate 135 mm minus baseline 125 mm (percentage points)")
    ax.set_title("Mean gain and paired lower tail")
    ax.grid(axis="x", alpha=0.25); ax.legend(fontsize=8, loc="lower right")
    fig.suptitle("S6-C assumed P1 assembly robustness (simulated tolerances)", fontsize=12)
    png = OUT / "s6_assembly_robustness.png"
    fig.savefig(png, dpi=170); plt.close(fig)
    record = {
        "schema": "optisys.s6.assembly_figure/1", "run_id": RUN_ID,
        "source_statistics_sha256": _sha(stats_path),
        "plot_data": {"path": csv_path.name, "bytes": csv_path.stat().st_size,
                      "sha256": _sha(csv_path)},
        "figure": {"path": png.name, "bytes": png.stat().st_size, "sha256": _sha(png)},
        "warning_count": 0,
        "note": "Error bars resample assembly_id; paired P05 panel exposes the stress_2x lower-tail reversal.",
        "rendered_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (OUT / "assembly_figure_metadata.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False, indent=2))
    return record


if __name__ == "__main__":
    render()
