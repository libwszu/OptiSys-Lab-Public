# S6-R Independent Science Recalculation

**Source run:** `20261021_024715_S6_P1`  
**Status:** `S6_DATA_ROWS_AND_PAIRING=PASS`; `S6_METRICS_RECOMPUTED=PASS`; `S6_VERDICT_TRACEABILITY=PASS_WITH_MISSING_STANDALONE_PREREGISTRATION_FILE`  
**Method:** recalculated from the immutable per-assembly CSVs; no assembly or ray simulation was rerun.

## Data integrity and pairing

- 800 unique `scenario × assembly_id` values: 200 in each of `zero`, `tight_0p5x`, `nominal_1x`, and `stress_2x`.
- 1,600 design-by-assembly rows and 800 paired comparison rows; each assembly contains one 125 mm baseline and one 135 mm candidate.
- Each design uses 1,024 source rays and source-weight denominator 1.0. Paired designs share the same source seed, source bundle hash, assembly perturbation, and input hash.
- Source seed rule `80630000 + latent_id` and latent draws reused across the four tolerance scales match the holdout manifest. The assembly manifest and all frozen hashes listed in Amendment 03 match.
- All 8,000 stored bootstrap rows were regenerated with seed `8064001`; all 2,000 rows per scenario matched exactly. The replay used `numpy.default_rng` / PCG64, assembly resampling with replacement, and NumPy's linear quantile interpolation for 95% intervals.
- Every terminal count totals 1,024 rays and each terminal-weight ledger totals 1.0. The maximum absolute ledger residual was `0`. The run has 800 complete assemblies, zero failures, zero timeouts, and zero unstarted assemblies.

## Recomputed results

Capture is captured source weight divided by all input source weight. `pp` is 100 times the fractional difference. P05 columns report separate estimands: marginal P05 of each design, then P05 of each paired assembly difference.

| Scenario | Mean capture 125 / 135 | Paired mean Δ, 95% bootstrap CI (pp) | Marginal P05 125 / 135 | Paired P05 Δ, bootstrap CI (pp) | L2 blocked rays 125 / 135 |
|---|---:|---:|---:|---:|---:|
| Zero | 66.53% / 85.92% | +19.39 [ +19.22, +19.56 ] | 63.87% / 84.47% | +17.38 [ +16.89, +17.87 ] | 0 / 0 |
| Tight 0.5× | 66.43% / 85.57% | +19.14 [ +18.97, +19.33 ] | 58.79% / 77.92% | +17.09 [ +16.60, +17.57 ] | 0 / 0 |
| Nominal 1× | 65.69% / 83.74% | +18.05 [ +17.74, +18.34 ] | 51.64% / 69.90% | +13.67 [ +12.60, +14.93 ] | 0 / 0 |
| Stress 2× | 59.69% / 72.43% | +12.75 [ +11.65, +13.85 ] | 27.51% / 32.91% | **−5.69 [ −9.28, −0.90 ]** | 1 / 2 |

The stress-tier marginal P05 is higher for 135 mm (32.91% versus 27.51%), while the P05 of within-assembly paired differences is negative. Those statements describe different estimands and can both be true. The stress paired P05 is not the candidate marginal P05 minus the baseline marginal P05.

## Verdict and rule trace

- **Nominal 1× estimand:** `VERIFIED_CONDITIONAL_GAIN`. The independently calculated paired-mean interval is above zero, paired P05 difference and its interval are positive, no failure weight increases, and candidate all-plane r90 P95 is lower.
- **All four registered scenarios:** `TRADEOFF_OR_NO_SUPPORTED_GAIN`. The 2× tier has a negative paired P05 difference with a bootstrap interval below zero and one additional candidate L2 aperture-blocked ray. This supports the finite model-level tail/failure tradeoff in the frozen criteria; the rare clipping count alone does not establish a manufacturing reliability risk.
- The original programmatic nominal-only label `SUPPORTED_WITHIN_ASSUMED_P1_AND_TOLERANCES` remains unchanged in the source JSON. The post-result Amendment 03 changes only the aggregate interpretation and preserves all samples, thresholds, and metrics.
- The acceptance criteria hash and holdout freeze rule verify. Timeline: holdout freeze `2026-10-21T07:25:40Z`; run complete `07:28:54Z`; Amendment 03 registered at `07:31` America/New_York; its hash record captured `07:34:50Z`. Amendment 03 is a post-result adjudication, not a retroactive preregistration.
- No standalone `docs/s6/S6_PRE_REGISTRATION.md` exists. The pre-result acceptance criteria and `S6_C_HOLDOUT_FREEZE_02.json` contain the applicable rule; there is no conflicting rule. Record this missing standalone file as `MISSING_SOURCE`.

## Interpretation limits

In the zero-tolerance tier every mechanical perturbation is zero. The 200 capture values vary because each assembly uses a different source-ray Monte Carlo seed; they are not 200 physically perturbed assemblies.

The stress paired P05 is estimated from the lower tail of 200 assemblies, so it is sensitive to tail sampling and the assumed P1/tolerance model. Its bootstrap interval is not a manufacturing-yield certification. All measurements are source-weight capture fractions, not absolute optical power. Lens vendor part, actual assembly tolerances, source far-field, mechanical travel, crystal dimensions, and physical measurements remain unavailable.

The machine-readable scenario results, full source hashes, and all validation checks are in `S6R_SCIENCE_RECOMPUTATION.json`.
