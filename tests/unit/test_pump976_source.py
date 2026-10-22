"""G4 source sampling tests: probability measure, units, weights, and RNG."""

from __future__ import annotations

import numpy as np
import pytest

from optisys.sources.multimode_fiber import RayBundle, sample_multimode_fiber


def test_same_seed_reproduces_bundle_and_different_seed_is_independent() -> None:
    a = sample_multimode_fiber(4096, 0.105, 0.22, seed=17)
    b = sample_multimode_fiber(4096, 0.105, 0.22, seed=17)
    c = sample_multimode_fiber(4096, 0.105, 0.22, seed=18)
    np.testing.assert_array_equal(a.origin_mm, b.origin_mm)
    np.testing.assert_array_equal(a.direction, b.direction)
    assert not np.array_equal(a.direction, c.direction)
    assert a.total_weight == pytest.approx(1.0, abs=1e-12)


@pytest.mark.parametrize("distribution", ["uniform_solid_angle", "edge_biased_sin_theta"])
def test_source_distribution_cdf_uses_declared_probability_measure(distribution: str) -> None:
    bundle = sample_multimode_fiber(8192, 0.105, 0.22, seed=976051,
                                    angular_distribution=distribution)
    r = np.hypot(bundle.origin_mm[:, 0], bundle.origin_mm[:, 1])
    radial_u = (r / 0.0525) ** 2
    theta = np.arccos(bundle.direction[:, 2])
    theta_max = np.arcsin(0.22)
    if distribution == "uniform_solid_angle":
        angular_u = (1 - np.cos(theta)) / (1 - np.cos(theta_max))
    else:
        angular_u = (np.sin(theta) / np.sin(theta_max)) ** 3
    limit = 1.63 / np.sqrt(bundle.n_rays)
    assert _ks_d(radial_u) <= limit
    assert _ks_d(angular_u) <= limit


def test_direction_na_limit_and_weights_are_normalized() -> None:
    bundle = sample_multimode_fiber(10, 0.105, 0.22, output_index=1.0, seed=9)
    np.testing.assert_allclose(np.linalg.norm(bundle.direction, axis=1), 1.0, atol=1e-12)
    assert np.max(np.arccos(bundle.direction[:, 2])) <= np.arcsin(0.22) + 1e-12
    assert bundle.metadata["theta_max_deg"] == pytest.approx(12.7099, abs=1e-3)
    assert bundle.total_weight == pytest.approx(1.0, abs=1e-12)
    assert "UNKNOWN" in bundle.metadata["weight_semantics"]


@pytest.mark.parametrize("kwargs", [
    {"n_rays": 0, "core_diameter_mm": 0.105, "numerical_aperture": 0.22},
    {"n_rays": 10, "core_diameter_mm": -0.1, "numerical_aperture": 0.22},
    {"n_rays": 10, "core_diameter_mm": 0.105, "numerical_aperture": 1.1},
    {"n_rays": 10, "core_diameter_mm": 0.105, "numerical_aperture": 0.22, "output_index": 0},
])
def test_invalid_source_config_is_rejected(kwargs) -> None:
    with pytest.raises(ValueError):
        sample_multimode_fiber(**kwargs)


def test_ray_bundle_rejects_negative_weights_and_nonunit_directions() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        RayBundle(np.array([0]), np.zeros((1, 3)), np.array([[0, 0, 1.0]]),
                  np.array([-1.0]), 1, "bad", {})
    with pytest.raises(ValueError, match="normalized"):
        RayBundle(np.array([0]), np.zeros((1, 3)), np.array([[0, 0, 2.0]]),
                  np.array([1.0]), 1, "bad", {})


def _ks_d(sample: np.ndarray) -> float:
    s = np.sort(sample)
    n = len(s)
    return float(max(np.max(np.arange(1, n + 1) / n - s),
                     np.max(s - np.arange(0, n) / n)))
