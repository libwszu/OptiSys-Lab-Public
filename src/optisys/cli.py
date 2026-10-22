"""Command-line interface.

Commands that belong to later gates return ``NOT_IMPLEMENTED`` and a non-zero
exit code instead of pretending to work.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from optisys import __version__
from optisys.config import ConfigError, config_from_dict, load_config
from optisys.config_g1 import ResolvedG1Config, load_config_g1
from optisys.errors import Status
from optisys.evaluation.metrics import is_valid, summarise
from optisys.gates.g1 import run_g1
from optisys.pipeline import run_g0
from optisys.reports.report import render_report
from optisys.reports.report_g1 import render_g1_report

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_CONFIG = 2
EXIT_NOT_IMPLEMENTED = 3

DEFAULT_ROOT = Path(__file__).resolve().parents[2]


def load_any_config(path: str | Path):
    """Dispatch G0–G4 configuration schemas."""

    config_path = Path(path)
    if not config_path.is_file():
        raise ConfigError(f"config file not found: {config_path}")
    payload = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ConfigError("config root must be a mapping")
    version = str(payload.get("schema_version"))
    if version == "1.0":
        return load_config(config_path)
    if version == "2.0":
        return load_config_g1(config_path)
    if version == "3.0":
        from optisys.config_g2 import load_config_g2

        return load_config_g2(config_path)
    if version == "4.0":
        from optisys.config_g4 import load_pump976_config

        return load_pump976_config(config_path)
    raise ConfigError(f"unsupported schema_version {version!r}")


def _root(args: argparse.Namespace) -> Path:
    return Path(args.project_root).resolve() if args.project_root else DEFAULT_ROOT


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="optisys",
        description="OptiSys-Lab: coplanar laser-triangulation verification platform (G0)",
    )
    parser.add_argument("--version", action="version", version=f"optisys {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="validate a YAML configuration")
    validate.add_argument("--config", required=True, type=Path)
    validate.add_argument("--project-root", type=Path, default=None)
    validate.set_defaults(func=cmd_validate)

    simulate = subparsers.add_parser("simulate", help="run the G0 geometry or G1 imaging chain")
    simulate.add_argument("--config", required=True, type=Path)
    simulate.add_argument("--project-root", type=Path, default=None)
    simulate.add_argument("--runs-dir", type=Path, default=None)
    simulate.add_argument("--tests-summary", type=Path, default=None)
    simulate.add_argument("--tests-stdout", type=Path, default=None)
    simulate.add_argument("--tests-junit", type=Path, default=None)
    simulate.add_argument("--limit-frames", type=int, default=None,
                          help="development smoke limit; produces PARTIAL, never PASS")
    simulate.set_defaults(func=cmd_simulate)

    evaluate = subparsers.add_parser("evaluate", help="re-summarise a finished run")
    evaluate.add_argument("--run", required=True, type=Path)
    evaluate.set_defaults(func=cmd_evaluate)

    tolerance = subparsers.add_parser("tolerance", help="G2 tolerance Monte-Carlo")
    tolerance.add_argument("--config", required=True, type=Path)
    tolerance.add_argument("--project-root", type=Path, default=None)
    tolerance.add_argument("--runs-dir", type=Path, default=None)
    tolerance.add_argument("--workers", type=int, default=None)
    tolerance.add_argument("--quick", action="store_true")
    tolerance.set_defaults(func=cmd_tolerance)

    g2 = subparsers.add_parser("g2", help="full G2 chain: optics, tolerance, optimisation, holdout")
    g2.add_argument("--config", required=True, type=Path)
    g2.add_argument("--project-root", type=Path, default=None)
    g2.add_argument("--runs-dir", type=Path, default=None)
    g2.add_argument("--tests-summary", type=Path, default=None)
    g2.add_argument("--tests-stdout", type=Path, default=None)
    g2.add_argument("--tests-junit", type=Path, default=None)
    g2.add_argument("--tests-command", type=str, default=None)
    g2.add_argument("--tests-exit-code", type=int, default=None)
    g2.add_argument("--quick", action="store_true",
                    help="reduced panels; always produces PARTIAL")
    g2.add_argument("--final-draws", type=int, default=None)
    g2.add_argument("--search-evals", type=int, default=None)
    g2.add_argument("--workers", type=int, default=None)
    g2.add_argument("--skip-stages", type=str, default="")
    g2.set_defaults(func=cmd_g2)

    optics_smoke = subparsers.add_parser(
        "optics-smoke", help="G2 optical backend smoke test (V4-A/V4-B only)")
    optics_smoke.add_argument("--config", required=True, type=Path)
    optics_smoke.add_argument("--project-root", type=Path, default=None)
    optics_smoke.add_argument("--runs-dir", type=Path, default=None)
    optics_smoke.set_defaults(func=cmd_optics_smoke)

    report = subparsers.add_parser("report", help="re-render report.html for a finished run")
    report.add_argument("--run", required=True, type=Path)
    report.set_defaults(func=cmd_report)

    g3_demo = subparsers.add_parser(
        "g3-demo",
        help="short G3 demonstration run: real optics, deliberately small panel")
    g3_demo.add_argument("--config", type=Path, default=Path("configs/g3_demo.yaml"))
    g3_demo.add_argument("--project-root", type=Path, default=None)
    g3_demo.add_argument("--runs-dir", type=Path, default=None)
    g3_demo.add_argument("--assemblies", type=int, default=12,
                         help="assembly count; must stay below the G2 panel to remain honest")
    g3_demo.add_argument("--workers", type=int, default=1)
    g3_demo.add_argument("--condition", type=str, default="medium",
                         choices=("strong", "medium", "weak"))
    g3_demo.set_defaults(func=cmd_g3_demo)

    pump_validate = subparsers.add_parser(
        "pump976-validate", help="validate a schema 4.0 976 nm pump config")
    pump_validate.add_argument("--config", required=True, type=Path)
    pump_validate.set_defaults(func=cmd_pump976_validate)

    pump976 = subparsers.add_parser(
        "pump976", help="run the registered 976 nm multimode pump case")
    pump976.add_argument("--config", type=Path, default=Path("configs/pump976_g4_l0.yaml"))
    pump976.add_argument("--candidate", type=Path, default=Path("configs/pump976_g4_l1.yaml"))
    pump976.add_argument("--tolerance", type=Path, default=Path("configs/pump976_g4_tolerance.yaml"))
    pump976.add_argument("--project-root", type=Path, default=None)
    pump976.add_argument("--runs-dir", type=Path, default=None)
    pump976.add_argument("--rays", type=int, default=None,
                         help="low-cost override; the run is marked as a reduced sample")
    pump976.add_argument("--assemblies", type=int, default=None,
                         help="low-cost override applied to precheck and holdout")
    pump976.add_argument("--timeout", type=float, default=300.0)
    pump976.add_argument("--resume-run", type=Path, default=None,
                         help="resume a matching TIMEOUT/PARTIAL run after hash verification")
    pump976.set_defaults(func=cmd_pump976)

    return parser


def cmd_validate(args: argparse.Namespace) -> int:
    try:
        config = load_any_config(args.config)
    except ConfigError as exc:
        print(f"CONFIG_INVALID: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    summary = config.summary()
    if hasattr(config, "unused_at_g0"):
        summary["unused_at_g0"] = list(config.unused_at_g0)
    summary["config_sha256"] = config.sha256
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print("CONFIG_VALID")
    return EXIT_OK


def cmd_pump976_validate(args: argparse.Namespace) -> int:
    try:
        from optisys.gates.g4 import validate_pump976_config

        result = validate_pump976_config(args.config)
    except ConfigError as exc:
        print(f"CONFIG_INVALID: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("CONFIG_VALID")
    return EXIT_OK


def cmd_pump976(args: argparse.Namespace) -> int:
    try:
        from optisys.gates.g4 import run_pump976

        run_dir, status = run_pump976(
            args.config, candidate_path=args.candidate, tolerance_path=args.tolerance,
            project_root=_root(args), runs_dir=args.runs_dir,
            rays_override=args.rays, assemblies_override=args.assemblies,
            timeout_s=args.timeout, resume_run=args.resume_run,
        )
    except (ConfigError, ValueError, OSError, RuntimeError) as exc:
        print(f"G4_FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return EXIT_FAIL
    print(json.dumps({
        "run_id": run_dir.name, "run_dir": str(run_dir),
        "status": status.get("G4_ENGINEERING_EXECUTION_STATUS", status.get("status")),
        "model_level": status.get("model_level_emitted"),
        "optical_model_verification": status.get("G4_OPTICAL_MODEL_VERIFICATION"),
        "tolerance_status": status.get("G4_TOLERANCE_EVALUATION_STATUS"),
        "empirical_validation": status.get("G4_EMPIRICAL_VALIDATION_STATUS"),
        "claim": status.get("G4_SCIENTIFIC_CLAIM"),
    }, indent=2, ensure_ascii=False))
    # A reduced-size smoke is a valid completed command with run_status=PARTIAL;
    # the engineering/sample state remains explicit in the emitted JSON.
    return EXIT_OK if status.get("status") in ("PASS_WITH_DECLARED_DEVIATIONS", "PARTIAL") else EXIT_FAIL


def cmd_simulate(args: argparse.Namespace) -> int:
    try:
        config = load_any_config(args.config)
    except ConfigError as exc:
        print(f"CONFIG_INVALID: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    if config.model_level != "L0":
        print(
            f"NOT_IMPLEMENTED: model_level={config.model_level}; G0/G1 support L0 only",
            file=sys.stderr,
        )
        return EXIT_NOT_IMPLEMENTED

    if isinstance(config, ResolvedG1Config):
        context, metrics = run_g1(
            config, _root(args), runs_dir=args.runs_dir,
            tests_summary=args.tests_summary, tests_stdout=args.tests_stdout,
            tests_junit=args.tests_junit, limit_frames=args.limit_frames,
        )
        gate_status = json.loads(
            context.path("run_status.json").read_text(encoding="utf-8")
        )["status"]
        summary = {
            "run_id": context.run_id,
            "run_dir": str(context.directory),
            "gate": "G1",
            "status": gate_status,
            "frames": metrics["dataset"]["frames_attempted"],
            "report": str(context.path("report.html")),
        }
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return EXIT_OK if gate_status == "PASS" else EXIT_FAIL

    context, metrics = run_g0(
        config, _root(args), runs_dir=args.runs_dir,
        tests_summary=args.tests_summary, tests_stdout=args.tests_stdout,
    )
    gate_status = json.loads(
        context.path("run_status.json").read_text(encoding="utf-8")
    )["status"]
    summary = {
        "run_id": context.run_id,
        "run_dir": str(context.directory),
        "gate": "G0",
        "status": gate_status,
        "max_abs_u_error_px": metrics["chain"]["max_abs_u_error_px"],
        "max_Z_relative_error": metrics["chain"]["max_Z_relative_error"],
        "report": str(context.path("report.html")),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return EXIT_OK if gate_status == "PASS" else EXIT_FAIL


def cmd_evaluate(args: argparse.Namespace) -> int:
    run_dir = Path(args.run)
    samples = run_dir / "samples.csv"
    if not samples.is_file():
        print(f"RUN_NOT_FOUND: {samples}", file=sys.stderr)
        return EXIT_FAIL
    with samples.open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        print("EMPTY_SAMPLES", file=sys.stderr)
        return EXIT_FAIL

    status = json.loads((run_dir / "run_status.json").read_text(encoding="utf-8"))
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))

    if status.get("gate") == "G1" or metrics.get("report_kind") == "G1":
        return _evaluate_g1(run_dir, rows)

    status_counts: dict[str, int] = {}
    u_errors: list[float] = []
    z_rel: list[float] = []
    for row in rows:
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1
        u_errors.append(float(row["u_abs_error_px"]))
        if row["Z_rel_error"]:
            z_rel.append(float(row["Z_rel_error"]))

    payload = {
        "run": str(run_dir),
        "n_samples": len(rows),
        "status_counts": status_counts,
        "max_abs_u_error_px": max(u_errors),
        "p95_abs_u_error_px": sorted(u_errors)[int(0.95 * (len(u_errors) - 1))],
        "max_Z_relative_error": max(z_rel) if z_rel else None,
        "note": "G0 geometry re-evaluation only; no sensor accuracy is implied",
    }
    target = _output_target(run_dir, "evaluate", "evaluation.json")
    payload["output"] = str(target)
    payload["frozen_source_untouched"] = target.parent != run_dir
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False))
    return EXIT_OK


def _evaluate_g1(run_dir: Path, rows: list[dict[str, Any]]) -> int:
    """Derived re-evaluation of a frozen G1 run (never writes into the run)."""

    overall = summarise(rows, ("estimator_name",))
    by_split = summarise(rows, ("estimator_name", "dataset_split"))
    test_rows = [
        {
            "estimator_name": row["estimator_name"],
            "condition_id": row["condition_id"],
            "Z_gt_mm": row["Z_gt_mm"],
            "valid": is_valid(row),
        }
        for row in rows
        if row.get("dataset_split") == "test"
    ]
    payload = {
        "run": str(run_dir),
        "gate": "G1",
        "n_rows": len(rows),
        "per_estimator": overall,
        "per_estimator_split": by_split,
        "test_attempted": len(test_rows),
        "test_valid": sum(1 for item in test_rows if item["valid"]),
        "failure_rate_all_attempts": (
            1.0 - sum(1 for item in test_rows if item["valid"]) / len(test_rows)
            if test_rows else None
        ),
        "note": "derived from frozen samples.csv; no refit, no test-set tuning",
    }
    target = _output_target(run_dir, "evaluate", "evaluation.json")
    payload["output"] = str(target)
    payload["frozen_source_untouched"] = target.parent != run_dir
    target.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n",
                      encoding="utf-8")
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    return EXIT_OK


def cmd_tolerance(args: argparse.Namespace) -> int:
    """G2 tolerance stage; writes a run directory with V4 + tolerance evidence."""

    try:
        from optisys.config_g2 import ResolvedG2Config
    except ImportError:  # pragma: no cover
        print("NOT_IMPLEMENTED: G2 modules unavailable", file=sys.stderr)
        return EXIT_NOT_IMPLEMENTED
    try:
        config = load_any_config(args.config)
    except ConfigError as exc:
        print(f"CONFIG_INVALID: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    if not isinstance(config, ResolvedG2Config):
        print("CONFIG_INVALID: tolerance requires a schema 3.0 G2 configuration",
              file=sys.stderr)
        return EXIT_CONFIG

    from optisys.gates.g2 import run_g2

    context, metrics = run_g2(
        config, _root(args), runs_dir=args.runs_dir, quick=args.quick,
        worker_override=args.workers, skip_stages=("D", "E"),
    )
    status = json.loads(context.path("run_status.json").read_text(encoding="utf-8"))
    print(json.dumps({"run_id": context.run_id, "run_dir": str(context.directory),
                      "status": status["status"],
                      "tolerance": metrics["results"]["tolerance"]["precheck"]
                      if "precheck" in metrics["results"].get("tolerance", {}) else "NOT_RUN"},
                     indent=2, ensure_ascii=False))
    return EXIT_OK if status["status"] == "PASS" else EXIT_FAIL


def cmd_g2(args: argparse.Namespace) -> int:
    try:
        from optisys.config_g2 import ResolvedG2Config
    except ImportError:  # pragma: no cover
        print("NOT_IMPLEMENTED: G2 modules unavailable", file=sys.stderr)
        return EXIT_NOT_IMPLEMENTED
    try:
        config = load_any_config(args.config)
    except ConfigError as exc:
        print(f"CONFIG_INVALID: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    if not isinstance(config, ResolvedG2Config):
        print("CONFIG_INVALID: the g2 command requires a schema 3.0 configuration",
              file=sys.stderr)
        return EXIT_CONFIG

    from optisys.gates.g2 import run_g2

    skip = tuple(part for part in args.skip_stages.split(",") if part)
    context, metrics = run_g2(
        config, _root(args), runs_dir=args.runs_dir,
        tests_summary=args.tests_summary, tests_stdout=args.tests_stdout,
        tests_junit=args.tests_junit, tests_command=args.tests_command,
        tests_exit_code=args.tests_exit_code, quick=args.quick,
        final_draws=args.final_draws, search_evals=args.search_evals,
        worker_override=args.workers, skip_stages=skip,
    )
    status = json.loads(context.path("run_status.json").read_text(encoding="utf-8"))
    summary = {
        "run_id": context.run_id,
        "run_dir": str(context.directory),
        "status": status["status"],
        "scientific_claim_status": status["scientific_claim_status"],
        "model_level_emitted": status["model_level_emitted"],
        "workers": metrics["compute"]["workers"],
        "wall_time_s": metrics["compute"]["wall_time_s"],
        "report": str(context.path("report.html")),
    }
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return EXIT_OK if status["status"] == "PASS" else EXIT_FAIL


def cmd_optics_smoke(args: argparse.Namespace) -> int:
    try:
        from optisys.config_g2 import ResolvedG2Config
    except ImportError:  # pragma: no cover
        print("NOT_IMPLEMENTED: G2 modules unavailable", file=sys.stderr)
        return EXIT_NOT_IMPLEMENTED
    try:
        config = load_any_config(args.config)
    except ConfigError as exc:
        print(f"CONFIG_INVALID: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    if not isinstance(config, ResolvedG2Config):
        print("CONFIG_INVALID: optics-smoke requires a schema 3.0 configuration",
              file=sys.stderr)
        return EXIT_CONFIG

    from optisys.gates.g2 import run_g2

    context, metrics = run_g2(
        config, _root(args), runs_dir=args.runs_dir, quick=True,
        worker_override=1, skip_stages=("C", "D", "E"),
    )
    print(json.dumps({
        "run_id": context.run_id,
        "run_dir": str(context.directory),
        "v4a": metrics["results"]["gate_checks"]["V4_A_OVERALL"]["value"],
        "v4b": metrics["results"]["gate_checks"]["V4_B_OVERALL"]["value"],
    }, indent=2, ensure_ascii=False))
    return EXIT_OK if metrics["results"]["gate_checks"]["V4_A_OVERALL"]["pass"] else EXIT_FAIL


def _resolve_report_config(run_dir: Path):
    """Load the config snapshot of a finished run at the right schema version.

    PRE-G3-06: this used to dispatch only on ``2.0`` and fall through to the
    schema 1.0 loader for everything else, so ``report --run <G2 run>`` raised
    ``ConfigError: unsupported schema_version '3.0'``.
    """

    snapshot = run_dir / "config_snapshot.yaml"
    data = yaml.safe_load(snapshot.read_text(encoding="utf-8"))
    version = str(data.get("schema_version"))
    if version == "3.0":
        from optisys.config_g2 import load_config_g2

        return load_config_g2(snapshot)
    if version == "2.0":
        return load_config_g1(snapshot)
    if version == "1.0":
        return config_from_dict(
            data,
            path=snapshot,
            sha256=hashlib.sha256(snapshot.read_bytes()).hexdigest(),
        )
    raise ConfigError(f"unsupported schema_version {version!r} in {snapshot}")


def cmd_report(args: argparse.Namespace) -> int:
    run_dir = Path(args.run)
    required = ["config_snapshot.yaml", "metrics.json", "provenance.json", "run_status.json"]
    missing = [name for name in required if not (run_dir / name).is_file()]
    if missing:
        print(f"RUN_INCOMPLETE: missing {', '.join(missing)}", file=sys.stderr)
        return EXIT_FAIL
    status_probe = json.loads((run_dir / "run_status.json").read_text(encoding="utf-8"))
    if status_probe.get("gate") in ("G3", "G4"):
        from optisys.reports.report_service import ReportService

        service = ReportService(run_dir.parent, verdict_root=DEFAULT_ROOT)
        result = service.build(run_dir)
        print(f"report: {result.html_path}")
        print(f"markdown: {result.markdown_path}")
        print(f"frozen_run_untouched: {result.frozen_run_untouched}")
        return EXIT_OK
    try:
        config = _resolve_report_config(run_dir)
    except ConfigError as exc:
        print(f"CONFIG_INVALID: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
    provenance = json.loads((run_dir / "provenance.json").read_text(encoding="utf-8"))
    status = json.loads((run_dir / "run_status.json").read_text(encoding="utf-8"))
    target = _output_target(run_dir, "report", "report.html")
    if target.parent != run_dir:
        if (run_dir / "figures").is_dir():
            shutil.copytree(run_dir / "figures", target.parent / "figures",
                            dirs_exist_ok=True)
        if (run_dir / "representative_frames").is_dir():
            shutil.copytree(run_dir / "representative_frames",
                            target.parent / "representative_frames", dirs_exist_ok=True)
    kind = str(metrics.get("report_kind") or "")
    if kind == "G2":
        from optisys.reports.report_g2 import render_g2_report

        html_text = render_g2_report(run_dir, config, metrics, provenance, status)
    elif kind == "G1":
        html_text = render_g1_report(run_dir, config, metrics, provenance, status)
    else:
        html_text = render_report(run_dir, config, metrics, provenance, status)
    target.write_text(html_text, encoding="utf-8")
    print(f"report: {target}")
    print(f"frozen_run_untouched: {target.parent != run_dir}")
    return EXIT_OK


def _is_frozen(run_dir: Path) -> bool:
    """Runs are frozen by default; only an explicit `frozen: false` allows drafts."""

    status_path = run_dir / "run_status.json"
    if not status_path.is_file():
        return True
    try:
        payload = json.loads(status_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return True
    return bool(payload.get("frozen", True))


def cmd_g3_demo(args: argparse.Namespace) -> int:
    """Short demonstration run: real optics, small panel, explicit boundary."""

    try:
        from optisys.config_g2 import ResolvedG2Config
    except ImportError:  # pragma: no cover
        print("NOT_IMPLEMENTED: G2/G3 modules unavailable", file=sys.stderr)
        return EXIT_NOT_IMPLEMENTED
    try:
        config = load_any_config(args.config)
    except ConfigError as exc:
        print(f"CONFIG_INVALID: {exc}", file=sys.stderr)
        return EXIT_CONFIG
    if not isinstance(config, ResolvedG2Config):
        print("CONFIG_INVALID: g3-demo requires a schema 3.0 configuration",
              file=sys.stderr)
        return EXIT_CONFIG
    if args.assemblies < 1:
        print("CONFIG_INVALID: --assemblies must be >= 1", file=sys.stderr)
        return EXIT_CONFIG
    if args.assemblies >= 2000:
        print("CONFIG_INVALID: --assemblies must stay below the G2 panel (2000); "
              "use the g2 command for a real gate run", file=sys.stderr)
        return EXIT_CONFIG

    from optisys.gates.g3_demo import run_g3_demo

    context, result = run_g3_demo(
        config, _root(args), assemblies=args.assemblies, workers=args.workers,
        runs_dir=args.runs_dir, condition=args.condition,
    )
    print(json.dumps({
        "run_id": result["run_id"],
        "run_dir": result["run_dir"],
        "status": result["status"],
        "wall_s": round(result["wall_s"], 1),
        "assemblies": result["assemblies"],
        "rows": result["rows"],
        "condition": result["condition"],
        "comparable_to_g2": False,
    }, indent=2, ensure_ascii=False))
    return EXIT_OK if result["status"] == "PASS" else EXIT_FAIL


def _output_target(run_dir: Path, kind: str, filename: str) -> Path:
    """Return a writable output path without touching frozen evidence."""

    if not _is_frozen(run_dir):
        return run_dir / filename
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory = run_dir.parent / "_derived" / run_dir.name / f"{stamp}_{kind}"
    directory.mkdir(parents=True, exist_ok=False)
    return directory / filename


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
