# G2 final report — L1 optical backend, tolerance and robust design

Run (frozen PASS): `runs/20261019_191117_G2_52369787` (wall time ≈ 5 625 s / 1 h 33 m 45 s, 4 workers)
Pre-fix run (execution FAIL, not used): `runs/20261019_170944_G2_52369787`
Configuration: `configs/triangulation_g2_l1.yaml`, SHA-256 `52369787c0e7f1dab7363a19132135a012dbe0fd9aa732e96a000d5a2e46e30c`

> The numbers below are from the **frozen PASS run `191117`**. A first full-scale
> run (`170944`) failed at execution time because of two bookkeeping defects
> (D-022: a stale estimator-count constant in the `S7` self-consistency check;
> D-024: the condition-stratified panel was scored with an empty calibration
> map). Both were fixed in code and the run was re-executed; the scientific
> results are deterministic and reproduce exactly between the two runs, so the
> `191117` artefacts are the ones carried into the audit package.

## 1. What was built

| Stage | Deliverable | Evidence |
|---|---|---|
| G2-PRE | baseline re-verification, PRE-01…PRE-10 | `G2_PRE_REPORT.md`, `docs/g2/G2_BASELINE_HASHES.json` |
| G2-A | real Optiland 0.6.3 trace + independent paraxial check | `run/optics/optical_validation.json`, `raytrace_reference.csv` |
| G2-B | L1 → CMOS contract, energy, capture, determinism | `run/optics/energy_and_capture.csv`, `psf_or_footprint_examples.npz` |
| G2-C | assembly-level tolerance, LHS, OAT, two calibration strategies | `run/tolerance/*` |
| G2-D | budgeted nominal + robust search over `(B, f, θ)` | `run/optimization/*` |
| G2-E | 2 000 fresh assemblies, paired cluster bootstrap | `run/independent_validation/*` |
| AUDIT | 1.87 MB ZIP, 180 files, extracted reproduction PASS | `_AUDIT/<run_id>/…_GPT_AUDIT.zip` |

## 2. Design space and constraints

`B ∈ [15, 35] mm`, `f ∈ [6, 12] mm`, `θ ∈ [−4, +4] deg`. Hard constraints:
sensor margin 24 px, ray success ≥ 0.90, kernel support ≥ 0.95, peak ≤ 0.8 ×
full well. **89 screened designs were infeasible**, overwhelmingly
`OUT_OF_FOV` (large `B` with long `f` pushes the far-end spot off the chip) and
`INSUFFICIENT_PSF_SUPPORT`.

## 3. Independent final evaluation — strategy A (factory nominal calibration)

2 000 assemblies × 7 held-out distances × 3 estimators = **42 000 rows per
candidate**. All three candidates see the *same* random offsets applied to
their own nominal geometry.

| candidate | B [mm] | f [mm] | θ [deg] | valid / attempted | failure | RMSE [mm] | P95 [mm] | bias [mm] |
|---|---:|---:|---:|---|---:|---:|---:|---:|
| baseline | 20.0 | 8.00 | 0.0 | 32 693 / 42 000 | 0.2216 | **3.1481** | 6.6430 | +0.1411 |
| nominal | 15.0 | 11.10 | 4.0 | 35 337 / 42 000 | 0.1586 | 3.0176 | 6.5663 | +0.0638 |
| robust | 34.4 | 7.27 | 4.0 | 31 373 / 42 000 | 0.2530 | **1.9031** | 3.8349 | −0.1717 |

### Paired differences, cluster bootstrap over assemblies (2 000 resamples)

| comparison (estimator) | pairs | ΔRMSE [mm] | 95 % CI [mm] | excludes 0 |
|---|---:|---:|---|---|
| baseline → robust (`gaussian_2d_integrated`) | 14 000 | −1.1257 | [−1.1715, −1.0782] | yes |
| baseline → robust (`centroid`) | 14 000 | −1.1760 | [−1.2180, −1.1322] | yes |
| nominal → robust (`gaussian_2d_integrated`) | 14 000 | −0.9868 | [−1.0728, −0.9064] | yes |
| baseline → nominal (`gaussian_2d_integrated`) | 14 000 | −0.1068 | [−0.2037, −0.0073] | yes |

