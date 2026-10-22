"""Shared UI building blocks.

Every component that shows a number also shows provenance.  That is not
decoration: the task book requires ``run_id / schema_version / model_level /
units / evidence_level / status / source_sha256`` on every displayed value, and
the G2 inheritance verdict requires four status tokens on every G2 surface.

Rules enforced here:

* :func:`provenance_bar` is the only way a page renders data, so no page can
  forget the metadata.
* :func:`science_banner` degrades to ``UNKNOWN`` instead of disappearing when
  the verdict file is unreadable.
* :func:`metric_table` never sorts candidates by a single metric, and never
  labels one as "best".
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Sequence

import streamlit as st

from optisys.presentation.run_repository import RunSummary
from optisys.reports.report_service import SCIENCE_TOKENS

# ---------------------------------------------------------------------------
# light theme tokens - deliberately fixed, not theme-adaptive, because the
# printed report uses the same palette and the two must not disagree.
# ---------------------------------------------------------------------------
INK = "#1a1a1a"
MUTED = "#5b6470"
LINE = "#d8dee6"
PANEL = "#f6f8fa"
BAD_BG = "#fdeaea"
BAD_LINE = "#8b1a1a"
WARN_BG = "#fff4e0"
WARN_LINE = "#8a4b00"
OK_BG = "#eaf5ee"
OK_LINE = "#1c5c2e"

CANDIDATE_COLORS = {
    "baseline": "#7f7f7f",
    "nominal": "#1f4e79",
    "robust": "#a83232",
}


def science_banner(strip: dict[str, Any], *, compact: bool = False) -> None:
    """The mandatory status strip.  Never optional, never hidden."""

    if strip.get("state") != "KNOWN":
        st.warning(
            f"**科学状态 UNKNOWN** — 无法读取 G2 继承裁决："
            f"{strip.get('reason', 'unknown')}。"
            "在裁决可得之前，本页所有 G2 数字都不得被引用。"
        )
        return

    if compact:
        st.error(
            "**科学状态 QUALIFIED_ONLY** · 预注册合规 "
            f"`{strip.get('prereg_compliance')}` · 数值核验 "
            f"`{strip.get('numerical_verification')}` · 不是未受限的 PASS"
        )
        return

    st.error(
        "### 科学状态：QUALIFIED_ONLY — 不是未受限的 PASS\n"
        f"历史 G2 执行记为 `{strip.get('historical_execution')}`，"
        f"126 000 行明细可在 1e-9 容差内被完全独立重算"
        f"（`{strip.get('numerical_verification')}`）。"
        f"但预注册**未被遵守**（`original_prereg_compliance = "
        f"{strip.get('prereg_compliance')}`）。\n\n"
        "任何显示 G2 数字的界面、报告或简历材料都必须同屏携带下列令牌。"
    )
    tokens = strip.get("tokens") or []
    if tokens:
        cols = st.columns(min(len(tokens), 2))
        for index, token in enumerate(tokens):
            cols[index % len(cols)].code(token, language=None)


def provenance_bar(summary: RunSummary, *, extra_note: str = "") -> None:
    """The metadata line every data view must carry."""

    units = ", ".join(f"{k}={v}" for k, v in list(summary.units.items())[:5])
    top = st.columns(4)
    top[0].caption(f"**run_id** · `{summary.run_id}`")
    top[1].caption(f"**schema** · `{summary.schema_version}`")
    top[2].caption(f"**model_level** · `{summary.model_level}`")
    top[3].caption(f"**evidence** · `{summary.evidence.evidence_level}`")

    second = st.columns(4)
    second[0].caption(f"**status** · `{summary.status}`")
    second[1].caption(f"**scientific** · `{summary.scientific_status}`")
    second[2].caption(f"**units** · {units}")
    digest = summary.config_sha256 or "UNKNOWN"
    second[3].caption(f"**config sha256** · `{digest[:16]}…`")

    if extra_note:
        st.caption(extra_note)


def demo_boundary_notice(summary: RunSummary) -> None:
    """Say loudly that a demo run is not a G2 run."""

    if not summary.counts.get("demo"):
        return
    st.warning(
        "**这是 G3 演示 run（DEMO_ONLY）** · "
        f"装配数 {summary.counts.get('n_assemblies')} · "
        f"条件 {summary.counts.get('condition')} · "
        f"测试距离 {len(summary.counts.get('test_distances') or [])} 个。\n\n"
        "面板远小于 G2 的 2000 装配主面板，因此**不能**与 G2 数字比较，"
        "也**不能**用来确认或反驳 G2 结论。它只证明代码路径在本轮真实跑通了。"
    )


def panel_deviation_notice(summary: RunSummary) -> None:
    """G2_FINAL_PANEL_DEVIATION - shown wherever main-panel numbers appear."""

    if summary.gate != "G2" or summary.counts.get("demo"):
        return
    st.info(
        "**G2_FINAL_PANEL_DEVIATION** — 每候选 42 000 行 = "
        "2 000 装配 × 7 距离 × 3 估计器，是**估计器级记录**。"
        "预注册要求每装配 21 帧（7 距离 × 3 光照），as-run 主面板只有 "
        "**medium** 一档。所以主面板结论**不得**跨光照条件外推；"
        "strong/weak 仅存在于 200 装配的分层子集，且该子集在修复前是错误的。"
    )


def metric_table(
    summary: RunSummary,
    *,
    show_design: bool = True,
    key_prefix: str = "mt",
) -> None:
    """Three metrics side by side.  No ranking, no "best" badge."""

    if not summary.candidates:
        st.caption("该 run 没有候选级指标。")
        return

    rows = []
    for name, metrics in summary.candidates.items():
        row = {
            "候选": name,
            "尝试帧": metrics.n_attempted,
            "有效帧": metrics.n_valid,
            "失败率": _fmt_rate(metrics.failure_rate),
            "RMSE (mm)": _fmt_num(metrics.rmse_mm),
            "P95 (mm)": _fmt_num(metrics.p95_abs_mm),
            "bias (mm)": _fmt_num(metrics.bias_mm),
        }
        if show_design and metrics.design:
            design = metrics.design
            row["B (mm)"] = _fmt_num(design.get("baseline_mm"))
            row["f (mm)"] = _fmt_num(design.get("focal_length_mm"))
            row["θ (deg)"] = _fmt_num(design.get("theta_deg"))
        rows.append(row)

    st.dataframe(rows, width="stretch", hide_index=True, key=f"{key_prefix}_table")
    st.caption(
        "三指标**同屏**、**不排名**。robust 的 RMSE 最低但失败率最高，"
        "把二者压缩成单一分数会掩盖取舍（G2-07）。"
    )


def estimator_breakdown(summary: RunSummary, *, key_prefix: str = "est") -> None:
    """Per-estimator table, keeping gaussian_2d's high failure rate visible."""

    rows = []
    for name, metrics in summary.candidates.items():
        for estimator, sub in metrics.by_estimator.items():
            rows.append({
                "候选": name,
                "估计器": estimator,
                "有效帧": sub.n_valid,
                "失败率": _fmt_rate(sub.failure_rate),
                "RMSE (mm)": _fmt_num(sub.rmse_mm),
                "P95 (mm)": _fmt_num(sub.p95_abs_mm),
            })
    if not rows:
        st.caption("该 run 没有按估计器拆分的指标。")
        return
    st.dataframe(rows, width="stretch", hide_index=True, key=f"{key_prefix}_table")
    st.caption(
        "`gaussian_2d` 的高失败率源于 σ 下界 1.0 px 造成的 MODEL_MISMATCH，"
        "是**模型不匹配**而非传感器失效，不得读作系统失败率，也不得被过滤掉。"
    )


