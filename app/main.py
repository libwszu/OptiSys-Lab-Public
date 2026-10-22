"""OptiSys-Lab G4 - Streamlit entry point (thin control layer).

Run with::

    .venv\\Scripts\\python.exe -m streamlit run app/main.py

Why Streamlit
-------------
Decision G3-D-002.  The project is CLI + run directory + JSON/CSV; Streamlit can
read that in place with no Qt build chain and no packaging step, and
``streamlit run`` is a single command.  A PySide6 build would need a rebuilt
thread model for the job service and a packaging pipeline, which conflicts with
the "runnable in 5 minutes" requirement.

What main.py does NOT do
------------------------
It does not compute anything.  Every number on screen comes from
``RunRepository``, ``JobService`` or ``ReportService``; the pages are layout
only, and they cannot import the G2 optimisation loop.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

# make ``app`` importable when Streamlit executes this file as a script
_APP_DIR = Path(__file__).resolve().parent
_ROOT = _APP_DIR.parent
for _path in (str(_ROOT), str(_ROOT / "src")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

from app.pages import (  # noqa: E402
    page_a_overview,
    page_b_bench,
    page_c_optimization,
    page_d_evidence,
    page_e_about,
    page_f_pump976,
)
from app.ui_context import build_context  # noqa: E402

PAGES = {
    "A · 项目总览与证据状态": page_a_overview,
    "B · 光斑实验台": page_b_bench,
    "C · 优化对照": page_c_optimization,
    "D · 运行与证据中心": page_d_evidence,
    "E · 说明与边界": page_e_about,
    "F · 976 nm 泵浦光路": page_f_pump976,
}

_PAGE_CSS = """
<style>
  .block-container { padding-top: 2.2rem; max-width: 1180px; }
  h1 { letter-spacing: -0.01em; }
  div[data-testid="stMetricValue"] { font-size: 1.28rem; }
  code { font-size: 0.84em; }
</style>
"""


def main() -> None:
    st.set_page_config(
        page_title="OptiSys-Lab G4",
        page_icon="◐",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    st.markdown(_PAGE_CSS, unsafe_allow_html=True)

    ctx = build_context()
    _sidebar(ctx)

    page = st.session_state.get("_page", list(PAGES)[0])
    module = PAGES.get(page, page_a_overview)
    module.render(ctx)

    _footer(ctx)


def _sidebar(ctx) -> None:
    with st.sidebar:
        st.markdown("### OptiSys-Lab")
        st.caption("650 nm 三角测量 + 976 nm 多模泵浦 · G4 仿真")
        st.divider()

        options = list(PAGES)
        current = st.session_state.get("_page", options[0])
        index = options.index(current) if current in options else 0
        choice = st.radio("页面", options, index=index, key="_page_radio")
        st.session_state["_page"] = choice

        st.divider()
        strip = ctx.strip
        if strip.get("state") == "KNOWN":
            st.error(
                "**QUALIFIED_ONLY**\n\n"
                f"预注册 `{strip.get('prereg_compliance')}` · "
                f"数值核验 `{strip.get('numerical_verification')}`"
            )
        else:
            st.warning("科学状态 **UNKNOWN**\n\n裁决文件不可读。")

        st.divider()
        runs = ctx.run_dirs()
        st.caption(f"run 数：{len(runs)} · 派生目录：" )
        derived = ctx.runs_dir / "_derived"
        st.caption(f"`{derived}`" if derived.is_dir() else "（无 _derived）")

        if st.button("重新读取裁决与 run 列表"):
            ctx.refresh_verdict()
            st.rerun()

        st.divider()
        st.caption(
            "证据等级上限 `SIMULATED` / `CROSS_CHECKED`。"
            "无实测数据；G4 泵浦案例为几何仿真。"
        )


def _footer(ctx) -> None:
    st.divider()
    cols = st.columns(3)
    cols[0].caption(f"project root · `{ctx.project_root}`")
    cols[1].caption(f"runs · `{ctx.runs_dir}`")
    cols[2].caption(
        "需要引用数字时，请带上 run_id / schema / model_level / "
        "units / evidence_level / status / source_sha256"
    )


if __name__ == "__main__":
    main()