The robust design is better on RMSE and its confidence interval excludes zero,
so the gain is real **within this model**.

### But it is a trade-off, not a free win

| estimator | baseline failure | nominal failure | robust failure |
|---|---:|---:|---:|
| centroid | 6.6 % | **0.06 %** | 9.2 % |
| gaussian_2d (G1) | 49.3 % | 47.4 % | 53.8 % |
| gaussian_2d_integrated | 10.5 % | **0.10 %** | 12.9 % |

The robust design achieves the lowest RMSE **and the highest failure rate**
(`SATURATED` at the near end, because a short focal length concentrates the
light). The pre-declared primary metric is ΔRMSE, so the claim is
`GAIN_SUPPORTED_WITHIN_ASSUMED_L1_MODEL`; the failure penalty term in the
objective (weight 0.15) was evidently not strong enough to keep the optimiser
away from the saturation boundary. That is a finding about the objective
design, not about the candidate.

## 4. Strategy B (per-unit recalibration), 200 assemblies × 7 distances

| candidate | valid / attempted | failure | RMSE [mm] | P95 [mm] |
|---|---:|---:|---:|---:|
| baseline | 1 270 / 1 400 | 9.3 % | 0.2294 | 0.4737 |
| nominal | 1 399 / 1 400 | 0.07 % | **0.0385** | 0.0791 |
| robust | 1 227 / 1 400 | 12.4 % | 0.4889 | 1.0214 |

**The ranking reverses.** Under strategy A the robust design wins on RMSE;
under strategy B the *nominal* design wins by 6×. Recalibration is worth
roughly 1.5 mm (baseline) to 3 mm (robust) in this model, which is far more
than the design choice itself is worth under strategy B.

Cost of strategy B, recorded as required: each unit needs its own 5 calibration
frames plus the estimator calls; the subset here is 200 units × 12 frames.

## 5. Estimator behaviour on the L1 spot (reported, not hidden)

* `gaussian_2d` (frozen G1, point-sampled) flags `MODEL_MISMATCH` on ~48 % of
  frames because the fitted sigma falls below its frozen 1.0 px lower bound.
  This is the discretisation finding of PRE-02, confirmed at scale.
* `gaussian_2d_integrated` (new) removes it: the same frames give 0.1–12.9 %
  failure, dominated by saturation and non-convergence instead.
* `centroid` has the smallest position bias (≈0.005–0.29 px depending on
  distance) because the coma tail is symmetric in energy, but no sub-pixel
  robustness at low signal.

## 6. Honest limitations

1. No measured lens, camera, laser or target. Nothing here is `MEASURED`.
2. The kernel is a geometric footprint convolved with a **scalar Airy limit**;
   it is not a wavefront PSF.
3. Tolerance sigmas are ASSUMED examples from the task book, not a
   manufacturing study.
4. A single-element singlet at an 11° field is aberration-dominated; the best
   RMS focus sits ≈0.1 mm from the paraxial focus.
5. Absolute radiometry is impossible here; `fixed_incident` isolates geometry
   and PSF effects and must not be read as a flux result.
6. The condition-stratified sub-panel of the first run is invalid (D-024); it
   was replaced in the re-run.

## 7. Verdict for this run

* `G2_EXECUTION_STATUS` = **FAIL** on the first run `170944`, caused by `S7`'s
  stale estimator-count constant (D-022); the underlying data is complete and
  correct. Fixed and re-executed as `191117`.
* `G2_EXECUTION_STATUS` = **PASS** on the re-run `191117` — all 27 numeric /
  boundary gate checks green, 252/252 ingested tests pass (failed = 0,
  skipped = 0), frozen at 2026-10-19T20:45:02+00:00.
* `V4_A` = PASS, `V4_B` = PASS, `V5_SAMPLER` = PASS, `V5_OPTIMIZER` = PASS,
  `V5_HOLDOUT` = PASS (2000 assemblies), `AUDIT` = PASS.
* `G2_SCIENTIFIC_CLAIM_STATUS` = **GAIN_SUPPORTED_WITHIN_ASSUMED_L1_MODEL**,
  with the failure-rate trade-off stated explicitly.
