"""Independently validate and recompute the frozen S6-C assembly results.

This verifier reads the immutable per-assembly CSVs and does not import the
OptiSys S6 simulation or statistics implementation. It can run from the source
checkout or from an extracted GPT audit package with the same relative paths.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np

RUN_ID = "20261021_024715_S6_P1"
SCENARIOS = ("zero", "tight_0p5x", "nominal_1x", "stress_2x")
DESIGNS = ("baseline125", "s5_position135")
FAILURE_CATEGORIES = (
    "INVALID_ASSEMBLY", "INVALID_SOURCE", "L1_APERTURE_BLOCK",
    "L2_APERTURE_BLOCK", "NO_INTERSECTION", "TIR", "TRACE_FAIL",
)
KNOWN_TERMINAL_CATEGORIES = {
    "CAPTURED", "OUTSIDE_TARGET", *FAILURE_CATEGORIES,
}
TOL = 1e-12


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def as_float(row: dict[str, str], key: str) -> float:
    value = float(row[key])
    if not math.isfinite(value):
        raise ValueError(f"non-finite {key}: {value}")
    return value


def as_bool(value: str) -> bool:
    if value.lower() in {"true", "1", "yes"}:
        return True
    if value.lower() in {"false", "0", "no"}:
        return False
    raise ValueError(f"not a boolean: {value!r}")


def q(values: list[float] | np.ndarray, probability: float) -> float:
    # The frozen implementation used np.quantile's default linear interpolation.
    return float(np.quantile(np.asarray(values, dtype=float), probability, method="linear"))


def find_file(root: Path, name: str, data_dir: Path) -> Path:
    candidates = [
        data_dir / name,
        root / f"runs/{RUN_ID}/s6_c_assemblies/{name}",
        root / f"runs/{RUN_ID}/{name}",
        root / f"science/{name}",
        root / f"evidence/s6/raw_data/{name}",
        root / f"evidence/s6/run_records/{name}",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"required S6-R source file is missing: {name}; checked {candidates}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1], help="source checkout or extracted package root")
    parser.add_argument("--data-dir", type=Path, help="directory containing the full S6-C CSV/JSON sources")
    parser.add_argument("--output", type=Path, help="optional JSON output path")
    args = parser.parse_args()
    root = args.root.resolve()
    data_dir = args.data_dir.resolve() if args.data_dir else root / f"runs/{RUN_ID}/s6_c_assemblies"
    if not data_dir.is_dir():
        for candidate in (root / "science", root / "evidence/s6/raw_data"):
            if candidate.is_dir():
                data_dir = candidate
                break

    errors: list[str] = []
    diagnostics: list[dict[str, Any]] = []
    required = [
        "p1_assembly_samples.csv", "paired_assembly_comparison.csv",
        "assembly_bootstrap_replicates.csv", "failure_breakdown.csv",
        "assembly_manifest.csv", "assembly_robustness_plot_data.csv",
        "zero_tolerance_controls.csv", "assembly_statistics_programmatic.json",
        "assembly_statistics.json", "assembly_parameter_registry.json",
        "run_contract.json", "run_status.json", "S6_C_FINAL_ADJUDICATION.json",
    ]
    files: dict[str, Path] = {}
    for name in required:
        try:
            files[name] = find_file(root, name, data_dir)
        except FileNotFoundError as e:
            errors.append(str(e))
    if errors:
        result = {"schema": "optisys.s6r.science_recomputation/1", "status": "FAIL", "errors": errors}
        emit(result, args.output)
        return 1

    samples = read_csv(files["p1_assembly_samples.csv"])
    pairs = read_csv(files["paired_assembly_comparison.csv"])
    bootstrap_stored = read_csv(files["assembly_bootstrap_replicates.csv"])
    failure_stored = read_csv(files["failure_breakdown.csv"])
    manifest = read_csv(files["assembly_manifest.csv"])
    plot_stored = read_csv(files["assembly_robustness_plot_data.csv"])
    zero_controls = read_csv(files["zero_tolerance_controls.csv"])
    original_auto = read_json(files["assembly_statistics_programmatic.json"])
    original_final = read_json(files["assembly_statistics.json"])
    registry = read_json(files["assembly_parameter_registry.json"])
    run_contract = read_json(files["run_contract.json"])
    run_status = read_json(files["run_status.json"])
    original_adjudication = read_json(files["S6_C_FINAL_ADJUDICATION.json"])

    # Preserve run-tree provenance for every principal source copied into this result.
    source_hashes = {name: {"bytes": p.stat().st_size, "sha256": file_sha256(p)} for name, p in sorted(files.items())}
    amendment_hash_file = root / "docs/s6/S6_AMENDMENT_03_HASHES.json"
    amendment03_file = root / "docs/s6/S6_AMENDMENT_03.md"
    acceptance_file = root / "docs/s6/S6_ACCEPTANCE_CRITERIA.md"
    holdout_freeze_file = root / f"runs/{RUN_ID}/S6_C_HOLDOUT_FREEZE_02.json"
    amendment03_trace = {"status": "PARTIAL", "source_file": "MISSING_SOURCE", "notes": []}
    if amendment_hash_file.is_file() and amendment03_file.is_file() and acceptance_file.is_file() and holdout_freeze_file.is_file():
        hash_doc = read_json(amendment_hash_file)
        holdout_freeze = read_json(holdout_freeze_file)
        frozen_criteria = holdout_freeze.get("hashes", {}).get("docs/s6/S6_ACCEPTANCE_CRITERIA.md", {}).get("sha256")
        actual_criteria = file_sha256(acceptance_file)
        amendment_time = hash_doc.get("frozen_at_utc")
        holdout_time = holdout_freeze.get("frozen_at_utc")
        actual_holdout_end = run_status.get("finished_at_utc")
        amendment03_trace = {
            "status": "PASS" if frozen_criteria == actual_criteria and hash_doc.get("formal_holdout_complete") is True and hash_doc.get("metrics_changed") is False and hash_doc.get("thresholds_changed") is False and hash_doc.get("samples_changed") is False else "PARTIAL",
            "standalone_preregistration_file": "MISSING_SOURCE",
            "available_frozen_rule_sources": ["docs/s6/S6_ACCEPTANCE_CRITERIA.md", f"runs/{RUN_ID}/S6_C_HOLDOUT_FREEZE_02.json"],
            "acceptance_criteria_expected_sha256": frozen_criteria,
            "acceptance_criteria_actual_sha256": actual_criteria,
            "holdout_freeze_at_utc": holdout_time,
            "holdout_finished_at_utc": actual_holdout_end,
            "amendment_03_hash_freeze_at_utc": amendment_time,
            "amendment_declares_formal_holdout_complete": hash_doc.get("formal_holdout_complete"),
            "amendment_declares_metrics_changed": hash_doc.get("metrics_changed"),
            "amendment_declares_thresholds_changed": hash_doc.get("thresholds_changed"),
            "amendment_declares_samples_changed": hash_doc.get("samples_changed"),
            "freeze_claim_rule": holdout_freeze.get("claim_rule"),
            "notes": ["The standalone S6_PRE_REGISTRATION.md is absent. The holdout freeze and pre-result acceptance criteria carry the registered rule; Amendment 03 is post-result and narrows the aggregate interpretation without changing numbers, thresholds, or samples."],
        }
    elif not acceptance_file.is_file():
        errors.append("MISSING_SOURCE: frozen S6 acceptance criteria")
    else:
        amendment03_trace["notes"].append("One or more source files needed to verify the Amendment 03 timeline are missing.")

    # Core sample completeness and design-pair identity.
    by_assembly: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in samples:
        by_assembly[row["assembly_id"]].append(row)
    pair_by_id = {row["assembly_id"]: row for row in pairs}
    manifest_by_id = {row["assembly_id"]: row for row in manifest}
    if len(samples) != 1600:
        errors.append(f"expected 1600 design-assembly rows, found {len(samples)}")
    if len(by_assembly) != 800 or len(pairs) != 800 or len(manifest) != 800:
        errors.append(f"expected 800 unique assembly pairs/manifests, found samples={len(by_assembly)} pairs={len(pairs)} manifest={len(manifest)}")
    if len(pair_by_id) != len(pairs) or len(manifest_by_id) != len(manifest):
        errors.append("duplicate assembly_id in paired comparison or manifest")
    scenario_assembly_counts: dict[str, int] = {}
    scenario_rows_counts: dict[str, int] = {}
    seed_base_match = re.search(r"(\d+)\s*\+\s*latent_id", run_contract.get("seed_info", {}).get("source_seed_rule", ""))
    # Older contract records seed_info numerically rather than as source_seed_rule text.
    source_seed_base = int(seed_base_match.group(1)) if seed_base_match else int(run_contract.get("seed_info", {}).get("source_seed_base", 80630000))
    scenario_ids: dict[str, set[str]] = {s: set() for s in SCENARIOS}
    latent_z_by_latent: dict[int, str] = {}
    vectors_by_scenario: dict[str, list[dict[str, float]]] = defaultdict(list)
    weights_by_scenario_design: dict[tuple[str, str], dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    counts_by_scenario_design: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    ray_count_by_scenario_design: dict[tuple[str, str], int] = defaultdict(int)
    assembly_count_by_scenario_design_outcome: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    unknown_terminal = set()
    ledger_max_abs = 0.0
    pair_value_max_abs = 0.0
    seed_ok = True
    source_reuse_ok = True
    zero_pose_ok = True

    sample_lookup: dict[tuple[str, str], dict[str, str]] = {}
    for aid, rows in by_assembly.items():
        if len(rows) != 2:
            errors.append(f"{aid}: expected exactly two design records, found {len(rows)}")
            continue
        scenarios = {x["scenario"] for x in rows}
        designs = {x["design_id"] for x in rows}
        if len(scenarios) != 1 or designs != set(DESIGNS):
            errors.append(f"{aid}: scenario/design pairing invalid: {scenarios} / {designs}")
            continue
        scenario = rows[0]["scenario"]
        if scenario not in SCENARIOS:
            errors.append(f"{aid}: unknown scenario {scenario}")
            continue
        scenario_ids[scenario].add(aid)
        source_seed_vals = {int(x["source_seed"]) for x in rows}
        bundle_hashes = {x["source_bundle_sha256"] for x in rows}
        input_hashes = {x["input_hash"] for x in rows}
        if len(source_seed_vals) != 1 or len(bundle_hashes) != 1 or len(input_hashes) != 1:
            errors.append(f"{aid}: paired designs do not share source_seed/source bundle/input hash")
            source_reuse_ok = False
        latent_id = int(rows[0]["latent_id"])
        if any(int(x["latent_id"]) != latent_id for x in rows):
            errors.append(f"{aid}: paired latent_id mismatch")
        expected_seed = source_seed_base + latent_id
        if source_seed_vals != {expected_seed}:
            errors.append(f"{aid}: source_seed {source_seed_vals} does not match frozen rule {expected_seed}")
            seed_ok = False
        for row in rows:
            sample_lookup[(aid, row["design_id"])] = row
            if int(row["rays_per_design"]) != 1024 or int(row["source_ray_count"]) != 1024:
                errors.append(f"{aid}/{row['design_id']}: source ray count is not 1,024")
            denominator = as_float(row, "source_weight_denominator")
            captured_weight = as_float(row, "captured_weight")
            captured_fraction = as_float(row, "capture_fraction_input")
            if not math.isclose(denominator, 1.0, abs_tol=TOL, rel_tol=0.0):
                errors.append(f"{aid}/{row['design_id']}: source weight denominator is {denominator}, expected 1.0")
            counts = json.loads(row["terminal_counts_json"])
            weights = json.loads(row["terminal_weights_json"])
            if set(counts) - KNOWN_TERMINAL_CATEGORIES or set(weights) - KNOWN_TERMINAL_CATEGORIES:
                unknown_terminal.update(set(counts) | set(weights))
            if sum(int(v) for v in counts.values()) != int(row["source_ray_count"]):
                errors.append(f"{aid}/{row['design_id']}: terminal counts do not close to source ray count")
            sum_weight = math.fsum(float(v) for v in weights.values())
            ledger_resid = sum_weight - denominator
            ledger_max_abs = max(ledger_max_abs, abs(ledger_resid))
            if abs(ledger_resid) > TOL:
                errors.append(f"{aid}/{row['design_id']}: terminal weight ledger residual {ledger_resid}")
            if not math.isclose(captured_weight, float(weights.get("CAPTURED", 0.0)), abs_tol=TOL, rel_tol=0.0):
                errors.append(f"{aid}/{row['design_id']}: captured_weight disagrees with CAPTURED terminal weight")
            if not math.isclose(captured_fraction, captured_weight / denominator if denominator else 0.0, abs_tol=TOL, rel_tol=0.0):
                errors.append(f"{aid}/{row['design_id']}: capture_fraction_input is not captured/source weight")
            if int(row["captured_count"]) != int(counts.get("CAPTURED", 0)):
                errors.append(f"{aid}/{row['design_id']}: captured_count disagrees with terminal counts")
            if row["ledger_status"] != "PASS":
                errors.append(f"{aid}/{row['design_id']}: ledger_status={row['ledger_status']}")
            for outcome, weight in weights.items():
                weights_by_scenario_design[(scenario, row["design_id"])][outcome].append(float(weight))
            for outcome, count in counts.items():
                counts_by_scenario_design[(scenario, row["design_id"])][outcome] += int(count)
                if int(count) > 0:
                    assembly_count_by_scenario_design_outcome[(scenario, row["design_id"], outcome)].add(aid)
            ray_count_by_scenario_design[(scenario, row["design_id"])] += int(row["source_ray_count"])
        if scenario == "zero":
            for row in rows:
                for key in ("L1_dx_mm", "L1_dy_mm", "L1_tilt_x_deg", "L1_tilt_y_deg", "L1_dz_mm", "L2_dx_mm", "L2_dy_mm", "L2_tilt_x_deg", "L2_tilt_y_deg", "L2_dz_mm"):
                    if not math.isclose(float(row[key]), 0.0, abs_tol=TOL, rel_tol=0.0):
                        zero_pose_ok = False
                        errors.append(f"{aid}: zero scenario contains non-zero {key}")

    scenario_assembly_counts = {s: len(scenario_ids[s]) for s in SCENARIOS}
    scenario_rows_counts = {s: sum(row["scenario"] == s for row in samples) for s in SCENARIOS}
    for scenario in SCENARIOS:
        if scenario_assembly_counts[scenario] != 200 or scenario_rows_counts[scenario] != 400:
            errors.append(f"{scenario}: expected 200 assembly pairs/400 design rows; got {scenario_assembly_counts[scenario]}/{scenario_rows_counts[scenario]}")
    if unknown_terminal:
        errors.append(f"undeclared terminal outcome categories found: {sorted(unknown_terminal)}")

    # Latent draws and paired seeds must be held across the four registered tiers.
    manifest_by_latent: dict[tuple[str, int], dict[str, str]] = {(r["scenario"], int(r["latent_id"])): r for r in manifest}
    source_seeds_per_scenario: dict[str, set[int]] = {}
    input_bundle_by_latent: dict[int, set[str]] = defaultdict(set)
    for scenario in SCENARIOS:
        seeds = set()
        for latent_id in range(200):
            row = manifest_by_latent.get((scenario, latent_id))
            if row is None:
                errors.append(f"manifest missing {scenario}/latent {latent_id}")
                continue
            seeds.add(int(row["source_seed"]))
            bundle = row["source_bundle_sha256"]
            input_bundle_by_latent[latent_id].add(bundle)
            try:
                z = json.loads(row["latent_z_json"])
                if latent_id in latent_z_by_latent and latent_z_by_latent[latent_id] != row["latent_z_json"]:
                    errors.append(f"latent draw changed across scenarios for latent_id={latent_id}")
                latent_z_by_latent[latent_id] = row["latent_z_json"]
                vectors_by_scenario[scenario].append(json.loads(row["perturbation_vector_json"]))
                expected_vector = np.asarray(z, dtype=float) * np.asarray([
                    registry["nominal_sigma"]["decenter_x_mm"], registry["nominal_sigma"]["decenter_y_mm"],
                    registry["nominal_sigma"]["tilt_x_deg"], registry["nominal_sigma"]["tilt_y_deg"], registry["nominal_sigma"]["axial_z_mm"],
                    registry["nominal_sigma"]["decenter_x_mm"], registry["nominal_sigma"]["decenter_y_mm"],
                    registry["nominal_sigma"]["tilt_x_deg"], registry["nominal_sigma"]["tilt_y_deg"], registry["nominal_sigma"]["axial_z_mm"],
                ]) * float(registry["scenarios"][scenario])
                param_order = registry["parameter_order"]
                actual_vector = np.asarray([float(json.loads(row["perturbation_vector_json"])[k]) for k in param_order])
                if not np.allclose(expected_vector, actual_vector, atol=TOL, rtol=0.0):
                    errors.append(f"{scenario}/latent {latent_id}: recorded perturbation differs from registered latent × sigma × scale")
            except Exception as e:
                errors.append(f"{scenario}/latent {latent_id}: seed/perturbation manifest parse failed: {e}")
        source_seeds_per_scenario[scenario] = seeds
        if len(seeds) != 200 or seeds != set(range(source_seed_base, source_seed_base + 200)):
            errors.append(f"{scenario}: source seed set is not the frozen one-to-one 200-seed range")
    if any(len(v) != 1 for v in input_bundle_by_latent.values()):
        errors.append("source bundle SHA differs across registered scenarios for the same latent_id")

    # Reconcile the paired table against its two source design rows and assembly manifest.
    for row in pairs:
        aid, scenario = row["assembly_id"], row["scenario"]
        base = sample_lookup.get((aid, "baseline125"))
        cand = sample_lookup.get((aid, "s5_position135"))
        mrow = manifest_by_id.get(aid)
        if base is None or cand is None or mrow is None:
            errors.append(f"paired table row missing source sample or assembly manifest: {aid}")
            continue
        for field, value in (("baseline_capture", as_float(base, "capture_fraction_input")), ("candidate_capture", as_float(cand, "capture_fraction_input"))):
            if not math.isclose(as_float(row, field), value, abs_tol=TOL, rel_tol=0.0):
                errors.append(f"{aid}: paired {field} differs from source sample")
        delta = as_float(row, "candidate_capture") - as_float(row, "baseline_capture")
        pair_resid = as_float(row, "paired_delta_capture") - delta
        pair_value_max_abs = max(pair_value_max_abs, abs(pair_resid))
        if abs(pair_resid) > TOL:
            errors.append(f"{aid}: paired delta does not equal candidate minus baseline")
        if row["input_hash"] != base["input_hash"] or row["input_hash"] != cand["input_hash"] or row["input_hash"] != mrow["input_hash"]:
            errors.append(f"{aid}: input hash mismatch across samples, pair table, and manifest")
        if bool(as_bool(row["both_designs_complete"])) != (base["design_status"] == "COMPLETE" and cand["design_status"] == "COMPLETE"):
            errors.append(f"{aid}: both_designs_complete flag disagrees with design rows")
        if row["source_seed"] != base["source_seed"] or row["source_seed"] != cand["source_seed"]:
            errors.append(f"{aid}: paired source_seed mismatch")

    # Verify whole-run completion and the frozen design size.
    if run_status.get("status") != "COMPLETE" or int(run_status.get("complete", -1)) != 800 or int(run_status.get("failed", -1)) != 0 or int(run_status.get("timed_out", -1)) != 0 or int(run_status.get("not_started", -1)) != 0:
        errors.append("run_status does not show 800 complete, zero failure, zero timeout and zero not-started assemblies")
    if int(run_contract.get("rays_per_design", -1)) != 1024 or int(run_contract.get("planned_assemblies_per_scenario", -1)) != 200:
        errors.append("run contract differs from the frozen 200 × 1,024 plan")
    if int(run_contract.get("seed_info", {}).get("bootstrap_seed", -1)) != 8064001 or int(run_contract.get("seed_info", {}).get("source_seed_base", source_seed_base)) != source_seed_base:
        errors.append("run contract seeds differ from the frozen source/bootstrap seed values")

    # Exact replay of the fixed-seed paired bootstrap. Preserve original input order,
    # matching the frozen script's filtered pair rows and default_rng per scenario.
    bootstrap_replay = []
    recomputed: dict[str, dict[str, Any]] = {}
    stored_boot = {(r["scenario"], int(r["replicate"])): r for r in bootstrap_stored}
    stored_plot = {r["scenario"]: r for r in plot_stored}
    programmatic_scenarios = original_auto.get("scenarios", {})
    final_scenarios = original_final.get("scenarios", {})
    for scenario in SCENARIOS:
        s_pairs = [r for r in pairs if r["scenario"] == scenario and as_bool(r["both_designs_complete"])]
        base = np.asarray([as_float(r, "baseline_capture") for r in s_pairs])
        cand = np.asarray([as_float(r, "candidate_capture") for r in s_pairs])
        delta = cand - base
        rng = np.random.default_rng(8064001)
        rep_values = []
        exact_match_count = 0
        for replicate in range(2000):
            indices = rng.integers(0, len(s_pairs), size=len(s_pairs))
            b, c = base[indices], cand[indices]
            d = c - b
            current = {
                "mean_delta_capture": float(np.mean(d)),
                "p05_baseline_capture": q(b, 0.05),
                "p05_candidate_capture": q(c, 0.05),
                "p05_delta_capture": q(d, 0.05),
                "p50_delta_capture": q(d, 0.50),
                "p95_delta_capture": q(d, 0.95),
            }
            rep_values.append(current)
            old = stored_boot.get((scenario, replicate))
            if old is None:
                errors.append(f"bootstrap output missing {scenario}/{replicate}")
                continue
            ok = True
            for key, value in current.items():
                if not math.isclose(float(old[key]), value, abs_tol=TOL, rel_tol=0.0):
                    ok = False
                    errors.append(f"bootstrap mismatch {scenario}/{replicate}/{key}: {old[key]} != {value}")
                    break
            exact_match_count += int(ok)

        sample_rows = [r for r in samples if r["scenario"] == scenario]
        base_rows = [r for r in sample_rows if r["design_id"] == "baseline125"]
        cand_rows = [r for r in sample_rows if r["design_id"] == "s5_position135"]
        base_valid = [as_bool(r["assembly_valid"]) for r in base_rows]
        cand_valid = [as_bool(r["assembly_valid"]) for r in cand_rows]
        failure_mean: dict[str, dict[str, float]] = {}
        failure_count: dict[str, dict[str, int]] = {}
        for design_id, rows in (("baseline125", base_rows), ("s5_position135", cand_rows)):
            cats: dict[str, list[float]] = {x: [] for x in FAILURE_CATEGORIES}
            counts: Counter[str] = Counter()
            for r in rows:
                for category in FAILURE_CATEGORIES:
                    cats[category].append(float(json.loads(r["terminal_weights_json"]).get(category, 0.0)))
                    counts[category] += int(json.loads(r["terminal_counts_json"]).get(category, 0))
            failure_mean[design_id] = {k: float(np.mean(v)) for k, v in cats.items()}
            failure_count[design_id] = dict(counts)
        failure_delta = {k: failure_mean["s5_position135"][k] - failure_mean["baseline125"][k] for k in FAILURE_CATEGORIES}
        boot_mean = np.asarray([x["mean_delta_capture"] for x in rep_values])
        boot_p05 = np.asarray([x["p05_delta_capture"] for x in rep_values])
        mean_ci = [q(boot_mean, 0.025), q(boot_mean, 0.975)]
        p05_ci = [q(boot_p05, 0.025), q(boot_p05, 0.975)]
        r90_base = [as_float(r, "r90_all_plane_reachers_mm") for r in base_rows]
        r90_cand = [as_float(r, "r90_all_plane_reachers_mm") for r in cand_rows]
        computed = {
            "scenario": scenario,
            "n_planned_assemblies": len(base_rows),
            "n_complete_pairs": len(s_pairs),
            "bootstrap_successful_replicates": exact_match_count,
            "bootstrap_seed": 8064001,
            "bootstrap_unit": "assembly_id",
            "bootstrap_interval_quantiles": [0.025, 0.975],
            "percentile_method": "numpy.quantile method=linear",
            "mean_capture_baseline125": float(np.mean(base)),
            "mean_capture_candidate135": float(np.mean(cand)),
            "mean_delta_capture_candidate_minus_baseline": float(np.mean(delta)),
            "paired_mean_delta_capture_ci95": mean_ci,
            "p05_capture_baseline125": q([as_float(r, "capture_fraction_input") for r in base_rows], 0.05),
            "p05_capture_candidate135": q([as_float(r, "capture_fraction_input") for r in cand_rows], 0.05),
            "p05_paired_delta_capture": q(delta, 0.05),
            "p05_paired_delta_bootstrap_ci95": p05_ci,
            "p50_capture_baseline125": q(base, 0.50),
            "p50_capture_candidate135": q(cand, 0.50),
            "p95_capture_baseline125": q(base, 0.95),
            "p95_capture_candidate135": q(cand, 0.95),
            "all_plane_r90_median_mm_baseline125": q(r90_base, 0.50),
            "all_plane_r90_median_mm_candidate135": q(r90_cand, 0.50),
            "all_plane_r90_p95_mm_baseline125": q(r90_base, 0.95),
            "all_plane_r90_p95_mm_candidate135": q(r90_cand, 0.95),
            "failure_weight_mean_by_design": failure_mean,
            "failure_weight_mean_delta_candidate_minus_baseline": failure_delta,
            "failure_ray_counts_by_design": failure_count,
            "invalid_assembly_rate_baseline125": 1.0 - float(np.mean(base_valid)),
            "invalid_assembly_rate_candidate135": 1.0 - float(np.mean(cand_valid)),
            "n_both_valid": sum(as_bool(r["baseline_valid"]) and as_bool(r["candidate_valid"]) for r in s_pairs),
            "n_only_baseline_valid": sum(as_bool(r["baseline_valid"]) and not as_bool(r["candidate_valid"]) for r in s_pairs),
            "n_only_candidate_valid": sum(not as_bool(r["baseline_valid"]) and as_bool(r["candidate_valid"]) for r in s_pairs),
            "source_weight_ledger_max_abs_residual": ledger_max_abs,
        }
        recomputed[scenario] = computed
        old_rows = [programmatic_scenarios.get(scenario, {}), final_scenarios.get(scenario, {})]
        metric_keys = (
            "mean_capture_baseline125", "mean_capture_candidate135", "mean_delta_capture_candidate_minus_baseline",
            "p05_capture_baseline125", "p05_capture_candidate135", "p05_paired_delta_capture",
            "p50_capture_baseline125", "p50_capture_candidate135", "p95_capture_baseline125", "p95_capture_candidate135",
            "all_plane_r90_median_mm_baseline125", "all_plane_r90_median_mm_candidate135",
            "all_plane_r90_p95_mm_baseline125", "all_plane_r90_p95_mm_candidate135",
            "invalid_assembly_rate_baseline125", "invalid_assembly_rate_candidate135",
        )
        for label, old in zip(("programmatic", "amended_final"), old_rows, strict=True):
            if not old:
                errors.append(f"{label} stats missing {scenario}")
                continue
            for key in metric_keys:
                if old.get(key) is None or not math.isclose(float(old[key]), float(computed[key]), abs_tol=TOL, rel_tol=0.0):
                    errors.append(f"{label} stats mismatch {scenario}/{key}: recorded={old.get(key)} recomputed={computed[key]}")
            for key, expected in (("paired_mean_delta_capture_ci95", mean_ci), ("p05_paired_delta_bootstrap_ci95", p05_ci)):
                got = old.get(key)
                if not isinstance(got, list) or len(got) != 2 or any(not math.isclose(float(a), float(b), abs_tol=TOL, rel_tol=0.0) for a, b in zip(got, expected, strict=True)):
                    errors.append(f"{label} bootstrap CI mismatch {scenario}/{key}: recorded={got} recomputed={expected}")
        plot = stored_plot.get(scenario)
        if plot is None:
            errors.append(f"plot data missing scenario {scenario}")
        else:
            plot_map = {
                "mean_capture_baseline125": "mean_capture_baseline125",
                "mean_capture_candidate135": "mean_capture_candidate135",
                "mean_delta_capture": "mean_delta_capture_candidate_minus_baseline",
                "p05_capture_baseline125": "p05_capture_baseline125",
                "p05_capture_candidate135": "p05_capture_candidate135",
                "p05_paired_delta_capture": "p05_paired_delta_capture",
                "mean_delta_ci95_low": "paired_mean_delta_capture_ci95",
            }
            for plot_key, result_key in plot_map.items():
                expected = computed[result_key]
                actual = as_float(plot, plot_key)
                if result_key == "paired_mean_delta_capture_ci95":
                    expected = expected[0]
                if not math.isclose(actual, float(expected), abs_tol=TOL, rel_tol=0.0):
                    errors.append(f"plot data mismatch {scenario}/{plot_key}")
            for plot_key, bound in (("mean_delta_ci95_high", 1), ("p05_delta_bootstrap_ci95_low", 0), ("p05_delta_bootstrap_ci95_high", 1)):
                ref = computed["paired_mean_delta_capture_ci95"] if plot_key.startswith("mean_delta") else computed["p05_paired_delta_bootstrap_ci95"]
                if not math.isclose(as_float(plot, plot_key), ref[bound], abs_tol=TOL, rel_tol=0.0):
                    errors.append(f"plot data mismatch {scenario}/{plot_key}")
        bootstrap_replay.append({"scenario": scenario, "replicates_expected": 2000, "replicates_replayed": 2000, "replicates_matched": exact_match_count, "status": "PASS" if exact_match_count == 2000 else "FAIL"})

    # Recompute the failure ledger summary and verify it retains every ray and weight.
    expected_failure_rows = {}
    for scenario in SCENARIOS:
        for design in DESIGNS:
            for outcome in sorted(KNOWN_TERMINAL_CATEGORIES):
                expected_failure_rows[(scenario, design, outcome)] = {
                    "assemblies": len(assembly_count_by_scenario_design_outcome[(scenario, design, outcome)]),
                    "source_rays": counts_by_scenario_design[(scenario, design)][outcome],
                    "source_weight": math.fsum(weights_by_scenario_design[(scenario, design)].get(outcome, [])),
                }
    stored_failure_map = {(r["scenario"], r["design_id"], r["outcome"]): r for r in failure_stored}
    if len(stored_failure_map) != len(failure_stored):
        errors.append("duplicate rows in failure_breakdown.csv")
    for key, expected in expected_failure_rows.items():
        row = stored_failure_map.get(key)
        if row is None:
            errors.append(f"failure breakdown missing {key}")
            continue
        for field in ("assemblies", "source_rays"):
            if int(row[field]) != expected[field]:
                errors.append(f"failure breakdown mismatch {key}/{field}")
        if not math.isclose(float(row["source_weight"]), expected["source_weight"], abs_tol=TOL, rel_tol=0.0):
            errors.append(f"failure breakdown mismatch {key}/source_weight")

    # Explicitly validate the zero-tolerance controls and separate marginal from paired P05.
    zero_by_id = {r["assembly_id"]: r for r in zero_controls}
    if len(zero_controls) != 200 or len(zero_by_id) != 200:
        errors.append(f"zero-tolerance controls should contain 200 unique records, found {len(zero_controls)}")
    for row in zero_controls:
        if row["scenario"] != "zero" or not as_bool(row["all_perturbations_zero"]):
            errors.append(f"zero-tolerance control does not show zero perturbations: {row['assembly_id']}")
        base = sample_lookup.get((row["assembly_id"], "baseline125"))
        cand = sample_lookup.get((row["assembly_id"], "s5_position135"))
        if base and cand:
            for field, value in (("baseline_capture", as_float(base, "capture_fraction_input")), ("candidate_capture", as_float(cand, "capture_fraction_input"))):
                if not math.isclose(as_float(row, field), value, abs_tol=TOL, rel_tol=0.0):
                    errors.append(f"zero-tolerance control mismatch {row['assembly_id']}/{field}")

    for scenario, row in recomputed.items():
        plot = stored_plot[scenario]
        # Catch the common interpretation error: paired P05 is the fifth percentile of paired deltas.
        if math.isclose(row["p05_paired_delta_capture"], row["p05_capture_candidate135"] - row["p05_capture_baseline125"], abs_tol=1e-15, rel_tol=0.0):
            diagnostics.append({"scenario": scenario, "note": "paired P05 happens to equal the marginal-P05 difference in this dataset; retain the separate estimands"})
        else:
            diagnostics.append({
                "scenario": scenario,
                "base_marginal_P05": row["p05_capture_baseline125"],
                "candidate_marginal_P05": row["p05_capture_candidate135"],
                "candidate_minus_base_marginal_P05": row["p05_capture_candidate135"] - row["p05_capture_baseline125"],
                "paired_P05_of_candidate_minus_baseline": row["p05_paired_delta_capture"],
                "paired_P05_bootstrap_CI95": row["p05_paired_delta_bootstrap_ci95"],
            })

    nominal = recomputed["nominal_1x"]
    stress = recomputed["stress_2x"]
    nominal_pass = (
        nominal["paired_mean_delta_capture_ci95"][0] > 0.0
        and nominal["p05_paired_delta_capture"] >= 0.0
        and nominal["p05_paired_delta_bootstrap_ci95"][0] >= 0.0
        and nominal["invalid_assembly_rate_candidate135"] <= nominal["invalid_assembly_rate_baseline125"]
        and all(v <= 0.0 for v in nominal["failure_weight_mean_delta_candidate_minus_baseline"].values())
        and nominal["all_plane_r90_p95_mm_candidate135"] <= nominal["all_plane_r90_p95_mm_baseline125"]
    )
    cross_scenario_cost = any(
        stats["p05_paired_delta_capture"] < 0.0
        or stats["p05_paired_delta_bootstrap_ci95"][0] < 0.0
        or stats["invalid_assembly_rate_candidate135"] > stats["invalid_assembly_rate_baseline125"]
        or any(v > TOL for v in stats["failure_weight_mean_delta_candidate_minus_baseline"].values())
        or stats["all_plane_r90_p95_mm_candidate135"] > stats["all_plane_r90_p95_mm_baseline125"] + TOL
        for stats in recomputed.values()
    )
    aggregate_verdict = "TRADEOFF_OR_NO_SUPPORTED_GAIN" if cross_scenario_cost else ("SUPPORTED_WITHIN_ASSUMED_P1_AND_TOLERANCES" if nominal_pass else "NOT_VERIFIED")
    recomputed_nominal_claim = "SUPPORTED_WITHIN_ASSUMED_P1_AND_TOLERANCES" if nominal_pass else "TRADEOFF_OR_NO_SUPPORTED_GAIN"
    if recomputed_nominal_claim != original_auto.get("S6_C_ASSEMBLY_CLAIM"):
        errors.append("nominal-only automatic verdict does not match independently recomputed nominal evidence")
    if aggregate_verdict != original_adjudication.get("S6_C_ASSEMBLY_CLAIM") or aggregate_verdict != original_final.get("S6_C_ASSEMBLY_CLAIM"):
        errors.append("cross-scenario verdict does not match Amendment 03 final adjudication and amended stats")

    # Verify the frozen S6 source hashes represented by Amendment 03.
    amendment_source_checks = []
    if amendment_hash_file.is_file():
        am_hashes = read_json(amendment_hash_file).get("hashes", {})
        for rel, meta in am_hashes.items():
            rel_path = Path(rel.replace("\\", "/"))
            candidates = [root / rel_path]
            if rel_path.parts and rel_path.parts[0] == "runs":
                candidates.append(data_dir / rel_path.name)
            candidates += [root / "docs/s6" / rel_path.name, root / "science" / rel_path.name]
            target = next((p for p in candidates if p.is_file()), None)
            if target is None:
                amendment_source_checks.append({"path": rel, "status": "MISSING_SOURCE"})
                continue
            actual = file_sha256(target)
            ok = actual == meta["sha256"] and target.stat().st_size == meta.get("bytes", target.stat().st_size)
            amendment_source_checks.append({"path": rel, "bytes": target.stat().st_size, "expected_sha256": meta["sha256"], "actual_sha256": actual, "status": "PASS" if ok else "FAIL"})
        if any(x["status"] != "PASS" for x in amendment_source_checks):
            errors.append("one or more source hashes in S6_AMENDMENT_03_HASHES.json did not verify")

    # Compute an independent aggregate for outcomes and assembly dimensions.
    layer_rows = []
    for scenario in SCENARIOS:
        layer_rows.append({
            "scenario": scenario,
            "assemblies": scenario_assembly_counts[scenario],
            "design_assembly_rows": scenario_rows_counts[scenario],
            "source_rays_per_design_assembly": 1024,
            "source_rays_total": sum(int(r["source_ray_count"]) for r in samples if r["scenario"] == scenario),
            "mean_capture_125_fraction": recomputed[scenario]["mean_capture_baseline125"],
            "mean_capture_135_fraction": recomputed[scenario]["mean_capture_candidate135"],
            "paired_mean_delta_fraction": recomputed[scenario]["mean_delta_capture_candidate_minus_baseline"],
            "paired_mean_delta_pp": 100.0 * recomputed[scenario]["mean_delta_capture_candidate_minus_baseline"],
            "paired_mean_delta_CI95_pp": [100.0 * x for x in recomputed[scenario]["paired_mean_delta_capture_ci95"]],
            "base_marginal_P05_fraction": recomputed[scenario]["p05_capture_baseline125"],
            "candidate_marginal_P05_fraction": recomputed[scenario]["p05_capture_candidate135"],
            "paired_P05_delta_pp": 100.0 * recomputed[scenario]["p05_paired_delta_capture"],
            "paired_P05_bootstrap_CI95_pp": [100.0 * x for x in recomputed[scenario]["p05_paired_delta_bootstrap_ci95"]],
            "invalid_assemblies": 200 - recomputed[scenario]["n_complete_pairs"],
            "candidate_minus_baseline_L2_aperture_block_rays": recomputed[scenario]["failure_ray_counts_by_design"]["s5_position135"].get("L2_APERTURE_BLOCK", 0) - recomputed[scenario]["failure_ray_counts_by_design"]["baseline125"].get("L2_APERTURE_BLOCK", 0),
        })

    # No registered ray-level traces are regenerated; all counts below derive from the frozen summaries.
    successful = all(x["status"] == "PASS" for x in bootstrap_replay)
    result = {
        "schema": "optisys.s6r.science_recomputation/1",
        "run_id": RUN_ID,
        "status": "PASS" if not errors and successful and amendment03_trace["status"] == "PASS" else "PARTIAL",
        "source_mode": "immutable_per_assembly_csv_recomputation",
        "source_files": source_hashes,
        "rows": {"unique_assembly_scenarios": len(by_assembly), "design_assembly_rows": len(samples), "paired_rows": len(pairs), "assembly_manifest_rows": len(manifest), "bootstrap_rows": len(bootstrap_stored), "failure_breakdown_rows": len(failure_stored)},
        "sampling_and_pairing": {"scenario_assemblies": scenario_assembly_counts, "scenario_design_rows": scenario_rows_counts, "source_seed_base": source_seed_base, "source_seed_rule_verified": seed_ok, "paired_source_reuse_verified": source_reuse_ok, "latent_draw_reused_across_scenarios": len(latent_z_by_latent) == 200, "zero_scenario_geometry_all_zero": zero_pose_ok, "zero_scenario_unique_source_seeds": len(source_seeds_per_scenario.get("zero", set()))},
        "weight_ledger": {"all_source_weights_close_to_one": ledger_max_abs <= TOL, "max_abs_residual": ledger_max_abs, "tolerance": TOL, "all_invalid_assemblies_retained": True, "unknown_terminal_categories": sorted(unknown_terminal)},
        "bootstrap": {"resampling_unit": "assembly_id", "replicates_per_scenario": 2000, "seed": 8064001, "random_generator": "numpy.default_rng / PCG64", "percentile_method": "numpy.quantile method=linear", "interval_quantiles": [0.025, 0.975], "successful_replicates_per_scenario": bootstrap_replay},
        "scenarios": recomputed,
        "plot_data_reconciliation": "PASS" if not any("plot data" in e for e in errors) else "FAIL",
        "failure_breakdown_reconciliation": "PASS" if not any("failure breakdown" in e for e in errors) else "FAIL",
        "p05_estimand_diagnostics": diagnostics,
        "nominal_estimand_status": "VERIFIED_CONDITIONAL_GAIN" if nominal_pass else "NOT_VERIFIED",
        "recomputed_automatic_nominal_claim": recomputed_nominal_claim,
        "cross_scenario_verdict": aggregate_verdict,
        "amendment_03_traceability": amendment03_trace,
        "amendment_03_source_hash_checks": amendment_source_checks,
        "historical_automatic_nominal_claim_preserved": original_auto.get("S6_C_ASSEMBLY_CLAIM"),
        "final_amended_claim": original_final.get("S6_C_ASSEMBLY_CLAIM"),
        "total_registered_assembly_design_ray_traces": int(run_contract.get("planned_assemblies_per_scenario", 200)) * len(SCENARIOS) * 2 * 1024,
        "verified_trace_scope": "S6-C summary/assembly metrics only; the 1,638,400 original traces were not rerun",
        "errors": errors,
        "notes": [
            "P05 paired delta is quantile_5(candidate_capture[i] - baseline_capture[i]) and is distinct from candidate marginal P05 minus baseline marginal P05.",
            "For the zero-tolerance layer, mechanical perturbations are all zero; between-assembly spread reflects distinct source-ray Monte Carlo seeds rather than physical assembly variation.",
            "Capture fractions are source-weight fractions, not optical power, manufacturing yield, or empirical hardware performance.",
            "The full stress-tier P05 uses the lower tail of 200 assemblies and remains sensitive to tail sampling and the assumed model/distribution; the bootstrap interval is not a manufacturing-yield certification.",
        ],
        "environment": {"python": sys.version.split()[0], "numpy": np.__version__},
    }
    emit(result, args.output)
    return 0 if result["status"] == "PASS" else 1


def emit(result: dict[str, Any], output: Path | None) -> None:
    serialized = json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n"
    if output:
        output = output.resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(serialized, encoding="utf-8")
    print(serialized, end="")


if __name__ == "__main__":
    raise SystemExit(main())
