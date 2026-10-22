"""One-shot G3 release verification.

Runs every acceptance gate that can be checked mechanically and prints a single
machine-readable verdict.  This is the script a reader runs when they do not
want to trust any individual document.

What it checks
--------------
1. frozen evidence: whole-tree digests of G0/G1/G2 against the pre-change
   baseline, plus the source PDF, the G2 audit ZIP and the G2 config;
2. the global verdict file is present, parses, and keeps its two lines separate;
3. a G3 demo run exists with every gate check passing and a complete figure set;
4. the test suite: this round's JUnit shows zero failures and zero skips;
5. the five inherited G3 UI surfaces import and render;
6. the audit ZIP: integrity, manifest coverage, and an independent extraction;
7. the documented non-claims are actually stated in the README.

Exit codes: 0 PASS, 1 FAIL, 2 DEPENDENCY_UNAVAILABLE.

Deliberately NOT checked here
-----------------------------
* whether the science is *right* - that is what the audit is for;
* remote CI - it has not run, and pretending otherwise is the failure mode this
  project is written against;
* G3-load parallel speedup or GPU - not tested in the G3 round.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "docs" / "g3" / "G3_BASELINE_HASHES.json"
VERDICT = ROOT / "docs" / "g3" / "G2_INHERITANCE_VERDICT.json"
STATUS = ROOT / "docs" / "g3" / "G3_FINAL_STATUS.json"
JUNIT = ROOT / "artifacts" / "g3" / "tests" / "g3_full_junit.xml"

FROZEN_RUNS = {
    "G0": ROOT / "runs" / "20261019_130948_G0_78fa364f",
    "G1": ROOT / "runs" / "20261019_145702_G1_54c9e3fb",
    "G2": ROOT / "runs" / "20261019_191117_G2_52369787",
}

VERDICT_FIELDS = (
    "historical_g2_execution",
    "original_prereg_compliance",
    "as_run_numerical_verification",
    "stratified_panel_repair",
    "full_samples_available",
    "scientific_claim_allowed",
)

REQUIRED_README_PHRASES = (
    "无实测",
    "NOT_MEASURED",
    "G4",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def tree_manifest(base: Path, root: Path = ROOT) -> tuple[str, int, int]:
    files = sorted(p for p in base.rglob("*")
                   if p.is_file() and "__pycache__" not in p.parts
                   and p.suffix not in (".pyc", ".pyo"))
    digest = hashlib.sha256()
    total = 0
    for path in files:
        rel = path.relative_to(root).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256_file(path).encode("ascii"))
        digest.update(b"\n")
        total += path.stat().st_size
    return digest.hexdigest(), len(files), total


# ---------------------------------------------------------------------------
# individual gates
# ---------------------------------------------------------------------------
def check_frozen_evidence() -> list[str]:
    failures: list[str] = []
    if not BASELINE.is_file():
        return [f"baseline snapshot missing: {BASELINE}"]
    baseline = json.loads(BASELINE.read_text(encoding="utf-8"))

    for key, rel_key in (("source_pdf", "sha256"), ("g2_audit_zip", "sha256"),
                         ("g2_config", "sha256")):
        entry = baseline.get(key, {})
        path = ROOT / str(entry.get("path", "")).replace("\\", "/")
        if not path.is_file():
            failures.append(f"{key}: file missing at {entry.get('path')}")
            continue
        actual = sha256_file(path)
        expected = entry.get("expected") or entry.get(rel_key)
        if actual != expected:
            failures.append(f"{key}: {actual[:16]} != {str(expected)[:16]}")

    for gate, run_dir in FROZEN_RUNS.items():
        recorded = baseline["frozen_runs"].get(gate)
        if recorded is None:
            failures.append(f"{gate}: no baseline entry")
            continue
        if not run_dir.is_dir():
            failures.append(f"{gate}: run directory missing")
            continue
        digest, count, total = tree_manifest(run_dir)
        if count != recorded["file_count"]:
            failures.append(
                f"{gate}: {count} files now, {recorded['file_count']} at baseline")
        if total != recorded["total_bytes"]:
            failures.append(
                f"{gate}: {total} bytes now, {recorded['total_bytes']} at baseline")
        if digest != recorded["tree_digest"]:
            failures.append(f"{gate}: tree digest changed")
        status_sha = sha256_file(run_dir / "run_status.json")
        if status_sha != recorded["run_status_sha256"]:
            failures.append(f"{gate}: run_status.json rewritten")
    return failures


def check_verdict() -> list[str]:
    failures: list[str] = []
    if not VERDICT.is_file():
        return [f"verdict missing: {VERDICT}"]
    try:
        verdict = json.loads(VERDICT.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return [f"verdict is not valid JSON: {exc}"]

    for field in VERDICT_FIELDS:
        if field not in verdict:
            failures.append(f"verdict field missing: {field}")

    execution = verdict.get("historical_g2_execution")
    compliance = verdict.get("original_prereg_compliance")
    if execution == compliance:
        failures.append(
            "historical execution and prereg compliance collapsed to one token; "
            "the whole point of the verdict is that they differ")
    if verdict.get("scientific_claim_allowed") != "QUALIFIED_ONLY":
        failures.append(
            f"scientific_claim_allowed is {verdict.get('scientific_claim_allowed')!r}, "
            "expected QUALIFIED_ONLY")
    if verdict.get("full_samples_available") is not True:
        failures.append("full_samples_available is not True")
    return failures


def _find_g3_run() -> Path | None:
    runs = sorted((ROOT / "runs").glob("*_G3_*"))
    for candidate in reversed(runs):
        if (candidate / "run_status.json").is_file():
            return candidate
    return None


def check_demo_run() -> list[str]:
    failures: list[str] = []
    run_dir = _find_g3_run()
    if run_dir is None:
        return ["no G3 run with a run_status.json found"]
    status = json.loads((run_dir / "run_status.json").read_text(encoding="utf-8"))
    if status.get("gate") != "G3":
        failures.append(f"run gate is {status.get('gate')!r}")
    if status.get("status") != "PASS":
        failures.append(f"run status is {status.get('status')!r}, expected PASS")
    if status.get("scientific_claim_status") != "DEMO_ONLY_NOT_A_G2_CONFIRMATION":
        failures.append(
            "scientific claim status does not disclaim G2 confirmation: "
            f"{status.get('scientific_claim_status')!r}")
    for name, check in status.get("gate_checks", {}).items():
        if not check.get("pass"):
            failures.append(f"gate check failed: {name}")

    figures = list((run_dir / "figures").glob("*.png"))
    if len(figures) < 4:
        failures.append(f"only {len(figures)} figures produced, expected >= 4")

    csv_path = run_dir / "independent_validation" / "sampled_results.csv"
    if not csv_path.is_file():
        failures.append("per-sample record missing")
    else:
        with csv_path.open(encoding="utf-8") as handle:
            rows = sum(1 for _ in handle) - 1
        if rows == 0:
            failures.append("per-sample record is empty")

    provenance = json.loads((run_dir / "provenance.json").read_text(encoding="utf-8"))
    # ``demo_boundary`` is written by ``RunContext.provenance(extra=...)``, so it
    # lands under ``extra``; accepting only the top level would report a demo that
    # declares its boundary correctly as undeclared.
    boundary = provenance.get("extra", {}).get("demo_boundary") or \
        provenance.get("demo_boundary") or {}
    if not boundary:
        failures.append("provenance carries no demo_boundary block")
    else:
        if boundary.get("is_g2_rerun") is not False:
            failures.append("demo does not declare is_g2_rerun: false")
        if boundary.get("comparable_to_g2") is not False:
            failures.append("demo does not declare comparable_to_g2: false")
    return failures


def check_tests() -> list[str]:
    """Verify the JUnit produced by a *completed* run.

    This script is expected to be run after ``pytest`` has finished, so the file
    on disk is complete.  The in-suite tests deliberately do not enforce
    ``failed == 0`` on this file, because a test cannot assert on the archive it
    is itself writing; that gate belongs here, once.
    """

    if not JUNIT.is_file():
        return [f"JUnit missing: {JUNIT}; run pytest with --junitxml first"]
    root = ET.parse(JUNIT).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
    total = sum(int(s.get("tests", 0)) for s in suites)
    failed = sum(int(s.get("failures", 0)) for s in suites)
    errors = sum(int(s.get("errors", 0)) for s in suites)
    skipped = sum(int(s.get("skipped", 0)) for s in suites)
    failures: list[str] = []
    if total < 252:
        failures.append(f"{total} tests is fewer than the 252 historical baseline")
    if failed:
        failures.append(f"{failed} failing tests")
    if errors:
        failures.append(f"{errors} erroring tests")
    if skipped:
        failures.append(f"{skipped} skipped tests; the gate forbids skips")
    return failures


def check_ui(with_serve: bool = False) -> list[str]:
    """Import every page module; a syntax or import error must not hide until
    someone opens the app.

    Module import is not the same claim as "the README's one command works":
    the pages could import cleanly and ``streamlit run`` could still fail to
    bind a port.  ``with_serve`` closes that gap by running
    ``scripts/smoke_streamlit_serve.py``, which starts the server, probes
    ``/_stcore/health`` for the literal ``ok`` and shuts it down again.
    """

    sys.path.insert(0, str(ROOT))
    failures: list[str] = []
    modules = [
        "app.main",
        "app.ui_context",
        "app.components",
        "app.components.plotting",
        "app.pages.page_a_overview",
        "app.pages.page_b_bench",
        "app.pages.page_c_optimization",
        "app.pages.page_d_evidence",
        "app.pages.page_e_about",
    ]
    for name in modules:
        try:
            __import__(name)
        except Exception as exc:  # noqa: BLE001 - report the real error
            failures.append(f"{name}: {type(exc).__name__}: {exc}")

    if with_serve:
        smoke = ROOT / "scripts" / "smoke_streamlit_serve.py"
        if not smoke.is_file():
            failures.append(f"serve smoke test missing: {smoke}")
        else:
            result = subprocess.run(
                [sys.executable, str(smoke),
                 "--json", str(ROOT / "artifacts" / "g3" / "tests" / "streamlit_serve.json")],
                capture_output=True, text=True, timeout=600,
            )
            if result.returncode == 2:
                failures.append("serve smoke test reported DEPENDENCY_UNAVAILABLE")
            elif result.returncode != 0:
                failures.append(
                    "the documented 'streamlit run app/main.py' did not serve "
                    f"(exit {result.returncode}): {result.stdout.strip()[-400:]}")
    return failures


def check_audit_package() -> list[str]:
    zips = sorted((ROOT / "_AUDIT").glob("*G3*/OptiSysLab_G3_*_GPT_AUDIT.zip"))
    if not zips:
        return ["no G3 audit ZIP found"]
    archive = zips[-1]
    verifier = ROOT / "scripts" / "verify_g3_audit_package.py"
    if not verifier.is_file():
        return [f"verifier missing: {verifier}"]
    result = subprocess.run(
        [sys.executable, str(verifier), str(archive)],
        capture_output=True, text=True, timeout=1800,
    )
    if result.returncode == 2:
        return ["audit verification reported DEPENDENCY_UNAVAILABLE"]
    if result.returncode != 0:
        return [f"audit verification failed (exit {result.returncode}): "
                f"{result.stdout.strip()[-400:]}"]
    return []


def check_readme_non_claims() -> list[str]:
    """The README may *name* a forbidden claim only to deny it.

    ``无实测``, ``NOT_MEASURED`` and ``G4`` must be present.  A phrase such as
    ``实测验证`` is acceptable inside a table cell that says ``无数据``; it is not
    acceptable as a standalone capability claim.
    """

    readme = ROOT / "README.md"
    if not readme.is_file():
        return ["README.md missing"]
    text = readme.read_text(encoding="utf-8")
    failures = [f"README does not state {phrase!r}"
                for phrase in REQUIRED_README_PHRASES if phrase not in text]

    denials = ("无数据", "无实测", "不可用", "NOT_", "未", "无", "不是", "禁止")
    for chunk in text.splitlines():
        if not any(phrase in chunk for phrase in ("已通过 CI", "实测验证", "高精度工业")):
            continue
        if any(word in chunk for word in denials):
            continue
        failures.append(f"README contains an unsupported claim: {chunk.strip()[:120]}")
    return failures


def check_status_file() -> list[str]:
    if not STATUS.is_file():
        return [f"final status missing: {STATUS}"]
    status = json.loads(STATUS.read_text(encoding="utf-8"))
    failures: list[str] = []
    lines = status.get("verdict_lines", {})
    if lines.get("G3_ENGINEERING_EXECUTION_STATUS") == \
            lines.get("G3_SCIENCE_HANDOFF_STATUS"):
        failures.append("status collapses the two verdict lines")
    if "G3_ALL_PASS" not in lines.get("aggregate_form_forbidden", []):
        failures.append("status does not explicitly forbid G3_ALL_PASS")
    missing_docs = [name for name, rel in status.get("documents", {}).items()
                    if not (ROOT / rel).is_file()]
    if missing_docs:
        failures.append(f"documents promised but absent: {missing_docs}")
    return failures


GATES = {
    "frozen_evidence": check_frozen_evidence,
    "verdict": check_verdict,
    "demo_run": check_demo_run,
    "tests": check_tests,
    "ui": check_ui,
    "audit_package": check_audit_package,
    "readme_non_claims": check_readme_non_claims,
    "status_file": check_status_file,
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="verify the G3 release")
    parser.add_argument("--json", type=Path, default=None,
                        help="also write the result as JSON to this path")
    parser.add_argument("--skip-audit", action="store_true",
                        help="skip the (slow) audit-package verification")
    parser.add_argument("--with-serve", action="store_true",
                        help="also launch 'streamlit run' and probe the port "
                             "(~10 s); without it the ui gate only imports modules")
    args = parser.parse_args(argv)

    results: dict[str, Any] = {}
    total_failures: list[str] = []
    for name, gate in GATES.items():
        if args.skip_audit and name == "audit_package":
            results[name] = {"status": "SKIPPED_BY_REQUEST", "failures": []}
            continue
        try:
            failures = gate(with_serve=args.with_serve) if name == "ui" else gate()
        except Exception as exc:  # noqa: BLE001 - a crashing gate is a failure
            failures = [f"{type(exc).__name__}: {exc}"]
        results[name] = {"status": "PASS" if not failures else "FAIL",
                         "failures": failures}
        total_failures.extend(failures)

    for name, payload in results.items():
        marker = "OK  " if payload["status"] == "PASS" else (
            "SKIP" if payload["status"].startswith("SKIPPED") else "FAIL")
        print(f"[{marker}] {name}")
        for item in payload["failures"][:8]:
            print(f"        - {item}")
        if len(payload["failures"]) > 8:
            print(f"        ... {len(payload['failures']) - 8} more")

    verdict_token = "PASS" if not total_failures else "FAIL"
    print(f"\nG3_RELEASE_VERIFY: {verdict_token}")
    if args.skip_audit:
        print("  WARNING: the audit-package gate was skipped on request; this run "
              "does not certify G3-12")
    print("  note: this checks engineering reproducibility, NOT that the "
          "science is correct and NOT any claim of physical measurement")

    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({
            "schema": "g3.release_verify/1",
            "result": verdict_token,
            "gates": results,
            "not_checked": ["remote CI", "physical measurement",
                            "parallel speedup", "GPU"],
        }, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    return 0 if not total_failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
