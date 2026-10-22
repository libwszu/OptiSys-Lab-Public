"""UI context: the only object pages are allowed to reach through.

Pages never import ``optisys.gates.g2`` or start a subprocess directly.  They
call this context, which wraps the four tested interfaces the task book names:
``ConfigService`` (config loading), ``RunRepository`` (run parsing),
``JobService`` (job control) and ``ReportService`` (report rendering).

Keeping this indirection in one file makes the UI testable without Streamlit:
:func:`build_context` can be constructed in a plain pytest and asserted on.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from optisys.presentation.run_repository import (
    RunSummary,
    list_runs,
    load_latest_per_gate,
    load_run,
)
from optisys.reports.report_service import ReportService, load_verdict, science_strip


@dataclass
class UiContext:
    project_root: Path
    runs_dir: Path
    python: str
    strip: dict[str, Any]
    verdict: dict[str, Any]
    selected_run_id: str
    reports: ReportService

    # -- runs -----------------------------------------------------------
    def run_dirs(self, *, include_derived: bool = False) -> list[Path]:
        return list_runs(self.runs_dir, include_derived=include_derived)

    def load(self, run_id: str) -> RunSummary:
        return load_run(self.runs_dir / run_id)

    def latest(self) -> dict[str, RunSummary]:
        return load_latest_per_gate(self.runs_dir)

    def select_run(self, run_id: str) -> None:
        self.selected_run_id = run_id

    # -- science --------------------------------------------------------
    def refresh_verdict(self) -> None:
        self.verdict = load_verdict(self.project_root)
        self.strip = science_strip(self.verdict)


def build_context(project_root: Path | None = None) -> UiContext:
    root = Path(project_root) if project_root else _detect_root()
    runs_dir = root / "runs"
    runs_dir.mkdir(parents=True, exist_ok=True)

    verdict = load_verdict(root)
    strip = science_strip(verdict)

    runs = list_runs(runs_dir)
    selected = runs[-1].name if runs else ""

    return UiContext(
        project_root=root,
        runs_dir=runs_dir,
        python=sys.executable,
        strip=strip,
        verdict=verdict,
        selected_run_id=selected,
        reports=ReportService(runs_dir, verdict_root=root),
    )


def _detect_root() -> Path:
    """Find the project root from this file's location (``app/ui_context.py``)."""

    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "pyproject.toml").is_file() and (parent / "src").is_dir():
            return parent
    return Path.cwd()