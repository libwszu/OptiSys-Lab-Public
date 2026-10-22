"""Validate S6-R audit ZIP coverage, clean extraction, replay, and negative controls."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
import zlib
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_RUN_ID = "20261021_024715_S6_P1"
SECRET_PATTERNS = [
    re.compile(r"\b(?:ghp_|gho_|ghu_|ghs_|ghr_|github_pat_)[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{24,}\b"),
]
TEXT_SUFFIXES = {".txt", ".md", ".json", ".csv", ".yaml", ".yml", ".py", ".toml", ".xml", ".html", ".css", ".js", ".svg"}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def safe_names(names: list[str]) -> list[str]:
    issues = []
    for name in names:
        p = PurePosixPath(name)
        if p.is_absolute() or ".." in p.parts or "\\" in name or "\x00" in name:
            issues.append(f"unsafe path: {name}")
    return issues


def expected_manifest_files(root: Path) -> dict[str, dict[str, Any]]:
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    return {item["path"]: item for item in manifest.get("files", [])}


def check_package_tree(root: Path) -> dict[str, Any]:
    issues = safe_names([p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()])
    members = {p.relative_to(root).as_posix(): p for p in root.rglob("*") if p.is_file()}
    expected = expected_manifest_files(root)
    expected_names = set(expected)
    exceptions = {"manifest.json", "SHA256SUMS.txt"}
    actual_names = set(members) - exceptions
    missing = sorted(expected_names - actual_names)
    extra = sorted(actual_names - expected_names)
    mismatches = []
    for name in sorted(expected_names & actual_names):
        path = members[name]
        item = expected[name]
        if path.stat().st_size != item["bytes"] or sha(path) != item["sha256"]:
            mismatches.append(name)
    checksums = {}
    checksum_path = root / "SHA256SUMS.txt"
    if checksum_path.is_file():
        for line in checksum_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            digest, sep, name = line.partition("  ")
            if not sep or name in checksums:
                issues.append(f"invalid/duplicate checksum line: {line}")
            checksums[name] = digest
    checksum_missing = sorted(expected_names - set(checksums))
    checksum_extra = sorted(set(checksums) - expected_names)
    checksum_mismatches = []
    for name in sorted(expected_names & set(checksums)):
        if checksums[name] != expected[name]["sha256"]:
            checksum_mismatches.append(name)
    executable = [n for n in actual_names if Path(n).suffix.lower() in {".exe", ".dll", ".msi", ".bat", ".cmd", ".ps1"}]
    local_path_hits = []
    secret_hits = []
    for name, path in members.items():
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for private in (str(ROOT), str(ROOT).replace("\\", "/"), str(Path.home()), "<USER_PROFILE>"):
            if private in text:
                local_path_hits.append(name)
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                secret_hits.append(name)
    manifest_status = "PASS" if not (missing or extra or mismatches or checksum_missing or checksum_extra or checksum_mismatches or executable or issues or local_path_hits or secret_hits) else "FAIL"
    return {
        "status": manifest_status,
        "member_count": len(members),
        "managed_file_count": len(expected_names),
        "unmanaged_members": sorted(set(members) - expected_names - exceptions),
        "missing_members": missing,
        "extra_members": extra,
        "content_hash_mismatches": mismatches,
        "checksum_file_count": len(checksums),
        "checksum_missing": checksum_missing,
        "checksum_extra": checksum_extra,
        "checksum_mismatches": checksum_mismatches,
        "unsafe_paths": issues,
        "unexpected_executables": executable,
        "personal_path_hits": sorted(set(local_path_hits)),
        "secret_pattern_hits": sorted(set(secret_hits)),
    }


def canonical_rebuild(root: Path, target: Path) -> None:
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9, strict_timestamps=True) as zf:
        for path in sorted((x for x in root.rglob("*") if x.is_file()), key=lambda p: p.relative_to(root).as_posix()):
            rel = path.relative_to(root).as_posix()
            info = zipfile.ZipInfo(rel, date_time=(2026, 10, 21, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0o100644 << 16
            info.flag_bits = 0
            zf.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def run_repro(root: Path, log_prefix: Path, timeout: int = 180) -> dict[str, Any]:
    command = [sys.executable, str(root / "repro/verify_s6r.py"), "--root", str(root)]
    proc = subprocess.run(command, cwd=root, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    log_prefix.with_suffix(".stdout.txt").write_text(proc.stdout, encoding="utf-8")
    log_prefix.with_suffix(".stderr.txt").write_text(proc.stderr, encoding="utf-8")
    try:
        result = json.loads(proc.stdout)
        domain_status = result.get("status")
    except json.JSONDecodeError:
        result, domain_status = None, None
    return {"command": command, "exit_code": proc.returncode, "status": domain_status, "stdout": proc.stdout, "stderr": proc.stderr}


def copy_tree(source: Path, target: Path) -> None:
    if target.exists():
        raise FileExistsError(target)
    shutil.copytree(source, target)


def tamper_csv(path: Path) -> None:
    rows = []
    with path.open("r", newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fields = reader.fieldnames
        rows = list(reader)
    if not fields or not rows or "captured_weight" not in fields:
        raise RuntimeError("tamper control could not find captured_weight in first S6 assembly CSV")
    rows[0]["captured_weight"] = str(float(rows[0]["captured_weight"]) + 0.0001)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("zip", type=Path)
    parser.add_argument("--output", type=Path, default=ROOT / "docs/s6r/AUDIT_VERIFY_RESULT.json")
    args = parser.parse_args()
    zip_path = args.zip.resolve()
    if not zip_path.is_file():
        raise SystemExit(f"audit ZIP does not exist: {zip_path}")
    with zipfile.ZipFile(zip_path) as zf:
        names = zf.namelist()
        duplicate_names = sorted({n for n in names if names.count(n) > 1})
        corrupt = zf.testzip()
        path_issues = safe_names(names)
        link_issues = []
        for info in zf.infolist():
            mode = (info.external_attr >> 16) & 0xFFFF
            if mode and (mode & 0o170000) == 0o120000:
                link_issues.append(info.filename)
    extract_parent = ROOT / "artifacts" / "s6r" / "verify"
    extract_parent.mkdir(parents=True, exist_ok=True)
    extraction = Path(tempfile.mkdtemp(prefix="s6r_extract_", dir=extract_parent))
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(extraction)
    content = check_package_tree(extraction)
    repro = run_repro(extraction, extract_parent / f"{extraction.name}_repro")
    release_command = [sys.executable, str(extraction / "scripts/s6r_verify_release.py"), "--root", str(extraction), "--no-write"]
    release_proc = subprocess.run(release_command, cwd=extraction, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
    try:
        release_result = json.loads(release_proc.stdout)
    except json.JSONDecodeError:
        release_result = {"status": "FAIL", "stdout": release_proc.stdout, "stderr": release_proc.stderr}

    tamper_dir = extract_parent / f"s6r_tamper_{os.urandom(6).hex()}"
    copy_tree(extraction, tamper_dir)
    tamper_target = tamper_dir / f"runs/{EXPECTED_RUN_ID}/s6_c_assemblies/p1_assembly_samples.csv"
    tamper_csv(tamper_target)
    tamper_repro = run_repro(tamper_dir, extract_parent / f"{tamper_dir.name}_repro")
    tamper_ok = tamper_repro["exit_code"] != 0

    deletion_dir = extract_parent / f"s6r_deletion_{os.urandom(6).hex()}"
    copy_tree(extraction, deletion_dir)
    deletion_target = deletion_dir / f"runs/{EXPECTED_RUN_ID}/s6_c_assemblies/assembly_parameter_registry.json"
    resolved = deletion_target.resolve()
    if not resolved.is_relative_to(deletion_dir.resolve()):
        raise RuntimeError("refusing to delete a path outside the newly created deletion test copy")
    deletion_target.unlink()
    deletion_repro = run_repro(deletion_dir, extract_parent / f"{deletion_dir.name}_repro")
    deletion_ok = deletion_repro["exit_code"] != 0

    rebuild_path = extract_parent / f"{extraction.name}_canonical_rebuild.zip"
    canonical_rebuild(extraction, rebuild_path)
    original_zip_sha = sha(zip_path)
    rebuild_sha = sha(rebuild_path)
    same_environment_rebuild = "PASS" if original_zip_sha == rebuild_sha else "BYTE_REPRO_NOT_ESTABLISHED"
    size_bytes = zip_path.stat().st_size
    zip_ok = corrupt is None and not duplicate_names and not path_issues and not link_issues
    overall = "PASS" if zip_ok and content["status"] == "PASS" and repro["exit_code"] == 0 and repro["status"] == "PASS" and release_proc.returncode == 0 and release_result.get("status") == "PASS" and tamper_ok and deletion_ok else "FAIL"
    result = {
        "schema": "optisys.s6r.audit_verification/1",
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "zip_path": str(zip_path.relative_to(ROOT)).replace("\\", "/"),
        "zip_bytes": size_bytes,
        "zip_sha256": original_zip_sha,
        "zip_testzip": "PASS" if corrupt is None else f"FAIL:{corrupt}",
        "duplicate_names": duplicate_names,
        "unsafe_paths": path_issues,
        "symlink_members": link_issues,
        "manifest_coverage": content,
        "extracted_repro": {"status": "PASS" if repro["exit_code"] == 0 and repro["status"] == "PASS" else "FAIL", "exit_code": repro["exit_code"], "result": repro["status"], "logs": str(extract_parent.relative_to(ROOT) / f"{extraction.name}_repro")},
        "release_candidate_verification": {"status": release_result.get("status"), "exit_code": release_proc.returncode, "broken_links": release_result.get("broken_links"), "false_delivery_claims": release_result.get("false_delivery_claims"), "release_manifest_hash_mismatches": release_result.get("release_manifest_hash_mismatches")},
        "tamper_and_deletion_rejection": {
            "tampered_csv_rejected": tamper_ok,
            "tamper_exit_code": tamper_repro["exit_code"],
            "tampered_file": f"runs/{EXPECTED_RUN_ID}/s6_c_assemblies/p1_assembly_samples.csv",
            "required_file_deletion_rejected": deletion_ok,
            "deletion_exit_code": deletion_repro["exit_code"],
            "deleted_file": f"runs/{EXPECTED_RUN_ID}/s6_c_assemblies/assembly_parameter_registry.json",
        },
        "same_environment_byte_rebuild": same_environment_rebuild,
        "byte_rebuild_environment": {"python": platform.python_version(), "zlib": zlib.ZLIB_VERSION},
        "canonical_rebuild_sha256": rebuild_sha,
        "recommended_size_under_40_mib": size_bytes < 40 * 1024 * 1024,
        "temporary_validation_paths": {"extracted": str(extraction.relative_to(ROOT)).replace("\\", "/"), "tamper_copy": str(tamper_dir.relative_to(ROOT)).replace("\\", "/"), "deletion_copy": str(deletion_dir.relative_to(ROOT)).replace("\\", "/")},
        "status": overall,
    }
    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
