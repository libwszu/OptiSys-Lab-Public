"""Compare the protected S6 run and docs trees against the S6-R intake hashes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "docs" / "s6r" / "BASELINE_HASHES.json"
OUT = ROOT / "docs" / "s6r" / "S6R_BASELINE_PRESERVATION.json"


def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def inspect_tree(rel: str, expected: dict) -> dict:
    base = ROOT / rel
    actual_rows = []
    for p in sorted((x for x in base.rglob("*") if x.is_file()), key=lambda x: x.relative_to(ROOT).as_posix()):
        actual_rows.append({"path": p.relative_to(ROOT).as_posix(), "bytes": p.stat().st_size, "sha256": hash_file(p)})
    expected_rows = expected.get("files", [])
    expected_by_path = {x["path"]: x for x in expected_rows}
    actual_by_path = {x["path"]: x for x in actual_rows}
    changed = []
    for path in sorted(set(expected_by_path) & set(actual_by_path)):
        if expected_by_path[path] != actual_by_path[path]:
            changed.append({"path": path, "expected": expected_by_path[path], "actual": actual_by_path[path]})
    missing = sorted(set(expected_by_path) - set(actual_by_path))
    added = sorted(set(actual_by_path) - set(expected_by_path))
    h = hashlib.sha256()
    for row in actual_rows:
        h.update(row["path"].encode("utf-8"))
        h.update(b"\0")
        h.update(str(row["bytes"]).encode("ascii"))
        h.update(b"\0")
        h.update(row["sha256"].encode("ascii"))
        h.update(b"\n")
    tree_hash = h.hexdigest()
    okay = not changed and not missing and not added and tree_hash == expected.get("tree_sha256")
    return {"path": rel, "status": "PASS" if okay else "FAIL", "expected_file_count": expected.get("file_count"), "actual_file_count": len(actual_rows), "expected_bytes": expected.get("bytes"), "actual_bytes": sum(x["bytes"] for x in actual_rows), "expected_tree_sha256": expected.get("tree_sha256"), "actual_tree_sha256": tree_hash, "changed": changed, "missing": missing, "added": added}


def main() -> int:
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))
    protected = ["runs/20261021_024715_S6_P1", "docs/s6"]
    results = [inspect_tree(path, baseline["immutable_trees"][path]) for path in protected]
    release = inspect_tree("RELEASE_CANDIDATE_V2", baseline["immutable_trees"]["RELEASE_CANDIDATE_V2"])
    result = {
        "schema": "optisys.s6r.baseline_preservation/1",
        "intake_head": baseline["repository"]["head"],
        "protected_science_trees": results,
        "S6_ORIGINAL_SCIENCE_TREE_UNCHANGED": "YES" if all(x["status"] == "PASS" for x in results) else "NO",
        "release_draft_tree_at_intake": {"status": release["status"], "initial_tree_sha256": release["expected_tree_sha256"], "current_tree_sha256": release["actual_tree_sha256"], "change_reason": "R0 documented corrections to README, checklist, S6 evidence index, and release manifest; original intake hashes remain above."},
        "status": "PASS" if all(x["status"] == "PASS" for x in results) else "FAIL",
    }
    OUT.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
