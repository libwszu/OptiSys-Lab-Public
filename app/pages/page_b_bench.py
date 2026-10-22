"""Page B - laser triangulation / spot bench.

This page executes *one frame* through the real L1 optical chain on demand.
It deliberately does not run the optimisation loop; the task book forbids a
button press from launching a 90-minute computation.

FAST_PREVIEW vs VERIFIED_RUN
----------------------------
``FAST_PREVIEW`` renders the analytic L0 pinhole chain with a synthetic
Gaussian spot.  It is fast, it is **not** the optical model, and every number it
produces is labelled ``PREVIEW_ONLY``.  ``VERIFIED_RUN`` traces the actual
single-element lens and is what any quoted number must come from.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import streamlit as st

from app.components import (
    failure_reason_explainer,
    no_g4_notice,
    provenance_bar,
    science_banner,
)
from app.components.plotting import apply as apply_plot_style
from optisys.config_g2 import load_config_g2
from optisys.errors import Status
from optisys.tolerance.assembly_model import SceneRunner
from optisys.tolerance.perturbations import make_design_assembly

CONFIG_PATH = Path("configs/g3_demo.yaml")
ESTIMATORS = ("centroid", "gaussian_2d", "gaussian_2d_integrated")


@dataclass
class FrameOutcome:
    mode: str
    distance_mm: float
    condition: str
    seed: int
    image_adu: Any
    u_gt_px: float | None
    estimates: dict[str, dict[str, Any]]
    optical_status: str
    roi_status: str
    kernel_support: float | None
    peak_expected_e: float | None
    saturation_full_well: bool | None
    saturation_adc: bool | None
    ray_success_fraction: float | None
    capture_fraction: float | None
    wall_s: float
    explanation: list[str]


def render(ctx) -> None:
    st.title("激光三角测量与光斑实验台")
    st.caption(
        "真值来自几何构造，测量值来自估计器 + 标定反解。"
        "界面不会为失败帧填零，也不会隐藏样本。"
    )
    apply_plot_style()
    science_banner(ctx.strip, compact=True)

    config = _load_config()
    if config is None:
        return

    st.divider()
    mode, params = _controls(config)
    st.divider()

    # The taxonomy is shown *before* any frame exists on purpose.  A reader
    # should be able to tell how this page reports a lost track before they
    # spend six seconds tracing one, and st.expander keeps it out of the way
    # once they have read it.
    with st.expander("失败状态分类速查（先读这个，再看数据）", expanded=False):
        failure_reason_explainer()
        st.caption(
            "本页对失败帧的处理原则：报出状态码与原因，绝不填零、绝不隐藏样本。"
            "把 Z 推到量程边缘可看 ROI 越界；把信号档位切到 strong 可看 full well 饱和。"
        )

    st.divider()
    _run_and_render(ctx, config, mode, params)


def _load_config():
    if not CONFIG_PATH.is_file():
        st.error(f"配置文件缺失：`{CONFIG_PATH}`")
        return None
    try:
        return load_config_g2(CONFIG_PATH)
    except Exception as exc:  # noqa: BLE001 - config errors must be shown verbatim
        st.error(f"配置无效：`{type(exc).__name__}: {exc}`")
        return None


def _controls(config) -> tuple[str, dict[str, Any]]:
    st.subheader("参数")

    mode = st.radio(
        "执行模式",
        ("VERIFIED_RUN", "FAST_PREVIEW"),
        horizontal=True,
        help=(
            "VERIFIED_RUN 走真实单透镜追迹，数值可被引用；"
            "FAST_PREVIEW 是解析针孔 + 合成高斯光斑，只用于快速看构图，"
            "其全部输出标 PREVIEW_ONLY。"
        ),
    )
    if mode == "FAST_PREVIEW":
        st.info(
            "**PREVIEW_ONLY** — 该模式不追迹真实透镜，只做解析几何与合成光斑。"
            "任何数值都不得作为证据引用。需要可引用数值请切到 VERIFIED_RUN。"
        )

    col1, col2, col3 = st.columns(3)
    with col1:
        z_mm = st.slider("工作距离 Z [mm]", float(config.z_min_mm),
                         float(config.z_max_mm), 200.0, step=5.0)
        baseline = st.number_input("基线 B [mm]", 1.0, 60.0,
                                   float(config.baseline_mm), step=0.5)
        focal = st.number_input("焦距 f [mm]", 4.0, 20.0,
                                float(config.focal_length_mm), step=0.1)
    with col2:
        theta_deg = st.number_input("倾角 θ [deg]", -6.0, 6.0,
                                    float(config.theta_deg), step=0.5)
        pixel_um = st.number_input("像元尺寸 [µm]", 1.0, 10.0,
                                   float(config.pixel_size_mm * 1000.0), step=0.05)
        exposure_ms = st.number_input("曝光 [ms]", 0.05, 50.0,
                                      float(config.sensor.exposure_ms), step=0.05)
    with col3:
        condition = st.selectbox("信号档位", [c.name for c in config.dataset.conditions],
                                 index=1)
        seed = st.number_input("随机种子", 0, 2**31 - 1, 20261020, step=1)
        estimator = st.selectbox("主估计器", ESTIMATORS, index=2)

    st.caption(
        "单位：`Z/B/f` = mm，`θ` = deg（载入即转 rad），像元 = µm（内部转 mm），"
        f"曝光 = ms（内部转 s）。当前配置：fx = {config.fx_px:.3f} px，"
        f"分辨率 {config.width_px}×{config.height_px} px。"
    )
    st.caption(
        "改动 `B / f / θ` 会构造一个新的设计，而不是 G2 冻结的三个候选之一。"
        "这是刻意的：实验台用于探索，冻结候选的对照在「优化对照」页。"
    )

    return mode, {
        "z_mm": z_mm,
        "baseline_mm": baseline,
        "focal_mm": focal,
        "theta_deg": theta_deg,
        "pixel_um": pixel_um,
        "exposure_ms": exposure_ms,
        "condition": condition,
        "seed": int(seed),
        "estimator": estimator,
    }


def _run_and_render(ctx, config, mode: str, params: dict[str, Any]) -> None:
    st.subheader("执行")
    st.caption(
        "单帧执行，不进入优化循环。UI 只通过 JobService / SceneRunner 调用，"
        "点击按钮不会触发 G2 的 2000 装配重算。"
    )
    if st.button("生成单帧", type="primary"):
        with st.spinner("追迹中…"):
            outcome = _execute(config, mode, params)
        st.session_state["bench_outcome"] = outcome

    outcome: FrameOutcome | None = st.session_state.get("bench_outcome")
    if outcome is None:
        st.caption("尚未生成帧。")
        return

    _render_outcome(config, outcome)


def _execute(config, mode: str, params: dict[str, Any]) -> FrameOutcome:
    started = time.perf_counter()
    explanation: list[str] = []

    if mode == "FAST_PREVIEW":
        return _preview_frame(config, params, started, explanation)

    from optisys.estimators import build_estimators_g2
    from optisys.optimization.search_space import Design

    estimators = [e for e in build_estimators_g2() if e.name in ESTIMATORS]
    runner = SceneRunner(config, estimators=estimators, max_cached_models=4)

    design = Design(params["baseline_mm"], params["focal_mm"], params["theta_deg"])
    # Build the assembly through the same constructor the gate uses, then apply
    # the pixel-size / exposure overrides as explicit notes on the state.
    assembly = _nominal_assembly(design, config, params)
    condition = next(c for c in config.dataset.conditions
                     if c.name == params["condition"])

    outcome = runner.run_scene(
        assembly, float(params["z_mm"]), condition, repeat=0,
        seed_namespace=f"G3BENCH|{params['seed']}",
        return_frame=True,
    )
    wall = time.perf_counter() - started

    if outcome.optical_status != "OK":
        explanation.append(f"光学状态 `{outcome.optical_status}`")
    if outcome.roi_status not in ("INSIDE", "OK"):
        explanation.append(f"ROI 状态 `{outcome.roi_status}`：光斑可能越界或贴边")
    if outcome.saturation_full_well:
        explanation.append("full well 饱和：峰值期望电子数超过满阱容量，"
                           "该帧不能当作有效测量")
    if outcome.saturation_adc:
        explanation.append("ADC 截断：ADU 触顶，光斑形态已被削平")
    if outcome.kernel_support is not None and outcome.kernel_support < 0.95:
        explanation.append(
            f"kernel_support = {outcome.kernel_support:.4f} 低于 as-run 门限 0.950："
            "PSF 核能量截断显著")
    if outcome.ray_success_fraction is not None and outcome.ray_success_fraction < 0.90:
        explanation.append(
            f"光线成功率 {outcome.ray_success_fraction:.3f} 低于 0.90：渐晕显著")

    return FrameOutcome(
        mode=mode,
        distance_mm=float(params["z_mm"]),
        condition=params["condition"],
        seed=params["seed"],
        image_adu=outcome.image_adu,
        u_gt_px=outcome.u_gt_px,
        estimates=outcome.estimates,
        optical_status=outcome.optical_status,
        roi_status=outcome.roi_status,
        kernel_support=outcome.kernel_support,
        peak_expected_e=outcome.peak_expected_e,
        saturation_full_well=outcome.saturation_full_well,
        saturation_adc=outcome.saturation_adc,
        ray_success_fraction=outcome.ray_success_fraction,
        capture_fraction=outcome.capture_fraction,
        wall_s=wall,
        explanation=explanation,
    )


def _nominal_assembly(design, config, params: dict[str, Any]):
    from optisys.tolerance.perturbations import AssemblyPerturbation

    perturbation = AssemblyPerturbation(
        assembly_id="BENCHNOM",
        d_baseline_mm=0.0, d_theta_rad=0.0, d_focal_relative=0.0,
        d_cx_px=0.0, d_focus_mm=0.0,
    )
    assembly = make_design_assembly(
        perturbation, config,
        baseline_mm=design.baseline_mm, theta_rad=design.theta_rad,
        focal_length_mm=design.focal_length_mm,
    )
    return assembly


def _preview_frame(config, params: dict[str, Any], started: float,
                   explanation: list[str]) -> FrameOutcome:
    """Analytic pinhole + synthetic Gaussian spot.  NOT the optical model."""

    theta_rad = float(np.deg2rad(params["theta_deg"]))
    B = float(params["baseline_mm"])
    Z = float(params["z_mm"])
    fx = float(params["focal_mm"] * 1e-3 / (params["pixel_um"] * 1e-6))
    cx = config.cx_px
    u = cx + fx * (B / Z - np.tan(theta_rad))

    data = np.zeros((config.height_px, config.width_px), dtype=float)
    sigma = max(1.2, 3.0 * Z / 200.0)
    yy, xx = np.mgrid[0:config.height_px, 0:config.width_px]
    spot = np.exp(-(((xx - u) ** 2 + (yy - config.cy_px) ** 2) / (2 * sigma ** 2)))
    full_well = config.sensor.full_well_e
    peak_e = full_well * 0.08
    electrons = spot * peak_e
    adu = electrons / config.sensor.e_per_adu + config.sensor.black_level_adu
    adu = np.clip(adu, 0, config.sensor.adc_max_adu)

    wall = time.perf_counter() - started
    explanation.append(
        "PREVIEW_ONLY：本帧由解析针孔几何 + 合成高斯光斑生成，未追迹透镜。"
        "其 u 值只反映 `u = cx + fx·(B/Z − tanθ)`，不含像差与 PSF 卷积。")

    estimates = {}
    for name in ESTIMATORS:
        if name == "centroid":
            weights = np.clip(adu - config.sensor.black_level_adu, 0, None)
            total = weights.sum()
            u_hat = float((weights * xx).sum() / total) if total > 0 else None
            estimates[name] = {"u_hat_px": u_hat, "status": "OK" if u_hat else "NOT_ESTIMABLE",
                               "flags": []}
        else:
            estimates[name] = {"u_hat_px": None, "status": "NOT_RUN_IN_PREVIEW",
                               "flags": ["PREVIEW_SKIPS_FITTING"]}

    return FrameOutcome(
        mode="FAST_PREVIEW",
        distance_mm=Z,
        condition=params["condition"],
        seed=params["seed"],
        image_adu=adu,
        u_gt_px=float(u),
        estimates=estimates,
        optical_status="PREVIEW_ONLY",
        roi_status="INSIDE" if 24 <= u <= config.width_px - 24 else "TOUCHES_BORDER",
        kernel_support=None,
        peak_expected_e=float(peak_e),
        saturation_full_well=bool(peak_e > full_well),
        saturation_adc=bool((electrons.max() / config.sensor.e_per_adu
                             + config.sensor.black_level_adu) > config.sensor.adc_max_adu),
        ray_success_fraction=None,
        capture_fraction=None,
        wall_s=wall,
        explanation=explanation,
    )


def _render_outcome(config, outcome: FrameOutcome) -> None:
    if outcome.mode == "FAST_PREVIEW":
        st.warning("**PREVIEW_ONLY** — 下列数值不可引用。")

    cols = st.columns(4)
    cols[0].metric("Z 设定 [mm]", f"{outcome.distance_mm:.1f}")
    cols[1].metric("真值 u [px]", f"{outcome.u_gt_px:.2f}"
                   if outcome.u_gt_px is not None else "NOT_AVAILABLE")
    cols[2].metric("kernel_support",
                   f"{outcome.kernel_support:.4f}"
                   if outcome.kernel_support is not None else "N/A")
    cols[3].metric("耗时 [s]", f"{outcome.wall_s:.2f}")

    st.caption(
        f"光学状态 `{outcome.optical_status}` · ROI `{outcome.roi_status}` · "
        f"峰值期望 {outcome.peak_expected_e:.1f} e- · "
        f"捕捉比 {outcome.capture_fraction:.4f} "
        if outcome.capture_fraction is not None else
        f"光学状态 `{outcome.optical_status}` · ROI `{outcome.roi_status}`"
    )

    if outcome.explanation:
        st.error("**该帧存在异常，界面如实报告而非隐藏：**\n\n"
                 + "\n".join(f"- {line}" for line in outcome.explanation))
    else:
        st.success("该帧无异常旗标。")

    st.subheader("光斑")
    image = np.asarray(outcome.image_adu, dtype=float)
    st.image(_to_display(image), caption=(
        f"ADU 图像 · {image.shape[1]}×{image.shape[0]} px · "
        f"min {np.nanmin(image):.0f} / max {np.nanmax(image):.0f} ADU"
    ), width="stretch", clamp=True)

    st.subheader("估计器结果")
    rows = []
    for name, payload in outcome.estimates.items():
        u_hat = payload.get("u_hat_px")
        error_px = (u_hat - outcome.u_gt_px) if (
            u_hat is not None and outcome.u_gt_px is not None) else None
        rows.append({
            "估计器": name,
            "u_hat [px]": f"{u_hat:.3f}" if u_hat is not None else "NOT_AVAILABLE",
            "Δu vs 真值 [px]": f"{error_px:+.3f}" if error_px is not None else "NOT_AVAILABLE",
            "状态": payload.get("status"),
            "旗标": ";".join(payload.get("flags") or []) or "—",
        })
    st.dataframe(rows, width="stretch", hide_index=True)
    st.caption(
        "真值来自几何构造（`u_gt_px`），不是来自估计器。"
        "估计器的 `NOT_AVAILABLE` 表示该帧不可估，**不是 0**。"
    )

    st.subheader("异常情形速查")
    st.caption(
        "本帧的旗标列在上方红色提示框内。完整状态分类见页面顶部的可折叠速查表。"
    )


def _to_display(image: np.ndarray) -> np.ndarray:
    lo, hi = float(np.nanmin(image)), float(np.nanmax(image))
    if hi - lo < 1e-9:
        return np.zeros_like(image, dtype=np.uint8)
    scaled = (image - lo) / (hi - lo)
    return (scaled * 255).astype(np.uint8)