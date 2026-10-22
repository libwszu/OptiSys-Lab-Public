# Stage 5 acceptance criteria (frozen before new scientific results)

Run ID: `20261020_210201_S5_HNA`

Stage 5 is an optional post-G4 reliability and portfolio extension. It is not a new mandatory PDF gate and does not replace any G2/G4 status.

## Evidence and status rules

- Every S5-generated optical output is `SIMULATED` under an `ASSUMED` centered-spherical-singlet model. Source absolute power, actual crystal dimensions, vendor lens parts, coatings, and measured spots remain unknown.
- G2 remains `QUALIFIED_ONLY`; G4 optical science remains `QUALIFIED`; G4 overall design claim remains `NO_SUPPORTED_IMPROVEMENT`.
- Engineering execution, reference validation, cause diagnosis, design comparison, portfolio, empirical status, and audit status are separate fields. No aggregate `ALL_PASS` state is permitted.
- The P1 design may only be called cross-checked within the assumed model when the independent sphere/Snell implementation meets the gates below. No simulation result is a manufacturing or experimental claim.

## Frozen numerical gates

For ordinary, non-tangent rays:

- Absolute sphere residual `abs(norm(hit - center) - abs(radius)) <= 1e-8 mm`.
- Independent-reference versus Optiland surface intersection maximum absolute coordinate delta `<= 1e-8 mm`.
- Surface exit unit-direction maximum component delta `<= 1e-9`.
- Target-plane x/y maximum absolute delta `<= 1e-6 mm`.
- Input direction norm error `<= 1e-12`; positive finite source weights; sum of source weights within `1e-12` of 1 for normalized evidence bundles.
- Exactly one terminal outcome per source ray. Weighted ledger closure `abs(residual) <= 1e-10` of source weight.
- Aperture inclusion uses `x*x + y*y <= semi_aperture**2 + 1e-12 mm**2`; target-circle inclusion uses the same squared-radius tolerance.
- An intersection discriminant within `1e-12 * max(radius**2, 1)` of zero, or Snell `k` within `1e-12` of zero, is flagged `ILL_CONDITIONED` and reported separately; it cannot be mixed into ordinary-ray percentiles.

Terminal outcomes are mutually exclusive: `CAPTURED`, `OUTSIDE_TARGET`, `APERTURE_BLOCKED_L1`, `APERTURE_BLOCKED_L2`, `NO_INTERSECTION`, `TIR_OR_REFRACTION_FAILURE`, `TRACE_FAILED`, and `INVALID_SOURCE`. Ill-conditioning is an orthogonal diagnostic flag. Invalid weights/configurations are rejected before tracing.

`S5_A_REFERENCE_VERIFICATION=PASS` requires all 4,096 original NA=0.22 source rays for both G4 designs to have independent surface records and an Optiland comparison at all four lens surfaces, no ordinary-ray tolerance breach, matching aperture/target outcomes, mutually exclusive ledger closure, and explicit negative controls. `QUALIFIED` means useful matched scope exists but full surface or angle coverage is unavailable. Any reproducible unexplained discrepancy is `FAIL`.

## Frozen sampling and analysis plan

- S5-A: replay all 4,096 source rows from the immutable G4 run, for both G4 designs; all source rows and surface records are retained. Preserve ray IDs, input states, weights, and the fixed `NA=0.22`, seed `976051` source.
- Angle bins in degrees are `[0,3)`, `[3,6)`, `[6,9)`, `[9,11)`, `[11,12.7099]`; exact final boundary is closed. Denominator is all attempted source weight in each bin.
- Radius-by-surface marginal bins are normalized semi-aperture fractions `[0,.25)`, `[.25,.50)`, `[.50,.75)`, `[.75,1]`; source near-field radius uses four equal-weight quantile bins; azimuth uses eight equal-width bins on `[-pi, pi)`. Each table records attempted weight and the weights reaching the surface.
- Sensitivity sources use `NA=0.05` and `0.22`, with `uniform_solid_angle` and `edge_biased_sin_theta` only where geometrically defined, each at `n=4096` and declared seed. These are source-model sensitivities, not physical source measurements.
- Focus offsets are frozen at `[-25,-10,0,+10,+25] mm` relative to each as-built target z (`225 mm` baseline, `235 mm` G4 candidate). Original planes remain the named fixed-target baseline. Focus results are sensitivities, not post-hoc redesign.
- Target scenarios are circles with radii `[0.5,1.0,1.5,2.0] mm` and a `2 x 2 mm` square. These are assumed receiving regions. Source-weight-normalized encircled curves use radii `0.00..2.00 mm` in `0.05 mm` increments. Failed or aperture-blocked rays remain in the denominator and have no invented image point.
- Mechanical geometry reports both lens surfaces, sag, clear aperture, center thickness, calculated edge thickness, and `t_edge <= 0` invalid geometry. `0 < t_edge < 0.5 mm` is a low-edge-thickness exploration warning only, not a vendor acceptance standard. Clear aperture is not treated as part outer diameter.

## Conditional S5-C design gate, frozen before data

S5-C may run only after S5-A passes and S5-B outputs exist. The equal-aperture search keeps N-BK7, 2 mm center thickness, L1 `f=25 mm / principal z=25 mm / clear aperture 12 mm`, L2 `f=100 mm / clear aperture 12 mm`, target circle radius `1 mm` at fixed `z=225 mm`, and varies only L2 principal z over `[115,120,125,130,135] mm` (90–110 mm lens spacing). Search uses 512 rays with seed `976052`; baseline is included. The best search design is selected by source-denominated fixed-target capture, ties resolved by smaller absolute focus shift and then smaller L2 z. Independent holdout uses 4,096 rays with seed `976053`. Common ray IDs are paired. The gain claim needs the frozen 5,000-replicate ray bootstrap (seed `976054`), nonzero 95% interval for paired capture difference, reference agreement, and disclosed axial-motion strategy. This is a nominal ray-sampling comparison, not an assembly-tolerance validation; no P1 tolerance claim is permitted.

If the scientific gate, material agreement, geometry validity, holdout, or compute gate fails, record `S5_C_DESIGN_STATUS=NOT_RUN_DUE_TO_SCIENTIFIC_GATE` or `NOT_COMPARABLE` with the reason. A no-gain result is valid.

## Engineering and audit gates

- Full current pytest suite must be executed; report passed, failed, errors, skipped, exit code, outer wall and JUnit suite time separately. Any skip is individually explained and cannot count as a pass.
- Run reduced main-case and pump-case CLI examples with captured stdout/stderr and exit status. Execute all six Streamlit page scripts with AppTest, and separately launch a real `streamlit run app/main.py`; verify `/_stcore/health == ok`, root HTTP 200, process stop, and port release.
- Browser E2E, screenshot, and video are separate deliverables. If unavailable, mark `NOT_AVAILABLE` / `NOT_DELIVERED`; do not synthesize browser evidence.
- Audit ZIP must remain below 40 MB unless the complete evidence requires more; every ordinary member is SHA-256/byte-count covered, paths are safe, manifest coverage is exact, standalone extraction replay passes, and a changed evidence CSV is rejected.
- No remote push, public release, third-party upload, or experiment is in scope.
