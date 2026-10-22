"""CLI integration tests: honest exit codes and a complete evidence folder."""

from __future__ import annotations

import csv
import json
from functools import partial
from pathlib import Path

import pytest
import yaml

import optisys.pipeline as pipeline
from optisys.cli import EXIT_CONFIG, EXIT_FAIL, EXIT_NOT_IMPLEMENTED, EXIT_OK, main
from optisys.runtime.compute import benchmark as real_benchmark

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs" / "triangulation_v0.yaml"


def _fast_benchmark(spec, seed=0):
    return real_benchmark(
        spec,
        seed=seed,
        mc_samples=2000,
        workers=(1,),
        parallel_reps=1,
        analytic_reps=5,
        reference_reps=2,
        mc_reps=1,
    )


@pytest.fixture()
def passing_tests_summary(tmp_path):
    path = tmp_path / "tests_summary.json"
    path.write_text(json.dumps({
        "totals": {"passed": 200, "failed": 0, "skipped": 0, "total": 200},
        "not_run": [],
    }), encoding="utf-8")
    return path


@pytest.fixture()
def fast_pipeline(monkeypatch):
    monkeypatch.setattr(pipeline, "benchmark", _fast_benchmark)


def test_validate_prints_resolved_config(capsys) -> None:
    assert main(["validate", "--config", str(CONFIG)]) == EXIT_OK
    output = capsys.readouterr().out
    payload = json.loads(output.split("CONFIG_VALID")[0])
    assert payload["fx_px"] == pytest.approx(2318.8405797101445, rel=1e-15)
    assert payload["working_range_mm"] == [100.0, 300.0]
    assert "CONFIG_VALID" in output


def test_validate_rejects_unknown_field(tmp_path, capsys) -> None:
    data = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    data["camera"]["shutter"] = "rolling"
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(data), encoding="utf-8")
    assert main(["validate", "--config", str(bad)]) == EXIT_CONFIG
    assert "CONFIG_INVALID" in capsys.readouterr().err


def test_tolerance_rejects_a_non_g2_config(capsys) -> None:
    """G2 implemented the tolerance stage; the guard is now schema validation.

    The old assertion (`NOT_IMPLEMENTED`) is obsolete and would hide the fact
    that the command exists.
    """

    assert main(["tolerance", "--config", str(CONFIG)]) == EXIT_CONFIG
    assert "CONFIG_INVALID" in capsys.readouterr().err


def test_g2_command_can_skip_the_monte_carlo_stages(tmp_path) -> None:
    """The cheap stage-skip path, so the test suite stays under a few minutes.

    The full tolerance/optimisation/holdout chain is exercised by the run
    scripts, not inside pytest.
    """

    runs = tmp_path / "runs"
    code = main([
        "g2", "--config", str(ROOT / "configs" / "triangulation_g2_l1.yaml"),
        "--project-root", str(ROOT), "--runs-dir", str(runs),
        "--workers", "1", "--skip-stages", "C,D,E",
    ])
    assert code in (EXIT_OK, EXIT_FAIL)
    run = next(path for path in runs.iterdir() if path.is_dir())
    assert (run / "optics" / "optical_validation.json").is_file()
    assert (run / "optimization" / "candidates_frozen.json").is_file()
    assert not (run / "tolerance" / "oat_samples.csv").is_file()


