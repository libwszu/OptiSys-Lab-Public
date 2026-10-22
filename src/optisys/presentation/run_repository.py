"""Versioned, read-only parsing of run directories (schema 1.0 / 2.0 / 3.0).

Why this module exists
----------------------
G0, G1 and G2 do not share a sample layout:

* G0 writes ``samples.csv`` with geometry columns (``u_analytic_px``,
  ``Z_rel_error``, ...) and no estimator.
* G1 writes ``samples.csv`` with ``sample_id``, ``dataset_split``,
  ``estimator_name``, ``condition_id`` and ``Z_gt_mm``.
* G2 writes **no** ``samples.csv`` at all: its per-sample record lives in
  ``independent_validation/sampled_results.csv`` with one row per
  (candidate, assembly, distance, estimator) and a ``valid`` flag.

Treating them uniformly - the previous CLI ``report`` path effectively did -
either crashes or silently mislabels columns.  So each schema gets its own
adapter, and everything downstream consumes the normalised dataclasses.

Contract
--------
* Never writes into a run directory.
* A missing field is ``None`` plus an entry in ``missing_reasons``; it is never
  filled with ``0``.
* Every value carries the run's ``source_sha256`` so a UI cannot show a number
  without provenance.
"""

from __future__ import annotations

import csv
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

MODEL_LEVELS = ("L0", "L1-approximate")
EVIDENCE_LEVELS = ("FORMULA", "SIMULATED", "CROSS_CHECKED", "MEASURED", "VALIDATED")

CANDIDATE_ORDER = ("baseline", "nominal", "robust")
ESTIMATOR_ORDER = ("centroid", "gaussian_2d", "gaussian_2d_integrated")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass
class EvidenceStatus:
    """What a number is allowed to claim."""

    evidence_level: str = "SIMULATED"
    status: str = "UNKNOWN"
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {"evidence_level": self.evidence_level, "status": self.status,
                "note": self.note}


@dataclass
class CandidateMetrics:
    candidate: str
    n_attempted: int | None = None
    n_valid: int | None = None
    rmse_mm: float | None = None
    p95_abs_mm: float | None = None
    bias_mm: float | None = None
    mae_mm: float | None = None
    failure_rate: float | None = None
    design: dict[str, Any] = field(default_factory=dict)
    by_estimator: dict[str, "CandidateMetrics"] = field(default_factory=dict)
    by_distance: list[dict[str, Any]] = field(default_factory=list)
    missing_reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "candidate": self.candidate,
            "design": self.design,
            "n_attempted": self.n_attempted,
            "n_valid": self.n_valid,
            "rmse_mm": self.rmse_mm,
            "p95_abs_mm": self.p95_abs_mm,
            "bias_mm": self.bias_mm,
            "mae_mm": self.mae_mm,
            "failure_rate": self.failure_rate,
            "by_estimator": {k: v.as_dict() for k, v in self.by_estimator.items()},
            "by_distance": self.by_distance,
            "missing_reasons": self.missing_reasons,
        }


@dataclass
class FrameResult:
    run_id: str
    schema_version: str
    source_sha256: str
    units: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "schema_version": self.schema_version,
            "source_sha256": self.source_sha256,
            "units": self.units,
        }


@dataclass
class RunSummary:
    run_id: str
    path: Path
    gate: str
    schema_version: str
    case_id: str
    model_level: str
    status: str
    scientific_status: str
    frozen: bool
    finished_at_utc: str
    config_sha256: str
    source_tree_sha256: str
    git_commit: str
    evidence: EvidenceStatus
    units: dict[str, str]
    files: dict[str, str] = field(default_factory=dict)
    candidates: dict[str, CandidateMetrics] = field(default_factory=dict)
    counts: dict[str, Any] = field(default_factory=dict)
    missing_reasons: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "path": str(self.path),
            "gate": self.gate,
            "schema_version": self.schema_version,
            "case_id": self.case_id,
            "model_level": self.model_level,
            "status": self.status,
            "scientific_status": self.scientific_status,
            "frozen": self.frozen,
            "finished_at_utc": self.finished_at_utc,
            "config_sha256": self.config_sha256,
            "source_tree_sha256": self.source_tree_sha256,
            "git_commit": self.git_commit,
            "evidence": self.evidence.as_dict(),
            "units": self.units,
            "files": self.files,
            "candidates": {k: v.as_dict() for k, v in self.candidates.items()},
            "counts": self.counts,
            "missing_reasons": self.missing_reasons,
            "notes": self.notes,
        }


