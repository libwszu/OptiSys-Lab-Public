"""Budgeted deterministic search: LHS screening plus compass refinement.

No deep-learning surrogate is used.  The objective is three-dimensional,
inexpensive enough to evaluate directly, and a surrogate would only add an
unverifiable approximation layer.

Every evaluated design is recorded, including the infeasible ones with their
reason codes.  The search stops when the pre-registered evaluation budget or
wall-clock cap is reached and keeps the best feasible candidate found.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

import numpy as np

from optisys.optimization.objectives import DesignMetrics
from optisys.optimization.search_space import Design, SearchSpace

EvaluateFn = Callable[[Design], DesignMetrics]


@dataclass
class SearchRecord:
    design: Design
    phase: str
    feasible: bool
    reason: str
    j_value: float | None
    rmse_mm: float | None
    frames: int
    wall_s: float

    def to_row(self) -> dict[str, Any]:
        return {
            **self.design.as_row(),
            "phase": self.phase,
            "feasible": self.feasible,
            "reason": self.reason,
            "j_value": self.j_value,
            "rmse_mm": self.rmse_mm,
            "frames": self.frames,
            "wall_s": self.wall_s,
        }


@dataclass
class SearchOutcome:
    best: Design | None
    best_metrics: DesignMetrics | None
    history: list[SearchRecord] = field(default_factory=list)
    n_evaluations: int = 0
    wall_s: float = 0.0
    stopped_by: str = "budget"

    def summary(self) -> dict[str, Any]:
        return {
            "best_design": None if self.best is None else self.best.as_row(),
            "best_metrics": None if self.best_metrics is None else self.best_metrics.to_row(),
            "n_evaluations": self.n_evaluations,
            "wall_s": self.wall_s,
            "stopped_by": self.stopped_by,
            "n_infeasible": sum(1 for r in self.history if not r.feasible),
        }


class BudgetedSearch:
    def __init__(self, space: SearchSpace, evaluate: EvaluateFn, *,
                 max_evaluations: int, max_wall_s: float, log: Callable[[str], None] | None = None
                 ) -> None:
        self.space = space
        self.evaluate = evaluate
        self.max_evaluations = int(max_evaluations)
        self.max_wall_s = float(max_wall_s)
        self.log = log or (lambda message: None)
        self.history: list[SearchRecord] = []
        self._cache: dict[str, DesignMetrics] = {}
        self._started = 0.0

    # ------------------------------------------------------------------
    def _exhausted(self) -> str | None:
        if len(self._cache) >= self.max_evaluations:
            return "evaluation_budget"
        if time.perf_counter() - self._started > self.max_wall_s:
            return "wall_clock_cap"
        return None

    def _evaluate(self, design: Design, phase: str) -> DesignMetrics:
        key = design.key()
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        metrics = self.evaluate(design)
        self._cache[key] = metrics
        record = SearchRecord(
            design=design, phase=phase, feasible=metrics.feasible, reason=metrics.reason,
            j_value=metrics.j_value, rmse_mm=metrics.rmse_mm, frames=metrics.frames,
            wall_s=metrics.wall_s,
        )
        self.history.append(record)
        if metrics.feasible and metrics.j_value is not None:
            self.log(
                f"[{phase}] {key} J={metrics.j_value:.4f} rmse={metrics.rmse_mm:.4f} mm "
                f"fail={metrics.failure_rate:.3f}"
            )
        elif not metrics.feasible:
            self.log(f"[{phase}] {key} {metrics.reason}")
        return metrics

    # ------------------------------------------------------------------
    def run(self, n_screen: int, seed: int, *, n_starts: int = 4,
            step_fractions: tuple[float, ...] = (0.15, 0.07, 0.03)) -> SearchOutcome:
        self._started = time.perf_counter()
        stop_reason = "budget"
        for design in self.space.lhs(n_screen, seed):
            if (reason := self._exhausted()) is not None:
                stop_reason = reason
                break
            self._evaluate(design, "screen")

        feasible = [m for m in self._cache.values() if m.feasible and m.j_value is not None]
        feasible.sort(key=lambda m: m.j_value)
        if not feasible:
            return SearchOutcome(
                best=None, best_metrics=None, history=self.history,
                n_evaluations=len(self._cache), wall_s=time.perf_counter() - self._started,
                stopped_by="no_feasible_screen",
            )

        starts = feasible[:n_starts]
        spans = np.array([high - low for low, high in self.space.bounds])
        for start_index, metrics in enumerate(starts):
            current = metrics.design
            current_value = metrics.j_value
            for stage, fraction in enumerate(step_fractions):
                improved = True
                while improved:
                    improved = False
                    for axis in range(3):
                        for sign in (-1.0, 1.0):
                            if (reason := self._exhausted()) is not None:
                                stop_reason = reason
                                break
                            step = sign * fraction * spans[axis]
                            vector = self.space.encode(current).copy()
                            vector[axis] += step
                            candidate = self.space.decode(vector).clip(self.space)
                            if candidate.key() == current.key():
                                continue
                            result = self._evaluate(candidate, f"refine{start_index}")
                            if (result.feasible and result.j_value is not None
                                    and result.j_value < current_value - 1e-9):
                                current = candidate
                                current_value = result.j_value
                                improved = True
                        if (reason := self._exhausted()) is not None:
                            break
                    if (reason := self._exhausted()) is not None:
                        break
                if (reason := self._exhausted()) is not None:
                    break
            if (reason := self._exhausted()) is not None:
                break

        feasible = [m for m in self._cache.values() if m.feasible and m.j_value is not None]
        feasible.sort(key=lambda m: m.j_value)
        best = feasible[0] if feasible else None
        return SearchOutcome(
            best=None if best is None else best.design,
            best_metrics=best,
            history=self.history,
            n_evaluations=len(self._cache),
            wall_s=time.perf_counter() - self._started,
            stopped_by=stop_reason,
        )


def history_rows(outcome: SearchOutcome) -> list[dict[str, Any]]:
    return [record.to_row() for record in outcome.history]
