"""Strict loader for the schema 4.0 976 nm pump case."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from optisys.config import ConfigError
from optisys.optics.pump_beamline import BeamlineConfig, ThinLensPlane


class PumpConfigError(ConfigError):
    """Invalid schema 4.0 pump configuration."""


@dataclass(frozen=True)
class Pump976Config:
    path: Path
    raw: dict[str, Any]
    design_id: str
    wavelength_nm: float
    core_diameter_mm: float
    numerical_aperture: float
    output_index: float
    angular_distribution: str
    seed: int
    n_rays: int
    absolute_power_w: float | None
    beamline: BeamlineConfig

    def source_metadata(self) -> dict[str, Any]:
        return {
            "wavelength_nm": self.wavelength_nm,
            "core_diameter_mm": self.core_diameter_mm,
            "numerical_aperture": self.numerical_aperture,
            "output_index": self.output_index,
            "angular_distribution": self.angular_distribution,
            "seed": self.seed,
            "n_rays": self.n_rays,
            "absolute_power_w": self.absolute_power_w,
        }

    @property
    def sha256(self) -> str:
        import hashlib
        return hashlib.sha256(self.path.read_bytes()).hexdigest()

    @property
    def model_level(self) -> str:
        return "P0_ANALYTIC"

    def summary(self) -> dict[str, Any]:
        return {
            "schema_version": "4.0", "case_id": "pump976_g4",
            "design_id": self.design_id, "model_level": self.model_level,
            "source": self.source_metadata(),
            "optics": {
                "l1": {"focal_length_mm": self.beamline.l1.focal_length_mm,
                       "z_mm": self.beamline.l1.z_mm,
                       "aperture_diameter_mm": self.beamline.l1.aperture_diameter_mm},
                "l2": {"focal_length_mm": self.beamline.l2.focal_length_mm,
                       "z_mm": self.beamline.l2.z_mm,
                       "aperture_diameter_mm": self.beamline.l2.aperture_diameter_mm},
                "target_z_mm": self.beamline.target_z_mm,
                "target_radius_mm": self.beamline.target_radius_mm,
            },
            "evidence_status": "SIMULATED", "absolute_power_w": "UNKNOWN",
        }


@dataclass(frozen=True)
class PumpToleranceConfig:
    path: Path
    raw: dict[str, Any]
    rays_per_assembly: int
    precheck_assemblies: int
    precheck_seed: int
    holdout_assemblies: int
    holdout_seed: int
    oat_seed: int
    perturbations: dict[str, dict[str, Any]]


def load_pump976_config(path: str | Path) -> Pump976Config:
    config_path = Path(path).resolve()
    if not config_path.is_file():
        raise PumpConfigError(f"config file not found: {config_path}")
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise PumpConfigError(f"invalid YAML: {exc}") from exc
    if not isinstance(raw, dict):
        raise PumpConfigError("config root must be a mapping")
    if str(raw.get("schema_version")) != "4.0":
        raise PumpConfigError("pump976 requires schema_version '4.0'")
    if raw.get("case_id") not in ("pump976_g4", "pump976_g4_tolerance"):
        raise PumpConfigError("case_id must identify a G4 pump case")
    units = raw.get("units", {})
    if units.get("distance") != "mm" or units.get("angle") != "rad":
        raise PumpConfigError("core units must be distance=mm and angle=rad")

    source = raw.get("source")
    optics = raw.get("optics")
    if not isinstance(source, dict) or not isinstance(optics, dict):
        raise PumpConfigError("source and optics must be mappings")
    for key in ("wavelength_nm", "core_diameter_mm", "numerical_aperture", "output_index"):
        if key not in source or not np.isfinite(float(source[key])):
            raise PumpConfigError(f"source.{key} must be finite")
    if float(source["wavelength_nm"]) <= 0.0:
        raise PumpConfigError("wavelength_nm must be positive")
    if not isinstance(source.get("seed"), int) or isinstance(source.get("seed"), bool):
        raise PumpConfigError("source.seed must be an integer")
    if not isinstance(source.get("n_rays"), int) or isinstance(source.get("n_rays"), bool):
        raise PumpConfigError("source.n_rays must be an integer")
    if source["n_rays"] <= 0:
        raise PumpConfigError("source.n_rays must be positive")
    if source.get("absolute_power_w") is not None:
        raise PumpConfigError("absolute_power_w must remain null until calibrated")

    try:
        l1 = _lens(optics["l1"])
        l2 = _lens(optics["l2"])
        target = optics["target"]
        beamline = BeamlineConfig(
            l1=l1,
            l2=l2,
            target_z_mm=float(target["z_mm"]),
            target_radius_mm=float(target["active_radius_mm"]),
            lens_clearance_mm=float(optics.get("lens_clearance_mm", 0.0)),
        )
        beamline.validate()
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise PumpConfigError(f"invalid optics geometry: {exc}") from exc

    try:
        source_n = int(source["n_rays"])
        source_seed = int(source["seed"])
        n_out = float(source["output_index"])
        na = float(source["numerical_aperture"])
        core = float(source["core_diameter_mm"])
    except (TypeError, ValueError, OverflowError) as exc:
        raise PumpConfigError(f"invalid source field: {exc}") from exc
    if core < 0 or na < 0 or n_out <= 0 or na > n_out:
        raise PumpConfigError("core diameter/NA/output index outside physical domain")
    angular = str(source.get("angular_distribution", ""))
    if angular not in ("uniform_solid_angle", "edge_biased_sin_theta"):
        raise PumpConfigError(f"unsupported angular_distribution {angular!r}")
    return Pump976Config(
        path=config_path, raw=raw, design_id=str(raw.get("design_id", "unknown")),
        wavelength_nm=float(source["wavelength_nm"]), core_diameter_mm=core,
        numerical_aperture=na, output_index=n_out, angular_distribution=angular,
        seed=source_seed, n_rays=source_n, absolute_power_w=None, beamline=beamline,
    )


def _lens(data: dict[str, Any]) -> ThinLensPlane:
    if not isinstance(data, dict):
        raise ValueError("lens config must be a mapping")
    lens = ThinLensPlane(
        focal_length_mm=float(data["focal_length_mm"]),
        z_mm=float(data["principal_z_mm"]),
        aperture_diameter_mm=float(data["diameter_mm"]),
        decenter_x_mm=float(data.get("decenter_x_mm", 0.0)),
        decenter_y_mm=float(data.get("decenter_y_mm", 0.0)),
        tilt_x_rad=float(data.get("tilt_x_rad", 0.0)),
        tilt_y_rad=float(data.get("tilt_y_rad", 0.0)),
    )
    lens.validate()
    return lens


def parse_pump_mapping(raw: dict[str, Any], *, path: str | Path = "<mapping>") -> Pump976Config:
    """Validate an in-memory config through the same schema as a file."""

    temp = Path(path)
    return _parse_pump_mapping(raw, temp)


def _parse_pump_mapping(raw: dict[str, Any], path: Path) -> Pump976Config:
    # Keep one validation implementation without creating a temporary file.
    # The YAML round trip preserves ordinary scalar/list/mapping values.
    import tempfile

    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".yaml", delete=False) as f:
        yaml.safe_dump(raw, f, sort_keys=False)
        temp_path = Path(f.name)
    try:
        loaded = load_pump976_config(temp_path)
        return Pump976Config(path=path, raw=raw, design_id=loaded.design_id,
                             wavelength_nm=loaded.wavelength_nm,
                             core_diameter_mm=loaded.core_diameter_mm,
                             numerical_aperture=loaded.numerical_aperture,
                             output_index=loaded.output_index,
                             angular_distribution=loaded.angular_distribution,
                             seed=loaded.seed, n_rays=loaded.n_rays,
                             absolute_power_w=loaded.absolute_power_w,
                             beamline=loaded.beamline)
    finally:
        temp_path.unlink(missing_ok=True)


def load_pump_tolerance_config(path: str | Path) -> PumpToleranceConfig:
    config_path = Path(path).resolve()
    if not config_path.is_file():
        raise PumpConfigError(f"tolerance config not found: {config_path}")
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise PumpConfigError(f"invalid tolerance YAML: {exc}") from exc
    if not isinstance(raw, dict) or str(raw.get("schema_version")) != "4.0":
        raise PumpConfigError("tolerance config requires schema_version '4.0'")
    if raw.get("case_id") != "pump976_g4_tolerance":
        raise PumpConfigError("case_id must be pump976_g4_tolerance")
    try:
        source = raw["source"]
        pre = raw["precheck"]
        holdout = raw["holdout"]
        rays = int(source["rays_per_assembly"])
        pre_n, pre_seed = int(pre["assemblies"]), int(pre["seed"])
        hold_n, hold_seed = int(holdout["assemblies"]), int(holdout["seed"])
        oat_seed = int(raw["oat_seed"])
        perturbations = raw["perturbations"]
    except (KeyError, TypeError, ValueError) as exc:
        raise PumpConfigError(f"incomplete tolerance config: {exc}") from exc
    if min(rays, pre_n, hold_n) <= 0:
        raise PumpConfigError("rays and assembly counts must be positive")
    if pre_seed == hold_seed:
        raise PumpConfigError("precheck and holdout seeds must be independent")
    if not isinstance(perturbations, dict) or not perturbations:
        raise PumpConfigError("perturbations must be a non-empty mapping")
    for name, spec in perturbations.items():
        if not isinstance(spec, dict) or spec.get("distribution") != "uniform":
            raise PumpConfigError(f"{name} must declare a uniform distribution")
        lower, upper = float(spec["lower"]), float(spec["upper"])
        if not np.isfinite(lower) or not np.isfinite(upper) or lower >= upper:
            raise PumpConfigError(f"{name} bounds must be finite and increasing")
        if spec.get("evidence") != "ASSUMED":
            raise PumpConfigError(f"{name} must remain labelled ASSUMED")
    return PumpToleranceConfig(
        path=config_path, raw=raw, rays_per_assembly=rays,
        precheck_assemblies=pre_n, precheck_seed=pre_seed,
        holdout_assemblies=hold_n, holdout_seed=hold_seed,
        oat_seed=oat_seed, perturbations=perturbations,
    )
