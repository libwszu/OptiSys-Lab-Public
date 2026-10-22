# G2 Acceptance Criteria (frozen before execution)

Frozen: **2026-10-19**, before any G2 numerical result existed.
Any change requires a new version file and a `DECISION_LOG.md` entry.

## 1. Gate vocabulary

| Symbol | Meaning |
|---|---|
| `PASS` | every required check executed and satisfied |
| `PARTIAL` | some required evidence missing; the produced evidence is still valid |
| `FAIL` | a required check executed and was violated |
| `NOT_RUN` | not executed; a reason is mandatory |
| `NOT_TESTED` | hardware/dependency not exercised |

Rules that cannot be relaxed to obtain `PASS`:

* a check may not be removed, renamed to hide a failure, or turned from
  `NOT_RUN` into `PASS`;
* the required test count may not be lowered;
* the failure denominator may not be reduced by deleting failed frames.

## 2. Required gate checks

### 2.1 `G0_G1_REGRESSION`

| Check | Requirement |
|---|---|
| R1 | `pytest` executed on this machine, JUnit XML present, `failed==0`, `skipped==0`, `passed>=194` |
| R2 | exit code recorded and equals 0 |
| R3 | `repro/verify_g0.py` prints `REPRO_STATUS: PASS` |
| R4 | `repro/verify_g1.py` prints `REPRO_STATUS: PASS` |
| R5 | `src/**/*.py` digest equals `1c80c3e1…704d5` **or** the difference is documented with the affected files and a fresh G1 regression has been re-run |
| R6 | `configs/triangulation_g1_l0.yaml` SHA-256 equals `54c9e3fb…50b6` |
| R7 | G0 and G1 audit ZIP SHA-256 match the values in the task book |
| R8 | the test summary is bound to `code_sha256`, command line, interpreter and JUnit file hash |

### 2.2 `V4_A` — real optical backend

| Check | Requirement |
|---|---|
| A1 | `optiland` importable, version recorded, real `Optic` constructed |
| A2 | at least one real refracting surface with declared radius/thickness/material |
| A3 | ray trace actually executed; per-ray input/output/valid flag exported |
| A4 | chief-ray image height agrees with the independent paraxial thin-lens reference within a **pre-registered** tolerance (`<= 1 %` of image height) |
| A5 | pinhole limit: as `EPD -> 0`, the traced chief ray converges to the pinhole model within `<= 0.5 %` of image height |
| A6 | aperture change produces a monotone change of the geometric spot size (Spearman `rho = 1`, `p < 0.05`) |
| A7 | focus change produces the expected defocus blur growth, monotone in `|z_focus - Z|` |
| A8 | blocked/failed rays are counted, never silently averaged away |
| A9 | optical layout and spot-diagram figures exist with units |

`V4_A = PASS` requires A1–A9. Otherwise `PARTIAL` (A1/A3 satisfied, A4–A7 not)
or `FAIL` (backend not executable).

### 2.3 `V4_B` — L1 → CMOS

| Check | Requirement |
|---|---|
| B1 | energy: `sum(kernel)` over the support vs the transmitted ray energy, relative deviation `<= 0.5 %` |
| B2 | kernel non-negative, finite, normalised on the chip; no re-normalisation after clipping |
| B3 | pixel integration applied **exactly once** (spot ⊛ kernel, then pixel-area integration) |
| B4 | L0 limit: with the pinhole reference kernel the L1 pipeline reproduces the G1 L0 result within `0.01 px` on `u` for the same seed |
| B5 | `z_focus`, `D_entrance` change the kernel and the electron count according to the declared model (not a constant offset) |
| B6 | degenerate cases return named statuses (`ALL_RAYS_BLOCKED`, `OUT_OF_FOV`, `INSUFFICIENT_PSF_SUPPORT`, …) and never a fake distance |
| B7 | deterministic kernel for a repeated identical configuration (bitwise identical arrays) |
| B8 | `capture_fraction` reported and `< 1` cases not renormalsed |

