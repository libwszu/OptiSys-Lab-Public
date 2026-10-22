"""Verify the integrity of an unpacked audit package.

Usage (from the package root):
    python scripts/verify_audit_package.py
    python scripts/verify_audit_package.py <package-root>

Checks:
1. every entry in ``SHA256SUMS.txt`` exists and matches;
2. every file listed in ``manifest.json`` exists with the stated size and hash;
3. no path escapes the package root.

Exit code 0 = all checks pass.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    root = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else Path.cwd()
    problems: list[str] = []

    sums_path = root / "SHA256SUMS.txt"
    if not sums_path.is_file():
        print(f"ERROR: missing {sums_path}")
        return 2
    entries = 0
    for line in sums_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, rel = line.split("  ", 1)
        target = (root / rel).resolve()
        if not str(target).startswith(str(root)):
            problems.append(f"unsafe path: {rel}")
            continue
        if not target.is_file():
            problems.append(f"missing: {rel}")
            continue
        if sha256_file(target) != digest:
            problems.append(f"sha256 mismatch: {rel}")
        entries += 1

    manifest_path = root / "manifest.json"
    manifest_files = 0
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for item in manifest.get("files", []):
            target = root / item["path"]
            manifest_files += 1
            if not target.is_file():
                problems.append(f"manifest file missing: {item['path']}")
            elif target.stat().st_size != item["bytes"]:
                problems.append(f"manifest size mismatch: {item['path']}")
            elif sha256_file(target) != item["sha256"]:
                problems.append(f"manifest hash mismatch: {item['path']}")
    else:
        problems.append("missing: manifest.json")

    print(f"package root        : {root}")
    print(f"SHA256SUMS entries  : {entries}")
    print(f"manifest files      : {manifest_files}")
    print(f"problems            : {len(problems)}")
    for problem in problems:
        print(f"  - {problem}")
    print("VERIFY_STATUS       :", "PASS" if not problems else "FAIL")
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
