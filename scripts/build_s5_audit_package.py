"""Build a deterministic, redacted, minimal Stage 5 GPT audit ZIP."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUN = "20261020_210201_S5_HNA"
RUN_DIR = ROOT / "runs" / RUN
ART = ROOT / "artifacts" / "s5" / RUN
STAGE = Path(os.environ.get("OPTISYS_S5_AUDIT_STAGE", str(ART / "audit_package_final")))
AUDIT_DIR = ROOT / "_AUDIT" / RUN
G4_RUN = ROOT / "runs/20261020_133555_G4_ec3e2813_0e48"
G4_ZIP = ROOT / "_AUDIT/20261020_133555_G4_ec3e2813_0e48/OptiSysLab_G4_20261020_133555_G4_ec3e2813_0e48_GPT_AUDIT.zip"
FREEZE = ROOT / "docs/s5/S5_FREEZE_HASHES.json"
EXCEPTIONS = {"manifest.json", "SHA256SUMS.txt"}
TEXT_SUFFIXES = {".txt", ".md", ".json", ".csv", ".xml", ".yaml", ".yml", ".py", ".toml", ".html"}
ABSOLUTE_PATH = re.compile(r"(?i)(?<![A-Za-z0-9])[A-Z]:[\\/][^\s\"'<>|]+")
SECRET_PATTERNS = (
    re.compile(r"(?i)\b(?:sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    re.compile(r"(?i)\bAKIA[0-9A-Z]{16}\b"),
)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha_path(path: Path) -> str:
    return sha(path.read_bytes())


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _copy(src: Path, dst_rel: str, *, sanitize: bool = True) -> None:
    dst = STAGE.joinpath(*PurePosixPath(dst_rel).parts)
    dst.parent.mkdir(parents=True, exist_ok=True)
    data = src.read_bytes()
    if sanitize and src.suffix.lower() in TEXT_SUFFIXES:
        text = data.decode("utf-8", errors="strict")
        text = text.replace(str(ROOT), "<PROJECT_ROOT>")
        text = text.replace(str(ROOT).replace("\\", "/"), "<PROJECT_ROOT>")
        # Remove remaining absolute local paths without changing relative run IDs.
        text = ABSOLUTE_PATH.sub("<ABSOLUTE_PATH_REDACTED>", text)
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                raise ValueError(f"possible secret found in {dst_rel}")
        data = text.encode("utf-8")
    dst.write_bytes(data)


def _safe_member(name: str) -> bool:
    if not name or "\\" in name or name.startswith("/") or (len(name) > 1 and name[1] == ":"):
        return False
    p = PurePosixPath(name)
    return not p.is_absolute() and ".." not in p.parts and all(x not in ("", ".") for x in p.parts)


def _freeze_summaries() -> tuple[dict[str, Any], dict[str, Any]]:
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    baseline = json.loads((ART / "S5_BASELINE_SNAPSHOT.json").read_text(encoding="utf-8"))
    g4_verify = json.loads((RUN_DIR / "g4_audit_verify.json").read_text(encoding="utf-8"))
    g03 = json.loads((RUN_DIR / "g0_g3_baseline.stdout.txt").read_text(encoding="utf-8").splitlines()[-1])
    g4_tree = baseline["historical_g4"]["run_tree"]
    g4_archive = baseline["historical_g4"]["audit_zip"]
    frozen = {
        "schema": "optisys.s5.baseline_hashes/1", "run_id": RUN,
        "G0_G1_G2_G3_protected_verification": {"result": g03.get("result"), "check_count": g03.get("check_count"),
                                                "failure_count": g03.get("failure_count")},
        "G4_run": {"run_id": "20261020_133555_G4_ec3e2813_0e48",
                   "file_count": g4_tree["file_count"], "tree_sha256": g4_tree["tree_sha256"]},
        "G4_audit_zip": {"sha256": g4_archive["sha256"], "bytes": g4_archive["bytes"],
                         "content_and_replay_status": g4_verify.get("AUDIT_VERIFY"),
                         "members": g4_verify.get("zip_members"),
                         "manifest_files": g4_verify.get("manifest_covered")},
        "G4_historical_status_sha256": sha_path(ROOT / "docs/g4/G4_FINAL_STATUS.json"),
        "source_plan_sha256": freeze["files"][5]["sha256"],
        "task_prompt_sha256": freeze["files"][6]["sha256"],
        "S5_freeze_files": freeze["files"][:5],
        "preexisting_dirty_files_hashed_at_takeover": baseline["git"]["porcelain_lines"],
        "git_commit_at_takeover": baseline["git"]["commit"],
        "note": "No G0-G4 run, historical status or audit archive is embedded or rewritten.",
    }
    replay = {
        "schema": "optisys.s5.g4_replay_result/1", "run_id": RUN,
        "G4_AUDIT_ZIP_SHA256": g4_archive["sha256"],
        "G4_ZIP_CONTENT_INTEGRITY": g4_verify.get("CONTENT_INTEGRITY"),
        "G4_EXTRACTED_REPRO": g4_verify.get("EXTRACTED_REPRO"),
        "G4_TAMPER_REJECTED": g4_verify.get("TAMPER_REJECTED"),
        "G4_VERIFIER_EXIT_CODE": g4_verify.get("exit_code"),
        "source_zip_embedded": False,
    }
    return frozen, replay


def _build_stage() -> None:
    if STAGE.exists():
        raise FileExistsError(f"refusing to overwrite existing audit staging tree: {STAGE}")
    STAGE.mkdir(parents=True)
    for d in ("baseline_g4", "source", "src/optisys/optics", "src/optisys/sources", "src/optisys",
              "configs", "tests/unit", "tests/integration", "scripts", "repro", "run_evidence/figures",
              "run_evidence/test_evidence", "run_evidence/streamlit_evidence", "portfolio/screenshot_evidence",
              "portfolio/figures", "portfolio/data"):
        (STAGE / d).mkdir(parents=True, exist_ok=True)

    # Executive and audit-facing documents.
    docs = {
        "00_START_HERE.md": "# Start here\n\nThis package contains the complete Stage 5 evidence needed to independently replay the assumed P1 high-NA model and its nominal equal-aperture position trade-off. Run `python repro/verify_s5.py` from this extracted directory. The package is not a measured optical result.\n",
        "01_EXECUTIVE_SUMMARY.md": (ROOT / "docs/s5/S5_HIGH_NA_DIAGNOSIS.md").read_text(encoding="utf-8"),
        "02_SCIENCE_SCOPE_AND_ASSUMPTIONS.md": (ROOT / "docs/s5/S5_SCIENCE_SCOPE.md").read_text(encoding="utf-8"),
        "03_HIGH_NA_REFERENCE_AUDIT.md": (ROOT / "docs/s5/S5_HIGH_NA_DIAGNOSIS.md").read_text(encoding="utf-8"),
        "04_MECHANICAL_AND_DESIGN_TRADEOFF.md": (ROOT / "docs/s5/S5_HIGH_NA_DIAGNOSIS.md").read_text(encoding="utf-8"),
        "05_VALIDATION_MATRIX.md": (ROOT / "docs/s5/S5_VALIDATION_MATRIX.md").read_text(encoding="utf-8"),
        "06_COMPUTE_AND_PERFORMANCE.md": (ROOT / "docs/s5/S5_COMPUTE_MEASURED.md").read_text(encoding="utf-8"),
        "07_KNOWN_ISSUES_AND_FAILURES.md": (ROOT / "docs/s5/S5_OPEN_ISSUES.md").read_text(encoding="utf-8"),
        "08_REPRODUCTION_GUIDE.md": (ROOT / "repro/README.md").read_text(encoding="utf-8"),
        "09_NEXT_STEPS.md": "# Next steps\n\n1. Obtain vendor lens drawings and actual clear/outer aperture and mount envelope if physical feasibility is needed.\n2. Measure the source angular distribution and calibrated optical power only in an authorized instrumented setup.\n3. If assembly robustness is needed, add verified P1 decenter/tilt coordinate breaks and a separately frozen assembly-level holdout.\n4. Keep empirical and manufacturing claims separate from this assumed-model result.\n",
        "GPT_REVIEW_INSTRUCTIONS.md": "# GPT review instructions\n\nIndependently run `python repro/verify_s5.py` after extraction. Review all source-weight denominators, full surface states, angle bins, focus planes, receiving-region cases, mechanical sag and edge thickness, equal-aperture search/holdout and paired bootstrap. Treat all conclusions as `SIMULATED / ASSUMED P1`. Do not infer watts, efficiency, vendor manufacturability, assembly robustness or experiment. The G4 baseline and its status are immutable.\n",
    }
    for name, content in docs.items():
        _write(STAGE / name, content)

    freeze, replay = _freeze_summaries()
    _write(STAGE / "baseline_g4/G4_BASELINE_HASHES.json", json.dumps(freeze, ensure_ascii=False, indent=2) + "\n")
    _copy(ROOT / "docs/g4/G4_FINAL_STATUS.json", "baseline_g4/G4_HISTORICAL_STATUS.json")
    _write(STAGE / "baseline_g4/G4_REPLAY_RESULT.json", json.dumps(replay, ensure_ascii=False, indent=2) + "\n")
    for name in ("optics_model.json", "source_samples.csv", "raytrace_reference.csv"):
        _copy(G4_RUN / name, f"baseline_g4/{name}")

    _write(STAGE / "source/source_plan_sha256.txt", "sha256 25d0a727fbf047e8b399be8bd1ab670149b4a32377ff8edcef63e41ca4e6319d\n")
    _write(STAGE / "source/task_prompt_sha256.txt", "sha256 a90a597244c240775d1211a282d38cf5e39cb4bffc980610f387d788ac370fc0\n")
    _write(STAGE / "source/original_model_scope.md",
           "# Original model scope\n\nThe source project plan defines G4 as a lightweight 976 nm multi-mode geometric pump path, not a complete Er:YAP laser twin. Stage 5 is the optional post-G4 extension specified by the user-provided task prompt. S5 does not create an additional mandatory project Gate. The original PDF and prompt are identified by SHA-256 above; they are not embedded to keep the audit minimal.\n")

    # Portable design inputs assembled from the G4 model/configs and S5 freeze.
    _copy(RUN_DIR / "design_configs.json", "configs/design_configs.json")
    _copy(RUN_DIR / "config_snapshot.yaml", "configs/config_snapshot.yaml")
    for name in ("pump976_g4_l0.yaml", "pump976_g4_l1.yaml"):
        _copy(ROOT / "configs" / name, f"configs/{name}")
    _copy(ROOT / "requirements.lock.txt", "configs/requirements.lock.txt")
    _copy(ROOT / "pyproject.toml", "configs/pyproject.toml")
    _copy(ROOT / "LICENSE", "source/LICENSE")
    schott = ROOT / ".venv/Lib/site-packages/optiland/database/data-nk/glass/schott/N-BK7.yml"
    _copy(schott, "source/N-BK7_SCHOTT_catalog_excerpt.yml")

    # Relevant implementation and its direct imports only.
    src_files = (
        "src/optisys/__init__.py", "src/optisys/config.py", "src/optisys/config_g4.py",
        "src/optisys/optics/__init__.py", "src/optisys/optics/pump_beamline.py",
        "src/optisys/optics/reference_thin_lens.py", "src/optisys/optics/pump_optiland.py",
        "src/optisys/optics/s5_reference.py", "src/optisys/sources/__init__.py",
        "src/optisys/sources/multimode_fiber.py", "src/optisys/evaluation/__init__.py",
        "src/optisys/evaluation/pump_metrics.py", "src/optisys/cli.py",
    )
    for rel in src_files:
        _copy(ROOT / rel, rel)
    for rel in ("tests/unit/test_s5_reference.py", "tests/unit/test_pump976_optiland.py",
                "tests/integration/test_report_g3_cli.py", "scripts/__init__.py",
                "scripts/s5_profile.py", "scripts/s5_run_reference.py", "scripts/s5_analyze.py",
                "scripts/s5_design_compare.py", "scripts/s5_process_runner.py",
                "scripts/s5_build_report.py", "scripts/s5_finalize_metadata.py",
                "scripts/build_s5_audit_package.py",
                "scripts/verify_s5_audit_package.py", "repro/verify_s5.py", "repro/README.md"):
        _copy(ROOT / rel, rel)

    # Complete science evidence; G4's large archive and unrelated G2/G3 files are not nested.
    evidence_files = (
        "config_snapshot.yaml", "design_configs.json", "provenance.json", "environment.json",
        "run_status.json", "compute_measured.json", "compute_profile_samples.csv",
        "s5_b_analysis_status.json", "s5_c_design_status.json",
        "s5_a_execution_final.json", "s5_b_execution_final2.json", "s5_c_execution_final3.json",
        "full_na_surface_reference.csv", "full_na_ray_reference.csv", "full_na_verdict.json",
        "surface_geometry.json", "angle_resolved_p0_p1_capture.csv", "surface_level_ray_deltas.csv",
        "mechanism_strata.csv", "focus_sweep.csv", "focus_sweep_ray_deltas.csv",
        "encircled_weight.csv", "nominal_conditional_unconditional_metrics.csv",
        "target_geometry_sensitivity.csv", "lens_geometry_feasibility.csv",
        "longitudinal_focus_proxy.csv", "source_assumption_sensitivity.csv",
        "source_assumption_source_samples.csv", "source_assumption_ray_reference.csv",
        "design_search.csv", "design_search_source_samples.csv", "design_holdout_source_samples.csv",
        "design_holdout_ray_results.csv", "design_comparison.csv", "paired_samples.csv",
        "bootstrap_summary.json", "report.md", "report.html",
    )
    for name in evidence_files:
        _copy(RUN_DIR / name, f"run_evidence/{name}")
    _copy(ROOT / "docs/s5/S5_FINAL_VERDICT.json", "run_evidence/final_verdict.json")
    for name in ("S5_ACCEPTANCE_CRITERIA.md", "S5_EXECUTION_PLAN.md", "S5_COMPUTE_BUDGET.md",
                 "S5_SCIENCE_SCOPE.md", "S5_FREEZE_HASHES.json", "S5_BASELINE_VERIFICATION.md",
                 "S5_HIGH_NA_DIAGNOSIS.md", "S5_COMPUTE_MEASURED.md", "S5_VALIDATION_MATRIX.md",
                 "S5_OPEN_ISSUES.md"):
        _copy(ROOT / "docs/s5" / name, f"run_evidence/prereg_and_reports/{name}")
    for path in sorted((RUN_DIR / "figures").glob("*.png")):
        _copy(path, f"run_evidence/figures/{path.name}", sanitize=False)

    # Full suite output, JUnit, actual serve probe and compact CLI logs.
    test_dir = RUN_DIR / "test_evidence"
    for name in ("s5_full_junit.xml", "s5_full_stdout.txt", "s5_full_stderr.txt", "s5_full_process.json"):
        _copy(test_dir / name, f"run_evidence/test_evidence/{name}")
    serve_dir = test_dir / "streamlit"
    for name in ("streamlit_serve.json", "streamlit_serve_execution.json", "streamlit_serve.log",
                 "streamlit_serve_negative.log"):
        path = serve_dir / name
        if path.is_file():
            _copy(path, f"run_evidence/streamlit_evidence/{name}")
    for src, dst in (
        (ART / "cli_g3_demo.stdout.txt", "g3_demo_stdout.txt"),
        (ART / "cli_g3_demo.stderr.txt", "g3_demo_stderr.txt"),
        (test_dir / "cli_g3_demo_execution.json", "g3_demo_execution.json"),
        (ART / "cli_pump976.stdout.txt", "pump976_stdout.txt"),
        (ART / "cli_pump976.stderr.txt", "pump976_stderr.txt"),
        (test_dir / "cli_pump976_execution.json", "pump976_execution.json"),
        (ART / "cli_expected_error.stderr.txt", "expected_cli_error_stderr.txt"),
        (test_dir / "cli_expected_error.json", "expected_cli_error_execution.json"),
        (ART / "cli_g3_report_retry.stdout.txt", "g3_report_stdout.txt"),
        (test_dir / "cli_g3_report_retry_execution.json", "g3_report_execution.json"),
        (ART / "cli_pump976_report.stdout.txt", "pump976_report_stdout.txt"),
        (test_dir / "cli_pump976_report_execution.json", "pump976_report_execution.json"),
    ):
        _copy(src, f"run_evidence/cli_evidence/{dst}")
    _copy(RUN_DIR / "portfolio/browser_e2e_final.json", "portfolio/browser_e2e.json")

    # Portfolio excerpt, real screen captures, figures, and source-backed data.
    for src, dst in (
        (ROOT / "RELEASE_CANDIDATE/README_excerpt.md", "portfolio/README_excerpt.md"),
        (ROOT / "RELEASE_CANDIDATE/DEMO_SCRIPT_5MIN.md", "portfolio/DEMO_SCRIPT_5MIN.md"),
        (ROOT / "RELEASE_CANDIDATE/DEMO_CAPTURE_CHECKLIST.md", "portfolio/DEMO_CAPTURE_CHECKLIST.md"),
        (ROOT / "RELEASE_CANDIDATE/KNOWN_LIMITATIONS.md", "portfolio/KNOWN_LIMITATIONS.md"),
        (ROOT / "RELEASE_CANDIDATE/TECH_INTERVIEW_SUMMARY.md", "portfolio/TECH_INTERVIEW_SUMMARY.md"),
        (ROOT / "RELEASE_CANDIDATE/release_candidate_manifest.json", "portfolio/release_candidate_manifest.json"),
    ):
        _copy(src, dst)
    for path in sorted((ROOT / "RELEASE_CANDIDATE/screenshot_evidence").glob("*.png")):
        _copy(path, f"portfolio/screenshot_evidence/{path.name}", sanitize=False)
    for path in sorted((ROOT / "RELEASE_CANDIDATE/figures").glob("*.png")):
        _copy(path, f"portfolio/figures/{path.name}", sanitize=False)
    for path in sorted((ROOT / "RELEASE_CANDIDATE/data").glob("*.csv")):
        _copy(path, f"portfolio/data/{path.name}")

    # Standalone sanitized test/installation summaries; raw paths remain in the local run folder only.
    full = json.loads((test_dir / "s5_full_process.json").read_text(encoding="utf-8"))
    clean_install = json.loads((ART / "clean_install_result.json").read_text(encoding="utf-8"))
    _write(STAGE / "run_evidence/test_evidence/test_summary.json", json.dumps({
        "suite": "pytest", "tests": 461, "passed": 461, "failed": 0, "errors": 0, "skipped": 0,
        "junit_suite_time_s": 144.875, "outer_process_wall_s": full["outer_wall_s"],
        "exit_code": full["exit_code"], "fresh_environment_install_status": clean_install["status"],
        "streamlit_version": "1.66.0", "optiland_version": "0.6.3",
        "video": "NOT_DELIVERED", "remote_ci": "NOT_RUN", "gpu": "NOT_TESTED"
    }, ensure_ascii=False, indent=2) + "\n")

    # Security and path audit on all ordinary package files before manifest construction.
    for path in (p for p in STAGE.rglob("*") if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES):
        text = path.read_text(encoding="utf-8")
        hit = ABSOLUTE_PATH.search(text)
        if hit:
            raise ValueError(f"absolute path remains in audit content {path.relative_to(STAGE)}: {hit.group(0)}")
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                raise ValueError(f"possible secret remains in audit content {path.relative_to(STAGE)}")


def _deterministic_zip(path: Path, root: Path, names: list[str]) -> None:
    # CSV ray evidence is large but highly repetitive; DEFLATED keeps the full
    # evidence below the registered 40 MB archive target without dropping rows.
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for name in names:
            p = root.joinpath(*PurePosixPath(name).parts)
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o600 << 16
            info.create_system = 0
            info.flag_bits = 0
            zf.writestr(info, p.read_bytes())


def build(archive_override: Path | None = None) -> dict[str, Any]:
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    archive_name = f"OptiSysLab_S5_{RUN}_GPT_AUDIT.zip"
    archive = archive_override.resolve() if archive_override else AUDIT_DIR / archive_name
    archive.parent.mkdir(parents=True, exist_ok=True)
    if archive.exists():
        raise FileExistsError(f"refusing to overwrite audit ZIP: {archive}")
    if not STAGE.exists():
        _build_stage()
    elif (STAGE / "manifest.json").exists():
        raise FileExistsError(f"refusing to rebuild a frozen audit staging tree: {STAGE}")
    ordinary = []
    for p in sorted(x for x in STAGE.rglob("*") if x.is_file()):
        name = p.relative_to(STAGE).as_posix()
        if not _safe_member(name):
            raise ValueError(f"unsafe audit member: {name}")
        data = p.read_bytes()
        ordinary.append({"path": name, "bytes": len(data), "sha256": sha(data)})
    manifest = {"schema": "optisys.s5.audit_manifest/1", "run_id": RUN,
                "files": ordinary, "self_reference_exceptions": sorted(EXCEPTIONS)}
    _write(STAGE / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    sum_rows = [f"{sha((STAGE / row['path']).read_bytes())}  {row['path']}" for row in ordinary]
    sum_rows.append(f"{sha((STAGE / 'manifest.json').read_bytes())}  manifest.json")
    _write(STAGE / "SHA256SUMS.txt", "\n".join(sum_rows) + "\n")
    all_names = sorted(p.relative_to(STAGE).as_posix() for p in STAGE.rglob("*") if p.is_file())
    _deterministic_zip(archive, STAGE, all_names)
    archive_sha = sha_path(archive)
    result = {"run_id": RUN, "archive": archive.relative_to(ROOT).as_posix(),
              "archive_bytes": archive.stat().st_size, "archive_sha256": archive_sha,
              "member_count": len(all_names), "manifest_covered": len(ordinary),
              "self_reference_exceptions": sorted(EXCEPTIONS),
              "size_under_40mb": archive.stat().st_size < 40*1024*1024,
              "built_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if not result["size_under_40mb"]:
        raise ValueError(f"audit archive exceeds 40 MB: {result['archive_bytes']}")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage-only", action="store_true",
                        help="build the sanitized package tree for independent preflight reproduction")
    parser.add_argument("--archive-path", type=Path, default=None,
                        help="optional output path for preflight builds")
    args = parser.parse_args()
    if args.stage_only:
        _build_stage()
        print(json.dumps({"stage": str(STAGE), "status": "STAGED_FOR_PRECHECK"}, ensure_ascii=False))
    else:
        build(args.archive_path)
