"""Configuration schema 2.0 for the G1 L0 imaging pipeline.

Rule change relative to schema 1.0: unit-bearing field names carry no suffix.
The unit of every physical quantity is declared once in ``units`` and applied
explicitly at load time.  Schema 1.0 keeps its legacy suffix rule (validated in
``optisys.config``); the two rules are never mixed inside one file.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from optisys import units
from optisys.config import ConfigError
from optisys.geometry.coplanar import CoplanarSpec

SCHEMA_VERSION = "2.0"


@dataclass(frozen=True)
class ImagingSpec:
    sigma_px: float
    total_electrons: float
    background_e_per_px: float
    signal_mode: str = "total_electrons"


@dataclass(frozen=True)
class SensorSpec:
    read_noise_e: float
    dark_rate_e_per_s: float
    exposure_ms: float
    full_well_e: float
    bit_depth: int
    e_per_adu: float
    black_level_adu: int
    adc_max_adu: int

    @property
    def exposure_s(self) -> float:
        return self.exposure_ms * 1e-3

    @property
    def dark_e_per_px(self) -> float:
        return self.dark_rate_e_per_s * self.exposure_s

    @property
    def adc_limit(self) -> int:
        return min(self.adc_max_adu, 2**self.bit_depth - 1)

    def with_read_noise(self, read_noise_e: float) -> "SensorSpec":
        return SensorSpec(
            read_noise_e=read_noise_e,
            dark_rate_e_per_s=self.dark_rate_e_per_s,
            exposure_ms=self.exposure_ms,
            full_well_e=self.full_well_e,
            bit_depth=self.bit_depth,
            e_per_adu=self.e_per_adu,
            black_level_adu=self.black_level_adu,
            adc_max_adu=self.adc_max_adu,
        )


@dataclass(frozen=True)
class ConditionSpec:
    name: str
    total_electrons: float
    background_e_per_px: float
    read_noise_e: float
    reflectance_proxy: float

    def sensor(self, base: SensorSpec) -> SensorSpec:
        return base.with_read_noise(self.read_noise_e)

    def imaging(self, base: ImagingSpec) -> ImagingSpec:
        return ImagingSpec(
            sigma_px=base.sigma_px,
            total_electrons=self.total_electrons,
            background_e_per_px=self.background_e_per_px,
            signal_mode=base.signal_mode,
        )


@dataclass(frozen=True)
class DatasetSpec:
    conditions: tuple[ConditionSpec, ...]
    repeats: int
    validation_distances: tuple[float, ...]
    test_distances: tuple[float, ...]
    representative_frames: int = 12


@dataclass(frozen=True)
class ResolvedG1Config:
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
    imaging: ImagingSpec
    sensor: SensorSpec
    dataset: DatasetSpec
    seed: int
    unused_fields: tuple[str, ...] = field(default_factory=tuple)

    @property
    def distances_mm(self) -> tuple[float, ...]:
        return tuple(
            float(value)
            for value in np.arange(self.z_min_mm, self.z_max_mm + 1e-9, 5.0)
        )

    def summary(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "schema_version": self.schema_version,
            "model_level": self.model_level,
            "fx_px": self.fx_px,
            "baseline_mm": self.baseline_mm,
            "theta_deg": self.theta_deg,
            "theta_rad": self.theta_rad,
            "working_range_mm": [self.z_min_mm, self.z_max_mm],
            "distances_mm": len(self.distances_mm),
            "sigma_px": self.imaging.sigma_px,
            "base_total_electrons": self.imaging.total_electrons,
            "conditions": [condition.name for condition in self.dataset.conditions],
            "repeats": self.dataset.repeats,
            "frames": len(self.distances_mm) * len(self.dataset.conditions) * self.dataset.repeats,
            "sensor": {
                "read_noise_e": self.sensor.read_noise_e,
                "exposure_ms": self.sensor.exposure_ms,
                "full_well_e": self.sensor.full_well_e,
                "bit_depth": self.sensor.bit_depth,
                "e_per_adu": self.sensor.e_per_adu,
                "black_level_adu": self.sensor.black_level_adu,
            },
            "seed": self.seed,
        }


_ALLOWED = {
    "root": {"schema_version", "case_id", "model_level", "units", "source", "geometry",
             "camera", "imaging", "sensor", "dataset", "run"},
    "units": {"distance", "angle", "pixel_size"},
    "source": {"wavelength_nm", "theta"},
    "geometry": {"baseline", "distance", "working_range_enforced", "min_baseline_mm",
                 "singular_denominator_px", "sensor_margin_px", "range_epsilon_mm"},
    "camera": {"focal_length", "pixel_size", "resolution_px", "principal_point_px"},
    "imaging": {"sigma_px", "signal", "background_e_per_px"},
    "imaging.signal": {"mode", "total_electrons"},
    "sensor": {"read_noise_e", "dark_rate_e_per_s", "exposure_ms", "full_well_e",
               "bit_depth", "e_per_adu", "black_level_adu", "adc_max_adu"},
    "dataset": {"conditions", "repeats", "split", "representative_frames"},
    "dataset.split": {"validation_distances", "test_distances"},
    "dataset.conditions[]": {"name", "total_electrons", "background_e_per_px",
                             "read_noise_e", "reflectance_proxy"},
    "run": {"seed"},
}


def _require(mapping: dict[str, Any], key: str, section: str) -> Any:
    if key not in mapping:
        raise ConfigError(f"missing required key: {section}.{key}")
    return mapping[key]


def _check(mapping: dict[str, Any], section: str) -> None:
    unknown = sorted(set(mapping) - _ALLOWED[section])
    if unknown:
        raise ConfigError(f"unknown key(s) in {section}: {', '.join(unknown)}")


def _section(data: dict[str, Any], key: str) -> dict[str, Any]:
    value = _require(data, key, "root")
    if not isinstance(value, dict):
        raise ConfigError(f"root.{key} must be a mapping")
    _check(value, key)
    return value


def _num(value: Any, name: str, *, minimum: float | None = None,
         strict: bool = False, allow_zero: bool = True) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ConfigError(f"{name} must be a number")
    number = float(value)
    if not np.isfinite(number):
        raise ConfigError(f"{name} must be finite")
    if minimum is not None:
        if strict and number <= minimum:
            raise ConfigError(f"{name} must be > {minimum}")
        if not strict and number < minimum:
            raise ConfigError(f"{name} must be >= {minimum}")
    return number


def _int(value: Any, name: str, minimum: int, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{name} must be an integer")
    if value < minimum or (maximum is not None and value > maximum):
        raise ConfigError(f"{name} out of range [{minimum}, {maximum}]")
    return value


def load_config_g1(path: str | Path) -> ResolvedG1Config:
    config_path = Path(path)
    if not config_path.is_file():
        raise ConfigError(f"config file not found: {config_path}")
    payload = config_path.read_bytes()
    digest = hashlib.sha256(payload).hexdigest()
    try:
        data = yaml.safe_load(payload.decode("utf-8"))
    except yaml.YAMLError as exc:  # pragma: no cover
        raise ConfigError(f"invalid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError("root must be a mapping")
    if str(_require(data, "schema_version", "root")) != SCHEMA_VERSION:
        raise ConfigError(f"schema_version must be {SCHEMA_VERSION!r} for this loader")
    _check(data, "root")
    case_id = _require(data, "case_id", "root")
    if not isinstance(case_id, str) or not case_id.strip():
        raise ConfigError("case_id must be a non-empty string")
    model_level = str(_require(data, "model_level", "root"))
    if model_level != "L0":
        raise ConfigError("G1 schema 2.0 supports model_level 'L0' only")

    units_cfg = _section(data, "units")
    unit_map = {
        quantity: str(_require(units_cfg, quantity, "units"))
        for quantity in ("distance", "angle", "pixel_size")
    }
    for quantity, unit in unit_map.items():
        if unit not in units.SUPPORTED_UNITS[quantity]:
            raise ConfigError(f"units.{quantity}={unit!r} not supported")

    source = _section(data, "source")
    wavelength_nm = _num(_require(source, "wavelength_nm", "source"), "source.wavelength_nm",
                         minimum=0, strict=True)
    theta_raw = _num(_require(source, "theta", "source"), "source.theta")
    theta_rad = units.to_internal("angle", theta_raw, unit_map["angle"])
    theta_deg = units.rad_to_deg(theta_rad)
    if abs(theta_deg) > 80.0:
        raise ConfigError("source.theta exceeds the +/-80 deg validity domain")

    geometry = _section(data, "geometry")
    baseline_mm = units.to_internal(
        "distance", _num(_require(geometry, "baseline", "geometry"), "geometry.baseline",
                         minimum=0, strict=True), unit_map["distance"]
    )
    distance = _require(geometry, "distance", "geometry")
    if not isinstance(distance, (list, tuple)) or len(distance) != 2:
        raise ConfigError("geometry.distance must be [min, max]")
    z_min = units.to_internal("distance", _num(distance[0], "geometry.distance[0]",
                                               minimum=0, strict=True), unit_map["distance"])
    z_max = units.to_internal("distance", _num(distance[1], "geometry.distance[1]",
                                               minimum=0, strict=True), unit_map["distance"])
    if z_min >= z_max:
        raise ConfigError("geometry.distance requires min < max")
    min_baseline = _num(geometry.get("min_baseline_mm", 1.0), "geometry.min_baseline_mm",
                        minimum=0, strict=True)
    if baseline_mm < min_baseline:
        raise ConfigError("geometry.baseline is below geometry.min_baseline_mm")
    singular_px = _num(geometry.get("singular_denominator_px", 1e-6),
                       "geometry.singular_denominator_px", minimum=0, strict=True)
    margin_px = _num(geometry.get("sensor_margin_px", 0.0),
                     "geometry.sensor_margin_px", minimum=0)
    epsilon_mm = _num(geometry.get("range_epsilon_mm", 1e-6),
                      "geometry.range_epsilon_mm", minimum=0)
    enforce_range = geometry.get("working_range_enforced", True)
    if not isinstance(enforce_range, bool):
        raise ConfigError("geometry.working_range_enforced must be boolean")

    camera = _section(data, "camera")
    focal_length_mm = _num(_require(camera, "focal_length", "camera"), "camera.focal_length",
                           minimum=0, strict=True)
    pixel_size_mm = units.to_internal(
        "pixel_size", _num(_require(camera, "pixel_size", "camera"), "camera.pixel_size",
                           minimum=0, strict=True), unit_map["pixel_size"]
    )
    resolution = _require(camera, "resolution_px", "camera")
    if not isinstance(resolution, (list, tuple)) or len(resolution) != 2:
        raise ConfigError("camera.resolution_px must be [width, height]")
    width_px = _int(resolution[0], "camera.resolution_px[0]", 8)
    height_px = _int(resolution[1], "camera.resolution_px[1]", 8)
    principal = _require(camera, "principal_point_px", "camera")
    if not isinstance(principal, (list, tuple)) or len(principal) != 2:
        raise ConfigError("camera.principal_point_px must be [cx, cy]")
    cx_px = _num(principal[0], "camera.principal_point_px[0]", minimum=0)
    cy_px = _num(principal[1], "camera.principal_point_px[1]", minimum=0)
    if cx_px > width_px - 1 or cy_px > height_px - 1:
        raise ConfigError("principal point must lie inside the sensor")
    fx_px = focal_length_mm / pixel_size_mm
    if not np.isfinite(fx_px) or fx_px <= 0:
        raise ConfigError("derived fx is invalid")

    imaging_cfg = _section(data, "imaging")
    sigma_px = _num(_require(imaging_cfg, "sigma_px", "imaging"), "imaging.sigma_px",
                    minimum=0, strict=True)
    signal_cfg = _require(imaging_cfg, "signal", "imaging")
    if not isinstance(signal_cfg, dict):
        raise ConfigError("imaging.signal must be a mapping")
    _check(signal_cfg, "imaging.signal")
    signal_mode = str(signal_cfg.get("mode", "total_electrons"))
    if signal_mode != "total_electrons":
        raise ConfigError("imaging.signal.mode must be 'total_electrons' for G1")
    total_electrons = _num(_require(signal_cfg, "total_electrons", "imaging.signal"),
                           "imaging.signal.total_electrons", minimum=0, strict=True)
    background = _num(_require(imaging_cfg, "background_e_per_px", "imaging"),
                      "imaging.background_e_per_px", minimum=0)

    sensor_cfg = _section(data, "sensor")
    read_noise = _num(_require(sensor_cfg, "read_noise_e", "sensor"), "sensor.read_noise_e",
                      minimum=0)
    dark_rate = _num(_require(sensor_cfg, "dark_rate_e_per_s", "sensor"),
                     "sensor.dark_rate_e_per_s", minimum=0)
    exposure_ms = _num(_require(sensor_cfg, "exposure_ms", "sensor"), "sensor.exposure_ms",
                       minimum=0, strict=True)
    full_well = _num(_require(sensor_cfg, "full_well_e", "sensor"), "sensor.full_well_e",
                     minimum=0, strict=True)
    bit_depth = _int(_require(sensor_cfg, "bit_depth", "sensor"), "sensor.bit_depth", 8, 16)
    e_per_adu = _num(_require(sensor_cfg, "e_per_adu", "sensor"), "sensor.e_per_adu",
                     minimum=0, strict=True)
    black_level = _int(_require(sensor_cfg, "black_level_adu", "sensor"),
                       "sensor.black_level_adu", 0, 2**bit_depth - 1)
    adc_max = _int(_require(sensor_cfg, "adc_max_adu", "sensor"), "sensor.adc_max_adu", 1,
                   2**bit_depth - 1)

    dataset_cfg = _section(data, "dataset")
    conditions_raw = _require(dataset_cfg, "conditions", "dataset")
    if not isinstance(conditions_raw, list) or not conditions_raw:
        raise ConfigError("dataset.conditions must be a non-empty list")
    conditions = []
    for index, item in enumerate(conditions_raw):
        if not isinstance(item, dict):
            raise ConfigError(f"dataset.conditions[{index}] must be a mapping")
        _check(item, "dataset.conditions[]")
        name = str(_require(item, "name", f"dataset.conditions[{index}]"))
        if not name or name in {condition.name for condition in conditions}:
            raise ConfigError(f"dataset.conditions[{index}].name must be unique and non-empty")
        conditions.append(
            ConditionSpec(
                name=name,
                total_electrons=_num(_require(item, "total_electrons", name),
                                     f"{name}.total_electrons", minimum=0, strict=True),
                background_e_per_px=_num(_require(item, "background_e_per_px", name),
                                         f"{name}.background_e_per_px", minimum=0),
                read_noise_e=_num(_require(item, "read_noise_e", name),
                                  f"{name}.read_noise_e", minimum=0),
                reflectance_proxy=_num(_require(item, "reflectance_proxy", name),
                                       f"{name}.reflectance_proxy", minimum=0, strict=True),
            )
        )
    repeats = _int(_require(dataset_cfg, "repeats", "dataset"), "dataset.repeats", 1, 1000)
    split_cfg = _require(dataset_cfg, "split", "dataset")
    if not isinstance(split_cfg, dict):
        raise ConfigError("dataset.split must be a mapping")
    _check(split_cfg, "dataset.split")
    validation = tuple(
        float(value) for value in _require(split_cfg, "validation_distances", "dataset.split")
    )
    test = tuple(float(value) for value in _require(split_cfg, "test_distances", "dataset.split"))
    representative = _int(dataset_cfg.get("representative_frames", 12),
                          "dataset.representative_frames", 0, 200)

    run_cfg = _section(data, "run")
    seed = _int(_require(run_cfg, "seed", "run"), "run.seed", 0, 2**32 - 1)

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
        singular_denominator_px=singular_px,
        sensor_margin_px=margin_px,
        enforce_working_range=enforce_range,
        range_epsilon_mm=epsilon_mm,
    )

    distances = np.arange(z_min, z_max + 1e-9, 5.0)
    _validate_split(validation, test, distances)
    if not conditions:
        raise ConfigError("no conditions")

    sensor = SensorSpec(
        read_noise_e=read_noise,
        dark_rate_e_per_s=dark_rate,
        exposure_ms=exposure_ms,
        full_well_e=full_well,
        bit_depth=bit_depth,
        e_per_adu=e_per_adu,
        black_level_adu=black_level,
        adc_max_adu=adc_max,
    )

    return ResolvedG1Config(
        path=config_path,
        sha256=digest,
        raw=data,
        case_id=case_id,
        schema_version=SCHEMA_VERSION,
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
        imaging=ImagingSpec(sigma_px, total_electrons, background),
        sensor=sensor,
        dataset=DatasetSpec(
            conditions=tuple(conditions),
            repeats=repeats,
            validation_distances=validation,
            test_distances=test,
            representative_frames=representative,
        ),
        seed=seed,
    )


def _validate_split(validation: tuple[float, ...], test: tuple[float, ...],
                    distances: np.ndarray) -> None:
    allowed = {round(float(value), 6) for value in distances}
    for name, values in (("validation", validation), ("test", test)):
        if len(set(values)) != len(values):
            raise ConfigError(f"dataset.split.{name}_distances contains duplicates")
        missing = [value for value in values if round(float(value), 6) not in allowed]
        if missing:
            raise ConfigError(f"dataset.split.{name}_distances outside the distance grid: {missing}")
    overlap = set(validation) & set(test)
    if overlap:
        raise ConfigError(f"validation and test distances overlap: {sorted(overlap)}")
    if len(validation) + len(test) >= len(distances):
        raise ConfigError("split leaves no calibration distances")
    calib = allowed - {round(float(v), 6) for v in validation} - {round(float(v), 6) for v in test}
    if not calib:
        raise ConfigError("empty calibration split")
    if min(calib) > min(distances) + 1e-9 or max(calib) < max(distances) - 1e-9:
        raise ConfigError("calibration split must include both ends of the distance range")
