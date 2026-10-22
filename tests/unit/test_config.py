"""Configuration schema tests: strict, unit-aware, and fail-closed."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path

import pytest
import yaml

from optisys.config import ConfigError, config_from_dict, load_config

CONFIG_PATH = Path(__file__).resolve().parents[2] / "configs" / "triangulation_v0.yaml"


@pytest.fixture()
def raw() -> dict:
    return copy.deepcopy(yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")))


def test_loads_reference_configuration(config) -> None:
    assert config.case_id == "triangulation_v0"
    assert config.model_level == "L0"
    assert config.fx_px == pytest.approx(8.0 / 0.00345, rel=1e-15)
    assert config.theta_rad == pytest.approx(0.0)
    assert (config.z_min_mm, config.z_max_mm) == (100.0, 300.0)
    assert config.run.seed == 20261019
    assert config.geometry.range_epsilon_mm == pytest.approx(1e-6)


def test_config_hash_is_of_the_actual_file(config) -> None:
    payload = CONFIG_PATH.read_bytes()
    assert config.sha256 == hashlib.sha256(payload).hexdigest()


def test_unknown_key_is_rejected(raw) -> None:
    raw["camera"]["focal_lenght_mm"] = 50.0  # deliberate typo
    with pytest.raises(ConfigError, match="unknown key"):
        config_from_dict(raw)


def test_missing_section_is_rejected(raw) -> None:
    del raw["geometry"]
    with pytest.raises(ConfigError, match="missing required key"):
        config_from_dict(raw)


def test_unsupported_schema_version_is_rejected(raw) -> None:
    raw["schema_version"] = "2.0"
    with pytest.raises(ConfigError, match="schema_version"):
        config_from_dict(raw)


def test_unsupported_unit_is_rejected(raw) -> None:
    raw["units"]["pixel_size"] = "inch"
    with pytest.raises(ConfigError, match="units.pixel_size"):
        config_from_dict(raw)


def test_zero_baseline_is_rejected(raw) -> None:
    raw["geometry"]["baseline_mm"] = 0.0
    with pytest.raises(ConfigError, match="baseline_mm"):
        config_from_dict(raw)


def test_baseline_below_declared_minimum_is_rejected(raw) -> None:
    raw["geometry"]["baseline_mm"] = 0.4
    with pytest.raises(ConfigError, match="below the declared physical"):
        config_from_dict(raw)


def test_principal_point_must_be_inside_sensor(raw) -> None:
    raw["camera"]["principal_point_px"] = [2000.0, 512.0]
    with pytest.raises(ConfigError, match="principal_point"):
        config_from_dict(raw)


def test_reversed_distance_range_is_rejected(raw) -> None:
    raw["geometry"]["distance_mm"] = [300.0, 100.0]
    with pytest.raises(ConfigError, match="min < max"):
        config_from_dict(raw)


def test_angle_beyond_domain_is_rejected(raw) -> None:
    raw["source"]["theta_deg"] = 89.0
    with pytest.raises(ConfigError, match="theta_deg"):
        config_from_dict(raw)


def test_non_boolean_switch_is_rejected(raw) -> None:
    raw["geometry"]["working_range_enforced"] = "yes"
    with pytest.raises(ConfigError, match="must be a boolean"):
        config_from_dict(raw)


def test_seed_must_fit_32_bits(raw) -> None:
    raw["run"]["seed"] = 2**32
    with pytest.raises(ConfigError, match="32 bits"):
        config_from_dict(raw)


def test_degrees_are_converted_and_fx_uses_consistent_units(raw) -> None:
    raw["source"]["theta_deg"] = 3.0
    raw["camera"]["pixel_size_um"] = 5.0
    resolved = config_from_dict(raw)
    assert resolved.theta_rad == pytest.approx(0.05235987755982989)
    assert resolved.fx_px == pytest.approx(8.0 / 0.005)


def test_missing_file_raises_config_error(tmp_path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_config(tmp_path / "absent.yaml")


def test_angle_unit_must_match_field_suffix(raw) -> None:
    """Schema 1.0 uses theta_deg; declaring rad is ambiguous and must be rejected."""

    raw["units"]["angle"] = "rad"
    raw["source"]["theta_deg"] = 0.05
    with pytest.raises(ConfigError, match="suffix determines unit"):
        config_from_dict(raw)


def test_pixel_unit_must_match_field_suffix(raw) -> None:
    raw["units"]["pixel_size"] = "mm"
    raw["camera"]["pixel_size_um"] = 0.00345
    with pytest.raises(ConfigError, match="suffix determines unit"):
        config_from_dict(raw)


def test_angle_unit_must_match_field_suffix(raw) -> None:
    """Schema 1.0 uses theta_deg; declaring rad is ambiguous and must be rejected."""

    raw["units"]["angle"] = "rad"
    raw["source"]["theta_deg"] = 0.05
    with pytest.raises(ConfigError, match="suffix determines unit"):
        config_from_dict(raw)


def test_pixel_unit_must_match_field_suffix(raw) -> None:
    raw["units"]["pixel_size"] = "mm"
    raw["camera"]["pixel_size_um"] = 0.00345
    with pytest.raises(ConfigError, match="suffix determines unit"):
        config_from_dict(raw)
