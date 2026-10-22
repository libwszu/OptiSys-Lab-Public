"""G2 configuration validation and test-evidence binding."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from optisys.config import ConfigError
from optisys.config_g2 import load_config_g2

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "configs" / "triangulation_g2_l1.yaml"
BASE = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def _write(tmp_path: Path, mutate) -> Path:
    payload = yaml.safe_load(yaml.safe_dump(BASE))
    mutate(payload)
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
    return path


def test_reference_config_loads() -> None:
    config = load_config_g2(CONFIG)
    assert config.model_level == "L1-approximate"
    assert len(config.calibration_distances) == 27
    assert len(config.dataset.validation_distances) == 7
    assert len(config.dataset.test_distances) == 7


def test_unknown_root_key_is_rejected(tmp_path) -> None:
    path = _write(tmp_path, lambda d: d.update({"surprise": 1}))
    with pytest.raises(ConfigError, match="unknown key"):
        load_config_g2(path)


def test_unknown_optics_key_is_rejected(tmp_path) -> None:
    def mutate(d):
        d["optics"]["magic"] = True

    with pytest.raises(ConfigError, match="unknown key"):
        load_config_g2(_write(tmp_path, mutate))


def test_wrong_schema_version_is_rejected(tmp_path) -> None:
    path = _write(tmp_path, lambda d: d.update({"schema_version": "2.0"}))
    with pytest.raises(ConfigError, match="schema_version"):
        load_config_g2(path)


def test_negative_tolerance_sigma_is_rejected(tmp_path) -> None:
    def mutate(d):
        d["tolerance"]["variables"]["cx_px"]["sigma"] = -0.5

    with pytest.raises(ConfigError):
        load_config_g2(_write(tmp_path, mutate))


def test_tolerance_unit_mismatch_is_rejected(tmp_path) -> None:
    def mutate(d):
        d["tolerance"]["variables"]["cx_px"]["unit"] = "mm"

    with pytest.raises(ConfigError, match="unit"):
        load_config_g2(_write(tmp_path, mutate))


def test_overlapping_splits_are_rejected(tmp_path) -> None:
    def mutate(d):
        d["dataset"]["split"]["test_distances"] = [110.0, 135.0, 165.0]

    with pytest.raises(ConfigError, match="overlap"):
        load_config_g2(_write(tmp_path, mutate))


def test_calibration_must_cover_the_range(tmp_path) -> None:
    def mutate(d):
        d["dataset"]["calibration_distances"] = [
            v for v in d["dataset"]["calibration_distances"] if v != 300.0
        ]

    with pytest.raises(ConfigError):
        load_config_g2(_write(tmp_path, mutate))


def test_objective_weights_must_sum_to_one(tmp_path) -> None:
    def mutate(d):
        d["objective"]["weights"]["failure"] = 0.5

    with pytest.raises(ConfigError, match="sum to 1"):
        load_config_g2(_write(tmp_path, mutate))


def test_unsupported_psf_kind_is_rejected(tmp_path) -> None:
    def mutate(d):
        d["optics"]["psf"]["kind"] = "magic_psf"

    with pytest.raises(ConfigError, match="psf.kind"):
        load_config_g2(_write(tmp_path, mutate))


def test_non_finite_number_is_rejected(tmp_path) -> None:
    def mutate(d):
        d["optics"]["aperture_diameter"] = float("nan")

    with pytest.raises(ConfigError, match="finite"):
        load_config_g2(_write(tmp_path, mutate))


# ---------------------------------------------------------------------------
# PRE-05: test evidence binding
# ---------------------------------------------------------------------------
def _summary(tmp_path: Path, passed: int, failed: int, skipped: int) -> Path:
    path = tmp_path / "summary.json"
    path.write_text(json.dumps({"totals": {
        "passed": passed, "failed": failed, "skipped": skipped,
        "total": passed + failed + skipped,
    }}), encoding="utf-8")
    return path


def _junit(tmp_path: Path, tests: int, failures: int, errors: int, skipped: int) -> Path:
    path = tmp_path / "junit.xml"
    path.write_text(
        f'<testsuite name="pytest" tests="{tests}" failures="{failures}" '
        f'errors="{errors}" skipped="{skipped}" time="1.0"/>',
        encoding="utf-8",
    )
    return path


def _context(tmp_path: Path):
    from optisys.runtime.run import RunContext

    return RunContext(project_root=ROOT, gate="G2", config_sha256="deadbeef",
                      runs_dir=tmp_path / "runs")


def test_binding_accepts_consistent_evidence(tmp_path) -> None:
    from optisys.config_g2 import load_config_g2 as loader
    from optisys.gates.g2 import _bind_tests

    context = _context(tmp_path)
    payload, check = _bind_tests(
        context, loader(CONFIG),
        summary_path=_summary(tmp_path, 194, 0, 0),
        stdout_path=None, junit_path=_junit(tmp_path, 194, 0, 0, 0),
        command="python -m pytest -q", exit_code=0, code_sha="abc",
    )
    assert check["pass"] is True
    assert payload["consistent"] is True


def test_binding_rejects_a_junit_count_mismatch(tmp_path) -> None:
    from optisys.config_g2 import load_config_g2 as loader
    from optisys.gates.g2 import _bind_tests

    context = _context(tmp_path)
    _, check = _bind_tests(
        context, loader(CONFIG),
        summary_path=_summary(tmp_path, 200, 0, 0),
        stdout_path=None, junit_path=_junit(tmp_path, 194, 0, 0, 0),
        command="python -m pytest -q", exit_code=0, code_sha="abc",
    )
    assert check["pass"] is False


def test_binding_rejects_a_nonzero_exit_with_zero_failures(tmp_path) -> None:
    from optisys.config_g2 import load_config_g2 as loader
    from optisys.gates.g2 import _bind_tests

    context = _context(tmp_path)
    _, check = _bind_tests(
        context, loader(CONFIG),
        summary_path=_summary(tmp_path, 194, 0, 0),
        stdout_path=None, junit_path=_junit(tmp_path, 194, 0, 0, 0),
        command="python -m pytest -q", exit_code=1, code_sha="abc",
    )
    assert check["pass"] is False


def test_binding_rejects_missing_junit(tmp_path) -> None:
    from optisys.config_g2 import load_config_g2 as loader
    from optisys.gates.g2 import _bind_tests

    context = _context(tmp_path)
    _, check = _bind_tests(
        context, loader(CONFIG),
        summary_path=_summary(tmp_path, 194, 0, 0),
        stdout_path=None, junit_path=None,
        command="python -m pytest -q", exit_code=0, code_sha="abc",
    )
    assert check["pass"] is False
