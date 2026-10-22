# OptiSys-Lab Stage 5 engineering report

Run ID: `20261020_210201_S5_HNA`  
Evidence: `SIMULATED / ASSUMED P1 MODEL`  
S5-A: `PASS` · S5-B: `EXPLAINED_WITH_SCOPE` · S5-C: `P1_SUPPORTED_TRADEOFF`

## Executive result

The independent global sphere/Snell reference replayed 4,096 source rays for each G4 design across four lens faces. Maximum surface coordinate component delta was `1.421e-13 mm`; maximum surface outgoing-direction component delta was `1.887e-15`. Target outcomes, source-weight ledgers and Optiland surface classifications matched.

At the original assumed 1 mm circle, P1 baseline capture was `0.681885` with conditional `r90=0.847725 mm`; the G4 P1 candidate was `0.675049` with conditional `r90=0.843407 mm`. No ray was aperture-blocked or lost to a trace failure; misses are outside this assumed receiving region.

## Model-level explanation

Within the assumed P1 geometry, the nominal 1 mm-target miss is consistent with pupil-dependent longitudinal spherical aberration: the outer sampled L2 pupil bands have a shorter closest-axis focus than the inner pupil, and the registered -25 mm target-plane sensitivity recovers capture. No ray is lost at a lens aperture or in tracing. This is a geometric model diagnosis, not measured lens performance or a hardware prescription. The -25 mm point is the lower edge of the registered focus grid, so the exact optimum was not bracketed.

## Equal-aperture candidate

L2 moved from z=125 to z=135 mm while both clear apertures, glass, focal lengths, center thicknesses and the z=225 mm / r=1 mm target stayed fixed. Independent holdout capture changed from `0.660889` to `0.870605`; paired ray bootstrap 95% interval `[+0.1973, +0.2219]`. This is a nominal ray-sampling interval, not an assembly-tolerance result.

## Limits

No measured source profile, absolute source power, vendor lens drawing, actual outer diameter, coating, decenter/tilt, crystal dimension, absorption, thermal response or experiment is available. Do not interpret geometric weight as watts, efficiency or W/mm².

## Figures and data

All figures are backed by CSV evidence in this run. Source-weight denominators are retained.
