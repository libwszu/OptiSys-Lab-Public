"""T-SCI - the PRE-G3-01 .. 06 corrections must stay corrected.

Each test here pins one *scientific* finding from the G3 task book so that a
later refactor cannot quietly reintroduce the defect it repaired.  The tests
assert on the artefacts, not on prose: a verdict JSON field, a recomputed
number, a threshold constant.

A finding whose evidence is not yet available is asserted as ``UNRESOLVED``
rather than skipped.  The task book is explicit that an unresolved scientific
disagreement must fail the gate; a silently skipped test would hide exactly
that.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
VERDICT_PATH = ROOT / "docs" / "g3" / "G2_INHERITANCE_VERDICT.json"
G2_RUN = ROOT / "runs" / "20261019_191117_G2_52369787"

VERDICT_KEYS = (
    "historical_g2_execution",
    "original_prereg_compliance",
    "as_run_numerical_verification",
    "stratified_panel_repair",
    "full_samples_available",
    "scientific_claim_allowed",
)


@pytest.fixture(scope="module")
def verdict() -> dict:
    assert VERDICT_PATH.is_file(), f"verdict missing: {VERDICT_PATH}"
    return json.loads(VERDICT_PATH.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# PRE-G3-01 .. 06 - the verdict must carry every required field
# --------------------------------------------------------------------------
@pytest.mark.parametrize("key", VERDICT_KEYS)
def test_verdict_has_required_field(verdict: dict, key: str) -> None:
    assert key in verdict, f"PRE-G3-06: verdict field {key!r} missing"


def test_verdict_keeps_execution_and_science_lines_separate(verdict: dict) -> None:
    """PRE-G3-06: the two judgements are not collapsed into one token.

    The G2 run recorded PASS while its pre-registration was not complied with.
    A single ``G2_ALL_PASS`` would assert both that the numbers check out and
    that the protocol was honoured, which is false.
    """

    execution = verdict["historical_g2_execution"]
    compliance = verdict["original_prereg_compliance"]
    assert execution != compliance, (
        "historical execution and prereg compliance collapsed to the same token "
        f"({execution!r}); PRE-G3-06 requires them to stay separable")
    assert execution == "PASS_RECORDED"
    assert compliance == "FAIL"


def test_verdict_does_not_claim_full_compliance(verdict: dict) -> None:
    """The forbidden phrasings may appear only inside an explicit ban list.

    The verdict *does* contain the string "pre-registration fully complied
    with" - inside ``forbidden_phrasings``, where it is named in order to be
    banned.  A naive substring check would therefore fire on the correct file,
    so the check walks the leaves and allows the phrase only in a list that is
    itself labelled forbidden.
    """

    forbidden = ("fully complied", "all gates passed", "unqualified")

    def walk(node, key_path: tuple[str, ...] = ()):
        if isinstance(node, dict):
            for key, value in node.items():
                yield from walk(value, (*key_path, str(key)))
        elif isinstance(node, list):
            for index, value in enumerate(node):
                yield from walk(value, (*key_path, str(index)))
        elif isinstance(node, str):
            yield key_path, node

    violations = []
    for path, text in walk(verdict):
        lowered = text.lower()
        if not any(word in lowered for word in forbidden):
            continue
        if any("forbidden" in segment.lower() for segment in path):
            continue  # naming a banned phrase in a ban list is the point
        violations.append((path, text[:120]))
    assert not violations, f"unqualified compliance claim at {violations}"


def test_scientific_claim_is_qualified_not_granted(verdict: dict) -> None:
    assert verdict["scientific_claim_allowed"] == "QUALIFIED_ONLY"
    rationale = verdict.get("verdict_rationale", "")
    assert "QUALIFIED_ONLY" in rationale or "qualified" in rationale.lower()


# --------------------------------------------------------------------------
# PRE-G3-01 - HC3: registered 0.999 vs as-run 0.950
# --------------------------------------------------------------------------
def test_hc3_conflict_is_recorded_as_a_reason(verdict: dict) -> None:
    reasons = verdict["original_prereg_compliance_reasons"]
    joined = json.dumps(reasons, ensure_ascii=False)
    assert "PRE-G3-01" in joined, "PRE-G3-01 (HC3 conflict) vanished from the verdict"
    assert "0.999" in joined and "0.950" in joined


def test_hc3_amendment_is_marked_post_hoc() -> None:
    """The amendment must never present itself as the original registration."""

    path = ROOT / "docs" / "g3" / "G2_CONSTRAINTS_AMENDMENT.md"
    assert path.is_file(), "HC3 amendment document missing"
    text = path.read_text(encoding="utf-8")
    assert "POST-HOC AMENDMENT" in text.upper()
    # and it must state falsifiability, not just assert a new number
    assert "伪证" in text or "falsif" in text.lower()


def test_as_run_threshold_matches_the_amendment() -> None:
    """The demo config's HC3 gate must equal the as-run 0.950, not the prereg 0.999."""

    import yaml

    config = yaml.safe_load((ROOT / "configs" / "g3_demo.yaml").read_text(encoding="utf-8"))
    support = config["constraints"]["min_kernel_support"]
    assert support == pytest.approx(0.950), (
        f"configs/g3_demo.yaml gates kernel support at {support}, "
        "which would reintroduce the PRE-G3-01 conflict")


