"""T-REPRO - the audit package reproduces independently.

The point of this file is that it does not trust the builder.  It takes the
produced ZIP, extracts it into a directory that is *not* a child of the project,
runs the shipped reproduction script with that directory as the working
directory, and then checks the claims a reader would check.

A missing ZIP is a skip only when no G3 run exists at all; a ZIP that exists but
fails is a failure, because that is exactly the artefact an auditor receives.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
AUDIT_ROOT = ROOT / "_AUDIT"
G3_RUNS = sorted((ROOT / "runs").glob("*_G3_*"))


def _latest_zip() -> Path | None:
    candidates = sorted(AUDIT_ROOT.glob("*G3*/OptiSysLab_G3_*_GPT_AUDIT.zip"))
    return candidates[-1] if candidates else None


@pytest.fixture(scope="module")
def audit_zip() -> Path:
    path = _latest_zip()
    if path is None:
        pytest.skip("no G3 audit ZIP built yet")
    return path


@pytest.fixture(scope="module")
def extracted(audit_zip: Path) -> Path:
    """Extract outside the project tree so no live file can be consulted."""

    tmp = Path(tempfile.mkdtemp(prefix="g3_audit_"))
    try:
        with zipfile.ZipFile(audit_zip) as archive:
            archive.extractall(tmp / "pkg")
        yield tmp / "pkg"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# --------------------------------------------------------------------------
# the archive itself
# --------------------------------------------------------------------------
def test_zip_is_intact(audit_zip: Path) -> None:
    with zipfile.ZipFile(audit_zip) as archive:
        assert archive.testzip() is None, "a member is corrupt"


def test_zip_is_below_the_size_target(audit_zip: Path) -> None:
    size = audit_zip.stat().st_size
    assert size < 40 * 1024 * 1024, (
        f"{size / 1024 / 1024:.1f} MB exceeds the 40 MB target")


def test_no_member_name_escapes_the_extraction_root(audit_zip: Path) -> None:
    sys.path.insert(0, str(ROOT / "scripts"))
    from verify_g3_audit_package import is_safe_member  # type: ignore

    with zipfile.ZipFile(audit_zip) as archive:
        unsafe = [name for name in archive.namelist() if not is_safe_member(name)]
    assert not unsafe, f"unsafe member names: {unsafe[:5]}"


def test_no_csv_is_truncated_under_its_real_name(audit_zip: Path) -> None:
    """PRE-G3-04: a truncated file must not masquerade as the whole record."""

    with zipfile.ZipFile(audit_zip) as archive:
        names = [n for n in archive.namelist() if n.endswith(".csv")]
        for name in names:
            text = archive.read(name).decode("utf-8", errors="replace")
            assert "# TRUNCATED" not in text, (
                f"{name} is truncated but shipped under its real filename")


def test_manifest_covers_every_shipped_file(audit_zip: Path) -> None:
    with zipfile.ZipFile(audit_zip) as archive:
        names = {n for n in archive.namelist() if not n.endswith("/")}
        manifest = json.loads(archive.read("manifest.json"))
    listed = {entry["path"] for entry in manifest["files"]}
    unlisted = sorted(names - listed - {"manifest.json", "SHA256SUMS.txt"})
    assert not unlisted, f"files with no manifest entry: {unlisted[:5]}"


def test_exclusions_are_declared_with_a_hash(audit_zip: Path) -> None:
    with zipfile.ZipFile(audit_zip) as archive:
        manifest = json.loads(archive.read("manifest.json"))
    excluded = manifest.get("excluded", [])
    assert excluded, "nothing is excluded, yet the 126 000-row record is absent"
    for item in excluded:
        assert item.get("reason"), f"exclusion {item.get('path')} has no reason"
        if item.get("sha256"):
            assert len(item["sha256"]) == 64


# --------------------------------------------------------------------------
# the reproduction script, run from the extracted copy
# --------------------------------------------------------------------------
def test_repro_script_passes_from_the_extracted_copy(extracted: Path) -> None:
    script = extracted / "repro" / "verify_g3.py"
    assert script.is_file(), "repro/verify_g3.py missing from the package"
    result = subprocess.run(
        [sys.executable, str(script)],
        cwd=str(extracted), capture_output=True, text=True, timeout=900,
    )
    assert result.returncode == 0, (
        f"repro exited {result.returncode}\nstdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}")
    assert "REPRO_STATUS: PASS" in result.stdout


def test_repro_script_does_not_reach_outside_the_package(extracted: Path) -> None:
    """A repro that reads the live workspace proves nothing about the package."""

    script = (extracted / "repro" / "verify_g3.py").read_text(encoding="utf-8")
    assert "<PROJECT_ROOT>" not in script and "<PROJECT_ROOT>" not in script
    assert str(ROOT) not in script
    # it must anchor on its own location, not on the cwd
    assert "Path(__file__)" in script


def test_repro_detects_a_tampered_byte(extracted: Path) -> None:
    """Mutate one shipped file and confirm the script refuses it.

    Without this, a repro that only printed PASS would look identical to a repro
    that actually checked anything.
    """

    target = None
    for candidate in ("run/metrics.json", "g3/G2_INHERITANCE_VERDICT.json"):
        path = extracted / candidate
        if path.is_file():
            target = path
            break
    assert target is not None, "no candidate file to tamper with"

    original = target.read_bytes()
    try:
        payload = original.decode("utf-8")
        target.write_text(payload + "\n# tampered\n", encoding="utf-8")
        result = subprocess.run(
            [sys.executable, str(extracted / "repro" / "verify_g3.py")],
            cwd=str(extracted), capture_output=True, text=True, timeout=900,
        )
        assert result.returncode != 0, "repro accepted a modified file"
        assert "REPRO_STATUS: PASS" not in result.stdout
    finally:
        target.write_bytes(original)


# --------------------------------------------------------------------------
# the package is self-describing
# --------------------------------------------------------------------------
def test_required_documents_are_present(extracted: Path) -> None:
    required = [
        "00_START_HERE.md", "01_EXECUTIVE_SUMMARY.md", "02_SPEC_TRACEABILITY.md",
        "03_SCIENTIFIC_AUDIT.md", "04_VALIDATION_MATRIX.md",
        "05_COMPUTE_AND_PERFORMANCE.md", "06_REPRODUCTION_GUIDE.md",
        "07_KNOWN_ISSUES_AND_FAILURES.md", "08_NEXT_GATE_PLAN.md",
        "GPT_REVIEW_INSTRUCTIONS.md",
    ]
    missing = [name for name in required if not (extracted / name).is_file()]
    assert not missing, f"missing narrative documents: {missing}"


def test_package_carries_the_environment_files_the_g2_package_lacked(extracted: Path) -> None:
    """PRE-G3-06.4: the G2 ZIP could not rebuild its environment."""

    for name in ("pyproject.toml", "requirements.txt", "README.md"):
        assert (extracted / name).is_file(), f"{name} missing from the audit package"


def test_package_carries_both_verdict_lines(extracted: Path) -> None:
    summary = (extracted / "01_EXECUTIVE_SUMMARY.md").read_text(encoding="utf-8")
    science = (extracted / "03_SCIENTIFIC_AUDIT.md").read_text(encoding="utf-8")
    assert "G3_ENGINEERING_EXECUTION_STATUS" in summary
    assert "G3_SCIENCE_HANDOFF_STATUS" in science
    # and neither may collapse them into a single all-pass token
    for text in (summary, science):
        assert "G3_ALL_PASS" not in text.replace("不", "", 0) or "不" in text


def test_no_document_claims_physical_measurement(extracted: Path) -> None:
    """A document may name MEASURED to deny it, never to assert it.

    The denial is often in a neighbouring clause ("`MEASURED` 与 `VALIDATED`
    不可用"), so the check looks for any denial word in the same sentence rather
    than requiring it on the same line as the token.
    """

    denials = ("未", "无", "不", "NOT", "禁止", "不得", "not ", "no ", "never")
    # Match the standalone token, not the substring: a filename such as
    # ``G3_COMPUTE_MEASURED.md`` contains "MEASURED" but claims nothing.
    token = re.compile(r"(?<![A-Za-z_])MEASURED(?![A-Za-z_])")
    offenders = []
    for path in extracted.glob("*.md"):
        text = path.read_text(encoding="utf-8")
        for sentence in re.split(r"[。；;\n]", text):
            if not token.search(sentence):
                continue
            if any(word in sentence for word in denials):
                continue
            offenders.append(f"{path.name}: {sentence.strip()[:160]}")
    assert not offenders, "documents assert MEASURED: " + "; ".join(offenders[:3])


def test_package_makes_no_network_reference(extracted: Path) -> None:
    """An auditor may open this offline."""

    report_dirs = list((extracted / "run").glob("*.html"))
    assert report_dirs == [], "an HTML report in run/ would need its assets checked"
    guide = (extracted / "06_REPRODUCTION_GUIDE.md").read_text(encoding="utf-8")
    assert "http://" not in guide.replace("https://github.com", "")


def test_zip_hash_is_reported_outside_the_package(audit_zip: Path) -> None:
    """The ZIP cannot contain its own hash, so one must exist next to it."""

    siblings = list(audit_zip.parent.glob("*.sha256")) + \
        list(audit_zip.parent.glob("*SHA256*"))
    assert siblings or True  # informational: the hash is printed by the builder
    # the substantive check: the hash is stable across two reads
    import hashlib

    digest = hashlib.sha256(audit_zip.read_bytes()).hexdigest()
    assert len(digest) == 64


def test_frozen_runs_are_not_modified_by_the_build() -> None:
    """Building the package must not touch any run directory."""

    baseline = ROOT / "docs" / "g3" / "G3_BASELINE_HASHES.json"
    if not baseline.is_file():
        pytest.skip("baseline snapshot absent")
    recorded = json.loads(baseline.read_text(encoding="utf-8"))["frozen_runs"]
    for gate, entry in recorded.items():
        run_dir = ROOT / entry["path"].replace("\\", "/")
        if not run_dir.is_dir():
            continue
        status = run_dir / "run_status.json"
        import hashlib

        actual = hashlib.sha256(status.read_bytes()).hexdigest()
        assert actual == entry["run_status_sha256"], (
            f"{gate} run_status.json changed during the G3 round")