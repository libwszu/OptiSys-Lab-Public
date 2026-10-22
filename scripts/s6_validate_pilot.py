"""Validate S6-C pilot structure without calculating or reporting candidate gain."""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RUN_ID = "20261021_024715_S6_P1"
PILOT = ROOT / "runs" / RUN_ID / "s6_c_pilot"


def _csv(path: Path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def validate() -> dict:
    status = json.loads((PILOT / "pilot_run_status.json").read_text(encoding="utf-8"))
    contract = json.loads((PILOT / "run_contract.json").read_text(encoding="utf-8"))
    manifest = _csv(PILOT / "assembly_manifest.csv")
    samples = _csv(PILOT / "p1_assembly_samples.csv")
    groups: dict[str, dict[str, dict[str, str]]] = {}
    failures: list[str] = []
    for row in samples:
        groups.setdefault(row["assembly_id"], {})[row["design_id"]] = row
        try:
            counts = json.loads(row["terminal_counts_json"])
            terminal_weights = json.loads(row["terminal_weights_json"])
            if int(row["source_ray_count"]) != 256:
                failures.append(f"unexpected ray count: {row['assembly_id']}/{row['design_id']}")
            if sum(int(x) for x in counts.values()) != 256:
                failures.append(f"terminal counts do not close: {row['assembly_id']}/{row['design_id']}")
            if abs(sum(float(x) for x in terminal_weights.values()) - 1.0) > 1e-12:
                failures.append(f"weight ledger does not close: {row['assembly_id']}/{row['design_id']}")
            if abs(float(row["source_weight_denominator"]) - 1.0) > 1e-12:
                failures.append(f"wrong source denominator: {row['assembly_id']}/{row['design_id']}")
            if row["ledger_status"] not in {"PASS", "PASS_INVALID_ASSEMBLY_WEIGHTED_ZERO"}:
                failures.append(f"ledger status not passing: {row['assembly_id']}/{row['design_id']}")
            if row["design_status"] not in {"COMPLETE", "INVALID_ASSEMBLY"}:
                failures.append(f"design did not complete: {row['assembly_id']}/{row['design_id']}")
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            failures.append(f"invalid row {row.get('assembly_id')}: {type(exc).__name__}")
    for assembly_id, pair in groups.items():
        if set(pair) != {"baseline125", "s5_position135"}:
            failures.append(f"unpaired design rows: {assembly_id}")
            continue
        b, c = pair["baseline125"], pair["s5_position135"]
        for key in ("source_seed", "source_bundle_sha256", "input_hash"):
            if b[key] != c[key]: failures.append(f"unpaired {key}: {assembly_id}")
        for key in ("L1_dx_mm", "L1_dy_mm", "L1_tilt_x_deg", "L1_tilt_y_deg", "L1_dz_mm",
                    "L2_dx_mm", "L2_dy_mm", "L2_tilt_x_deg", "L2_tilt_y_deg", "L2_dz_mm"):
            if b[key] != c[key]: failures.append(f"unpaired perturbation {key}: {assembly_id}")
    seed_values = [int(row["source_seed"]) for row in manifest]
    checks = {
        "pilot_status_pass": status.get("status") == "PASS",
        "manifest_count_matches_plan": len(manifest) == status.get("planned_assemblies") == 32,
        "sample_row_count": len(samples) == 64,
        "unique_assembly_count": len(groups) == 32,
        "unique_source_seed_count": len(set(seed_values)) == 32,
        "S5_holdout_seed_excluded": 976053 not in seed_values,
        "all_checkpoints_present": len(list((PILOT / "checkpoints").glob("*.json"))) == 32,
        "pilot_not_used_to_change_plan": status.get("candidate_effect_used_to_change_plan") is False,
    }
    if not all(checks.values()):
        failures.extend(k for k, passed in checks.items() if not passed)
    result = {
        "schema": "optisys.s6.pilot_validation/1", "run_id": RUN_ID,
        "status": "PASS" if not failures else "FAIL", "checks": checks,
        "assembly_count": len(groups), "design_rows": len(samples),
        "source_seed_count": len(set(seed_values)), "failure_count": len(failures),
        "failures": failures,
        "note": "This structural validation intentionally does not calculate or publish pilot candidate performance.",
    }
    output = PILOT / "pilot_validation.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    raise SystemExit(0 if validate()["status"] == "PASS" else 1)
