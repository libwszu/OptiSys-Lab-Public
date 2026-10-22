"""Page F - registered 976 nm multimode fiber pump case."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import streamlit as st

from optisys.jobs.service import JobService, JobState, default_jobs
from optisys.reports.report_service import ReportService


def _job_service(ctx) -> JobService:
    service = st.session_state.get("_g4_jobs")
    if service is None:
        service = JobService(
            ctx.project_root, python=str(ctx.python),
            jobs_dir=ctx.project_root / "artifacts" / "g4" / "jobs",
        )
        st.session_state["_g4_jobs"] = service
    return service


def _g4_runs(ctx) -> list[Path]:
    paths = []
    for path in ctx.runs_dir.iterdir() if ctx.runs_dir.is_dir() else []:
        if not path.is_dir() or path.name.startswith("_"):
            continue
        status_path = path / "run_status.json"
        if not status_path.is_file():
            continue
        try:
            status = json.loads(status_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if status.get("gate") == "G4":
            paths.append(path)
    return sorted(paths, key=lambda item: item.name, reverse=True)


def _preview_csv(path: Path, limit: int = 30) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))[:limit]


def render(ctx) -> None:
    st.title("976 nm 多模光纤泵浦光路")
    st.caption("G4 第二案例 · 真实几何计算 · 无绝对功率标定 · SIMULATED")
    st.info(
        "本页使用 G4 注册的光源、P0 薄透镜计算与 Optiland 0.6.3 P1 交叉核对。"
        "G2 旧案例的科学状态仍是 `QUALIFIED_ONLY`；两个案例的数据和结论分开。"
    )
    st.markdown("**当前继承状态：G2 `QUALIFIED_ONLY`** · G4 外部实测：`NOT_AVAILABLE`")

    st.subheader("注册的输入与假设")
    st.caption("参数来源均为 ASSUMED，除 976 nm 概念波长与既有配置给出的芯径/NA 外没有厂家料号。")
    st.dataframe([
        {"参数": "波长", "基线": "976 nm", "工程候选": "976 nm", "来源": "概念配置"},
        {"参数": "纤芯直径 / NA", "基线": "0.105 mm / 0.22", "工程候选": "0.105 mm / 0.22", "来源": "既有配置，未核手册"},
        {"参数": "L1 焦距 / 口径", "基线": "25 mm / Ø12 mm", "工程候选": "35 mm / Ø16 mm", "来源": "ASSUMED"},
        {"参数": "L2 焦距 / 口径", "基线": "100 mm / Ø12 mm", "工程候选": "100 mm / Ø17 mm", "来源": "ASSUMED"},
        {"参数": "源功率", "基线": "UNKNOWN", "工程候选": "UNKNOWN", "来源": "无辐射定标"},
        {"参数": "目标有效半径", "基线": "1.0 mm", "工程候选": "1.0 mm", "来源": "模型接收区，非晶体实测尺寸"},
    ], width="stretch", hide_index=True)
    st.caption("源角分布：均匀立体角；敏感性模型：sin(θ) 边缘偏重。两者均非实测模态分布。")

    st.subheader("启动注册的低成本演示")
    st.caption("任务在独立 JobService 子进程运行；可以取消，硬超时 300 s。低成本规模不会替代冻结的 100 装配 precheck/holdout。")
    rays = int(st.number_input("演示射线数", min_value=100, max_value=8192, value=1024, step=256))
    assemblies = int(st.number_input("每阶段装配数", min_value=2, max_value=100, value=10, step=2))
    spec = default_jobs(python=str(ctx.python))["pump976"]
    service = _job_service(ctx)
    if st.button("运行 G4 泵浦演示", type="primary"):
        try:
            record = service.start(spec, {
                "config": "configs/pump976_g4_l0.yaml",
                "candidate": "configs/pump976_g4_l1.yaml",
                "tolerance": "configs/pump976_g4_tolerance.yaml",
                "rays": rays, "assemblies": assemblies,
            })
            st.session_state["_g4_job_id"] = record.job_id
            st.success(f"已提交 `{record.job_id}` · 状态 `{record.state.value}`")
        except Exception as exc:  # noqa: BLE001 - visible rejection
            st.error(f"任务未提交：{type(exc).__name__}: {exc}")

    jobs = service.list_jobs()
    job_id = st.session_state.get("_g4_job_id")
    record = service.get(job_id) if job_id else None
    if record is not None:
        col1, col2, col3 = st.columns(3)
        col1.metric("任务状态", record.state.value)
        col2.metric("耗时 [s]", f"{record.wall_s:.2f}" if record.wall_s is not None else "—")
        col3.metric("峰值 RSS [MB]", f"{record.ram_peak_mb:.1f}" if record.ram_peak_mb else "—")
        if record.state not in {JobState.PASS, JobState.FAIL, JobState.TIMEOUT,
                                JobState.CANCELLED, JobState.ORPHANED,
                                JobState.DEPENDENCY_UNAVAILABLE}:
            if st.button("取消 G4 任务"):
                service.cancel(record.job_id)
                st.warning("已请求终止任务进程树；部分结果会标记 TIMEOUT/CANCELLED。")
        st.code(service.tail_log(record.job_id, lines=80) or "（暂无输出）", language="text")

    st.divider()
    runs = _g4_runs(ctx)
    if not runs:
        st.caption("尚无 G4 run。当前页只显示注册参数；没有模拟数据时不画占位图。")
        return
    selected = st.selectbox("查看 G4 run", [p.name for p in runs], key="g4_run_select")
    run_dir = ctx.runs_dir / selected
    status = json.loads((run_dir / "run_status.json").read_text(encoding="utf-8"))
    st.subheader(f"运行结果 · {selected}")
    st.json({k: status.get(k) for k in (
        "G4_ENGINEERING_EXECUTION_STATUS", "G4_OPTICAL_MODEL_VERIFICATION",
        "G4_TOLERANCE_EVALUATION_STATUS", "G4_EMPIRICAL_VALIDATION_STATUS",
        "G4_PORTFOLIO_DELIVERY_STATUS", "G4_AUDIT_STATUS", "G4_SCIENTIFIC_CLAIM",
        "INHERITED_G2_SCIENCE_STATUS", "open_issues")}, expanded=False)
    st.caption("通光率分母为全部源权重；spot 半径按到达目标有效区的传输权重条件化。密度单位不是 W/mm²。")
    nominal = _preview_csv(run_dir / "target_plane_metrics.csv", limit=12)
    if nominal:
        st.dataframe(nominal, width="stretch", hide_index=True)
    figures = sorted((run_dir / "figures").glob("*.png")) if (run_dir / "figures").is_dir() else []
    if figures:
        for figure in figures:
            st.image(str(figure), caption=figure.name, width="stretch")
    if st.button("生成离线 G4 报告", key="g4_report"):
        result = ctx.reports.build(run_dir, title=f"OptiSys-Lab G4 · {selected}")
        st.success(f"HTML: {result.html_path} · Markdown: {result.markdown_path}")
        st.caption(f"冻结运行未被改写：{result.frozen_run_untouched}")
    st.caption(f"run 路径：`{run_dir}`")
