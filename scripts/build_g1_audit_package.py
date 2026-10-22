"""Build and verify the frozen G1 GPT audit ZIP.

Structure follows the G1 task book section 8.2.  The G0 audit ZIP is *not*
nested; only its run id, hash and regression evidence are included under
``baseline_g0/``.

Usage:
    python scripts/build_g1_audit_package.py --run runs/<G1_RUN_ID>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from build_audit_package import (  # noqa: E402
    build_zip,
    copy_file,
    copy_tree,
    scan_package,
    sha256_file,
    write_sums,
)

ROOT = Path(__file__).resolve().parents[1]
AUDIT_ROOT = ROOT / "_AUDIT"
G0_RUN = "20261019_130948_G0_78fa364f"
G0_ZIP = ROOT / "_AUDIT" / G0_RUN / f"OptiSysLab_G0_{G0_RUN}_GPT_AUDIT.zip"
G0_ZIP_SHA = "3967d064cbc4349c6d484ec4378cdfe228115545089923b0d2629baab2d34c44"

REQUIRED = [
    "00_START_HERE.md",
    "01_EXECUTIVE_SUMMARY.md",
    "02_SPEC_TRACEABILITY.md",
    "03_SCIENTIFIC_AUDIT.md",
    "04_VALIDATION_MATRIX.md",
    "05_COMPUTE_AND_PERFORMANCE.md",
    "06_REPRODUCTION_GUIDE.md",
    "07_KNOWN_ISSUES_AND_FAILURES.md",
    "08_NEXT_GATE_PLAN.md",
    "GPT_REVIEW_INSTRUCTIONS.md",
    "manifest.json",
    "SHA256SUMS.txt",
    "README.md",
    "pyproject.toml",
    "requirements.lock.txt",
    "source_spec/OptiSys_Lab_Job_Oriented_Development_Plan_2026.pdf",
    "source_spec/source_pdf_sha256.txt",
    "baseline_g0/baseline.json",
    "baseline_g0/G0_REGRESSION.md",
    "configs/triangulation_v0.yaml",
    "configs/triangulation_g1_l0.yaml",
    "configs/gate_requirements.json",
    "src/optisys/gates/g1.py",
    "tests/unit/test_spot.py",
    "repro/verify_g1.py",
    "run_evidence/config_snapshot.yaml",
    "run_evidence/environment.json",
    "run_evidence/compute_plan.json",
    "run_evidence/benchmark.json",
    "run_evidence/metrics.json",
    "run_evidence/provenance.json",
    "run_evidence/run_status.json",
    "run_evidence/calibration.json",
    "run_evidence/split_manifest.json",
    "run_evidence/samples/samples.csv",
    "run_evidence/tests_summary.json",
    "run_evidence/pytest_stdout.txt",
    "run_evidence/pytest_junit.xml",
    "run_evidence/main_run_log_excerpt.txt",
    "run_evidence/g0_regression.json",
    ".github/workflows/ci.yml",
]
REQUIRED_BEFORE_MANIFEST = [name for name in REQUIRED
                            if name not in {"manifest.json", "SHA256SUMS.txt"}]


def build_package(run_dir: Path, package: Path) -> None:
    if package.exists():
        shutil.rmtree(package)
    package.mkdir(parents=True)

    copy_tree(ROOT / "src", package / "src")
    copy_tree(ROOT / "configs", package / "configs")
    copy_tree(ROOT / "tests", package / "tests")
    copy_tree(ROOT / "scripts", package / "scripts")
    copy_tree(ROOT / "repro", package / "repro")
    copy_tree(ROOT / "docs", package / "docs")
    if (ROOT / ".github").is_dir():
        copy_tree(ROOT / ".github", package / ".github")
    for name in ("README.md", "pyproject.toml", "LICENSE", "requirements.lock.txt"):
        copy_file(ROOT / name, package / name)

    audit_docs = ROOT / "docs" / "audit_g1"
    for name in ("00_START_HERE.md", "01_EXECUTIVE_SUMMARY.md", "03_SCIENTIFIC_AUDIT.md",
                 "05_COMPUTE_AND_PERFORMANCE.md", "06_REPRODUCTION_GUIDE.md",
                 "07_KNOWN_ISSUES_AND_FAILURES.md", "08_NEXT_GATE_PLAN.md",
                 "GPT_REVIEW_INSTRUCTIONS.md"):
        copy_file(audit_docs / name, package / name)
    copy_file(ROOT / "docs" / "SPEC_TRACEABILITY.md", package / "02_SPEC_TRACEABILITY.md")
    copy_file(ROOT / "docs" / "VALIDATION_MATRIX.md", package / "04_VALIDATION_MATRIX.md")

    pdf = ROOT / "OptiSys_Lab_Job_Oriented_Development_Plan_2026.pdf"
    copy_file(pdf, package / "source_spec" / pdf.name)
    (package / "source_spec" / "source_pdf_sha256.txt").write_text(
        f"{sha256_file(pdf)}  {pdf.name}\n# bytes: {pdf.stat().st_size}\n", encoding="utf-8"
    )

    # G0 baseline (no nested ZIP).
    baseline = package / "baseline_g0"
    baseline.mkdir()
    regression = json.loads((ROOT / "artifacts" / "g0_regression.json").read_text(encoding="utf-8"))
    (baseline / "baseline.json").write_text(json.dumps({
        "g0_run_id": G0_RUN,
        "g0_zip_sha256": G0_ZIP_SHA,
        "g0_zip_bytes": G0_ZIP.stat().st_size if G0_ZIP.is_file() else None,
        "g0_source_tree_sha256": "054b0919c53cdd1b8e155043decf92a768948c13132ac76b172a8cf039a50960",
        "g0_tests": "117 passed / 0 failed / 0 skipped (historical)",
        "note": "G0 ZIP is not nested; verify it by SHA-256 in the user's original folder.",
        "regression": regression,
    }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    copy_file(ROOT / "artifacts" / "g0_regression.json", baseline / "g0_regression.json")
    (baseline / "G0_REGRESSION.md").write_text(
        "# G0 baseline and regression\n\n"
        f"- G0 frozen run: `{G0_RUN}` (status PASS)\n"
        f"- G0 audit ZIP SHA-256: `{G0_ZIP_SHA}`\n"
        "- G0 ZIP is **not** embedded in this package; the hash above is the reference.\n\n"
        "## Regression re-executed against the G1 source tree\n\n"
        f"- max |u_analytic - u_reference|: `{regression['metrics']['max_abs_u_error_px']:.3e} px`\n"
        f"- max relative Z error: `{regression['metrics']['max_Z_relative_error']:.3e}`\n"
        f"- boundary cases: `{sum(1 for item in regression['boundary_cases'] if item['pass'])}/"
        f"{len(regression['boundary_cases'])}` pass\n"
        f"- all G0 gate checks: `{regression['all_pass']}`\n\n"
        "The G0 test modules remain in `tests/`; the G1 run ingested the full pytest\n"
        "summary, so a failed G0 test would have blocked the G1 gate.\n",
        encoding="utf-8",
    )

    # Run evidence.
    evidence = package / "run_evidence"
    evidence.mkdir()
    for name in ("config_snapshot.yaml", "environment.json", "compute_plan.json",
                 "benchmark.json", "metrics.json", "provenance.json", "run_status.json",
                 "calibration.json", "split_manifest.json", "report.html"):
        copy_file(run_dir / name, evidence / name)
    for src_name, dst_name in (
        ("tests_summary.json", "tests_summary.json"),
        ("pytest_stdout.txt", "pytest_stdout.txt"),
        ("run.log", "main_run_log_excerpt.txt"),
    ):
        copy_file(run_dir / src_name, evidence / dst_name)
    # JUnit carries the machine hostname; redact it in the packaged copy.
    junit_text = (run_dir / "tests_junit.xml").read_text(encoding="utf-8")
    junit_text = re.sub(r'hostname="[^"]*"', 'hostname="REDACTED"', junit_text)
    (evidence / "pytest_junit.xml").write_text(junit_text, encoding="utf-8")
    copy_file(ROOT / "artifacts" / "g0_regression.json", evidence / "g0_regression.json")

    samples_dir = evidence / "samples"
    samples_dir.mkdir()
    copy_file(run_dir / "samples.csv", samples_dir / "samples.csv")
    copy_file(run_dir / "metrics_by_group.csv", samples_dir / "metrics_by_group.csv")
    copy_file(run_dir / "metrics_by_distance.csv", samples_dir / "metrics_by_distance.csv")
    copy_file(run_dir / "failure_breakdown.csv", samples_dir / "failure_breakdown.csv")

    figures = evidence / "figures"
    figures.mkdir()
    for path in sorted((run_dir / "figures").iterdir()):
        if path.is_file():
            copy_file(path, figures / path.name)

    frames = evidence / "representative_frames"
    frames.mkdir()
    for path in sorted((run_dir / "representative_frames").iterdir()):
        if path.is_file():
            copy_file(path, frames / path.name)


def derive_statuses(metrics: dict[str, Any], status_map: dict[str, Any]) -> dict[str, Any]:
    checks = metrics["gate_checks"]

    def group(prefix: str) -> str:
        selected = {k: v for k, v in checks.items() if k.startswith(prefix)}
        return "PASS" if selected and all(v["pass"] for v in selected.values()) else "FAIL"

    v1, v2, v3 = group("v1_"), group("v2_"), group("v3_")
    validation = dict(status_map["validation"])
    validation.update({"V1": v1, "V2": v2, "V3": v3, "V6": "PARTIAL", "V0": "PASS"})

    requirements = dict(status_map["requirements"])
    if v2 != "PASS":
        requirements["R04"] = "IN_PROGRESS"
    if v3 != "PASS":
        requirements["R05"] = "IN_PROGRESS"
        requirements["R06"] = "IN_PROGRESS"
    return {"requirements": requirements, "validation": validation}


def write_manifest(package: Path, run_dir: Path, run_status: dict[str, Any],
                   metrics: dict[str, Any], statuses: dict[str, Any]) -> dict[str, Any]:
    provenance = json.loads((run_dir / "provenance.json").read_text(encoding="utf-8"))
    tests = json.loads((package / "run_evidence" / "tests_summary.json").read_text(encoding="utf-8"))
    calibration = json.loads((run_dir / "calibration.json").read_text(encoding="utf-8"))
    pdf_hash = (package / "source_spec" / "source_pdf_sha256.txt").read_text(
        encoding="utf-8").split()[0]

    files = []
    for path in sorted(package.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(package).as_posix()
        if rel in {"manifest.json", "SHA256SUMS.txt"}:
            continue
        files.append({"path": rel, "bytes": path.stat().st_size, "sha256": sha256_file(path)})

    failures = list(run_status.get("gate_aggregation", {}).get("failures", []))
    manifest = {
        "audit_schema_version": "1.0",
        "project": "OptiSys-Lab",
        "gate": "G1",
        "run_id": run_status["run_id"],
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "result_status": run_status["status"],
        "scientific_claim_status": run_status["scientific_claim_status"],
        "scientific_claim_scope": run_status.get("scientific_claim_scope", ""),
        "source_pdf_sha256": pdf_hash,
        "baseline_g0": {
            "run_id": G0_RUN,
            "zip_sha256": G0_ZIP_SHA,
            "note": "not nested; verified against the original G0 package by the user",
        },
        "git_commit": provenance["code"]["git_commit"],
        "source_tree_sha256": provenance["code"]["source_tree_sha256"],
        "source_tree_scope": provenance["code"]["source_tree_scope"],
        "config_sha256": provenance["inputs"]["config_sha256"],
        "model_level": provenance["code"]["model_level"],
        "random_seeds": provenance["random_seeds"],
        "dataset": metrics["dataset"],
        "calibration": {
            "identifiability": calibration["identifiability"],
            "fits": {
                name: {
                    "a_px_mm": fit.get("a_px_mm"),
                    "b_px": fit.get("b_px"),
                    "status": fit.get("status"),
                    "n_frames_used": fit.get("n_frames_used"),
                }
                for name, fit in calibration["fits"].items()
            },
        },
        "requirements": statuses["requirements"],
        "validation": statuses["validation"],
        "tests": {
            "passed": tests["totals"]["passed"],
            "failed": tests["totals"]["failed"],
            "skipped": tests["totals"]["skipped"],
            "not_run": tests.get("not_run", []),
        },
        "hardware_backend": "CPU",
        "critical_failures": failures,
        "files": files,
    }
    (package / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest


def verify_zip(zip_path: Path, log: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "testzip": None, "hash_mismatches": [], "unsafe_paths": [],
        "file_count": 0, "repro_status": "NOT_REPLAYED", "missing_required": [],
    }
    with zipfile.ZipFile(zip_path) as archive:
        bad = archive.testzip()
        result["testzip"] = "OK" if bad is None else f"CORRUPT: {bad}"
        names = archive.namelist()
        result["file_count"] = len(names)
        for name in names:
            if name.startswith("/") or ".." in Path(name).parts or ":" in name.split("/")[0]:
                result["unsafe_paths"].append(name)

        with tempfile.TemporaryDirectory(prefix="optisys_g1_audit_") as tmp:
            tmp_path = Path(tmp)
            archive.extractall(tmp_path)
            entries = []
            for line in (tmp_path / "SHA256SUMS.txt").read_text(encoding="utf-8").splitlines():
                if line.strip():
                    digest, rel = line.split("  ", 1)
                    entries.append((digest, rel))
            for digest, rel in entries:
                target = tmp_path / rel
                if not target.is_file():
                    result["hash_mismatches"].append(f"missing: {rel}")
                elif sha256_file(target) != digest:
                    result["hash_mismatches"].append(f"hash mismatch: {rel}")
            result["verified_entries"] = len(entries)
            result["missing_required"] = [name for name in REQUIRED
                                          if not (tmp_path / name).exists()]

            repro = subprocess.run(
                [sys.executable, str(tmp_path / "repro" / "verify_g1.py")],
                capture_output=True, text=True, timeout=300, cwd=str(tmp_path),
            )
            result["repro_status"] = "PASS" if repro.returncode == 0 else f"FAIL({repro.returncode})"
            result["repro_stdout_tail"] = repro.stdout.strip().splitlines()[-10:]
            log.append(f"repro exit={repro.returncode}")
            for line in result["repro_stdout_tail"]:
                log.append(f"  {line}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--status-map", type=Path,
                        default=ROOT / "docs" / "audit_g1" / "status_map.json")
    args = parser.parse_args()

    run_dir = args.run.resolve()
    run_status = json.loads((run_dir / "run_status.json").read_text(encoding="utf-8"))
    if run_status.get("gate") != "G1":
        print("ERROR: not a G1 run", file=sys.stderr)
        return 2

    audit_dir = AUDIT_ROOT / run_status["run_id"]
    if audit_dir.exists():
        print(f"ERROR: audit directory already exists: {audit_dir}", file=sys.stderr)
        return 2
    audit_dir.mkdir(parents=True)
    package = audit_dir / "package"
    log = [f"G1 audit packaging started {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
           f"gate=G1 run={run_dir}"]
    started = time.perf_counter()

    build_package(run_dir, package)
    log.append(f"package built: {sum(1 for p in package.rglob('*') if p.is_file())} files")

    missing = [name for name in REQUIRED_BEFORE_MANIFEST if not (package / name).exists()]
    if missing:
        print(f"ERROR: missing required files: {missing}", file=sys.stderr)
        return 2
    hits = scan_package(package)
    if hits:
        print("ERROR: sanitisation scan failed:", file=sys.stderr)
        for hit in hits:
            print(f"  {hit}", file=sys.stderr)
        return 2
    log.append("sanitisation scan: clean")

    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    status_map = json.loads(args.status_map.read_text(encoding="utf-8"))
    statuses = derive_statuses(metrics, status_map)
    manifest = write_manifest(package, run_dir, run_status, metrics, statuses)
    log.append(f"manifest: {len(manifest['files'])} files hashed")

    count = write_sums(package)
    log.append(f"SHA256SUMS.txt: {count} entries")
    still_missing = [name for name in REQUIRED if not (package / name).exists()]
    if still_missing:
        print(f"ERROR: required files still missing: {still_missing}", file=sys.stderr)
        return 2

    zip_path = audit_dir / f"OptiSysLab_G1_{run_status['run_id']}_GPT_AUDIT.zip"
    build_zip(package, zip_path)
    log.append(f"zip written: {zip_path.name} ({zip_path.stat().st_size} bytes)")

    verification = verify_zip(zip_path, log)
    log.append(f"integrity: testzip={verification['testzip']}, "
               f"verified={verification.get('verified_entries')}, "
               f"mismatches={verification['hash_mismatches']}, "
               f"unsafe={verification['unsafe_paths']}, "
               f"missing={verification['missing_required']}, repro={verification['repro_status']}")

    digest = sha256_file(zip_path)
    (audit_dir / "AUDIT_ZIP_SHA256.txt").write_text(
        f"{digest}  {zip_path.name}\nbytes: {zip_path.stat().st_size}\n"
        f"files: {verification['file_count']}\n"
        f"created_at: {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n",
        encoding="utf-8",
    )
    log.append(f"zip sha256: {digest}")
    log.append(f"elapsed: {time.perf_counter() - started:.2f} s")
    (audit_dir / "AUDIT_PACKAGING_LOG.txt").write_text("\n".join(log) + "\n", encoding="utf-8")

    size_ok = zip_path.stat().st_size < 40 * 1024 * 1024
    ok = (verification["testzip"] == "OK" and not verification["hash_mismatches"]
          and not verification["unsafe_paths"] and not verification["missing_required"]
          and verification["repro_status"] == "PASS" and size_ok)
    print(json.dumps({
        "zip": str(zip_path), "sha256": digest, "bytes": zip_path.stat().st_size,
        "files": verification["file_count"], "integrity": "PASS" if ok else "FAIL",
        "repro": verification["repro_status"], "result_status": manifest["result_status"],
        "under_40mb": size_ok,
    }, indent=2, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
