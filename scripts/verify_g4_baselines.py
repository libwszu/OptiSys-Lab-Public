"""Verify the protected G0–G3 run, source, config, and audit baselines."""

from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SNAPSHOT = ROOT / "docs/g4/G4_BASELINE_HASHES.json"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _tree(path: Path) -> dict[str, Any]:
    files = []
    for item in sorted(p for p in path.rglob("*") if p.is_file()):
        rel = item.relative_to(ROOT).as_posix()
        files.append({"path": rel, "bytes": item.stat().st_size, "sha256": _sha256(item)})
    canonical = "".join(f"{f['path']}\0{f['sha256']}\n" for f in files).encode("utf-8")
    return {"file_count": len(files), "total_bytes": sum(f["bytes"] for f in files),
            "tree_sha256": hashlib.sha256(canonical).hexdigest(), "files": files}


def verify() -> dict[str, Any]:
    captured_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    baseline = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    checks: list[dict[str, Any]] = []
    for rel, expected in baseline["protected_paths"].items():
        path = ROOT / rel
        if not expected.get("exists"):
            checks.append({"path": rel, "pass": not path.exists(), "kind": "absence"})
            continue
        if not path.exists():
            checks.append({"path": rel, "pass": False, "kind": "missing"})
            continue
        if path.is_dir():
            actual = _tree(path)
            passed = (actual["file_count"] == expected["file_count"]
                      and actual["total_bytes"] == expected["total_bytes"]
                      and actual["tree_sha256"] == expected["tree_sha256"]
                      and actual["files"] == expected["files"])
            checks.append({"path": rel, "pass": passed, "kind": "tree",
                           "expected_tree_sha256": expected["tree_sha256"],
                           "actual_tree_sha256": actual["tree_sha256"],
                           "expected_file_count": expected["file_count"],
                           "actual_file_count": actual["file_count"]})
        else:
            actual_hash = _sha256(path)
            passed = path.stat().st_size == expected["bytes"] and actual_hash == expected["sha256"]
            checks.append({"path": rel, "pass": passed, "kind": "file",
                           "expected_sha256": expected["sha256"], "actual_sha256": actual_hash,
                           "expected_bytes": expected["bytes"], "actual_bytes": path.stat().st_size})
    for archive in baseline.get("audit_archives", []):
        path = ROOT / archive["path"]
        actual_hash = _sha256(path) if path.is_file() else "MISSING"
        checks.append({"path": archive["path"], "pass": path.is_file()
                       and path.stat().st_size == archive["bytes"]
                       and actual_hash == archive["sha256"],
                       "kind": "audit_zip", "expected_sha256": archive["sha256"],
                       "actual_sha256": actual_hash,
                       "expected_bytes": archive["bytes"],
                       "actual_bytes": path.stat().st_size if path.is_file() else None})
    try:
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.SubprocessError):
        head = "UNKNOWN"
    checks.append({"path": "git/HEAD", "pass": head == baseline["git"]["commit"],
                   "kind": "git_commit", "expected": baseline["git"]["commit"], "actual": head})
    failures = [check for check in checks if not check["pass"]]
    return {"schema": "g4.baseline_verification/1", "checked_at_utc": captured_at,
            "result": "PASS" if not failures else "FAIL", "check_count": len(checks),
            "failure_count": len(failures), "checks": checks, "failures": failures,
            "preexisting_git_status_line_count": len(baseline["git"]["status_porcelain_v1_before_g4"])}


def main() -> int:
    result = verify()
    out_json = ROOT / "docs/g4/G4_BASELINE_VERIFICATION.json"
    out_md = ROOT / "docs/g4/G4_BASELINE_VERIFICATION.md"
    out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# G4 baseline verification", "", f"**Result**: `{result['result']}`",
             f"**Checked at (UTC)**: {result['checked_at_utc']}",
             f"**Checks**: {result['check_count']} · **Failures**: {result['failure_count']}",
             "", "| Scope | Check | Expected | Actual |", "|---|---|---|---|"]
    for check in result["checks"]:
        expected = check.get("expected_tree_sha256") or check.get("expected_sha256") or check.get("expected", "—")
        actual = check.get("actual_tree_sha256") or check.get("actual_sha256") or check.get("actual", "—")
        lines.append(f"| `{check['path']}` | {'PASS' if check['pass'] else 'FAIL'} | `{expected}` | `{actual}` |")
    lines += ["", "The check re-hashes protected G0/G1/G2/G3 run trees, G2/G3 docs/configs/test records, the original source PDF, and every pre-existing audit ZIP. It does not require the current Git working tree to be clean; the 67 pre-existing status lines are preserved as the takeover snapshot.", ""]
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"result": result["result"], "checks": result["check_count"],
                      "failures": result["failure_count"], "report": str(out_md)}, ensure_ascii=False))
    return 0 if result["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
