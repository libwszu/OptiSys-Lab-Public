"""PRE-G3-05: are strategy A and strategy B comparable?

They are not, and the G2 report invites the reader to subtract them anyway:

    "Recalibration is worth roughly 1.5 mm (baseline) to 3 mm (robust)"

A and B differ in assembly count, estimator set, table scope, and calibration
frame count.  This script puts every difference in one table and stops there:
it does not invent an A/B gain.  A proper gain would need strategy B re-run on
the same 2000 assemblies with all three estimators, which is out of the G3
budget and is declared as `NOT_RUN`.

It also corrects the calibration-frame count: the report says five frames per
unit, the code path takes nine.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
G2_RUN = ROOT / "runs" / "20261019_191117_G2_52369787"
OUT = ROOT / "docs" / "g3" / "evidence"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    summary = json.loads((G2_RUN / "independent_validation" / "summary.json")
                         .read_text(encoding="utf-8"))
    budget = json.loads((G2_RUN / "optimization" / "budget_usage.json")
                        .read_text(encoding="utf-8"))

    # --- factual table ----------------------------------------------------
    rows: list[dict[str, Any]] = []
    for name in ("baseline", "nominal", "robust"):
        a = summary["candidates"][name]
        b = summary["strategy_b"][name]
        rows.append({
            "candidate": name,
            "strategy": "A",
            "n_assemblies": summary["n_final_assemblies"],
            "n_estimators": 3,
            "estimators": "centroid;gaussian_2d;gaussian_2d_integrated",
            "n_distances": len(summary["test_distances"]),
            "conditions": "medium",
            "n_attempted": a["n_attempted"],
            "n_valid": a["n_valid"],
            "failure_rate": a["failure_rate"],
            "rmse_mm": a["rmse_mm"],
            "p95_abs_mm": a["p95_abs_mm"],
            "bias_mm": a["bias_mm"],
            "calibration_frames_per_unit": 0,
            "calibration_scope": "one factory fit on the nominal unit, reused",
        })
        rows.append({
            "candidate": name,
            "strategy": "B",
            "n_assemblies": summary["subsets"]["strategy_b"],
            "n_estimators": 1,
            "estimators": "gaussian_2d_integrated",
            "n_distances": len(summary["test_distances"]),
            "conditions": "medium",
            "n_attempted": b["n_attempted"],
            "n_valid": b["n_valid"],
            "failure_rate": b["failure_rate"],
            "rmse_mm": b["rmse_mm"],
            "p95_abs_mm": b["p95_abs_mm"],
            "bias_mm": b["bias_mm"],
            "calibration_frames_per_unit": 9,
            "calibration_scope": "per-unit fit on each assembly's own optics",
        })

    with (OUT / "G2_STRATEGY_COMPARABILITY.csv").open("w", encoding="utf-8",
                                                     newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    # --- how many of the 200 B assemblies also appear in A? ---------------
    sb = list(csv.DictReader((G2_RUN / "independent_validation" / "strategy_b_baseline.csv")
                             .open(encoding="utf-8")))
    b_assemblies = {row["assembly_id"] for row in sb}
    heldout = list(csv.DictReader((G2_RUN / "independent_validation" / "heldout_assemblies.csv")
                                  .open(encoding="utf-8")))
    final_assemblies = {row["assembly_id"] for row in heldout}

    # --- calibration frame count: what the code actually did --------------
    # factory_calibration in summary.json records n_points for strategy A.
    factory_points = {name: {est: payload["n_points"]
                             for est, payload in summary["factory_calibration"][name].items()}
                      for name in ("baseline", "nominal", "robust")}

    verdict = {
        "gate": "PRE-G3-05",
        "issue": "strategy A and B are not on the same footing",
        "comparability": "NOT_DIRECTLY_COMPARABLE",
        "dimensions_that_differ": [
            {"dimension": "assembly count", "A": summary["n_final_assemblies"],
             "B": summary["subsets"]["strategy_b"]},
            {"dimension": "estimators", "A": 3, "B": 1},
            {"dimension": "attempted rows", "A": 42000, "B": 1400},
            {"dimension": "calibration frames per unit", "A": 0, "B": 9},
            {"dimension": "calibration object", "A": "factory nominal unit",
             "B": "each assembly's own perturbed optics"},
        ],
        "subset_relationship": {
            "b_assemblies": len(b_assemblies),
            "final_assemblies": len(final_assemblies),
            "b_subset_of_final": b_assemblies <= final_assemblies,
            "n_b_assemblies_in_final": len(b_assemblies & final_assemblies),
            "note": ("B uses the first 200 of the same FIN#### draw, so the units "
                     "overlap; the estimator set and the calibration regime do not"),
        },
        "calibration_frame_count_correction": {
            "report_claim": 5,
            "code_path": ("src/optisys/gates/g2.py:1046 "
                          "_evenly_spaced(calibration_distances, 5 if quick else 9)"),
            "observed_n_points_strategy_A": factory_points,
            "actual": 9,
            "verdict": "REPORT_TEXT_WRONG_CODE_RIGHT",
            "explanation": ("the non-quick path takes 9 calibration distances; the "
                            "'5' in the report is the quick-mode value, so the cost "
                            "of strategy B was understated by 80%"),
        },
        "invalid_gain_quote": {
            "quoted": "recalibration is worth roughly 1.5 mm (baseline) to 3 mm (robust)",
            "status": "WITHDRAWN",
            "why": ("subtracting a 200-assembly single-estimator number from a "
                    "2000-assembly three-estimator number mixes populations; the "
                    "per-estimator A value for gaussian_2d_integrated is the only "
                    "legitimate comparison point, and even then the assembly count "
                    "and failure denominators still differ"),
        },
        "legitimate_comparison_available": {
            "per_estimator_A_vs_B": {
                name: {
                    "A_rmse_mm_gaussian_2d_integrated":
                        summary["by_estimator"][name][2]["rmse_mm"]
                        if len(summary["by_estimator"][name]) > 2 else None,
                    "B_rmse_mm": summary["strategy_b"][name]["rmse_mm"],
                    "A_failure_rate_gaussian_2d_integrated":
                        summary["by_estimator"][name][2]["failure_rate"]
                        if len(summary["by_estimator"][name]) > 2 else None,
                    "B_failure_rate": summary["strategy_b"][name]["failure_rate"],
                }
                for name in ("baseline", "nominal", "robust")
            },
            "caveat": ("still not a paired test: B covers 200 of the 2000 assemblies. "
                       "A paired A/B bootstrap on the 200 shared assemblies with the "
                       "same estimator is the minimum honest comparison, and that "
                       "re-run is budget-bound"),
            "paired_rerun": "NOT_RUN",
            "paired_rerun_reason": ("strategy B on 200 assemblies x 7 distances x 1 "
                                    "estimator took ~4 minutes per candidate during "
                                    "the original run; G3 does not re-execute it"),
        },
        "required_disclosure": [
            "any A/B table shows N=2000/3 estimators and N=200/1 estimator side by side",
            "the 'recalibration is worth X mm' sentence is withdrawn",
            "the 5-calibration-frame claim is corrected to 9",
        ],
        "artifacts": ["docs/g3/evidence/G2_STRATEGY_COMPARABILITY.csv"],
    }

    (OUT / "G2_STRATEGY_COMPARABILITY.json").write_text(
        json.dumps(verdict, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(verdict["comparability"])
    print("calibration frames:", verdict["calibration_frame_count_correction"]["actual"])
    print(json.dumps(verdict["legitimate_comparison_available"]["per_estimator_A_vs_B"],
                     indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())