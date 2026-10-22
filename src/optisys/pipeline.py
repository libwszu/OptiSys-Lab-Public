"""G0 execution pipeline: geometry sweep -> evidence -> figures -> report."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from optisys.config import ResolvedConfig
from optisys.evaluation.chain import (
    U_TOLERANCE_PX,
    boundary_cases,
    compare_chain,
    pdf_reference_table,
)
from optisys.reports.figures import build_all
from optisys.qa import aggregate_gate_status, load_gate_requirements
from optisys.reports.report import render_report
from optisys.runtime.compute import benchmark, build_compute_plan
from optisys.runtime.environment import collect_environment
from optisys.runtime.run import RunContext, utc_now

_SAMPLE_FIELDS = [
    "theta_deg", "Z_mm", "X_analytic_mm", "X_reference_mm", "X_abs_error_mm",
    "u_analytic_px", "u_reference_px", "u_abs_error_px", "v_analytic_px",
    "v_reference_px", "Z_hat_mm", "Z_abs_error_mm", "Z_rel_error",
    "du_dZ_analytic_px_per_mm", "du_dZ_finite_difference_px_per_mm",
    "du_dZ_rel_error", "dZ_du_analytic_mm_per_px", "abs_sensitivity_mm_per_px",
    "status", "inverse_status",
]


def _write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def run_g0(
    config: ResolvedConfig,
    project_root: Path,
    runs_dir: Path | None = None,
    tests_summary: Path | None = None,
    tests_stdout: Path | None = None,
) -> tuple[RunContext, dict[str, Any]]:
    """Execute the whole G0 chain and freeze its evidence."""

    root = Path(project_root)
    context = RunContext(
        project_root=root,
        gate="G0",
        config_sha256=config.sha256,
        config_path=config.path,
        runs_dir=runs_dir,
    )
    context.log(f"case={config.case_id} model_level={config.model_level} fx={config.fx_px:.9f} px")
    context.snapshot_config(config.path)

    tests_info: dict[str, Any] | None = None
    if tests_summary is not None:
        tests_info = json.loads(Path(tests_summary).read_text(encoding="utf-8"))
        context.path("tests_summary.json").write_bytes(Path(tests_summary).read_bytes())
        context.log(
            f"tests ingested: {tests_info['totals']['passed']} passed / "
            f"{tests_info['totals']['failed']} failed / {tests_info['totals']['skipped']} skipped"
        )
    if tests_stdout is not None:
        context.path("tests_stdout.txt").write_bytes(Path(tests_stdout).read_bytes())

    environment = collect_environment(root)
    context.write_json("environment.json", environment)
    context.log(
        f"hardware: {environment['cpu']['model']} | "
        f"{environment['cpu']['physical_cores']}C/{environment['cpu']['logical_cores']}T | "
        f"RAM {environment['memory']['total_gb']} GB"
    )

    benchmark_report = benchmark(config.geometry, seed=config.run.seed)
    context.write_json("benchmark.json", benchmark_report)
    plan = build_compute_plan(environment, benchmark_report)
    context.write_json("compute_plan.json", plan)
    context.log(
        "benchmark: G0 median "
        f"{benchmark_report['workloads'][0]['median_s'] * 1e3:.2f} ms, "
        f"mc proxy median {benchmark_report['workloads'][2]['median_s'] * 1e3:.2f} ms, "
        f"best speedup {benchmark_report['parallel_scaling']['best_speedup_vs_1']:.2f}x"
    )

    comparison = compare_chain(config)
    pdf_rows = pdf_reference_table(config)
    boundaries = boundary_cases(config)
    _write_csv(context.path("samples.csv"), comparison.rows, _SAMPLE_FIELDS)
    _write_csv(
        context.path("formula_comparison.csv"),
        pdf_rows,
        ["quantity", "unit", "pdf_printed", "computed", "abs_difference", "rel_difference", "inputs"],
    )
    _write_csv(
        context.path("boundary_cases.csv"),
        boundaries,
        ["case", "expected_status", "actual_status", "pass", "detail"],
    )
    context.log(
        f"chain comparison: max|du|={comparison.metrics['max_abs_u_error_px']:.3e} px, "
        f"max|dX|={comparison.metrics['max_abs_X_error_mm']:.3e} mm, "
        f"max rel dZ={comparison.metrics['max_Z_relative_error']:.3e}"
    )

    figure_paths = build_all(config, comparison, context.path("figures"), U_TOLERANCE_PX)
    context.log(f"figures: {', '.join(path.name for path in figure_paths)}")

    requirements = load_gate_requirements(root)
    aggregation = aggregate_gate_status(
        "G0", comparison.gate_checks, boundaries, tests_info, requirements
    )
    checks_pass = aggregation.numeric_checks_pass
    boundaries_pass = aggregation.boundary_cases_pass
    gate_status = aggregation.status

    metrics: dict[str, Any] = {
        "schema_version": "1.0",
        "gate": "G0",
        "case_id": config.case_id,
        "model_level": config.model_level,
        "evidence_levels": {
            "geometry_formula": "FORMULA",
            "independent_cross_check": "CROSS-CHECKED",
            "sensor_performance": "NOT_ASSESSED",
            "measured_data": "NOT_RUN",
        },
        "chain": comparison.metrics,
        "gate_checks": comparison.gate_checks,
        "pdf_reference": pdf_rows,
        "boundary_cases": boundaries,
        "environment": {
            "cpu": (
                f"{environment['cpu']['model']} "
                f"({environment['cpu']['physical_cores']}C/{environment['cpu']['logical_cores']}T)"
            ),
            "memory": (
                f"{environment['memory']['total_gb']} GB total, "
                f"{environment['memory']['available_gb']} GB available"
            ),
            "gpu": _gpu_summary(environment),
            "python": environment["python"]["version"],
            "optiland": environment["optiland"],
        },
        "compute": {
            "policy": plan["selected_policy"]["g0"],
            "g0_median_ms": round(benchmark_report["workloads"][0]["median_s"] * 1e3, 3),
            "mc_proxy_median_ms": round(benchmark_report["workloads"][2]["median_s"] * 1e3, 3),
            "best_speedup": round(benchmark_report["parallel_scaling"]["best_speedup_vs_1"], 2),
            "ram_budget_gb": benchmark_report["ram_budget_gb"],
        },
        "limitations": [
            "static, single-point, coplanar 2-D geometry only",
            "theta verified on a -3/0/+3 deg grid; wider angles are outside this gate's evidence",
            "v is constant at the principal row by construction; real sensor row direction needs calibration",
            "no lens distortion, occlusion, stray light, or non-coplanar rotation",
            "Optiland installed and import-checked only; no lens case executed",
            "GPU not tested (no tensor workload at G0, torch not installed)",
        ],
        "unused_config_fields_at_g0": list(config.unused_at_g0),
        "tests": tests_info["totals"] if tests_info else "NOT_INGESTED",
        "gate_aggregation": aggregation.to_dict(),
    }
    context.write_json("metrics.json", metrics)

    provenance = context.provenance(
        model_level=config.model_level,
        seeds=[config.run.seed],
        extra={
            "config_case_id": config.case_id,
            "units_internal": {"distance": "mm", "angle": "rad", "pixel": "pixel"},
            "geometry_model": "ideal pinhole, coplanar, virtual image plane",
        },
    )
    context.write_json("provenance.json", provenance)

    status_payload = {
        "schema_version": "1.0",
        "run_id": context.run_id,
        "gate": "G0",
        "status": gate_status,
        "scientific_claim_status": "SUPPORTED" if checks_pass else "NOT_SUPPORTED",
        "scientific_claim_scope": (
            "Ideal coplanar geometry implementation matches an independent vector/matrix chain "
            "within declared tolerances. No sensor-performance claim."
        ),
        "finished_at_utc": utc_now(),
        "frozen": True,
        "gate_checks": comparison.gate_checks,
        "boundary_cases_pass": boundaries_pass,
        "gate_aggregation": aggregation.to_dict(),
        "tests": tests_info["totals"] if tests_info else "NOT_INGESTED",
        "report_note": "report.html is written after this snapshot and is therefore not in outputs[]",
        "outputs": sorted(
            path.relative_to(context.directory).as_posix()
            for path in context.directory.rglob("*") if path.is_file()
        ),
    }
    context.write_json("run_status.json", status_payload)

    context.flush_log()
    report_html = render_report(context.directory, config, metrics, provenance, status_payload)
    context.write_text("report.html", report_html)
    print(f"report: {context.path('report.html')}", flush=True)

    return context, metrics


def _gpu_summary(environment: dict[str, Any]) -> str:
    """Readable GPU string; never a raw Python list in reports."""

    if not environment["gpu"]["available"]:
        return f"not available ({environment['gpu']['reason']})"
    parts = []
    for device in environment["gpu"]["devices"]:
        parts.append(
            f"{device.get('name', 'UNKNOWN')} "
            f"({device.get('memory_total_mb', 'UNKNOWN')} MB, "
            f"driver {device.get('driver_version', 'UNKNOWN')})"
        )
    return "; ".join(parts)
