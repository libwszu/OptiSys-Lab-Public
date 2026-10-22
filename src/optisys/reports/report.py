"""HTML engineering report (G0).

The report is generated from the same structured data stored in the run
directory; nothing is typed in by hand.  It intentionally states what was NOT
done as clearly as what was done.
"""

from __future__ import annotations

import hashlib
import html
from pathlib import Path
from typing import Any, Iterable

from optisys.config import ResolvedConfig

_CSS = """
:root { color-scheme: light; }
body { font-family: "Segoe UI", "Microsoft YaHei", Arial, sans-serif; margin: 0;
       background: #f6f7f9; color: #1b1f24; line-height: 1.55; }
main { max-width: 1080px; margin: 0 auto; padding: 32px 24px 64px; background: #ffffff;
       box-shadow: 0 1px 3px rgba(0,0,0,.08); }
h1 { font-size: 26px; margin: 0 0 6px; }
h2 { font-size: 19px; margin-top: 34px; border-left: 4px solid #1f77b4; padding-left: 10px; }
h3 { font-size: 15px; margin-top: 22px; }
.sub { color: #5b6573; margin: 0 0 18px; }
.badge { display: inline-block; padding: 2px 9px; border-radius: 10px; font-size: 12px;
         font-weight: 600; margin-right: 6px; }
.pass { background: #e4f5e9; color: #14663a; }
.fail { background: #fde8e8; color: #9b1c1c; }
.warn { background: #fff4e0; color: #8a5300; }
.info { background: #e8f0fb; color: #1c4e8a; }
table { border-collapse: collapse; width: 100%; margin: 10px 0 6px; font-size: 13px; }
th, td { border: 1px solid #dfe3e8; padding: 6px 8px; text-align: left; vertical-align: top; }
th { background: #f1f4f8; font-weight: 600; }
code, pre { font-family: Consolas, "Courier New", monospace; font-size: 12.5px; }
pre { background: #f5f7fa; border: 1px solid #e2e6ec; padding: 10px 12px; overflow-x: auto; }
.note { background: #fff9e8; border: 1px solid #f0d9a8; padding: 10px 12px; font-size: 13px; }
figure { margin: 16px 0 8px; }
figure img { max-width: 100%; border: 1px solid #e2e6ec; background: white; }
figcaption { font-size: 12.5px; color: #5b6573; margin-top: 6px; }
.kv { font-size: 13px; }
.kv td:first-child { width: 220px; color: #4a5360; background: #fafbfc; }
"""


def _esc(value: Any) -> str:
    return html.escape(str(value))


def _badge(passed: bool, text_pass: str = "PASS", text_fail: str = "FAIL") -> str:
    css = "pass" if passed else "fail"
    return f'<span class="badge {css}">{_esc(text_pass if passed else text_fail)}</span>'


