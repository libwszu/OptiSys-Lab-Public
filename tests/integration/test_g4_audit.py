"""G4 archive manifest detects a changed sample byte."""

from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import build_g4_audit_package as builder  # noqa: E402
import verify_g4_audit_package as verifier  # noqa: E402


def test_manifest_rejects_tampered_tolerance_sample(tmp_path) -> None:
    required_files = [name for name in verifier.REQUIRED
                      if name not in ("manifest.json", "SHA256SUMS.txt")]
    payload = {name: f"evidence for {name}\n".encode("utf-8") for name in required_files}
    payload["run/run_status.json"] = b'{"gate":"G4","status":"PARTIAL"}\n'
    payload["run/tolerance_samples.csv"] = b"sample_id,weight\nassembly-0,1.0\n"
    archive = tmp_path / "g4_test.zip"
    builder.build_archive(payload, archive, "g4-test-run")
    errors, _, _ = verifier._content_check(archive)
    assert errors == []

    tampered = tmp_path / "g4_test_tampered.zip"
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(
            tampered, "w", compression=zipfile.ZIP_STORED) as output:
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename == "run/tolerance_samples.csv":
                data = data.replace(b"1.0", b"2.0")
            replacement = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            replacement.compress_type = zipfile.ZIP_STORED
            replacement.external_attr = info.external_attr
            replacement.create_system = info.create_system
            output.writestr(replacement, data)
    errors, _, _ = verifier._content_check(tampered)
    assert any("manifest mismatch: run/tolerance_samples.csv" in error for error in errors)
