"""Page A - project overview and evidence status.

Two status lines are shown separately and never merged:

1. the engineering execution record (what was run, and how it ended)
2. the science verdict (whether the registered procedure was followed)

Merging them into one green light is precisely what the task book forbids.
"""

from __future__ import annotations

import streamlit as st

from app.components import (
    demo_boundary_notice,
    metric_table,
    panel_deviation_notice,
    provenance_bar,
    science_banner,
)
from optisys.presentation.run_repository import load_run, load_latest_per_gate

GATE_ORDER = ("G0", "G1", "G2", "G3", "G4")


def render(ctx) -> None:
    st.title("项目总览与证据状态")
    st.caption(
        "OptiSys-Lab · 650 nm 三角测量 + 976 nm 多模泵浦 · 仿真，**无实测数据**"
    )

    science_banner(ctx.strip, compact=False)

    st.divider()
    _status_split(ctx)
    st.divider()
    _capability_matrix()
    st.divider()
    _run_selector(ctx)


def _status_split(ctx) -> None:
    st.subheader("两条独立的裁决线")
    st.caption(
        "工程执行状态与科学裁决状态**不是同一件事**，因此分两行显示，"
        "不合并为 `G3_ALL_PASS`。"
    )

    latest = load_latest_per_gate(ctx.runs_dir)
    left, right = st.columns(2)

    with left:
        st.markdown("**工程执行状态**")
        rows = []
        for gate in GATE_ORDER:
            summary = latest.get(gate)
            if summary is None:
                rows.append({"Gate": gate, "状态": "NOT_RUN", "run": "—",
                             "结束时间(UTC)": "—"})
                continue
            rows.append({
                "Gate": gate,
                "状态": summary.status,
                "run": summary.run_id,
                "结束时间(UTC)": summary.finished_at_utc or "—",
            })
        st.dataframe(rows, width="stretch", hide_index=True)
        st.caption("此表记录各 Gate 的工程运行状态，不把它合并为科学有效性结论。")

    with right:
        st.markdown("**科学裁决状态**")
        if ctx.strip.get("state") != "KNOWN":
            st.warning("UNKNOWN — 无法读取 `docs/g3/G2_INHERITANCE_VERDICT.json`")
            return
        rows = [
            {"项": "历史 G2 执行记录",
             "值": ctx.strip.get("historical_execution"),
             "含义": "冻结 run 记录的 status"},
            {"项": "预注册合规性",
             "值": ctx.strip.get("prereg_compliance"),
             "含义": "注册的四项门槛是否被遵守"},
            {"项": "as-run 数值核验",
             "值": ctx.strip.get("numerical_verification"),
             "含义": "126000 行明细能否独立重算"},
            {"项": "分层面板修复",
             "值": ctx.strip.get("stratified_repair"),
             "含义": "陈旧 design 复用缺陷是否修复并重算"},
            {"项": "允许的科学主张",
             "值": ctx.strip.get("claim_allowed"),
             "含义": "对外可用的最强表述"},
        ]
        st.dataframe(rows, width="stretch", hide_index=True)
        st.caption(
            "`original_prereg_compliance = FAIL` 与 `as_run_numerical_verification = PASS` "
            "**同时为真**：跑完了、数自洽，但没按预注册的规矩跑。"
        )


