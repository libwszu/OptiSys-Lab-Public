"""Offline HTML/Markdown G4 report renderer."""

from __future__ import annotations

import base64
import csv
import html
import json
import mimetypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from optisys.reports.report_service import ReportResult, SCIENCE_TOKENS


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _read_csv(path: Path, limit: int = 24) -> tuple[list[str], list[dict[str, str]], int]:
    if not path.is_file():
        return [], [], 0
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        fields = list(reader.fieldnames or [])
        rows = list(reader)
    return fields, rows[:limit], len(rows)


def _table(headers: list[str], rows: list[dict[str, Any]], *, limit: int = 24) -> str:
    if not headers or not rows:
        return "<p><em>NOT_RUN / no rows recorded.</em></p>"
    head = "".join(f"<th>{html.escape(str(h))}</th>" for h in headers)
    body = []
    for row in rows[:limit]:
        body.append("<tr>" + "".join(f"<td>{html.escape(str(row.get(h, '')))}</td>" for h in headers) + "</tr>")
    return f"<div class='table-wrap'><table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table></div>"


def render_g4_report(
    run_dir: Path,
    out_dir: Path,
    *,
    title: str | None = None,
    verdict_root: Path | None = None,
    formats: tuple[str, ...] = ("html", "markdown"),
) -> ReportResult:
    run_dir = Path(run_dir).resolve()
    out_dir = Path(out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    status = _read_json(run_dir / "run_status.json")
    metrics = _read_json(run_dir / "metrics.json")
    model = _read_json(run_dir / "optics_model.json")
    compute = _read_json(run_dir / "compute_measured.json")
    convergence = _read_json(run_dir / "ray_count_convergence_summary.json")
    provenance = _read_json(run_dir / "provenance.json")
    split_manifest = _read_json(run_dir / "split_manifest.json")
    title = title or f"OptiSys-Lab G4 Pump976 — {run_dir.name}"
    root = Path(verdict_root).resolve() if verdict_root else run_dir.parents[1]
    verdict_path = root / "docs/g3/G2_INHERITANCE_VERDICT.json"
    inherited = _read_json(verdict_path)
    g2_status = inherited.get("scientific_claim_allowed", "UNKNOWN") if inherited else "UNKNOWN"
    if g2_status != "QUALIFIED_ONLY":
        g2_status = "UNKNOWN"
    science_text = "\n".join(SCIENCE_TOKENS)
    figures: dict[str, str] = {}
    figure_html = []
    for path in sorted((run_dir / "figures").glob("*.png")) if (run_dir / "figures").is_dir() else []:
        data = path.read_bytes()
        import hashlib
        digest = hashlib.sha256(data).hexdigest()
        figures[path.name] = digest
        mime = mimetypes.guess_type(path.name)[0] or "image/png"
        encoded = base64.b64encode(data).decode("ascii")
        figure_html.append(
            f"<figure><img alt='{html.escape(path.stem)}' src='data:{mime};base64,{encoded}'>"
            f"<figcaption>{html.escape(path.name)} · SHA-256 {digest}</figcaption></figure>"
        )
    target_fields, target_rows, target_n = _read_csv(run_dir / "target_plane_metrics.csv")
    balance_fields, balance_rows, balance_n = _read_csv(run_dir / "ray_balance.csv")
    design_fields, design_rows, design_n = _read_csv(run_dir / "design_comparison.csv")
    oat_fields, oat_rows, oat_n = _read_csv(run_dir / "oat.csv")
    tol_fields, tol_rows, tol_n = _read_csv(run_dir / "tolerance_samples.csv")
    import hashlib
    evidence_hashes = {}
    for name in ("config_snapshot.yaml", "source_samples.csv", "source_samples.npz",
                 "source_distribution_summary.csv", "raytrace_reference.csv", "ray_balance.csv",
                 "target_plane_metrics.csv", "target_plane_density.npz", "ray_count_convergence.csv",
                 "oat.csv", "tolerance_samples.csv", "bootstrap_replicates.csv",
                 "design_comparison.csv", "optical_crosscheck.json", "split_manifest.json",
                 "run_status.json"):
        path = run_dir / name
        if path.is_file():
            evidence_hashes[name] = hashlib.sha256(path.read_bytes()).hexdigest()

    html_text = f"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(title)}</title>
<style>
body{{font:15px/1.55 system-ui,Segoe UI,sans-serif;max-width:1180px;margin:2rem auto;padding:0 1rem;color:#1e2730}}
h1,h2{{line-height:1.2}}h1{{border-bottom:2px solid #3b657e;padding-bottom:.5rem}}
.banner{{background:#fff0dc;border-left:5px solid #d77b2a;padding:1rem;margin:1rem 0}}
.status{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:.7rem}}
.status div{{background:#eef3f6;padding:.7rem;border-radius:5px}}code{{overflow-wrap:anywhere}}
.table-wrap{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;font-size:.87rem}}th,td{{border:1px solid #ccd4da;padding:.35rem .45rem;text-align:left;vertical-align:top}}th{{background:#eaf0f3}}
figure{{margin:1rem 0;padding:.7rem;border:1px solid #d7dde1}}img{{max-width:100%;height:auto}}figcaption{{font-size:.8rem;color:#52616b;overflow-wrap:anywhere}}
.limit{{background:#f5f5f5;padding:.8rem;border-radius:5px}}ul{{padding-left:1.3rem}}
</style><body>
<h1>{html.escape(title)}</h1>
<div class="banner"><strong>SIMULATED · {html.escape(str(status.get('model_level_emitted','UNKNOWN')))}</strong> — geometric ray model; no experimental validation. Absolute source power is UNKNOWN; density is not W/mm².</div>
<div class="status">
<div><b>Engineering execution</b><br>{html.escape(str(status.get('G4_ENGINEERING_EXECUTION_STATUS','UNKNOWN')))}</div>
<div><b>Optical verification</b><br>{html.escape(str(status.get('G4_OPTICAL_MODEL_VERIFICATION','UNKNOWN')))}</div>
<div><b>Tolerance evaluation</b><br>{html.escape(str(status.get('G4_TOLERANCE_EVALUATION_STATUS','UNKNOWN')))}</div>
<div><b>Empirical validation</b><br>{html.escape(str(status.get('G4_EMPIRICAL_VALIDATION_STATUS','UNKNOWN')))}</div>
<div><b>Portfolio delivery</b><br>{html.escape(str(status.get('G4_PORTFOLIO_DELIVERY_STATUS','UNKNOWN')))}</div>
<div><b>Audit</b><br>{html.escape(str(status.get('G4_AUDIT_STATUS','UNKNOWN')))}</div>
<div><b>Inherited G2 science status</b><br>{html.escape(str(g2_status))}</div>
</div>
<h2>Inherited limitation</h2><div class="banner">G2 remains <b>QUALIFIED_ONLY</b>. Its historical execution record does not imply original pre-registration compliance. Required tokens:<pre>{html.escape(science_text)}</pre></div>
<h2>Nominal target-plane metrics</h2><p>{target_n} rows in the full source table. Transmission denominator is total source weight; spot radii are conditional on transmitted weight inside the modeled target circle.</p>
{_table(target_fields, target_rows)}
<h2>Weight balance</h2><p>Every ray retains its source denominator. No survivor renormalization is used for geometric transmission.</p>
{_table(balance_fields, balance_rows)}
<h2>Design comparison</h2><p>{design_n} rows; any candidate benefit is conditional on P0 assumptions and must be read alongside P1 high-NA discrepancy and aperture size.</p>
{_table(design_fields, design_rows)}
<h2>Ray-count convergence</h2><p>Status: <code>{html.escape(str(convergence.get('status','NOT_RUN')))}</code>. The 95% intervals describe seed sampling variation only, not physical model uncertainty.</p>
<pre>{html.escape(json.dumps(convergence,ensure_ascii=False,indent=2))}</pre>
<h2>OAT sensitivity</h2><p>Full table: {oat_n} rows. Values are assumed geometric sensitivity, not manufacturing yield.</p>
{_table(oat_fields, oat_rows)}
<h2>Tolerance samples</h2><p>Full file: {tol_n} rows in <code>tolerance_samples.csv</code>; table below is a preview only. Use the complete CSV for recomputation.</p>
{_table(tol_fields, tol_rows)}
<h2>Figures</h2>{''.join(figure_html) or '<p>NOT_RUN</p>'}
<h2>Model and data limits</h2><div class="limit"><ul>
<li>Fiber diameter, NA, lens focal lengths, singlet material/thickness and apertures are assumed; no vendor part numbers were supplied.</li>
<li>Power is UNKNOWN. Density values are normalized geometric ray weights, never absolute W/mm², absorbed power, temperature, or laser efficiency.</li>
<li>P0 is paraxial thin-lens geometry. P1 is Optiland 0.6.3 with assumed centered equiconvex singlets; it does not model coating/Fresnel loss, scatter, diffraction, coherence, or tilted/decentered surfaces.</li>
<li>External experiment status: NOT_AVAILABLE / NOT_RUN. No 976 nm hardware was started.</li>
<li>This is a pump beamline case, not a complete Er:YAP resonator or digital twin.</li>
</ul></div>
<h2>Provenance</h2><pre>{html.escape(json.dumps({'run_id':run_dir.name,'git_commit':provenance.get('git_commit'),'source_tree_sha256':provenance.get('source_tree_sha256'),'source_code_sha256':provenance.get('source_code_sha256'),'config_sha256':provenance.get('config_sha256'),'input_hashes':provenance.get('input_hashes'),'command':provenance.get('command'),'seeds':split_manifest,'evidence_file_sha256':evidence_hashes,'compute':compute,'issues':status.get('open_issues')},ensure_ascii=False,indent=2))}</pre>
</body></html>"""
    html_path = out_dir / "report.html" if "html" in formats else None
    markdown_path = out_dir / "report.md" if "markdown" in formats else None
    if html_path:
        html_path.write_text(html_text, encoding="utf-8")
    markdown = f"""# {title}

**SIMULATED · {status.get('model_level_emitted','UNKNOWN')}**  
Engineering: `{status.get('G4_ENGINEERING_EXECUTION_STATUS','UNKNOWN')}` · Optical verification: `{status.get('G4_OPTICAL_MODEL_VERIFICATION','UNKNOWN')}` · Tolerance: `{status.get('G4_TOLERANCE_EVALUATION_STATUS','UNKNOWN')}` · Empirical validation: `{status.get('G4_EMPIRICAL_VALIDATION_STATUS','UNKNOWN')}`

**Inherited G2 science status: `QUALIFIED_ONLY`.**

G2 tokens: `{', '.join(SCIENCE_TOKENS)}`.

## Scope

Geometric ray density proxy from a 976 nm multimode fiber through two assumed lenses. Absolute power is `UNKNOWN`; no result is W/mm². No experimental validation was available.

## Run files

- `target_plane_metrics.csv`: {target_n} rows
- `ray_balance.csv`: {balance_n} rows
- `design_comparison.csv`: {design_n} rows
- `ray_count_convergence.csv`: fixed 2k/8k/32k counts × three source seeds per design; status `{convergence.get('status','NOT_RUN')}`
- `oat.csv`: {oat_n} rows
- `tolerance_samples.csv`: {tol_n} rows (complete file; HTML table is only a preview)
- core CSV/NPZ/JSON evidence SHA-256 values are embedded in the HTML provenance block.
- Status: `{status.get('G4_ENGINEERING_EXECUTION_STATUS','UNKNOWN')}`; claim: `{status.get('G4_SCIENTIFIC_CLAIM','UNKNOWN')}`

## Limitations

{chr(10).join('- '+str(v) for v in status.get('open_issues',[]))}

No Fresnel/coating loss, diffraction, modal interference, scatter, crystal absorption, or Er:YAP resonator physics is included. Inherited G2 conclusions remain `QUALIFIED_ONLY`.
"""
    if markdown_path:
        markdown_path.write_text(markdown, encoding="utf-8")
    return ReportResult(
        run_id=run_dir.name, html_path=html_path, markdown_path=markdown_path,
        pdf_status="NOT_DELIVERED", pdf_reason="PDF export is not configured for G4; no empty PDF is generated.",
        bytes_html=html_path.stat().st_size if html_path else 0,
        bytes_markdown=markdown_path.stat().st_size if markdown_path else 0,
        science_tokens_present=list(SCIENCE_TOKENS), figures_indexed=figures,
        frozen_run_untouched=(out_dir != run_dir),
        generated_at_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
