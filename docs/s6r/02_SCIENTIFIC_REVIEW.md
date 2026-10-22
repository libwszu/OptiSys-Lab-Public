# Scientific Review

## Evidence and scope

S6 uses an assumed N-BK7 double-singlet P1 geometry, assumed multimode fiber source distributions, a fixed 1 mm target radius at z=225 mm, and simulated tolerance distributions. Captured source weight is a geometric fraction of all input source weight. It is not optical power, measured efficiency, or manufacturing yield.

S6-A's frozen summary hash matches its pre-holdout freeze. It reports 25 noncoaxial cases and 10 adversarial controls passing, with maximum surface hit difference `1.28e-13 mm`; this is model-internal cross-checking, not vendor qualification. S6-B reports both focus and L2 position `OPTIMUM_NOT_BRACKETED`; 145 mm is the top of the registered L2 search grid, not a demonstrated global optimum.

## S6-C recomputation

The source contains 200 unique assembly IDs per scenario, two designs per assembly, 1,024 source rays per design, and 800 unique scenario-assembly pairs total. The paired designs have matching source seed, source bundle hash, perturbation vector, and input hash. All terminal counts sum to 1,024; terminal weights sum to the unit source weight. Failed/invalid categories remain in the denominator. No failed, timed-out, or unstarted assembly is removed.

The verifier independently recalculated means, marginal P05/P50/P95, within-assembly deltas, paired P05, all-plane r90 quantiles, failure weights and counts, plot table values, and programmatic/final statistics. It replayed 2,000 cluster bootstrap draws per scenario with seed `8064001`, sampling complete assembly pairs and using `numpy.quantile(method="linear")`; all 8,000 stored replicate rows matched exactly.

| Scenario | Mean capture 125 / 135 | Paired mean Δ, 95% CI (pp) | Marginal P05 125 / 135 | Paired P05 Δ, bootstrap CI (pp) | L2 blocked rays 125 / 135 |
|---|---:|---:|---:|---:|---:|
| Zero | 66.53% / 85.92% | +19.39 [+19.22,+19.56] | 63.87% / 84.47% | +17.38 [+16.89,+17.87] | 0 / 0 |
| Tight 0.5× | 66.43% / 85.57% | +19.14 [+18.97,+19.33] | 58.79% / 77.92% | +17.09 [+16.60,+17.57] | 0 / 0 |
| Nominal 1× | 65.69% / 83.74% | +18.05 [+17.74,+18.34] | 51.64% / 69.90% | +13.67 [+12.60,+14.93] | 0 / 0 |
| Stress 2× | 59.69% / 72.43% | +12.75 [+11.65,+13.85] | 27.51% / 32.91% | **−5.69 [−9.28,−0.90]** | 1 / 2 |

The stress marginal P05 is higher for 135 mm while the paired P05 is negative. They differ because the paired P05 takes the fifth percentile of `candidate[i] - baseline[i]`; it is not the difference between each design's marginal fifth percentile.

In the zero-tolerance tier, all pose vectors are zero. The observed spread comes from distinct source-ray Monte Carlo seeds, not physical assembly variation. The stress P05 summarizes the lower tail of only 200 assemblies and is sensitive to tail sampling and model assumptions. Its bootstrap interval does not certify manufacturing yield. The one-ray difference in L2 clipping is too sparse to establish a reliability risk by itself; the broader adverse signal is the negative stress paired tail under the frozen rule.

## Claim rule and Amendment 03

The frozen acceptance criteria and `S6_C_HOLDOUT_FREEZE_02.json` state that finite support requires a positive mean interval, nonnegative paired P05 and its interval, no increase in failure weights, and no worse all-plane r90 P95. Otherwise the result is `TRADEOFF_OR_NO_SUPPORTED_GAIN`.

The run finished at `2026-10-21T07:28:54Z`. Amendment 03 was registered after the holdout result (03:31 America/New_York / 07:31Z; its hash record is 07:34:50Z). It preserves the original nominal-only automatic label and all data/thresholds, while applying the pre-result cross-scenario tail/failure rule to the aggregate conclusion. The standalone `S6_PRE_REGISTRATION.md` file is missing, but no conflict exists between the available frozen rule and Amendment 03.

**Nominal 1×:** `VERIFIED_CONDITIONAL_GAIN` within this assumed model.  
**Four registered scenarios:** `TRADEOFF_OR_NO_SUPPORTED_GAIN`.

See `docs/s6r/S6R_SCIENCE_RECOMPUTATION.json` for full precision and source file hashes.
