"""Explicit unit handling.

Internal computation uses millimetres, radians, pixels and seconds.  Every
conversion is an explicit named function; no module relies on implicit
"magic" constants such as ``0.00345`` inline.
"""

from __future__ import annotations

import math

MM_PER_UM: float = 1.0e-3
"""Millimetres per micrometre."""

DEG_PER_RAD: float = 180.0 / math.pi
RAD_PER_DEG: float = math.pi / 180.0
"""(pi/180) radians per degree."""

S_PER_MS: float = 1.0e-3

#: Supported unit strings per physical quantity for schema version 1.0.
SUPPORTED_UNITS: dict[str, tuple[str, ...]] = {
    "distance": ("mm",),
    "angle": ("deg", "rad"),
    "pixel_size": ("um", "mm"),
    "time": ("ms", "s"),
    "wavelength": ("nm",),
}

#: Canonical internal unit per quantity.
CANONICAL_UNITS: dict[str, str] = {
    "distance": "mm",
    "angle": "rad",
    "pixel_size": "mm",
    "time": "s",
    "wavelength": "nm",
}


def um_to_mm(value_um: float) -> float:
    """Convert micrometres to millimetres."""

    return float(value_um) * MM_PER_UM


def mm_to_um(value_mm: float) -> float:
    """Convert millimetres to micrometres."""

    return float(value_mm) / MM_PER_UM


def deg_to_rad(value_deg: float) -> float:
    """Convert degrees to radians."""

    return float(value_deg) * RAD_PER_DEG


def rad_to_deg(value_rad: float) -> float:
    """Convert radians to degrees."""

    return float(value_rad) * DEG_PER_RAD


def ms_to_s(value_ms: float) -> float:
    """Convert milliseconds to seconds."""

    return float(value_ms) * S_PER_MS


def s_to_ms(value_s: float) -> float:
    """Convert seconds to milliseconds."""

    return float(value_s) / S_PER_MS


def nm_to_mm(value_nm: float) -> float:
    """Convert nanometres to millimetres (1 nm = 1e-6 mm)."""

    return float(value_nm) * 1.0e-6


def to_internal(quantity: str, value: float, unit: str) -> float:
    """Convert *value* given in *unit* to the canonical internal unit.

    Raises
    ------
    ValueError
        If the quantity is unknown or the unit is not supported for it.
    """

    if quantity not in SUPPORTED_UNITS:
        raise ValueError(f"unknown quantity {quantity!r}")
    if unit not in SUPPORTED_UNITS[quantity]:
        allowed = ", ".join(SUPPORTED_UNITS[quantity])
        raise ValueError(f"unit {unit!r} not supported for {quantity}; allowed: {allowed}")

    value = float(value)
    if quantity == "distance":
        return value  # only mm is supported
    if quantity == "angle":
        return deg_to_rad(value) if unit == "deg" else value
    if quantity == "pixel_size":
        return um_to_mm(value) if unit == "um" else value
    if quantity == "time":
        return ms_to_s(value) if unit == "ms" else value
    if quantity == "wavelength":
        return value
    raise ValueError(f"unhandled quantity {quantity!r}")
