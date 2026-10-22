"""Unit-contract tests: every conversion is explicit and reversible."""

from __future__ import annotations

import math

import pytest

from optisys import units


def test_micrometre_to_millimetre_exact_factor() -> None:
    assert units.MM_PER_UM == 1.0e-3
    assert units.um_to_mm(3.45) == pytest.approx(0.00345, rel=0, abs=1e-18)


def test_degree_radian_round_trip() -> None:
    assert units.deg_to_rad(180.0) == pytest.approx(math.pi, rel=1e-15)
    assert units.deg_to_rad(3.0) == pytest.approx(0.05235987755982989, rel=1e-15)
    assert units.rad_to_deg(units.deg_to_rad(37.5)) == pytest.approx(37.5, rel=1e-14)


def test_time_round_trip() -> None:
    assert units.ms_to_s(2.0) == pytest.approx(2e-3, rel=0, abs=0)
    assert units.s_to_ms(units.ms_to_s(17.0)) == pytest.approx(17.0, rel=1e-15)


def test_nanometre_to_millimetre() -> None:
    assert units.nm_to_mm(650.0) == pytest.approx(6.5e-4, rel=1e-15)


def test_to_internal_converts_declared_units() -> None:
    assert units.to_internal("pixel_size", 3.45, "um") == pytest.approx(0.00345)
    assert units.to_internal("angle", 3.0, "deg") == pytest.approx(units.deg_to_rad(3.0))
    assert units.to_internal("angle", 0.5, "rad") == 0.5
    assert units.to_internal("distance", 20.0, "mm") == 20.0


def test_to_internal_rejects_unsupported_unit() -> None:
    with pytest.raises(ValueError, match="not supported"):
        units.to_internal("distance", 20.0, "inch")
    with pytest.raises(ValueError, match="unknown quantity"):
        units.to_internal("mass", 1.0, "kg")
