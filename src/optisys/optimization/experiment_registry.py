"""Candidate registry: freeze baseline/nominal/robust before the final test."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from optisys.optimization.objectives import DesignMetrics
from optisys.optimization.search_space import Design


@dataclass
class Candidate:
    candidate_id: str
    name: str
    design: Design
    optical_config_sha256: str
    geometry_parameters_and_units: dict[str, Any]
    calibration_strategy: str
    objective_pre_registered_version: str
    search_budget_used: dict[str, Any]
    validation_metrics: dict[str, Any]
    constraint_feasibility: dict[str, Any]
    source_code_sha256: str
    selected_at_utc: str
    notes: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["design"] = self.design.as_row()
        payload["notes"] = list(self.notes)
        return payload


def make_candidate(*, name: str, design: Design, metrics: DesignMetrics | None,
                   optical_config_sha256: str, calibration_strategy: str,
                   objective_version: str, budget: dict[str, Any],
                   source_code_sha256: str, feasibility: dict[str, Any],
                   notes: tuple[str, ...] = ()) -> Candidate:
    candidate_id = hashlib.sha256(
        f"{name}|{design.key()}|{optical_config_sha256}|{objective_version}".encode("utf-8")
    ).hexdigest()[:16]
    return Candidate(
        candidate_id=candidate_id,
        name=name,
        design=design,
        optical_config_sha256=optical_config_sha256,
        geometry_parameters_and_units={
            "baseline_mm": design.baseline_mm,
            "focal_length_mm": design.focal_length_mm,
            "theta_deg": design.theta_deg,
            "theta_rad": design.theta_rad,
        },
        calibration_strategy=calibration_strategy,
        objective_pre_registered_version=objective_version,
        search_budget_used=budget,
        validation_metrics={} if metrics is None else metrics.to_row(),
        constraint_feasibility=feasibility,
        source_code_sha256=source_code_sha256,
        selected_at_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        notes=notes,
    )


@dataclass
class CandidateRegistry:
    candidates: list[Candidate] = field(default_factory=list)
    frozen_at_utc: str = ""
    payload_hash: str = ""

    def add(self, candidate: Candidate) -> None:
        if any(c.name == candidate.name for c in self.candidates):
            raise ValueError(f"candidate name {candidate.name!r} already registered")
        self.candidates.append(candidate)

    def freeze(self) -> None:
        self.frozen_at_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
        body = [c.to_dict() for c in self.candidates]
        self.payload_hash = hashlib.sha256(
            json.dumps(body, sort_keys=True, default=str).encode("utf-8")
        ).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "frozen_at_utc": self.frozen_at_utc,
            "registry_sha256": self.payload_hash,
            "candidates": [c.to_dict() for c in self.candidates],
        }

    def get(self, name: str) -> Candidate:
        for candidate in self.candidates:
            if candidate.name == name:
                return candidate
        raise KeyError(name)
