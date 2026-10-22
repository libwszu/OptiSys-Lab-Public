"""G1 pipeline integration: limited run, evidence layout, frozen protection."""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

import optisys.gates.g1 as g1_module
from optisys.cli import EXIT_OK, main

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs" / "triangulation_g1_l0.yaml"


def _stub_benchmark(config):
    return {
        "frame_render": {"median_ms": 110.0, "p95_ms": 120.0, "samples": 9},
        "roi_detection": {"median_ms": 18.0, "p95_ms": 20.0},
        "estimators": {
            "centroid": {"median_ms": 0.4, "p95_ms": 0.6},
            "gaussian_1d": {"median_ms": 22.0, "p95_ms": 26.0},
            "gaussian_2d": {"median_ms": 8.0, "p95_ms": 10.0},
        },
        "parallel": {"decision": "single_process", "best_workers": 1,
                     "best_speedup_vs_1": 1.0, "cases": [], "frames": 8},
        "thread_environment": {"OMP_NUM_THREADS": "1"},
        "gpu": "NOT_TESTED",
    }


@pytest.fixture()
def stub_benchmark(monkeypatch):
    monkeypatch.setattr(g1_module, "_benchmark_g1", _stub_benchmark)


@pytest.fixture()
def tests_summary(tmp_path):
    path = tmp_path / "tests_summary.json"
    path.write_text(json.dumps({
        "totals": {"passed": 200, "failed": 0, "skipped": 0, "total": 200},
        "not_run": [],
    }), encoding="utf-8")
    return path


def test_limited_g1_run_is_partial_but_complete_in_layout(tmp_path, stub_benchmark, tests_summary) -> None:
    runs = tmp_path / "runs"
    code = main([
        "simulate", "--config", str(CONFIG),
        "--project-root", str(ROOT), "--runs-dir", str(runs),
        "--tests-summary", str(tests_summary), "--limit-frames", "60",
    ])
    assert code != EXIT_OK
    run = next(path for path in runs.iterdir() if path.is_dir())
    status = json.loads((run / "run_status.json").read_text(encoding="utf-8"))
    assert status["status"] == "PARTIAL"
    assert status["gate"] == "G1"
    assert "limited run" in " ".join(status["gate_aggregation"]["notes"])

    for name in ("config_snapshot.yaml", "environment.json", "compute_plan.json",
                 "benchmark.json", "metrics.json", "samples.csv", "calibration.json",
                 "split_manifest.json", "provenance.json", "run_status.json", "report.html",
                 "tests_summary.json"):
        assert (run / name).is_file(), name
    assert len(list((run / "figures").glob("*.png"))) == 7
    assert len(list((run / "representative_frames").glob("*.npz"))) == 6

    split = json.loads((run / "split_manifest.json").read_text(encoding="utf-8"))
    assert split["counts"] == {"calib": 27, "validation": 7, "test": 7}

    calibration = json.loads((run / "calibration.json").read_text(encoding="utf-8"))
    assert calibration["fits"]["oracle"]["status"] == "OK"
    for name in ("centroid", "gaussian_1d", "gaussian_2d"):
        assert calibration["fits"][name]["status"] == "NOT_ESTIMABLE"

    with (run / "samples.csv").open(encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 60 * 3
    assert {row["estimator_name"] for row in rows} == {"centroid", "gaussian_1d", "gaussian_2d"}

    # The three estimators must share the same image seed for each frame.
    seeds = {row["sample_id"].rsplit("|", 1)[0]: row["image_seed"] for row in rows}
    assert len(seeds) == 60
    assert len({row["image_seed"] for row in rows}) == 60


def test_frozen_g1_report_goes_to_derived(tmp_path, stub_benchmark, tests_summary) -> None:
    runs = tmp_path / "runs"
    assert main([
        "simulate", "--config", str(CONFIG),
        "--project-root", str(ROOT), "--runs-dir", str(runs),
        "--tests-summary", str(tests_summary), "--limit-frames", "30",
    ]) != EXIT_OK
    run = next(path for path in runs.iterdir() if path.is_dir())
    before = hashlib.sha256((run / "report.html").read_bytes()).hexdigest()
    assert main(["report", "--run", str(run)]) == EXIT_OK
    after = hashlib.sha256((run / "report.html").read_bytes()).hexdigest()
    assert before == after
    derived = list((runs / "_derived" / run.name).rglob("report.html"))
    assert derived
    assert "G1" in derived[0].read_text(encoding="utf-8")


def test_worker_policy_follows_measured_speedup() -> None:
    from optisys.gates.g1 import _workers_from_benchmark

    environment = {"cpu": {"physical_cores": 6}}
    assert _workers_from_benchmark(
        {"parallel": {"decision": "single_process", "best_workers": 1}}, environment
    ) == 1
    assert _workers_from_benchmark(
        {"parallel": {"decision": "workers_4", "best_workers": 4}}, environment
    ) == 4
    assert _workers_from_benchmark(
        {"parallel": {"decision": "workers_8", "best_workers": 8}}, environment
    ) == 6


def test_worker_policy_defaults_to_single_process_without_measured_gain() -> None:
    """PRE-06: this used to be a duplicate definition that shadowed the test above.

    It now covers a different property: the policy must fall back to one worker
    when the evidence is missing or when the core count is unknown, instead of
    silently using every logical core.
    """

    from optisys.gates.g1 import _workers_from_benchmark

    assert _workers_from_benchmark({}, {"cpu": {"physical_cores": 6}}) == 1
    assert _workers_from_benchmark({"parallel": {}}, {"cpu": {"physical_cores": 6}}) == 1
    assert _workers_from_benchmark(
        {"parallel": {"decision": "workers_4", "best_workers": 4}}, {"cpu": {}}
    ) == 1
    assert _workers_from_benchmark(
        {"parallel": {"decision": "workers_2", "best_workers": 2}},
        {"cpu": {"physical_cores": 6}},
    ) == 2
