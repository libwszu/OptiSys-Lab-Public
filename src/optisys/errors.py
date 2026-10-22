"""Explicit status codes shared by every OptiSys-Lab module.

A numeric result is only meaningful together with its status.  Callers must
never treat ``nan``/``inf`` or an out-of-range value as a valid measurement.
"""

from __future__ import annotations

from enum import Enum


class Status(str, Enum):
    """Machine-readable outcome of a geometric or numerical operation."""

    OK = "OK"
    NONFINITE_INPUT = "NONFINITE_INPUT"
    INVALID_DEPTH = "INVALID_DEPTH"
    BASELINE_DEGENERATE = "BASELINE_DEGENERATE"
    SINGULAR_GEOMETRY = "SINGULAR_GEOMETRY"
    OUT_OF_RANGE = "OUT_OF_RANGE"
    OUT_OF_SENSOR = "OUT_OF_SENSOR"
    INVALID_CONFIG = "INVALID_CONFIG"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"
    # --- G1 imaging / estimation statuses (appended to keep legacy codes stable)
    NO_SIGNAL = "NO_SIGNAL"
    LOW_SNR = "LOW_SNR"
    SATURATED = "SATURATED"
    PARTIAL_SPOT = "PARTIAL_SPOT"
    ROI_TRUNCATED = "ROI_TRUNCATED"
    INVALID_ROI = "INVALID_ROI"
    NUMERICAL_FAILURE = "NUMERICAL_FAILURE"
    MODEL_MISMATCH = "MODEL_MISMATCH"
    FIT_NOT_CONVERGED = "FIT_NOT_CONVERGED"
    NOT_ESTIMABLE = "NOT_ESTIMABLE"
    # --- G2 optical-backend statuses (append-only; never renumber existing codes)
    OPTICS_TRACE_FAILED = "OPTICS_TRACE_FAILED"
    ALL_RAYS_BLOCKED = "ALL_RAYS_BLOCKED"
    OUT_OF_FOV = "OUT_OF_FOV"
    INSUFFICIENT_PSF_SUPPORT = "INSUFFICIENT_PSF_SUPPORT"
    NONPHYSICAL_ENERGY = "NONPHYSICAL_ENERGY"
    BACKEND_UNAVAILABLE = "BACKEND_UNAVAILABLE"
    OUT_OF_SENSOR_PARTIAL = "OUT_OF_SENSOR_PARTIAL"


#: Stable integer code used in vectorised paths and CSV output.
STATUS_CODES: dict[Status, int] = {status: index for index, status in enumerate(Status)}

#: Reverse lookup for decoding vectorised status arrays.
CODE_TO_STATUS: dict[int, Status] = {code: status for status, code in STATUS_CODES.items()}

#: Statuses that invalidate a measurement.
FAILURE_STATUSES: frozenset[Status] = frozenset(
    status for status in Status if status is not Status.OK
)


def is_failure(status: Status | str) -> bool:
    """Return True when *status* does not represent a valid result."""

    value = Status(status)
    return value is not Status.OK
