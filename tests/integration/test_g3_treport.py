"""T-REPORT - report numbers, schema branch, offline assets, disclaimers.

The report is the artefact a reader is most likely to quote out of context, so
these tests check three things a careless implementation would break:

* the numbers in the report equal the numbers recomputed from the CSV;
* the generated HTML needs no network resource to render;
* every science token and every limitation sentence survives each schema.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
G0_RUN = ROOT / "runs" / "20261019_130948_G0_78fa364f"
G1_RUN = ROOT / "runs" / "20261019_145702_G1_54c9e3fb"
G2_RUN = ROOT / "runs" / "20261019_191117_G2_52369787"
G3_RUNS = sorted((ROOT / "runs").glob("*_G3_*"))

SCIENCE_TOKENS = (
    "G2_PREREG_FEASIBILITY_NOT_ESTABLISHED",
    "G2_FINAL_PANEL_DEVIATION",
    "G2_FINAL_DISTANCE_LEAK_INTO_DEVELOPMENT",
    "CALIBRATION_MODEL_SELECTION_NOT_EXECUTED_AS_REGISTERED",
)


@pytest.fixture(scope="module")
def service():
    from optisys.reports.report_service import ReportService

    return ReportService(ROOT / "runs", verdict_root=ROOT)


@pytest.fixture(scope="module")
def g2_report(service, tmp_path_factory):
    out = tmp_path_factory.mktemp("g2_report")
    return service.build(G2_RUN, out_dir=out, formats=("html", "markdown")), out


# --------------------------------------------------------------------------
# numbers in the report equal the numbers in the data
# --------------------------------------------------------------------------
def test_report_rmse_matches_a_recomputation_from_the_csv(g2_report) -> None:
    """Recompute per-candidate RMSE from the raw rows and compare cell by cell.

    This is the test that would have caught the truncated-CSV problem
    (PRE-G3-04) had it existed earlier: a report built from 20 000 of 126 000
    rows cannot reproduce the frozen RMSE.
    """

    result, out = g2_report
    html = (out / "report.html").read_text(encoding="utf-8")
    rows = list(csv.DictReader(
        (G2_RUN / "independent_validation" / "sampled_results.csv").open(
            encoding="utf-8", newline="")))

    by_candidate: dict[str, list[float]] = {}
    attempted: dict[str, int] = {}
    for row in rows:
        name = row["candidate"]
        attempted[name] = attempted.get(name, 0) + 1
        if str(row["valid"]).strip().lower() in ("true", "1"):
            value = row["signed_error_mm"].strip()
            if value:
                try:
                    number = float(value)
                except ValueError:
                    continue
                if number == number and abs(number) != float("inf"):
                    by_candidate.setdefault(name, []).append(number)

    for name, errors in by_candidate.items():
        rmse = (sum(e * e for e in errors) / len(errors)) ** 0.5
        # the HTML prints four decimals; allow the rounding of that field only
        assert f"{rmse:.4f}" in html, (
            f"{name}: recomputed RMSE {rmse:.4f} mm does not appear in the report; "
            "the report is not reproducing the frozen rows")

    assert sum(attempted.values()) == 126_000


def test_report_failure_rate_uses_the_attempt_denominator(g2_report) -> None:
    result, out = g2_report
    html = (out / "report.html").read_text(encoding="utf-8")
    summary = json.loads(
        (G2_RUN / "independent_validation" / "summary.json").read_text(encoding="utf-8"))
    for name in ("baseline", "nominal", "robust"):
        expected = summary["candidates"][name]["failure_rate"]
        assert f"{expected * 100:.2f}%" in html or f"{expected:.4f}" in html, (
            f"{name}: failure rate {expected:.4f} missing from the report")


# --------------------------------------------------------------------------
# schema branches
# --------------------------------------------------------------------------
@pytest.mark.parametrize("run,gate", [(G0_RUN, "G0"), (G1_RUN, "G1"), (G2_RUN, "G2")])
def test_every_schema_renders_and_keeps_the_science_tokens(service, tmp_path, run, gate) -> None:
    if not run.is_dir():
        pytest.skip(f"frozen {gate} run absent")
    result = service.build(run, out_dir=tmp_path / gate, formats=("html", "markdown"))
    assert result.bytes_html > 2000
    html = (tmp_path / gate / "report.html").read_text(encoding="utf-8")
    for token in SCIENCE_TOKENS:
        assert token in html, f"{gate} report dropped science token {token}"
    assert result.science_tokens_present == list(SCIENCE_TOKENS)


def test_g3_demo_report_marks_itself_as_a_demo(service, tmp_path) -> None:
    if not G3_RUNS:
        pytest.skip("no G3 run")
    run = G3_RUNS[-1]
    result = service.build(run, out_dir=tmp_path / "g3", formats=("html",))
    html = (tmp_path / "g3" / "report.html").read_text(encoding="utf-8")
    assert "G3" in html
    # a demo must never be presentable as a G2 result
    assert "DEMO_ONLY" in html or "demo" in html.lower()
    assert result.bytes_html > 2000


# --------------------------------------------------------------------------
# offline HTML
# --------------------------------------------------------------------------
def test_html_has_no_external_resource(g2_report) -> None:
    """The audit package must open on a machine with no network.

    A CDN stylesheet or a remote image would silently degrade the report for
    exactly the recipient who is supposed to audit it.
    """

    result, out = g2_report
    html = (out / "report.html").read_text(encoding="utf-8")
    assert "<style>" in html, "no inline stylesheet: the page depends on something external"
    for pattern in (r'src=["\']https?://', r'href=["\']https?://', r'@import\s+url\(',
                    r'<script[^>]+src='):
        assert not re.search(pattern, html, re.IGNORECASE), (
            f"report references a remote resource: {pattern}")
    # and no http(s) link may be the *only* way to reach a figure
    for digest in result.figures_indexed.values():
        assert re.fullmatch(r"[0-9a-f]{64}", digest)


def test_report_copies_the_figures_it_indexes(g2_report) -> None:
    result, out = g2_report
    copied = out / "figures"
    assert copied.is_dir(), "figures were indexed but not copied next to the report"
    for rel in result.figures_indexed:
        assert (copied / Path(rel).name).is_file(), f"indexed figure {rel} not copied"


# --------------------------------------------------------------------------
# disclaimers and forbidden claims
# --------------------------------------------------------------------------
def test_report_states_the_measurement_boundary(g2_report) -> None:
    result, out = g2_report
    html = (out / "report.html").read_text(encoding="utf-8")
    assert "无实测" in html or "NOT_MEASURED" in html or "SIMULATED" in html
    assert "G4" in html and "独立模拟案例" in html, (
        "the G2 report must distinguish its own data from the separate G4 case")


def test_report_never_quantifies_the_recalibration_gain(g2_report) -> None:
    from optisys.reports.report_service import FORBIDDEN_CLAIMS

    result, out = g2_report
    html = (out / "report.html").read_text(encoding="utf-8").lower()
    for claim in FORBIDDEN_CLAIMS:
        assert claim.lower() not in html, f"report contains a forbidden claim: {claim!r}"


def test_report_marks_strategy_ab_as_not_directly_comparable(g2_report) -> None:
    result, out = g2_report
    html = (out / "report.html").read_text(encoding="utf-8")
    assert "NOT_DIRECTLY_COMPARABLE" in html or "不可直接" in html


def test_report_declares_the_evidence_level(g2_report) -> None:
    """The report may *name* MEASURED, but only in order to deny it.

    The limitations section says "未达到 MEASURED 或 VALIDATED", which is the
    correct statement.  So the check looks for an *affirmative* claim instead of
    the bare token: a paragraph that asserts MEASURED without a negation in the
    same sentence.
    """

    result, out = g2_report
    html = (out / "report.html").read_text(encoding="utf-8")
    assert "SIMULATED" in html or "CROSS_CHECKED" in html

    negations = ("未达到", "未做", "无实测", "不支持", "not ", "no ", "never",
                 "NOT_", "不得", "禁止", "尚未")
    for chunk in re.split(r"(?<=[。；;])|</li>|</p>", html):
        if "MEASURED" not in chunk:
            continue
        assert any(word in chunk for word in negations), (
            "report asserts MEASURED evidence without a negation: "
            f"{chunk.strip()[:200]}")


def test_pdf_is_reported_as_not_delivered_not_faked(service, tmp_path) -> None:
    result = service.build(G2_RUN, out_dir=tmp_path / "pdf", formats=("html", "pdf"))
    assert result.pdf_status == "NOT_DELIVERED"
    assert result.pdf_reason
    assert not (tmp_path / "pdf" / "report.pdf").exists(), (
        "a pdf file exists although no renderer is installed")


# --------------------------------------------------------------------------
# the report must not write into the run it reports on
# --------------------------------------------------------------------------
def test_building_a_report_does_not_modify_the_frozen_run(service, tmp_path) -> None:
    def tree_digest(base: Path) -> str:
        digest = hashlib.sha256()
        for path in sorted(p for p in base.rglob("*")
                           if p.is_file() and "__pycache__" not in p.parts):
            digest.update(path.relative_to(base).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii"))
        return digest.hexdigest()

    before = tree_digest(G2_RUN)
    service.build(G2_RUN, out_dir=tmp_path / "guard", formats=("html", "markdown"))
    after = tree_digest(G2_RUN)
    assert before == after, "report generation wrote into the frozen run directory"


def test_default_output_directory_is_under_derived(service) -> None:
    """A report for a frozen run must land in runs/_derived, never in the run."""

    result = service.build(G2_RUN, formats=("html",))
    assert result.html_path is not None
    assert "_derived" in result.html_path.parts, (
        f"default report path {result.html_path} is not under runs/_derived")
    assert result.frozen_run_untouched is True
    # clean up the artefact this test just created so reruns stay idempotent
    for path in (result.html_path, result.markdown_path):
        if path is not None and path.is_file():
            path.unlink()
    try:
        result.html_path.parent.rmdir()
    except OSError:
        pass
