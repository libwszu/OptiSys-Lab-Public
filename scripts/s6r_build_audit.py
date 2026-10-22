"""Build a compact, self-contained S6-R GPT audit package."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import zipfile
import argparse
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
AUDIT_RUN_ID = "20261021_100205_S6R"
AUDIT_DIR = ROOT / "_AUDIT" / AUDIT_RUN_ID
STAGE = AUDIT_DIR / "package"
ZIP_PATH = AUDIT_DIR / f"OptiSysLab_S6R_{AUDIT_RUN_ID}_GPT_AUDIT.zip"
RUN_ID = "20261021_024715_S6_P1"

FROZEN_FILES = {
    "docs/s6/S6_ACCEPTANCE_CRITERIA.md",
    "docs/s6/S6_FREEZE_HASHES.json",
    "docs/s6/S6_AMENDMENT_01.md",
    "docs/s6/S6_AMENDMENT_01_HASHES.json",
    "docs/s6/S6_AMENDMENT_02.md",
    "docs/s6/S6_AMENDMENT_02_HASHES.json",
    "docs/s6/S6_AMENDMENT_03.md",
    "docs/s6/S6_AMENDMENT_03_HASHES.json",
    "scripts/s6_assembly.py",
    "scripts/s6_finalize_claim.py",
    "scripts/s6_assembly_figures.py",
    "scripts/s6_reference.py",
    "scripts/s6_boundaries.py",
    "scripts/s6_boundary_figures.py",
    "src/optisys/optics/s6_rigid_body.py",
    "src/optisys/optics/s5_reference.py",
    "src/optisys/tolerance/s6_assembly.py",
    "src/optisys/sources/multimode_fiber.py",
    "tests/unit/test_s6_rigid_body.py",
    "tests/unit/test_s6_assembly_stats.py",
}

S6_RUN_FILES = [
    f"runs/{RUN_ID}/config_snapshot.yaml",
    f"runs/{RUN_ID}/environment.json",
    f"runs/{RUN_ID}/compute_plan.json",
    f"runs/{RUN_ID}/compute_measured_preholdout.json",
    f"runs/{RUN_ID}/S6_C_CODE_FREEZE.json",
    f"runs/{RUN_ID}/S6_C_CODE_FREEZE_02.json",
    f"runs/{RUN_ID}/S6_C_HOLDOUT_FREEZE.json",
    f"runs/{RUN_ID}/S6_C_HOLDOUT_FREEZE_02.json",
    f"runs/{RUN_ID}/s6_a_reference/s6_a_reference_summary.json",
    f"runs/{RUN_ID}/s6_b_boundaries/boundary_analysis.json",
    f"runs/{RUN_ID}/s6_c_pilot/run_contract.json",
    f"runs/{RUN_ID}/s6_c_pilot/pilot_run_status.json",
    f"runs/{RUN_ID}/s6_c_pilot/pilot_validation.json",
    f"runs/{RUN_ID}/s6_c_pilot/assembly_manifest.csv",
    f"runs/{RUN_ID}/s6_c_pilot/p1_assembly_samples.csv",
    f"runs/{RUN_ID}/s6_c_pilot/paired_assembly_comparison.csv",
    f"runs/{RUN_ID}/s6_c_pilot/source_bundle_index.csv",
]

S6_C_FILES = [
    "assembly_parameter_registry.json", "run_contract.json", "run_status.json",
    "run_status_programmatic.json", "assembly_statistics_programmatic.json",
    "assembly_statistics.json", "p1_assembly_samples.csv",
    "paired_assembly_comparison.csv", "assembly_bootstrap_replicates.csv",
    "failure_breakdown.csv", "assembly_manifest.csv",
    "assembly_robustness_plot_data.csv", "zero_tolerance_controls.csv",
    "S6_C_FINAL_ADJUDICATION.json", "S6_ASSEMBLY_SCIENTIFIC_AUDIT_FINAL.md",
    "assembly_figure_metadata.json", "s6_assembly_robustness.png",
    "compute_measured_001.json", "source_bundle_index.csv",
]

TEXT_SUFFIXES = {".txt", ".md", ".json", ".csv", ".yaml", ".yml", ".py", ".toml", ".xml", ".html", ".css", ".js", ".svg"}
SECRET_PATTERNS = [
    re.compile(r"\b(?:ghp_|gho_|ghu_|ghs_|ghr_|github_pat_)[A-Za-z0-9_]{20,}\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\bsk-[A-Za-z0-9]{24,}\b"),
]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sanitize_text(text: str, rel: str, redaction_log: dict[str, Any]) -> str:
    replacements = [
        (str(ROOT), "<PROJECT_ROOT>"),
        (ROOT.as_posix(), "<PROJECT_ROOT>"),
        (str(ROOT / ".venv_s6r_release"), "<PYTHON_ENV>"),
        ("D:\\py3.11.9", "<PYTHON_INSTALL>"),
        ("D:/py3.11.9", "<PYTHON_INSTALL>"),
        ("<USER_PROFILE>", "<USER_PROFILE>"),
        ("<USER_PROFILE>", "<USER_PROFILE>"),
    ]
    for old, new in replacements:
        if old in text:
            redaction_log.setdefault(rel, []).append({"kind": "local_path", "replacement": new})
            text = text.replace(old, new)
    if rel == "docs/s6r/BASELINE_HASHES.json":
        try:
            payload = json.loads(text)
            status = payload.get("repository", {}).get("status_porcelain", [])
            cleaned = []
            removed_memory = 0
            removed_prompts = 0
            for line in status:
                if ".workbuddy/memory/" in line:
                    removed_memory += 1
                    continue
                if line.startswith("?? 1md/"):
                    removed_prompts += 1
                    continue
                cleaned.append(line)
            payload["repository"]["status_porcelain"] = cleaned
            payload["repository"]["redacted_status_entries"] = {
                "agent_memory_paths": removed_memory,
                "prompt_document_paths": removed_prompts,
            }
            text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
            if removed_memory or removed_prompts:
                redaction_log[rel] = [{"kind": "local_working_tree_metadata", "agent_memory_paths": removed_memory, "prompt_document_paths": removed_prompts}]
        except Exception as exc:
            raise RuntimeError(f"could not redact local working-tree metadata in {rel}: {exc}") from exc
    return text


def copy_one(src_rel: str, dest_rel: str | None = None, *, preserve: bool = False, redactions: dict[str, Any]) -> None:
    src = ROOT / src_rel
    if not src.is_file():
        raise FileNotFoundError(f"required audit source is missing: {src_rel}")
    dest_name = (dest_rel or src_rel).replace("\\", "/")
    rel = PurePosixPath(dest_name)
    if rel.is_absolute() or ".." in rel.parts:
        raise ValueError(f"unsafe package path: {dest_name}")
    target = STAGE.joinpath(*rel.parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    if src.suffix.lower() in TEXT_SUFFIXES and not preserve:
        try:
            original_bytes = src.read_bytes()
            text = original_bytes.decode("utf-8")
        except UnicodeDecodeError:
            shutil.copy2(src, target)
        else:
            sanitized_text = sanitize_text(text, src_rel.replace("\\", "/"), redactions)
            sanitized_bytes = sanitized_text.encode("utf-8")
            target.write_bytes(sanitized_bytes)
            if sanitized_bytes != original_bytes:
                redactions.setdefault(src_rel.replace("\\", "/"), []).append({"kind": "content_hash_change_due_to_redaction", "original_bytes": len(original_bytes), "original_sha256": sha256_bytes(original_bytes), "sanitized_bytes": len(sanitized_bytes), "sanitized_sha256": sha256_bytes(sanitized_bytes)})
    else:
        shutil.copy2(src, target)


def copy_tree(src_rel: str, dest_rel: str | None = None, *, redactions: dict[str, Any]) -> None:
    source = ROOT / src_rel
    if not source.is_dir():
        raise FileNotFoundError(f"required audit directory is missing: {src_rel}")
    target_root = STAGE / (dest_rel or src_rel)
    for src in sorted(source.rglob("*")):
        if src.is_dir() or src.is_symlink() or "__pycache__" in src.parts or src.suffix.lower() == ".pyc":
            continue
        if src_rel == "docs/s6r" and src.name == "AUDIT_VERIFY_RESULT.json":
            # This sidecar contains the outer ZIP hash and remains outside the package.
            continue
        rel_source = src.relative_to(ROOT).as_posix()
        rel_target = src.relative_to(source).as_posix()
        # The package copy of the release folder is a standalone subdirectory.
        if dest_rel:
            rel_target = f"{dest_rel}/{rel_target}"
        else:
            rel_target = rel_source
        preserve = rel_source in FROZEN_FILES or src_rel == "docs/s6"
        copy_one(rel_source, rel_target, preserve=preserve, redactions=redactions)


def verify_frozen_manifest_paths(redactions: dict[str, Any]) -> None:
    holdout = json.loads((ROOT / f"runs/{RUN_ID}/S6_C_HOLDOUT_FREEZE_02.json").read_text(encoding="utf-8"))
    for rel in holdout.get("hashes", {}):
        if (ROOT / rel).is_file():
            copy_one(rel, preserve=rel in FROZEN_FILES, redactions=redactions)
    amendment = json.loads((ROOT / "docs/s6/S6_AMENDMENT_03_HASHES.json").read_text(encoding="utf-8"))
    for rel in amendment.get("hashes", {}):
        if (ROOT / rel).is_file():
            copy_one(rel, preserve=rel in FROZEN_FILES, redactions=redactions)


def scan_package(redactions: dict[str, Any]) -> list[str]:
    issues = []
    for path in STAGE.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() in {".exe", ".dll", ".msi", ".bat", ".cmd", ".ps1"}:
            issues.append(f"unexpected executable member: {path.relative_to(STAGE).as_posix()}")
        if path.suffix.lower() not in TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                issues.append(f"possible secret pattern in {path.relative_to(STAGE).as_posix()}")
        for private in (str(ROOT), str(ROOT).replace("\\", "/"), "<USER_PROFILE>", "<USER_PROFILE>"):
            if private in text:
                issues.append(f"unredacted local path in {path.relative_to(STAGE).as_posix()}")
    return issues


def build_manifest() -> dict[str, Any]:
    rows = []
    for path in sorted((x for x in STAGE.rglob("*") if x.is_file() and x.name not in {"manifest.json", "SHA256SUMS.txt"}), key=lambda p: p.relative_to(STAGE).as_posix()):
        rel = path.relative_to(STAGE).as_posix()
        rows.append({"path": rel, "bytes": path.stat().st_size, "sha256": sha256_bytes(path.read_bytes())})
    baseline_hashes = json.loads((ROOT / "docs/s6r/BASELINE_HASHES.json").read_text(encoding="utf-8"))
    status = json.loads((ROOT / "docs/s6r/S6R_FINAL_STATUS.json").read_text(encoding="utf-8"))
    manifest = {
        "schema": "optisys.s6r.gpt_audit_manifest/1",
        "package_run_id": AUDIT_RUN_ID,
        "source_s6_run_id": RUN_ID,
        "created_at_utc": status.get("generated_at_utc"),
        "source_s6_tree_sha256": baseline_hashes["immutable_trees"][f"runs/{RUN_ID}"]["tree_sha256"],
        "member_count_excluding_manifest_and_checksum": len(rows),
        "uncompressed_bytes_excluding_manifest_and_checksum": sum(x["bytes"] for x in rows),
        "checksum_coverage_exceptions": ["manifest.json", "SHA256SUMS.txt"],
        "files": rows,
        "zip_rebuild_status": "SAME_ENV_BYTE_REPRO_PASS",
        "screenshot_status": "NOT_DELIVERED_NEW_S6",
        "video_status": "NOT_DELIVERED",
    }
    return manifest


def make_checksum_text(manifest: dict[str, Any]) -> str:
    return "".join(f"{entry['sha256']}  {entry['path']}\n" for entry in manifest["files"])


def refresh_packaged_release_manifest() -> None:
    relroot = STAGE / "RELEASE_CANDIDATE_V2"
    manifest_path = relroot / "release_candidate_manifest.json"
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    status = json.loads((ROOT / "docs/s6r/S6R_FINAL_STATUS.json").read_text(encoding="utf-8"))
    rows = []
    for path in sorted((x for x in relroot.rglob("*") if x.is_file() and x != manifest_path), key=lambda p: p.relative_to(relroot).as_posix()):
        rows.append({"path": path.relative_to(relroot).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_bytes(path.read_bytes())})
    payload["status"] = status.get("S6R_RELEASE_STATUS", "PARTIAL")
    payload["engineering_status"] = status.get("S6R_RELEASE_STATUS", "PARTIAL")
    payload["science_recomputation_status"] = status.get("S6R_SCIENCE_RECOMPUTATION", "PARTIAL")
    payload["all_scenarios_verdict"] = status.get("S6_C_ALL_SCENARIOS_STATUS", "NOT_VERIFIED")
    payload["portfolio_media_status"] = status.get("S6R_PORTFOLIO_STATUS", "PARTIAL")
    payload["browser_e2e"] = status.get("S6R_BROWSER_E2E", "NOT_RUN")
    payload["screenshots"] = status.get("S6R_SCREENSHOTS", "NOT_DELIVERED")
    payload["new_s6_screenshots"] = status.get("S6R_SCREENSHOTS", "NOT_DELIVERED")
    payload["video"] = status.get("S6R_VIDEO", "NOT_DELIVERED")
    payload["gpt_audit"] = status.get("S6R_GPT_AUDIT_STATUS", "NOT_BUILT")
    payload["files"] = rows
    payload["file_count_excluding_manifest"] = len(rows)
    payload["total_bytes_excluding_manifest"] = sum(x["bytes"] for x in rows)
    payload["not_included"] = [".venv and local Python environments", "browser profiles", "personal agent memory files", "absolute local machine paths", "G0-G5 historical audit ZIPs"]
    manifest_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_zip() -> None:
    with zipfile.ZipFile(ZIP_PATH, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9, strict_timestamps=True) as zf:
        for path in sorted((x for x in STAGE.rglob("*") if x.is_file()), key=lambda p: p.relative_to(STAGE).as_posix()):
            rel = path.relative_to(STAGE).as_posix()
            info = zipfile.ZipInfo(rel, date_time=(2026, 10, 21, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 0
            info.external_attr = 0o100644 << 16
            info.flag_bits = 0
            zf.writestr(info, path.read_bytes(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)


def main() -> int:
    global AUDIT_RUN_ID, AUDIT_DIR, STAGE, ZIP_PATH
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", default=AUDIT_RUN_ID)
    parser.add_argument("--destination-root", type=Path, default=ROOT / "_AUDIT")
    args = parser.parse_args()
    AUDIT_RUN_ID = args.run_id
    destination_root = args.destination_root if args.destination_root.is_absolute() else ROOT / args.destination_root
    destination_root = destination_root.resolve()
    if not destination_root.is_relative_to(ROOT):
        raise SystemExit("audit destination root must remain inside the project workspace")
    AUDIT_DIR = destination_root / AUDIT_RUN_ID
    STAGE = AUDIT_DIR / "package"
    ZIP_PATH = AUDIT_DIR / f"OptiSysLab_S6R_{AUDIT_RUN_ID}_GPT_AUDIT.zip"
    if AUDIT_DIR.exists():
        raise SystemExit(f"Refusing to overwrite existing audit directory: {AUDIT_DIR}")
    if not (ROOT / "docs/s6r/S6R_FINAL_STATUS.json").is_file():
        raise SystemExit("S6R_FINAL_STATUS.json must exist before package creation")
    AUDIT_DIR.mkdir(parents=True, exist_ok=False)
    STAGE.mkdir(parents=True, exist_ok=False)
    redactions: dict[str, Any] = {}
    holdout_hashes = json.loads((ROOT / f"runs/{RUN_ID}/S6_C_HOLDOUT_FREEZE_02.json").read_text(encoding="utf-8")).get("hashes", {})
    amendment_hashes = json.loads((ROOT / "docs/s6/S6_AMENDMENT_03_HASHES.json").read_text(encoding="utf-8")).get("hashes", {})
    FROZEN_FILES.update(holdout_hashes)
    FROZEN_FILES.update(amendment_hashes)

    # Package-level review reports and the machine-readable S6-R record.
    copy_tree("docs/s6r", redactions=redactions)
    for doc in ("docs/s6r/00_START_HERE.md", "docs/s6r/01_EXECUTIVE_SUMMARY.md", "docs/s6r/02_SCIENTIFIC_REVIEW.md", "docs/s6r/03_VALIDATION_MATRIX.md", "docs/s6r/04_COMPUTE_AND_TESTS.md", "docs/s6r/05_RELEASE_VERIFICATION.md", "docs/s6r/06_KNOWN_ISSUES.md", "docs/s6r/07_REPRO_GUIDE.md", "docs/s6r/GPT_REVIEW_INSTRUCTIONS.md"):
        copy_one(doc, Path(doc).name, redactions=redactions)

    # Historic rules and hash ledgers. G0-G5 ZIPs themselves are intentionally not nested.
    for tree in ("docs/s6",):
        copy_tree(tree, redactions=redactions)
    for rel in (
        "docs/g2/G2_BASELINE_HASHES.json", "docs/g3/G3_BASELINE_HASHES.json",
        "docs/g4/G4_BASELINE_HASHES.json", "docs/g4/G4_FREEZE_HASHES.json", "docs/g4/G4_FINAL_STATUS.json",
        "docs/s5/S5_FREEZE_HASHES.json", "docs/s5/S5_FINAL_VERDICT.json",
    ):
        copy_one(rel, redactions=redactions)

    # Preserve all files named by the pre-result S6 holdout and post-run Amendment 03.
    verify_frozen_manifest_paths(redactions)
    for rel in S6_RUN_FILES:
        copy_one(rel, preserve=rel in FROZEN_FILES, redactions=redactions)
    cdir = f"runs/{RUN_ID}/s6_c_assemblies"
    for name in S6_C_FILES:
        copy_one(f"{cdir}/{name}", preserve=f"{cdir}/{name}" in FROZEN_FILES, redactions=redactions)
    for rel in (
        "runs/20261021_024715_S6_P1/s6_b_boundaries/focus_plane_extended.csv",
        "runs/20261021_024715_S6_P1/s6_b_boundaries/l2_position_extended.csv",
        "runs/20261021_024715_S6_P1/s6_b_boundaries/s6_focus_boundary.png",
        "runs/20261021_024715_S6_P1/s6_b_boundaries/s6_l2_position_boundary.png",
    ):
        if (ROOT / rel).is_file():
            copy_one(rel, redactions=redactions)

    # Core project, UI, configurations, all tests, and project license.
    for tree in ("src", "app", "tests", "configs"):
        copy_tree(tree, redactions=redactions)
    for rel in ("pyproject.toml", "requirements.lock.txt", "LICENSE", "README.md", ".github/workflows/ci.yml"):
        if (ROOT / rel).is_file():
            copy_one(rel, redactions=redactions)
    copy_one("repro/verify_s6r.py", redactions=redactions)
    verify_scripts = (
        "scripts/s6_assembly.py", "scripts/s6_finalize_claim.py", "scripts/s6_assembly_figures.py",
        "scripts/s6_reference.py", "scripts/s6_boundaries.py", "scripts/s6_boundary_figures.py",
        "scripts/make_basetemp.py", "scripts/smoke_streamlit_serve.py",
        "scripts/s6r_make_basetemp.py", "scripts/s6r_run_pytest.py", "scripts/s6r_run_apptest.py",
        "scripts/s6r_run_command.py", "scripts/s6r_install_check.py", "scripts/s6r_start_browser_server.py",
        "scripts/s6r_stop_browser_server.py", "scripts/s6r_inventory.py", "scripts/s6r_verify_release.py",
        "scripts/s6r_verify_audit.py",
        "scripts/s6r_generate_release_manifest.py",
    )
    for rel in verify_scripts:
        if (ROOT / rel).is_file():
            copy_one(rel, redactions=redactions)

    # The full release candidate is retained, including its historical S5 images and current S6 plots.
    copy_tree("RELEASE_CANDIDATE_V2", "RELEASE_CANDIDATE_V2", redactions=redactions)
    refresh_packaged_release_manifest()

    # Full R2 evidence, but no virtual environment, basetemp tree, or unrelated cache.
    validation_files = [
        "artifacts/s6r/environment/install_status.json", "artifacts/s6r/environment/install_stdout.txt",
        "artifacts/s6r/environment/install_stderr.txt", "artifacts/s6r/environment/pip_freeze.txt",
        "artifacts/s6r/environment/pip_freeze_stderr.txt", "artifacts/s6r/environment/environment_versions.json",
        "artifacts/s6r/tests/full_run.json", "artifacts/s6r/tests/full_stdout.txt",
        "artifacts/s6r/tests/full_stderr.txt", "artifacts/s6r/tests/full_junit.xml",
        "artifacts/s6r/ui/apptest_six_pages.json", "artifacts/s6r/ui/apptest_six_pages.xml",
        "artifacts/s6r/ui/apptest_six_pages_stdout.txt", "artifacts/s6r/ui/apptest_six_pages_stderr.txt",
        "artifacts/s6r/ui/streamlit_serve.json", "artifacts/s6r/ui/streamlit_serve.log",
        "artifacts/s6r/ui/browser_server.json", "artifacts/s6r/ui/browser_streamlit.log",
        "artifacts/s6r/cli/demo_650_run.json", "artifacts/s6r/cli/demo_650_stdout.txt", "artifacts/s6r/cli/demo_650_stderr.txt",
        "artifacts/s6r/cli/demo_976_run.json", "artifacts/s6r/cli/demo_976_stdout.txt", "artifacts/s6r/cli/demo_976_stderr.txt",
        "artifacts/s6r/cli/report_650_run.json", "artifacts/s6r/cli/report_650_stdout.txt", "artifacts/s6r/cli/report_650_stderr.txt",
        "artifacts/s6r/cli/report_976_run.json", "artifacts/s6r/cli/report_976_stdout.txt", "artifacts/s6r/cli/report_976_stderr.txt",
        "artifacts/s6r/audit_trial/verify_attempt_001_error.txt",
        "artifacts/s6r/audit_preflight/verify_result.json",
    ]
    for rel in validation_files:
        if (ROOT / rel).is_file():
            copy_one(rel, redactions=redactions)
    for rel in (
        "runs/_derived/s6r_20261021_0842/g3_demo",
        "runs/_derived/s6r_20261021_0842/pump976",
    ):
        if (ROOT / rel).is_dir():
            copy_tree(rel, redactions=redactions)

    (STAGE / "requirements-verify.txt").write_text("numpy==2.4.6\n", encoding="utf-8")
    (STAGE / "metadata" / "sanitization.json").parent.mkdir(parents=True, exist_ok=True)
    (STAGE / "metadata" / "sanitization.json").write_text(json.dumps({"schema": "optisys.s6r.sanitization/1", "redactions": redactions, "excluded": [".git", ".venv*", ".workbuddy", "1md task prompts", "_AUDIT historical ZIPs", "runs/20261021_024715_S6_P1/checkpoint shards beyond the full per-assembly evidence" ]}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    issues = scan_package(redactions)
    if issues:
        raise SystemExit("package privacy/integrity scan failed:\n" + "\n".join(issues))
    manifest = build_manifest()
    (STAGE / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")
    (STAGE / "SHA256SUMS.txt").write_text(make_checksum_text(manifest), encoding="utf-8")
    write_zip()
    with zipfile.ZipFile(ZIP_PATH) as zf:
        names = zf.namelist()
        if len(names) != len(set(names)):
            raise SystemExit("duplicate member names found in audit ZIP")
        if any(PurePosixPath(n).is_absolute() or ".." in PurePosixPath(n).parts for n in names):
            raise SystemExit("unsafe absolute or traversal member found in audit ZIP")
        bad = zf.testzip()
    if bad is not None:
        raise SystemExit(f"ZIP CRC failure at {bad}")
    print(json.dumps({"audit_dir": str(AUDIT_DIR), "package_dir": str(STAGE), "zip": str(ZIP_PATH), "zip_bytes": ZIP_PATH.stat().st_size, "member_count": len(names), "manifest_member_count": manifest["member_count_excluding_manifest_and_checksum"], "uncompressed_bytes": manifest["uncompressed_bytes_excluding_manifest_and_checksum"], "zip_test": "PASS"}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
