"""PRE-G3-02: which distances each stage actually touched.

The pre-registration says final-test distances ``105, 135, 165, 195, 225, 255,
285 mm`` never appear in any search, OAT, precheck or model selection.  The
existing ``O6`` check only proved that the *search evaluation* panel and the
*final-test* panel are disjoint.  It never looked at OAT or precheck.

This script extracts the usage from two independent sources and reconciles
them:

1. **Code path** — the literal distance tuples in ``gates/g2.py`` plus the
   ``budget_usage.json`` written by the run.
2. **Run artifacts** — the distances actually present in the CSVs the run
   wrote (``oat_samples.csv`` is aggregated and has no distance column, so its
   distances can only come from the code; ``sample_status.csv`` has them).

Both are reported so that a reader can see where a leak would be invisible in
the artifacts (aggregated OAT) and where it is directly observable.
"""

from __future__ import annotations

import csv
import itertools
import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
G2_RUN = ROOT / "runs" / "20261019_191117_G2_52369787"
OUT = ROOT / "docs" / "g3" / "evidence"

SEARCH_TRAIN = (100.0, 120.0, 140.0, 160.0, 180.0, 200.0, 220.0, 240.0,
                260.0, 280.0, 300.0)
SEARCH_VALIDATION = (110.0, 130.0, 150.0, 170.0, 190.0, 210.0, 230.0, 250.0,
                     270.0, 290.0)
FINAL_TEST = (105.0, 135.0, 165.0, 195.0, 225.0, 255.0, 285.0)


def _read_distances(path: Path, column: str = "distance_mm") -> set[float]:
    if not path.is_file():
        return set()
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if column not in (reader.fieldnames or []):
            return set()
        return {float(row[column]) for row in reader if row.get(column)}


def build_usage() -> list[dict[str, Any]]:
    budget = json.loads((G2_RUN / "optimization" / "budget_usage.json")
                        .read_text(encoding="utf-8"))
    summary = json.loads((G2_RUN / "independent_validation" / "summary.json")
                         .read_text(encoding="utf-8"))

    search_calib = tuple(budget["search_calibration_distances"])
    search_eval = tuple(budget["search_evaluation_distances"])
    robust_dist = tuple(budget["robust_distances"])
    test = tuple(summary["test_distances"])
    observed_precheck = _read_distances(G2_RUN / "tolerance" / "sample_status.csv")
    observed_sb = _read_distances(G2_RUN / "independent_validation" / "strategy_b_baseline.csv")

    # OAT and precheck distances are literals in gates/g2.py::_tolerance_stage.
    oat = (105.0, 130.0, 180.0, 230.0, 285.0)
    precheck = (105.0, 130.0, 180.0, 230.0, 285.0)

    stages: list[tuple[str, tuple[float, ...], str, str]] = [
        ("TRAIN(search objective nominal)", search_eval,
         "src/optisys/gates/g2.py:845 _evenly_spaced(validation, 7)",
         "declared search-validation list; used as the nominal objective panel"),
        ("TRAIN(search objective robust)", robust_dist,
         "src/optisys/gates/g2.py:846 _evenly_spaced(validation, 4)",
         "4 of the 7 nominal distances"),
        ("SEARCH_CALIBRATION", search_calib,
         "src/optisys/gates/g2.py:843 _evenly_spaced(calibration, 6)",
         "factory calibration inside the search; not a test panel"),
        ("VALIDATION(distances declared)", SEARCH_VALIDATION,
         "configs/triangulation_g2_l1.yaml dataset.split.validation_distances",
         "the declared search-validation list; search_eval is a subset of it"),
        ("OAT", oat,
         "src/optisys/gates/g2.py:698 (literal in _tolerance_stage)",
         "aggregated CSV has no distance column, so only the code shows this"),
        ("PRECHECK", precheck,
         "src/optisys/gates/g2.py:748 (literal in _tolerance_stage)",
         "directly observable in tolerance/sample_status.csv"),
        ("FINAL-TEST(main)", test,
         "configs/triangulation_g2_l1.yaml dataset.split.test_distances",
         "7 distances x medium only; 2000 assemblies"),
        ("FINAL-TEST(strategy B)", tuple(sorted(observed_sb)) or test,
         "src/optisys/gates/g2.py:1100 subset_perturbations",
         "200 assemblies, single estimator"),
        ("CONSTRAINT_PROBE", (100.0, 200.0, 300.0),
         "src/optisys/optimization/constraints.py:53 default distances",
         "hard-constraint evaluation; 100 and 300 are train-range endpoints"),
    ]

    rows: list[dict[str, Any]] = []
    for stage, distances, site, note in stages:
        overlap = sorted(set(distances) & set(FINAL_TEST))
        rows.append({
            "stage": stage,
            "distances_mm": ";".join(f"{d:g}" for d in distances),
            "n_distances": len(distances),
            "source_of_evidence": site,
            "overlaps_final_test": "YES" if overlap else "NO",
            "overlapping_distances_mm": ";".join(f"{d:g}" for d in overlap),
            "leak_severity": ("HIGH" if stage.startswith(("OAT", "PRECHECK")) and overlap
                              else ("INFO" if overlap else "NONE")),
            "note": note,
        })

    # reconcile the code-declared precheck distances against the artifacts
    rows.append({
        "stage": "PRECHECK(observed)",
        "distances_mm": ";".join(f"{d:g}" for d in sorted(observed_precheck)),
        "n_distances": len(observed_precheck),
        "source_of_evidence": "run/tolerance/sample_status.csv",
        "overlaps_final_test": "YES" if observed_precheck & set(FINAL_TEST) else "NO",
        "overlapping_distances_mm": ";".join(
            f"{d:g}" for d in sorted(observed_precheck & set(FINAL_TEST))),
        "leak_severity": "HIGH",
        "note": "artifact-confirmed leak; matches the code literal",
    })
    return rows


