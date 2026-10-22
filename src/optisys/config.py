"""Configuration loading and strict validation.

The YAML file is the single source of truth for a run.  Validation is
deliberately strict: unknown keys are rejected so that a typo cannot silently
fall back to a default.  Units are declared in the file and converted
explicitly; nothing downstream guesses a unit from a variable name.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from optisys import units
from optisys.geometry.coplanar import CoplanarSpec

SCHEMA_VERSION = "1.0"
SUPPORTED_MODEL_LEVELS = ("L0", "L1", "L2")
G0_IMPLEMENTED_MODEL_LEVELS = ("L0",)


class ConfigError(ValueError):
    """Raised when a configuration file violates the schema or physics domain."""


@dataclass(frozen=True)
class RunSettings:
    seed: int
    distance_points: int
    repeats: int


@dataclass(frozen=True)
class ImageAssumptions:
    """Image-chain assumptions from the PDF section 9.1 example.

    They are validated at G0 but *not used*: sensor/PSF modelling starts at G1.
    """

    spot_sigma_px: float
    peak_electrons: float
    read_noise_e: float
    dark_rate_e_per_s: float
    exposure_ms: float


@dataclass(frozen=True)
class ResolvedConfig:
    path: Path
    sha256: str
    raw: dict[str, Any]
    case_id: str
    schema_version: str
    model_level: str
    wavelength_nm: float
    theta_deg: float
    theta_rad: float
    baseline_mm: float
    z_min_mm: float
    z_max_mm: float
    focal_length_mm: float
    pixel_size_mm: float
    fx_px: float
    width_px: int
    height_px: int
    cx_px: float
    cy_px: float
    geometry: CoplanarSpec
    run: RunSettings
    image: ImageAssumptions
    unused_at_g0: tuple[str, ...] = field(default_factory=tuple)

    def summary(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "schema_version": self.schema_version,
            "model_level": self.model_level,
            "wavelength_nm": self.wavelength_nm,
            "baseline_mm": self.baseline_mm,
            "theta_deg": self.theta_deg,
            "theta_rad": self.theta_rad,
            "working_range_mm": [self.z_min_mm, self.z_max_mm],
            "focal_length_mm": self.focal_length_mm,
            "pixel_size_mm": self.pixel_size_mm,
            "fx_px": self.fx_px,
            "sensor_px": [self.width_px, self.height_px],
            "principal_point_px": [self.cx_px, self.cy_px],
            "seed": self.run.seed,
            "distance_points": self.run.distance_points,
        }


_ALLOWED_KEYS: dict[str, set[str]] = {
    "root": {"schema_version", "case_id", "model_level", "units", "source", "geometry",
             "camera", "image", "run"},
    "units": {"distance", "angle", "pixel_size"},
    "source": {"wavelength_nm", "theta_deg"},
    "geometry": {"baseline_mm", "distance_mm", "working_range_enforced", "min_baseline_mm",
                 "singular_denominator_px", "sensor_margin_px", "range_epsilon_mm"},
    "camera": {"focal_length_mm", "pixel_size_um", "resolution_px", "principal_point_px"},
    "image": {"spot_sigma_px", "peak_electrons", "read_noise_e", "dark_rate_e_per_s",
              "exposure_ms"},
    "run": {"seed", "distance_points", "repeats"},
}


def _require(mapping: dict[str, Any], key: str, section: str) -> Any:
    if key not in mapping:
        raise ConfigError(f"missing required key: {section}.{key}")
    return mapping[key]


def _check_unknown(mapping: dict[str, Any], section: str) -> None:
    allowed = _ALLOWED_KEYS[section]
    unknown = sorted(set(mapping) - allowed)
    if unknown:
        raise ConfigError(f"unknown key(s) in {section}: {', '.join(unknown)}")


def _section(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = _require(data, key, "root")
    if not isinstance(value, dict):
        raise ConfigError(f"root.{key} must be a mapping")
    _check_unknown(value, key)
    return value


def _positive(value: Any, name: str, allow_zero: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{name} must be a number, got {type(value).__name__}")
    number = float(value)
    if not np.isfinite(number):
        raise ConfigError(f"{name} must be finite")
    if allow_zero and number < 0.0:
        raise ConfigError(f"{name} must be >= 0")
    if not allow_zero and number <= 0.0:
        raise ConfigError(f"{name} must be > 0")
    return number


def _integer(value: Any, name: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{name} must be an integer")
    if value < minimum:
        raise ConfigError(f"{name} must be >= {minimum}")
    return value


def config_from_dict(data: dict[str, Any], *, path: Path | None = None,
                     sha256: str = "UNKNOWN") -> ResolvedConfig:
    """Validate an in-memory configuration mapping."""

    if not isinstance(data, dict):
        raise ConfigError("root must be a mapping")
    schema_version = str(_require(data, "schema_version", "root"))
    if schema_version != SCHEMA_VERSION:
        raise ConfigError(f"unsupported schema_version {schema_version!r}; expected {SCHEMA_VERSION!r}")

    case_id = _require(data, "case_id", "root")
    if not isinstance(case_id, str) or not case_id.strip():
        raise ConfigError("case_id must be a non-empty string")

    model_level = str(_require(data, "model_level", "root"))
    if model_level not in SUPPORTED_MODEL_LEVELS:
        raise ConfigError(f"model_level must be one of {SUPPORTED_MODEL_LEVELS}")

    units_cfg = _section(data, "units")
    unit_map = {
        "distance": str(_require(units_cfg, "distance", "units")),
        "angle": str(_require(units_cfg, "angle", "units")),
        "pixel_size": str(_require(units_cfg, "pixel_size", "units")),
    }
    for quantity, unit in unit_map.items():
        if unit not in units.SUPPORTED_UNITS[quantity]:
            allowed = ", ".join(units.SUPPORTED_UNITS[quantity])
            raise ConfigError(f"units.{quantity}={unit!r} not supported; allowed: {allowed}")

    # Schema 1.0 rule: the field suffix determines the unit.  A declaration that
    # disagrees with the suffix is ambiguous and therefore rejected instead of
    # being silently converted.
    if unit_map["angle"] != "deg":
        raise ConfigError(
            "schema 1.0 uses source.theta_deg (suffix determines unit); "
            "units.angle must be 'deg', got " + repr(unit_map["angle"])
        )
    if unit_map["pixel_size"] != "um":
        raise ConfigError(
            "schema 1.0 uses camera.pixel_size_um (suffix determines unit); "
            "units.pixel_size must be 'um', got " + repr(unit_map["pixel_size"])
        )

    source = _section(data, "source")
    wavelength_nm = _positive(_require(source, "wavelength_nm", "source"), "source.wavelength_nm")
    theta_deg = _require(source, "theta_deg", "source")
    if isinstance(theta_deg, bool) or not isinstance(theta_deg, (int, float)):
        raise ConfigError("source.theta_deg must be a number")
    theta_deg = float(theta_deg)
    if not np.isfinite(theta_deg) or abs(theta_deg) > 80.0:
        raise ConfigError("source.theta_deg must be finite and |theta| <= 80 deg")

    geometry = _section(data, "geometry")
    baseline_mm = _positive(_require(geometry, "baseline_mm", "geometry"), "geometry.baseline_mm")
    distance = _require(geometry, "distance_mm", "geometry")
    if not isinstance(distance, (list, tuple)) or len(distance) != 2:
        raise ConfigError("geometry.distance_mm must be a two-element list [min, max]")
    z_min = _positive(distance[0], "geometry.distance_mm[0]")
    z_max = _positive(distance[1], "geometry.distance_mm[1]")
    if not z_min < z_max:
        raise ConfigError("geometry.distance_mm requires min < max")
    min_baseline = _positive(geometry.get("min_baseline_mm", 1.0), "geometry.min_baseline_mm")
    singular_denominator = _positive(
        geometry.get("singular_denominator_px", 1.0e-6), "geometry.singular_denominator_px"
    )
    sensor_margin = _positive(
        geometry.get("sensor_margin_px", 0.0), "geometry.sensor_margin_px", allow_zero=True
    )
    range_epsilon = _positive(
        geometry.get("range_epsilon_mm", 1.0e-6), "geometry.range_epsilon_mm", allow_zero=True
    )
    enforce_range = geometry.get("working_range_enforced", True)
    if not isinstance(enforce_range, bool):
        raise ConfigError("geometry.working_range_enforced must be a boolean")
    if baseline_mm < min_baseline:
        raise ConfigError(
            f"geometry.baseline_mm={baseline_mm} mm is below the declared physical "
            f"minimum {min_baseline} mm (B -> 0 destroys triangulation)"
        )

    camera = _section(data, "camera")
    focal_length_mm = _positive(
        _require(camera, "focal_length_mm", "camera"), "camera.focal_length_mm"
    )
    pixel_size_um = _positive(_require(camera, "pixel_size_um", "camera"), "camera.pixel_size_um")
    resolution = _require(camera, "resolution_px", "camera")
    if not isinstance(resolution, (list, tuple)) or len(resolution) != 2:
        raise ConfigError("camera.resolution_px must be [width, height]")
    width_px = _integer(resolution[0], "camera.resolution_px[0]", 2)
    height_px = _integer(resolution[1], "camera.resolution_px[1]", 2)
    principal = _require(camera, "principal_point_px", "camera")
    if not isinstance(principal, (list, tuple)) or len(principal) != 2:
        raise ConfigError("camera.principal_point_px must be [cx, cy]")
    cx_px = float(principal[0])
    cy_px = float(principal[1])
    if not (0.0 <= cx_px <= width_px - 1):
        raise ConfigError(f"camera.principal_point_px[0]={cx_px} outside [0, {width_px - 1}]")
    if not (0.0 <= cy_px <= height_px - 1):
        raise ConfigError(f"camera.principal_point_px[1]={cy_px} outside [0, {height_px - 1}]")

    image_cfg = _section(data, "image")
    spot_sigma_px = _positive(_require(image_cfg, "spot_sigma_px", "image"), "image.spot_sigma_px")
    peak_electrons = _positive(
        _require(image_cfg, "peak_electrons", "image"), "image.peak_electrons", allow_zero=True
    )
    read_noise_e = _positive(
        _require(image_cfg, "read_noise_e", "image"), "image.read_noise_e", allow_zero=True
    )
    dark_rate = _positive(
        _require(image_cfg, "dark_rate_e_per_s", "image"), "image.dark_rate_e_per_s", allow_zero=True
    )
    exposure_ms = _positive(_require(image_cfg, "exposure_ms", "image"), "image.exposure_ms")
    image = ImageAssumptions(spot_sigma_px, peak_electrons, read_noise_e, dark_rate, exposure_ms)

    run_cfg = _section(data, "run")
    seed = _integer(_require(run_cfg, "seed", "run"), "run.seed", 0)
    if seed > 2**32 - 1:
        raise ConfigError("run.seed must fit in 32 bits (<= 4294967295)")
    distance_points = _integer(_require(run_cfg, "distance_points", "run"), "run.distance_points", 2)
    if distance_points > 1_000_000:
        raise ConfigError("run.distance_points is unreasonably large (> 1e6)")
    repeats = _integer(_require(run_cfg, "repeats", "run"), "run.repeats", 1)

    pixel_size_mm = units.to_internal("pixel_size", pixel_size_um, unit_map["pixel_size"])
    theta_rad = units.to_internal("angle", theta_deg, unit_map["angle"])
    fx_px = focal_length_mm / pixel_size_mm
    if not np.isfinite(fx_px) or fx_px <= 0.0:
        raise ConfigError("derived fx = f_mm / p_mm is not a positive finite number")

    spec = CoplanarSpec(
        baseline_mm=baseline_mm,
        theta_rad=theta_rad,
        fx_px=fx_px,
        cx_px=cx_px,
        cy_px=cy_px,
        width_px=width_px,
        height_px=height_px,
        z_min_mm=z_min,
        z_max_mm=z_max,
        min_baseline_mm=min_baseline,
        singular_denominator_px=singular_denominator,
        sensor_margin_px=sensor_margin,
        enforce_working_range=enforce_range,
        range_epsilon_mm=range_epsilon,
    )

    unused = tuple(
        sorted(
            [f"image.{key}" for key in image_cfg]
            + (["run.repeats"] if repeats else [])
        )
    )

    return ResolvedConfig(
        path=path or Path("<memory>"),
        sha256=sha256,
        raw=data,
        case_id=case_id,
        schema_version=schema_version,
        model_level=model_level,
        wavelength_nm=wavelength_nm,
        theta_deg=theta_deg,
        theta_rad=theta_rad,
        baseline_mm=baseline_mm,
        z_min_mm=z_min,
        z_max_mm=z_max,
        focal_length_mm=focal_length_mm,
        pixel_size_mm=pixel_size_mm,
        fx_px=fx_px,
        width_px=width_px,
        height_px=height_px,
        cx_px=cx_px,
        cy_px=cy_px,
        geometry=spec,
        run=RunSettings(seed, distance_points, repeats),
        image=image,
        unused_at_g0=unused,
    )


def load_config(path: str | Path) -> ResolvedConfig:
    """Read and validate a YAML configuration file."""

    config_path = Path(path)
    if not config_path.is_file():
        raise ConfigError(f"config file not found: {config_path}")
    payload = config_path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    try:
        data = yaml.safe_load(payload.decode("utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover - malformed file path
        raise ConfigError(f"invalid YAML in {config_path}: {exc}") from exc
    return config_from_dict(data, path=config_path, sha256=digest)
