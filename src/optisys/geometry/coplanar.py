"""Coplanar (2-D) laser-triangulation geometry.

Coordinate contract (PDF section 4.1, master prompt section 3.1)
---------------------------------------------------------------
* Right-handed frame, origin at the camera pinhole ``O = (0, 0, 0)``.
* Optical axis ``+Z``; lateral object-space axis ``+X``.
* Laser exit point ``(B, 0, 0)``; beam propagates toward ``+Z`` and is
  tilted toward ``-X`` by ``theta``.
* Target is a plane perpendicular to ``Z`` at depth ``Z > 0``.
* Virtual image plane *in front of* the pinhole (pinhole projection
  convention, no image flip).  Image-space lateral direction ``+u`` follows
  object-space ``+X``.  Real cameras may invert rows/columns; that requires
  a separate calibration and is NOT assumed here.

Equations
---------
``X_L(Z)  = B - Z * tan(theta)``
``fx      = f_mm / p_mm``                       [pixel]
``u(Z)    = cx + fx * (B / Z - tan(theta))``
``Z(u)    = fx * B / (u - cx + fx * tan(theta))``
``du/dZ   = -fx * B / Z**2``                    [pixel/mm]
``dZ/du   = -Z**2 / (fx * B)``                   [mm/pixel, signed]
``|dZ/du| =  Z**2 / (fx * B)``

The signed ``dZ/du`` is negative for ``B > 0``: the spot moves toward the
principal point as the target recedes.  PDF page 8, equation (3) prints the
magnitude with a positive sign; see ``docs/SPEC_DISCREPANCIES.md``.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from optisys.errors import STATUS_CODES, Status

_NAN = float("nan")


@dataclass(frozen=True)
class CoplanarSpec:
    """Fully resolved, unit-explicit geometry specification."""

    baseline_mm: float
    theta_rad: float
    fx_px: float
    cx_px: float
    cy_px: float
    width_px: int
    height_px: int
    z_min_mm: float
    z_max_mm: float
    min_baseline_mm: float = 1.0
    singular_denominator_px: float = 1.0e-6
    sensor_margin_px: float = 0.0
    enforce_working_range: bool = True
    #: Numerical guard at the working-range boundary (1 nm).  It absorbs
    #: round-off such as 300.00000000000006 mm; it is not a physical extension
    #: of the validated range.
    range_epsilon_mm: float = 1.0e-6

    def __post_init__(self) -> None:
        checks = {
            "baseline_mm": self.baseline_mm,
            "theta_rad": self.theta_rad,
            "fx_px": self.fx_px,
            "cx_px": self.cx_px,
            "cy_px": self.cy_px,
            "z_min_mm": self.z_min_mm,
            "z_max_mm": self.z_max_mm,
            "min_baseline_mm": self.min_baseline_mm,
            "singular_denominator_px": self.singular_denominator_px,
            "sensor_margin_px": self.sensor_margin_px,
            "range_epsilon_mm": self.range_epsilon_mm,
        }
        for name, value in checks.items():
            if not np.isfinite(value):
                raise ValueError(f"{name} must be finite, got {value!r}")
        if self.baseline_mm <= 0.0:
            raise ValueError("baseline_mm must be > 0; B -> 0 destroys triangulation")
        if self.min_baseline_mm <= 0.0:
            raise ValueError("min_baseline_mm must be > 0")
        if self.fx_px <= 0.0:
            raise ValueError("fx_px must be > 0")
        if self.z_min_mm <= 0.0 or self.z_max_mm <= self.z_min_mm:
            raise ValueError("require 0 < z_min_mm < z_max_mm")
        if abs(self.theta_rad) >= np.pi / 2.0:
            raise ValueError("|theta| must be < 90 deg for a forward intersection")
        if self.width_px < 2 or self.height_px < 2:
            raise ValueError("resolution must be at least 2x2 pixels")
        if self.singular_denominator_px <= 0.0:
            raise ValueError("singular_denominator_px must be > 0")
        if self.range_epsilon_mm < 0.0:
            raise ValueError("range_epsilon_mm must be >= 0")

    @property
    def tan_theta(self) -> float:
        return float(np.tan(self.theta_rad))


@dataclass(frozen=True)
class ForwardResult:
    """Result of ``forward(Z)``.

    ``u_px``/``X_mm`` may still be finite diagnostics when ``status`` is a
    failure (e.g. ``OUT_OF_SENSOR``); only ``status is OK`` makes them a
    valid projection.
    """

    Z_mm: float
    X_mm: float
    u_px: float
    v_px: float
    visible: bool
    status: Status
    message: str


@dataclass(frozen=True)
class InverseResult:
    """Result of ``inverse(u)``.

    ``Z_mm`` and ``dZ_du_mm_per_px`` are ``nan`` unless ``status is OK``.
    ``candidate_Z_mm`` keeps the algebraically computed value for diagnostics
    (never use it as a measurement).
    """

    u_px: float
    Z_mm: float
    candidate_Z_mm: float
    dZ_du_mm_per_px: float
    abs_sensitivity_mm_per_px: float
    status: Status
    message: str


@dataclass(frozen=True)
class ForwardBatch:
    """Vectorised forward result."""

    Z_mm: np.ndarray
    X_mm: np.ndarray
    u_px: np.ndarray
    v_px: np.ndarray
    visible: np.ndarray
    status_code: np.ndarray

    def statuses(self) -> list[Status]:
        from optisys.errors import CODE_TO_STATUS

        return [CODE_TO_STATUS[int(code)] for code in self.status_code]


@dataclass(frozen=True)
class InverseBatch:
    """Vectorised inverse result."""

    u_px: np.ndarray
    Z_mm: np.ndarray
    candidate_Z_mm: np.ndarray
    dZ_du_mm_per_px: np.ndarray
    status_code: np.ndarray

    def statuses(self) -> list[Status]:
        from optisys.errors import CODE_TO_STATUS

        return [CODE_TO_STATUS[int(code)] for code in self.status_code]


class CoplanarGeometry:
    """Ideal pinhole, single-point, coplanar triangulation model (L0)."""

    def __init__(self, spec: CoplanarSpec) -> None:
        self.spec = spec
        self._u_min = float(spec.sensor_margin_px)
        self._u_max = float(spec.width_px - 1) - float(spec.sensor_margin_px)

    # ------------------------------------------------------------------
    # Scalar API
    # ------------------------------------------------------------------
    def forward(self, Z_mm: float) -> ForwardResult:
        """Project the laser spot at depth ``Z_mm`` onto the sensor.

        For ``OUT_OF_RANGE``/``OUT_OF_SENSOR`` the returned ``X_mm``/``u_px``
        are geometric diagnostics only; ``status is OK`` is required for the
        projection to count as valid.
        """

        spec = self.spec
        Z = float(Z_mm)

        if not np.isfinite(Z):
            return ForwardResult(Z, _NAN, _NAN, spec.cy_px, False, Status.NONFINITE_INPUT,
                                 "Z must be finite")
        if Z <= 0.0:
            return ForwardResult(Z, _NAN, _NAN, spec.cy_px, False, Status.INVALID_DEPTH,
                                 "Z must be > 0 (target behind the pinhole)")
        if spec.baseline_mm < spec.min_baseline_mm:
            return ForwardResult(Z, _NAN, _NAN, spec.cy_px, False, Status.BASELINE_DEGENERATE,
                                 f"baseline {spec.baseline_mm} mm < minimum {spec.min_baseline_mm} mm")

        X = spec.baseline_mm - Z * spec.tan_theta
        u = spec.cx_px + spec.fx_px * (spec.baseline_mm / Z - spec.tan_theta)

        if spec.enforce_working_range and not (
            spec.z_min_mm - spec.range_epsilon_mm <= Z <= spec.z_max_mm + spec.range_epsilon_mm
        ):
            return ForwardResult(Z, X, u, spec.cy_px, False, Status.OUT_OF_RANGE,
                                 f"Z outside working range [{spec.z_min_mm}, {spec.z_max_mm}] mm")

        if not self._inside_sensor(u):
            return ForwardResult(Z, X, u, spec.cy_px, False, Status.OUT_OF_SENSOR,
                                 f"u={u:.6f} px outside sensor [{self._u_min}, {self._u_max}] px")
        return ForwardResult(Z, X, u, spec.cy_px, True, Status.OK, "ok")

    def inverse(self, u_px: float) -> InverseResult:
        """Invert a measured spot column ``u_px`` into depth ``Z``."""

        spec = self.spec
        u = float(u_px)

        if not np.isfinite(u):
            return InverseResult(u, _NAN, _NAN, _NAN, _NAN, Status.NONFINITE_INPUT,
                                 "u must be finite")
        if spec.baseline_mm < spec.min_baseline_mm:
            return InverseResult(u, _NAN, _NAN, _NAN, _NAN, Status.BASELINE_DEGENERATE,
                                 f"baseline {spec.baseline_mm} mm < minimum {spec.min_baseline_mm} mm")

        denom = u - spec.cx_px + spec.fx_px * spec.tan_theta
        if not np.isfinite(denom) or abs(denom) < spec.singular_denominator_px:
            return InverseResult(u, _NAN, _NAN, _NAN, _NAN, Status.SINGULAR_GEOMETRY,
                                 f"|u - cx + fx*tan(theta)| = {abs(denom):.3e} px below threshold")

        candidate = spec.fx_px * spec.baseline_mm / denom
        if not np.isfinite(candidate) or candidate <= 0.0:
            return InverseResult(u, _NAN, candidate, _NAN, _NAN, Status.INVALID_DEPTH,
                                 "denominator sign implies Z <= 0")
        if spec.enforce_working_range and not (
            spec.z_min_mm - spec.range_epsilon_mm <= candidate
            <= spec.z_max_mm + spec.range_epsilon_mm
        ):
            return InverseResult(u, _NAN, candidate, _NAN, _NAN, Status.OUT_OF_RANGE,
                                 f"Z={candidate:.6f} mm outside [{spec.z_min_mm}, {spec.z_max_mm}] mm")

        # A spot column outside the physical chip cannot be a valid measurement,
        # even when the implied depth happens to fall inside the working range.
        # Ordering mirrors forward(): range first, then sensor bounds.
        if not self._inside_sensor(u):
            return InverseResult(
                u, _NAN, candidate, _NAN, _NAN, Status.OUT_OF_SENSOR,
                f"u={u:.6f} px outside sensor [{self._u_min}, {self._u_max}] px "
                f"(implied Z={candidate:.6f} mm is inside the working range)",
            )

        dZ_du = -candidate ** 2 / (spec.fx_px * spec.baseline_mm)
        return InverseResult(u, candidate, candidate, dZ_du, abs(dZ_du), Status.OK, "ok")

    def du_dZ(self, Z_mm: float) -> float:
        """Analytic signed ``du/dZ`` in pixel/mm (negative for B > 0)."""

        Z = float(Z_mm)
        if not np.isfinite(Z) or Z <= 0.0:
            raise ValueError("du_dZ requires a finite Z > 0")
        return -self.spec.fx_px * self.spec.baseline_mm / (Z * Z)

    def dZ_du(self, Z_mm: float) -> float:
        """Analytic signed ``dZ/du`` in mm/pixel (negative for B > 0)."""

        Z = float(Z_mm)
        if not np.isfinite(Z) or Z <= 0.0:
            raise ValueError("dZ_du requires a finite Z > 0")
        return -Z * Z / (self.spec.fx_px * self.spec.baseline_mm)

    def abs_sensitivity(self, Z_mm: float) -> float:
        """Absolute depth sensitivity ``|dZ/du|`` in mm/pixel."""

        return abs(self.dZ_du(Z_mm))

    # ------------------------------------------------------------------
    # Vectorised API (no Python loops)
    # ------------------------------------------------------------------
    def forward_many(self, Z_mm: np.ndarray | float) -> ForwardBatch:
        spec = self.spec
        Z = np.asarray(Z_mm, dtype=float)
        shape = Z.shape

        status = np.full(shape, STATUS_CODES[Status.OK], dtype=np.int8)
        u = np.full(shape, np.nan)
        X = np.full(shape, np.nan)
        v = np.full(shape, spec.cy_px)

        finite = np.isfinite(Z)
        positive = finite & (Z > 0.0)
        safe_z = np.where(positive, Z, 1.0)

        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            X_calc = spec.baseline_mm - safe_z * spec.tan_theta
            u_calc = spec.cx_px + spec.fx_px * (spec.baseline_mm / safe_z - spec.tan_theta)

        X = np.where(positive, X_calc, np.nan)
        u = np.where(positive, u_calc, np.nan)

        if spec.baseline_mm < spec.min_baseline_mm:
            status[:] = STATUS_CODES[Status.BASELINE_DEGENERATE]
        else:
            status[~finite] = STATUS_CODES[Status.NONFINITE_INPUT]
            status[finite & ~positive] = STATUS_CODES[Status.INVALID_DEPTH]
            if spec.enforce_working_range:
                outside = positive & (
                    (Z < spec.z_min_mm - spec.range_epsilon_mm)
                    | (Z > spec.z_max_mm + spec.range_epsilon_mm)
                )
                status[outside] = STATUS_CODES[Status.OUT_OF_RANGE]
            out_sensor = (status == STATUS_CODES[Status.OK]) & (u < self._u_min)
            out_sensor |= (status == STATUS_CODES[Status.OK]) & (u > self._u_max)
            status[out_sensor] = STATUS_CODES[Status.OUT_OF_SENSOR]

        visible = status == STATUS_CODES[Status.OK]
        return ForwardBatch(Z, X, u, np.full(shape, spec.cy_px), visible, status)

    def inverse_many(self, u_px: np.ndarray | float) -> InverseBatch:
        spec = self.spec
        u = np.asarray(u_px, dtype=float)
        shape = u.shape

        status = np.full(shape, STATUS_CODES[Status.OK], dtype=np.int8)
        candidate = np.full(shape, np.nan)
        Z = np.full(shape, np.nan)
        dZ_du = np.full(shape, np.nan)

        finite = np.isfinite(u)
        denom = np.where(finite, u - spec.cx_px + spec.fx_px * spec.tan_theta, np.nan)
        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            cand = spec.fx_px * spec.baseline_mm / denom

        good_denom = finite & np.isfinite(denom) & (np.abs(denom) >= spec.singular_denominator_px)
        candidate = np.where(good_denom, cand, np.nan)

        if spec.baseline_mm < spec.min_baseline_mm:
            status[:] = STATUS_CODES[Status.BASELINE_DEGENERATE]
        else:
            status[~finite] = STATUS_CODES[Status.NONFINITE_INPUT]
            status[finite & ~good_denom] = STATUS_CODES[Status.SINGULAR_GEOMETRY]
            bad_depth = (status == STATUS_CODES[Status.OK]) & (
                ~np.isfinite(candidate) | (candidate <= 0.0)
            )
            status[bad_depth] = STATUS_CODES[Status.INVALID_DEPTH]
            if spec.enforce_working_range:
                out_range = (status == STATUS_CODES[Status.OK]) & (
                    (candidate < spec.z_min_mm - spec.range_epsilon_mm)
                    | (candidate > spec.z_max_mm + spec.range_epsilon_mm)
                )
                status[out_range] = STATUS_CODES[Status.OUT_OF_RANGE]

            out_sensor = (status == STATUS_CODES[Status.OK]) & (
                (u < self._u_min) | (u > self._u_max)
            )
            status[out_sensor] = STATUS_CODES[Status.OUT_OF_SENSOR]

        ok = status == STATUS_CODES[Status.OK]
        Z = np.where(ok, candidate, np.nan)
        dZ_du = np.where(ok, -Z * Z / (spec.fx_px * spec.baseline_mm), np.nan)
        return InverseBatch(u, Z, candidate, dZ_du, status)

    # ------------------------------------------------------------------
    def _inside_sensor(self, u_px: float) -> bool:
        return bool(self._u_min <= u_px <= self._u_max)
