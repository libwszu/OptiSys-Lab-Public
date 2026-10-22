"""Build and verify the frozen GPT audit ZIP for a gate.

The script is intentionally explicit about every step required by the master
prompt section 7:

1. build a clean ``package/`` tree (no ``.venv``, no ``__pycache__``, no
   ``_AUDIT`` self-inclusion);
2. scan for credentials and personal paths;
3. write ``manifest.json`` (no self-hash) and ``SHA256SUMS.txt``;
4. compress with ``zipfile`` and run ``testzip()``;
5. extract into an independent temporary directory and verify every hash;
6. run the minimal repro script from the extracted copy;
7. write the ZIP hash outside the package.

Usage:
    python scripts/build_audit_package.py --gate G0 --run runs/<run_id>
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
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
AUDIT_ROOT = ROOT / "_AUDIT"

#: Files that must exist in every audit package (master prompt 7.2).
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
    "source_spec/OptiSys_Lab_Job_Oriented_Development_Plan_2026.pdf",
    "source_spec/source_pdf_sha256.txt",
    "README.md",
    "pyproject.toml",
    "requirements.lock.txt",
    "run_evidence/config_snapshot.yaml",
    "run_evidence/environment.json",
    "run_evidence/compute_plan.json",
    "run_evidence/benchmark.json",
    "run_evidence/metrics.json",
    "run_evidence/provenance.json",
    "run_evidence/run_status.json",
    "run_evidence/tests_summary.json",
    "run_evidence/tests_stdout.txt",
    "run_evidence/main_run_log_excerpt.txt",
]

REQUIRED_BEFORE_MANIFEST = [
    name for name in REQUIRED if name not in {"manifest.json", "SHA256SUMS.txt"}
]

REQUIRED_BEFORE_MANIFEST = [
    name for name in REQUIRED if name not in {"manifest.json", "SHA256SUMS.txt"}
]

FORBIDDEN_PATTERNS = [
    (re.compile(r"C:[\\/]+Users[\\/]+", re.I), "absolute Windows user path"),
    (re.compile(r"/home/[a-z0-9_]+", re.I), "absolute Linux home path"),
    (re.compile(r"\bsk-[A-Za-z0-9]{16,}\b"), "OpenAI-style secret"),
    (re.compile(r"\bghp_[A-Za-z0-9]{20,}\b"), "GitHub token"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS access key"),
    (re.compile(r"(?i)(api[_-]?key|secret|password)\s*[:=]\s*['\"][^'\"]{8,}"),
     "inline credential assignment"),
]
TEXT_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml", ".py", ".toml", ".csv", ".cfg", ".ini"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def copy_file(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def copy_tree(src: Path, dst: Path, exclude: Iterable[str] = ("__pycache__",)) -> None:
    for path in sorted(src.rglob("*")):
        if not path.is_file():
            continue
        if any(part in path.parts for part in exclude):
            continue
        if path.suffix in {".pyc", ".pyo"}:
            continue
        copy_file(path, dst / path.relative_to(src))


def scan_package(package: Path) -> list[str]:
    hits: list[str] = []
    for path in sorted(package.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            for pattern, label in FORBIDDEN_PATTERNS:
                if pattern.search(line):
                    hits.append(f"{path.relative_to(package)}:{line_number}: {label}")
    return hits


def build_package(gate: str, run_dir: Path, package: Path) -> None:
    if package.exists():
        shutil.rmtree(package)
    package.mkdir(parents=True)

    # Source code, configs, tests, scripts, repro, docs.
    copy_tree(ROOT / "src", package / "src")
    copy_tree(ROOT / "configs", package / "configs")
    copy_tree(ROOT / "tests", package / "tests")
    copy_tree(ROOT / "scripts", package / "scripts")
    copy_tree(ROOT / "repro", package / "repro")
    copy_tree(ROOT / "docs", package / "docs")

    # Top-level project files.
    for name in ("README.md", "pyproject.toml", "LICENSE", "requirements.lock.txt"):
        if (ROOT / name).is_file():
            copy_file(ROOT / name, package / name)

    # Audit-facing documents.
    audit_docs = ROOT / "docs" / "audit"
    for name in (
        "00_START_HERE.md", "01_EXECUTIVE_SUMMARY.md", "03_SCIENTIFIC_AUDIT.md",
        "05_COMPUTE_AND_PERFORMANCE.md", "06_REPRODUCTION_GUIDE.md",
        "07_KNOWN_ISSUES_AND_FAILURES.md", "08_NEXT_GATE_PLAN.md",
        "GPT_REVIEW_INSTRUCTIONS.md",
    ):
        copy_file(audit_docs / name, package / name)
    copy_file(ROOT / "docs" / "SPEC_TRACEABILITY.md", package / "02_SPEC_TRACEABILITY.md")
    copy_file(ROOT / "docs" / "VALIDATION_MATRIX.md", package / "04_VALIDATION_MATRIX.md")

    # Source specification.
    pdf = ROOT / "OptiSys_Lab_Job_Oriented_Development_Plan_2026.pdf"
    copy_file(pdf, package / "source_spec" / pdf.name)
    (package / "source_spec" / "source_pdf_sha256.txt").write_text(
        f"{sha256_file(pdf)}  {pdf.name}\n"
        f"# bytes: {pdf.stat().st_size}\n"
        f"# verified against the hash stated in the master prompt on {datetime.now(timezone.utc):%Y-%m-%d}\n",
        encoding="utf-8",
    )

    # Run evidence.
    evidence = package / "run_evidence"
    evidence.mkdir()
    for name in (
        "config_snapshot.yaml", "environment.json", "compute_plan.json", "benchmark.json",
        "metrics.json", "provenance.json", "run_status.json", "report.html",
    ):
        copy_file(run_dir / name, evidence / name)
    for src_name, dst_name in (
        ("tests_summary.json", "tests_summary.json"),
        ("tests_stdout.txt", "tests_stdout.txt"),
        ("run.log", "main_run_log_excerpt.txt"),
    ):
        source = run_dir / src_name
        if source.is_file():
            copy_file(source, evidence / dst_name)

    samples_dir = evidence / "samples"
    samples_dir.mkdir()
    copy_file(run_dir / "samples.csv", samples_dir / "samples.csv")
    copy_file(run_dir / "boundary_cases.csv", samples_dir / "boundary_cases.csv")
    copy_file(run_dir / "formula_comparison.csv", samples_dir / "formula_comparison.csv")

    figures_dir = evidence / "figures"
    figures_dir.mkdir()
    for path in sorted((run_dir / "figures").iterdir()):
        if path.is_file():
            copy_file(path, figures_dir / path.name)

    comparison_dir = evidence / "comparison"
    comparison_dir.mkdir()
    copy_file(run_dir / "samples.csv", comparison_dir / "analytic_vs_reference.csv")
    copy_file(run_dir / "formula_comparison.csv", comparison_dir / "formula_vs_pdf.csv")


def write_manifest(package: Path, run_dir: Path, gate: str, status_map: dict[str, Any],
                   critical_failures: list[str]) -> dict[str, Any]:
    provenance = json.loads((run_dir / "provenance.json").read_text(encoding="utf-8"))
    run_status = json.loads((run_dir / "run_status.json").read_text(encoding="utf-8"))
    tests = json.loads((package / "run_evidence" / "tests_summary.json").read_text(encoding="utf-8"))
    pdf_hash = (package / "source_spec" / "source_pdf_sha256.txt").read_text(encoding="utf-8").split()[0]

    files = []
    for path in sorted(package.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(package).as_posix()
        if rel in {"manifest.json", "SHA256SUMS.txt"}:
            continue
        files.append({"path": rel, "bytes": path.stat().st_size, "sha256": sha256_file(path)})

    manifest = {
        "audit_schema_version": "1.0",
        "project": "OptiSys-Lab",
        "gate": gate,
        "run_id": run_status["run_id"],
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "result_status": run_status["status"],
        "scientific_claim_status": run_status["scientific_claim_status"],
        "scientific_claim_scope": run_status.get("scientific_claim_scope", ""),
        "source_pdf_sha256": pdf_hash,
        "git_commit": provenance["code"]["git_commit"],
        "source_tree_sha256": provenance["code"]["source_tree_sha256"],
        "source_tree_scope": provenance["code"]["source_tree_scope"],
        "model_level": provenance["code"]["model_level"],
        "random_seeds": provenance["random_seeds"],
        "requirements": status_map["requirements"],
        "validation": status_map["validation"],
        "tests": {
            "passed": tests["totals"]["passed"],
            "failed": tests["totals"]["failed"],
            "skipped": tests["totals"]["skipped"],
            "not_run": tests.get("not_run", []),
        },
        "hardware_backend": "CPU",
        "critical_failures": critical_failures,
        "files": files,
    }
    (package / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return manifest


def write_sums(package: Path) -> int:
    lines = []
    for path in sorted(package.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(package).as_posix()
        if rel == "SHA256SUMS.txt":
            continue
        lines.append(f"{sha256_file(path)}  {rel}")
    (package / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


def build_zip(package: Path, zip_path: Path) -> None:
    if zip_path.exists():
        raise FileExistsError(f"refusing to overwrite existing audit zip: {zip_path}")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(package.rglob("*")):
            if path.is_file():
                archive.write(path, arcname=path.relative_to(package).as_posix())


def verify_zip(zip_path: Path, log: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {"testzip": None, "hash_mismatches": [], "unsafe_paths": [],
                              "file_count": 0, "repro_status": "NOT_REPLAYED"}
    with zipfile.ZipFile(zip_path) as archive:
        bad = archive.testzip()
        result["testzip"] = "OK" if bad is None else f"CORRUPT: {bad}"
        names = archive.namelist()
        result["file_count"] = len(names)
        for name in names:
            if name.startswith("/") or ".." in Path(name).parts or ":" in name.split("/")[0]:
                result["unsafe_paths"].append(name)

        with tempfile.TemporaryDirectory(prefix="optisys_audit_") as tmp:
            tmp_path = Path(tmp)
            archive.extractall(tmp_path)
            sums_file = tmp_path / "SHA256SUMS.txt"
            entries = []
            for line in sums_file.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                digest, rel = line.split("  ", 1)
                entries.append((digest, rel))
            for digest, rel in entries:
                target = tmp_path / rel
                if not target.is_file():
                    result["hash_mismatches"].append(f"missing: {rel}")
                elif sha256_file(target) != digest:
                    result["hash_mismatches"].append(f"hash mismatch: {rel}")
            result["verified_entries"] = len(entries)

            missing = [name for name in REQUIRED if not (tmp_path / name).exists()]
            result["missing_required"] = missing

            repro = subprocess.run(
                [sys.executable, str(tmp_path / "repro" / "verify_g0.py")],
                capture_output=True, text=True, timeout=180, cwd=str(tmp_path),
            )
            result["repro_status"] = "PASS" if repro.returncode == 0 else f"FAIL({repro.returncode})"
            result["repro_stdout_tail"] = repro.stdout.strip().splitlines()[-6:]
            log.append(f"repro exit={repro.returncode}")
            for line in result["repro_stdout_tail"]:
                log.append(f"  {line}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate", default="G0")
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--status-map", type=Path,
                        default=ROOT / "docs" / "audit" / "status_map.json")
    parser.add_argument("--critical-failures", default="")
    args = parser.parse_args()

    run_dir = args.run.resolve()
    if not (run_dir / "run_status.json").is_file():
        print(f"ERROR: not a finished run directory: {run_dir}", file=sys.stderr)
        return 2

    run_status = json.loads((run_dir / "run_status.json").read_text(encoding="utf-8"))
    audit_dir = AUDIT_ROOT / run_status["run_id"]
    if audit_dir.exists():
        print(f"ERROR: audit directory already exists: {audit_dir}", file=sys.stderr)
        return 2
    audit_dir.mkdir(parents=True)
    package = audit_dir / "package"

    log: list[str] = [
        f"audit packaging started {datetime.now(timezone.utc).isoformat(timespec='seconds')}",
        f"gate={args.gate} run={run_dir}",
    ]
    started = time.perf_counter()

    build_package(args.gate, run_dir, package)
    log.append(f"package built: {sum(1 for _ in package.rglob('*') if _.is_file())} files")

    missing = [name for name in REQUIRED_BEFORE_MANIFEST if not (package / name).exists()]
    if missing:
        print(f"ERROR: missing required audit files: {missing}", file=sys.stderr)
        return 2

    hits = scan_package(package)
    if hits:
        print("ERROR: sanitisation scan failed:", file=sys.stderr)
        for hit in hits:
            print(f"  {hit}", file=sys.stderr)
        return 2
    log.append("sanitisation scan: clean")

    status_map = json.loads(args.status_map.read_text(encoding="utf-8"))
    critical = [item.strip() for item in args.critical_failures.split("|") if item.strip()]
    manifest = write_manifest(package, run_dir, args.gate, status_map, critical)
    log.append(f"manifest: {len(manifest['files'])} files hashed")

    count = write_sums(package)
    log.append(f"SHA256SUMS.txt: {count} entries")

    still_missing = [name for name in REQUIRED if not (package / name).exists()]
    if still_missing:
        print(f"ERROR: required files still missing: {still_missing}", file=sys.stderr)
        return 2

    zip_path = audit_dir / f"OptiSysLab_{args.gate}_{run_status['run_id']}_GPT_AUDIT.zip"
    build_zip(package, zip_path)
    log.append(f"zip written: {zip_path.name} ({zip_path.stat().st_size} bytes)")

    verification = verify_zip(zip_path, log)
    log.append(f"integrity: testzip={verification['testzip']}, "
               f"verified={verification.get('verified_entries')}, "
               f"mismatches={verification['hash_mismatches']}, "
               f"unsafe={verification['unsafe_paths']}, "
               f"missing={verification['missing_required']}, "
               f"repro={verification['repro_status']}")

    digest = sha256_file(zip_path)
    (audit_dir / "AUDIT_ZIP_SHA256.txt").write_text(
        f"{digest}  {zip_path.name}\n"
        f"bytes: {zip_path.stat().st_size}\n"
        f"files: {verification['file_count']}\n"
        f"created_at: {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n",
        encoding="utf-8",
    )
    log.append(f"zip sha256: {digest}")
    log.append(f"elapsed: {time.perf_counter() - started:.2f} s")
    (audit_dir / "AUDIT_PACKAGING_LOG.txt").write_text("\n".join(log) + "\n", encoding="utf-8")

    ok = (
        verification["testzip"] == "OK"
        and not verification["hash_mismatches"]
        and not verification["unsafe_paths"]
        and not verification["missing_required"]
        and verification["repro_status"] == "PASS"
    )
    print(json.dumps({
        "zip": str(zip_path),
        "sha256": digest,
        "bytes": zip_path.stat().st_size,
        "files": verification["file_count"],
        "integrity": "PASS" if ok else "FAIL",
        "repro": verification["repro_status"],
        "result_status": manifest["result_status"],
    }, indent=2, ensure_ascii=False))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
