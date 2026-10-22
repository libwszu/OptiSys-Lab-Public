"""G4 end-to-end contract, reports, and non-claim negative controls."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

from optisys.gates.g4 import run_pump976, validate_g4_claims
from optisys.presentation.run_repository import load_run
from optisys.reports.report_service import ReportService

ROOT = Path(__file__).resolve().parents[2]


def _tree_digest(path: Path) -> str:
    rows = []
    for file in sorted(p for p in path.rglob("*") if p.is_file()):
        rel = file.relative_to(path).as_posix()
        digest = hashlib.sha256(file.read_bytes()).hexdigest()
        rows.append(f"{rel}\0{digest}\n")
    return hashlib.sha256("".join(rows).encode()).hexdigest()


def test_small_g4_run_emits_complete_partial_sample_and_report(tmp_path) -> None:
    protected = [
        ROOT / "runs/20261019_130948_G0_78fa364f",
        ROOT / "runs/20261019_145702_G1_54c9e3fb",
        ROOT / "runs/20261019_191117_G2_52369787",
        ROOT / "runs/20261020_071457_G3_ea57a83b",
    ]
    before = [_tree_digest(p) for p in protected]
    run_dir, status = run_pump976(
        "configs/pump976_g4_l0.yaml",
        candidate_path="configs/pump976_g4_l1.yaml",
        tolerance_path="configs/pump976_g4_tolerance.yaml",
        project_root=ROOT,
        runs_dir=tmp_path / "runs",
        rays_override=512,
        assemblies_override=2,
    )
    assert status["status"] == "PARTIAL"
    assert status["G4_ENGINEERING_EXECUTION_STATUS"] == "PARTIAL"
    assert status["G4_TOLERANCE_EVALUATION_STATUS"] == "PARTIAL"
    assert status["G4_EMPIRICAL_VALIDATION_STATUS"] == "NOT_AVAILABLE"
    assert status["INHERITED_G2_SCIENCE_STATUS"] == "QUALIFIED_ONLY"
    assert status["actual_tolerance_rows"] == 8
    for name in (
        "config_snapshot.yaml", "environment.json", "provenance.json", "run_status.json",
        "compute_plan.json", "compute_measured.json", "source_distribution.json",
        "source_samples.npz", "source_distribution_summary.csv", "raytrace_reference.csv",
        "ray_balance.csv", "target_plane_metrics.csv", "target_plane_density.npz",
        "source_samples.csv", "ray_count_convergence.csv", "ray_count_convergence_summary.json",
        "oat.csv", "tolerance_samples.csv", "design_comparison.csv", "split_manifest.json",
        "report.html", "report.md", "run.log", "optical_crosscheck.json",
    ):
        assert (run_dir / name).is_file(), name
    with (run_dir / "tolerance_samples.csv").open(encoding="utf-8", newline="") as f:
        samples = list(csv.DictReader(f))
    assert len(samples) == 8
    assert {row["phase"] for row in samples} == {"precheck", "holdout"}
    assert all(row["balance_residual"] not in (None, "") for row in samples)
    crosscheck = json.loads((run_dir / "optical_crosscheck.json").read_text(encoding="utf-8"))
    assert crosscheck["p0_scalar_reference"]["status"] == "PASS"
    assert crosscheck["p1_low_na_status"] == "PASS"
    convergence = json.loads((run_dir / "ray_count_convergence_summary.json").read_text(encoding="utf-8"))
    assert convergence["status"] in {"PASS", "NOT_CONVERGED"}
    assert len(convergence["confidence_interval_rows"]) == 18

    summary = load_run(run_dir)
    assert summary.gate == "G4"
    assert summary.scientific_status == "QUALIFIED"
    assert summary.evidence.evidence_level == "SIMULATED"

    before_report = _tree_digest(run_dir)
    service = ReportService(tmp_path / "runs", verdict_root=ROOT)
    report = service.build(run_dir)
    assert report.html_path and report.html_path.is_file()
    assert report.markdown_path and report.markdown_path.is_file()
    assert report.frozen_run_untouched is True
    assert _tree_digest(run_dir) == before_report

    assert [_tree_digest(p) for p in protected] == before


def test_quality_gate_rejects_not_run_as_pass() -> None:
    invalid = {
        "status": "PASS", "G4_ENGINEERING_EXECUTION_STATUS": "PASS",
        "G4_OPTICAL_MODEL_VERIFICATION": "PASS",
        "G4_TOLERANCE_EVALUATION_STATUS": "PASS",
        "G4_EMPIRICAL_VALIDATION_STATUS": "PASS",
        "G4_AUDIT_STATUS": "PASS", "G4_SCIENTIFIC_CLAIM": "MEASURED",
        "measured_data_used": False, "expected_tolerance_rows": 100,
        "actual_tolerance_rows": 0,
        "audit_verification": {"content_integrity": False,
                                "extracted_repro": False,
                                "tamper_rejected": False},
    }
    result = validate_g4_claims(invalid, root=ROOT)
    assert not result["valid"]
    assert len(result["errors"]) >= 4
