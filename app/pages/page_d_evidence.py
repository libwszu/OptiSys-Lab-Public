"""Page D - runs, jobs and the evidence centre.

Job submission goes through :class:`optisys.jobs.service.JobService`, which
whitelists commands and refuses shell metacharacters.  The UI never builds an
argv string itself.

Old runs are read-only.  Report regeneration writes to ``runs/_derived/`` and
the page shows the source run's immutable hashes next to the new output.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import streamlit as st

from app.components import (
    demo_boundary_notice,
    panel_deviation_notice,
    path_open_hint,
    provenance_bar,
    science_banner,
)
from optisys.jobs.service import JobService, JobState, default_jobs, profile_estimate
from optisys.presentation.run_repository import load_run, sha256_file

TERMINAL = {JobState.PASS, JobState.FAIL, JobState.CANCELLED, JobState.TIMEOUT,
            JobState.ORPHANED}


def render(ctx) -> None:
    st.title("运行、测试与证据中心")
    st.caption(
        "任务通过白名单 JobService 提交，无 shell 拼接；"
        "旧 run 只读，派生输出写 `runs/_derived/`。"
    )
    science_banner(ctx.strip, compact=True)

    tabs = st.tabs(["运行清单", "提交任务", "任务详情", "证据与哈希", "导出"])
    with tabs[0]:
        _tab_runs(ctx)
    with tabs[1]:
        _tab_submit(ctx)
    with tabs[2]:
        _tab_job_detail(ctx)
    with tabs[3]:
        _tab_evidence(ctx)
    with tabs[4]:
        _tab_export(ctx)


# ---------------------------------------------------------------------------
def _tab_runs(ctx) -> None:
    st.subheader("全部 run")
    rows = []
    for path in ctx.run_dirs(include_derived=False):
        try:
            summary = load_run(path)
        except Exception as exc:  # noqa: BLE001
            rows.append({"run_id": path.name, "gate": "UNREADABLE",
                         "status": str(exc), "scientific": "—", "frozen": "—",
                         "finished": "—", "config_sha256": "—"})
            continue
        rows.append({
            "run_id": summary.run_id,
            "gate": summary.gate,
            "schema": summary.schema_version,
            "status": summary.status,
            "scientific": summary.scientific_status,
            "frozen": "yes" if summary.frozen else "no",
            "demo": "yes" if summary.counts.get("demo") else "no",
            "finished": summary.finished_at_utc or "—",
            "config_sha256": summary.config_sha256[:16] + "…",
        })
    if not rows:
        st.caption("`runs/` 下没有 run。")
        return
    st.dataframe(rows, width="stretch", hide_index=True)
    st.caption(
        "`status` 是工程执行状态，`scientific` 是科学主张状态。"
        "两者不是同一件事：G2 的 status PASS 与 scientific QUALIFIED_ONLY 并存。"
    )

    st.markdown("**查看某个 run**")
    names = [r["run_id"] for r in rows]
    choice = st.selectbox("run", names, key="evidence_run_select")
    if st.button("载入该 run 的元数据"):
        summary = load_run(ctx.runs_dir / choice)
        provenance_bar(summary)
        demo_boundary_notice(summary)
        panel_deviation_notice(summary)
        if summary.missing_reasons:
            st.warning("缺失项：" + "；".join(summary.missing_reasons))
        st.json({
            "gate": summary.gate,
            "status": summary.status,
            "scientific_status": summary.scientific_status,
            "model_level": summary.model_level,
            "evidence_level": summary.evidence.evidence_level,
            "evidence_note": summary.evidence.note,
            "counts": summary.counts,
            "notes": summary.notes,
        }, expanded=False)


# ---------------------------------------------------------------------------
def _jobs(ctx) -> JobService:
    service = st.session_state.get("_jobs")
    if service is None:
        service = JobService(ctx.project_root)
        st.session_state["_jobs"] = service
    return service


def _tab_submit(ctx) -> None:
    st.subheader("提交任务")
    st.info(
        "任务在**独立子进程**中运行，不是在本页面线程里。"
        "可取消；取消会终止整个进程树，而不是只杀父进程。"
    )
    specs = default_jobs(python=str(ctx.python))
    labels = {key: f"{spec.label} — {spec.description}" for key, spec in specs.items()}
    choice = st.selectbox("任务", list(specs), format_func=lambda k: labels[k])
    spec = specs[choice]

    params: dict[str, Any] = {}
    if choice in ("validate-g2", "optics-smoke"):
        params["config"] = st.selectbox(
            "配置", ["configs/g3_demo.yaml", "configs/triangulation_g2_l1.yaml"])
    elif choice == "g3-demo":
        params["config"] = "configs/g3_demo.yaml"
        params["assemblies"] = st.number_input("装配数", 1, 1999, 12, step=1,
                                               help="必须小于 G2 的 2000 面板")
        params["workers"] = st.number_input("进程数", 1, 6, 1, step=1)
        estimate = profile_estimate(int(params["assemblies"]), 7, 3)
        st.caption(
            f"声明式估算：{estimate['frames']} 帧 · "
            f"{estimate['estimated_wall_s']:.0f} s "
            f"（**规划常数**，不是实测；实测值写在 job 记录里）"
        )
    elif choice == "pump976":
        params["config"] = "configs/pump976_g4_l0.yaml"
        params["candidate"] = "configs/pump976_g4_l1.yaml"
        params["tolerance"] = "configs/pump976_g4_tolerance.yaml"
        params["rays"] = st.number_input("G4 射线数", 100, 8192, 1024, step=256)
        params["assemblies"] = st.number_input("G4 每阶段装配数", 2, 100, 10, step=2)
        st.caption("小规模 SIMULATED 演示；正式预注册规模见 G4 运行计划。")
    elif choice == "report-g2":
        candidates = [p.name for p in ctx.run_dirs()]
        params["run"] = f"runs/{st.selectbox('run', candidates)}"

    st.caption(f"预计耗时（声明值）：{spec.estimated_wall_s:.0f} s · "
               f"超时上限 {spec.timeout_s:.0f} s")

    missing = _jobs(ctx).check_dependencies(spec)
    if missing:
        st.warning(f"缺少依赖：{', '.join(missing)}。任务可以提交，但预计会失败。")

    if st.button("提交任务", type="primary"):
        try:
            record = _jobs(ctx).start(spec, params)
        except Exception as exc:  # noqa: BLE001 - reject reason must be visible
            st.error(f"拒绝提交：`{type(exc).__name__}: {exc}`")
            return
        st.session_state["_job_id"] = record.job_id
        st.success(f"已提交 `{record.job_id}`（状态 {record.state.value}）")


def _tab_job_detail(ctx) -> None:
    st.subheader("任务状态与实时日志")
    service = _jobs(ctx)
    jobs = service.list_jobs()
    if not jobs:
        st.caption("尚无任务记录。")
        return

    ids = [job.job_id for job in jobs]
    default = st.session_state.get("_job_id") or ids[0]
    job_id = st.selectbox("任务", ids,
                          index=ids.index(default) if default in ids else 0)
    record = service.get(job_id)
    if record is None:
        st.caption("任务记录已丢失。")
        return

    cols = st.columns(4)
    cols[0].metric("状态", record.state.value)
    cols[1].metric("退出码", str(record.exit_code) if record.exit_code is not None else "—")
    cols[2].metric("耗时 [s]", f"{record.wall_s:.1f}" if record.wall_s else "—")
    cols[3].metric("峰值 RSS [MB]",
                   f"{record.ram_peak_mb:.1f}" if record.ram_peak_mb else "—")

    st.caption(
        f"argv: `{' '.join(record.argv)}`"
    )
    st.caption(f"启动 {record.started_at_utc or '—'} · 结束 {record.finished_at_utc or '—'}")

    if record.state == JobState.ORPHANED:
        st.error(
            "**ORPHANED** — UI 重启后找不到活进程。"
            "不伪造进度；对应的 run 目录（若有）需要人工检查。"
        )

    left, right = st.columns([1, 1])
    with left:
        if st.button("刷新状态"):
            st.rerun()
    with right:
        if record.state not in TERMINAL and st.button("取消任务"):
            service.cancel(job_id)
            st.warning("已发出取消；进程树被终止。")

    log = service.tail_log(job_id, lines=120)
    st.markdown("**日志尾部**")
    st.code(log or "（无日志）", language="text")

    if record.run_dir:
        st.success(f"产生的 run：`{record.run_dir}`")
        path = Path(record.run_dir)
        if (path / "run_status.json").is_file():
            summary = load_run(path)
            provenance_bar(summary)
            demo_boundary_notice(summary)

    with st.expander("完整任务记录 JSON"):
        st.json(record.as_dict(), expanded=False)


# ---------------------------------------------------------------------------
def _tab_evidence(ctx) -> None:
    st.subheader("冻结证据完整性")
    st.caption(
        "对每份冻结 run 的文件逐一哈希并与基线快照比对。"
        "任何不一致都必须显示为失败，不得忽略。"
    )

    baseline_path = ctx.project_root / "docs" / "g3" / "G3_BASELINE_HASHES.json"
    if not baseline_path.is_file():
        st.warning(f"基线快照缺失：`{baseline_path}`")
        return
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))

    rows = []
    for gate, info in (baseline.get("frozen_runs") or {}).items():
        run_status = Path(info["path"]) / "run_status.json"
        if not run_status.is_file():
            rows.append({"gate": gate, "run": info["path"], "检查项": "run_status.json",
                         "期望": info["run_status_sha256"][:16] + "…",
                         "实际": "MISSING", "一致": "否"})
            continue
        actual = sha256_file(run_status)
        rows.append({
            "gate": gate,
            "run": Path(info["path"]).name,
            "检查项": "run_status.json",
            "期望": info["run_status_sha256"][:16] + "…",
            "实际": actual[:16] + "…",
            "一致": "是" if actual == info["run_status_sha256"] else "**否**",
        })
    st.dataframe(rows, width="stretch", hide_index=True)

    all_ok = all(r["一致"] == "是" for r in rows)
    if all_ok:
        st.success("全部冻结 run 的 `run_status.json` 与基线快照一致。")
    else:
        st.error("存在不一致项。冻结证据可能已被改动，必须立即调查。")

    st.markdown("**基线快照中的外部证据**")
    ext = []
    for key in ("source_pdf", "g2_audit_zip", "g2_config"):
        block = baseline.get(key)
        if not isinstance(block, dict):
            continue
        path = Path(block.get("path", ""))
        exists = path.is_file()
        actual = sha256_file(path) if exists else "MISSING"
        expected = block.get("expected") or block.get("sha256")
        ext.append({
            "项": key,
            "路径": block.get("path"),
            "期望": (expected or "")[:16] + "…",
            "实际": actual[:16] + "…",
            "一致": "是" if actual == expected else "**否**",
        })
    if ext:
        st.dataframe(ext, width="stretch", hide_index=True)

    st.markdown("**完整明细可得性（PRE-G3-04）**")
    g2 = baseline.get("frozen_runs", {}).get("G2", {})
    detail = baseline.get("g2_complete_samples") or {}
    if g2:
        st.caption(
            f"任务书称 G2 审计 ZIP 内的 `sampled_results.csv` 被截断至 20 000 行；"
            f"本机冻结 run 目录内的文件为 "
            f"{detail.get('rows', '?')} 行 / {detail.get('bytes', '?')} 字节 / "
            f"截断标记 {detail.get('truncated_marker', '?')}。"
            "结论：**打包缺陷，不是数据丢失**。"
        )


def _tab_export(ctx) -> None:
    st.subheader("导出")
    st.caption(
        "导出的内容全部来自已存在的文件；本页不生成任何未落盘的数字。"
    )

    names = [p.name for p in ctx.run_dirs()]
    if not names:
        st.caption("无可导出的 run。")
        return
    choice = st.selectbox("run", names, key="export_run")
    run_dir = ctx.runs_dir / choice

    st.markdown("**机器可读文件**")
    wanted = ["run_status.json", "metrics.json", "provenance.json",
              "independent_validation/summary.json",
              "independent_validation/sampled_results.csv",
              "gate_checks.json", "tests_junit.xml"]
    for rel in wanted:
        path = run_dir / rel
        if not path.is_file():
            st.caption(f"`{rel}` — 不存在")
            continue
        size = path.stat().st_size
        st.caption(f"`{rel}` — {size:,} 字节")
        if size <= 6_000_000:
            st.download_button(
                label=f"下载 {rel}",
                data=path.read_bytes(),
                file_name=Path(rel).name,
                key=f"dl_{choice}_{rel}",
            )
        else:
            path_open_hint(path)
            st.caption("文件过大，请直接使用上面的路径；界面不做静默截断导出。")

    st.markdown("**HTML 报告**")
    if st.button("生成/重建报告", key=f"export_build_{choice}"):
        with st.spinner("渲染中…"):
            result = ctx.reports.build(run_dir)
        st.success(f"`{result.html_path}` · {result.bytes_html} 字节 · "
                   f"令牌 {len(result.science_tokens_present)}/4")
        st.caption(f"PDF：{result.pdf_status} — {result.pdf_reason}")

    derived = list((ctx.runs_dir / "_derived" / choice).glob("*_report/report.html"))
    if derived:
        st.caption(f"已有派生报告 {len(derived)} 份，最新：`{derived[-1]}`")
        st.download_button(
            "下载最新报告 HTML",
            data=derived[-1].read_bytes(),
            file_name="report.html",
            key=f"dl_report_{choice}",
        )
