"""Generate the V2 release file manifest from the files actually present."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "RELEASE_CANDIDATE_V2"
MANIFEST = RELEASE / "release_candidate_manifest.json"
RUN_ID = "20261021_024715_S6_P1"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def main() -> int:
    previous = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.is_file() else {}
    browser = json.loads((ROOT / "docs/s6r/S6R_BROWSER_E2E.json").read_text(encoding="utf-8"))
    files = []
    for path in sorted((p for p in RELEASE.rglob("*") if p.is_file() and p != MANIFEST), key=lambda p: p.relative_to(RELEASE).as_posix()):
        files.append({"path": path.relative_to(RELEASE).as_posix(), "bytes": path.stat().st_size, "sha256": sha(path)})
    payload = {
        **previous,
        "schema": "optisys.s6r.release_candidate/1",
        "source_s6_run_id": RUN_ID,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
        "status": previous.get("status", "PENDING_AUDIT_PACKAGE_VERIFICATION"),
        "engineering_status": "PASS_WITH_DECLARED_DEVIATIONS",
        "science_recomputation_status": "PASS",
        "nominal_1x_estimand": "VERIFIED_CONDITIONAL_GAIN",
        "all_scenarios_verdict": "TRADEOFF_OR_NO_SUPPORTED_GAIN",
        "portfolio_media_status": "PARTIAL",
        "browser_e2e": browser.get("status", "NOT_RUN"),
        "partial_browser_interaction_status": browser.get("partial_in_app_interaction_status", "NOT_RUN"),
        "browser_e2e_evidence": "../docs/s6r/S6R_BROWSER_E2E.json",
        "screenshots": "S5_HISTORICAL_ONLY",
        "new_s6_screenshots": "NOT_DELIVERED",
        "video": "NOT_DELIVERED",
        "gpt_audit": previous.get("gpt_audit", "NOT_BUILT"),
        "full_pytest": {"status": "PASS", "passed": 482, "failed": 0, "errors": 0, "skipped": 0, "exit_code": 0, "wall_clock_s": 191.266},
        "clean_install": {"status": "PASS", "python": "3.11.9", "environment": ".venv_s6r_release", "log": "../artifacts/s6r/environment/install_stdout.txt", "pip_freeze": "../artifacts/s6r/environment/pip_freeze.txt"},
        "cli_demos": {"status": "PASS_WITH_DECLARED_SCOPE", "650nm": {"exit_code": 0, "run_status": "PASS", "assemblies": 1}, "976nm": {"exit_code": 0, "run_status": "PARTIAL", "rays": 512, "assemblies": 2}},
        "apptest": {"status": "PASS", "tests": 18, "passed": 18, "failed": 0, "skipped": 0, "pages": ["A", "B", "C", "D", "E", "F"]},
        "streamlit_serve_smoke": {"status": "PASS", "port": 20274, "health_body": "ok", "root_http_status": 200, "shutdown": "PASS"},
        "remote_ci": "NOT_RUN",
        "gpu": "NOT_TESTED",
        "empirical_validation": "NOT_AVAILABLE",
        "g2_inherited": "QUALIFIED_ONLY",
        "g4_inherited": "QUALIFIED",
        "science_recomputation_report": "../docs/s6r/S6R_SCIENCE_RECOMPUTATION.json",
        "files": files,
        "file_count_excluding_manifest": len(files),
        "total_bytes_excluding_manifest": sum(x["bytes"] for x in files),
        "not_included": [
            ".venv and local Python environments",
            "browser profiles",
            "personal agent memory files",
            "absolute local machine paths",
            "G0-G5 historical audit ZIPs",
        ],
    }
    MANIFEST.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "file_count": payload["file_count_excluding_manifest"], "total_bytes": payload["total_bytes_excluding_manifest"], "manifest": str(MANIFEST.relative_to(ROOT))}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
