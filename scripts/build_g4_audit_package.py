"""Build a compact, deterministic, self-contained G4 GPT audit ZIP.

ZIP members use ZIP_STORED intentionally: fixed metadata and the standard
library writer avoid DEFLATE-version differences across Python/zlib builds.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 40 * 1024 * 1024
RUN_REQUIRED = (
    "config_snapshot.yaml", "environment.json", "provenance.json", "run_status.json",
    "compute_plan.json", "compute_measured.json", "source_distribution.json",
    "source_distribution_summary.csv", "source_samples.csv", "source_samples.npz",
    "repro_inputs.json", "optics_model.json", "optical_crosscheck.json",
    "raytrace_reference.csv", "ray_balance.csv", "target_plane_metrics.csv",
    "target_plane_density.npz", "oat.csv", "tolerance_samples.csv",
    "design_comparison.csv", "ray_count_convergence.csv",
    "ray_count_convergence_summary.json", "split_manifest.json", "bootstrap_summary.json",
    "bootstrap_replicates.csv",
    "metrics.json", "report.html", "report.md", "run.log",
)
SECRET_PATTERNS = (
    re.compile(rb"(?i)\bsk-[A-Za-z0-9_-]{24,}\b"),
    re.compile(rb"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),
    re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(rb"-----BEGIN [A-Z ]+PRIVATE KEY-----"),
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_arcname(name: str) -> bool:
    path = Path(name)
    return (name and not name.startswith("/") and "\\" not in name
            and not path.is_absolute() and ".." not in path.parts
            and not (len(name) >= 2 and name[1] == ":"))


def _read(path: Path) -> bytes:
    return path.read_bytes()


def _collect_tree(root: Path, rel: str, *, prefix: str | None = None) -> dict[str, bytes]:
    base = root / rel
    out: dict[str, bytes] = {}
    if not base.exists():
        return out
    if base.is_file():
        out[(prefix or rel).replace("\\", "/")] = _read(base)
        return out
    target = prefix if prefix is not None else rel
    for path in sorted(base.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        if "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo"):
            continue
        arc = (Path(target) / path.relative_to(base)).as_posix()
        out[arc] = _read(path)
    return out


def _add_path(files: dict[str, bytes], rel: str, *, arc: str | None = None) -> None:
    path = ROOT / rel
    if not path.is_file():
        raise FileNotFoundError(path)
    files[(arc or rel).replace("\\", "/")] = _read(path)


def collect_members(run_dir: Path) -> dict[str, bytes]:
    run_dir = run_dir.resolve()
    try:
        run_dir.relative_to((ROOT / "runs").resolve())
    except ValueError as exc:
        raise ValueError("formal G4 audit run must be directly under runs/ or a descendant") from exc
    if not (run_dir / "run_status.json").is_file():
        raise FileNotFoundError(f"run_status.json missing: {run_dir}")
    status = json.loads((run_dir / "run_status.json").read_text(encoding="utf-8"))
    if status.get("gate") != "G4":
        raise ValueError("selected run is not Gate G4")
    missing = [name for name in RUN_REQUIRED if not (run_dir / name).is_file()]
    if missing:
        raise ValueError(f"required run evidence missing: {missing}")

    files: dict[str, bytes] = {}
    for req in (
        "00_START_HERE.md", "01_EXECUTIVE_SUMMARY.md", "02_SPEC_TRACEABILITY.md",
        "03_SCIENTIFIC_AUDIT.md", "04_VALIDATION_MATRIX.md",
        "05_COMPUTE_AND_PERFORMANCE.md", "06_REPRODUCTION_GUIDE.md",
        "07_KNOWN_ISSUES_AND_FAILURES.md", "08_NEXT_STEPS.md",
        "GPT_REVIEW_INSTRUCTIONS.md",
    ):
        _add_path(files, f"docs/g4/audit/{req}", arc=req)

    files.update(_collect_tree(ROOT, "src/optisys", prefix="src/optisys"))
    files.update(_collect_tree(ROOT, "app", prefix="app"))
    files.update(_collect_tree(ROOT, "tests", prefix="tests"))
    files.update(_collect_tree(ROOT, "configs", prefix="configs"))
    files.update(_collect_tree(ROOT, "docs/g4", prefix="g4"))
    files.update(_collect_tree(ROOT, "repro", prefix="repro"))
    files.update(_collect_tree(ROOT, "baseline"))
    for rel, arc in (
        ("README.md", "README.md"), ("LICENSE", "LICENSE"),
        ("pyproject.toml", "pyproject.toml"),
        ("requirements.lock.txt", "requirements.lock.txt"),
        (".github/workflows/ci.yml", ".github/workflows/ci.yml"),
        ("OptiSys_Lab_Job_Oriented_Development_Plan_2026.pdf",
         "source/OptiSys_Lab_Job_Oriented_Development_Plan_2026.pdf"),
        ("1md/OptiSysLab_G4_976nm_Pump_Portfolio_Audit_Master_Prompt.md",
         "source/OptiSysLab_G4_976nm_Pump_Portfolio_Audit_Master_Prompt.md"),
        ("scripts/build_g4_audit_package.py", "scripts/build_g4_audit_package.py"),
        ("scripts/verify_g4_audit_package.py", "scripts/verify_g4_audit_package.py"),
        ("scripts/verify_g4_baselines.py", "scripts/verify_g4_baselines.py"),
        ("scripts/g4_pre_profile.py", "scripts/g4_pre_profile.py"),
        ("scripts/make_basetemp.py", "scripts/make_basetemp.py"),
        ("scripts/smoke_streamlit_serve.py", "scripts/smoke_streamlit_serve.py"),
    ):
        _add_path(files, rel, arc=arc)

    run_files = {}
    for path in sorted(p for p in run_dir.rglob("*") if p.is_file()):
        if "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo"):
            continue
        run_files[(Path("run") / path.relative_to(run_dir)).as_posix()] = _read(path)
    files.update(run_files)

    # Include the G3 frozen science handoff, the prior audit ZIP hash, and the
    # complete G3 756-row CSV that was present locally but omitted from G3 ZIP.
    g3_required = (
        "G3_FINAL_STATUS.json", "G3_VALIDATION_MATRIX.md", "G3_COMPUTE_MEASURED.md",
        "G2_INHERITANCE_VERDICT.json", "G2_INHERITANCE_SCIENTIFIC_AUDIT.md",
        "G3_OPEN_ISSUES.md", "DEMO_SCRIPT_5MIN.md", "G3_BASELINE_HASHES.json",
        "G3_BASELINE_VERIFICATION.md",
    )
    for name in g3_required:
        _add_path(files, f"docs/g3/{name}", arc=f"baseline_g3/{name}")
    g3_zip_dir = ROOT / "_AUDIT/20261020_071457_G3_ea57a83b"
    _add_path(files, "_AUDIT/20261020_071457_G3_ea57a83b/AUDIT_ZIP_SHA256.txt",
              arc="baseline_g3/G3_AUDIT_ZIP_SHA256.txt")
    g3_csv = ROOT / "runs/20261020_071457_G3_ea57a83b/independent_validation/sampled_results.csv"
    _add_path(files, "runs/20261020_071457_G3_ea57a83b/independent_validation/sampled_results.csv",
              arc="baseline_g3/G3_756_sampled_results.csv")

    # Preserve primary pre-check and full-test evidence, without including temp
    # directories or stale scratch files.
    evidence_files = [
        "artifacts/g4/pre/environment.json", "artifacts/g4/pre/commands.json",
        "artifacts/g4/pre/platform_extensions.stdout.txt",
        "artifacts/g4/pre/platform_extensions.stderr.txt",
        "artifacts/g4/pre/pre_g4_interfaces.junit.xml",
        "artifacts/g4/pre/optiland_g4_crosscheck_coordinatefix.json",
        "artifacts/g4/pre/compute_profile.json",
        "artifacts/g4/tests/pump976_unit.junit.xml",
        "artifacts/g4/tests/pump976_unit.stdout.txt",
        "artifacts/g4/tests/g4_integration_v2.junit.xml",
        "artifacts/g4/tests/g4_integration_v2.stdout.txt",
        "artifacts/g4/tests/g4_ui_smoke.junit.xml",
        "artifacts/g4/tests/g4_ui_smoke.stdout.txt",
        "artifacts/g4/tests/g4_ui_full.junit.xml",
        "artifacts/g4/tests/g4_ui_full.stdout.txt",
        "artifacts/g4/tests/g4_full_junit.xml",
        "artifacts/g4/tests/g4_full_stdout.txt",
        "artifacts/g4/tests/g4_full_stderr.txt",
        "artifacts/g4/tests/g4_full_exit.json",
        "artifacts/g4/tests/g4_formal_cli.json",
        "artifacts/g4/tests/g4_formal_cli.stdout.txt",
        "artifacts/g4/tests/g4_formal_cli.stderr.txt",
        "artifacts/g4/tests/g4_report_cli.json",
        "artifacts/g4/tests/g4_report_cli.stdout.txt",
        "artifacts/g4/tests/g4_report_cli.stderr.txt",
        "artifacts/g4/tests/pump976_cli.json",
        "artifacts/g4/tests/pump976_cli.stdout.txt",
        "artifacts/g4/tests/pump976_cli.stderr.txt",
        "artifacts/g4/tests/g3_cli_smoke.json",
        "artifacts/g4/tests/g3_cli_smoke.stdout.txt",
        "artifacts/g4/tests/g3_cli_smoke.stderr.txt",
        "artifacts/g4/tests/streamlit_serve.json",
        "artifacts/g4/tests/streamlit_serve.stdout.txt",
        "artifacts/g4/tests/streamlit_serve.stderr.txt",
    ]
    for rel in evidence_files:
        path = ROOT / rel
        if path.is_file():
            _add_path(files, rel, arc=f"test_evidence/{Path(rel).name}")
    for rel in ("artifacts/g3/tests/g3_full_junit.xml", "artifacts/g3/tests/g3_full_stdout.txt",
                "artifacts/g3/tests/g3_release_verify.json", "artifacts/g3/tests/streamlit_serve.json"):
        if (ROOT / rel).is_file():
            _add_path(files, rel, arc=f"test_evidence/baseline_g3/{Path(rel).name}")

    files["g4/run_id.txt"] = (run_dir.name + "\n").encode("utf-8")
    if len(files) != len(set(files)):
        raise ValueError("duplicate archive path")
    unsafe = [name for name in files if not _safe_arcname(name)]
    if unsafe:
        raise ValueError(f"unsafe archive paths: {unsafe[:5]}")
    return dict(sorted(files.items()))


def secret_scan(files: dict[str, bytes]) -> list[str]:
    hits = []
    for name, data in files.items():
        for pattern in SECRET_PATTERNS:
            if pattern.search(data):
                hits.append(name)
                break
    return hits


def build_archive(files: dict[str, bytes], destination: Path, run_id: str) -> dict[str, Any]:
    ordinary = [{"path": name, "bytes": len(data), "sha256": sha256(data)}
                for name, data in files.items()]
    manifest = {
        "schema": "g4.audit_manifest/1", "gate": "G4", "run_id": run_id,
        "created_at_utc": json.loads(files["run/run_status.json"].decode("utf-8")).get("finished_at_utc"),
        "compression": "ZIP_STORED", "file_count": len(ordinary),
        "total_bytes": sum(row["bytes"] for row in ordinary),
        "self_reference_exceptions": ["manifest.json", "SHA256SUMS.txt"],
        "files": ordinary,
    }
    manifest_bytes = (json.dumps(manifest, ensure_ascii=False, sort_keys=True,
                                 separators=(",", ":")) + "\n").encode("utf-8")
    sums_rows = [f"{row['sha256']}  {row['path']}" for row in ordinary]
    sums_rows.append(f"{sha256(manifest_bytes)}  manifest.json")
    sums_bytes = ("\n".join(sorted(sums_rows)) + "\n").encode("utf-8")
    members = dict(files)
    members["manifest.json"] = manifest_bytes
    members["SHA256SUMS.txt"] = sums_bytes
    total_size = sum(len(data) for data in members.values())
    if total_size > MAX_BYTES:
        raise ValueError(f"uncompressed audit content exceeds 40 MiB: {total_size} bytes")
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_STORED) as archive:
        for name, data in sorted(members.items()):
            info = zipfile.ZipInfo(filename=name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o600 << 16
            info.create_system = 0
            info.flag_bits = 0
            archive.writestr(info, data)
    return {"zip_bytes": destination.stat().st_size,
            "zip_sha256": sha256(destination.read_bytes()),
            "member_count": len(members), "manifest_covered_count": len(ordinary),
            "self_reference_exceptions": 2, "content_bytes": total_size,
            "compression": "ZIP_STORED"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--audit-dir", type=Path)
    parser.add_argument("--replace-archive", action="store_true",
                        help="replace an existing archive in the same G4 audit directory")
    args = parser.parse_args()
    run_dir = args.run if args.run.is_absolute() else ROOT / args.run
    run_dir = run_dir.resolve()
    run_id = run_dir.name
    audit_dir = args.audit_dir or (ROOT / "_AUDIT" / run_id)
    if not audit_dir.is_absolute():
        audit_dir = ROOT / audit_dir
    audit_dir.mkdir(parents=True, exist_ok=True)
    dest = audit_dir / f"OptiSysLab_G4_{run_id}_GPT_AUDIT.zip"
    if dest.exists() and not args.replace_archive:
        raise SystemExit(f"Refusing to replace existing audit ZIP: {dest}")
    files = collect_members(run_dir)
    secret_hits = secret_scan(files)
    if secret_hits:
        raise SystemExit(f"secret scan found candidate patterns in: {secret_hits}")
    temp_zip = audit_dir / f".{dest.name}.tmp"
    summary = build_archive(files, temp_zip, run_id)
    temp_zip.replace(dest)
    hash_text = (f"gate: G4\nrun_id: {run_id}\nbytes: {dest.stat().st_size}\n"
                 f"sha256: {summary['zip_sha256']}\nzip: {dest.name}\n")
    (audit_dir / "AUDIT_ZIP_SHA256.txt").write_text(hash_text, encoding="utf-8")
    build_log = audit_dir / "AUDIT_BUILD_LOG.txt"
    build_log.write_text(
        f"built_at_utc: {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n"
        f"run_dir: {run_dir}\nzip: {dest}\n"
        f"source_files: {len(files)}\nmember_count: {summary['member_count']}\n"
        f"manifest_covered_count: {summary['manifest_covered_count']}\n"
        f"self_reference_exceptions: {summary['self_reference_exceptions']}\n"
        f"compression: {summary['compression']}\ncontent_bytes: {summary['content_bytes']}\n"
        f"zip_bytes: {summary['zip_bytes']}\nzip_sha256: {summary['zip_sha256']}\n"
        f"secret_scan: PASS (patterns_checked={len(SECRET_PATTERNS)})\n",
        encoding="utf-8")
    print(json.dumps({**summary, "zip": str(dest), "audit_dir": str(audit_dir)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
