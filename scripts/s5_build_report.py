"""Render the registered S5 Markdown and standalone HTML engineering report."""

from __future__ import annotations

import csv
import html
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
S5=ROOT/"runs/20261020_210201_S5_HNA"


def _csv(path):
    with path.open(newline="",encoding="utf-8") as f:return list(csv.DictReader(f))


def main() -> int:
    verdict=json.loads((S5/"full_na_verdict.json").read_text(encoding="utf-8"))
    b=json.loads((S5/"s5_b_analysis_status.json").read_text(encoding="utf-8"))
    c=json.loads((S5/"bootstrap_summary.json").read_text(encoding="utf-8"))
    nominal=_csv(S5/"nominal_conditional_unconditional_metrics.csv")
    candidate=next(r for r in nominal if r["design_id"]=="baseline" and r["model_level"]=="P1_INDEPENDENT")
    g4candidate=next(r for r in nominal if r["design_id"]=="engineering_candidate" and r["model_level"]=="P1_INDEPENDENT")
    md=("# OptiSys-Lab Stage 5 engineering report\n\n"
        f"Run ID: `{verdict['run_id']}`  \nEvidence: `SIMULATED / ASSUMED P1 MODEL`  \n"
        f"S5-A: `{verdict['status']}` · S5-B: `{b['S5_B_HIGH_NA_CAUSE_STATUS']}` · "
        f"S5-C: `{c['status']}`\n\n"
        "## Executive result\n\n"
        f"The independent global sphere/Snell reference replayed {verdict['n_rays_per_design']:,} source rays for each G4 design across four lens faces. "
        f"Maximum surface coordinate component delta was `{verdict['surface_coord_delta_max_mm']:.3e} mm`; "
        f"maximum surface outgoing-direction component delta was `{verdict['surface_exit_direction_delta_max']:.3e}`. "
        "Target outcomes, source-weight ledgers and Optiland surface classifications matched.\n\n"
        f"At the original assumed 1 mm circle, P1 baseline capture was `{float(candidate['unconditional_capture_fraction_at_1mm']):.6f}` "
        f"with conditional `r90={float(candidate['conditional_r90_within_1mm_mm']):.6f} mm`; "
        f"the G4 P1 candidate was `{float(g4candidate['unconditional_capture_fraction_at_1mm']):.6f}` "
        f"with conditional `r90={float(g4candidate['conditional_r90_within_1mm_mm']):.6f} mm`. "
        "No ray was aperture-blocked or lost to a trace failure; misses are outside this assumed receiving region.\n\n"
        "## Model-level explanation\n\n"
        f"{b['main_diagnosis_scope']}\n\n"
        "## Equal-aperture candidate\n\n"
        f"L2 moved from z=125 to z={float(c['selected_l2_principal_z_mm']):.0f} mm while both clear apertures, glass, focal lengths, center thicknesses and the z=225 mm / r=1 mm target stayed fixed. "
        f"Independent holdout capture changed from `{float(c['baseline_capture_fraction']):.6f}` to `{float(c['candidate_capture_fraction']):.6f}`; "
        f"paired ray bootstrap 95% interval `[+{float(c['ci95'][0]):.4f}, +{float(c['ci95'][1]):.4f}]`. "
        "This is a nominal ray-sampling interval, not an assembly-tolerance result.\n\n"
        "## Limits\n\n"
        "No measured source profile, absolute source power, vendor lens drawing, actual outer diameter, coating, decenter/tilt, crystal dimension, absorption, thermal response or experiment is available. Do not interpret geometric weight as watts, efficiency or W/mm².\n\n"
        "## Figures and data\n\n"
        "All figures are backed by CSV evidence in this run. Source-weight denominators are retained.\n")
    (S5/"report.md").write_text(md,encoding="utf-8")
    figure_rows=[
        ("angle_resolved_p0_p1_capture.png","Capture fraction within the launch-angle bin; SIMULATED, NA=0.22."),
        ("surface_level_ray_deltas.png","Independent sphere/Snell versus Optiland surface deltas; SIMULATED, 4,096 rays/design."),
        ("encircled_weight_and_focus_sweep.png","Unconditional source-weight encircled curve and target-plane focus sensitivity."),
        ("target_geometry_sensitivity.png","Capture sensitivity to assumed circular/square receiving regions."),
        ("s5_assumed_lens_mechanical_outline.png","Assumed spherical lens sections; clear aperture shown, outer diameter unspecified."),
    ]
    body=[]
    for name,caption in figure_rows:
        body.append(f'<figure><img src="figures/{html.escape(name)}" alt="{html.escape(caption)}"><figcaption>{html.escape(caption)}</figcaption></figure>')
    report_html=("<!doctype html><html lang=\"en\"><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
      "<title>OptiSys-Lab S5 report</title><style>body{font:16px/1.55 system-ui,sans-serif;max-width:1080px;margin:2rem auto;padding:0 1rem;color:#182330}"
      "h1,h2{line-height:1.2}table{border-collapse:collapse;width:100%}td,th{border:1px solid #ccd3da;padding:.5rem;text-align:left}"
      "figure{margin:2rem 0}img{max-width:100%;height:auto}figcaption{color:#536170;font-size:.9rem}"
      ".banner{background:#eef5fb;padding:1rem;border-left:4px solid #286a91}code{overflow-wrap:anywhere}</style><body>"
      f"<h1>OptiSys-Lab Stage 5 engineering report</h1><p>Run <code>{html.escape(verdict['run_id'])}</code> · <strong>SIMULATED / ASSUMED P1</strong></p>"
      f"<p class=\"banner\">S5-A <b>{html.escape(verdict['status'])}</b> · S5-B <b>{html.escape(b['S5_B_HIGH_NA_CAUSE_STATUS'])}</b> · S5-C <b>{html.escape(c['status'])}</b>. No measured optical data.</p>"
      "<h2>High-NA reference</h2><p>4,096 source rays per G4 design; 32,768 surface records. "
      f"Maximum surface coordinate delta {verdict['surface_coord_delta_max_mm']:.3e} mm; "
      f"maximum direction delta {verdict['surface_exit_direction_delta_max']:.3e}. "
      "Source-weight ledgers and terminal classifications close. Geometric target misses are not measured power losses.</p>"
      f"<h2>Cause scope</h2><p>{html.escape(b['main_diagnosis_scope'])}</p>"
      f"<h2>Equal-aperture position comparison</h2><p>Holdout source-weight capture {float(c['baseline_capture_fraction']):.4f} → "
      f"{float(c['candidate_capture_fraction']):.4f}; paired ray-bootstrap 95% interval {float(c['ci95'][0]):+.4f} to {float(c['ci95'][1]):+.4f}. "
      "L2 position changes 125 → 135 mm; same 12/12 mm clear apertures, glass, focal lengths and fixed target. No assembly tolerance claim.</p>"
      "<h2>Assumptions and limitations</h2><p>No measured source power/profile, vendor lens drawing, real crystal dimensions, coating losses, absorption, thermal response or experiment. No watts, efficiency or W/mm² are inferred.</p>"
      +"".join(body)+"</body></html>")
    (S5/"report.html").write_text(report_html,encoding="utf-8")
    print(json.dumps({"report_md":"runs/20261020_210201_S5_HNA/report.md",
                      "report_html":"runs/20261020_210201_S5_HNA/report.html",
                      "figures":len(figure_rows),"bytes_html":len(report_html.encode())},indent=2))
    return 0


if __name__=="__main__":
    raise SystemExit(main())
