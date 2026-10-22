"""G2 integration: the optical smoke command produces real, checkable evidence."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from optisys.cli import EXIT_OK, EXIT_FAIL, main

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs" / "triangulation_g2_l1.yaml"


def test_optics_smoke_produces_v4_evidence(tmp_path) -> None:
    runs = tmp_path / "runs"
    code = main([
        "optics-smoke", "--config", str(CONFIG),
        "--project-root", str(ROOT), "--runs-dir", str(runs),
    ])
    assert code == EXIT_OK
    run = next(path for path in runs.iterdir() if path.is_dir())

    for name in ("config_snapshot.yaml", "optical_model_snapshot.yaml",
                 "tolerance_distributions.yaml", "optimization_objectives_frozen.yaml",
                 "source_tree_manifest.json", "environment.json", "metrics.json",
                 "gate_checks.json", "provenance.json", "run_status.json",
                 "report.html", "report.md"):
        assert (run / name).is_file(), name

    status = json.loads((run / "run_status.json").read_text(encoding="utf-8"))
    assert status["gate"] == "G2"
    assert status["model_level_emitted"] == "L1-approximate"

    validation = json.loads((run / "optics" / "optical_validation.json").read_text(encoding="utf-8"))
    assert validation["backend_executed"] is True
    assert validation["trace_rows"] > 0
    assert validation["backend"]["version"] == "0.6.3"

    with (run / "optics" / "raytrace_reference.csv").open(encoding="utf-8") as handle:
        rays = list(csv.DictReader(handle))
    assert len(rays) == validation["trace_rows"]
    assert {"Z_mm", "ray_index", "x_image_mm", "y_image_mm", "intensity", "valid"} <= set(rays[0])

    with (run / "optics" / "energy_and_capture.csv").open(encoding="utf-8") as handle:
        energy = list(csv.DictReader(handle))
    assert energy
    assert all(float(row["capture_fraction"]) <= 1.0 + 1e-9 for row in energy)

    assert (run / "optics" / "psf_or_footprint_examples.npz").is_file()
    assert len(list((run / "figures").glob("*.png"))) >= 1


def test_optics_smoke_rejects_a_g1_config(tmp_path) -> None:
    code = main([
        "optics-smoke", "--config", str(ROOT / "configs" / "triangulation_g1_l0.yaml"),
        "--project-root", str(ROOT), "--runs-dir", str(tmp_path / "runs"),
    ])
    assert code != EXIT_OK
