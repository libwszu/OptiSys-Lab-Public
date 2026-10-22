"""S6 tolerance sampling and assembly-cluster bootstrap input controls."""

import numpy as np
import pytest

from optisys.tolerance.s6_assembly import (
    PARAMETER_ORDER,
    perturbation_vector,
    paired_cluster_bootstrap,
    poses_from_perturbation,
    truncated_standard_normal_latents,
)


def test_truncated_normal_latents_are_seeded_and_bounded() -> None:
    a = truncated_standard_normal_latents(200, 8062101)
    b = truncated_standard_normal_latents(200, 8062101)
    assert a.shape == (200, 10)
    assert a == pytest.approx(b, abs=0.0)
    assert np.max(np.abs(a)) <= 3.0
    assert abs(float(np.mean(a))) < 0.08


def test_tolerance_levels_scale_one_shared_latent_draw() -> None:
    latent = truncated_standard_normal_latents(1, 8062101)[0]
    zero = perturbation_vector(latent, "zero")
    tight = perturbation_vector(latent, "tight_0p5x")
    nominal = perturbation_vector(latent, "nominal_1x")
    stress = perturbation_vector(latent, "stress_2x")
    assert set(nominal) == set(PARAMETER_ORDER)
    assert all(value == 0.0 for value in zero.values())
    for key in PARAMETER_ORDER:
        assert tight[key] == pytest.approx(0.5 * nominal[key])
        assert stress[key] == pytest.approx(2.0 * nominal[key])
    poses = poses_from_perturbation(nominal)
    assert poses[0].dx_mm == pytest.approx(nominal["L1_dx_mm"])
    assert poses[1].tilt_y_deg == pytest.approx(nominal["L2_tilt_y_deg"])


def test_bootstrap_resamples_paired_assemblies_and_is_deterministic() -> None:
    ids = [f"nominal_{i:03d}" for i in range(4)]
    base = [0.50, 0.60, 0.70, 0.80]
    cand = [0.60, 0.70, 0.80, 0.90]
    a = paired_cluster_bootstrap(ids, base, cand, n_replicates=2000, seed=8064001)
    b = paired_cluster_bootstrap(ids, base, cand, n_replicates=2000, seed=8064001)
    assert len(a) == 2000
    assert a == b
    assert all(row["resampling_unit"] == "assembly_id" for row in a)
    assert all(row["n_assemblies_resampled"] == 4 for row in a)
    assert all(row["mean_delta_capture"] == pytest.approx(0.1) for row in a)


def test_bootstrap_rejects_duplicates_nan_and_wrong_denominator() -> None:
    with pytest.raises(ValueError, match="unique"):
        paired_cluster_bootstrap(["a", "a"], [0.5, 0.6], [0.7, 0.8], n_replicates=2)
    with pytest.raises(ValueError, match="finite"):
        paired_cluster_bootstrap(["a"], [float("nan")], [0.8], n_replicates=2)
    with pytest.raises(ValueError, match=r"\[0,1\]"):
        paired_cluster_bootstrap(["a"], [1.2], [0.8], n_replicates=2)
    with pytest.raises(ValueError, match="unknown"):
        perturbation_vector(np.zeros(10), "yield")
