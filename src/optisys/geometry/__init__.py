"""Geometry package: coordinate frames, intersection, projection, inversion."""

from optisys.geometry.coplanar import (
    CoplanarGeometry,
    CoplanarSpec,
    ForwardBatch,
    ForwardResult,
    InverseBatch,
    InverseResult,
)

__all__ = [
    "CoplanarGeometry",
    "CoplanarSpec",
    "ForwardBatch",
    "ForwardResult",
    "InverseBatch",
    "InverseResult",
]
