"""Fixed distance splits: calibration / validation / final test.

Splitting is done by **whole distances**, never by individual frames, so that
no noise realisation of a test distance can enter calibration.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class SplitManifest:
    calib_distances: tuple[float, ...]
    validation_distances: tuple[float, ...]
    test_distances: tuple[float, ...]

    def __post_init__(self) -> None:
        calib = {round(value, 6) for value in self.calib_distances}
        validation = {round(value, 6) for value in self.validation_distances}
        test = {round(value, 6) for value in self.test_distances}
        if calib & validation or calib & test or validation & test:
            raise ValueError("split distances overlap")
        if not calib:
            raise ValueError("calibration split is empty")

    def split_for(self, distance_mm: float) -> str:
        key = round(float(distance_mm), 6)
        if key in {round(v, 6) for v in self.calib_distances}:
            return "calib"
        if key in {round(v, 6) for v in self.validation_distances}:
            return "validation"
        if key in {round(v, 6) for v in self.test_distances}:
            return "test"
        raise KeyError(f"distance {distance_mm} is not part of the manifest")

    def to_dict(self) -> dict:
        return {
            "calib_distances": list(self.calib_distances),
            "validation_distances": list(self.validation_distances),
            "test_distances": list(self.test_distances),
            "counts": {
                "calib": len(self.calib_distances),
                "validation": len(self.validation_distances),
                "test": len(self.test_distances),
            },
            "rule": "whole distances; no frame crosses splits",
        }


def make_distance_splits(distances: np.ndarray | tuple[float, ...],
                         validation: tuple[float, ...],
                         test: tuple[float, ...]) -> SplitManifest:
    grid = tuple(round(float(value), 6) for value in distances)
    validation = tuple(round(float(value), 6) for value in validation)
    test = tuple(round(float(value), 6) for value in test)
    missing = [value for value in validation + test if value not in grid]
    if missing:
        raise ValueError(f"split distances outside the grid: {missing}")
    calib = tuple(value for value in grid if value not in validation and value not in test)
    manifest = SplitManifest(calib, validation, test)
    if min(calib) > min(grid) or max(calib) < max(grid):
        raise ValueError("calibration split must cover both ends of the distance range")
    return manifest