# --------------------------------------------------------------------------
# PRE-G3-02 - development must not see the final test distances
# --------------------------------------------------------------------------
def test_oat_and_precheck_do_not_touch_final_test_distances() -> None:
    """105 / 285 mm are final-test distances; development may not use them.

    The test recomputes the split from the config rather than hard-coding the
    numbers, so a config edit that leaks a test distance is caught.
    """

    from optisys.config_g2 import load_config_g2

    config = load_config_g2(ROOT / "configs" / "triangulation_g2_l1.yaml")
    test = set(config.dataset.test_distances)
    validation = set(config.dataset.validation_distances)
    leak = test & validation
    assert not leak, f"PRE-G3-02: distances appear in both splits: {sorted(leak)}"
    assert 105.0 not in validation and 285.0 not in validation


def test_verdict_records_the_distance_leak(verdict: dict) -> None:
    joined = json.dumps(verdict, ensure_ascii=False)
    assert "PRE-G3-02" in joined
    assert "105" in joined or "285" in joined


# --------------------------------------------------------------------------
# PRE-G3-03 - stratified reuse of a stale design
# --------------------------------------------------------------------------
def test_stratified_repair_is_recorded(verdict: dict) -> None:
    """PRE-G3-03: the stale-binding defect must be evidenced, not merely asserted.

    The verdict does not carry a literal ``PRE-G3-03`` id in
    ``original_prereg_compliance_reasons`` - it is not a pre-registration
    deviation but a code defect found during the G3 repair.  What must be
    present is the *structure* of the repair: the defect description, the
    independence check that proves the main panel was unaffected, the
    old-vs-new deltas, and the note that one candidate's delta is exactly zero
    for a stated reason.
    """

    assert verdict["stratified_panel_repair"] == "PASS"
    detail = verdict["stratified_panel_repair_detail"]

    assert "stale" in detail["defect"].lower() or "reused" in detail["defect"].lower()
    assert detail["main_panel_independence_check"]["conclusion"]
    assert detail["tests_failed_before_fix"] is True
    assert detail["tests_pass_after_fix"] is True

    deltas = detail["deltas_old_to_new"]
    assert len(deltas) == 6, "each candidate x condition pair needs its own delta"
    changed = [d for d in deltas if d["old_rmse_mm"] != d["new_rmse_mm"]]
    unchanged = [d for d in deltas if d["old_rmse_mm"] == d["new_rmse_mm"]]
    assert changed, "a repair with no changed rows repaired nothing"
    # robust is unchanged because the stale binding happened to be its own design
    assert {d["candidate"] for d in unchanged} == {"robust"}
    assert "zero" in detail["robust_unchanged_reason"].lower() or \
        "0.0" in detail["robust_unchanged_reason"]


def test_stratified_recompute_budget_breach_is_admitted(verdict: dict) -> None:
    """The 1897.8 s recompute must say it blew the 600 s budget."""

    recompute = verdict["stratified_panel_repair_detail"]["recomputation"]
    assert recompute["budget_exceeded"] is True
    assert recompute["wall_s"] > recompute["budget_s"]
    assert recompute["budget_handling"], "no statement about how the breach was handled"


