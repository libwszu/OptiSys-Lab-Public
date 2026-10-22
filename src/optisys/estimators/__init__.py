"""Spot estimators with a uniform contract.

``build_estimators()`` returns the frozen G1 set of three algorithms.  The G2
area-integrated fitter is registered separately in ``build_estimators_g2()`` so
that adding it cannot change any G1 result or source-hash expectation.
"""

from optisys.estimators.base import EstimateResult
from optisys.estimators.centroid import CentroidEstimator
from optisys.estimators.gaussian_1d import Gaussian1DEstimator
from optisys.estimators.gaussian_2d import Gaussian2DEstimator
from optisys.estimators.gaussian_2d_integrated import Gaussian2DIntegratedEstimator

ESTIMATORS = (CentroidEstimator, Gaussian1DEstimator, Gaussian2DEstimator)
ESTIMATORS_G2 = (CentroidEstimator, Gaussian2DEstimator, Gaussian2DIntegratedEstimator)


def build_estimators() -> list:
    """Frozen G1 estimator set.  Never extended in place."""

    return [cls() for cls in ESTIMATORS]


def build_estimators_g2() -> list:
    """G2 set: G1 baseline plus the area-integrated fitter."""

    return [cls() for cls in ESTIMATORS_G2]


__all__ = [
    "EstimateResult",
    "CentroidEstimator",
    "Gaussian1DEstimator",
    "Gaussian2DEstimator",
    "Gaussian2DIntegratedEstimator",
    "build_estimators",
    "build_estimators_g2",
]
