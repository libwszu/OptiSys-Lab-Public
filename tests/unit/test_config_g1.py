"""Schema 2.0 configuration tests: unit rule, splits, dataset size."""

from __future__ import annotations

import copy
from pathlib import Path

import pytest
import yaml

from optisys.config import ConfigError
from optisys.config_g1 import load_config_g1

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs" / "triangulation_g1_l0.yaml"


@pytest.fixture()
def raw() -> dict:
    return copy.deepcopy(yaml.safe_load(CONFIG.read_text(encoding="utf-8")))


def _write(tmp_path: Path, data: dict) -> Path:
    path = tmp_path / "cfg.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    return path


def test_reference_config_loads() -> None:
    config = load_config_g1(CONFIG)
    assert config.schema_version == "2.0"
    assert len(config.distances_mm) == 41
    assert config.dataset.repeats == 40
    assert len(config.dataset.conditions) == 3
    assert config.fx_px == pytest.approx(8.0 / 0.00345, rel=1e-15)
    assert config.sensor.dark_e_per_px == pytest.approx(0.002)


def test_theta_follows_declared_rad_unit(raw, tmp_path) -> None:
    raw["units"]["angle"] = "rad"
    raw["source"]["theta"] = 0.05
    config = load_config_g1(_write(tmp_path, raw))
    assert config.theta_rad == pytest.approx(0.05)
    assert config.theta_deg == pytest.approx(0.05 * 180 / 3.141592653589793)


def test_pixel_size_follows_declared_mm_unit(raw, tmp_path) -> None:
    raw["units"]["pixel_size"] = "mm"
    raw["camera"]["pixel_size"] = 0.00345
    config = load_config_g1(_write(tmp_path, raw))
    assert config.pixel_size_mm == pytest.approx(0.00345)
    assert config.fx_px == pytest.approx(8.0 / 0.00345, rel=1e-15)


def test_distance_unit_accepts_mm_only(raw, tmp_path) -> None:
    raw["units"]["distance"] = "um"
    with pytest.raises(ConfigError, match="units.distance"):
        load_config_g1(_write(tmp_path, raw))


def test_unknown_key_is_rejected(raw, tmp_path) -> None:
    raw["sensor"]["gain_e_per_adu"] = 3.0
    with pytest.raises(ConfigError, match="unknown key"):
        load_config_g1(_write(tmp_path, raw))


def test_duplicate_condition_names_are_rejected(raw, tmp_path) -> None:
    raw["dataset"]["conditions"][1]["name"] = raw["dataset"]["conditions"][0]["name"]
    with pytest.raises(ConfigError, match="unique"):
        load_config_g1(_write(tmp_path, raw))


def test_split_overlap_is_rejected(raw, tmp_path) -> None:
    raw["dataset"]["split"]["test_distances"] = raw["dataset"]["split"]["validation_distances"]
    with pytest.raises(ConfigError, match="overlap"):
        load_config_g1(_write(tmp_path, raw))


def test_split_outside_grid_is_rejected(raw, tmp_path) -> None:
    raw["dataset"]["split"]["test_distances"] = [110.0, 137.0]
    with pytest.raises(ConfigError, match="outside the distance grid"):
        load_config_g1(_write(tmp_path, raw))


def test_bit_depth_range_is_enforced(raw, tmp_path) -> None:
    raw["sensor"]["bit_depth"] = 4
    with pytest.raises(ConfigError, match="bit_depth"):
        load_config_g1(_write(tmp_path, raw))


def test_principal_point_must_be_inside(raw, tmp_path) -> None:
    raw["camera"]["principal_point_px"] = [2000.0, 512.0]
    with pytest.raises(ConfigError, match="principal point"):
        load_config_g1(_write(tmp_path, raw))


def test_schema_2_config_is_rejected_by_schema_1_loader() -> None:
    from optisys.config import load_config

    with pytest.raises(ConfigError, match="schema_version"):
        load_config(CONFIG)


def test_summary_reports_dataset_size() -> None:
    summary = load_config_g1(CONFIG).summary()
    assert summary["frames"] == 4920
    assert summary["distances_mm"] == 41
    assert summary["conditions"] == ["strong", "medium", "weak"]