def _capability_matrix() -> None:
    st.subheader("已实现 / 未实现")
    rows = [
        {"功能": "G0 几何内核与向量-矩阵对照", "状态": "DONE", "证据": "冻结 run + 审计 ZIP"},
        {"功能": "G1 L0 成像/噪声/三定位器/标定", "状态": "DONE", "证据": "4 920 帧，冻结 run"},
        {"功能": "G2 L1 单透镜 + 公差 + 优化 + 留出验证", "状态": "DONE_WITH_QUALIFICATION",
         "证据": "126 000 行；但预注册未遵守"},
        {"功能": "G3 UI / 报告 / 审计包", "状态": "DONE", "证据": "原五页及冻结 G3 包"},
        {"功能": "G4 976 nm 多模泵浦", "状态": "SIMULATED", "证据": "独立 run / P0 与限定范围 P1 / 审计包"},
        {"功能": "实测标定 / 真实相机", "状态": "NOT_DONE", "证据": "全项目无实测数据"},
        {"功能": "消色差双胶合 / Scheimpflug 倾斜", "状态": "NOT_DONE", "证据": "未建模"},
        {"功能": "真实波前 PSF / 衍射传播", "状态": "NOT_DONE", "证据": "用几何足迹⊛标量 Airy 近似"},
        {"功能": "GPU 计算", "状态": "NOT_TESTED", "证据": "GTX 可见，但 torch 未安装"},
    ]
    st.dataframe(rows, width="stretch", hide_index=True)

    st.warning(
        "**证据层级上限 = SIMULATED / CROSS_CHECKED。** 本项目从未达到 "
        "`MEASURED` 或 `VALIDATED`。任何把这里的数字读作工业实测或量产收益的表述都是错的。"
    )


def _run_selector(ctx) -> None:
    st.subheader("历史冻结 run")
    run_dirs = ctx.run_dirs()
    if not run_dirs:
        st.caption("`runs/` 下没有可读的 run。")
        return

    labels = [p.name for p in run_dirs]
    default_index = max(0, labels.index(ctx.selected_run_id)) \
        if ctx.selected_run_id in labels else 0
    choice = st.selectbox("选择 run", labels, index=default_index, key="overview_run")
    if choice != ctx.selected_run_id:
        ctx.select_run(choice)

    summary = load_run(ctx.runs_dir / choice)
    provenance_bar(summary, extra_note=(
        "所有展示数据必须带 run_id / schema_version / model_level / units / "
        "evidence_level / status / source_sha256"
    ))
    demo_boundary_notice(summary)
    panel_deviation_notice(summary)

    st.markdown("**参数快照与环境**")
    col1, col2 = st.columns(2)
    with col1:
        st.json({
            "gate": summary.gate,
            "case_id": summary.case_id or "NOT_AVAILABLE",
            "model_level": summary.model_level,
            "frozen": summary.frozen,
            "git_commit": summary.git_commit,
            "config_sha256": summary.config_sha256,
            "source_tree_sha256": summary.source_tree_sha256,
        }, expanded=False)
    with col2:
        st.json({k: v for k, v in summary.counts.items() if v is not None}
                or {"note": "no counts"}, expanded=False)

    if summary.missing_reasons:
        st.warning("缺失项：" + "；".join(summary.missing_reasons))

    metric_table(summary, key_prefix=f"overview_{summary.run_id}")

    st.markdown("**报告**")
    _report_block(ctx, summary)


def _report_block(ctx, summary) -> None:
    existing = list((ctx.runs_dir / "_derived").glob(f"{summary.run_id}/*_report/report.html"))
    if existing:
        st.caption(f"已生成的派生报告：`{existing[-1]}`")
        if st.button("在浏览器中打开最新派生报告", key=f"open_{summary.run_id}"):
            st.session_state["_open_report"] = str(existing[-1])
            st.info(
                f"报告路径（只读副本，未修改冻结 run）：\n\n`{existing[-1]}`\n\n"
                "在文件管理器中打开该文件即可查看完整 HTML 报告。"
            )
    if st.button("生成 / 重建 HTML 报告", key=f"build_{summary.run_id}"):
        with st.spinner("渲染报告中（写入 runs/_derived/，不修改冻结 run）…"):
            result = ctx.reports.build(summary.path)
        st.success(
            f"已生成：`{result.html_path}`（{result.bytes_html} 字节）· "
            f"科学令牌 {len(result.science_tokens_present)}/4 · "
            f"冻结 run 未改动：{result.frozen_run_untouched}"
        )
        st.caption(f"PDF：{result.pdf_status} — {result.pdf_reason}")
        st.session_state["_open_report"] = str(result.html_path)

    open_path = st.session_state.get("_open_report")
    if open_path:
        st.caption(f"当前报告：`{open_path}`")
