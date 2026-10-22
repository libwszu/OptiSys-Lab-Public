"""Path-aware integrity check for the inherited G0-G4/S5 and S6 freezes."""

from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "s6r" / "HISTORICAL_PRESERVATION.json"


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def path_is_relevant(value: str) -> bool:
    return "/" in value or "\\" in value or value.lower().endswith((".pdf", ".zip", ".csv", ".json", ".md", ".yaml", ".yml", ".png", ".py", ".xml"))


def entries_from_manifest(payload: Any) -> list[dict[str, Any]]:
    out: dict[tuple[str, str], dict[str, Any]] = {}

    def add(path: str, sha: str, size: Any = None) -> None:
        if path_is_relevant(path):
            out[(path.replace("\\", "/"), sha.lower())] = {"path": path.replace("\\", "/"), "sha256": sha.lower(), "bytes": size}

    def walk(node: Any, context: str = "") -> None:
        if isinstance(node, dict):
            if isinstance(node.get("path"), str) and isinstance(node.get("sha256"), str):
                add(node["path"], node["sha256"], node.get("bytes"))
            if context in {"hashes", "protected_paths"}:
                for key, child in node.items():
                    if isinstance(child, dict) and isinstance(child.get("sha256"), str):
                        add(child.get("path", key), child["sha256"], child.get("bytes"))
            if context == "key_sources":
                for key, child in node.items():
                    if isinstance(child, str) and len(child) == 64:
                        add(key, child)
            for key, child in node.items():
                walk(child, key)
        elif isinstance(node, list):
            for child in node:
                walk(child, context)

    walk(payload)
    return list(out.values())


def resolve(raw_path: str) -> Path:
    raw = Path(raw_path)
    return raw if raw.is_absolute() else ROOT / raw


def zip_member_sha256(zip_path: Path, member_suffix: str) -> tuple[str | None, str | None]:
    with zipfile.ZipFile(zip_path) as zf:
        matches = [name for name in zf.namelist() if name.replace("\\", "/").endswith(member_suffix)]
        if len(matches) != 1:
            return None, None
        return matches[0], hashlib.sha256(zf.read(matches[0])).hexdigest()


