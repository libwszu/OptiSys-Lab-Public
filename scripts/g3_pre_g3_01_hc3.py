"""PRE-G3-01: hard-constraint conflict between the G2 pre-registration and the
configuration that was actually executed.

Produces three artifacts under ``docs/g3/evidence/``:

* ``G2_PREREG_VS_ASRUN.csv`` — item-by-item comparison of the pre-registered
  hard constraints, the shipped configuration, the frozen snapshot inside the
  run, and the code that evaluates them.
* ``G2_HC3_THRESHOLD_SCAN.csv`` — kernel-support feasibility of the three
  frozen candidates at four thresholds (0.950 / 0.975 / 0.990 / 0.999) for
  every constraint-probe distance and for every observed final-panel row.
* ``G2_HC3_SUMMARY.json`` — machine-readable verdict.

Read-only.  Nothing here modifies a frozen run.
"""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
G2_RUN = ROOT / "runs" / "20261019_191117_G2_52369787"
OUT = ROOT / "docs" / "g3" / "evidence"

THRESHOLDS = (0.950, 0.975, 0.990, 0.999)
CONSTRAINT_DISTANCES = (100.0, 200.0, 300.0)
FULL_WELL_E = 15000.0
PEAK_FRACTION = 0.80
MIN_RAY_SUCCESS = 0.90


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


# ---------------------------------------------------------------------------
def prereg_vs_asrun() -> list[dict[str, Any]]:
    """Compare declared hard constraints across the four evidence sources."""

    return [
        {
            "constraint_id": "HC1",
            "quantity": "chief ray inside sensor for every Z in [100, 300]",
            "prereg_value": "24 <= u <= 1255 px",
            "asrun_config_value": "sensor_margin_px = 24.0, width 1280 px -> 24..1255",
            "run_snapshot_value": "sensor_margin_px = 24.0",
            "code_site": "src/optisys/optimization/constraints.py:66-76",
            "match": "MATCH",
            "notes": "identical",
        },
        {
            "constraint_id": "HC2",
            "quantity": "ray success fraction (no vignetting)",
            "prereg_value": ">= 0.90",
            "asrun_config_value": "min_ray_success = 0.90",
            "run_snapshot_value": "min_ray_success = 0.90",
            "code_site": "src/optisys/optimization/constraints.py:95-96",
            "match": "MATCH",
            "notes": "identical",
        },
        {
            "constraint_id": "HC3",
            "quantity": "kernel support fraction",
            "prereg_value": ">= 0.999",
            "asrun_config_value": "min_kernel_support = 0.950",
            "run_snapshot_value": "min_kernel_support = 0.95",
            "code_site": "src/optisys/optimization/constraints.py:97-98",
            "match": "CONFLICT",
            "notes": ("pre-registered threshold is 5.2x stricter than the executed one; "
                      "100% of the 126000 final-panel rows sit below 0.999 for all three "
                      "candidates, so no frozen design would be feasible under HC3 as written"),
        },
        {
            "constraint_id": "HC4",
            "quantity": "peak signal fraction of full well",
            "prereg_value": "<= 0.80 x full well",
            "asrun_config_value": "max_peak_fraction_of_full_well = 0.80",
            "run_snapshot_value": "peak_limit_e = 12000.0 (= 0.80 x 15000 e-)",
            "code_site": "src/optisys/optimization/constraints.py:99-103",
            "match": "MATCH",
            "notes": "identical",
        },
        {
            "constraint_id": "SEARCH-BUDGET",
            "quantity": "search objective evaluations",
            "prereg_value": "<= 300 total",
            "asrun_config_value": "search_max_evaluations = 300",
            "run_snapshot_value": "nominal 147 + robust 138 = 285 recorded designs",
            "code_site": "src/optisys/gates/g2.py:900-910",
            "match": "MATCH",
            "notes": "285 <= 300; history rows are attempted designs",
        },
        {
            "constraint_id": "OAT-PANEL",
            "quantity": "OAT distances",
            "prereg_value": "5 distances, medium, 1 repeat",
            "asrun_config_value": "105, 130, 180, 230, 285 mm",
            "run_snapshot_value": "oat_samples.csv has no distance column (aggregated)",
            "code_site": "src/optisys/gates/g2.py:698",
            "match": "COUNT_MATCH_DISTANCES_LEAK_TEST",
            "notes": ("5 distances match the count, but 105 and 285 are final-test "
                      "distances - see PRE-G3-02"),
        },
        {
            "constraint_id": "PRECHECK-PANEL",
            "quantity": "precheck distances",
            "prereg_value": "5 distances, medium, 1 repeat",
            "asrun_config_value": "105, 130, 180, 230, 285 mm",
            "run_snapshot_value": "sample_status.csv distances 105..285",
            "code_site": "src/optisys/gates/g2.py:748",
            "match": "COUNT_MATCH_DISTANCES_LEAK_TEST",
            "notes": "2 of 5 distances are final-test distances - see PRE-G3-02",
        },
        {
            "constraint_id": "FINAL-PANEL",
            "quantity": "final frames per assembly",
            "prereg_value": "7 distances x 3 conditions = 21 frames",
            "asrun_config_value": "main panel 7 distances x 1 condition (medium)",
            "run_snapshot_value": "summary.json n_frames_per_candidate = 14000 = 2000x7",
            "code_site": "src/optisys/gates/g2.py:1063",
            "match": "CONFLICT",
            "notes": ("strong/weak run only on the 200-assembly stratified subset, "
                      "and that subset reused the previous loop's design (PRE-G3-03); "
                      "the 42000 rows per candidate are estimate rows, not 42000 images"),
        },
        {
            "constraint_id": "CALIB-FRAMES-B",
            "quantity": "calibration frames per unit in strategy B",
            "prereg_value": "the pre-registration fixes the budget, the report claims 5",
            "asrun_config_value": "_final_stage uses calib_distances = 9 (non-quick)",
            "run_snapshot_value": "factory_calibration n_points = 9 / 8 / 9",
            "code_site": "src/optisys/gates/g2.py:1046",
            "match": "CONFLICT",
            "notes": "report text says 5; the code path runs 9 - see PRE-G3-05",
        },
        {
            "constraint_id": "CALIB-MODEL-CHOICE",
            "quantity": "calibration model selection artifact",
            "prereg_value": "calibration_model_choice.json written before final test",
            "asrun_config_value": "config uses model M1 directly; select_model only in tests",
            "run_snapshot_value": "file absent from the run directory",
            "code_site": "src/optisys/calibration/assembly_strategies.py:165 (never called)",
            "match": "CONFLICT",
            "notes": "CALIBRATION_MODEL_SELECTION_NOT_EXECUTED_AS_REGISTERED",
        },
    ]


