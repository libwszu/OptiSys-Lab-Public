"""Scene execution for one (assembly, distance, condition, repeat).

This is the only place where optics, sensor and estimators meet.  It never
uses ``Z_gt`` inside estimation: the ground truth leaves this module only as a
scoring field.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np

from optisys.config_g2 import ResolvedG2Config
from optisys.config_g1 import ConditionSpec, SensorSpec
from optisys.errors import Status
from optisys.estimators import build_estimators_g2
from optisys.imaging.roi import detect_roi
from optisys.imaging.sensor import stable_seed
from optisys.imaging.sensor_g2 import render_frame_g2
from optisys.optics.optical_image_contract import (
    CameraGeometry,
    L1OpticalModel,
    SIGNAL_MODE_BUDGET,
)
from optisys.optics.psf_or_footprint import KernelSpec
from optisys.tolerance.perturbations import AssemblyState


@dataclass
class SceneOutcome:
    z_gt_mm: float
    z_commanded_mm: float
    condition: str
    assembly_id: str
    repeat: int
    seed: int
    u_gt_px: float
    v_gt_px: float
    optical_status: str
    cloud_status: str
    capture_fraction: float
    ray_success_fraction: float
    kernel_support: float
    transmitted_fraction: float
    peak_expected_e: float
    expected_sum_e: float
    saturation_full_well: float
    saturation_adc: float
    roi_status: str
    roi: tuple[int, int, int, int] | None
    estimates: dict[str, dict[str, Any]]
    #: Filled only when ``run_scene(..., return_frame=True)`` is requested.
    #: Gate runs leave it ``None`` so the per-frame array is never retained
    #: across the 126 000-row panel.
    image_adu: Any | None = None


class SceneRunner:
    """Builds (and caches) one optical model per assembly."""

    def __init__(self, config: ResolvedG2Config, *, estimators: list | None = None,
                 max_cached_models: int = 24) -> None:
        self.config = config
        self.camera = CameraGeometry(
            width_px=config.width_px, height_px=config.height_px,
            pixel_size_mm=config.pixel_size_mm, cx_px=config.cx_px, cy_px=config.cy_px,
        )
        self.kernel_spec = KernelSpec(
            subpixel=config.optics.psf.subpixel,
            max_half_px=config.optics.psf.max_half_px,
            airy_radius_margin=config.optics.psf.airy_radius_margin,
            include_airy=config.optics.psf.kind != "geometric_footprint",
        )
        self.estimators = estimators if estimators is not None else build_estimators_g2()
        self._models: dict[str, L1OpticalModel] = {}
        self._order: list[str] = []
        self._max = max_cached_models
        self.scene_count = 0

    # ------------------------------------------------------------------
    def model_for(self, assembly: AssemblyState) -> L1OpticalModel:
        key = assembly.perturbation.signature() if assembly.perturbation else assembly.assembly_id
        model = self._models.get(key)
        if model is not None:
            return model
        if len(self._order) >= self._max:
            oldest = self._order.pop(0)
            self._models.pop(oldest, None)
        model = L1OpticalModel(
            self.camera,
            assembly.lens(self.config),
            kernel_spec=self.kernel_spec,
            signal_mode=self.config.imaging.signal_mode,
            reference_electrons=self.config.imaging.reference_electrons,
            reference_distance_mm=self.config.imaging.reference_distance_mm,
            reference_aperture_mm=self.config.imaging.reference_aperture_mm,
        )
        self._models[key] = model
        self._order.append(key)
        return model

    def scene_electrons(self, distance_mm: float, condition: ConditionSpec) -> float:
        base = condition.total_electrons
        if self.config.imaging.signal_mode == SIGNAL_MODE_BUDGET:
            scale = (self.config.imaging.reference_distance_mm / float(distance_mm)) ** 2
            return float(base * scale)
        return float(base)

    # ------------------------------------------------------------------
    def run_scene(self, assembly: AssemblyState, distance_mm: float,
                  condition: ConditionSpec, repeat: int, *,
                  seed_namespace: str = "G2",
                  collect_estimates: bool = True,
                  return_frame: bool = False) -> SceneOutcome:
        distance = float(distance_mm)
        object_height = assembly.object_height_mm(distance)
        model = self.model_for(assembly)
        electrons = self.scene_electrons(distance, condition)
        optical = model.image(distance, object_height, total_electrons=electrons)

        scene_key = f"{seed_namespace}|{assembly.assembly_id}|{distance:07.2f}|{condition.name}|{repeat:02d}"
        seed = stable_seed(self.config.run.seed, scene_key)
        sensor = SensorSpec(
            read_noise_e=condition.read_noise_e,
            dark_rate_e_per_s=self.config.sensor.dark_rate_e_per_s,
            exposure_ms=self.config.sensor.exposure_ms,
            full_well_e=self.config.sensor.full_well_e,
            bit_depth=self.config.sensor.bit_depth,
            e_per_adu=self.config.sensor.e_per_adu,
            black_level_adu=self.config.sensor.black_level_adu,
            adc_max_adu=self.config.sensor.adc_max_adu,
        )

        estimates: dict[str, dict[str, Any]] = {}
        if optical.status not in (Status.OK, Status.OUT_OF_SENSOR_PARTIAL):
            frame_flags = (optical.status.value,)
            return SceneOutcome(
                z_gt_mm=distance, z_commanded_mm=distance, condition=condition.name,
                assembly_id=assembly.assembly_id, repeat=repeat, seed=seed,
                u_gt_px=float("nan"), v_gt_px=float("nan"),
                optical_status=optical.status.value, cloud_status="NO_IMAGE",
                capture_fraction=optical.capture_fraction,
                ray_success_fraction=float(optical.ray_success_fraction or 0.0),
                kernel_support=float(optical.support_fraction or 0.0),
                transmitted_fraction=float(optical.transmitted_energy_fraction or 0.0),
                peak_expected_e=0.0, expected_sum_e=0.0,
                saturation_full_well=0.0, saturation_adc=0.0,
                roi_status="NOT_RUN", roi=None,
                estimates={name: {
                    "u_hat_px": None, "v_hat_px": None, "status": optical.status.value,
                    "flags": frame_flags, "sigma_px": None, "fit_rms_e": None,
                    "snr_proxy": None, "runtime_ms": 0.0,
                } for name in ("centroid", "gaussian_1d", "gaussian_2d")},
            )

        frame = render_frame_g2(
            optical.expected_signal_e, condition.background_e_per_px, sensor, seed
        )
        roi = detect_roi(frame.image_adu, sensor)
        self.scene_count += 1
        if collect_estimates:
            for estimator in self.estimators:
                result = estimator.estimate(frame.image_adu, roi.roi, sensor)
                estimates[estimator.name] = {
                    "u_hat_px": result.u_hat_px,
                    "v_hat_px": result.v_hat_px,
                    "status": result.status.value,
                    "flags": tuple(result.flags),
                    "sigma_px": (result.quality or {}).get("sigma_px"),
                    "fit_rms_e": result.residual_rms_e,
                    "snr_proxy": (result.quality or {}).get("snr_proxy"),
                    "runtime_ms": result.runtime_ms,
                    "roi_touches_border": (result.quality or {}).get("roi_touches_border"),
                }

        return SceneOutcome(
            z_gt_mm=distance, z_commanded_mm=distance, condition=condition.name,
            assembly_id=assembly.assembly_id, repeat=repeat, seed=seed,
            u_gt_px=float(optical.spot_center_px[0]),
            v_gt_px=float(optical.spot_center_px[1]),
            optical_status=optical.status.value,
            cloud_status="OK",
            capture_fraction=float(optical.capture_fraction),
            ray_success_fraction=float(optical.ray_success_fraction or 0.0),
            kernel_support=float(optical.support_fraction or 0.0),
            transmitted_fraction=float(optical.transmitted_energy_fraction or 0.0),
            peak_expected_e=float(optical.diagnostics.get("expected_peak_e", 0.0)),
            expected_sum_e=float(optical.diagnostics.get("expected_sum_e", 0.0)),
            saturation_full_well=float(frame.full_well_saturation_fraction),
            saturation_adc=float(frame.adc_clipping_fraction),
            roi_status=roi.status.value,
            roi=roi.roi,
            estimates=estimates,
            image_adu=(frame.image_adu if return_frame else None),
        )

    def signature_of(self, assembly: AssemblyState) -> dict[str, Any]:
        model = self.model_for(assembly)
        return {
            "assembly_id": assembly.assembly_id,
            "optical_config_hash": model.optical_config_hash,
            "lens": assembly.lens(self.config).describe(),
        }
