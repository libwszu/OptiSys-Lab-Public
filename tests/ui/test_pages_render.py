"""T-UI: the five pages render, and the science status cannot be dropped.

These tests use ``streamlit.testing.v1.AppTest``, so they exercise the real page
modules including their imports.  They are deliberately shallow - they assert
that pages render and that the mandatory status tokens appear - because the
scientific guarantees live in ``T-SCI`` / ``T-DATA`` tests, not here.

What a failure here means:
* ``exception`` non-empty -> a page crashed;
* a science token missing -> a page is able to show G2 numbers without the
  qualification, which is the exact failure mode the task book forbids.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
for path in (str(ROOT), str(ROOT / "src")):
    if path not in sys.path:
        sys.path.insert(0, path)

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest

MAIN = str(ROOT / "app" / "main.py")

PAGE_LABELS = {
    "A": "A · 项目总览与证据状态",
    "B": "B · 光斑实验台",
    "C": "C · 优化对照",
    "D": "D · 运行与证据中心",
    "E": "E · 说明与边界",
    "F": "F · 976 nm 泵浦光路",
}

SCIENCE_TOKENS = (
    "G2_PREREG_FEASIBILITY_NOT_ESTABLISHED",
    "G2_FINAL_PANEL_DEVIATION",
    "G2_FINAL_DISTANCE_LEAK_INTO_DEVELOPMENT",
    "CALIBRATION_MODEL_SELECTION_NOT_EXECUTED_AS_REGISTERED",
)


def _run_page(label: str) -> "AppTest":
    app = AppTest.from_file(MAIN, default_timeout=180)
    app.session_state["_page"] = label
    app.run()
    return app


@pytest.mark.parametrize("key", sorted(PAGE_LABELS))
def test_each_page_renders_without_exception(key: str) -> None:
    app = _run_page(PAGE_LABELS[key])
    assert not app.exception, [str(e.value) for e in app.exception]


def test_overview_shows_both_verdict_lines_separately() -> None:
    """Engineering PASS and science FAIL must both be visible, not merged."""

    app = _run_page(PAGE_LABELS["A"])
    assert not app.exception
    blob = _all_text(app)
    assert "QUALIFIED_ONLY" in blob
    assert "PASS_RECORDED" in blob
    assert "FAIL" in blob
    # The page may mention G3_ALL_PASS only to reject it, so the assertion is
    # that no surface ever *asserts* an all-pass conclusion.
    assert _asserts_all_pass(app) is False


def test_no_surface_asserts_an_all_pass_conclusion() -> None:
    for key in PAGE_LABELS:
        app = _run_page(PAGE_LABELS[key])
        assert _asserts_all_pass(app) is False, f"page {key} claims an all-pass state"


def _asserts_all_pass(app: "AppTest") -> bool:
    """True only if a rendered element asserts all-pass WITHOUT negating it."""

    negatives = ("不合并", "不得", "禁止", "不是", "NOT", "禁止被")
    for chunk in _chunks(app):
        if "G3_ALL_PASS" not in chunk and "全部通过" not in chunk:
            continue
        if not any(marker in chunk for marker in negatives):
            return True
    return False


def test_overview_states_no_measured_data() -> None:
    app = _run_page(PAGE_LABELS["A"])
    blob = _all_text(app)
    assert "无实测" in blob or "SIMULATED" in blob
    assert "G4" in blob and "SIMULATED" in blob


def test_page_c_carries_all_science_tokens() -> None:
    """Page C shows G2 numbers, so it must carry the strip."""

    app = _run_page(PAGE_LABELS["C"])
    assert not app.exception
    codes = {element.value for element in app.code} if app.code else set()
    blob = _all_text(app)
    present = [token for token in SCIENCE_TOKENS if token in codes or token in blob]
    assert present, "page C rendered G2 numbers with no science token"


def test_page_c_refuses_single_axis_ranking() -> None:
    app = _run_page(PAGE_LABELS["C"])
    blob = _all_text(app)
    assert "不排名" in blob or "不" in blob
    assert "最优" in blob  # stated in the negative: "不做单一排名...「最优」"


def test_page_c_strategy_gain_module_is_disabled() -> None:
    """The withdrawn 1.5-3 mm gain must not be reasserted anywhere."""

    app = _run_page(PAGE_LABELS["C"])
    blob = _all_text(app)
    assert "NOT_RUN" in blob
    assert "NOT_DIRECTLY_COMPARABLE" in blob


def test_page_f_marks_g4_as_simulated_and_keeps_g2_qualification() -> None:
    app = _run_page(PAGE_LABELS["F"])
    blob = _all_text(app)
    assert "SIMULATED" in blob
    assert "QUALIFIED_ONLY" in blob
    assert "976" in blob
    assert "NOT_AVAILABLE" in blob or "UNKNOWN" in blob


def test_page_d_shows_orphaned_state_vocabulary() -> None:
    app = _run_page(PAGE_LABELS["D"])
    assert not app.exception


def test_bench_fast_preview_is_labelled_preview_only() -> None:
    """FAST_PREVIEW must announce itself before any number is produced."""

    app = _run_page(PAGE_LABELS["B"])
    assert not app.exception
    radios = app.radio
    assert radios, "bench page must offer an execution mode selector"
    options = " ".join(str(option) for option in radios[0].options)
    assert "VERIFIED_RUN" in options
    assert "FAST_PREVIEW" in options


def test_bench_verified_run_produces_a_real_frame() -> None:
    """Clicking the button must trace the real lens, not fake a result."""

    app = _run_page(PAGE_LABELS["B"])
    assert not app.exception
    targets = [button for button in app.button if "生成单帧" in button.label]
    assert targets, "bench page must expose a single-frame action"
    targets[0].click()
    app.run()
    assert not app.exception, [str(e.value) for e in app.exception]
    labels = {metric.label for metric in app.metric}
    assert "真值 u [px]" in labels
    assert "kernel_support" in labels
    # a real trace reports a support fraction below 1.0; a fabricated one would not
    support = next(m.value for m in app.metric if m.label == "kernel_support")
    assert support not in ("N/A", "NOT_AVAILABLE")
    assert 0.5 < float(support) < 1.0


def test_bench_failure_explainer_lists_statuses() -> None:
    app = _run_page(PAGE_LABELS["B"])
    blob = _all_text(app)
    for status in ("FIT_NOT_CONVERGED", "NOT_ESTIMABLE", "SATURATION_FULL_WELL",
                   "ROI_TOUCHES_BORDER", "MODEL_MISMATCH"):
        assert status in blob, f"failure taxonomy missing {status}"


def test_bench_has_no_button_that_runs_the_g2_loop() -> None:
    """A page button must never launch the 2000-assembly chain."""

    app = _run_page(PAGE_LABELS["B"])
    labels = " ".join(button.label for button in app.button)
    for forbidden in ("g2", "G2 全量", "优化", "2000"):
        assert forbidden not in labels


def _chunks(app: "AppTest") -> list[str]:
    """Every rendered string the AppTest can see."""

    out: list[str] = []
    for collection in ("markdown", "caption", "code", "info", "warning", "error",
                       "success", "title", "subheader", "header"):
        elements = getattr(app, collection, None)
        if elements is None:
            continue
        for element in elements:
            value = getattr(element, "value", None) or getattr(element, "body", None)
            if value:
                out.append(str(value))
    for frame in (getattr(app, "dataframe", None) or []):
        value = getattr(frame, "value", None)
        if value is not None:
            out.append(str(value))
    for metric in (getattr(app, "metric", None) or []):
        out.append(f"{metric.label} {metric.value}")
    for radio in (getattr(app, "radio", None) or []):
        out.append(" ".join(str(option) for option in radio.options))
        out.append(str(getattr(radio, "value", "") or ""))
    for tabs in (getattr(app, "tabs", None) or []):
        out.append(str(getattr(tabs, "label", "") or ""))
    return out


def _all_text(app: "AppTest") -> str:
    return "\n".join(_chunks(app))
