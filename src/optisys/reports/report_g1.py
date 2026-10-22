"""G1 HTML report: tables + figures, explicitly labelled SIMULATED / L0."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from optisys.config_g1 import ResolvedG1Config
from optisys.reports.report import _CSS, _badge, _esc, _fmt_value, _table


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_index(run_dir: Path) -> str:
    rows = []
    for path in sorted(Path(run_dir).rglob("*")):
        if not path.is_file() or path.name == "report.html":
            continue
        rows.append((path.relative_to(run_dir).as_posix(),
                     f"{path.stat().st_size:,}", _sha256(path)[:16]))
    return _table(("文件", "字节", "SHA-256 前 16 位"), rows)


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{100 * value:.2f}%"


def _num(value: Any, digits: int = 4) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.{digits}g}"
    return str(value)


def render_g1_report(run_dir: Path, config: ResolvedG1Config, metrics: dict[str, Any],
                     provenance: dict[str, Any], status: dict[str, Any]) -> str:
    run_dir = Path(run_dir)
    checks = metrics["gate_checks"]
    all_pass = all(check["pass"] for check in checks.values())
    dataset = metrics["dataset"]
    v1 = metrics["v1"]["v1"]

    check_rows = [(name, item["what"], item["value"], item["threshold"],
                   "PASS" if item["pass"] else "FAIL") for name, item in checks.items()]

    subpixel_rows = [(row["offset_px"], row["estimator"], _num(row["error_px"], 5),
                      row["status"]) for row in v1["subpixel"]]
    noise_rows = [(row["scenario"], row["n"], _num(row["theoretical_mean"]),
                   _num(row["sample_mean"]), _num(row["mean_ci"]),
                   _num(row["theoretical_variance"]), _num(row["sample_variance"]),
                   row["replicate_passes"], "PASS" if row["pass"] else "FAIL")
                  for row in metrics["v2"]["v2"]]
    calibration_rows = []
    for name, fit in metrics["calibration"]["fits"].items():
        calibration_rows.append((
            name, _num(fit.get("a_px_mm"), 8), _num(fit.get("b_px"), 6),
            _num(fit.get("a_std"), 3), _num(fit.get("b_std"), 3),
            _num(fit.get("residual_rms_px"), 3), fit.get("n_frames_used", 0),
            fit.get("status"),
        ))

    overall_rows = []
    for row in metrics["summaries"]["by_estimator"]:
        overall_rows.append((
            row["estimator_name"], row["n_attempted"], row["n_valid"],
            _pct(row["failure_rate"]), _num(row["bias_mm"]), _num(row["rmse_mm"]),
            _num(row["p95_abs_mm"]), _num(row["repeatability_std_mm"]),
            _num(row["runtime_median_ms"], 3), _num(row["runtime_p95_ms"], 3),
        ))

    test_rows = []
    for row in metrics["summaries"]["by_estimator_split_condition"]:
        if row["dataset_split"] != "test":
            continue
        test_rows.append((
            row["estimator_name"], row["condition_id"], row["n_attempted"], row["n_valid"],
            _pct(row["failure_rate"]), _num(row["bias_mm"]), _num(row["rmse_mm"]),
            _num(row["p95_abs_mm"]), _num(row["rmse_ci_low_mm"]), _num(row["rmse_ci_high_mm"]),
        ))

    failure_rows = [(row["estimator_name"], row["condition_id"], row["n_attempted"],
                     row["n_valid"], _pct(row["failure_rate"]), row["status_counts"],
                     row["flag_counts"]) for row in metrics["failures"]]

    figures = [
        ("figures/fig1_spot_and_pixel_integration.png",
         "图 1｜连续高斯与像元面积积分；右侧剖面同时给出连续曲线与离散积分值。"),
        ("figures/fig2_edge_capture.png",
         "图 2｜光斑接近芯片边缘时的捕获率；未做重归一化。"),
        ("figures/fig3_noise_statistics.png",
         "图 3｜单像元噪声统计（3×10,000 合并，99% 区间）与理论值。"),
        ("figures/fig4_estimators_same_frame.png",
         "图 4｜三种定位器在同一帧上的估计位置。"),
        ("figures/fig5_calibration_and_residuals.png",
         "图 5｜系统标定 a/Z+b、数据划分与残差。"),
        ("figures/fig6_error_vs_distance.png",
         "图 6｜中等信号条件下 RMSE / P95 随距离变化。"),
        ("figures/fig7_failure_and_timing.png",
         "图 7｜全尝试帧失败率与单帧耗时（中位 / P95）。"),
    ]
    figure_html = "".join(
        f'<figure><img src="{_esc(src)}" alt="{_esc(src)}"><figcaption>{_esc(caption)}</figcaption></figure>'
        for src, caption in figures if (run_dir / src).exists()
    )

    run_id = _esc(status.get("run_id", ""))
    gate_status = _esc(status.get("status", "UNKNOWN"))
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OptiSys-Lab G1 工程报告 · {_esc(config.case_id)}</title>
<style>{_CSS}</style></head>
<body><main>
<h1>OptiSys-Lab · G1 成像与测距闭环报告</h1>
<p class="sub">案例 <code>{_esc(config.case_id)}</code> · 运行 <code>{run_id}</code> ·
模型等级 <strong>L0</strong> ·
证据等级 <span class="badge info">SIMULATED</span><span class="badge info">L0</span></p>
<p>{_badge(all_pass, "GATE CHECKS PASS", "GATE CHECKS FAIL")}
<span class="badge info">status: {gate_status}</span>
<span class="badge warn">{dataset['frames_attempted']} frames attempted</span></p>

<div class="note"><strong>结论边界：</strong>本报告证明 L0 仿真链路（高斯光斑 → 像元积分 →
泊松/读出噪声 → 三种定位器 → 系统标定 → 固定划分测试）在本机可复现，并给出误差与失败率。
它<strong>不</strong>代表真实相机、镜头、散斑或工业测距精度；传感器参数是设计假设，不是手册值。</div>

<h2>1. 数据集与划分</h2>
<p class="kv">距离 {dataset['distances']} 个（100–300 mm，步长 5 mm）× 条件
{_esc(dataset['conditions'])} × 重复 {dataset['repeats']} = 计划 {dataset['frames_expected']} 帧，
实际 {dataset['frames_attempted']} 帧；无效场景 {dataset['invalid_scenes']}。
每帧运行 3 个定位器，共 {dataset['n_rows']} 条估计记录。</p>
{_table(("划分", "距离数", "距离 [mm]"),
        [("calib", len(dataset['splits']['calib_distances']),
          ", ".join(str(v) for v in dataset['splits']['calib_distances'])),
         ("validation", len(dataset['splits']['validation_distances']),
          ", ".join(str(v) for v in dataset['splits']['validation_distances'])),
         ("test", len(dataset['splits']['test_distances']),
          ", ".join(str(v) for v in dataset['splits']['test_distances']))])}

<h2>2. 质量门</h2>
{_table(("检查", "含义", "实测", "阈值", "结果"), check_rows)}

<h2>3. V1：光斑与像元积分</h2>
<p class="kv">连续总量 {v1['continuous_total_e']:.0f} e，离散总和 {v1['discrete_sum_e']:.6f} e，
相对偏差 {v1['energy_relative_deviation']:.3e}；中心捕获率 {v1['capture_fraction_centered']:.9f}。
独立 Gauss–Legendre 对照 {v1['quadrature_pixels']} 像元，最大相对差
{v1['quadrature_max_relative_error']:.3e}。边缘捕获率
{_esc([round(v, 6) for v in v1['edge_capture_fractions']])}（偏移 {v1['edge_offsets_px']} px）。</p>
{_table(("亚像素偏移 [px]", "定位器", "u 误差 [px]", "状态"), subpixel_rows)}

<h2>4. V2：CMOS 噪声统计</h2>
{_table(("场景", "n", "理论均值", "样本均值", "均值 99% 半宽", "理论方差", "样本方差", "重复通过", "结果"), noise_rows)}
<p class="sub">每个场景为 3 次独立 10,000 抽样合并（n=30,000）；单次重复结果保留在 metrics.json。</p>

<h2>5. V3：定位、标定与测试</h2>
{_table(("估计器", "a [px·mm]", "b [px]", "σa", "σb", "标定残差 RMS [px]", "标定帧数", "状态"), calibration_rows)}
<div class="note">可辨识性：一维 Z–u 数据只能确定 <code>a = fx·B</code> 与
<code>b = cx − fx·tanθ</code>，<strong>不能</strong>唯一确定 B、fx、cx、θ 四个参数。
本报告不声称相机内参已标定。</div>
{_table(("估计器", "尝试帧", "有效帧", "失败率", "Bias [mm]", "RMSE [mm]", "P95 [mm]",
         "重复性 std [mm]", "中位耗时 [ms]", "P95 耗时 [ms]"), overall_rows)}
<p class="kv">失败率分母为全部尝试帧；精度指标仅对有效帧（状态 OK 且无阻塞质量标志）计算。</p>
<h3>最终测试集（按条件）</h3>
{_table(("估计器", "条件", "尝试", "有效", "失败率", "Bias [mm]", "RMSE [mm]", "P95 [mm]",
         "RMSE 95% CI 低", "RMSE 95% CI 高"), test_rows)}
<h3>失败构成</h3>
{_table(("估计器", "条件", "尝试", "有效", "失败率", "状态计数", "质量标志计数"), failure_rows)}

<h2>6. 图</h2>
{figure_html}

<h2>7. 明确未做</h2>
<ul>
<li>无镜头 PSF、像差、畸变、真实散斑；Optiland 未运行镜头案例。</li>
<li>无真实相机/激光器实测数据；所有传感器参数为设计假设。</li>
<li>无相机内参标定（棋盘格/畸变）；只做系统距离标定。</li>
<li>无公差 Monte Carlo、鲁棒优化、GUI、976 nm 案例（G2–G4）。</li>
<li>仅静态单点共面；v 由仿真构造为常数，不构成二维面形测量。</li>
</ul>

<h2>8. 复现</h2>
<pre>python -m optisys validate --config configs/triangulation_g1_l0.yaml
python -m optisys simulate --config configs/triangulation_g1_l0.yaml
python -m optisys evaluate --run runs/{run_id}
python -m pytest -q</pre>

<h2>9. 运行文件索引</h2>
{_file_index(run_dir)}
<p class="sub">索引不含 report.html 自身；生成时间 {_esc(status.get('finished_at_utc', ''))}，
配置 SHA-256 <code>{_esc(config.sha256)}</code>，源码树摘要
<code>{_esc(provenance.get('code', {}).get('source_tree_sha256', 'UNKNOWN'))}</code>。</p>
</main></body></html>
"""
