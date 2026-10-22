"""PRE-G3-03: recompute the condition-stratified sub-panel with the correct design.

The frozen run's stratified panel is unusable: the loop that built it inherited
``design`` from the strategy-B loop, so baseline and nominal were assembled with
the robust geometry (B=34.4 mm, f=7.272 mm, theta=4 deg).

This script rebuilds that panel exactly as the fixed code would:

* same 200 subset assemblies (the first 200 of the frozen ``G2F`` draw, read
  from ``heldout_assemblies.csv`` so the perturbation vectors are identical),
* same distances (the 7 final-test distances),
* same conditions (strong, weak),
* same estimators, same namespace ``G2F_C``, same seed rule,
* same factory calibration objects, taken from the frozen ``summary.json``,

and writes the corrected metrics next to the old ones plus the per-candidate
difference.

Read-only with respect to the frozen run: output goes to
``artifacts/g3/pre/stratified_repair/``.
"""

from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
G2_RUN = ROOT / "runs" / "20261019_191117_G2_52369787"
OUT = ROOT / "artifacts" / "g3" / "pre" / "stratified_repair"


def load_subset_perturbations(path: Path, config: Any, n: int):
    from optisys.tolerance.perturbations import AssemblyPerturbation

    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    perturbations = []
    for row in rows:
        perturbations.append(AssemblyPerturbation(
            assembly_id=row["assembly_id"],
            d_baseline_mm=float(row["d_baseline_mm"]),
            d_theta_rad=float(row["d_theta_rad"]),
            d_focal_relative=float(row["d_focal_relative"]),
            d_cx_px=float(row["d_cx_px"]),
            d_focus_mm=float(row["d_focus_mm"]),
        ))
    return perturbations[:n]


def rebuild_fit(payload: dict[str, Any]):
    from optisys.calibration.assembly_strategies import CalibrationFit
    from optisys.errors import Status

    return CalibrationFit(
        payload["estimator"], payload["model"], tuple(payload["params"]),
        payload["z_range_mm"][0], payload["z_range_mm"][1],
        payload["n_points"], payload["residual_rms_px"],
        Status(payload["status"]), payload.get("assembly_id", ""))


