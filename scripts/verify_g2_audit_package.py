"""Verify a G2 audit ZIP: integrity, manifest, extraction and reproduction.

Checks, in order:

1. `zipfile.testzip()` reports no corrupt member;
2. no path traversal / absolute path / duplicate name;
3. every manifest entry exists, has the recorded size and SHA-256;
4. `SHA256SUMS.txt` agrees with the manifest;
5. required entry documents are present;
6. the ZIP is extracted into a fresh directory and `repro/verify_g2.py` is
   executed **from the extracted copy**.

Exit codes: 0 PASS, 1 FAIL, 2 DEPENDENCY_UNAVAILABLE.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REQUIRED = [
    "00_START_HERE.md", "01_EXECUTIVE_SUMMARY.md", "02_SPEC_TRACEABILITY.md",
    "03_SCIENTIFIC_AUDIT.md", "04_VALIDATION_MATRIX.md", "05_COMPUTE_AND_PERFORMANCE.md",
    "06_REPRODUCTION_GUIDE.md", "07_KNOWN_ISSUES_AND_FAILURES.md", "08_NEXT_GATE_PLAN.md",
    "GPT_REVIEW_INSTRUCTIONS.md", "manifest.json", "SHA256SUMS.txt",
]


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("zip", type=Path)
    parser.add_argument("--skip-repro", action="store_true")
    args = parser.parse_args()

    archive_path = args.zip.resolve()
    failures: list[str] = []

    with zipfile.ZipFile(archive_path) as archive:
        bad = archive.testzip()
        if bad is not None:
            failures.append(f"corrupt member: {bad}")
        names = archive.namelist()
        if len(names) != len(set(names)):
            failures.append("duplicate member names")
        for name in names:
            parts = Path(name).parts
            if name.startswith("/") or ".." in parts or (parts and ":" in parts[0]):
                failures.append(f"path traversal: {name}")
        missing = [name for name in REQUIRED if name not in names]
        if missing:
            failures.append(f"missing documents: {missing}")

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "pkg"
            archive.extractall(target)

            manifest_path = target / "manifest.json"
            if manifest_path.is_file():
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                for entry in manifest["files"]:
                    path = target / entry["path"]
                    if not path.is_file():
                        failures.append(f"manifest entry missing: {entry['path']}")
                        continue
                    if path.stat().st_size != entry["bytes"]:
                        failures.append(f"size mismatch: {entry['path']}")
                    if _sha(path) != entry["sha256"]:
                        failures.append(f"sha256 mismatch: {entry['path']}")
                sums = target / "SHA256SUMS.txt"
                if sums.is_file():
                    listed = {}
                    for line in sums.read_text(encoding="utf-8").splitlines():
                        if not line.strip():
                            continue
                        digest, name = line.split("  ", 1)
                        listed[name] = digest
                    for entry in manifest["files"]:
                        if listed.get(entry["path"]) != entry["sha256"]:
                            failures.append(f"SHA256SUMS disagreement: {entry['path']}")
                else:
                    failures.append("SHA256SUMS.txt missing")
            else:
                failures.append("manifest.json missing")

            repro = target / "repro" / "verify_g2.py"
            if not repro.is_file():
                failures.append("repro/verify_g2.py missing")
            elif not args.skip_repro:
                result = subprocess.run(
                    [sys.executable, str(repro)], cwd=str(target),
                    capture_output=True, text=True, timeout=1800,
                )
                print("--- repro stdout ---")
                print(result.stdout.strip())
                if result.returncode == 2:
                    print("REPRO: DEPENDENCY_UNAVAILABLE")
                    return 2
                if result.returncode != 0 or "REPRO_STATUS: PASS" not in result.stdout:
                    failures.append(f"repro failed (exit {result.returncode})")

    if failures:
        print("\nAUDIT_VERIFY: FAIL")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("\nAUDIT_VERIFY: PASS")
    print(f"  zip sha256: {_sha(archive_path)}")
    print(f"  bytes: {archive_path.stat().st_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