def test_simulate_writes_complete_run(tmp_path, fast_pipeline, passing_tests_summary, capsys) -> None:
    runs = tmp_path / "runs"
    exit_code = main([
        "simulate", "--config", str(CONFIG),
        "--project-root", str(ROOT), "--runs-dir", str(runs), "--tests-summary", str(passing_tests_summary),
    ])
    assert exit_code == EXIT_OK
    run_dirs = [path for path in runs.iterdir() if path.is_dir()]
    assert len(run_dirs) == 1
    run = run_dirs[0]

    for name in (
        "config_snapshot.yaml", "environment.json", "compute_plan.json", "benchmark.json",
        "metrics.json", "samples.csv", "provenance.json", "run_status.json", "run.log",
        "formula_comparison.csv", "boundary_cases.csv", "report.html",
    ):
        assert (run / name).is_file(), name

    figures = sorted((run / "figures").glob("*.png"))
    assert len(figures) == 4
    assert len(list((run / "figures").glob("*.csv"))) == 4

    status = json.loads((run / "run_status.json").read_text(encoding="utf-8"))
    assert status["status"] == "PASS"
    assert status["gate"] == "G0"
    assert all(check["pass"] for check in status["gate_checks"].values())

    with (run / "samples.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 3 * 41
    assert {row["status"] for row in rows} == {"OK"}

    assert (run / "config_snapshot.yaml").read_bytes() == CONFIG.read_bytes()
    report = (run / "report.html").read_text(encoding="utf-8")
    assert "G0" in report and "fig4_independent_residual.png" in report

    # evaluate command must accept the produced run; frozen evidence stays untouched
    assert main(["evaluate", "--run", str(run)]) == EXIT_OK
    derived = runs / "_derived" / run.name
    assert list(derived.rglob("evaluation.json"))


def test_report_command_regenerates_html(tmp_path, fast_pipeline, passing_tests_summary) -> None:
    runs = tmp_path / "runs"
    assert main([
        "simulate", "--config", str(CONFIG),
        "--project-root", str(ROOT), "--runs-dir", str(runs), "--tests-summary", str(passing_tests_summary),
    ]) == EXIT_OK
    run = next(path for path in runs.iterdir() if path.is_dir())
    original = (run / "report.html").read_bytes()
    assert main(["report", "--run", str(run)]) == EXIT_OK
    assert (run / "report.html").read_bytes() == original
    derived_reports = list((runs / "_derived" / run.name).rglob("report.html"))
    assert derived_reports
    assert "OptiSys-Lab" in derived_reports[0].read_text(encoding="utf-8")


def test_runs_never_overwrite_each_other(tmp_path, fast_pipeline, passing_tests_summary) -> None:
    runs = tmp_path / "runs"
    for _ in range(2):
        assert main([
            "simulate", "--config", str(CONFIG),
            "--project-root", str(ROOT), "--runs-dir", str(runs), "--tests-summary", str(passing_tests_summary),
        ]) == EXIT_OK
    assert len([path for path in runs.iterdir() if path.is_dir()]) == 2


def test_simulate_returns_nonzero_when_a_gate_check_fails(
    tmp_path, fast_pipeline, passing_tests_summary, monkeypatch
) -> None:
    real = pipeline.compare_chain

    def broken(config):
        result = real(config)
        result.gate_checks["max_abs_u_error_px"]["pass"] = False
        return result

    monkeypatch.setattr(pipeline, "compare_chain", broken)
    runs = tmp_path / "runs"
    code = main([
        "simulate", "--config", str(CONFIG),
        "--project-root", str(ROOT), "--runs-dir", str(runs), "--tests-summary", str(passing_tests_summary),
    ])
    assert code != EXIT_OK
    run = next(path for path in runs.iterdir() if path.is_dir())
    status = json.loads((run / "run_status.json").read_text(encoding="utf-8"))
    assert status["status"] == "FAIL"
    assert status["gate_aggregation"]["numeric_checks_pass"] is False


def test_failed_pytest_evidence_blocks_gate(tmp_path, fast_pipeline) -> None:
    summary = tmp_path / "tests_summary.json"
    summary.write_text(json.dumps({
        "totals": {"passed": 199, "failed": 1, "skipped": 0, "total": 200},
        "not_run": [],
    }), encoding="utf-8")
    runs = tmp_path / "runs"
    code = main([
        "simulate", "--config", str(CONFIG),
        "--project-root", str(ROOT), "--runs-dir", str(runs),
        "--tests-summary", str(summary),
    ])
    assert code != EXIT_OK
    run = next(path for path in runs.iterdir() if path.is_dir())
    status = json.loads((run / "run_status.json").read_text(encoding="utf-8"))
    assert status["status"] == "FAIL"
    assert any("tests failed" in item for item in status["gate_aggregation"]["failures"])


def test_frozen_run_is_not_modified_by_report_or_evaluate(tmp_path, fast_pipeline, passing_tests_summary) -> None:
    import hashlib

    runs = tmp_path / "runs"
    assert main([
        "simulate", "--config", str(CONFIG),
        "--project-root", str(ROOT), "--runs-dir", str(runs), "--tests-summary", str(passing_tests_summary),
    ]) == EXIT_OK
    run = next(path for path in runs.iterdir() if path.is_dir())
    before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
              for path in run.iterdir() if path.is_file()}

    assert main(["report", "--run", str(run)]) == EXIT_OK
    after = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
             for path in run.iterdir() if path.is_file()}
    assert before == after

    assert main(["evaluate", "--run", str(run)]) == EXIT_OK
    after_eval = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                  for path in run.iterdir() if path.is_file()}
    assert before == after_eval

    derived = runs / "_derived" / run.name
    assert list(derived.rglob("report.html"))
    assert list(derived.rglob("evaluation.json"))
