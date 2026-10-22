"""Verify the raw checkout bytes of the six preregistered G4 inputs.

Uses only the Python standard library. Never normalizes or rewrites input files.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

INPUTS = frozenset({
    "docs/g4/G4_PRE_REGISTRATION.md",
    "docs/g4/G4_ACCEPTANCE_CRITERIA.md",
    "docs/g4/G4_COMPUTE_BUDGET.md",
    "configs/pump976_g4_l0.yaml",
    "configs/pump976_g4_l1.yaml",
    "configs/pump976_g4_tolerance.yaml",
})


def verify(root: Path) -> dict:
    rows = []
    errors = []
    try:
        manifest = json.loads((root / "docs/g4/G4_FREEZE_HASHES.json").read_bytes())
        inputs = manifest["inputs"]
        if len(inputs) != 6 or {entry["path"] for entry in inputs} != INPUTS:
            raise ValueError("manifest must list exactly the six registered G4 inputs")
        for entry in inputs:
            row = {"path": entry["path"], "expected_bytes": entry["bytes"],
                   "expected_sha256": entry["sha256"]}
            try:
                data = (root / entry["path"]).read_bytes()
                row.update(bytes=len(data), sha256=hashlib.sha256(data).hexdigest(),
                           crlf_count=data.count(b"\r\n"))
                row["status"] = ("PASS" if row["bytes"] == entry["bytes"]
                                 and row["sha256"] == entry["sha256"] else "FAIL")
            except OSError as exc:
                row.update(status="FAIL", error=type(exc).__name__)
            rows.append(row)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        errors.append(str(exc))
    return {"schema": "optisys.published_frozen_inputs/1",
            "status": "PASS" if not errors and len(rows) == 6
                      and all(row["status"] == "PASS" for row in rows) else "FAIL",
            "hash_basis": "raw_worktree_bytes", "files": rows, "errors": errors}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path, help="Optional JSON report path")
    args = parser.parse_args()
    result = verify(args.root)
    report = json.dumps(result, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    print(report, end="")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
