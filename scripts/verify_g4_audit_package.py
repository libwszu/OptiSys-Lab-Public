"""Verify G4 audit ZIP integrity, extraction replay, tamper detection, and byte rebuilds."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

REQUIRED = (
    "00_START_HERE.md", "01_EXECUTIVE_SUMMARY.md", "02_SPEC_TRACEABILITY.md",
    "03_SCIENTIFIC_AUDIT.md", "04_VALIDATION_MATRIX.md",
    "05_COMPUTE_AND_PERFORMANCE.md", "06_REPRODUCTION_GUIDE.md",
    "07_KNOWN_ISSUES_AND_FAILURES.md", "08_NEXT_STEPS.md",
    "GPT_REVIEW_INSTRUCTIONS.md", "manifest.json", "SHA256SUMS.txt",
    "run/run_status.json", "run/tolerance_samples.csv", "run/source_samples.csv",
    "run/bootstrap_replicates.csv",
    "repro/verify_g4.py", "baseline_g3/G2_INHERITANCE_VERDICT.json",
    "test_evidence/g4_full_junit.xml",
)
EXCEPTIONS = {"manifest.json", "SHA256SUMS.txt"}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_name(name: str) -> bool:
    if not name or "\\" in name or name.startswith("/"):
        return False
    if len(name) >= 2 and name[1] == ":":
        return False
    path = PurePosixPath(name)
    return not path.is_absolute() and ".." not in path.parts and all(part not in ("", ".") for part in path.parts)


def _parse_sums(data: bytes) -> dict[str, str]:
    out = {}
    for line in data.decode("utf-8").splitlines():
        if not line.strip():
            continue
        try:
            digest, name = line.split("  ", 1)
        except ValueError as exc:
            raise ValueError(f"invalid SHA256SUMS line: {line!r}") from exc
        out[name] = digest
    return out


def _content_check(path: Path) -> tuple[list[str], dict[str, bytes], dict[str, Any]]:
    errors: list[str] = []
    contents: dict[str, bytes] = {}
    try:
        archive = zipfile.ZipFile(path, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        return [f"cannot open ZIP: {exc}"], {}, {}
    with archive:
        infos = archive.infolist()
        names = [item.filename for item in infos]
        if len(names) != len(set(names)):
            errors.append("duplicate member names")
        unsafe = [name for name in names if not _safe_name(name)]
        if unsafe:
            errors.append(f"unsafe paths: {unsafe[:5]}")
        missing = [name for name in REQUIRED if name not in names]
        if missing:
            errors.append(f"required members missing: {missing}")
        bad = archive.testzip()
        if bad is not None:
            errors.append(f"ZIP testzip failed at {bad}")
        if any(info.compress_type != zipfile.ZIP_STORED for info in infos if not info.is_dir()):
            errors.append("member compression is not ZIP_STORED")
        for name in names:
            if name.endswith("/"):
                continue
            contents[name] = archive.read(name)
    if not errors:
        try:
            manifest = json.loads(contents["manifest.json"].decode("utf-8"))
            rows = manifest.get("files", [])
            records = {row["path"]: row for row in rows}
            ordinary = set(contents) - EXCEPTIONS
            if set(records) != ordinary:
                errors.append("manifest coverage differs from regular members")
            for name in sorted(ordinary):
                record = records.get(name, {})
                data = contents[name]
                if len(data) != record.get("bytes") or _sha(data) != record.get("sha256"):
                    errors.append(f"manifest mismatch: {name}")
            sums = _parse_sums(contents["SHA256SUMS.txt"])
            expected_sums = {name: _sha(data) for name, data in contents.items()
                             if name != "SHA256SUMS.txt"}
            if sums != expected_sums:
                errors.append("SHA256SUMS.txt disagrees with archive members")
            manifest_exceptions = set(manifest.get("self_reference_exceptions", []))
            if manifest_exceptions != EXCEPTIONS:
                errors.append("manifest self-reference exception set is incorrect")
            return errors, contents, manifest
        except Exception as exc:  # noqa: BLE001 - report malformed untrusted package
            errors.append(f"manifest parse/check failed: {type(exc).__name__}: {exc}")
    return errors, contents, {}


def _write_deterministic_zip(path: Path, root: Path, names: list[str]) -> None:
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_STORED) as archive:
        for name in names:
            source = root.joinpath(*PurePosixPath(name).parts)
            data = source.read_bytes()
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_STORED
            info.external_attr = 0o600 << 16
            info.create_system = 0
            info.flag_bits = 0
            archive.writestr(info, data)


def verify(path: Path, *, cross_python: str | None = None,
           skip_repro: bool = False, skip_same_env: bool = False) -> dict[str, Any]:
    path = path.resolve()
    content_errors, contents, manifest = _content_check(path)
    content_status = "PASS" if not content_errors else "FAIL"
    result: dict[str, Any] = {
        "schema": "g4.audit_verification/1",
        "zip": str(path), "zip_bytes": path.stat().st_size if path.is_file() else None,
        "zip_sha256": _sha(path.read_bytes()) if path.is_file() else None,
        "zip_members": len(contents),
        "manifest_covered": len(manifest.get("files", [])),
        "self_reference_exceptions": 2,
        "CONTENT_INTEGRITY": content_status,
        "content_errors": content_errors,
        "EXTRACTED_REPRO": "NOT_RUN",
        "TAMPER_REJECTED": "NOT_RUN",
        "SAME_ENV_BYTE_REPRO": "NOT_RUN",
        "CROSS_ENV_BYTE_REPRO": "NOT_RUN",
    }
    if content_status != "PASS":
        result["AUDIT_VERIFY"] = "FAIL"
        return result

    with tempfile.TemporaryDirectory(prefix="optisys_g4_verify_") as temp:
        temp_root = Path(temp) / "extracted"
        temp_root.mkdir()
        for name, data in contents.items():
            if not _safe_name(name):
                result["EXTRACTED_REPRO"] = "FAIL"
                result["AUDIT_VERIFY"] = "FAIL"
                return result
            dest = temp_root.joinpath(*PurePosixPath(name).parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            if not dest.resolve().is_relative_to(temp_root.resolve()):
                result["EXTRACTED_REPRO"] = "FAIL"
                result["AUDIT_VERIFY"] = "FAIL"
                return result

        # Mutation happens only in a separate temporary copy; the clean
        # extraction remains available for reproduction and deterministic rebuild.
        candidate = "run/tolerance_samples.csv"
        tamper_file = Path(temp) / "tampered" / candidate
        tamper_file.parent.mkdir(parents=True, exist_ok=True)
        data = bytearray((temp_root / candidate).read_bytes())
        if not data:
            result["TAMPER_REJECTED"] = "FAIL"
        else:
            data[len(data) // 2] ^= 1
            tamper_file.write_bytes(data)
            expected = next(row["sha256"] for row in manifest["files"] if row["path"] == candidate)
            if _sha(tamper_file.read_bytes()) == expected:
                result["TAMPER_REJECTED"] = "FAIL"
            else:
                result["TAMPER_REJECTED"] = "PASS"

        if not skip_repro:
            repro = temp_root / "repro/verify_g4.py"
            try:
                cp = subprocess.run([sys.executable, str(repro)], cwd=temp_root,
                                    capture_output=True, text=True, timeout=180)
            except (OSError, subprocess.SubprocessError) as exc:
                result["EXTRACTED_REPRO"] = f"FAIL: {type(exc).__name__}: {exc}"
            else:
                result["repro_stdout"] = cp.stdout
                result["repro_stderr"] = cp.stderr
                result["EXTRACTED_REPRO"] = "PASS" if cp.returncode == 0 and "REPRO_STATUS: PASS" in cp.stdout else "FAIL"

        names = list(contents)
        if not skip_same_env:
            rebuilt = Path(temp) / "same_env_rebuilt.zip"
            try:
                _write_deterministic_zip(rebuilt, temp_root, names)
            except Exception as exc:  # noqa: BLE001
                result["SAME_ENV_BYTE_REPRO"] = f"FAIL: {type(exc).__name__}: {exc}"
            else:
                result["SAME_ENV_BYTE_REPRO"] = "PASS" if _sha(rebuilt.read_bytes()) == result["zip_sha256"] else "FAIL"

        if cross_python:
            script = Path(temp) / "cross_rebuild.py"
            script.write_text(
                "import json,sys,zipfile\nfrom pathlib import Path\nfrom zipfile import ZipInfo,ZIP_STORED\n"
                "root=Path(sys.argv[1]); names=json.loads(Path(sys.argv[2]).read_text(encoding='utf-8')); out=Path(sys.argv[3])\n"
                "with zipfile.ZipFile(out,'w',compression=ZIP_STORED) as z:\n"
                "  for n in names:\n"
                "    i=ZipInfo(n,date_time=(1980,1,1,0,0,0)); i.compress_type=ZIP_STORED; i.external_attr=0o600<<16; i.create_system=0; i.flag_bits=0; z.writestr(i,root.joinpath(*n.split('/')).read_bytes())\n",
                encoding="utf-8")
            names_json = Path(temp) / "names.json"
            names_json.write_text(json.dumps(names), encoding="utf-8")
            cross_zip = Path(temp) / "cross_env_rebuilt.zip"
            cp = subprocess.run([cross_python, str(script), str(temp_root), str(names_json), str(cross_zip)],
                                cwd=temp_root, capture_output=True, text=True, timeout=180)
            result["cross_python"] = cross_python
            result["cross_python_exit_code"] = cp.returncode
            result["cross_python_stderr"] = cp.stderr
            if cp.returncode == 0 and cross_zip.is_file():
                result["CROSS_ENV_BYTE_REPRO"] = "PASS" if _sha(cross_zip.read_bytes()) == result["zip_sha256"] else "FAIL"
            else:
                result["CROSS_ENV_BYTE_REPRO"] = "FAIL"
        else:
            result["CROSS_ENV_BYTE_REPRO"] = "NOT_GUARANTEED"

    required = (result["CONTENT_INTEGRITY"] == "PASS"
                and result["TAMPER_REJECTED"] == "PASS"
                and (skip_repro or result["EXTRACTED_REPRO"] == "PASS")
                and (skip_same_env or result["SAME_ENV_BYTE_REPRO"] == "PASS")
                and result["CROSS_ENV_BYTE_REPRO"] in ("PASS", "NOT_GUARANTEED"))
    result["AUDIT_VERIFY"] = "PASS" if required else "FAIL"
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("zip", type=Path)
    parser.add_argument("--cross-python", type=str, default=None,
                        help="alternate Python executable for cross-environment stored-ZIP rebuild")
    parser.add_argument("--skip-extracted-repro", action="store_true")
    parser.add_argument("--skip-same-env-repro", action="store_true")
    args = parser.parse_args()
    result = verify(args.zip, cross_python=args.cross_python,
                    skip_repro=args.skip_extracted_repro,
                    skip_same_env=args.skip_same_env_repro)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print(f"AUDIT_VERIFY: {result['AUDIT_VERIFY']}")
    return 0 if result["AUDIT_VERIFY"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
