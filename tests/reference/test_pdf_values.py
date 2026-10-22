"""Cross-check against the numeric values printed in PDF section 4.2.

The PDF states, for f = 8 mm, p = 3.45 um, B = 20 mm:

* fx ~ 2318.84 pixel;
* u - cx ~ 463.77 / 231.88 / 154.59 pixel at Z = 100 / 200 / 300 mm;
* |dZ/du| ~ 0.8625 mm/pixel at Z = 200 mm and 1.9406 mm/pixel at Z = 300 mm;
* to reach 0.1 mm at Z = 300 mm the spot error must be below ~0.052 pixel.

If these fail, the implementation disagrees with the specification's own
worked example and the gate must stop.
"""

from __future__ import annotations

import numpy as np
import pytest

from optisys.geometry.coplanar import CoplanarGeometry


def test_fx_matches_pdf(config) -> None:
    assert config.fx_px == pytest.approx(2318.84, rel=2e-6)


@pytest.mark.parametrize("Z_mm,pdf_value", [(100.0, 463.77), (200.0, 231.88), (300.0, 154.59)])
def test_pixel_offsets_match_pdf(config, Z_mm: float, pdf_value: float) -> None:
    geom = CoplanarGeometry(config.geometry)
    computed = geom.forward(Z_mm).u_px - config.cx_px
    assert computed == pytest.approx(pdf_value, abs=5e-3)


@pytest.mark.parametrize("Z_mm,pdf_value", [(200.0, 0.8625), (300.0, 1.9406)])
def test_sensitivity_matches_pdf(config, Z_mm: float, pdf_value: float) -> None:
    geom = CoplanarGeometry(config.geometry)
    assert geom.abs_sensitivity(Z_mm) == pytest.approx(pdf_value, abs=1e-4)


def test_pdf_signed_derivative_has_a_sign_inconsistency(config) -> None:
    """Record SD-001: the printed derivative is positive, the signed one is not."""

    geom = CoplanarGeometry(config.geometry)
    assert geom.dZ_du(200.0) < 0.0
    assert geom.abs_sensitivity(200.0) > 0.0
    # The printed magnitude is correct; only the sign is missing.
    assert abs(geom.dZ_du(200.0)) == pytest.approx(0.8625, abs=1e-4)


def test_pdf_error_budget_number(config) -> None:
    """0.052 px at Z = 300 mm corresponds to ~0.1 mm with |dZ/du| = 1.9406."""

    geom = CoplanarGeometry(config.geometry)
    sigma_u = 0.1 / geom.abs_sensitivity(300.0)
    assert sigma_u == pytest.approx(0.0515, abs=1e-4)
    assert geom.abs_sensitivity(300.0) * 0.052 == pytest.approx(0.101, abs=2e-3)


def test_sensitivity_ratio_follows_z_squared(config) -> None:
    geom = CoplanarGeometry(config.geometry)
    ratio = geom.abs_sensitivity(300.0) / geom.abs_sensitivity(200.0)
    assert ratio == pytest.approx((300.0 / 200.0) ** 2, rel=1e-13)