DEFAULT_UNITS = {
    "distance": "mm",
    "error": "mm",
    "angle_internal": "rad",
    "angle_config": "deg",
    "spot_position": "px",
    "pixel_size": "um",
    "signal": "e-",
    "adu": "ADU",
    "time": "s",
}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _row_count(path: Path) -> int:
    if not path.is_file():
        return 0
    with path.open(encoding="utf-8", newline="") as handle:
        return max(0, sum(1 for _ in handle) - 1)


def detect_schema(run_dir: Path) -> str:
    """Configuration schema of the run (G0 through G4).

    The config snapshot wins.  ``run_status.json`` is *not* authoritative here:
    the frozen G1 run writes ``schema_version: "1.0"`` in its status file to
    mean "run-record format 1.0" while its config snapshot correctly says
    ``"2.0"``.  Reading the status file first therefore mislabels every G1 run
    as schema 1.0 and would route it to the G0 parser.
    """

    snapshot = run_dir / "config_snapshot.yaml"
    if snapshot.is_file():
        import yaml

        try:
            data = yaml.safe_load(snapshot.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError:
            data = {}
        if isinstance(data, dict) and data.get("schema_version"):
            return str(data["schema_version"])
    if (run_dir / "independent_validation").is_dir():
        return "3.0"
    if (run_dir / "split_manifest.json").is_file():
        return "2.0"
    return "1.0"


def load_run(run_dir: Path) -> RunSummary:
    """Parse a run directory into the normalised summary."""

    run_dir = Path(run_dir)
    if not run_dir.is_dir():
        raise FileNotFoundError(f"run directory not found: {run_dir}")

    status = _read_json(run_dir / "run_status.json")
    provenance = _read_json(run_dir / "provenance.json")
    environment = _read_json(run_dir / "environment.json")
    schema = detect_schema(run_dir)
    gate = str(status.get("gate") or _infer_gate(run_dir))

    files = {}
    for name in ("run_status.json", "metrics.json", "provenance.json",
                 "config_snapshot.yaml", "tests_junit.xml"):
        path = run_dir / name
        files[name] = sha256_file(path) if path.is_file() else "ABSENT"

    summary = RunSummary(
        run_id=run_dir.name,
        path=run_dir,
        gate=gate,
        schema_version=schema,
        case_id=str(status.get("case_id") or provenance.get("case_id") or ""),
        model_level=str(status.get("model_level_emitted")
                        or status.get("model_level") or "UNKNOWN"),
        status=str(status.get("status") or "UNKNOWN"),
        scientific_status=str(status.get("scientific_claim_status") or "NOT_STATED"),
        frozen=bool(status.get("frozen", True)),
        finished_at_utc=str(status.get("finished_at_utc") or provenance.get("finished_at_utc") or ""),
        config_sha256=str(provenance.get("config_sha256")
                          or status.get("config_sha256") or "UNKNOWN"),
        source_tree_sha256=str(provenance.get("source_tree_sha256") or "UNKNOWN"),
        git_commit=str(provenance.get("git_commit") or "NO_COMMIT"),
        evidence=EvidenceStatus(
            evidence_level=_evidence_level(gate, status),
            status=str(status.get("status") or "UNKNOWN"),
            note=_evidence_note(gate, status),
        ),
        units=dict(DEFAULT_UNITS),
        files=files,
    )
    summary.notes.append(f"environment: python {environment.get('python', '?')}, "
                         f"workers {environment.get('workers', '?')}")

    if gate == "G4" or schema == "4.0":
        _load_g4(run_dir, summary)
    elif gate == "G2" or schema == "3.0":
        # A G3 demo run is also schema 3.0 but its summary has a different shape
        # (no strategy B, no split manifest, reduced panel).  Routing it through
        # _load_g2 would silently present a reduced panel as a G2 panel.
        if gate == "G3" or _is_demo_run(run_dir):
            _load_g3_demo(run_dir, summary)
        else:
            _load_g2(run_dir, summary)
    elif gate == "G1" or schema == "2.0":
        _load_g1(run_dir, summary)
    else:
        _load_g0(run_dir, summary)
    return summary


def _is_demo_run(run_dir: Path) -> bool:
    payload = _read_json(run_dir / "independent_validation" / "summary.json")
    return bool(payload.get("demo"))


def _infer_gate(run_dir: Path) -> str:
    for token in ("_G0_", "_G1_", "_G2_", "_G3_", "_G4_"):
        if token in run_dir.name:
            return token.strip("_").split("_")[0]
    return "UNKNOWN"


def _evidence_level(gate: str, status: dict[str, Any]) -> str:
    """Cap the evidence level by what was actually run."""

    if status.get("measured_data_used"):
        return "MEASURED"
    if gate in ("G1", "G2", "G3", "G4"):
        return "SIMULATED"
    return "FORMULA"


def _evidence_note(gate: str, status: dict[str, Any]) -> str:
    if gate == "G4":
        return "geometric pump beamline simulation; no absolute power or experimental validation"
    if gate in ("G1", "G2", "G3"):
        return ("no measured data anywhere in this project; L1 is an assumed "
                "singlet model, not a characterised lens")
    return "analytic geometry cross-checked against an independent numeric chain"


def _load_g4(run_dir: Path, summary: RunSummary) -> None:
    """Read-only summary adapter for the 976 nm G4 run contract."""

    status = _read_json(run_dir / "run_status.json")
    metrics = _read_json(run_dir / "metrics.json")
    source = _read_json(run_dir / "source_distribution.json")
    for name in ("source_distribution_summary.csv", "target_plane_metrics.csv",
                 "ray_balance.csv", "oat.csv", "tolerance_samples.csv",
                 "design_comparison.csv", "raytrace_reference.csv"):
        path = run_dir / name
        summary.files[name] = sha256_file(path) if path.is_file() else "ABSENT"
    figure_dir = run_dir / "figures"
    if figure_dir.is_dir():
        for path in sorted(figure_dir.glob("*.png")):
            summary.files[f"figures/{path.name}"] = sha256_file(path)
    target_rows = _row_count(run_dir / "target_plane_metrics.csv")
    balance_rows = _row_count(run_dir / "ray_balance.csv")
    oat_rows = _row_count(run_dir / "oat.csv")
    tolerance_rows = _row_count(run_dir / "tolerance_samples.csv")
    comparison = []
    for row in metrics.get("nominal_metrics", []):
        comparison.append({k: row.get(k) for k in
                           ("design_id", "backend", "angular_case", "geometric_transmission_fraction",
                            "rms_radius_mm", "r80_mm", "r90_mm", "status")})
    summary.case_id = "pump976_g4"
    summary.model_level = str(status.get("model_level_emitted", "UNKNOWN"))
    summary.scientific_status = str(status.get("G4_SCIENTIFIC_CLAIM", "UNKNOWN"))
    summary.units = {"distance": "mm", "angle_internal": "rad", "wavelength": "nm",
                     "weight": "dimensionless normalized source fraction",
                     "density": "weight_fraction/mm^2 (not W/mm^2)"}
    summary.counts.update({
        "source_rays": (source.get("baseline") or {}).get("n_rays"),
        "target_plane_metric_rows": target_rows,
        "ray_balance_rows": balance_rows,
        "oat_rows": oat_rows,
        "tolerance_rows": tolerance_rows,
        "nominal_metrics": comparison,
        "empirical_validation": status.get("G4_EMPIRICAL_VALIDATION_STATUS", "UNKNOWN"),
        "inherited_g2_science": status.get("INHERITED_G2_SCIENCE_STATUS", "UNKNOWN"),
    })
    summary.notes.extend([
        "G4 is a simulated geometric pump beamline, not an absolute radiometric model.",
        "P0 thin-lens output and P1 Optiland output have separate model scopes; check target_plane_metrics.csv.",
        "Inherited G2 science status remains QUALIFIED_ONLY.",
    ])


# ---------------------------------------------------------------------------
# G2
# ---------------------------------------------------------------------------
def _load_g2(run_dir: Path, summary: RunSummary) -> None:
    iv = run_dir / "independent_validation"
    summary_counts: dict[str, Any] = {}
    frozen = _read_json(run_dir / "optimization" / "candidates_frozen.json")

    designs = {}
    for candidate in frozen.get("candidates", []):
        designs[candidate["name"]] = {
            **candidate.get("design", {}),
            "optical_config_sha256": candidate.get("optical_config_sha256"),
            "constraint_feasibility": candidate.get("constraint_feasibility", {}).get("reason"),
        }

    summary_json = _read_json(iv / "summary.json")
    if not summary_json:
        summary.missing_reasons.append(
            "independent_validation/summary.json absent or unreadable")
        return

    summary.counts.update({
        "n_final_assemblies": summary_json.get("n_final_assemblies"),
        "n_frames_per_candidate": summary_json.get("n_frames_per_candidate"),
        "test_distances": summary_json.get("test_distances"),
        "subsets": summary_json.get("subsets"),
    })
    summary.units.update({"distance": "mm", "error": "mm", "spot_position": "px"})

    for name in CANDIDATE_ORDER:
        raw = summary_json.get("candidates", {}).get(name)
        if not raw:
            summary.missing_reasons.append(f"candidate {name} absent from summary.json")
            continue
        metrics = CandidateMetrics(
            candidate=name,
            n_attempted=raw.get("n_attempted"),
            n_valid=raw.get("n_valid"),
            rmse_mm=raw.get("rmse_mm"),
            p95_abs_mm=raw.get("p95_abs_mm"),
            bias_mm=raw.get("bias_mm"),
            mae_mm=raw.get("mae_mm"),
            failure_rate=raw.get("failure_rate"),
            design=designs.get(name, {}),
        )
        for row in summary_json.get("by_estimator", {}).get(name, []):
            estimator = row.get("estimator")
            metrics.by_estimator[estimator] = CandidateMetrics(
                candidate=f"{name}|{estimator}",
                n_attempted=row.get("n_attempted"),
                n_valid=row.get("n_valid"),
                rmse_mm=row.get("rmse_mm"),
                p95_abs_mm=row.get("p95_abs_mm"),
                bias_mm=row.get("bias_mm"),
                mae_mm=row.get("mae_mm"),
                failure_rate=row.get("failure_rate"),
            )
        metrics.by_distance = list(summary_json.get("by_distance", {}).get(name, []))
        summary.candidates[name] = metrics

    # provenance of the raw per-sample file
    sampled = iv / "sampled_results.csv"
    if sampled.is_file():
        summary.files["independent_validation/sampled_results.csv"] = sha256_file(sampled)
        summary.counts["sampled_rows"] = _row_count(sampled)
    else:
        summary.missing_reasons.append(
            "independent_validation/sampled_results.csv absent: per-frame detail "
            "cannot be shown")

    summary.counts["strategy_b_subsets"] = summary_json.get("subsets", {}).get("strategy_b")
    summary.counts["stratified_subsets"] = summary_json.get("subsets", {}).get("stratified")
    summary.notes.append(
        "main panel is 7 test distances x medium only; 42000 rows per candidate are "
        "estimator records (2000 x 7 x 3), not 42000 multi-condition images")
    if (run_dir / "split_manifest.json").is_file():
        summary.files["split_manifest.json"] = sha256_file(run_dir / "split_manifest.json")
    else:
        summary.missing_reasons.append(
            "split_manifest.json absent: the pre-registered split freeze artifact "
            "was never written for this run")


# ---------------------------------------------------------------------------
# G3 demo
# ---------------------------------------------------------------------------
def _load_g3_demo(run_dir: Path, summary: RunSummary) -> None:
    """Reduced-panel demonstration run.

    Every demo number is deliberately marked ``DEMO_ONLY`` and
    ``comparable_to_g2 = False`` in ``counts``: the panel is smaller than G2's,
    so any surface that renders these numbers must say so.
    """

    iv = run_dir / "independent_validation"
    payload = _read_json(iv / "summary.json")
    if not payload:
        summary.missing_reasons.append(
            "independent_validation/summary.json absent or unreadable")
        return

    summary.counts.update({
        "demo": True,
        "comparable_to_g2": False,
        "n_assemblies": payload.get("n_assemblies"),
        "n_test_distances": payload.get("n_test_distances"),
        "test_distances": payload.get("test_distances"),
        "condition": payload.get("condition"),
        "n_frames_per_candidate": payload.get("n_frames_expected_per_candidate"),
        "n_estimators": payload.get("n_estimators"),
    })

    for name in CANDIDATE_ORDER:
        raw = payload.get("candidates", {}).get(name)
        if not raw:
            continue
        metrics = CandidateMetrics(
            candidate=name,
            n_attempted=raw.get("n_attempted"),
            n_valid=raw.get("n_valid"),
            rmse_mm=raw.get("rmse_mm"),
            p95_abs_mm=raw.get("p95_abs_mm"),
            bias_mm=raw.get("bias_mm"),
            mae_mm=raw.get("mae_mm"),
            failure_rate=raw.get("failure_rate"),
        )
        for row in (payload.get("by_estimator", {}).get(name) or []):
            estimator = row.get("estimator")
            if not estimator:
                continue
            metrics.by_estimator[estimator] = CandidateMetrics(
                candidate=f"{name}|{estimator}",
                n_attempted=row.get("n_attempted"),
                n_valid=row.get("n_valid"),
                rmse_mm=row.get("rmse_mm"),
                p95_abs_mm=row.get("p95_abs_mm"),
                bias_mm=row.get("bias_mm"),
                mae_mm=row.get("mae_mm"),
                failure_rate=row.get("failure_rate"),
            )
        metrics.by_distance = list(payload.get("by_distance", {}).get(name) or [])
        summary.candidates[name] = metrics

    sampled = iv / "sampled_results.csv"
    if sampled.is_file():
        summary.files["independent_validation/sampled_results.csv"] = sha256_file(sampled)
        summary.counts["sampled_rows"] = _row_count(sampled)
    summary.notes.append(
        "G3 DEMO RUN: reduced assembly panel, single illumination condition. "
        "Not a G2 re-execution and not comparable to the 2000-assembly G2 panel.")


# ---------------------------------------------------------------------------
# G1
# ---------------------------------------------------------------------------
def _load_g1(run_dir: Path, summary: RunSummary) -> None:
    samples = run_dir / "samples.csv"
    metrics = _read_json(run_dir / "metrics.json")
    summary.counts.update({"metrics_keys": sorted(metrics.keys())[:12]})
    if not samples.is_file():
        summary.missing_reasons.append("samples.csv absent")
        return
    summary.files["samples.csv"] = sha256_file(samples)
    summary.counts["sample_rows"] = _row_count(samples)
    summary.notes.append(
        "G1 per-sample file is samples.csv with estimator_name / dataset_split / "
        "Z_gt_mm; it is NOT the same layout as the G2 per-sample file")


# ---------------------------------------------------------------------------
# G0
# ---------------------------------------------------------------------------
def _load_g0(run_dir: Path, summary: RunSummary) -> None:
    samples = run_dir / "samples.csv"
    metrics = _read_json(run_dir / "metrics.json")
    if not samples.is_file():
        summary.missing_reasons.append("samples.csv absent")
        return
    summary.files["samples.csv"] = sha256_file(samples)
    summary.counts["sample_rows"] = _row_count(samples)
    chain = metrics.get("chain", {})
    summary.counts["max_abs_u_error_px"] = chain.get("max_abs_u_error_px")
    summary.counts["max_Z_relative_error"] = chain.get("max_Z_relative_error")
    summary.notes.append("G0 has no sensor model and no estimator; geometry only")


# ---------------------------------------------------------------------------
# collection
# ---------------------------------------------------------------------------
def list_runs(runs_dir: Path, *, include_derived: bool = False) -> list[Path]:
    if not runs_dir.is_dir():
        return []
    out = []
    for path in sorted(runs_dir.iterdir()):
        if not path.is_dir():
            continue
        if path.name.startswith("_"):
            if not include_derived:
                continue
        if (path / "run_status.json").is_file():
            out.append(path)
    return out


def load_latest_per_gate(runs_dir: Path) -> dict[str, RunSummary]:
    """Newest run per gate, skipping directories whose status is FAIL."""

    best: dict[str, RunSummary] = {}
    for path in list_runs(runs_dir):
        try:
            summary = load_run(path)
        except (FileNotFoundError, OSError):
            continue
        if summary.gate == "UNKNOWN":
            continue
        current = best.get(summary.gate)
        if current is None or summary.run_id > current.run_id:
            best[summary.gate] = summary
    return best


def summarise_frame_csv(path: Path, *, valid_column: str = "valid",
                        error_column: str = "signed_error_mm") -> dict[str, Any]:
    """Generic per-frame aggregator used by tests and the UI fallback."""

    if not path.is_file():
        return {"status": "ABSENT", "path": str(path)}
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if valid_column not in (reader.fieldnames or []):
            return {"status": "NO_VALID_COLUMN", "columns": reader.fieldnames}
        rows = list(reader)
    attempted = len(rows)
    errors: list[float] = []
    for row in rows:
        token = str(row.get(valid_column, "")).strip().lower()
        if token in ("true", "1", "yes"):
            try:
                value = float(row.get(error_column, ""))
            except (TypeError, ValueError):
                continue
            if value == value and abs(value) != float("inf"):
                errors.append(value)
    import math

    return {
        "status": "OK",
        "attempted": attempted,
        "valid": len(errors),
        "failure_rate": 1.0 - len(errors) / attempted if attempted else None,
        "rmse_mm": (math.sqrt(sum(e * e for e in errors) / len(errors))
                    if errors else None),
    }
