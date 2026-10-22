"""Verify a G3 audit ZIP: integrity, manifest, extraction, reproduction.

Checks, in order:

1. ``zipfile.testzip()`` reports no corrupt member;
2. no path traversal / absolute path / duplicate member name;
3. every manifest entry exists, has the recorded size and SHA-256;
4. ``SHA256SUMS.txt`` agrees with the manifest, and the manifest covers every
   member of the archive (a file shipped without a checksum is unverifiable);
5. the required entry documents are present;
6. the ZIP is extracted into a *fresh* directory outside the project and the
   reproduction script is executed **from the extracted copy**, so the test
   cannot accidentally read the live workspace;
7. the ZIP's own SHA-256 is reported for transcription outside the package.

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
from pathlib import Path, PurePosixPath

REQUIRED = [
    "00_START_HERE.md",
    "01_EXECUTIVE_SUMMARY.md",
    "02_SPEC_TRACEABILITY.md",
    "03_SCIENTIFIC_AUDIT.md",
    "04_VALIDATION_MATRIX.md",
    "05_COMPUTE_AND_PERFORMANCE.md",
    "06_REPRODUCTION_GUIDE.md",
    "07_KNOWN_ISSUES_AND_FAILURES.md",
    "08_NEXT_GATE_PLAN.md",
    "GPT_REVIEW_INSTRUCTIONS.md",
    "manifest.json",
    "SHA256SUMS.txt",
]

#: Members that must carry the G3 science verdict and its boundary documents.
SCIENCE_REQUIRED = [
    "g3/G2_INHERITANCE_VERDICT.json",
    "g3/G2_INHERITANCE_SCIENTIFIC_AUDIT.md",
    "g3/G3_FINAL_STATUS.json",
    "g3/G3_VALIDATION_MATRIX.md",
    "g3/DEMO_SCRIPT_5MIN.md",
    "g3/RESUME_CLAIMS_AND_LIMITS.md",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def is_safe_member(name: str) -> bool:
    """True only for a relative, normalised archive member name.

    Rejects, in order:

    * an empty name;
    * an absolute POSIX path (``/etc/passwd``);
    * a Windows drive or UNC path (``C:/...``, ``\\\\server\\share``);
    * any ``..`` component, which resolves outside the extraction root;
    * a backslash used as a separator, because ``zipfile`` normalises with ``/``
      and a member written as ``a\\..\\..\\b`` would slip past a ``/``-only check.

    The function is deliberately pure and total: it never touches the
    filesystem, so it can be unit-tested with hostile names that do not exist.
    """

    if not name or not name.strip():
        return False
    # a backslash anywhere means the archive was built by a tool that thinks in
    # Windows separators; refuse it rather than guess how it would be extracted
    if "\\" in name:
        return False
    if name.startswith("/"):
        return False
    # drive letter or UNC-style prefix
    if len(name) >= 2 and name[1] == ":":
        return False
    parts = PurePosixPath(name).parts
    if any(part == ".." for part in parts):
        return False
    if any(part == "" for part in parts):
        return False
    return True


def reproducibility_findings(archive_path: Path) -> list[str]:
    """Check the two properties that make a rebuild comparison meaningful.

    The claim "rebuild and compare the SHA-256" is only true if the archive is a
    function of its contents.  It was not, until this round: ``archive.write``
    stamped each member with its source mtime, and ``manifest.json`` carried a
    wall-clock ``created_at_utc``, so two builds of identical evidence produced
    different hashes (measured: 209 members / 732722 bytes both times, differing
    sha256).  Both are now pinned.  Two things are checked here:

    1. every member carries the same fixed timestamp, so no build clock leaks in;
    2. re-zipping the members in their shipped order with that timestamp
       reproduces the archive byte for byte - i.e. nothing volatile remains.

    Point 2 uses the shipped order rather than a re-sort on purpose: the order
    itself is part of the artefact, so re-sorting would test a different file.
    """

    findings: list[str] = []
    with zipfile.ZipFile(archive_path) as archive:
        infos = [i for i in archive.infolist() if not i.is_dir()]
        members = [(info.filename, archive.read(info.filename), info.date_time)
                   for info in infos]

    stamps = {stamp for _, _, stamp in members}
    if len(stamps) > 1:
        findings.append(
            f"members carry {len(stamps)} different timestamps; a build-time clock "
            "is being recorded, so the archive is not a pure function of its content")

    with tempfile.TemporaryDirectory() as tmp:
        rebuilt = Path(tmp) / "rebuilt.zip"
        fixed = (1980, 1, 1, 0, 0, 0)
        with zipfile.ZipFile(rebuilt, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as out:
            for name, data, _ in members:
                info = zipfile.ZipInfo(filename=name, date_time=fixed)
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o600 << 16
                info.create_system = 0
                out.writestr(info, data)
        if sha256_file(rebuilt) != sha256_file(archive_path):
            findings.append(
                "the archive is not byte-for-byte reproducible from its own "
                "members in their shipped order: a timestamp, an extra field or "
                "the ordering is still injected at build time, so 'rebuild and "
                "compare the hash' cannot be used as a reproduction check")
    return findings


def verify_zip(archive_path: Path, *, skip_repro: bool = False,
               repro_name: str = "repro/verify_g3.py") -> tuple[list[str], int]:
    """Return ``(failures, exit_code)``.  Never raises on a bad archive."""

    failures: list[str] = []
    archive_path = archive_path.resolve()

    if not archive_path.is_file():
        return [f"archive not found: {archive_path}"], 1

    try:
        archive = zipfile.ZipFile(archive_path)
    except zipfile.BadZipFile as exc:
        return [f"not a zip file: {exc}"], 1

    with archive:
        bad = archive.testzip()
        if bad is not None:
            failures.append(f"corrupt member: {bad}")

        names = archive.namelist()
        if len(names) != len(set(names)):
            duplicates = sorted({n for n in names if names.count(n) > 1})
            failures.append(f"duplicate member names: {duplicates[:5]}")

        unsafe = [name for name in names if not is_safe_member(name)]
        if unsafe:
            failures.append(f"unsafe member names: {unsafe[:5]}")

        missing = [name for name in REQUIRED if name not in names]
        if missing:
            failures.append(f"missing documents: {missing}")

        missing_science = [name for name in SCIENCE_REQUIRED if name not in names]
        if missing_science:
            failures.append(f"missing G3 science evidence: {missing_science}")

        # A rebuild from the members must reproduce the archive byte for byte.
        try:
            failures.extend(reproducibility_findings(archive_path))
        except Exception as exc:  # noqa: BLE001 - a failed check is a finding
            failures.append(f"reproducibility check crashed: {type(exc).__name__}: {exc}")

        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "pkg"
            archive.extractall(target)

            # extraction must stay inside the target
            resolved_target = target.resolve()
            for path in resolved_target.rglob("*"):
                try:
                    path.resolve().relative_to(resolved_target)
                except ValueError:
                    failures.append(f"member escaped the extraction root: {path}")
                    break

            manifest_path = target / "manifest.json"
            if not manifest_path.is_file():
                failures.append("manifest.json missing")
            else:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                entries = manifest.get("files", [])
                listed_paths = set()
                for entry in entries:
                    rel = entry["path"]
                    listed_paths.add(rel)
                    path = target / rel
                    if not path.is_file():
                        failures.append(f"manifest entry missing: {rel}")
                        continue
                    if path.stat().st_size != entry["bytes"]:
                        failures.append(
                            f"size mismatch: {rel} "
                            f"({path.stat().st_size} != {entry['bytes']})")
                    actual = sha256_file(path)
                    if actual != entry["sha256"]:
                        failures.append(f"sha256 mismatch: {rel}")

                # every shipped member must be covered by the manifest
                unlisted = sorted(
                    name for name in names
                    if name not in listed_paths
                    and name not in ("manifest.json", "SHA256SUMS.txt")
                    and not name.endswith("/")
                )
                if unlisted:
                    failures.append(f"members with no manifest entry: {unlisted[:5]}")

                sums = target / "SHA256SUMS.txt"
                if not sums.is_file():
                    failures.append("SHA256SUMS.txt missing")
                else:
                    listed: dict[str, str] = {}
                    for line in sums.read_text(encoding="utf-8").splitlines():
                        if not line.strip():
                            continue
                        digest, _, name = line.partition("  ")
                        listed[name] = digest
                    for entry in entries:
                        if listed.get(entry["path"]) != entry["sha256"]:
                            failures.append(
                                f"SHA256SUMS disagreement: {entry['path']}")

            repro = target / repro_name
            if not repro.is_file():
                failures.append(f"{repro_name} missing")
            elif not skip_repro:
                result = subprocess.run(
                    [sys.executable, str(repro)], cwd=str(target),
                    capture_output=True, text=True, timeout=1800,
                )
                print("--- repro stdout ---")
                print(result.stdout.strip())
                if result.stderr.strip():
                    print("--- repro stderr ---")
                    print(result.stderr.strip())
                if result.returncode == 2:
                    return failures, 2
                if result.returncode != 0 or "REPRO_STATUS: PASS" not in result.stdout:
                    failures.append(f"repro failed (exit {result.returncode})")

    return failures, 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="verify a G3 audit ZIP")
    parser.add_argument("zip", type=Path)
    parser.add_argument("--skip-repro", action="store_true",
                        help="skip executing the extracted reproduction script")
    args = parser.parse_args(argv)

    archive_path = args.zip.resolve()
    failures, code = verify_zip(archive_path, skip_repro=args.skip_repro)
    if code == 2:
        print("\nAUDIT_VERIFY: DEPENDENCY_UNAVAILABLE")
        for item in failures:
            print(f"  - {item}")
        return 2

    if failures:
        print("\nAUDIT_VERIFY: FAIL")
        for item in failures:
            print(f"  - {item}")
        return 1

    print("\nAUDIT_VERIFY: PASS")
    print(f"  zip sha256: {sha256_file(archive_path)}")
    print(f"  bytes: {archive_path.stat().st_size}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())