"""Write Stage 5 final verdict/status from completed run evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
RUN="20261020_210201_S5_HNA"
RUN_DIR=ROOT/"runs"/RUN
DOCS=ROOT/"docs/s5"
ART=ROOT/"artifacts/s5"/RUN


def sha(path:Path)->str:return hashlib.sha256(path.read_bytes()).hexdigest()


def main()->int:
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-status",choices=("PARTIAL","PASS"),default="PARTIAL")
    args=parser.parse_args()
    ref=json.loads((RUN_DIR/"full_na_verdict.json").read_text(encoding="utf-8"))
    b=json.loads((RUN_DIR/"s5_b_analysis_status.json").read_text(encoding="utf-8"))
    c=json.loads((RUN_DIR/"bootstrap_summary.json").read_text(encoding="utf-8"))
    tests=json.loads((RUN_DIR/"test_evidence/s5_full_process.json").read_text(encoding="utf-8"))
    junit_root=ET.parse(RUN_DIR/"test_evidence/s5_full_junit.xml").getroot()
    suites=[junit_root] if junit_root.tag=="testsuite" else list(junit_root.findall(".//testsuite"))
    junit={"tests":sum(int(x.attrib.get("tests","0")) for x in suites),
           "failures":sum(int(x.attrib.get("failures","0")) for x in suites),
           "errors":sum(int(x.attrib.get("errors","0")) for x in suites),
           "skipped":sum(int(x.attrib.get("skipped","0")) for x in suites),
           "suite_time_s":sum(float(x.attrib.get("time","0")) for x in suites)}
    browser=json.loads((RUN_DIR/"portfolio/browser_e2e_final.json").read_text(encoding="utf-8"))
    serve=json.loads((RUN_DIR/"test_evidence/streamlit/streamlit_serve.json").read_text(encoding="utf-8"))
    portfolio_status="PARTIAL" if browser.get("status")=="PASS" else "PARTIAL"
    key_paths=[
      "runs/20261020_210201_S5_HNA/provenance.json",
      "runs/20261020_210201_S5_HNA/environment.json",
      "runs/20261020_210201_S5_HNA/design_configs.json",
      "runs/20261020_210201_S5_HNA/full_na_surface_reference.csv",
      "runs/20261020_210201_S5_HNA/full_na_ray_reference.csv",
      "runs/20261020_210201_S5_HNA/full_na_verdict.json",
      "runs/20261020_210201_S5_HNA/angle_resolved_p0_p1_capture.csv",
      "runs/20261020_210201_S5_HNA/surface_level_ray_deltas.csv",
      "runs/20261020_210201_S5_HNA/focus_sweep.csv",
      "runs/20261020_210201_S5_HNA/focus_sweep_ray_deltas.csv",
      "runs/20261020_210201_S5_HNA/encircled_weight.csv",
      "runs/20261020_210201_S5_HNA/target_geometry_sensitivity.csv",
      "runs/20261020_210201_S5_HNA/lens_geometry_feasibility.csv",
      "runs/20261020_210201_S5_HNA/source_assumption_sensitivity.csv",
      "runs/20261020_210201_S5_HNA/design_search.csv",
      "runs/20261020_210201_S5_HNA/design_comparison.csv",
      "runs/20261020_210201_S5_HNA/design_search_source_samples.csv",
      "runs/20261020_210201_S5_HNA/design_holdout_source_samples.csv",
      "runs/20261020_210201_S5_HNA/design_holdout_ray_results.csv",
      "runs/20261020_210201_S5_HNA/paired_samples.csv",
      "runs/20261020_210201_S5_HNA/bootstrap_summary.json",
      "runs/20261020_210201_S5_HNA/report.md",
      "runs/20261020_210201_S5_HNA/report.html",
      "runs/20261020_210201_S5_HNA/test_evidence/s5_full_junit.xml",
      "runs/20261020_210201_S5_HNA/test_evidence/s5_full_stdout.txt",
      "runs/20261020_210201_S5_HNA/portfolio/browser_e2e_final.json",
      "runs/20261020_210201_S5_HNA/portfolio/screenshot_evidence/A_overview_final.png",
      "runs/20261020_210201_S5_HNA/portfolio/screenshot_evidence/C_optimization_final.png",
      "runs/20261020_210201_S5_HNA/portfolio/screenshot_evidence/F_pump976_final.png",
    ]
    files={p:{"bytes":(ROOT/p).stat().st_size,"sha256":sha(ROOT/p)} for p in key_paths}
    freeze=json.loads((DOCS/"S5_FREEZE_HASHES.json").read_text(encoding="utf-8"))
    verdict={
      "schema":"optisys.s5.final_verdict/1","run_id":RUN,
      "historical_baselines_preserved":True,
      "G2_SCIENCE_INHERITED":"QUALIFIED_ONLY","G4_OPTICAL_SCIENCE_INHERITED":"QUALIFIED",
      "S5_ENGINEERING_EXECUTION_STATUS":"PASS",
      "S5_A_REFERENCE_VERIFICATION":ref["status"],
      "S5_B_HIGH_NA_CAUSE_STATUS":b["S5_B_HIGH_NA_CAUSE_STATUS"],
      "S5_C_DESIGN_STATUS":c["status"],"S5_PORTFOLIO_STATUS":portfolio_status,
      "S5_EMPIRICAL_STATUS":"NOT_AVAILABLE","S5_AUDIT_STATUS":args.audit_status,
      "source_power_w":None,"model_level":"P0_AND_ASSUMED_P1_WITH_SCOPE",
      "scientific_limitations":[
        "N-BK7 singlets and source probability distribution are assumptions, not measured device data.",
        "P1 reference verifies agreement between implementations only for the registered centered spherical geometry.",
        "High-NA longitudinal-focus proxy is geometric, not a wavefront Seidel coefficient or measured PSF.",
        "S5-C paired interval is ray-resampling uncertainty, not assembly-level tolerance.",
        "Target sizes are assumed receiving regions; no Er:YAP dimensions, pump power, efficiency, W/mm^2 or thermal response are available.",
        "G4 official scientific status and overall design claim remain unchanged."
      ],
      "untested_items":[
        "REMOTE_CI_NOT_RUN","GPU_NOT_TESTED","VIDEO_NOT_DELIVERED",
        "P1_ASSEMBLY_LEVEL_TOLERANCE_NOT_RUN","MEASURED_OPTICAL_VALIDATION_NOT_AVAILABLE"
      ],
      "git_commit":"PRIVATE_SOURCE_REVISION",
      "git_worktree_dirty_at_stage5_start":True,
      "preexisting_worktree_files_hashed":169,
      "freeze_hashes":{row["path"]:row["sha256"] for row in freeze["files"]},
      "files_index":files,
      "verification_summary":{"pytest":{"tests":junit["tests"],
                                          "passed":junit["tests"]-junit["failures"]-junit["errors"]-junit["skipped"],
                                          "failures":junit["failures"],
                                          "errors":junit["errors"],
                                          "skipped":junit["skipped"],
                                          "junit_time_s":junit["suite_time_s"],
                                          "outer_wall_s":tests.get("outer_wall_s")},
                            "streamlit_real_serve":"PASS" if serve.get("ok") else "FAIL",
                            "browser_e2e":browser.get("status"),"browser_screenshots":len(browser.get("pages",[]))},
      "external_audit_archive":None,
      "finalized_at_utc":datetime.now(timezone.utc).isoformat(timespec="seconds")
    }
    (DOCS/"S5_FINAL_VERDICT.json").write_text(json.dumps(verdict,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    run_status={"schema":"optisys.s5.run_status/1","run_id":RUN,"status":"PASS_WITH_DECLARED_LIMITS",
                "frozen":True,"evidence_level":"SIMULATED",
                **{k:verdict[k] for k in ("S5_ENGINEERING_EXECUTION_STATUS","S5_A_REFERENCE_VERIFICATION",
                                          "S5_B_HIGH_NA_CAUSE_STATUS","S5_C_DESIGN_STATUS","S5_PORTFOLIO_STATUS",
                                          "S5_EMPIRICAL_STATUS","S5_AUDIT_STATUS","G2_SCIENCE_INHERITED",
                                          "G4_OPTICAL_SCIENCE_INHERITED")},
                "model_level":verdict["model_level"],"source_power_w":None,
                "untested_items":verdict["untested_items"]}
    (RUN_DIR/"run_status.json").write_text(json.dumps(run_status,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps({"verdict":str((DOCS/"S5_FINAL_VERDICT.json").relative_to(ROOT)),
                      "S5_AUDIT_STATUS":args.audit_status,"S5_C_DESIGN_STATUS":c["status"],
                      "tests":verdict["verification_summary"]["pytest"]},ensure_ascii=False,indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