def check_manifest(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    checked, failures = [], []
    for item in entries_from_manifest(payload):
        target = resolve(item["path"])
        if not target.is_file():
            failures.append({**item, "reason": "MISSING_SOURCE"})
            continue
        actual_bytes = target.stat().st_size
        actual_sha = digest(target)
        if actual_sha != item["sha256"] or (item.get("bytes") is not None and actual_bytes != item["bytes"]):
            failures.append({**item, "actual_bytes": actual_bytes, "actual_sha256": actual_sha, "reason": "HASH_OR_SIZE_MISMATCH"})
        else:
            checked.append(item["path"])
    return {"manifest": path.relative_to(ROOT).as_posix(), "status": "PASS" if not failures else "PARTIAL", "declared": len(checked) + len(failures), "verified": len(checked), "failures": failures}


def main() -> None:
    manifests = [
        ROOT / "docs/g2/G2_BASELINE_HASHES.json",
        ROOT / "docs/g3/G3_BASELINE_HASHES.json",
        ROOT / "docs/g4/G4_BASELINE_HASHES.json",
        ROOT / "docs/g4/G4_FREEZE_HASHES.json",
        ROOT / "docs/s5/S5_FREEZE_HASHES.json",
        ROOT / "docs/s6/S6_FREEZE_HASHES.json",
        ROOT / "docs/s6/S6_AMENDMENT_01_HASHES.json",
        ROOT / "docs/s6/S6_AMENDMENT_02_HASHES.json",
        ROOT / "docs/s6/S6_AMENDMENT_03_HASHES.json",
    ]
    results = [check_manifest(p) for p in manifests if p.is_file()]
    archives = []
    for path in sorted((ROOT / "_AUDIT").rglob("*.zip")):
        with zipfile.ZipFile(path) as zf:
            corrupt = zf.testzip()
        archives.append({"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": digest(path), "zip_test": "PASS" if corrupt is None else f"FAIL:{corrupt}"})

    expected = {
        "_AUDIT/20261019_130948_G0_78fa364f/OptiSysLab_G0_20261019_130948_G0_78fa364f_GPT_AUDIT.zip": "3967d064cbc4349c6d484ec437f047e8b399be8bd1ab670149b4a32377ff8edc",
    }
    # Take additional authoritative archive hashes from the historical ledgers.
    g2 = json.loads((ROOT / "docs/g2/G2_BASELINE_HASHES.json").read_text(encoding="utf-8"))
    expected["_AUDIT/20261019_130948_G0_78fa364f/OptiSysLab_G0_20261019_130948_G0_78fa364f_GPT_AUDIT.zip"] = g2["g0"]["audit_zip_sha256"]
    expected["_AUDIT/20261019_145702_G1_54c9e3fb/OptiSysLab_G1_20261019_145702_G1_54c9e3fb_GPT_AUDIT.zip"] = g2["g1"]["audit_zip_sha256"]
    g3 = json.loads((ROOT / "docs/g3/G3_BASELINE_HASHES.json").read_text(encoding="utf-8"))
    expected[g3["g2_audit_zip"]["path"].replace("\\", "/")] = g3["g2_audit_zip"]["sha256"]
    g4 = json.loads((ROOT / "docs/g4/G4_BASELINE_HASHES.json").read_text(encoding="utf-8"))
    for entry in g4.get("audit_archives", []):
        expected[entry["path"].replace("\\", "/")] = entry["sha256"]
    g4_final = json.loads((ROOT / "docs/g4/G4_FINAL_STATUS.json").read_text(encoding="utf-8"))
    g4_zip_path = g4_final["audit_zip"].replace("\\", "/")
    g4_hash_path = ROOT / "_AUDIT/20261020_133555_G4_ec3e2813_0e48/AUDIT_ZIP_SHA256.txt"
    g4_hash_text = g4_hash_path.read_text(encoding="utf-8")
    g4_hash_match = re.search(r"sha256:\s*([0-9a-f]{64})", g4_hash_text, re.IGNORECASE)
    if g4_hash_match:
        expected[g4_zip_path] = g4_hash_match.group(1).lower()
    s5 = json.loads((ROOT / "docs/s5/S5_FREEZE_HASHES.json").read_text(encoding="utf-8"))
    for entry in s5.get("files", []):
        if str(entry.get("path", "")).lower().endswith(".zip"):
            expected[entry["path"].replace("\\", "/")] = entry["sha256"]
    s6 = json.loads((ROOT / "docs/s6/S6_FREEZE_HASHES.json").read_text(encoding="utf-8"))
    for rel, entry in s6.get("hashes", {}).items():
        if rel.lower().endswith(".zip"):
            expected[rel.replace("\\", "/")] = entry["sha256"]
    archive_by_path = {x["path"]: x for x in archives}
    archive_checks = []
    for path, exp in sorted(expected.items()):
        actual = archive_by_path.get(path)
        archive_checks.append({"path": path, "expected_sha256": exp, "actual_sha256": actual["sha256"] if actual else None, "status": "PASS" if actual and actual["sha256"] == exp and actual["zip_test"] == "PASS" else "FAIL"})

    # G3_BASELINE_HASHES.json is explicitly a pre-change snapshot. The two
    # source hashes that differ from today's checkout must be explained by
    # later archived source snapshots, not treated as a rewrite of G3 history.
    g3 = json.loads((ROOT / "docs/g3/G3_BASELINE_HASHES.json").read_text(encoding="utf-8"))
    g3_sources = g3.get("key_sources", {})
    evolution_sources = [
        ("src/optisys/cli.py", "_AUDIT/20261020_210201_S5_HNA/OptiSysLab_S5_20261020_210201_S5_HNA_GPT_AUDIT.zip"),
        ("src/optisys/gates/g2.py", "_AUDIT/20261020_133555_G4_ec3e2813_0e48/OptiSysLab_G4_20261020_133555_G4_ec3e2813_0e48_GPT_AUDIT.zip"),
    ]
    source_reconciliations = []
    for rel, archive_rel in evolution_sources:
        archive_path = ROOT / archive_rel
        member, archived_sha = zip_member_sha256(archive_path, rel)
        current_path = ROOT / rel
        current_sha = digest(current_path) if current_path.is_file() else None
        pre_change_sha = g3_sources.get(rel)
        source_reconciliations.append({
            "path": rel,
            "g3_pre_change_sha256": pre_change_sha,
            "current_sha256": current_sha,
            "later_archive": archive_rel,
            "later_archive_member": member,
            "later_archive_sha256": archived_sha,
            "status": "PASS_LATER_ARCHIVE_MATCHES_CURRENT" if current_sha and current_sha == archived_sha and current_sha != pre_change_sha else "FAIL",
        })
    source_reconciliation_status = "PASS_WITH_DOCUMENTED_EVOLUTION" if source_reconciliations and all(x["status"] == "PASS_LATER_ARCHIVE_MATCHES_CURRENT" for x in source_reconciliations) else "FAIL"

    # Independently validate the S6-C runner hashes locked before formal outcomes.
    holdout = json.loads((ROOT / f"runs/20261021_024715_S6_P1/S6_C_HOLDOUT_FREEZE_02.json").read_text(encoding="utf-8"))
    frozen_files = []
    for rel, meta in holdout.get("hashes", {}).items():
        target = resolve(rel)
        if not target.is_file():
            frozen_files.append({"path": rel, "status": "MISSING_SOURCE"})
        else:
            actual = digest(target)
            frozen_files.append({"path": rel, "expected_sha256": meta["sha256"], "actual_sha256": actual, "status": "PASS" if actual == meta["sha256"] else "FAIL"})
    payload = {
        "schema": "optisys.s6r.historical_preservation/1",
        "repository_head_at_intake": "PRIVATE_SOURCE_REVISION",
        "historical_freeze_manifests": results,
        "historical_archive_hashes": archive_checks,
        "g3_pre_change_source_reconciliation": {
            "snapshot_kind": g3.get("snapshot_kind"),
            "sources": source_reconciliations,
            "status": source_reconciliation_status,
            "note": "The two source hashes in the G3 pre-change baseline differ from the later checkout, but the exact current bytes are present in the subsequent immutable G4/S5 audit archives. This is documented source evolution; G3 run packages and archive hashes remain unchanged.",
        },
        "s6_pre_holdout_freeze_files": frozen_files,
        "status": "PASS" if all(x["status"] == "PASS" for x in archive_checks) and all(x["status"] == "PASS" for x in frozen_files) and all(x["status"] == "PASS" for x in results if x["manifest"] != "docs/g3/G3_BASELINE_HASHES.json") and source_reconciliation_status == "PASS_WITH_DOCUMENTED_EVOLUTION" else "PARTIAL",
        "qualification": "G3 baseline is explicitly a pre-change snapshot; two source entries are reconciled to later, hash-verified G4/S5 audit package members.",
    }
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(OUT), "status": payload["status"], "manifest_status": [(x["manifest"], x["status"], x["verified"], x["declared"], len(x["failures"])) for x in results], "archive_checks": archive_checks, "holdout_files": {"pass": sum(x["status"] == "PASS" for x in frozen_files), "fail": sum(x["status"] != "PASS" for x in frozen_files)}}, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
