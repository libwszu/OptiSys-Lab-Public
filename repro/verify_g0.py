"""Minimal standalone reproduction of the G0 evidence.

This script deliberately uses only the public package API plus the configuration
snapshot shipped in this folder.  It recomputes:

* the analytic forward model,
* the independent vector/matrix chain,
* the maximum image-coordinate disagreement,
* the depth-inversion agreement,
* the analytic versus finite-difference derivative agreement,
* the sign of the signed derivative.

Exit code 0 means the declared tolerances were met; 1 otherwise.

Run from the project root:
    python repro/verify_g0.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import numpy as np  # noqa: E402

from optisys.config import load_config  # noqa: E402
from optisys.evaluation.chain import U_TOLERANCE_PX  # noqa: E402
from optisys.geometry.coplanar import CoplanarGeometry  # noqa: E402
from optisys.geometry.reference import ReferenceModel  # noqa: E402


def main() -> int:
    config = load_config(ROOT / "configs" / "triangulation_v0.yaml")
    geom = CoplanarGeometry(config.geometry)
    reference = ReferenceModel(config.geometry)

    z = np.linspace(config.z_min_mm, config.z_max_mm, config.run.distance_points)
    u_ref, _ = reference.forward(z)
    u_analytic = geom.forward_many(z).u_px
    max_u_error = float(np.max(np.abs(u_analytic - u_ref)))

    z_errors = []
    for value in z:
        inverse = geom.inverse(float(reference.forward_one(float(value)).u_px))
        z_errors.append(abs(inverse.Z_mm - float(value)) / float(value))
    max_z_error = max(z_errors)

    derivative_errors = []
    for value in z:
        analytic = geom.du_dZ(float(value))
        numeric = reference.d_u_d_Z(float(value))
        derivative_errors.append(abs(analytic - numeric) / abs(analytic))
    max_derivative_error = max(derivative_errors)

    signed = geom.dZ_du(200.0)
    magnitude = geom.abs_sensitivity(200.0)

    print(f"config              : {config.path}")
    print(f"fx [pixel]          : {config.fx_px:.9f}")
    print(f"samples             : {z.size}")
    print(f"max |u_a - u_ref|   : {max_u_error:.3e} px (gate {U_TOLERANCE_PX:g})")
    print(f"max rel Z error     : {max_z_error:.3e}")
    print(f"max rel d(du/dZ)    : {max_derivative_error:.3e}")
    print(f"dZ/du @200 mm       : {signed:+.6f} mm/px (magnitude {magnitude:.6f})")

    ok = (
        max_u_error <= U_TOLERANCE_PX
        and max_z_error <= 1e-9
        and max_derivative_error <= 1e-5
        and signed < 0.0
    )
    print("REPRO_STATUS        :", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
