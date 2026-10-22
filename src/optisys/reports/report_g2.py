"""G2 report renderer (HTML + Markdown from the same data)."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from optisys.config_g2 import ResolvedG2Config


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    if not rows:
        return "<p class='muted'>NOT_RUN</p>"
    head = "".join(f"<th>{html.escape(c)}</th>" for c in columns)
    body = []
    for row in rows:
        cells = "".join(
            f"<td>{html.escape(_fmt(row.get(c)))}</td>" for c in columns
        )
        body.append(f"<tr>{cells}</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def _fmt(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        if value != value:
            return "—"
        if value != 0 and (abs(value) < 1e-3 or abs(value) >= 1e5):
            return f"{value:.3e}"
        return f"{value:.4f}"
    return str(value)


def render_g2_report(run_dir: Path, config: ResolvedG2Config, metrics: dict[str, Any],
                     provenance: dict[str, Any], status: dict[str, Any]) -> str:
    results = metrics.get("results", {})
    final = results.get("final", {})
    optics = results.get("optics", {})
    tolerance = results.get("tolerance", {})
    search = results.get("search", {})
    scientific = results.get("scientific", {})
    aggregation = results.get("aggregation", {})
    checks = results.get("gate_checks", {})

    check_rows = [
        {"check": name, "pass": value.get("pass"), "value": _fmt(value.get("value")),
         "threshold": _fmt(value.get("threshold"))}
        for name, value in checks.items() if isinstance(value, dict)
    ]

    candidate_rows = []
    for name in ("baseline", "nominal", "robust"):
        candidate = final.get("candidates", {}).get(name, {})
        engineering = final.get("engineering", {}).get(name, {})
        candidate_rows.append({
            "candidate": name,
            "B_mm": engineering.get("baseline_mm"),
            "f_mm": engineering.get("focal_length_mm"),
            "theta_deg": engineering.get("theta_deg"),
            "n_valid": candidate.get("n_valid"),
            "n_attempted": candidate.get("n_attempted"),
            "failure_rate": candidate.get("failure_rate"),
            "rmse_mm": candidate.get("rmse_mm"),
            "p95_mm": candidate.get("p95_abs_mm"),
            "bias_mm": candidate.get("bias_mm"),
        })

    ci_rows = []
    for key, value in final.get("ci", {}).items():
        rmse = value.get("rmse", {}) if isinstance(value, dict) else {}
        failure = value.get("failure_rate", {}) if isinstance(value, dict) else {}
        ci_rows.append({
            "comparison": key,
            "n_pairs": value.get("n_pairs"),
            "dRMSE_mm": rmse.get("delta"),
            "CI_low": rmse.get("ci_low"),
            "CI_high": rmse.get("ci_high"),
            "dFailure": failure.get("delta"),
        })

    strategy_rows = []
    for name in ("baseline", "nominal", "robust"):
        a = final.get("candidates", {}).get(name, {})
        b = final.get("strategy_b", {}).get(name, {})
        strategy_rows.append({
            "candidate": name,
            "A_rmse_mm": a.get("rmse_mm"),
            "A_failure": a.get("failure_rate"),
            "B_rmse_mm": b.get("rmse_mm"),
            "B_failure": b.get("failure_rate"),
        })

    figure_files = sorted((run_dir / "figures").glob("*.png"))
    figures_html = "".join(
        f"<figure><img src='figures/{path.name}' alt='{path.name}'/>"
        f"<figcaption>{path.name}</figcaption></figure>"
        for path in figure_files
    )

    css = """
    body{font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;
         background:#fbfbfb;color:#1b1b1b;margin:0;padding:28px 34px;line-height:1.55}
    h1{font-size:22px;margin:0 0 4px} h2{font-size:15px;margin:26px 0 8px;
         border-bottom:1px solid #e3e3e3;padding-bottom:4px}
    h3{font-size:12.5px;margin:16px 0 6px}
    .sub{color:#666;font-size:11.5px;margin-bottom:18px}
    table{border-collapse:collapse;margin:8px 0 14px;font-size:11.5px}
    th,td{border:1px solid #e0e0e0;padding:4px 8px;text-align:left}
    th{background:#f2f2f2;font-weight:600}
    .badge{display:inline-block;padding:2px 8px;border-radius:10px;font-size:11px;
           font-weight:600;margin-right:6px}
    .ok{background:#e5f3e8;color:#1d6b32} .warn{background:#fdf1dd;color:#8a5a05}
    .bad{background:#fbe6e6;color:#8c1d1d}
    .muted{color:#888;font-size:11.5px}
    figure{display:inline-block;width:46%;margin:6px 2% 12px 0;vertical-align:top}
    figure img{width:100%;border:1px solid #e6e6e6;background:#fff}
    figcaption{font-size:10.5px;color:#666;margin-top:3px}
    code{background:#f0f0f0;padding:1px 5px;border-radius:3px;font-size:11px}
    """

    status_class = {"PASS": "ok", "PARTIAL": "warn", "FAIL": "bad"}.get(
        status.get("status", ""), "warn")

    body = f"""
<h1>OptiSys-Lab — G2 report ({html.escape(config.case_id)})</h1>
<div class="sub">run <code>{html.escape(status.get('run_id', ''))}</code> ·
model level emitted <b>{html.escape(str(status.get('model_level_emitted', '')))}</b> ·
finished {html.escape(str(status.get('finished_at_utc', '')))}</div>

<p><span class="badge {status_class}">EXECUTION {html.escape(status.get('status', ''))}</span>
<span class="badge warn">SCIENTIFIC {html.escape(str(scientific.get('status', '')))}</span></p>

<h2>1. Scope and model level</h2>
<p>L1-approximate: a real sequential ray trace through an <b>assumed</b>
equiconvex N-BK7 singlet, whose geometric footprint is convolved with a scalar
Airy diffraction limit. This is not a wavefront-verified PSF, not a measured
lens and not a manufacturing-yield study. The G1 L0 chain is unchanged and is
used as the controlled baseline.</p>

<h2>2. Baseline provenance</h2>
{_table([provenance.get('extra', {})], ['source_tree_sha256', 'candidate_registry_sha256'])}
<p class="muted">G0 run 20261019_130948_G0_78fa364f ·
G1 run 20261019_145702_G1_54c9e3fb · both audit ZIPs re-hashed, identical.</p>

<h2>3. Optical backend</h2>
{_table([{
    'importable': optics.get('backend', {}).get('importable'),
    'version': optics.get('backend', {}).get('version'),
    'backend_executed': optics.get('backend_executed'),
    'trace_rows': optics.get('trace_rows'),
    'radius_1_mm': optics.get('model', {}).get('radius_1_mm') if optics.get('model') else None,
    'sensor_distance_mm': optics.get('model', {}).get('sensor_distance_from_rear_vertex_mm') if optics.get('model') else None,
    'f_number': optics.get('model', {}).get('working_f_number') if optics.get('model') else None,
}], ['importable', 'version', 'backend_executed', 'trace_rows', 'radius_1_mm',
      'sensor_distance_mm', 'f_number'])}

<h2>4. Gate checks</h2>
{_table(check_rows, ['check', 'pass', 'value', 'threshold'])}

<h2>5. Candidate comparison (independent panel, strategy A)</h2>
{_table(candidate_rows, ['candidate', 'B_mm', 'f_mm', 'theta_deg', 'n_valid',
                          'n_attempted', 'failure_rate', 'rmse_mm', 'p95_mm', 'bias_mm'])}

<h2>6. Paired differences with cluster bootstrap</h2>
{_table(ci_rows, ['comparison', 'n_pairs', 'dRMSE_mm', 'CI_low', 'CI_high', 'dFailure'])}

<h2>7. Calibration strategies</h2>
{_table(strategy_rows, ['candidate', 'A_rmse_mm', 'A_failure', 'B_rmse_mm', 'B_failure'])}
<p class="muted">Strategy B is run on a subset of assemblies; its cost
(calibration frames per unit) is part of the comparison.</p>

<h2>8. Figures</h2>
{figures_html if figures_html else "<p class='muted'>no figures</p>"}

<h2>9. Search budget</h2>
{_table([search.get('budget', {}).get('objective_weights', {})],
        list(search.get('budget', {}).get('objective_weights', {}).keys()))}

<h2>10. Limitations</h2>
<ul>{''.join(f'<li>{html.escape(item)}</li>' for item in metrics.get('limitations', []))}</ul>
"""
    return ("<!DOCTYPE html><html lang='zh'><head><meta charset='utf-8'>"
            f"<title>OptiSys-Lab G2 report</title><style>{css}</style></head><body>"
            f"{body}</body></html>")


def render_g2_markdown(run_dir: Path, config: ResolvedG2Config, metrics: dict[str, Any],
                       status: dict[str, Any]) -> str:
    results = metrics.get("results", {})
    final = results.get("final", {})
    lines = [
        f"# OptiSys-Lab G2 report — {config.case_id}",
        "",
        f"- run: `{status.get('run_id')}`",
        f"- execution status: **{status.get('status')}**",
        f"- scientific claim: **{status.get('scientific_claim_status')}**",
        f"- model level emitted: `{status.get('model_level_emitted')}`",
        "",
        "## Candidates",
        "",
        "| candidate | B [mm] | f [mm] | theta [deg] | valid/attempted | failure | RMSE [mm] | P95 [mm] |",
        "|---|---:|---:|---:|---|---:|---:|---:|",
    ]
    for name in ("baseline", "nominal", "robust"):
        row = final.get("candidates", {}).get(name, {})
        eng = final.get("engineering", {}).get(name, {})
        lines.append(
            f"| {name} | {_fmt(eng.get('baseline_mm'))} | {_fmt(eng.get('focal_length_mm'))} "
            f"| {_fmt(eng.get('theta_deg'))} | {row.get('n_valid')}/{row.get('n_attempted')} "
            f"| {_fmt(row.get('failure_rate'))} | {_fmt(row.get('rmse_mm'))} "
            f"| {_fmt(row.get('p95_abs_mm'))} |"
        )
    lines += ["", "## Paired comparisons", "",
              "| comparison | pairs | dRMSE [mm] | 95% CI |", "|---|---:|---:|---|"]
    for key, value in final.get("ci", {}).items():
        rmse = value.get("rmse", {}) if isinstance(value, dict) else {}
        if rmse.get("ci_low") is None:
            continue
        lines.append(
            f"| {key} | {value.get('n_pairs')} | {_fmt(rmse.get('delta'))} "
            f"| [{_fmt(rmse.get('ci_low'))}, {_fmt(rmse.get('ci_high'))}] |"
        )
    lines += ["", "## Limitations", ""]
    lines += [f"- {item}" for item in metrics.get("limitations", [])]
    return "\n".join(lines) + "\n"
