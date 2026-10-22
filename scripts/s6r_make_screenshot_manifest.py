"""Record S6 screenshot non-delivery and hash-check retained S5 images."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "RELEASE_CANDIDATE_V2"
OUT = ROOT / "docs" / "s6r" / "S6R_SCREENSHOT_MANIFEST.json"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    legacy = json.loads((RELEASE / "screenshot_evidence" / "browser_e2e.json").read_text(encoding="utf-8"))
    mapping = {
        "A": ("screenshot_evidence/A_overview.png", "A · 项目总览与证据状态"),
        "C": ("screenshot_evidence/C_optimization.png", "C · 优化对照"),
        "F": ("screenshot_evidence/F_pump976.png", "F · 976 nm 泵浦光路"),
    }
    rows = []
    for key, (rel, label) in mapping.items():
        path = RELEASE / rel
        match = next((x for x in legacy.get("pages", []) if x.get("page") == label), None)
        actual = sha(path) if path.is_file() else None
        expected = match.get("sha256") if match else None
        rows.append({"path": rel.replace("\\", "/"), "run_id": legacy.get("run_id"), "status": "PASS_HISTORICAL_S5" if actual and actual == expected else "FAIL_HASH_MISMATCH", "bytes": path.stat().st_size if path.is_file() else None, "sha256": actual, "expected_sha256": expected})
    result = {
        "schema": "optisys.s6r.screenshot_manifest/1",
        "S6R_SCREENSHOTS": "NOT_DELIVERED",
        "reason": "The in-app browser E2E tool did not expose a local PNG save path. Native Windows Chrome capture was stopped by the Computer Use active-URL safety check; no bypass was attempted.",
        "browser_e2e_record": "docs/s6r/S6R_BROWSER_E2E.json",
        "historical_s5_images": rows,
        "status": "PASS" if all(x["status"] == "PASS_HISTORICAL_S5" for x in rows) else "FAIL",
    }
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
