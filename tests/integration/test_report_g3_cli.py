"""Regression guard for ReportService routing of saved G3 demonstration runs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from optisys.cli import EXIT_OK, cmd_report


@pytest.mark.parametrize("gate", ["G3", "G4"])
def test_report_cli_routes_g3_and_g4_through_report_service(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], gate: str
) -> None:
    run_dir = tmp_path / f"{gate.lower()}-demo"
    run_dir.mkdir()
    for name, payload in (
        ("config_snapshot.yaml", "schema_version: '4.0'\n"),
        ("metrics.json", {"report_kind": "G3_DEMO" if gate == "G3" else "G4"}),
        ("provenance.json", {"source": "test fixture"}),
        ("run_status.json", {"gate": gate, "frozen": True}),
    ):
        path = run_dir / name
        if isinstance(payload, dict):
            path.write_text(json.dumps(payload), encoding="utf-8")
        else:
            path.write_text(payload, encoding="utf-8")

    calls = []

    class FakeReportService:
        def __init__(self, runs_dir: Path, *, verdict_root: Path) -> None:
            calls.append((runs_dir, verdict_root))

        def build(self, target: Path):
            calls.append(target)
            return SimpleNamespace(
                html_path=tmp_path / "derived" / "report.html",
                markdown_path=tmp_path / "derived" / "report.md",
                frozen_run_untouched=True,
            )

    monkeypatch.setattr("optisys.reports.report_service.ReportService", FakeReportService)
    result = cmd_report(argparse.Namespace(run=run_dir))
    assert result == EXIT_OK
    assert calls[-1] == run_dir
    output = capsys.readouterr().out
    assert "frozen_run_untouched: True" in output
    assert "report:" in output and "markdown:" in output