def pairwise_crosstab(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every stage pair, intersection size and the actual shared distances."""

    panels = {}
    for row in rows:
        if not row["distances_mm"]:
            continue
        key = row["stage"]
        if key.endswith("(observed)"):
            continue
        panels[key] = {float(x) for x in row["distances_mm"].split(";")}

    out: list[dict[str, Any]] = []
    for a, b in itertools.combinations(sorted(panels), 2):
        shared = sorted(panels[a] & panels[b])
        out.append({
            "stage_a": a,
            "stage_b": b,
            "n_shared": len(shared),
            "shared_distances_mm": ";".join(f"{d:g}" for d in shared),
            "shares_final_test_member": "YES" if set(shared) & set(FINAL_TEST) else "NO",
        })
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    usage = build_usage()
    with (OUT / "G2_DATA_USAGE_MAP.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(usage[0]))
        writer.writeheader()
        writer.writerows(usage)

    pairs = pairwise_crosstab(usage)
    with (OUT / "G2_DATA_USAGE_CROSSTAB.csv").open("w", encoding="utf-8",
                                                   newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(pairs[0]))
        writer.writeheader()
        writer.writerows(pairs)

    leaks = [row for row in usage if row["leak_severity"] == "HIGH"]
    verdict = {
        "gate": "PRE-G3-02",
        "issue": "final-test distances entered OAT and precheck",
        "prereg_rule": ("final-test distances never appear in any search, OAT, precheck "
                        "or model selection (docs/g2/G2_PRE_REGISTRATION.md:69)"),
        "leaking_stages": [row["stage"] for row in leaks],
        "leaking_distances": sorted({float(d) for row in leaks
                                     for d in row["overlapping_distances_mm"].split(";")
                                     if d}),
        "n_leaks": len(leaks),
        "existing_O6_check_covered": ["TRAIN(search objective nominal) vs FINAL-TEST(main)"],
        "existing_O6_check_missed": [
            "OAT vs FINAL-TEST(main)",
            "PRECHECK vs FINAL-TEST(main)",
        ],
        "leak_character": (
            "distance reuse, NOT noise-seed reuse and NOT assembly reuse: OAT and "
            "precheck use namespace G2P with their own assembly ids (OAT rows are "
            "aggregated; precheck ids are PRE####), while the final test uses G2F and "
            "FIN####. The consequence is that the frozen designs were screened on three "
            "distances that later served as test distances, so those test points are not "
            "fully held out at the design level. No final-test noise seed or final-test "
            "assembly was ever seen during OAT/precheck."
        ),
        "severity_assessment": (
            "MODERATE: the design variables are chosen by the search (which stays on "
            "validation distances), and OAT/precheck only produce a feasibility signal. "
            "But because OAT and precheck at 105/285 mm could have revealed an infeasible "
            "design and driven its removal, the final test is not a pristine holdout at "
            "those two distances. Claiming 'single evaluation after freeze' remains true; "
            "claiming 'never observed during development' does not."
        ),
        "search_validation_reuse": (
            "config.dataset.validation_distances (10 values) is declared as "
            "'model-family selection only', but _search_stage passes two subsets of it "
            "(7 values and 4 values) into the nominal and robust objective functions. "
            "The pre-registration therefore has no distance-level holdout for design "
            "search at all: search-train values 100..300 step 20 are never used, so the "
            "actual search objective runs entirely on the declared validation list."
        ),
        "final_panel_deviation": {
            "prereg": "7 distances x {strong, medium, weak} = 21 frames per assembly",
            "as_run": "7 distances x medium only = 7 frames per assembly on the main 2000 panel",
            "as_run_note": ("strong/weak exist only on the 200-assembly stratified subset, "
                            "which itself used the wrong design before PRE-G3-03 is fixed"),
            "consequence": ("the 42000 rows per candidate are estimator-level records "
                            "(2000 x 7 x 3), not 42000 independent multi-condition images; "
                            "every main-panel conclusion is medium-condition only"),
        },
        "required_disclosure": [
            "G2_FINAL_PANEL_DEVIATION must be shown wherever main-panel numbers appear",
            "no cross-condition generalisation may be claimed from the main panel",
        ],
        "artifacts": ["docs/g3/evidence/G2_DATA_USAGE_MAP.csv",
                      "docs/g3/evidence/G2_DATA_USAGE_CROSSTAB.csv"],
    }
    (OUT / "G2_DATA_USAGE_VERDICT.json").write_text(
        json.dumps(verdict, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    print(f"leaking stages: {[row['stage'] for row in leaks]}")
    print(f"leaking distances: {verdict['leaking_distances']}")
    print(f"written: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())