def probe_scan(frozen: dict[str, Any]) -> list[dict[str, Any]]:
    """Feasibility of the three frozen designs at the constraint-probe distances."""

    rows: list[dict[str, Any]] = []
    for cand in frozen["candidates"]:
        per_distance = cand["constraint_feasibility"]["details"]["per_distance"]
        for distance in CONSTRAINT_DISTANCES:
            entry = per_distance[f"{distance:.0f}"]
            support = float(entry["kernel_support"])
            ray = float(entry["ray_success_fraction"])
            peak = float(entry["peak_e"])
            for threshold in THRESHOLDS:
                failures = []
                if support < threshold:
                    failures.append("INSUFFICIENT_PSF_SUPPORT")
                if ray < MIN_RAY_SUCCESS:
                    failures.append("VIGNETTING")
                if peak > PEAK_FRACTION * FULL_WELL_E:
                    failures.append("SATURATION")
                rows.append({
                    "candidate": cand["name"],
                    "design": (f"B={cand['design']['baseline_mm']} "
                               f"f={cand['design']['focal_length_mm']} "
                               f"theta={cand['design']['theta_deg']}"),
                    "scope": "constraint_probe",
                    "distance_mm": distance,
                    "threshold": threshold,
                    "kernel_support": round(support, 9),
                    "ray_success_fraction": round(ray, 9),
                    "peak_e": round(peak, 4),
                    "feasible": "YES" if not failures else "NO",
                    "first_failure_reason": failures[0] if failures else "",
                    "frozen_decision": cand["constraint_feasibility"]["reason"],
                })
    return rows


