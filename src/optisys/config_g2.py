"""Configuration schema 3.0 for the G2 L1-approximate pipeline.

Rules
-----
* Unit-bearing field names carry no suffix; the unit is declared once in
  ``units`` and applied at load time (schema 2.0 rule, kept).
* Unknown keys are rejected, as are non-finite numbers, negative standard
  deviations, empty splits and unsupported model levels.
* ``model_level`` in the file is a *request*.  The gate decides the emitted
  level from evidence (`G2_ACCEPTANCE_CRITERIA.md` section 6).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from optisys import units
from optisys.config import ConfigError
from optisys.config_g1 import ConditionSpec, DatasetSpec, ImagingSpec, SensorSpec
from optisys.geometry.coplanar import CoplanarSpec
from optisys.optics.optical_image_contract import SUPPORTED_SIGNAL_MODES

SCHEMA_VERSION = "3.0"
SUPPORTED_MODEL_LEVELS = ("L1-approximate", "L1-attempted-not-verified")


@dataclass(frozen=True)
class PsfSpec:
    kind: str
    subpixel: int
    max_half_px: int
    airy_radius_margin: float


@dataclass(frozen=True)
class OpticsSpec:
    backend: str
    element: str
    material: str
    design_index: float
    aperture_diameter_mm: float
    element_thickness_mm: float
    rear_aperture_clearance_mm: float
    focus_distance_mm: float
    pupil_side: int
    psf: PsfSpec


@dataclass(frozen=True)
class ImagingG2Spec:
    signal_mode: str
    reference_electrons: float
    reference_distance_mm: float
    reference_aperture_mm: float
    background_e_per_px: float


@dataclass(frozen=True)
class ToleranceVariable:
    name: str
    sigma: float
    unit: str


@dataclass(frozen=True)
class ToleranceSpec:
    enabled: bool
    variables: tuple[ToleranceVariable, ...]
    correlation_enabled: bool
    rho_baseline_theta: float


@dataclass(frozen=True)
class ObjectiveSpec:
    w_mean_rmse: float
    w_p95: float
    w_failure: float
    rmse_ref_mm: float
    p95_ref_mm: float
    failure_ref: float
    robust_assemblies: int


@dataclass(frozen=True)
class ConstraintsSpec:
    sensor_margin_px: float
    min_ray_success: float
    min_kernel_support: float
    max_peak_fraction: float


@dataclass(frozen=True)
class CalibrationSpec:
    strategy_primary: str
    model: str
    min_improvement: float


@dataclass(frozen=True)
class RunG2Spec:
    seed: int
    search_max_evaluations: int
    search_wall_cap_s: float
    final_wall_cap_s: float


@dataclass(frozen=True)
class ResolvedG2Config:
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
    optics: OpticsSpec
    imaging: ImagingG2Spec
    sensor: SensorSpec
    dataset: DatasetSpec
    tolerance: ToleranceSpec
    objective: ObjectiveSpec
    constraints: ConstraintsSpec
    calibration: CalibrationSpec
    run: RunG2Spec
    calibration_distances: tuple[float, ...]
    final_assembly_draws: int
    stratified_assembly_draws: int

    @property
    def distances_mm(self) -> tuple[float, ...]:
        return tuple(float(v) for v in np.arange(self.z_min_mm, self.z_max_mm + 1e-9, 5.0))

    def summary(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "schema_version": self.schema_version,
            "model_level": self.model_level,
            "fx_px": self.fx_px,
            "baseline_mm": self.baseline_mm,
            "theta_deg": self.theta_deg,
            "working_range_mm": [self.z_min_mm, self.z_max_mm],
            "optics": {
                "backend": self.optics.backend,
                "element": self.optics.element,
                "aperture_mm": self.optics.aperture_diameter_mm,
                "focus_mm": self.optics.focus_distance_mm,
                "psf_kind": self.optics.psf.kind,
            },
            "signal_mode": self.imaging.signal_mode,
            "conditions": [c.name for c in self.dataset.conditions],
            "tolerance_variables": [v.name for v in self.tolerance.variables],
            "seed": self.run.seed,
        }


_ALLOWED = {
    "root": {"schema_version", "case_id", "model_level", "units", "source", "geometry",
             "camera", "optics", "imaging", "sensor", "dataset", "tolerance",
             "objective", "constraints", "calibration", "run"},
    "units": {"distance", "angle", "pixel_size"},
    "source": {"wavelength_nm", "theta"},
    "geometry": {"baseline", "distance", "working_range_enforced", "min_baseline_mm",
                 "singular_denominator_px", "sensor_margin_px", "range_epsilon_mm"},
    "camera": {"focal_length", "pixel_size", "resolution_px", "principal_point_px"},
    "optics": {"backend", "element", "material", "design_index", "aperture_diameter",
               "element_thickness", "rear_aperture_clearance", "focus_distance",
               "pupil_side", "psf"},
    "optics.psf": {"kind", "subpixel", "max_half_px", "airy_radius_margin"},
    "imaging": {"signal", "background_e_per_px"},
    "imaging.signal": {"mode", "reference_electrons", "reference_distance",
                       "reference_aperture"},
    "sensor": {"read_noise_e", "dark_rate_e_per_s", "exposure_ms", "full_well_e",
               "bit_depth", "e_per_adu", "black_level_adu", "adc_max_adu"},
    "dataset": {"conditions", "repeats", "split", "final_assembly_draws",
                "stratified_assembly_draws", "calibration_distances"},
    "dataset.split": {"validation_distances", "test_distances"},
    "dataset.conditions[]": {"name", "total_electrons", "background_e_per_px",
                             "read_noise_e", "reflectance_proxy"},
    "tolerance": {"enabled", "variables", "correlation"},
    "tolerance.variables": {"baseline_mm", "theta_deg", "focal_relative", "cx_px",
                            "focus_mm"},
    "tolerance.correlation": {"enabled", "rho_baseline_theta"},
    "objective": {"weights", "reference_scales", "robust_assemblies"},
    "objective.weights": {"mean_rmse", "p95", "failure"},
    "objective.reference_scales": {"rmse_mm", "p95_mm", "failure_rate"},
    "constraints": {"sensor_margin_px", "min_ray_success", "min_kernel_support",
                    "max_peak_fraction_of_full_well"},
    "calibration": {"strategy_primary", "model", "model_selection_min_improvement"},
    "run": {"seed", "search_max_evaluations", "search_wall_cap_s", "final_wall_cap_s"},
}

_TOLERANCE_UNITS = {"baseline_mm": "mm", "theta_deg": "deg", "focal_relative": "dimensionless",
                    "cx_px": "px", "focus_mm": "mm"}


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
         strict: bool = False) -> float:
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


def load_config_g2(path: str | Path) -> ResolvedG2Config:
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
    if model_level not in SUPPORTED_MODEL_LEVELS:
        raise ConfigError(f"model_level must be one of {SUPPORTED_MODEL_LEVELS}")

    units_cfg = _section(data, "units")
    unit_map = {q: str(_require(units_cfg, q, "units")) for q in ("distance", "angle", "pixel_size")}
    for quantity, unit in unit_map.items():
        if unit not in units.SUPPORTED_UNITS[quantity]:
            raise ConfigError(f"units.{quantity}={unit!r} not supported")

    source = _section(data, "source")
    wavelength_nm = _num(_require(source, "wavelength_nm", "source"), "source.wavelength_nm",
                         minimum=0, strict=True)
    theta_rad = units.to_internal(
        "angle", _num(_require(source, "theta", "source"), "source.theta"), unit_map["angle"]
    )
    theta_deg = units.rad_to_deg(theta_rad)
    if abs(theta_deg) > 80.0:
        raise ConfigError("source.theta exceeds the +/-80 deg validity domain")

    geometry = _section(data, "geometry")
    baseline_mm = units.to_internal(
        "distance", _num(_require(geometry, "baseline", "geometry"), "geometry.baseline",
                         minimum=0, strict=True), unit_map["distance"])
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
    margin_px = _num(geometry.get("sensor_margin_px", 0.0), "geometry.sensor_margin_px",
                     minimum=0)
    epsilon_mm = _num(geometry.get("range_epsilon_mm", 1e-6), "geometry.range_epsilon_mm",
                      minimum=0)
    enforce_range = geometry.get("working_range_enforced", True)
    if not isinstance(enforce_range, bool):
        raise ConfigError("geometry.working_range_enforced must be boolean")

    camera = _section(data, "camera")
    focal_length_mm = _num(_require(camera, "focal_length", "camera"), "camera.focal_length",
                           minimum=0, strict=True)
    pixel_size_mm = units.to_internal(
        "pixel_size", _num(_require(camera, "pixel_size", "camera"), "camera.pixel_size",
                           minimum=0, strict=True), unit_map["pixel_size"])
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

    optics_cfg = _section(data, "optics")
    backend = str(_require(optics_cfg, "backend", "optics"))
    if backend not in ("optiland",):
        raise ConfigError(f"optics.backend {backend!r} is not supported")
    element = str(_require(optics_cfg, "element", "optics"))
    if element not in ("singlet_equiconvex",):
        raise ConfigError(f"optics.element {element!r} is not supported")
    psf_cfg = _require(optics_cfg, "psf", "optics")
    if not isinstance(psf_cfg, dict):
        raise ConfigError("optics.psf must be a mapping")
    _check(psf_cfg, "optics.psf")
    psf_kind = str(psf_cfg.get("kind", "geometric_footprint_x_airy"))
    if psf_kind not in ("geometric_footprint_x_airy", "geometric_footprint", "airy_limit_model"):
        raise ConfigError(f"optics.psf.kind {psf_kind!r} is not supported")
    if int(psf_cfg.get("subpixel", 5)) % 2 == 0:
        raise ConfigError("optics.psf.subpixel must be odd")
    psf = PsfSpec(
        kind=psf_kind,
        subpixel=_int(psf_cfg.get("subpixel", 5), "optics.psf.subpixel", 1, 16),
        max_half_px=_int(psf_cfg.get("max_half_px", 40), "optics.psf.max_half_px", 4, 256),
        airy_radius_margin=_num(psf_cfg.get("airy_radius_margin", 6.0),
                                "optics.psf.airy_radius_margin", minimum=0),
    )
    optics = OpticsSpec(
        backend=backend,
        element=element,
        material=str(_require(optics_cfg, "material", "optics")),
        design_index=_num(_require(optics_cfg, "design_index", "optics"),
                          "optics.design_index", minimum=1.0, strict=True),
        aperture_diameter_mm=_num(_require(optics_cfg, "aperture_diameter", "optics"),
                                  "optics.aperture_diameter", minimum=0, strict=True),
        element_thickness_mm=_num(_require(optics_cfg, "element_thickness", "optics"),
                                  "optics.element_thickness", minimum=0, strict=True),
        rear_aperture_clearance_mm=_num(
            _require(optics_cfg, "rear_aperture_clearance", "optics"),
            "optics.rear_aperture_clearance", minimum=0.0),
        focus_distance_mm=_num(_require(optics_cfg, "focus_distance", "optics"),
                               "optics.focus_distance", minimum=0, strict=True),
        pupil_side=_int(optics_cfg.get("pupil_side", 17), "optics.pupil_side", 5, 51),
        psf=psf,
    )

    imaging_cfg = _section(data, "imaging")
    signal_cfg = _require(imaging_cfg, "signal", "imaging")
    if not isinstance(signal_cfg, dict):
        raise ConfigError("imaging.signal must be a mapping")
    _check(signal_cfg, "imaging.signal")
    signal_mode = str(signal_cfg.get("mode", "fixed_incident"))
    if signal_mode not in SUPPORTED_SIGNAL_MODES:
        raise ConfigError(f"imaging.signal.mode must be one of {SUPPORTED_SIGNAL_MODES}")
    imaging = ImagingG2Spec(
        signal_mode=signal_mode,
        reference_electrons=_num(_require(signal_cfg, "reference_electrons", "imaging.signal"),
                                 "imaging.signal.reference_electrons", minimum=0, strict=True),
        reference_distance_mm=_num(_require(signal_cfg, "reference_distance", "imaging.signal"),
                                   "imaging.signal.reference_distance", minimum=0, strict=True),
        reference_aperture_mm=_num(_require(signal_cfg, "reference_aperture", "imaging.signal"),
                                   "imaging.signal.reference_aperture", minimum=0, strict=True),
        background_e_per_px=_num(_require(imaging_cfg, "background_e_per_px", "imaging"),
                                 "imaging.background_e_per_px", minimum=0),
    )

    sensor_cfg = _section(data, "sensor")
    bit_depth = _int(_require(sensor_cfg, "bit_depth", "sensor"), "sensor.bit_depth", 8, 16)
    sensor = SensorSpec(
        read_noise_e=_num(_require(sensor_cfg, "read_noise_e", "sensor"), "sensor.read_noise_e",
                          minimum=0),
        dark_rate_e_per_s=_num(_require(sensor_cfg, "dark_rate_e_per_s", "sensor"),
                               "sensor.dark_rate_e_per_s", minimum=0),
        exposure_ms=_num(_require(sensor_cfg, "exposure_ms", "sensor"), "sensor.exposure_ms",
                         minimum=0, strict=True),
        full_well_e=_num(_require(sensor_cfg, "full_well_e", "sensor"), "sensor.full_well_e",
                         minimum=0, strict=True),
        bit_depth=bit_depth,
        e_per_adu=_num(_require(sensor_cfg, "e_per_adu", "sensor"), "sensor.e_per_adu",
                       minimum=0, strict=True),
        black_level_adu=_int(_require(sensor_cfg, "black_level_adu", "sensor"),
                             "sensor.black_level_adu", 0, 2**bit_depth - 1),
        adc_max_adu=_int(_require(sensor_cfg, "adc_max_adu", "sensor"), "sensor.adc_max_adu",
                         1, 2**bit_depth - 1),
    )

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
        if not name or name in {c.name for c in conditions}:
            raise ConfigError(f"dataset.conditions[{index}].name must be unique and non-empty")
        conditions.append(ConditionSpec(
            name=name,
            total_electrons=_num(_require(item, "total_electrons", name),
                                 f"{name}.total_electrons", minimum=0, strict=True),
            background_e_per_px=_num(_require(item, "background_e_per_px", name),
                                     f"{name}.background_e_per_px", minimum=0),
            read_noise_e=_num(_require(item, "read_noise_e", name), f"{name}.read_noise_e",
                              minimum=0),
            reflectance_proxy=_num(_require(item, "reflectance_proxy", name),
                                   f"{name}.reflectance_proxy", minimum=0, strict=True),
        ))
    repeats = _int(_require(dataset_cfg, "repeats", "dataset"), "dataset.repeats", 1, 1000)
    split_cfg = _require(dataset_cfg, "split", "dataset")
    if not isinstance(split_cfg, dict):
        raise ConfigError("dataset.split must be a mapping")
    _check(split_cfg, "dataset.split")
    validation = tuple(float(v) for v in _require(split_cfg, "validation_distances",
                                                  "dataset.split"))
    test = tuple(float(v) for v in _require(split_cfg, "test_distances", "dataset.split"))
    calibration_distances = tuple(
        float(v) for v in _require(dataset_cfg, "calibration_distances", "dataset")
    )
    final_draws = _int(_require(dataset_cfg, "final_assembly_draws", "dataset"),
                       "dataset.final_assembly_draws", 1, 20000)
    stratified = _int(dataset_cfg.get("stratified_assembly_draws", 200),
                      "dataset.stratified_assembly_draws", 1, 20000)

    tol_cfg = _section(data, "tolerance")
    variables_cfg = _require(tol_cfg, "variables", "tolerance")
    if not isinstance(variables_cfg, dict) or not variables_cfg:
        raise ConfigError("tolerance.variables must be a non-empty mapping")
    _check(variables_cfg, "tolerance.variables")
    variables = []
    for name, spec in variables_cfg.items():
        if not isinstance(spec, dict):
            raise ConfigError(f"tolerance.variables.{name} must be a mapping")
        unknown = sorted(set(spec) - {"distribution", "sigma", "unit"})
        if unknown:
            raise ConfigError(f"unknown key(s) in tolerance.variables.{name}: {unknown}")
        if str(spec.get("distribution", "normal")) != "normal":
            raise ConfigError(f"tolerance.variables.{name}.distribution must be 'normal'")
        unit = str(spec.get("unit", _TOLERANCE_UNITS[name]))
        if unit != _TOLERANCE_UNITS[name]:
            raise ConfigError(
                f"tolerance.variables.{name}.unit must be {_TOLERANCE_UNITS[name]!r}"
            )
        variables.append(ToleranceVariable(
            name=name,
            sigma=_num(_require(spec, "sigma", name), f"tolerance.variables.{name}.sigma",
                       minimum=0, strict=True),
            unit=unit,
        ))
    corr_cfg = tol_cfg.get("correlation", {"enabled": False, "rho_baseline_theta": 0.0})
    if not isinstance(corr_cfg, dict):
        raise ConfigError("tolerance.correlation must be a mapping")
    _check(corr_cfg, "tolerance.correlation")
    rho = _num(corr_cfg.get("rho_baseline_theta", 0.0),
               "tolerance.correlation.rho_baseline_theta", minimum=-0.99)
    if rho > 0.99:
        raise ConfigError("tolerance.correlation.rho_baseline_theta must be < 1")
    tolerance = ToleranceSpec(
        enabled=bool(tol_cfg.get("enabled", True)),
        variables=tuple(variables),
        correlation_enabled=bool(corr_cfg.get("enabled", False)),
        rho_baseline_theta=rho,
    )

    obj_cfg = _section(data, "objective")
    weights = _require(obj_cfg, "weights", "objective")
    scales = _require(obj_cfg, "reference_scales", "objective")
    if not isinstance(weights, dict) or not isinstance(scales, dict):
        raise ConfigError("objective.weights/reference_scales must be mappings")
    _check(weights, "objective.weights")
    _check(scales, "objective.reference_scales")
    w = {k: _num(_require(weights, k, "objective.weights"), f"objective.weights.{k}",
                 minimum=0) for k in ("mean_rmse", "p95", "failure")}
    total_w = sum(w.values())
    if not np.isclose(total_w, 1.0, atol=1e-9):
        raise ConfigError(f"objective weights must sum to 1, got {total_w}")
    objective = ObjectiveSpec(
        w_mean_rmse=w["mean_rmse"], w_p95=w["p95"], w_failure=w["failure"],
        rmse_ref_mm=_num(_require(scales, "rmse_mm", "objective.reference_scales"),
                         "objective.reference_scales.rmse_mm", minimum=0, strict=True),
        p95_ref_mm=_num(_require(scales, "p95_mm", "objective.reference_scales"),
                        "objective.reference_scales.p95_mm", minimum=0, strict=True),
        failure_ref=_num(_require(scales, "failure_rate", "objective.reference_scales"),
                         "objective.reference_scales.failure_rate", minimum=0, strict=True),
        robust_assemblies=_int(_require(obj_cfg, "robust_assemblies", "objective"),
                               "objective.robust_assemblies", 1, 500),
    )

    con_cfg = _section(data, "constraints")
    constraints = ConstraintsSpec(
        sensor_margin_px=_num(_require(con_cfg, "sensor_margin_px", "constraints"),
                              "constraints.sensor_margin_px", minimum=0),
        min_ray_success=_num(_require(con_cfg, "min_ray_success", "constraints"),
                             "constraints.min_ray_success", minimum=0),
        min_kernel_support=_num(_require(con_cfg, "min_kernel_support", "constraints"),
                                "constraints.min_kernel_support", minimum=0),
        max_peak_fraction=_num(_require(con_cfg, "max_peak_fraction_of_full_well", "constraints"),
                               "constraints.max_peak_fraction_of_full_well", minimum=0),
    )

    cal_cfg = _section(data, "calibration")
    strategy = str(_require(cal_cfg, "strategy_primary", "calibration"))
    if strategy not in ("A", "B"):
        raise ConfigError("calibration.strategy_primary must be 'A' or 'B'")
    model = str(cal_cfg.get("model", "M1"))
    if model not in ("M1", "M2", "AUTO"):
        raise ConfigError("calibration.model must be M1, M2 or AUTO")
    calibration = CalibrationSpec(
        strategy_primary=strategy,
        model=model,
        min_improvement=_num(cal_cfg.get("model_selection_min_improvement", 0.20),
                             "calibration.model_selection_min_improvement", minimum=0),
    )

    run_cfg = _section(data, "run")
    run_spec = RunG2Spec(
        seed=_int(_require(run_cfg, "seed", "run"), "run.seed", 0, 2**32 - 1),
        search_max_evaluations=_int(run_cfg.get("search_max_evaluations", 300),
                                    "run.search_max_evaluations", 1, 100000),
        search_wall_cap_s=_num(run_cfg.get("search_wall_cap_s", 3600.0),
                               "run.search_wall_cap_s", minimum=1.0),
        final_wall_cap_s=_num(run_cfg.get("final_wall_cap_s", 7200.0),
                              "run.final_wall_cap_s", minimum=1.0),
    )

    spec = CoplanarSpec(
        baseline_mm=baseline_mm, theta_rad=theta_rad, fx_px=fx_px, cx_px=cx_px, cy_px=cy_px,
        width_px=width_px, height_px=height_px, z_min_mm=z_min, z_max_mm=z_max,
        min_baseline_mm=min_baseline, singular_denominator_px=singular_px,
        sensor_margin_px=margin_px, enforce_working_range=enforce_range,
        range_epsilon_mm=epsilon_mm,
    )
    distances = np.arange(z_min, z_max + 1e-9, 5.0)
    _validate_split(validation, test, calibration_distances, distances)

    return ResolvedG2Config(
        path=config_path, sha256=digest, raw=data, case_id=case_id,
        schema_version=SCHEMA_VERSION, model_level=model_level,
        wavelength_nm=wavelength_nm, theta_deg=theta_deg, theta_rad=theta_rad,
        baseline_mm=baseline_mm, z_min_mm=z_min, z_max_mm=z_max,
        focal_length_mm=focal_length_mm, pixel_size_mm=pixel_size_mm, fx_px=fx_px,
        width_px=width_px, height_px=height_px, cx_px=cx_px, cy_px=cy_px,
        geometry=spec, optics=optics, imaging=imaging, sensor=sensor,
        dataset=DatasetSpec(
            conditions=tuple(conditions), repeats=repeats,
            validation_distances=validation, test_distances=test,
            representative_frames=0,
        ),
        tolerance=tolerance, objective=objective, constraints=constraints,
        calibration=calibration, run=run_spec,
        calibration_distances=calibration_distances,
        final_assembly_draws=final_draws,
        stratified_assembly_draws=stratified,
    )


def _validate_split(validation: tuple[float, ...], test: tuple[float, ...],
                    calibration: tuple[float, ...], distances: np.ndarray) -> None:
    allowed = {round(float(v), 6) for v in distances}
    for name, values in (("validation", validation), ("test", test),
                         ("calibration", calibration)):
        if len(set(values)) != len(values):
            raise ConfigError(f"{name} distances contain duplicates")
        missing = [v for v in values if round(float(v), 6) not in allowed]
        if missing:
            raise ConfigError(f"{name} distances outside the 5 mm grid: {missing}")
    sets = {
        "calibration": {round(v, 6) for v in calibration},
        "validation": {round(v, 6) for v in validation},
        "test": {round(v, 6) for v in test},
    }
    for a in sets:
        for b in sets:
            if a < b and sets[a] & sets[b]:
                raise ConfigError(
                    f"{a} and {b} distances overlap: {sorted(sets[a] & sets[b])}"
                )
    if min(sets["calibration"]) > min(allowed) + 1e-9:
        raise ConfigError("calibration must include the near end of the range")
    if max(sets["calibration"]) < max(allowed) - 1e-9:
        raise ConfigError("calibration must include the far end of the range")
