"""Independent recomputation of the G2 as-run statistics.

Evidence levels produced here
-----------------------------
``STATISTICAL_RECOMPUTE`` — the 126 000 row per-sample record is re-aggregated
from scratch (no reuse of ``summary.json``) and compared against the frozen
summary.  This is *not* a re-execution of the optical chain, and it is not an
experimental validation; it only proves that the frozen numbers follow from the
frozen rows under the declared denominators.

Design rules
------------
* Read-only with respect to every frozen run directory.
* ``n_attempted`` is the denominator for failure rate (all attempts).
* RMSE / P95 / bias use only ``valid`` rows, and the number of contributing
  rows is always reported next to the value.
* Nothing is silently dropped: non-finite errors on valid rows are counted as
  ``VALID_BUT_NONFINITE`` and abort the recompute rather than being skipped.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

CANDIDATES = ("baseline", "nominal", "robust")
ESTIMATORS = ("centroid", "gaussian_2d", "gaussian_2d_integrated")

REQUIRED_COLUMNS = (
    "candidate", "assembly_id", "distance_mm", "condition", "estimator",
    "optical_status", "estimator_status", "u_gt_px", "u_hat_px", "Z_hat_mm",
    "signed_error_mm", "valid", "kernel_support",
)

_TRUE = {"true", "1", "yes", "y", "t"}
_FALSE = {"false", "0", "no", "n", "f", ""}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_bool(text: Any) -> bool | None:
    """Parse a boolean cell.  Anything ambiguous returns ``None``.

    The G2 CSV writes ``True``/``False``; a tolerance for other spellings is
    kept because the same parser is reused for hand-edited fixtures.  Silent
    coercion of an unknown token to ``False`` would turn a read error into a
    fake failure rate, so ``None`` is returned and the caller must decide.
    """

    if isinstance(text, bool):
        return text
    if text is None:
        return None
    token = str(text).strip().lower()
    if token in _TRUE:
        return True
    if token in _FALSE:
        return False
    return None


@dataclass
class RecomputeReport:
    source_path: str
    source_sha256: str
    source_bytes: int
    n_rows: int
    header: list[str]
    truncated_marker: bool = False
    duplicate_keys: list[tuple[str, str, str, str]] = field(default_factory=list)
    missing_columns: list[str] = field(default_factory=list)
    ambiguous_valid_cells: int = 0
    valid_but_nonfinite: int = 0
    per_candidate: dict[str, dict[str, Any]] = field(default_factory=dict)
    per_candidate_estimator: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    per_condition: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    support: dict[str, Any] = field(default_factory=dict)
    status_counts: dict[str, Any] = field(default_factory=dict)
    comparisons: dict[str, Any] = field(default_factory=dict)
    summary_comparison: dict[str, Any] = field(default_factory=dict)
    anomalies: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "source_bytes": self.source_bytes,
            "n_rows": self.n_rows,
            "header": self.header,
            "truncated_marker": self.truncated_marker,
            "duplicate_key_count": len(self.duplicate_keys),
            "duplicate_key_examples": self.duplicate_keys[:10],
            "missing_columns": self.missing_columns,
            "ambiguous_valid_cells": self.ambiguous_valid_cells,
            "valid_but_nonfinite": self.valid_but_nonfinite,
            "per_candidate": self.per_candidate,
            "per_candidate_estimator": self.per_candidate_estimator,
            "per_condition": self.per_condition,
            "support": self.support,
            "status_counts": self.status_counts,
            "comparisons": self.comparisons,
            "summary_comparison": self.summary_comparison,
            "anomalies": self.anomalies,
        }


# ---------------------------------------------------------------------------
# metric primitives (must match gates/g2.py::_metrics exactly)
# ---------------------------------------------------------------------------
def metrics_from_errors(n_attempted: int, errors: Sequence[float]) -> dict[str, Any]:
    """Aggregate a denominator and a list of signed errors.

    ``n_attempted`` is the failure-rate denominator.  ``errors`` carries one
    entry per *valid* attempt, so ``n_valid`` is simply the number of finite
    entries; a non-finite value that reached this point is already a defect
    counted upstream by the caller.

    A cell with ``n_attempted == 0`` reports every statistic as ``None``.  It
    must not report ``failure_rate = 1.0``: "nothing was attempted" and
    "everything failed" are different statements, and the second one would be a
    fabricated 100% failure rate in any table that printed it.
    """

    arr = np.asarray([e for e in errors if e is not None and math.isfinite(e)], dtype=float)
    valid = int(arr.size)
    attempted = int(n_attempted)
    if attempted == 0:
        rate: float | None = None
    else:
        rate = 1.0 - valid / attempted
    payload: dict[str, Any] = {
        "n_attempted": attempted,
        "n_valid": valid,
        "n_errors": valid,
        "failure_rate": rate,
        "bias_mm": float(np.mean(arr)) if valid else None,
        "rmse_mm": float(np.sqrt(np.mean(arr ** 2))) if valid else None,
        "p95_abs_mm": float(np.percentile(np.abs(arr), 95)) if valid else None,
        "mae_mm": float(np.mean(np.abs(arr))) if valid else None,
    }
    return payload


def load_rows(path: Path) -> tuple[list[str], list[dict[str, str]], RecomputeReport]:
    report = RecomputeReport(
        source_path=str(path), source_sha256=sha256_file(path),
        source_bytes=path.stat().st_size, n_rows=0, header=[],
    )
    rows: list[dict[str, str]] = []
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        report.header = list(reader.fieldnames or [])
        report.missing_columns = [c for c in REQUIRED_COLUMNS if c not in report.header]
        for raw in reader:
            if raw is None:
                continue
            first = (raw.get(report.header[0]) or "").strip() if report.header else ""
            if first.startswith("#"):
                report.truncated_marker = True
                continue
            rows.append(raw)  # type: ignore[arg-type]
    report.n_rows = len(rows)
    return report.header, rows, report


def recompute(header: list[str], rows: Iterable[dict[str, str]],
              report: RecomputeReport) -> RecomputeReport:
    if report.missing_columns:
        report.anomalies.append(
            "missing columns: " + ", ".join(report.missing_columns))
        return report

    seen: set[tuple[str, str, str, str]] = set()
    per_cand: dict[str, list[float]] = {name: [] for name in CANDIDATES}
    per_cand_attempted: dict[str, int] = {name: 0 for name in CANDIDATES}
    per_cand_est: dict[str, dict[str, list[float]]] = {
        name: {est: [] for est in ESTIMATORS} for name in CANDIDATES}
    per_cand_est_att: dict[str, dict[str, int]] = {
        name: {est: 0 for est in ESTIMATORS} for name in CANDIDATES}
    per_cond: dict[str, dict[str, list[float]]] = {
        name: {} for name in CANDIDATES}
    per_cond_att: dict[str, dict[str, int]] = {name: {} for name in CANDIDATES}
    status_counts: dict[str, dict[str, int]] = {name: {} for name in CANDIDATES}
    support_samples: dict[str, list[float]] = {name: [] for name in CANDIDATES}
    by_unit: dict[str, dict[tuple[str, float], dict[str, Any]]] = {
        name: {} for name in CANDIDATES}

    for row in rows:
        cand = row["candidate"].strip()
        if cand not in per_cand:
            report.anomalies.append(f"unknown candidate {cand!r}")
            continue
        est = row["estimator"].strip()
        cond = row["condition"].strip()
        dist = float(row["distance_mm"])
        key = (cand, row["assembly_id"].strip(), f"{dist:.6f}", est)
        if key in seen:
            if len(report.duplicate_keys) < 50:
                report.duplicate_keys.append(key)
            continue
        seen.add(key)

        flag = parse_bool(row.get("valid"))
        if flag is None:
            report.ambiguous_valid_cells += 1
            flag = False
        per_cand_attempted[cand] += 1
        per_cand_est_att[cand][est] = per_cand_est_att[cand].get(est, 0) + 1

        status = row.get("estimator_status", "")
        status_counts[cand][status] = status_counts[cand].get(status, 0) + 1

        if row.get("kernel_support"):
            try:
                support_samples[cand].append(float(row["kernel_support"]))
            except ValueError:
                pass

        error: float | None = None
        if flag:
            raw_error = row.get("signed_error_mm", "")
            try:
                error = float(raw_error)
            except (TypeError, ValueError):
                error = None
            if error is None or not math.isfinite(error):
                report.valid_but_nonfinite += 1
                error = None
        if error is not None:
            per_cand[cand].append(error)
            per_cand_est[cand].setdefault(est, []).append(error)
            per_cond[cand].setdefault(cond, []).append(error)
            by_unit[cand][(row["assembly_id"].strip(), dist)] = {
                "error": error, "estimator": est, "valid": True}
        else:
            per_cond[cand].setdefault(cond, [])
            by_unit[cand].setdefault((row["assembly_id"].strip(), dist), {
                "error": None, "estimator": est, "valid": False})
        per_cond_att[cand][cond] = per_cond_att[cand].get(cond, 0) + 1

    for name in CANDIDATES:
        report.per_candidate[name] = metrics_from_errors(
            per_cand_attempted[name], per_cand[name])
        report.per_candidate_estimator[name] = {
            est: metrics_from_errors(per_cand_est_att[name].get(est, 0),
                                     per_cand_est[name].get(est, []))
            for est in ESTIMATORS
        }
        report.per_condition[name] = {
            cond: metrics_from_errors(per_cond_att[name].get(cond, 0), errs)
            for cond, errs in sorted(per_cond[name].items())
        }
        samples = np.asarray(support_samples[name], dtype=float)
        report.support[name] = {
            "n": int(samples.size),
            "min": float(samples.min()) if samples.size else None,
            "max": float(samples.max()) if samples.size else None,
            "mean": float(samples.mean()) if samples.size else None,
            "fraction_below_0.999": float(np.mean(samples < 0.999)) if samples.size else None,
            "fraction_below_0.975": float(np.mean(samples < 0.975)) if samples.size else None,
            "fraction_below_0.950": float(np.mean(samples < 0.950)) if samples.size else None,
        }
    report.status_counts = status_counts

    # paired comparison on the intersection of (assembly, distance)
    pairs = [("baseline", "nominal"), ("baseline", "robust"), ("nominal", "robust")]
    for a_name, b_name in pairs:
        a = by_unit[a_name]
        b = by_unit[b_name]
        common = sorted(set(a) & set(b))
        both_valid = 0
        a_only = 0
        b_only = 0
        err_a: list[float] = []
        err_b: list[float] = []
        for key in common:
            ea, eb = a[key], b[key]
            if ea["valid"] and eb["valid"]:
                both_valid += 1
                err_a.append(float(ea["error"]))
                err_b.append(float(eb["error"]))
            elif ea["valid"]:
                a_only += 1
            elif eb["valid"]:
                b_only += 1
        n_a_att = report.per_candidate[a_name]["n_attempted"]
        n_b_att = report.per_candidate[b_name]["n_attempted"]
        entry: dict[str, Any] = {
            "n_common_keys": len(common),
            "n_both_valid": both_valid,
            "n_only_a_valid": a_only,
            "n_only_b_valid": b_only,
            "n_attempted_a": n_a_att,
            "n_attempted_b": n_b_att,
            "failure_rate_a": report.per_candidate[a_name]["failure_rate"],
            "failure_rate_b": report.per_candidate[b_name]["failure_rate"],
            "failure_delta_b_minus_a": (
                report.per_candidate[b_name]["failure_rate"]
                - report.per_candidate[a_name]["failure_rate"]),
            "rmse_a_on_common_mm": None,
            "rmse_b_on_common_mm": None,
            "rmse_delta_on_common_mm": None,
        }
        if both_valid:
            ea = np.asarray(err_a)
            eb = np.asarray(err_b)
            rmse_a = float(np.sqrt(np.mean(ea ** 2)))
            rmse_b = float(np.sqrt(np.mean(eb ** 2)))
            entry["rmse_a_on_common_mm"] = rmse_a
            entry["rmse_b_on_common_mm"] = rmse_b
            entry["rmse_delta_on_common_mm"] = rmse_b - rmse_a
            # sign convention: positive delta = A worse reduction (B better)
            entry["paired_note"] = (
                "delta = B - A on the same (assembly, distance) units; "
                "only units valid in BOTH candidates contribute to RMSE")
        report.comparisons[f"{a_name}_vs_{b_name}"] = entry
    return report


def compare_with_summary(report: RecomputeReport, summary: dict[str, Any],
                         rtol: float = 1e-9, atol_rate: float = 1e-12) -> dict[str, Any]:
    """Compare recomputed candidate metrics against the frozen summary."""

    out: dict[str, Any] = {}
    frozen = summary.get("candidates", {})
    for name in CANDIDATES:
        mine = report.per_candidate.get(name)
        theirs = frozen.get(name, {})
        if not mine or not theirs:
            out[name] = {"status": "MISSING"}
            continue
        entry: dict[str, Any] = {}
        for key in ("n_attempted", "n_valid"):
            a, b = mine.get(key), theirs.get(key)
            entry[key] = {"recomputed": a, "frozen": b,
                          "match": (a is not None and b is not None and int(a) == int(b))}
        for key, tol in (("rmse_mm", rtol), ("p95_abs_mm", rtol), ("bias_mm", rtol),
                         ("mae_mm", rtol)):
            a, b = mine.get(key), theirs.get(key)
            if a is None or b is None:
                entry[key] = {"recomputed": a, "frozen": b, "match": False}
                continue
            denom = max(abs(float(b)), 1e-15)
            rel = abs(float(a) - float(b)) / denom
            entry[key] = {"recomputed": a, "frozen": b, "rel_diff": rel,
                          "match": bool(rel <= tol)}
        a, b = mine.get("failure_rate"), theirs.get("failure_rate")
        entry["failure_rate"] = {
            "recomputed": a, "frozen": b,
            "abs_diff": None if a is None or b is None else abs(float(a) - float(b)),
            "match": (a is not None and b is not None
                      and abs(float(a) - float(b)) <= atol_rate),
        }
        entry["status"] = "MATCH" if all(
            value.get("match") for value in entry.values()
            if isinstance(value, dict)) else "MISMATCH"
        out[name] = entry

    # per-estimator frozen comparison
    frozen_est = summary.get("by_estimator", {})
    est_out: dict[str, Any] = {}
    for name in CANDIDATES:
        rows = frozen_est.get(name) or []
        if not rows:
            est_out[name] = {"status": "ABSENT_IN_SUMMARY"}
            continue
        index = {row.get("estimator"): row for row in rows}
        est_out[name] = {}
        for est in ESTIMATORS:
            mine = report.per_candidate_estimator[name].get(est)
            theirs = index.get(est)
            if not mine or not theirs:
                est_out[name][est] = {"status": "MISSING"}
                continue
            rmse_a, rmse_b = mine.get("rmse_mm"), theirs.get("rmse_mm")
            rel = (None if rmse_a is None or rmse_b in (None, 0)
                   else abs(float(rmse_a) - float(rmse_b)) / abs(float(rmse_b)))
            est_out[name][est] = {
                "n_attempted": {"recomputed": mine.get("n_attempted"),
                                "frozen": theirs.get("n_attempted"),
                                "match": int(mine.get("n_attempted", -1))
                                == int(theirs.get("n_attempted", -2))},
                "n_valid": {"recomputed": mine.get("n_valid"),
                            "frozen": theirs.get("n_valid"),
                            "match": int(mine.get("n_valid", -1))
                            == int(theirs.get("n_valid", -2))},
                "rmse_mm": {"recomputed": rmse_a, "frozen": rmse_b, "rel_diff": rel,
                            "match": bool(rel is not None and rel <= rtol)},
            }
    report.summary_comparison = {"per_candidate": out, "per_estimator": est_out}
    return report.summary_comparison


def overall_verdict(report: RecomputeReport) -> dict[str, Any]:
    blockers: list[str] = []
    if report.truncated_marker:
        blockers.append("source CSV contains a '# TRUNCATED' marker line")
    if report.missing_columns:
        blockers.append("required columns missing")
    if report.duplicate_keys:
        blockers.append(f"{len(report.duplicate_keys)} duplicate primary keys")
    if report.valid_but_nonfinite:
        blockers.append(f"{report.valid_but_nonfinite} valid rows with non-finite error")
    if report.ambiguous_valid_cells:
        blockers.append(f"{report.ambiguous_valid_cells} unparseable 'valid' cells")

    statuses = [entry.get("status") for entry in
                report.summary_comparison.get("per_candidate", {}).values()]
    mismatched = [name for name, entry in
                  report.summary_comparison.get("per_candidate", {}).items()
                  if entry.get("status") != "MATCH"]

    if blockers:
        verdict = "INSUFFICIENT_EVIDENCE"
    elif mismatched:
        verdict = "MISMATCH"
    elif report.n_rows == 126000:
        verdict = "FULLY_RECOMPUTED"
    else:
        verdict = "RECOMPUTED_PARTIAL_ROWS"
    return {
        "verdict": verdict,
        "n_rows": report.n_rows,
        "expected_rows": 126000,
        "candidate_statuses": statuses,
        "mismatched_candidates": mismatched,
        "blockers": blockers,
        "evidence_level": "STATISTICAL_RECOMPUTE",
        "not_evidence_of": [
            "physical measurement",
            "optical re-execution",
            "original pre-registration compliance",
        ],
    }


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path,
                        default=Path("runs/20261019_191117_G2_52369787"))
    parser.add_argument("--out", type=Path,
                        default=Path("artifacts/g3/pre/g2_recompute.json"))
    parser.add_argument("--bootstrap", type=int, default=2000,
                        help="bootstrap resamples per paired comparison (0 disables)")
    parser.add_argument("--seed", type=int, default=424242)
    args = parser.parse_args(argv)

    sampled = args.run / "independent_validation" / "sampled_results.csv"
    summary_path = args.run / "independent_validation" / "summary.json"
    if not sampled.is_file():
        print(json.dumps({"verdict": "INSUFFICIENT_EVIDENCE",
                          "error": f"missing {sampled}"}, indent=2))
        return 2

    header, rows, report = load_rows(sampled)
    recompute(header, rows, report)
    summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.is_file() else {}
    compare_with_summary(report, summary)

    if args.bootstrap > 0:
        _add_bootstrap(report, args.run, args.seed, args.bootstrap)

    verdict = overall_verdict(report)
    payload = {"verdict": verdict, "report": report.to_dict()}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
    print(json.dumps(verdict, indent=2))
    print(f"written: {args.out}")
    return 0 if verdict["verdict"].startswith(("FULLY", "RECOMPUTED")) else 1


def _add_bootstrap(report: RecomputeReport, run_dir: Path, seed: int, n_boot: int) -> None:
    """Cluster bootstrap on assemblies for the paired RMSE difference."""

    from optisys.evaluation.paired_comparison import paired_bootstrap, paired_rate_difference

    sampled = run_dir / "independent_validation" / "sampled_results.csv"
    header, rows, _ = load_rows(sampled)
    # rebuild per-candidate valid error maps
    store: dict[str, dict[tuple[str, float], float]] = {name: {} for name in CANDIDATES}
    attempt: dict[str, set[tuple[str, float]]] = {name: set() for name in CANDIDATES}
    for row in rows:
        cand = row["candidate"].strip()
        if cand not in store:
            continue
        key = (row["assembly_id"].strip(), float(row["distance_mm"]))
        attempt[cand].add(key)
        if parse_bool(row.get("valid")) and row.get("signed_error_mm"):
            try:
                store[cand][key] = float(row["signed_error_mm"])
            except ValueError:
                continue
    for pair, entry in report.comparisons.items():
        a_name, b_name = pair.split("_vs_")
        common = sorted(set(store[a_name]) & set(store[b_name]))
        if len(common) < 10:
            entry["bootstrap"] = {"status": "INSUFFICIENT_PAIRS", "n_pairs": len(common)}
            continue
        ea = np.array([store[a_name][k] for k in common], dtype=float)
        eb = np.array([store[b_name][k] for k in common], dtype=float)
        clusters = np.array([k[0] for k in common])
        try:
            rmse = paired_bootstrap(ea, eb, clusters, metric="rmse",
                                    n_boot=n_boot, seed=seed)
            rmse_payload = rmse.to_dict()
        except ValueError as exc:
            rmse_payload = {"status": "NOT_ESTIMABLE", "error": str(exc)}
        all_keys = sorted(attempt[a_name] & attempt[b_name])
        succ_a = np.array([1.0 if a_name in store and k in store[a_name] else 0.0
                           for k in all_keys])
        succ_b = np.array([1.0 if k in store[b_name] else 0.0 for k in all_keys])
        cl2 = np.array([k[0] for k in all_keys])
        try:
            rate = paired_rate_difference(succ_a, succ_b, cl2,
                                          n_boot=n_boot, seed=seed + 1)
            rate_payload = rate.to_dict()
        except ValueError as exc:
            rate_payload = {"status": "NOT_ESTIMABLE", "error": str(exc)}
        entry["bootstrap"] = {
            "rmse": rmse_payload, "failure_rate": rate_payload,
            "n_boot": n_boot, "seed": seed,
            "cluster_unit": "assembly_id",
            "note": "recomputed independently from the per-sample CSV; "
                    "FROZEN ci_results.json was produced by the run itself",
        }


if __name__ == "__main__":
    raise SystemExit(main())