def observed_scan(sampled: list[dict[str, str]]) -> list[dict[str, Any]]:
    """Share of observed final-panel rows below each threshold.

    Every estimator of a scene sees the same optical kernel, so the three
    estimator rows per (assembly, distance) carry identical ``kernel_support``.
    Counting all rows therefore reports "share of recorded rows", which is what
    a reader of ``sampled_results.csv`` would compute.
    """

    store: dict[tuple[str, float], list[float]] = defaultdict(list)
    for row in sampled:
        raw = row.get("kernel_support")
        if not raw:
            continue
        store[(row["candidate"], float(row["distance_mm"]))].append(float(raw))

    rows: list[dict[str, Any]] = []
    for (cand, distance), values in sorted(store.items()):
        arr = np.asarray(values, dtype=float)
        for threshold in THRESHOLDS:
            share = float(np.mean(arr < threshold))
            rows.append({
                "candidate": cand,
                "design": "",
                "scope": "observed_final_panel",
                "distance_mm": distance,
                "threshold": threshold,
                "kernel_support": "",
                "ray_success_fraction": "",
                "peak_e": "",
                "feasible": "YES" if share == 0.0 else "NO",
                "first_failure_reason": "" if share == 0.0 else "INSUFFICIENT_PSF_SUPPORT",
                "frozen_decision": "",
                "n_rows": int(arr.size),
                "support_min": round(float(arr.min()), 9),
                "support_mean": round(float(arr.mean()), 9),
                "share_rows_below_threshold": round(share, 6),
                "all_rows_pass": "YES" if share == 0.0 else "NO",
            })
    return rows


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)

    write_csv(OUT / "G2_PREREG_VS_ASRUN.csv", prereg_vs_asrun(),
              ["constraint_id", "quantity", "prereg_value", "asrun_config_value",
               "run_snapshot_value", "code_site", "match", "notes"])

    frozen = json.loads((G2_RUN / "optimization" / "candidates_frozen.json")
                        .read_text(encoding="utf-8"))
    recompute = json.loads((ROOT / "artifacts" / "g3" / "pre" / "g2_recompute.json")
                           .read_text(encoding="utf-8"))
    sampled = read_csv(G2_RUN / "independent_validation" / "sampled_results.csv")

    scan = probe_scan(frozen) + observed_scan(sampled)
    write_csv(OUT / "G2_HC3_THRESHOLD_SCAN.csv", scan,
              ["candidate", "design", "scope", "distance_mm", "threshold",
               "kernel_support", "ray_success_fraction", "peak_e", "feasible",
               "first_failure_reason", "frozen_decision", "n_rows",
               "support_min", "support_mean", "share_rows_below_threshold",
               "all_rows_pass"])

    support = recompute["report"]["support"]
    per_candidate = {}
    for cand in frozen["candidates"]:
        name = cand["name"]
        per_candidate[name] = {
            "design": cand["design"],
            "probe_support": {
                f"{d:.0f}": cand["constraint_feasibility"]["details"]
                ["per_distance"][f"{d:.0f}"]["kernel_support"]
                for d in CONSTRAINT_DISTANCES
            },
            "probe_feasible_under_0.999": all(
                cand["constraint_feasibility"]["details"]["per_distance"]
                [f"{d:.0f}"]["kernel_support"] >= 0.999 for d in CONSTRAINT_DISTANCES),
            "observed_rows": support[name]["n"],
            "observed_min": support[name]["min"],
            "observed_max": support[name]["max"],
            "observed_share_below_0.999": support[name]["fraction_below_0.999"],
            "observed_share_below_0.990": float(np.mean(
                np.asarray([float(r["kernel_support"]) for r in sampled
                            if r["candidate"] == name and r["kernel_support"]]) < 0.990)),
            "observed_share_below_0.975": support[name]["fraction_below_0.975"],
            "observed_share_below_0.950": support[name]["fraction_below_0.950"],
        }

    summary = {
        "gate": "PRE-G3-01",
        "issue": "kernel-support hard constraint conflicts with the pre-registration",
        "prereg_threshold": 0.999,
        "asrun_threshold": 0.950,
        "conflict": True,
        "definition": (
            "kernel_support = geom_frac * airy_frac, where geom_frac is the fraction of "
            "traced ray weight that lands inside the finite PSF window "
            "(half-width = ceil(max|du|,|dv|) + airy_radius_margin*airy_radius + 1, capped "
            "at max_half_px=40) and airy_frac is the Airy encircled-energy fraction inside "
            "that same window. It is evaluated on the nominal unit at the constraint-probe "
            "distances 100/200/300 mm, medium condition."
        ),
        "evaluated_where": [
            "src/optisys/optimization/constraints.py:97-98 (feasibility gate)",
            "src/optisys/optics/psf_or_footprint.py:178-180 (definition)",
            "src/optisys/optics/optical_image_contract.py:233-237 (warning only)",
        ],
        "per_candidate": per_candidate,
        "conclusion": "G2_PREREG_FEASIBILITY_NOT_ESTABLISHED",
        "reason": (
            "under HC3 as registered (>= 0.999) none of the three frozen designs is "
            "feasible: 100% of the 42000 recorded rows per candidate sit below 0.999, "
            "and the constraint probe at 100/200/300 mm gives 0.973-0.987. The executed "
            "optimisation used 0.950, which every candidate passes. The gap is therefore "
            "a real deviation from the pre-registration, not a rounding difference."
        ),
        "scientific_reading": (
            "The 0.999 value is a *truncation* requirement on a finite PSF window. With "
            "max_half_px=40 and the Airy margin rule, the window is sized from the "
            "geometric footprint, and any residual Airy encircled-energy outside the "
            "window counts as lost. For this singlet at f/6.7-f/10 the Airy radius is "
            "~1.4 px while the geometric footprint is 3-9 um, so the window is tight and "
            "0.97-0.99 is the structural ceiling. 0.999 is unreachable for this optical "
            "model, which makes HC3 an ill-posed constraint rather than a strict one. "
            "That reading is *evidence for an amendment*, not a retroactive justification: "
            "the registered text is still what it is."
        ),
        "required_disclosure": [
            "every G3 surface shows 0.950 (as-run) next to 0.999 (pre-registered)",
            "the phrase 'pre-registration fully complied with' is forbidden",
            "status G2_PREREG_FEASIBILITY_NOT_ESTABLISHED must travel with the numbers",
        ],
        "artifacts": [
            "docs/g3/evidence/G2_PREREG_VS_ASRUN.csv",
            "docs/g3/evidence/G2_HC3_THRESHOLD_SCAN.csv",
        ],
    }
    (OUT / "G2_HC3_SUMMARY.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(summary["conclusion"])
    for name, entry in per_candidate.items():
        print(f"  {name}: probe {entry['probe_support']} "
              f"observed<0.999={entry['observed_share_below_0.999']:.3f} "
              f"<0.975={entry['observed_share_below_0.975']:.3f} "
              f"<0.950={entry['observed_share_below_0.950']:.3f}")
    print(f"written: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())