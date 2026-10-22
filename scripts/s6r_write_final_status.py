"""Build S6R_FINAL_STATUS.json from recorded evidence rather than expectations."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RUN_ID = "20261021_024715_S6_P1"
AUDIT_RUN_ID = "20261021_100205_S6R"
OUT = ROOT / "docs" / "s6r" / "S6R_FINAL_STATUS.json"


def load(path: str) -> dict[str, Any] | None:
    p = ROOT / path
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> int:
    science = load("docs/s6r/S6R_SCIENCE_RECOMPUTATION.json")
    hist = load("docs/s6r/HISTORICAL_PRESERVATION.json")
    preserve = load("docs/s6r/S6R_BASELINE_PRESERVATION.json")
    release = load("docs/s6r/S6R_RELEASE_VERIFICATION.json")
    tests = load("artifacts/s6r/tests/full_run.json")
    apptest = load("artifacts/s6r/ui/apptest_six_pages.json")
    serve = load("artifacts/s6r/ui/streamlit_serve.json")
    install = load("artifacts/s6r/environment/install_status.json")
    browser = load("docs/s6r/S6R_BROWSER_E2E.json")
    screenshots = load("docs/s6r/S6R_SCREENSHOT_MANIFEST.json")
    release_root = load("RELEASE_CANDIDATE_V2/release_candidate_manifest.json")
    cli_650 = load("artifacts/s6r/cli/demo_650_run.json")
    cli_976 = load("artifacts/s6r/cli/demo_976_run.json")
    audit = load("docs/s6r/AUDIT_VERIFY_RESULT.json")
    s6_a = load(f"runs/{RUN_ID}/s6_a_reference/s6_a_reference_summary.json")
    s6_b = load(f"runs/{RUN_ID}/s6_b_boundaries/boundary_analysis.json")
    holdout = load(f"runs/{RUN_ID}/S6_C_HOLDOUT_FREEZE_02.json")

    missing = [name for name, value in {
        "science": science, "historical_preservation": hist, "baseline_preservation": preserve,
        "release_verification": release, "full_pytest": tests, "apptest": apptest,
        "streamlit_smoke": serve, "install": install, "browser": browser, "screenshots": screenshots,
        "release_manifest": release_root, "CLI 650": cli_650, "CLI 976": cli_976,
        "S6-A summary": s6_a, "S6-B summary": s6_b, "holdout freeze": holdout,
    }.items() if value is None]
    if missing:
        raise SystemExit("missing required S6-R evidence: " + ", ".join(missing))

    audit_status = audit.get("status", "NOT_BUILT") if audit else "NOT_BUILT"
    science_ok = science.get("status") == "PASS" and science.get("cross_scenario_verdict") == "TRADEOFF_OR_NO_SUPPORTED_GAIN"
    historical_ok = hist.get("status") == "PASS"
    preserve_ok = preserve.get("status") == "PASS" and preserve.get("S6_ORIGINAL_SCIENCE_TREE_UNCHANGED") == "YES"
    release_ok = release.get("status") == "PASS" and release.get("false_delivery_claims") == []
    tests_ok = tests.get("status") == "PASS" and tests.get("exit_code") == 0 and tests.get("totals", {}).get("passed") == 482 and tests.get("totals", {}).get("failed") == 0 and tests.get("totals", {}).get("errors") == 0 and tests.get("totals", {}).get("skipped") == 0
    apptest_ok = apptest.get("status") == "PASS" and apptest.get("exit_code") == 0 and all(x.get("status") == "PASS" for x in apptest.get("six_page_checks", {}).values())
    serve_ok = serve.get("ok") is True and serve.get("health", {}).get("ok") is True and serve.get("root", {}).get("ok") is True and serve.get("alive_after_shutdown") is False
    install_ok = install.get("status") == "PASS" and install.get("install", {}).get("exit_code") == 0
    browser_status = browser.get("status", "NOT_RUN")
    browser_ok = browser_status in {"PASS", "NOT_RUN_POLICY_BLOCKED", "NOT_RUN"}
    screenshot_status = screenshots.get("S6R_SCREENSHOTS", "NOT_DELIVERED")
    gpt_status = audit_status if audit_status in {"PASS", "PARTIAL", "FAIL"} else "NOT_BUILT"
    all_core = all((science_ok, historical_ok, preserve_ok, release_ok, tests_ok, apptest_ok, serve_ok, install_ok, browser_ok))
    recovery = "PASS" if all_core and gpt_status == "PASS" else ("FAIL" if audit_status == "FAIL" or any(x.get("exit_code") not in (0, None) for x in (tests, apptest)) else "PARTIAL")
    release_status = "PASS_WITH_DECLARED_DEVIATIONS" if recovery == "PASS" and (screenshot_status != "DELIVERED_NEW_S6" or browser.get("video_status") != "DELIVERED_REAL_RECORDING") else ("PARTIAL" if recovery != "FAIL" else "FAIL")
    portfolio = "COMPLETE" if screenshot_status == "DELIVERED_NEW_S6" and browser.get("video_status") == "DELIVERED_REAL_RECORDING" else "PARTIAL"

    scenario = science["scenarios"]
    nominal = scenario["nominal_1x"]
    stress = scenario["stress_2x"]
    nominal_ci_pp = [100.0 * x for x in nominal["paired_mean_delta_capture_ci95"]]
    stress_p05_ci_pp = [100.0 * x for x in stress["p05_paired_delta_bootstrap_ci95"]]
    audit_zip_rel = f"_AUDIT/{AUDIT_RUN_ID}/OptiSysLab_S6R_{AUDIT_RUN_ID}_GPT_AUDIT.zip"
    checksum_rel = f"_AUDIT/{AUDIT_RUN_ID}/AUDIT_ZIP_SHA256.txt"
    s6a_rel = f"runs/{RUN_ID}/s6_a_reference/s6_a_reference_summary.json"
    s6a_hash_matches = holdout.get("hashes", {}).get(s6a_rel, {}).get("sha256") == hashlib.sha256((ROOT / s6a_rel).read_bytes()).hexdigest()
    result = {
        "schema": "optisys.s6r.final_status/1",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "project_root": str(ROOT),
        "source_s6_run_id": RUN_ID,
        "S6R_RECOVERY_EXECUTION_STATUS": recovery,
        "S6R_BASELINE_PRESERVATION": "PASS" if preserve_ok else "FAIL",
        "S6R_SCIENCE_RECOMPUTATION": "PASS" if science_ok else "PARTIAL",
        "S6_A_HISTORICAL_STATUS": "PASS" if s6_a.get("status") == "PASS" and s6a_hash_matches else "NOT_VERIFIED",
        "S6_B_HISTORICAL_STATUS": "OPTIMUM_NOT_BRACKETED" if s6_b.get("S6_B_FOCUS_STATUS") == "OPTIMUM_NOT_BRACKETED" and s6_b.get("S6_B_L2_POSITION_STATUS") == "OPTIMUM_NOT_BRACKETED" else "NOT_VERIFIED",
        "S6_C_NOMINAL_1X_STATUS": science.get("nominal_estimand_status", "NOT_VERIFIED"),
        "S6_C_ALL_SCENARIOS_STATUS": science.get("cross_scenario_verdict", "NOT_VERIFIED"),
        "S6_AMENDMENT_03_TRACEABILITY": "PASS" if science.get("amendment_03_traceability", {}).get("status") == "PASS" else "PARTIAL",
        "S6R_FULL_PYTEST": "PASS" if tests_ok else "FAIL",
        "S6R_APPTEST": "PASS" if apptest_ok else "FAIL",
        "S6R_STREAMLIT_REAL_SERVE": "PASS" if serve_ok else "FAIL",
        "S6R_BROWSER_E2E": browser_status if browser_status in {"PASS", "FAIL", "NOT_RUN_POLICY_BLOCKED", "NOT_RUN"} else "NOT_RUN",
        "S6R_SCREENSHOTS": screenshot_status,
        "S6R_VIDEO": "NOT_DELIVERED",
        "S6R_RELEASE_STATUS": release_status,
        "S6R_PORTFOLIO_STATUS": portfolio,
        "S6R_GPT_AUDIT_STATUS": gpt_status,
        "S6R_EMPIRICAL_STATUS": "NOT_AVAILABLE",
        "S6R_REMOTE_CI": "NOT_RUN",
        "S6R_GPU": "NOT_TESTED",
        "G2_SCIENCE_INHERITED": "QUALIFIED_ONLY",
        "G4_SCIENCE_INHERITED": "QUALIFIED",
        "S6_ASSEMBLIES_CHECKED": science["rows"]["unique_assembly_scenarios"],
        "S6_DESIGN_ASSEMBLY_ROWS": science["rows"]["design_assembly_rows"],
        "S6_NOMINAL_PAIRED_MEAN_DELTA_PP_CI95": {"mean_pp": 100.0 * nominal["mean_delta_capture_candidate_minus_baseline"], "ci95_pp": nominal_ci_pp},
        "S6_STRESS_PAIRED_P05_DELTA_PP_CI95": {"p05_pp": 100.0 * stress["p05_paired_delta_capture"], "ci95_pp": stress_p05_ci_pp},
        "S6_BOOTSTRAP_REPLAY": science["bootstrap"]["successful_replicates_per_scenario"],
        "HISTORICAL_G0_G1_G2_G3_G4_S5_HASHES": hist.get("status", "PARTIAL"),
        "CLEAN_INSTALL": {"status": "PASS" if install_ok else "FAIL", "python": install.get("environment", {}).get("python", "UNKNOWN"), "wall_s": install.get("install", {}).get("wall_s"), "pip_freeze": "artifacts/s6r/environment/pip_freeze.txt"},
        "CLI_DEMOS_AND_REPORT": {"status": "PASS_WITH_DECLARED_SCOPE" if cli_650.get("exit_code") == 0 and cli_976.get("exit_code") == 0 and cli_976.get("reported_domain_status") == "PARTIAL" else "FAIL", "650nm": cli_650, "976nm": cli_976},
        "STREAMLIT_APPTEST": apptest,
        "STREAMLIT_SERVE_SMOKE": serve,
        "BROWSER_E2E_EVIDENCE": "docs/s6r/S6R_BROWSER_E2E.json",
        "SCREENSHOT_MANIFEST": "docs/s6r/S6R_SCREENSHOT_MANIFEST.json",
        "RELEASE_DIR": "RELEASE_CANDIDATE_V2",
        "AUDIT_ZIP": audit_zip_rel,
        "AUDIT_ZIP_EXTERNAL_SHA256_FILE": checksum_rel,
        "AUDIT_MANIFEST_COVERAGE": audit.get("manifest_coverage") if audit else "PENDING",
        "AUDIT_EXTRACTED_REPRO": audit.get("extracted_repro") if audit else "PENDING",
        "AUDIT_TAMPER_AND_DELETION_REJECTION": audit.get("tamper_and_deletion_rejection") if audit else "PENDING",
        "AUDIT_SAME_ENVIRONMENT_BYTE_REBUILD": audit.get("same_environment_byte_rebuild") if audit else "PENDING",
        "OPEN_ISSUES": "docs/s6r/OPEN_ISSUES.md",
        "NEXT_ACTION": "Select an exact GitHub repository URL and visibility before upload; no remote is configured and accessible account repositories are unrelated.",
        "evidence": {
            "science": "docs/s6r/S6R_SCIENCE_RECOMPUTATION.json",
            "baseline": "docs/s6r/S6R_BASELINE_PRESERVATION.json",
            "release": "docs/s6r/S6R_RELEASE_VERIFICATION.json",
            "full_pytest": "artifacts/s6r/tests/full_run.json",
            "apptest": "artifacts/s6r/ui/apptest_six_pages.json",
            "streamlit_serve": "artifacts/s6r/ui/streamlit_serve.json",
            "install": "artifacts/s6r/environment/install_status.json",
            "historical": "docs/s6r/HISTORICAL_PRESERVATION.json",
        },
    }
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