def main() -> int:
    from optisys.config_g2 import load_config_g2
    from optisys.gates import g2 as g2mod
    from optisys.optimization.search_space import Design
    from optisys.tolerance.assembly_model import SceneRunner

    OUT.mkdir(parents=True, exist_ok=True)
    config = load_config_g2(ROOT / "configs" / "triangulation_g2_l1.yaml")
    summary = json.loads((G2_RUN / "independent_validation" / "summary.json")
                         .read_text(encoding="utf-8"))
    frozen = json.loads((G2_RUN / "optimization" / "candidates_frozen.json")
                        .read_text(encoding="utf-8"))
    n_subset = summary["subsets"]["stratified"]
    test_distances = tuple(summary["test_distances"])

    perturbations = load_subset_perturbations(
        G2_RUN / "independent_validation" / "heldout_assemblies.csv", config, n_subset)
    print(f"subset assemblies: {len(perturbations)}")

    runner = SceneRunner(config)
    cond_scenes = g2mod._scenes(test_distances, ("strong", "weak"), "G2F_C")

    results: dict[str, Any] = {}
    started = time.perf_counter()
    for cand in frozen["candidates"]:
        name = cand["name"]
        design = Design(baseline_mm=cand["design"]["baseline_mm"],
                        focal_length_mm=cand["design"]["focal_length_mm"],
                        theta_deg=cand["design"]["theta_deg"])
        fits = {est: rebuild_fit(payload)
                for est, payload in summary["factory_calibration"][name].items()}
        assemblies = g2mod._assemble(perturbations, design, config)
        payloads = [
            g2mod._assembly_payload(config, group, cond_scenes,
                                    g2mod.ESTIMATORS_FAST, name, design=design)
            for group in g2mod._chunk(assemblies, 20)
        ]
        rows = g2mod._run_chunks(payloads, 1, lambda message: print(f"  {message}"))
        scored = g2mod._score_rows(rows, fits, strategy="A")
        with (OUT / f"stratified_{name}.csv").open("w", encoding="utf-8",
                                                    newline="") as handle:
            fields = ["assembly_id", "distance_mm", "condition", "estimator",
                      "u_gt_px", "u_hat_px", "Z_hat_mm", "signed_error_mm",
                      "valid", "kernel_support", "optical_status",
                      "estimator_status"]
            writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(scored)
        results[name] = {
            "design": design.as_row(),
            "overall": g2mod._metrics(scored),
            "by_condition": g2mod._group_metrics(scored, "condition"),
            "by_estimator": g2mod._group_metrics(scored, "estimator"),
        }
        print(f"{name}: {results[name]['overall']}")

    elapsed = time.perf_counter() - started

    comparison = []
    for name in ("baseline", "nominal", "robust"):
        old = summary["stratified"][name]
        new = results[name]
        for condition in ("strong", "weak"):
            old_c = next((row for row in old["by_condition"]
                          if row["condition"] == condition), {})
            new_c = next((row for row in new["by_condition"]
                          if row["condition"] == condition), {})
            comparison.append({
                "candidate": name,
                "condition": condition,
                "old_design": "",  # filled below
                "new_design": new["design"],
                "old_n_valid": old_c.get("n_valid"),
                "old_n_attempted": old_c.get("n_attempted"),
                "old_rmse_mm": old_c.get("rmse_mm"),
                "old_failure_rate": old_c.get("failure_rate"),
                "new_n_valid": new_c.get("n_valid"),
                "new_n_attempted": new_c.get("n_attempted"),
                "new_rmse_mm": new_c.get("rmse_mm"),
                "new_failure_rate": new_c.get("failure_rate"),
                "rmse_delta_mm": (None if new_c.get("rmse_mm") is None
                                  or old_c.get("rmse_mm") is None
                                  else new_c["rmse_mm"] - old_c["rmse_mm"]),
                "failure_delta": (None if new_c.get("failure_rate") is None
                                  or old_c.get("failure_rate") is None
                                  else new_c["failure_rate"] - old_c["failure_rate"]),
            })

    # the old panel has no per-candidate design recorded; the defect is that
    # every candidate used the last bound design, i.e. robust's
    robust_design = next(c for c in frozen["candidates"] if c["name"] == "robust")["design"]
    for row in comparison:
        if row["candidate"] in ("baseline", "nominal"):
            row["old_design"] = (
                f"robust-geometry (BUG): B={robust_design['baseline_mm']} "
                f"f={robust_design['focal_length_mm']:.6f} "
                f"theta={robust_design['theta_deg']}"
            )
        else:
            row["old_design"] = "robust (correct by coincidence)"

    with (OUT / "G2_STRATIFIED_RECOMPARISON.csv").open("w", encoding="utf-8",
                                                       newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(comparison[0]))
        writer.writeheader()
        writer.writerows(comparison)

    payload = {
        "gate": "PRE-G3-03",
        "n_assemblies": len(perturbations),
        "n_distances": len(test_distances),
        "conditions": ["strong", "weak"],
        "estimators": list(g2mod.ESTIMATORS_FAST),
        "namespace": "G2F_C",
        "wall_s": elapsed,
        "processes": 1,
        "corrected": results,
        "frozen_reference": summary["stratified"],
        "comparison": comparison,
        "main_panel_unaffected_evidence": {
            "claim": ("the strategy-A main panel and the strategy-B subset each bind "
                      "their own design before use, so the stale variable could only "
                      "reach the third loop"),
            "structural_test": "tests/integration/test_g3_pre_g3_03.py::"
                               "test_every_assembling_loop_binds_its_own_design",
            "data_check": ("sampled_results.csv rows for baseline and nominal have "
                           "signed_error_mm consistent with their own design's "
                           "factory calibration parameters, not robust's"),
        },
    }
    (OUT / "stratified_repair.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"wall: {elapsed:.1f} s")
    print(f"written: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())