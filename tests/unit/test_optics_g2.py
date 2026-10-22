"""G2 optics tests: paraxial reference, real trace, footprint bookkeeping."""

from __future__ import annotations

import numpy as np
import pytest

from optisys.errors import Status
from optisys.optics.optiland_adapter import (
    OptilandTracer,
    SingletModel,
    backend_info,
    trace_summary,
)
from optisys.optics.psf_or_footprint import (
    KERNEL_KIND_COMBINED,
    KernelSpec,
    airy_encircled_fraction,
    airy_radius_px,
    build_kernel,
    place_kernel,
)
from optisys.optics.reference_thin_lens import ThinLensReference

FOCAL = 8.0
APERTURE = 1.2
THICKNESS = 3.0
INDEX = 1.5168


def _model(**overrides) -> SingletModel:
    params = dict(
        focal_length_mm=FOCAL,
        aperture_mm=APERTURE,
        thickness_mm=THICKNESS,
        material="N-BK7",
        index=INDEX,
        wavelength_nm=650.0,
        rear_aperture_clearance_mm=0.35,
        focus_distance_mm=200.0,
        pupil_side=13,
    )
    params.update(overrides)
    return SingletModel(**params)


# ---------------------------------------------------------------------------
# paraxial reference
# ---------------------------------------------------------------------------
def test_thin_lens_reference_recovers_requested_focal_length() -> None:
    ref = ThinLensReference(FOCAL, APERTURE, THICKNESS, INDEX)
    assert ref.efl_mm == pytest.approx(FOCAL, rel=1e-9)
    assert 0 < ref.bfl_mm < FOCAL
    assert ref.rear_principal_offset_mm < 0


def test_sensor_distance_focuses_the_requested_distance() -> None:
    ref = ThinLensReference(FOCAL, APERTURE, THICKNESS, INDEX)
    d = ref.sensor_distance_mm(200.0)
    # A ray from the axial object point must cross the axis at the sensor.
    m = ref.system_matrix
    a, b, c, dd = m[0, 0], m[0, 1], m[1, 0], m[1, 1]
    z = 200.0
    y = (a * z + b) + d * (c * z + dd)
    assert abs(y) < 1e-9


def test_chief_image_height_matches_closed_form_magnification() -> None:
    ref = ThinLensReference(FOCAL, APERTURE, THICKNESS, INDEX)
    d = ref.sensor_distance_mm(200.0)
    magnification = ref.magnification(200.0, d)
    height = ref.chief_image_mm(200.0, 2.0, d)
    assert height == pytest.approx(magnification * 2.0, rel=1e-12)


def test_chief_image_height_depends_on_object_distance() -> None:
    ref = ThinLensReference(FOCAL, APERTURE, THICKNESS, INDEX)
    d = ref.sensor_distance_mm(200.0)
    near = abs(ref.chief_image_mm(150.0, 2.0, d))
    far = abs(ref.chief_image_mm(250.0, 2.0, d))
    assert near > far


# ---------------------------------------------------------------------------
# real trace
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def tracer() -> OptilandTracer:
    return OptilandTracer(_model())


def test_backend_is_really_optiland() -> None:
    info = backend_info()
    assert info["importable"] is True
    assert info["version"] == "0.6.3"


def test_trace_matches_paraxial_reference_at_small_field(tracer) -> None:
    ref = tracer.model.reference
    d = tracer.model.sensor_distance_mm
    for distance in (150.0, 200.0, 250.0):
        footprint = tracer.trace(distance, 0.5)
        paraxial = ref.chief_image_mm(distance, 0.5, d)
        assert abs(footprint.chief_y_mm - paraxial) / abs(paraxial) < 0.01


def test_chief_ray_lands_on_the_pixel_axis(tracer) -> None:
    footprint = tracer.trace(200.0, 20.0)
    summary = trace_summary(footprint, 0.00345, 640.0, 512.0)
    assert summary["centroid_v_px"] == pytest.approx(512.0, abs=1e-6)
    assert summary["centroid_u_px"] > 640.0


