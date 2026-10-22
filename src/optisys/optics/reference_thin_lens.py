"""Independent paraxial reference for a thick singlet.

This module is deliberately **free of any Optiland import**.  It computes the
first-order (paraxial) behaviour of the same lens geometry using reduced-angle
matrices, so it can be used as an independent check of the ray-traced result.

Reduced angle convention
------------------------
Ray vector ``(y, n u)``; translation over distance ``d`` in index ``n``:

    T(d, n) = [[1, d/n], [0, 1]]

Refraction at a surface of power ``Phi = (n' - n) / R``:

    R(Phi)  = [[1, 0], [-Phi, 1]]

The system matrix of the two-surface element is ``M = R2 . T(t, n) . R1``.
For a ray entering parallel at height ``y`` the emergent reduced angle is
``C y``, hence ``EFL = -1/C`` and ``BFL = -A/C`` (measured from the rear
vertex).
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ThinLensReference:
    """First-order reference for an equiconvex singlet in air."""

    focal_length_mm: float
    aperture_mm: float
    thickness_mm: float
    index: float

    # -- geometry ------------------------------------------------------
    @property
    def radius_mm(self) -> float:
        """Equiconvex radius that gives the requested *thin-lens* focal length.

        Solved from ``1/f = (n-1)[2/R - (n-1) t / (n R^2)]``; see
        ``G2_SCIENTIFIC_ASSUMPTIONS.md`` section 2.1.
        """

        k = self.index - 1.0
        f = self.focal_length_mm
        t = self.thickness_mm
        n = self.index
        inner = 1.0 - t / (n * f)
        if inner < 0.0:
            raise ValueError(
                f"thickness {t} mm is too large for f={f} mm, n={n}: no real radius"
            )
        return float(k * f * (1.0 + np.sqrt(inner)))

    @property
    def system_matrix(self) -> np.ndarray:
        r = self.radius_mm
        n = self.index
        t = self.thickness_mm
        phi1 = (n - 1.0) / r
        phi2 = (1.0 - n) / (-r)
        r1 = np.array([[1.0, 0.0], [-phi1, 1.0]])
        r2 = np.array([[1.0, 0.0], [-phi2, 1.0]])
        trans = np.array([[1.0, t / n], [0.0, 1.0]])
        return r2 @ trans @ r1

    @property
    def efl_mm(self) -> float:
        return float(-1.0 / self.system_matrix[1, 0])

    @property
    def bfl_mm(self) -> float:
        m = self.system_matrix
        return float(-m[0, 0] / m[1, 0])

    @property
    def rear_principal_offset_mm(self) -> float:
        """Rear principal plane relative to the rear vertex (negative = inside)."""

        return float(self.bfl_mm - self.efl_mm)

    @property
    def front_principal_offset_mm(self) -> float:
        """Front principal plane relative to the front vertex (positive = inside)."""

        return float(-self.rear_principal_offset_mm)

    # -- imaging -------------------------------------------------------
    def sensor_distance_mm(self, focus_distance_mm: float) -> float:
        """Rear-vertex to sensor distance that focuses an object at ``focus_distance_mm``."""

        m = self.system_matrix
        a, b = m[0, 0], m[0, 1]
        c, d = m[1, 0], m[1, 1]
        z = float(focus_distance_mm)
        denominator = c * z + d
        if abs(denominator) < 1e-12:
            raise ValueError("degenerate conjugation (object at the front focal point)")
        return float(-(a * z + b) / denominator)

    def chief_image_mm(self, object_distance_mm: float, object_height_mm: float,
                       sensor_distance_mm: float) -> float:
        """Paraxial height of the chief ray at the sensor plane.

        The chief ray leaves the object point ``(h, -Z)`` and passes through
        the stop centre at the front vertex, so its angle at the lens plane is
        ``u = -h/Z`` and its height there is zero.  Propagating that ray through
        the element gives ``y' = u (B + d D)`` with ``(B, D)`` from the system
        matrix and ``d`` the rear-vertex-to-sensor distance.

        Using ``(h, 0)`` instead - a common slip - would make the image height
        independent of the object distance and is wrong.
        """

        m = self.system_matrix
        b, d = m[0, 1], m[1, 1]
        u = -float(object_height_mm) / float(object_distance_mm)
        return float(u * (b + sensor_distance_mm * d))

    def magnification(self, object_distance_mm: float,
                      sensor_distance_mm: float) -> float:
        m = self.system_matrix
        return float(m[0, 0] + sensor_distance_mm * m[1, 0])

    # -- pinhole limit -------------------------------------------------
    @staticmethod
    def pinhole_image_mm(object_distance_mm: float, object_height_mm: float,
                         focal_length_mm: float) -> float:
        """Ideal pinhole with the image plane at ``f``: y' = -f * h / Z.

        This is exactly the L0 contract ``u - cx = fx * B / Z`` (with a sign
        flip for the real image orientation).
        """

        return float(-focal_length_mm * object_height_mm / object_distance_mm)
