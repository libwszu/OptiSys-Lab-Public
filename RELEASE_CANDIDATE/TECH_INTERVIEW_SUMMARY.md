# Technical interview summary

Built a reproducible optical simulation platform spanning a laser-triangulation measurement chain and a separate 976 nm multimode pump-path model. Added an independent global-coordinate sphere-intersection and vector-Snell reference and cross-checked 32,768 assumed P1 surface events at NA 0.22; maximum surface-coordinate component difference was `1.42e-13 mm` against Optiland 0.6.3.

Within the assumed model, identified pupil-dependent longitudinal focus shift as the main explanation for the G4 high-angle target misses. A same-clear-aperture, fixed-target L2 position search produced a simulated capture trade-off from `66.09%` to `87.06%` on a 4,096-ray holdout; the paired ray-bootstrap 95% interval was `[+19.73,+22.19]` percentage points. This interval reflects ray sampling only, not mechanical assembly tolerance.

The platform has no measured source profile or absolute power, no vendor lens drawings and no validated Er:YAP dimensions. No experimental or manufacturing performance is claimed.