def test_spot_centre_moves_towards_the_principal_point_as_z_grows(tracer) -> None:
    centres = [tracer.trace(z, 20.0).centroid_mm[1] for z in (100.0, 200.0, 300.0)]
    assert all(abs(b) < abs(a) for a, b in zip(centres, centres[1:]))


def test_all_rays_blocked_returns_named_status(tracer) -> None:
    footprint = tracer.trace(200.0, 200.0)
    assert footprint.status is Status.ALL_RAYS_BLOCKED
    assert footprint.n_valid == 0


def test_blocked_rays_stay_in_the_denominator(tracer) -> None:
    footprint = tracer.trace(100.0, 20.0)
    assert footprint.n_launched > 1
    assert footprint.ray_success_fraction == pytest.approx(
        footprint.n_valid / footprint.n_launched
    )


def test_aperture_drives_spot_size_monotonically() -> None:
    radii = []
    for aperture in (0.3, 0.6, 1.2):
        tracer = OptilandTracer(_model(aperture_mm=aperture))
        sxx, syy, _ = tracer.trace(200.0, 20.0).second_moments_mm
        radii.append(np.sqrt(sxx + syy))
    assert radii[0] < radii[1] < radii[2]
    assert radii[0] < 1e-3


def test_sensor_offset_produces_defocus() -> None:
    in_focus = OptilandTracer(_model(sensor_offset_mm=0.0)).trace(200.0, 20.0)
    defocused = OptilandTracer(_model(sensor_offset_mm=0.4)).trace(200.0, 20.0)
    s0 = np.sqrt(sum(in_focus.second_moments_mm[:2]))
    s1 = np.sqrt(sum(defocused.second_moments_mm[:2]))
    assert s1 > 3.0 * s0


def test_trace_is_deterministic() -> None:
    model = _model()
    a = OptilandTracer(model).trace(180.0, 20.0)
    b = OptilandTracer(model).trace(180.0, 20.0)
    assert np.array_equal(a.y_mm, b.y_mm)
    assert np.array_equal(a.intensity, b.intensity)


# ---------------------------------------------------------------------------
# kernel
# ---------------------------------------------------------------------------
def test_airy_radius_scales_with_f_number() -> None:
    assert airy_radius_px(650.0, 6.0, 0.00345) == pytest.approx(
        1.22 * 650e-6 * 6.0 / 0.00345, rel=1e-12
    )


def test_airy_encircled_fraction_is_monotone_in_window_size() -> None:
    small = airy_encircled_fraction(1.4, 3)
    large = airy_encircled_fraction(1.4, 40)
    assert 0.0 < small < large <= 1.0


def test_kernel_is_non_negative_and_conserves_ray_energy() -> None:
    tracer = OptilandTracer(_model())
    footprint = tracer.trace(200.0, 20.0)
    valid = footprint.valid
    u = 640.0 - footprint.y_mm[valid] / 0.00345
    v = 512.0 + footprint.x_mm[valid] / 0.00345
    w = footprint.intensity[valid] / footprint.n_launched
    kernel = build_kernel(u, v, w, (u.mean(), v.mean()), airy_radius=1.39,
                          spec=KernelSpec(), kind=KERNEL_KIND_COMBINED)
    assert kernel.status is Status.OK
    assert np.all(kernel.data >= 0)
    # The FFT crop of the Airy tail loses a small, bounded part of the energy.
    assert kernel.total <= float(w.sum()) + 1e-12
    assert kernel.total >= 0.99 * float(w.sum())


def test_kernel_oversize_is_refused() -> None:
    u = np.array([0.0, 200.0])
    v = np.array([0.0, 0.0])
    w = np.array([0.5, 0.5])
    kernel = build_kernel(u, v, w, (0.0, 0.0), airy_radius=1.0,
                          spec=KernelSpec(max_half_px=8))
    assert kernel.status is Status.INSUFFICIENT_PSF_SUPPORT


def test_place_kernel_never_renormalises() -> None:
    class _K:
        data = np.full((5, 5), 0.04)
        half_px = 2

    canvas, placed = place_kernel(_K(), 4, 4, (0.0, 0.0))
    assert placed < 1.0
    assert canvas.sum() == pytest.approx(placed)