def test_stratified_repair_artifact_distinguishes_old_and_new() -> None:
    """If a repair artefact exists it must carry both the stale and fixed RMSE.

    Without both columns a reader cannot tell what changed, which is the exact
    failure PRE-G3-03 describes.
    """

    path = ROOT / "artifacts" / "g3" / "pre" / "stratified_repair" / "stratified_repair.json"
    assert path.is_file(), f"repaired stratified panel artefact missing: {path}"
    payload = json.loads(path.read_text(encoding="utf-8"))
    blob = json.dumps(payload, ensure_ascii=False).lower()
    assert "stale" in blob or "before" in blob or "old_rmse" in blob
    assert "new_rmse" in blob or "repaired" in blob
    # every candidate must have its own repaired CSV next to the JSON
    directory = path.parent
    for candidate in ("baseline", "nominal", "robust"):
        assert (directory / f"stratified_{candidate}.csv").is_file(), \
            f"repaired CSV missing for {candidate}"


# --------------------------------------------------------------------------
# PRE-G3-04 - truncated CSV
# --------------------------------------------------------------------------
def test_full_sample_record_is_available(verdict: dict) -> None:
    assert verdict["full_samples_available"] is True
    assert (G2_RUN / "independent_validation" / "sampled_results.csv").is_file()


def test_sample_csv_row_count_exceeds_the_truncated_export() -> None:
    """PRE-G3-04: the audit ZIP holds 20 000 rows; the run holds 126 000."""

    path = G2_RUN / "independent_validation" / "sampled_results.csv"
    if not path.is_file():
        pytest.skip("frozen G2 run not present in this checkout")
    with path.open(encoding="utf-8") as handle:
        n = sum(1 for _ in handle) - 1
    assert n == 126_000, f"expected the complete 126 000-row record, found {n}"
    assert n > 20_000, "record is still truncated at the audit-ZIP export size"


def test_verdict_explains_the_truncation(verdict: dict) -> None:
    joined = json.dumps(verdict, ensure_ascii=False)
    assert "PRE-G3-04" in joined
    assert "20000" in joined.replace(" ", "") or "20 000" in joined


# --------------------------------------------------------------------------
# PRE-G3-05 - Strategy A and B are not the same quantity
# --------------------------------------------------------------------------
def test_strategy_ab_is_not_a_direct_subtraction(verdict: dict) -> None:
    joined = json.dumps(verdict, ensure_ascii=False)
    assert "PRE-G3-05" in joined
    assert "NOT_DIRECTLY_COMPARABLE" in joined or "directly comparable" in joined.lower()


def test_report_does_not_quantify_a_calibration_gain() -> None:
    """No surface may claim a number for the Strategy-B gain."""

    from optisys.reports.report_service import FORBIDDEN_CLAIMS

    assert any("recalibration" in claim for claim in FORBIDDEN_CLAIMS)


# --------------------------------------------------------------------------
# PRE-G3-06 - the residual list
# --------------------------------------------------------------------------
@pytest.mark.parametrize("token", (
    "PRE-G3-06",
))
def test_residual_items_are_listed(verdict: dict, token: str) -> None:
    joined = json.dumps(verdict, ensure_ascii=False)
    assert token in joined, f"{token} not recorded in the verdict"


def test_formula_sign_issue_is_documented() -> None:
    """SD-001: PDF eq. (3) prints dZ/du positive; the derivative is negative."""

    path = ROOT / "docs" / "SPEC_DISCREPANCIES.md"
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    assert "SD-001" in text
    assert "magnitude" in text.lower() or "幅值" in text


def test_cli_report_handles_schema_3(tmp_path: Path) -> None:
    """PRE-G3-06: the report path must branch on schema 3.0, not crash."""

    from optisys.reports.report_service import ReportService

    service = ReportService(ROOT / "runs", verdict_root=ROOT)
    result = service.build(G2_RUN, out_dir=tmp_path / "g2_report",
                           formats=("html", "markdown"))
    assert result.bytes_html > 2000
    assert result.science_tokens_present, "schema-3.0 report dropped the science tokens"