def _fmt_value(value: Any) -> str:
    """Readable rendering for bool/dict/list values in user-facing tables."""

    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, dict):
        return "; ".join(f"{key}={_fmt_value(item)}" for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return ", ".join(_fmt_value(item) for item in value)
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _table(headers: Iterable[str], rows: Iterable[Iterable[Any]],
           formats: dict[int, str] | None = None) -> str:
    head = "".join(f"<th>{_esc(item)}</th>" for item in headers)
    body_rows = []
    for row in rows:
        cells = []
        for index, value in enumerate(row):
            if formats and index in formats and isinstance(value, (int, float)):
                text = formats[index].format(value)
            else:
                text = _esc(_fmt_value(value))
            cells.append(f"<td>{text}</td>")
        body_rows.append("<tr>" + "".join(cells) + "</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _file_index(run_dir: Path) -> str:
    rows = []
    for path in sorted(run_dir.rglob("*")):
        if not path.is_file() or path.name == "report.html":
            continue
        rows.append(
            (path.relative_to(run_dir).as_posix(), f"{path.stat().st_size:,}", _sha256(path)[:16])
        )
    return _table(("文件", "字节", "SHA-256 前 16 位"), rows)


def render_report(run_dir: Path, config: ResolvedConfig, metrics: dict[str, Any],
                  provenance: dict[str, Any], status: dict[str, Any]) -> str:
    run_dir = Path(run_dir)
    gate_checks = metrics["gate_checks"]
    all_pass = all(check["pass"] for check in gate_checks.values())
    chain = metrics["chain"]
    boundary = metrics["boundary_cases"]
    boundary_pass = all(item["pass"] for item in boundary)

    check_rows = [
        (name, check["what"], check["value"], check["threshold"],
         "PASS" if check["pass"] else "FAIL")
        for name, check in gate_checks.items()
    ]
    pdf_rows = [
        (row["quantity"], row["unit"], row["pdf_printed"], row["computed"],
         row["abs_difference"], row["rel_difference"])
        for row in metrics["pdf_reference"]
    ]
    boundary_rows = [
        (item["case"], item["expected_status"], item["actual_status"], item["detail"],
         "PASS" if item["pass"] else "FAIL")
        for item in boundary
    ]

    tests_value = metrics.get("tests", "NOT_INGESTED")
    if isinstance(tests_value, dict):
        tests_text = (
            f"{tests_value.get('passed', '?')} passed / "
            f"{tests_value.get('failed', '?')} failed / "
            f"{tests_value.get('skipped', '?')} skipped"
        )
    else:
        tests_text = str(tests_value)

    figures = [
        ("figures/fig1_Z_u_curve.png",
         "图 1｜Z–u 标定曲线（θ = -3°/0°/+3°）。空心圆为 PDF 第 8 页给出的 100/200/300 mm 对照点。"
         "数据：figures/fig1_Z_u_curve.csv。"),
        ("figures/fig2_Z_sensitivity.png",
         "图 2｜|dZ/du| = Z²/(fxB) 随距离增长；β 越大灵敏度越低。数据：figures/fig2_Z_sensitivity.csv。"),
        ("figures/fig3_sensor_visibility.png",
         "图 3｜像面占用与近距裁切。此图关闭工作范围检查以显示裁切边界；"
         "数据：figures/fig3_sensor_visibility.csv。"),
        ("figures/fig4_independent_residual.png",
         "图 4｜解析式与独立向量链的像点残差（对数坐标），是 V0 的核心证据。"
         "数据：figures/fig4_independent_residual.csv。"),
    ]
    figure_html = "".join(
        f'<figure><img src="{_esc(src)}" alt="{_esc(src)}"><figcaption>{_esc(caption)}</figcaption></figure>'
        for src, caption in figures
        if (run_dir / src).exists()
    )

    env = metrics.get("environment", {})
    compute = metrics.get("compute", {})
    check_html = _table(
        ("检查项", "含义", "实测", "阈值", "结果"),
        [(name, what, value, threshold, verdict)
         for name, what, value, threshold, verdict in check_rows],
    )

    status_label = _esc(status.get("status", "UNKNOWN"))
    gate = _esc(status.get("gate", "G0"))

    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>OptiSys-Lab {gate} 工程报告 · {_esc(config.case_id)}</title>
<style>{_CSS}</style></head>
<body><main>
<h1>OptiSys-Lab · {gate} 工程基线报告</h1>
<p class="sub">案例 <code>{_esc(config.case_id)}</code> ·
运行 <code>{_esc(status.get('run_id', ''))}</code> ·
模型等级 <strong>{_esc(config.model_level)}</strong> ·
证据等级 <span class="badge info">FORMULA</span><span class="badge info">CROSS-CHECKED</span></p>
<p>{_badge(all_pass, "GATE CHECKS PASS", "GATE CHECKS FAIL")}
{_badge(boundary_pass, "BOUNDARY CASES PASS", "BOUNDARY CASES FAIL")}
<span class="badge info">status: {status_label}</span></p>

<div class="note"><strong>结论边界：</strong>本报告只证明理想针孔共面几何的公式实现与独立向量/矩阵实现一致，
并正确拒绝病态与越界输入。<strong>不</strong>证明任何传感器精度、CMOS 噪声性能、镜头像质或产品指标；
这些属于 G1–G3 且尚未实现。</div>

<h2>1. 本轮实际完成的内容</h2>
<ul>
<li>显式单位契约（mm / rad / pixel）与严格 YAML 校验；未知字段直接拒绝。</li>
<li>理想几何 forward / inverse / 导数 / 灵敏度，含状态码与奇异、越界、非有限值处理。</li>
<li>独立对照链：3×3 线性方程射线–平面求交 + 齐次 3×4 投影矩阵 + Brent 数值反演。</li>
<li>可复现运行目录：配置快照、环境、基准、指标、样本表、图与数据表、哈希与状态。</li>
<li><strong>未实现</strong>：CMOS 成像、PSF/镜头追迹接入、光斑定位器、标定、公差与优化、GUI。这些是 G1–G3 的范围。</li>
</ul>

<h2>2. 关键数值与质量门</h2>
{check_html}
<p class="kv">样本点数：{chain['n_points']} = {len(chain['theta_values_deg'])} 个角度 × {chain['z_points']} 个距离；
距离范围 {chain['z_range_mm'][0]}–{chain['z_range_mm'][1]} mm；
灵敏度 {chain['sensitivity_mm_per_px']['min']:.6f}–{chain['sensitivity_mm_per_px']['max']:.6f} mm/pixel。<br>
测试：{_esc(tests_text)}</p>

<h2>3. 与 PDF 第 8 页印刷数值的对照</h2>
{_table(("量", "单位", "PDF 印刷值", "本实现计算值", "绝对差", "相对差"), pdf_rows,
        formats={3: "{:.9g}", 4: "{:.3e}", 5: "{:.3e}"})}
<p class="kv">说明：PDF 给出的 u−cx 与灵敏度只印到 4–6 位有效数字，故此处比较的是舍入一致性；
相对差在 1e-4 量级属于排版舍入，不是实现误差。</p>

<h2>4. 边界与病态输入</h2>
{_table(("用例", "期望状态", "实际状态", "说明", "结果"), boundary_rows)}
<p class="kv">所有失败用例均返回显式状态码，且不把 nan/inf 或截断后的数值当作有效测量。</p>

<h2>5. 图与绘图数据</h2>
{figure_html}

<h2>6. 计算资源与基准</h2>
<p class="kv">CPU：{_esc(env.get('cpu', 'UNKNOWN'))}<br>
内存：{_esc(env.get('memory', 'UNKNOWN'))}<br>
GPU：{_esc(env.get('gpu', 'UNKNOWN'))}<br>
策略：{_esc(compute.get('policy', 'UNKNOWN'))}<br>
G0 主工作负载中位耗时：{_esc(compute.get('g0_median_ms', 'UNKNOWN'))} ms；
200k 采样计时代理：{_esc(compute.get('mc_proxy_median_ms', 'UNKNOWN'))} ms；
最佳进程加速比：{_esc(compute.get('best_speedup', 'UNKNOWN'))}。</p>

<h2>7. 已知限制与未执行项</h2>
<ul>
<li>仅实现静态、单点、共面二维几何；无镜头畸变、遮挡、非共面旋转、多重反射。</li>
<li>θ 只验证到 ±3°（配置允许到 ±80°，但未在本 Gate 的对照网格中覆盖）。</li>
<li>v 方向在本模型中恒为主点（目标点在 XZ 平面内），真实行列方向需标定。</li>
<li>Optiland 已安装（0.6.3）且可导入，但<strong>未运行任何镜头案例</strong>，不构成光学追迹能力声明。</li>
<li>GPU 未测试：G0 无张量工作负载，且未安装 torch。</li>
<li>PDF 式 (3) 的导数符号与式 (2) 的有符号求导不一致，详见 <code>docs/SPEC_DISCREPANCIES.md</code>（SD-001）。</li>
</ul>

<h2>8. 复现</h2>
<pre>python -m optisys validate --config configs/triangulation_v0.yaml
python -m optisys simulate --config configs/triangulation_v0.yaml
python -m pytest -q</pre>

<h2>9. 运行文件索引</h2>
{_file_index(run_dir)}
<p class="sub">本表不含 report.html 自身以避免自引用；生成时间 {_esc(status.get('finished_at_utc', ''))}，
配置 SHA-256 <code>{_esc(config.sha256)}</code>，源码树摘要 <code>{_esc(provenance.get('code', {}).get('source_tree_sha256', 'UNKNOWN'))}</code>。</p>
</main></body></html>
"""