def failure_reason_explainer() -> None:
    """The failure taxonomy, used by both page B and page C."""

    st.markdown(
        """
| 状态 / 旗标 | 含义 | UI 必须做什么 |
|---|---|---|
| `OK` | 估计器收敛且标定可逆 | 显示数值 |
| `FIT_NOT_CONVERGED` | 高斯拟合未收敛 | 显示原因，**不填零** |
| `NOT_ESTIMABLE` | 标定反解在定义域外 | 显示原因，标为失败 |
| `SATURATION_FULL_WELL` | 峰值期望电子数超 full well | 显示饱和，不当成测量 |
| `SATURATION_ADC` | ADU 触顶 | 同上 |
| `ROI_TOUCHES_BORDER` | 光斑贴边/出界 | 显示越界，不裁掉 |
| `MODEL_MISMATCH` | 点采样高斯对有限核不适用 | 保留在表里，不替换估计器 |
| `LOW_SIGNAL` | SNR 过低 | 显示低信噪，不静默丢弃 |
"""
    )


def no_g4_notice() -> None:
    st.info(
        "976 nm 多模泵浦是独立的 G4 模拟案例，见页面 F。"
        "本页仍只展示三角测量主案例；G4 输出标记为 SIMULATED，不能当作实测或绝对功率。"
    )


def figures_gallery(summary: RunSummary, *, key_prefix: str = "fig") -> None:
    """Show run figures with their SHA-256 next to them."""

    figures = {k: v for k, v in summary.files.items() if k.startswith("figures/")}
    fig_dir = summary.path / "figures"
    if not fig_dir.is_dir():
        st.caption("该 run 没有图件目录。")
        return
    paths = sorted(fig_dir.glob("*.png"))
    if not paths:
        st.caption("该 run 没有图件。")
        return
    for path in paths:
        st.image(str(path), caption=path.name, width="stretch")
        digest = figures.get(f"figures/{path.name}")
        if digest:
            st.caption(f"`{digest}`")
    st.caption(
        "图件只做可视化，**不作为唯一数值证据**；所有数值均可从 CSV/JSON 重建。"
        "976 nm 泵浦光路结果在独立的 G4 页面和 run 中查看。"
    )


def _fmt_num(value: Any, digits: int = 4) -> str:
    if value is None:
        return "NOT_AVAILABLE"
    if isinstance(value, float):
        if value != value:
            return "NOT_AVAILABLE"
        return f"{value:.{digits}f}"
    return str(value)


def _fmt_rate(value: Any) -> str:
    if value is None or (isinstance(value, float) and value != value):
        return "NOT_AVAILABLE"
    return f"{float(value) * 100:.2f}%"


def render_tokens(tokens: Sequence[str] = SCIENCE_TOKENS) -> None:
    for token in tokens:
        st.code(token, language=None)


def path_open_hint(path: Path) -> None:
    """A file path the user can copy, rather than a fake download button."""

    st.code(str(path), language=None)
