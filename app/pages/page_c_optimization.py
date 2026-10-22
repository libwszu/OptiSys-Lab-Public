"""Page C - optimisation, tolerance and calibration-strategy comparison.

Reads the **frozen** G2 result.  Nothing on this page re-optimises, re-fits or
re-scores: the task book forbids a page switch from launching the G2 loop, and
a UI that silently recomputes would be able to produce numbers that disagree
with the frozen evidence.

Two things are deliberately *not* offered:

* an auto-selected winner (robust wins RMSE and loses failure rate),
* a "recalibration gain" figure (A and B are not directly comparable; the
  paired bootstrap is NOT_RUN).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import streamlit as st

from app.components import (
    CANDIDATE_COLORS,
    estimator_breakdown,
    metric_table,
    panel_deviation_notice,
    provenance_bar,
    science_banner,
)
from app.components.plotting import apply as apply_plot_style
from optisys.presentation.run_repository import CANDIDATE_ORDER, ESTIMATOR_ORDER, load_run


def render(ctx) -> None:
    st.title("优化、公差与校准策略对照")
    st.caption(
        "本页只读**已冻结**的 G2 数据。切换筛选不会触发重新优化、重新拟合或重新评分。"
    )
    apply_plot_style()
    science_banner(ctx.strip, compact=True)

    summary = _pick_g2(ctx)
    if summary is None:
        return

    provenance_bar(summary, extra_note="数据源：frozen run（只读）")
    panel_deviation_notice(summary)

    st.divider()
    tabs = st.tabs(["三指标对照", "Pareto 取舍", "距离分组", "估计器",
                    "标定策略 A/B", "分层面板"])
    with tabs[0]:
        _tab_metrics(summary)
    with tabs[1]:
        _tab_pareto(summary)
    with tabs[2]:
        _tab_by_distance(summary)
    with tabs[3]:
        _tab_estimators(summary)
    with tabs[4]:
        _tab_strategies(summary)
    with tabs[5]:
        _tab_stratified(summary)


def _pick_g2(ctx):
    """Always the frozen G2 run; no fallback to a demo run."""

    for path in ctx.run_dirs():
        try:
            summary = load_run(path)
        except Exception:  # noqa: BLE001
            continue
        if summary.gate == "G2" and not summary.counts.get("demo"):
            if summary.status != "PASS":
                st.warning(
                    f"该 G2 run 的记录状态为 `{summary.status}`，"
                    "其数字不应作为结论使用。"
                )
            return summary
    st.error(
        "未找到可读的 G2 冻结 run。本页**不会**用演示 run 替代 G2 数据。"
    )
    return None


def _tab_metrics(summary) -> None:
    st.subheader("RMSE / P95 / 失败率 同屏")
    metric_table(summary, key_prefix="pageC_main")
    st.caption(
        "刻意**不**按 RMSE 排序，也**不**标「最优」。"
        "robust 的 RMSE 最低、失败率最高，这是一次取舍而不是一次胜出。"
    )

    ci = _load_ci(summary)
    if ci:
        st.subheader("配对比较（共同有效帧口径）")
        rows = []
        for pair, payload in sorted(ci.items()):
            if not isinstance(payload, dict):
                continue
            for metric in ("rmse", "failure_rate"):
                block = payload.get(metric)
                if not isinstance(block, dict):
                    continue
                rows.append({
                    "配对": pair,
                    "指标": metric,
                    "Δ": _f(block.get("delta")),
                    "95% CI": f"[{_f(block.get('ci_low'))}, {_f(block.get('ci_high'))}]",
                    "排除 0": "是" if block.get("excludes_zero") else "否",
                    "装配数": block.get("n_assemblies"),
                })
        if rows:
            st.dataframe(rows, width="stretch", hide_index=True)
        st.caption(
            "配对口径只在**两候选都有效**的共同帧上计算 RMSE，"
            "与上表的**全尝试帧**口径分母不同，数值不可混用。"
            "CI 排除 0 只说明差异方向稳定，不说明工程可用。"
        )
    else:
        st.caption("该 run 无 `ci_results.json`，配对比较 NOT_AVAILABLE。")


def _tab_pareto(summary) -> None:
    st.subheader("精度 vs 测量成功率")
    st.caption(
        "x 轴 RMSE（越低越好），y 轴有效帧占比（越高越好）。"
        "两者不能同时最优时，本页**不**替你选。"
    )
    if not summary.candidates:
        st.caption("无候选数据。")
        return

    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6.4, 3.6), dpi=140)
    for name in CANDIDATE_ORDER:
        metrics = summary.candidates.get(name)
        if metrics is None or metrics.rmse_mm is None:
            continue
        success = 1.0 - (metrics.failure_rate or 0.0)
        ax.scatter(metrics.rmse_mm, success * 100, s=90,
                   color=CANDIDATE_COLORS.get(name, "#333"), label=name, zorder=3)
        ax.annotate(f"{name}\nRMSE {metrics.rmse_mm:.2f} mm\n"
                    f"成功率 {success * 100:.1f}%",
                    (metrics.rmse_mm, success * 100),
                    textcoords="offset points", xytext=(8, -4), fontsize=7)
    ax.set_xlabel("RMSE [mm]  ← 更好", fontsize=8)
    ax.set_ylabel("有效帧占比 [%]  ↑ 更好", fontsize=8)
    ax.set_title("精度–成功率取舍（无单一最优）", fontsize=10)
    ax.grid(True, color="#d8dee6", linewidth=0.6, alpha=0.8)
    ax.set_axisbelow(True)
    ax.tick_params(labelsize=7)
    fig.tight_layout()
    st.pyplot(fig, width="stretch")
    plt.close(fig)

    st.caption(
        "Pareto 视图的意义在于：如果某候选同时更准且更少失败，它才占优。"
        "本例中 robust 更准但更常失败，因此不在任何一维上占优。"
    )


def _tab_by_distance(summary) -> None:
    st.subheader("距离分组曲线")
    if not summary.candidates:
        st.caption("无候选数据。")
        return
    available = [n for n, m in summary.candidates.items() if m.by_distance]
    if not available:
        st.caption("该 run 没有按距离拆分的指标。")
        return

    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(9.6, 3.2), dpi=140)
    for name in CANDIDATE_ORDER:
        metrics = summary.candidates.get(name)
        if metrics is None or not metrics.by_distance:
            continue
        rows = sorted(metrics.by_distance, key=lambda r: r.get("distance_mm") or 0)
        z = [r.get("distance_mm") for r in rows]
        rmse = [r.get("rmse_mm") if r.get("rmse_mm") is not None else np.nan for r in rows]
        fail = [r.get("failure_rate") if r.get("failure_rate") is not None else np.nan
                for r in rows]
        color = CANDIDATE_COLORS.get(name, "#333")
        axes[0].plot(z, rmse, marker="o", markersize=3, linewidth=1.3, color=color,
                     label=name)
        axes[1].plot(z, fail, marker="o", markersize=3, linewidth=1.3, color=color,
                     label=name)

    for ax, label in ((axes[0], "RMSE [mm]"), (axes[1], "失败率")):
        ax.set_xlabel("Z [mm]", fontsize=8)
        ax.set_ylabel(label, fontsize=8)
        ax.grid(True, color="#d8dee6", linewidth=0.6, alpha=0.8)
        ax.set_axisbelow(True)
        ax.tick_params(labelsize=7)
        ax.legend(fontsize=7)
    axes[0].set_title("RMSE vs 距离", fontsize=10)
    axes[1].set_title("失败率 vs 距离", fontsize=10)
    fig.suptitle("同屏显示精度与失败率：只画 RMSE 会掩盖失败", fontsize=9)
    fig.tight_layout()
    st.pyplot(fig, width="stretch")
    plt.close(fig)

    st.caption(
        "失败率随距离变化通常比 RMSE 更陡。任何「某距离段可用」的结论必须两侧同时看。"
    )


def _tab_estimators(summary) -> None:
    st.subheader("估计器拆分")
    estimator_breakdown(summary, key_prefix="pageC_est")
    st.caption(
        "`gaussian_2d` 的历史高失败率被**保留**显示，未被过滤，"
        "选中的估计器也未被自动替换成表现更好的那个。"
    )


def _tab_strategies(summary) -> None:
    st.subheader("Strategy A / B")
    st.error(
        "**NOT_DIRECTLY_COMPARABLE** — A = 2 000 装配 × 3 估计器 × 0 校准帧；"
        "B = 200 装配 × 1 估计器 × 9 校准帧。\n\n"
        "把 A 的一个数与 B 的一个数相减会混合不同总体、不同估计器集合与不同标定机制。"
        "原报告中「重标定值约 1.5 mm 到 3 mm」的表述**已撤回**。"
    )

    b_path = summary.path / "independent_validation"
    payload = _load_json(b_path / "summary.json").get("strategy_b") or {}
    if payload:
        rows = []
        for name in CANDIDATE_ORDER:
            block = payload.get(name) or {}
            overall = block.get("overall", block)
            rows.append({
                "候选": name,
                "B 装配数": 200,
                "B 估计器数": 1,
                "B 有效帧": overall.get("n_valid"),
                "B 失败率": _rate(overall.get("failure_rate")),
                "B RMSE [mm]": _f(overall.get("rmse_mm")),
            })
        st.dataframe(rows, width="stretch", hide_index=True)
        st.caption(
            "对照上表 A 的 2 000 装配 / 3 估计器。B 只覆盖 A 的 200 个装配，"
            "且只用一个估计器，因此这不是配对检验。"
        )
    else:
        st.caption("该 run 无 Strategy B 汇总。")

    st.warning(
        "**「重标定量化收益」模块：DISABLED。**\n\n"
        "该模块只有在完成 PRE-G3-05 要求的同口径配对比较后才允许启用。"
        "最小诚实比较是在 200 个共享装配上做同估计器的配对 A/B bootstrap，"
        "本轮状态 `NOT_RUN`（预算受限，且 A 侧没有该 200 子集的逐样本结果）。\n\n"
        "未完成不等于不可能；但未完成时给出收益数字就是造假。"
    )
    st.caption(
        "校准帧数勘误：报告曾写每单元 5 帧，代码非 quick 路径实际取 9 帧。"
        "**报告文字错、代码对**，Strategy B 的成本因此被低估了 80%。"
    )


def _tab_stratified(summary) -> None:
    st.subheader("条件分层面板")

    artifact_dir = Path("artifacts/g3/pre/stratified_repair")
    repaired = artifact_dir / "stratified_repair.json"
    if repaired.is_file():
        st.success(
            "该面板的陈旧 design 复用缺陷**已修复并重算**（PRE-G3-03）。"
            "下方为修复后的数字；旧数字一并列出以便核对，不做覆盖。"
        )
        _render_repaired(artifact_dir)
    else:
        st.error(
            "**SUSPENDED_PENDING_REVIEW**\n\n"
            "分层面板存在陈旧 design 复用缺陷（`_final_stage` 复用了 Strategy B "
            "遗留的 robust 几何），且尚未完成重算，因此**不予展示**。\n\n"
            "按 G3-D-006，不通过删除该面板来「解决」问题；按 G3-D-009，"
            "修复完成前状态为 `SUSPENDED_PENDING_REVIEW`。"
        )

    old = summary.path / "independent_validation"
    old_files = sorted(old.glob("stratified_*.csv"))
    if old_files:
        with st.expander("冻结 run 内的旧分层面板文件（保留不删）"):
            for path in old_files:
                st.code(str(path), language=None)
            st.caption(
                "这些文件保留为历史证据。它们对 baseline 与 nominal **不携带"
                "候选专属信息**，因为整段面板是用 robust 几何渲染的。"
            )


def _render_repaired(artifact_dir: Path) -> None:
    payload = _load_json(artifact_dir / "stratified_repair.json")
    if not payload:
        st.caption("重算产物不可读。")
        return

    st.caption(
        f"重算：{payload.get('n_assemblies')} 装配 × {payload.get('n_distances')} 距离 × "
        f"{len(payload.get('conditions') or [])} 条件 × "
        f"{len(payload.get('estimators') or [])} 估计器 · "
        f"命名空间 `{payload.get('namespace')}` · "
        f"实测 {payload.get('wall_s'):.1f} s（预算 600 s，**超支 3.16×**，已记录）"
    )

    comparison = payload.get("comparison") or []
    if comparison:
        rows = []
        for item in comparison:
            rows.append({
                "候选": item.get("candidate"),
                "条件": item.get("condition"),
                "旧 RMSE": _f(item.get("old_rmse_mm")),
                "新 RMSE": _f(item.get("new_rmse_mm")),
                "Δ RMSE": _f(item.get("rmse_delta_mm")),
                "旧失败率": _rate(item.get("old_failure_rate")),
                "新失败率": _rate(item.get("new_failure_rate")),
                "Δ 失败率": _rate(item.get("failure_delta")),
            })
        st.dataframe(rows, width="stretch", hide_index=True)
        st.caption(
            "robust 的 Δ 恒为 0.0 —— 因为被错误复用的几何恰好就是 robust 自己的几何，"
            "缺陷对它是「错得正好」。baseline 与 nominal 的数字变化巨大，"
            "说明旧面板对它们完全失效。"
        )

    st.warning(
        "**由旧面板得出的结论一律撤回。** 任何形如「候选 X 在强光下表现差」的表述，"
        "若来自修复前的分层面板，都不成立。\n\n"
        "修复后候选确实分开了：nominal 的 weak RMSE 升到 6.54 mm，"
        "baseline weak 为 3.08 mm。分层条件没能挽救 nominal。"
    )


def _load_ci(summary) -> dict[str, Any]:
    path = summary.path / "independent_validation" / "ci_results.json"
    return _load_json(path)


def _load_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _f(value: Any) -> str:
    if value is None:
        return "NOT_AVAILABLE"
    if isinstance(value, (int, float)):
        return f"{float(value):.4f}"
    return str(value)


def _rate(value: Any) -> str:
    if value is None:
        return "NOT_AVAILABLE"
    return f"{float(value) * 100:.2f}%"