"""Page E - usage guide and model boundaries.

This page is where a viewer is told what the project cannot do.  It is
deliberately not a marketing page.
"""

from __future__ import annotations

import streamlit as st

from app.components import no_g4_notice, render_tokens, science_banner

FIVE_MIN_STEPS = [
    ("0:00–0:45", "总览页",
     "两条裁决线分开显示：工程执行 PASS_RECORDED，科学裁决 QUALIFIED_ONLY。"
     "点开任一 run 看元数据条。"),
    ("0:45–1:45", "光斑实验台",
     "选 L1、Z=200 mm、medium，生成单帧；展示光斑、ROI、真值与三估计器结果。"),
    ("1:45–2:30", "异常情形",
     "把信号档位调到 strong 触发 full well 饱和；把 Z 推到量程边缘触发 ROI 越界。"
     "界面解释失败原因，**不填零**。"),
    ("2:30–3:45", "优化对照",
     "读取冻结 G2 数据：三指标同屏、Pareto 视图、A/B 不可比警告、"
     "分层面板显示 `SUSPENDED_PENDING_REVIEW`。"),
    ("3:45–4:30", "运行与证据中心",
     "提交一次 validate 或 demo 任务，看实时日志与 RSS；取消一次；"
     "在证据中心核对 manifest 与 SHA-256。"),
    ("4:30–5:00", "说明与边界",
     "明确说出：无实测、L1 近似、G4 的模型范围、预注册未遵守。"),
]


def render(ctx) -> None:
    st.title("使用说明与模型边界")
    st.caption("先看边界，再看功能。这个项目的能力上限写在下面，不在截图里。")

    science_banner(ctx.strip, compact=True)

    st.divider()
    st.subheader("5 分钟演示顺序")
    rows = [{"时间": t, "页面": p, "操作": d} for t, p, d in FIVE_MIN_STEPS]
    st.dataframe(rows, width="stretch", hide_index=True)
    st.caption(
        "该脚本不依赖运行 90 分钟仿真：全部使用已冻结的 G2 数据、已生成的演示 run、"
        "以及单帧交互生成。详见 `docs/g3/DEMO_SCRIPT_5MIN.md`。"
    )

    st.divider()
    st.subheader("坐标、单位与符号约定")
    st.markdown(
        """
- 物点 `O = (0,0,0)`，`+Z` 为光轴，`+X` 横向。
- 激光位于 `(B, 0, 0)`，方向 `(−sinθ, 0, cosθ)`。
- 内部单位：`mm / rad / pixel / s`。角度**只在配置层**用 `deg`，载入即转 `rad`。
- 像元位置 `u` 以像素为单位，`+u` 与 `+X` 同向；**UI 不修改像素方向符号**。
- 成像关系 `u(Z) = cx + fx·(B/Z − tanθ)`；导数 `dZ/du = −Z²/(fxB)`（负号，见 SD-001）。
"""
    )

    st.divider()
    st.subheader("L0 与 L1-approximate 的边界")
    st.markdown(
        """
| | L0 | L1-approximate |
|---|---|---|
| 像方 | 虚拟像平面，**不翻转** | 真实倒像 |
| 光学 | 针孔，解析 | 单透镜等凸 N-BK7，Optiland 真实追迹 |
| PSF | 无（点） | 几何足迹 ⊛ 标量 Airy 极限 |
| 用途 | 几何与标定链的独立对照 | G2/G3 的成像与误差统计 |

**关键限制**：PSF 是几何足迹与标量 Airy 圆盘的卷积近似，不是真实波前传播。
有限窗半宽上限 `max_half_px = 40`，窗宽 `= ceil(max|du|,|dv|) + 6·airy_radius + 1`。
这个近似直接导致 `kernel_support` 的结构上限约 0.972–0.991 —— 也就是 HC3 冲突的物理根源。
"""
    )

    st.divider()
    st.subheader("第三方库的实际贡献")
    st.markdown(
        """
- **Optiland 0.6.3**：提供真实光线追迹（折射面求交 + 折射定律）。这是本项目唯一
  非自研的核心光学计算，必须如实说明。
- **NumPy / SciPy**：数值与优化基底。
- **Matplotlib**：图件渲染。
- **Streamlit 1.66.0**：本 UI。
- 误差统计、标定模型（M1/M2）、优化器、约束、核生成、审计打包均为**自研**。

不得把 Optiland 的能力说成自研，也不得把自研的统计层说成「工业级光学设计软件」。
"""
    )

    st.divider()
    st.subheader("开放问题")
    verdict = ctx.verdict
    if verdict.get("available"):
        rows = [{
            "ID": issue.get("id"),
            "严重度": issue.get("severity"),
            "问题": issue.get("title"),
            "状态": issue.get("status"),
        } for issue in verdict.get("open_issues", [])]
        st.dataframe(rows, width="stretch", hide_index=True)
    else:
        st.warning(f"裁决不可读：{verdict.get('reason')}")

    st.divider()
    st.subheader("必须同屏携带的状态令牌")
    render_tokens()

    st.divider()
    st.subheader("明确未做的事")
    st.markdown(
        """
- **无实测数据**：没有真实相机、没有真实镜头标定，全部为仿真。
- **G4（976 nm 多模泵浦）已实现仿真案例**，但没有 976 nm 实测或绝对功率标定，P0 与 P1 在 NA=0.22 的结果有显著模型差异。
- 消色差双胶合、Scheimpflug 倾斜、真实波前 PSF：未做。
- Strategy A/B 的配对 bootstrap：`NOT_RUN`（预算）。
- 为求漂亮数值重跑 G2：**禁止**，本轮未做。
- 演示视频：`NOT_DELIVERED`（录不到就不放占位链接）。
- PDF 导出：`NOT_DELIVERED`（未安装任何 PDF 渲染器）。
"""
    )

    st.divider()
    no_g4_notice()

    st.divider()
    st.subheader("复现命令")
    st.code(
        ".venv\\Scripts\\python.exe -m optisys validate --config configs/g3_demo.yaml\n"
        ".venv\\Scripts\\python.exe -m optisys g3-demo --assemblies 12\n"
        ".venv\\Scripts\\python.exe -m optisys pump976 --rays 1024 --assemblies 10\n"
        ".venv\\Scripts\\python.exe -m optisys report --run runs/<run_id>\n"
        ".venv\\Scripts\\python.exe -m pytest -q\n"
        ".venv\\Scripts\\python.exe scripts/verify_g3_release.py",
        language="powershell",
    )
    st.caption(
        "所有命令都不修改已冻结的 G0/G1/G2 证据；派生输出写入 "
        "`runs/_derived/<run_id>/`。"
    )
