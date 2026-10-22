"""Shared pytest fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from optisys.config import ResolvedConfig, load_config
from optisys.geometry.coplanar import CoplanarGeometry

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "configs" / "triangulation_v0.yaml"


@pytest.fixture(scope="session")
def config() -> ResolvedConfig:
    return load_config(CONFIG_PATH)


@pytest.fixture(scope="session")
def geometry(config: ResolvedConfig) -> CoplanarGeometry:
    return CoplanarGeometry(config.geometry)
