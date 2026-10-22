# Stage 5 high-NA diagnosis

Run ID: `20261020_210201_S5_HNA`  
Evidence level: `SIMULATED / ASSUMED P1 MODEL`  
Scope: centered, 2 mm center-thickness, equiconvex N-BK7 singlets from the frozen G4 geometry; no vendor part, coating, decenter/tilt, measured source profile, or absolute power.

## Reference verdict

The independent implementation uses global-coordinate sphere intersections and a vector Snell law. It reads the frozen G4 optical model, source rows, and design configuration. It does not call Optiland for intersections/refractions.

For both designs, all 4,096 original `NA=0.22` rays were traced through the four physical lens faces. The 32,768 surface rows and 8,192 final-ray rows are retained in the S5 run evidence. Independent surface positions agree with Optiland to a maximum coordinate component difference of `1.4210854715202004e-13 mm`; outgoing directions agree to `1.887379141862766e-15`. Final target coordinates agree to a maximum of `3.4638958368304884e-14 mm`. There were zero surface-classification or terminal-outcome mismatches, zero aperture blocks, zero refraction failures, and a zero source-weight ledger residual for both designs. The SCHOTT N-BK7 Sellmeier index at 976 nm also matches the installed Optiland 0.6.3 catalog value `1.5078427267710073`.

**S5-A: `PASS` within this assumed P1 model.** This establishes implementation agreement for the declared surfaces, coordinates, material and rays. It does not establish that the assumed singlets match a manufactured lens.

## Where the high-angle difference appears

| Launch angle | Rays | P0 baseline/candidate capture within angle | P1 baseline capture | P1 G4 candidate capture |
|---|---:|---:|---:|---:|
| 0–3° | 234 | 100% / 100% | 100% | 100% |
| 3–6° | 706 | 100% / 100% | 100% | 100% |
| 6–9° | 1,181 | 100% / 100% | 100% | 100% |
| 9–11° | 1,000 | 100% / 100% | 67.2% | 64.4% |
| 11–12.7099° | 975 | 100% / 100% | 0% | 0% |

The denominator is each angle bin's total source weight. Across all 4,096 rays, P1 capture at the original assumed 1 mm circular target is `0.681884765625` for baseline and `0.675048828125` for the G4 candidate. Every uncaptured ray reaches the target plane outside the assumed circle: no ray is aperture-blocked, and no trace failed. These are geometric receiving-region misses, not measured power losses.

P0's full capture across launch angles is consistent with its ideal thin-lens conjugate model. That angular cancellation is a property of P0 and is not, by itself, evidence of a bug. It cannot be used as evidence for real singlets.

## Model-level mechanism

The registered focus scan kept the optics fixed and moved only the modeled receiving plane by `[-25,-10,0,+10,+25] mm` relative to each original target plane. At the registered `-25 mm` boundary, both P1 designs capture 100% of source weight inside the assumed 1 mm circle; conditional `r90` is `0.56398 mm` for baseline and `0.83073 mm` for the G4 candidate. At the original planes, capture is `68.19%` / `67.50%`.

The L2-rear ray exit states show a decreasing closest-axis focus location with increasing sampled pupil radius. The weighted median shifts from `221.59 mm` in the inner baseline pupil band to `202.62 mm` in the outer sampled band; the G4 candidate shifts from `233.68 mm` to `219.18 mm`. This is consistent with longitudinal spherical aberration moving marginal-ray focus forward in the assumed singlet model. Because the best registered capture occurs at the lower focus-grid boundary, the precise best focus was not bracketed.

**S5-B: `EXPLAINED_WITH_SCOPE`.** Within the assumed P1 geometry, the dominant modeled effect is pupil-dependent longitudinal focus spread relative to the fixed target plane, not aperture clipping. This is a geometric diagnosis, not a wavefront Seidel coefficient, measured lens performance, or instruction to move a physical crystal.

## Receiving-region and source sensitivities

At the original target planes, independent P1 baseline/candidate source-weight capture is `43.41% / 43.63%` for a 0.5 mm circle, `68.19% / 67.50%` for a 1 mm circle, `85.30% / 84.79%` for a 1.5 mm circle, and `99.10% / 99.02%` for a 2 mm circle. The assumed 2 x 2 mm square gives `72.53% / 71.66%`; shape and size are not interchangeable.

With the baseline lens unchanged and a separate seed `976061`, P1 capture is `100%` at `NA=0.05`, `65.97%` for `NA=0.22` uniform solid angle, and `54.49%` for the `NA=0.22` edge-biased angular sensitivity. Those changes are source-model sensitivities, not lens-design gains.

For all rays that reach the original target plane, P1 axis-centered encircled-weight `r90` is `1.61392 mm` / `1.64643 mm` for baseline / G4 candidate. Conditional `r90` among rays inside the 1 mm circle is `0.84773 mm` / `0.84341 mm`. Both measures and their different denominators are reported separately.

## Mechanical screen

The spherical sag calculation gives G4 baseline L1 edge thickness `0.54169 mm`, baseline L2 `1.64406 mm`, G4 candidate L1 `0.15819 mm`, and candidate L2 `1.28502 mm`. All computed edges are positive; candidate L1 receives the `EDGE_THICKNESS_ASSUMED_LOW` exploration warning. The 0.5 mm warning is not a manufacturing standard. Outer diameter and mount envelope remain unspecified.

## Conditional same-aperture position comparison

After S5-A and S5-B passed their entry conditions, the registered five-point L2-position search selected `z=135 mm` using 512 rays and search seed `976052`. The independent holdout used 4,096 paired rays and seed `976053`, with a fixed 1 mm circular receiving region at `z=225 mm`.

The same assumed N-BK7 lenses, 2 mm center thicknesses, `12/12 mm` clear apertures and `25/100 mm` focal lengths were retained. Only L2 position changed from 125 to 135 mm, increasing L1-to-L2 principal-plane spacing from 100 to 110 mm. Holdout capture rose from `66.09%` to `87.06%`, a paired difference of `+20.97` percentage points; the 5,000-replicate paired **ray** bootstrap 95% interval is `[+19.73,+22.19]` percentage points.

**S5-C: `P1_SUPPORTED_TRADEOFF` within the assumed model.** The cost is a 10 mm L2 position shift. This is nominal ray-sampling evidence only: no assembly-level P1 tolerance or manufacturing claim was made. G4's historical overall claim remains `NO_SUPPORTED_IMPROVEMENT`; S5 is a separately constrained post-G4 position strategy, not an update to G4.
