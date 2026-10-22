"""Independent G2 reproduction check.

Runs a small, self-contained slice of the G2 chain and prints a machine-readable
verdict.  It is intentionally cheap (no Monte Carlo): it re-traces the lens,
re-checks the paraxial reference, the energy contract, one full scene through
the sensor and the estimator, and the calibration round trip.

Exit codes
----------
0  REPRO_STATUS: PASS
1  REPRO_STATUS: FAIL
2  DEPENDENCY_UNAVAILABLE (third-party backend missing)
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from optisys.calibration.assembly_strategies import fit_calibration  # noqa: E402
from optisys.config_g1 import SensorSpec  # noqa: E402
from optisys.config_g2 import load_config_g2  # noqa: E402
from optisys.errors import Status  # noqa: E402
from optisys.estimators import build_estimators  # noqa: E402
from optisys.imaging.roi import detect_roi  # noqa: E402
from optisys.imaging.sensor_g2 import render_frame_g2  # noqa: E402
from optisys.optics.optiland_adapter import (  # noqa: E402
    OptilandTracer,
    SingletModel,
    backend_info,
    trace_summary,
)
from optisys.optics.optical_image_contract import (  # noqa: E402
    CameraGeometry,
    L1OpticalModel,
)
from optisys.optics.psf_or_footprint import KernelSpec  # noqa: E402
from optisys.optics.reference_thin_lens import ThinLensReference  # noqa: E402


def main() -> int:
    report: list[str] = []
    failures: list[str] = []

    def record(name: str, value: str, ok: bool) -> None:
        report.append(f"{name:<28}: {value}")
        if not ok:
            failures.append(name)

    info = backend_info()
    if not info["importable"]:
        print(f"DEPENDENCY_UNAVAILABLE: optiland not importable ({info.get('error')})")
        return 2

    config = load_config_g2(ROOT / "configs" / "triangulation_g2_l1.yaml")
    record("config", config.case_id, True)
    record("optiland version", str(info["version"]), info["version"] == "0.6.3")

    lens = SingletModel(
        focal_length_mm=config.focal_length_mm,
        aperture_mm=config.optics.aperture_diameter_mm,
        thickness_mm=config.optics.element_thickness_mm,
        material=config.optics.material,
        index=config.optics.design_index,
        wavelength_nm=config.wavelength_nm,
        rear_aperture_clearance_mm=config.optics.rear_aperture_clearance_mm,
        focus_distance_mm=config.optics.focus_distance_mm,
        pupil_side=config.optics.pupil_side,
    )
    reference = ThinLensReference(
        focal_length_mm=config.focal_length_mm,
        aperture_mm=config.optics.aperture_diameter_mm,
        thickness_mm=config.optics.element_thickness_mm,
        index=config.optics.design_index,
    )
    record("efl from matrix [mm]", f"{reference.efl_mm:.9f}",
           abs(reference.efl_mm - config.focal_length_mm) < 1e-9)

    tracer = OptilandTracer(lens)
    worst_paraxial = 0.0
    for distance in (150.0, 200.0, 250.0):
        footprint = tracer.trace(distance, 0.5)
        paraxial = reference.chief_image_mm(distance, 0.5, lens.sensor_distance_mm)
        worst_paraxial = max(
            worst_paraxial, abs(footprint.chief_y_mm - paraxial) / abs(paraxial)
        )
    record("paraxial agreement", f"{worst_paraxial:.3e}", worst_paraxial < 0.01)

    camera = CameraGeometry(config.width_px, config.height_px, config.pixel_size_mm,
                            config.cx_px, config.cy_px)
    model = L1OpticalModel(
        camera, lens,
        kernel_spec=KernelSpec(subpixel=config.optics.psf.subpixel,
                               max_half_px=config.optics.psf.max_half_px,
                               airy_radius_margin=config.optics.psf.airy_radius_margin),
        signal_mode=config.imaging.signal_mode,
        reference_electrons=config.imaging.reference_electrons,
        reference_distance_mm=config.imaging.reference_distance_mm,
        reference_aperture_mm=config.imaging.reference_aperture_mm,
    )
    image = model.image(200.0, config.baseline_mm,
                        total_electrons=config.imaging.reference_electrons)
    transmitted = float(image.transmitted_energy_fraction or 0.0)
    placed = float(image.expected_signal_e.sum() / config.imaging.reference_electrons)
    energy_error = abs(placed - transmitted * image.capture_fraction)
    record("energy relative error", f"{energy_error:.3e}", energy_error <= 0.005)
    record("kernel kind", str(image.kernel_kind), image.kernel_kind is not None)

    sensor = SensorSpec(
        read_noise_e=3.0, dark_rate_e_per_s=config.sensor.dark_rate_e_per_s,
        exposure_ms=config.sensor.exposure_ms, full_well_e=config.sensor.full_well_e,
        bit_depth=config.sensor.bit_depth, e_per_adu=config.sensor.e_per_adu,
        black_level_adu=config.sensor.black_level_adu, adc_max_adu=config.sensor.adc_max_adu,
    )
    frame = render_frame_g2(image.expected_signal_e, 100.0, sensor, 20261019)
    roi = detect_roi(frame.image_adu, sensor)
    record("roi status", roi.status.value, roi.status is Status.OK)

    estimators = {e.name: e for e in build_estimators()}
    estimate = estimators["gaussian_2d"].estimate(frame.image_adu, roi.roi, sensor)
    record("2-D estimator", f"{estimate.status.value}", estimate.status is Status.OK)
    if estimate.u_hat_px is not None:
        # This is a *physical* bias, not a bug: the L1 spot is coma-dominated,
        # so any symmetric (Gaussian) fit sits off the energy centroid.  The
        # bound is therefore generous and the value is reported, not hidden.
        error_px = abs(estimate.u_hat_px - image.spot_center_px[0])
        record("2-D vs kernel centre [px]", f"{error_px:.4f} (physical coma bias)",
               error_px < 1.0)

    z = np.array([100.0, 150.0, 200.0, 250.0, 300.0])
    u = np.array([reference.chief_image_mm(float(value), config.baseline_mm,
                                           lens.sensor_distance_mm) for value in z])
    u = config.cx_px - u / config.pixel_size_mm
    fit = fit_calibration(z, u, model="M1", estimator="gaussian_2d")
    # Probe inside the fitted interval. Endpoint round-off may cross the strict
    # calibrated-range guard; out-of-range handling is covered by unit tests.
    probe_z = np.array([110.0, 150.0, 200.0, 250.0, 290.0])
    probe_u = np.array([reference.chief_image_mm(float(value), config.baseline_mm,
                                                 lens.sensor_distance_mm) for value in probe_z])
    probe_u = config.cx_px - probe_u / config.pixel_size_mm
    recovered = [fit.inverse(float(value)) for value in probe_u]
    inverse_ok = all(depth is not None and status is Status.OK
                     for depth, status, _ in recovered)
    worst_cal = (max(abs(depth - float(zz))
                     for (depth, _, _), zz in zip(recovered, probe_z))
                 if inverse_ok else float("inf"))
    record("calibration inverse status", ", ".join(status.value for _, status, _ in recovered),
           inverse_ok)
    record("calibration round trip [mm]", f"{worst_cal:.3e}", worst_cal < 1e-6)

    print("\n".join(report))
    if failures:
        print("FAILED_CHECKS: " + ", ".join(failures))
        print("REPRO_STATUS: FAIL")
        return 1
    print("REPRO_STATUS: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