### 2.4 `V5_SAMPLER`

| Check | Requirement |
|---|---|
| S1 | zero perturbation reproduces the nominal configuration bitwise |
| S2 | LHS marginals pass a KS test against the target normal at `alpha = 0.01` |
| S3 | one `assembly_id` shares `ΔB, Δθ, Δf, Δcx, Δz_focus` across all scenes and repeats |
| S4 | frame noise independent per `(assembly, scene, repeat)` |
| S5 | OAT sweep `0, ±1σ, ±2σ, ±3σ` recorded for all five variables |
| S6 | >= 200 exploratory assembly draws, each with a status row |
| S7 | failures enter the denominator; no `NaN` deletion |

### 2.5 `V5_OPTIMIZER`

| Check | Requirement |
|---|---|
| O1 | objective weights, reference scales, panel, and hard constraints frozen before search |
| O2 | `baseline`, `nominal`, `robust` evaluated on the same scenes with common random numbers |
| O3 | every attempted design recorded with feasibility status |
| O4 | budget recorded: wall clock, CPU time, ray count, frame count |
| O5 | `candidate_registry.json` frozen before the final test |
| O6 | final-test seeds/scenes provably disjoint from search seeds/scenes |

### 2.6 `V5_HOLDOUT`

| Check | Requirement |
|---|---|
| H1 | >= 2000 independent assembly draws for the final evaluation (`N_assembly`, not frames) |
| H2 | all three candidates use the same assemblies and the same scenes |
| H3 | paired differences `ΔRMSE`, `ΔP95`, `Δfailure` with cluster-bootstrap 95 % CI (cluster = assembly) |
| H4 | strategy A and strategy B reported separately |
| H5 | failure rate over **all attempts** |
| H6 | negative results retained and reported |

If H1 cannot be met, the run reports `INSUFFICIENT_PRECISION` with the actual
`N`, and the G2 scientific claim is downgraded. It is not silently relabelled.

## 3. Stage deliverable checklist

Each stage must produce the files listed in task book §5, §6, §7, §8, §9, §13.1.
Missing files are `NOT_RUN` with a reason, never empty `PASS` tables.

## 4. Evidence levels

`FORMULA < SIMULATED < CROSS-CHECKED < MEASURED < VALIDATED`.

G2 target: **CROSS-CHECKED within declared assumptions**. `MEASURED` is
impossible in this round because no camera data exist.

## 5. Statistical rules

* Confidence intervals: cluster bootstrap resampling **assemblies**, 2000
  resamples, percentile method, `alpha = 0.05`.
* Comparisons are **paired** on identical assemblies/scenes.
* A gain is claimed only when the paired CI excludes zero.
* Two metrics that disagree (e.g. better P95, worse RMSE) are reported as a
  trade-off, not as a gain.

## 6. Derivation of `model_level`

`model_level = L1-approximate` is emitted only when **all** hold:

1. `optics_backend_status.json.backend_executed == true`;
2. the trace produced a non-empty valid-ray set for every required scene;
3. `V4_A == PASS` and `V4_B == PASS`.

Otherwise the emitted level is `L0` (if only the G1 chain ran) or
`L1-attempted-not-verified`.

## 7. Overall G2 status

```
G2_EXECUTION_STATUS = PASS  iff  G0_G1_REGRESSION, V4_A, V4_B,
                                 V5_SAMPLER, V5_OPTIMIZER, V5_HOLDOUT, AUDIT
                                 are all PASS or PASS-with-declared-downgrade
G2_SCIENTIFIC_CLAIM_STATUS ∈ {GAIN_SUPPORTED_WITHIN_ASSUMED_L1_MODEL,
                              TRADEOFF_OBSERVED, NO_CONFIRMED_GAIN,
                              NO_FEASIBLE_DESIGN, PARTIAL, FAIL}
```

`NO_CONFIRMED_GAIN` with `PASS` execution is a legitimate, expected outcome.
