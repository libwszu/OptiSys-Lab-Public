# G2 Pre-Registration

Version: **v1.0** — frozen 2026-10-19, before any G2 result was inspected.
The SHA-256 of this file is recorded in `G2_BASELINE_HASHES.json` and in the
run's `provenance.json`. Later versions are new files; this one is never edited.

## 1. Reference system

Coplanar laser triangulation, 650 nm, working range 100–300 mm.
Baseline `B = 20 mm`, `θ = 0°`, `f = 8 mm`, `p = 3.45 µm`, 1280 × 1024,
`cx = 640`, `cy = 512`.

## 2. Design variables (frozen)

```
x = (B, f, θ)
B     ∈ [15, 35] mm
f     ∈ [ 6, 12] mm
θ     ∈ [-4, +4] deg      (converted to rad inside the engine)
```

`z_focus` and `D_entrance` are **not** optimisation variables in this round.
They are fixed (`D = 1.2 mm`, `z_focus = 200 mm`) and analysed by OAT only.
Reason: keeping the frozen 3-variable space preserves comparability with the
task book and avoids claiming that "more variables" is an achievement.

## 3. Hard constraints (evaluated before any objective)

| ID | Constraint | Threshold | Consequence |
|---|---|---|---|
| HC1 | chief ray inside the sensor for every `Z ∈ [100,300]` | `24 ≤ u ≤ 1255 px` | else `INFEASIBLE(OUT_OF_FOV)` |
| HC2 | ray success fraction | `>= 0.90` | else `INFEASIBLE(VIGNETTING)` |
| HC3 | kernel support fraction | `>= 0.999` | else `INFEASIBLE(INSUFFICIENT_PSF_SUPPORT)` |
| HC4 | max expected pixel signal, medium condition | `<= 0.80 · full_well` | else `INFEASIBLE(SATURATION)` |
| HC5 | parameter bounds | box in §2 | else `INFEASIBLE(BOUNDS)` |
| HC6 | calibration achievable: validation distance where the fit is evaluated must lie inside the calibrated span | — | else `INFEASIBLE(CALIB_SPAN)` |

Infeasible designs return a **reason code**, never a large soft penalty that
could be traded against accuracy.

## 4. Objective (frozen)

```
J_nom(x)    = RMSE_nominal(x) / RMSE_ref
J_robust(x) = w1·E_Δ[RMSE(x,Δ)]/RMSE_ref
            + w2·P95_Δ(|e|)/P95_ref
            + w3·P(failure|x)/Pfail_ref
w1 = 0.50, w2 = 0.35, w3 = 0.15
RMSE_ref = 0.050 mm, P95_ref = 0.100 mm, Pfail_ref = 0.050
```

* `RMSE` and `P95` use **valid frames only**, and are always reported next to
  `n_valid / n_attempted`.
* `P95_Δ` is defined over **all frames of all assemblies** in the evaluation
  panel (pooled). The per-assembly P95 is reported separately but never
  substituted silently.
* `P(failure)` uses **all attempts** as the denominator.
* Units: every error term is in mm; the ratio removes the unit. Failure rate
  is dimensionless. No un-normalised weighting is allowed.

## 5. Data splits (frozen)

| Split | Distances (mm) | Use |
|---|---|---|
| search-train | 100, 120, 140, 160, 180, 200, 220, 240, 260, 280, 300 | objective during search |
| search-validation | 110, 130, 150, 170, 190, 210, 230, 250, 270, 290 | model-family selection only |
| final-test | 105, 135, 165, 195, 225, 255, 285 | **single** evaluation after freeze |

Final-test distances never appear in any search, OAT, precheck or model
selection. The final-test seeds are drawn from a separate namespace
(`G2F`), and `split_manifest.json` records a disjointness assertion that is
checked at run time.

## 6. Scenes

Conditions (inherited G1): `strong` (2×10⁵ e⁻), `medium` (4×10⁴ e⁻),
`weak` (8×10³ e⁻).

| Panel | Distances | Conditions | Repeats | Frames per assembly |
|---|---|---|---|---|
| search (train) | 6 of the train list | medium | 1 | 6 |
| search (robust) | 6 | medium, weak | 1 | 12 |
| OAT | 5 | medium | 1 | 5 |
| precheck | 5 | medium | 1 | 5 |
| final | 7 (test) | strong, medium, weak | 1 | 21 |

Deterministic choice of the 6 search distances: the first, last and four
evenly spaced values of the train list — fixed here, not chosen after seeing
results.

## 7. Calibration strategies (frozen, never mixed)

**Strategy A — factory nominal calibration.**
A single `(a, b)` (or the selected model) is fitted on a *nominal* virtual
unit at `B₀, f₀, θ₀` using calibration distances, then applied unchanged to
every perturbed assembly. The evaluator never reads the assembly truth.

**Strategy B — per-unit recalibration.**
For each `assembly_id`, calibration frames are generated **from that
assembly's own perturbed optics**, the same estimator runs, and `(a, b)` are
fitted from the measured `u`. The calibration distances are disjoint from the
evaluation distances of that unit. `a = fx·B` from the simulator is **never**
handed to the fitter. Calibration failure counts as a failure of that unit.

Cost is reported: calibration frames per unit, estimator calls, wall time.

### Calibration model family (selected on validation only)

```
M1: u = a/Z + b                (G1 baseline; 2 parameters)
M2: u = a/(Z - c) + b          (thin-lens motivated; 3 parameters)
```

Selection rule: choose M2 only if its validation RMSE is at least **20 %**
lower than M1's. Otherwise M1. The decision is written to
`calibration_model_choice.json` **before** the final test is run.

## 8. Random-number policy

* Seed derivation: `blake2b(f"{namespace}|{assembly_id}|{scene_key}|{repeat}")`.
* Namespaces: `G2P` (precheck/OAT), `G2S` (search), `G2F` (final).
* Assembly perturbation index: `assembly_id` → one `Δ` vector, shared by all
  scenes and repeats of that assembly (common random numbers across
  candidates).
* Frame noise: independent per `(assembly, scene, repeat)`.
* A final-test assembly ID set is generated from `G2F` only; a runtime
  assertion checks `search_ids ∩ final_ids = ∅`.

## 9. Budgets (frozen before search)

| Stage | Budget |
|---|---|
| OAT | 5 variables × 7 levels × 5 frames |
| precheck LHS | 200 assemblies × 5 frames |
| search | 300 objective evaluations total, each ≤ 12 frames |
| search wall clock cap | 3600 s |
| final | 2000 assemblies × 21 frames |
| final wall clock cap | 7200 s (degrade to fewer assemblies with reported `N` if exceeded) |

A budget overrun is reported, not silently exceeded. The optimiser stops at
the budget and keeps the best feasible candidate with all attempts recorded.

## 10. Candidate comparison

`baseline` = the PDF initial design `(B, f, θ) = (20, 8, 0)`.
`nominal` = argmin `J_nom` under HC1–HC6.
`robust` = argmin `J_robust` under HC1–HC6.

All three are frozen in `candidate_registry.json` before the final test.

## 11. Statistics

* Cluster bootstrap, cluster = assembly, 2000 resamples, percentile CI, 95 %.
* Paired differences on identical assemblies: `ΔRMSE`, `ΔP95`, `Δfailure`.
* A gain is claimed only if the paired CI excludes 0 in the favourable
  direction for the pre-declared primary metric (`ΔRMSE`).
* The three candidates are compared on identical scenes.

## 12. Declared outcome language

| Situation | Reported |
|---|---|
| paired CI excludes 0 and favours robust | `GAIN_SUPPORTED_WITHIN_ASSUMED_L1_MODEL` |
| mixed metrics or CI crossing 0 | `TRADEOFF_OBSERVED` / `NO_CONFIRMED_GAIN` |
| no feasible design | `NO_FEASIBLE_DESIGN` |
| optical backend not executed | `V4_NOT_VERIFIED`, `G2_PARTIAL` |
| 2000 assemblies not reached | `INSUFFICIENT_PRECISION` + actual N |

## 13. What will be reported even if unfavourable

* every failed frame, with its status;
* every infeasible design, with its reason;
* the L0-vs-L1 discrepancy in mm and px;
* the model-mismatch rate of the 2-D Gaussian estimator on the L1 spot;
* the cost of strategy B in frames and time;
* any correlation-sensitivity rank change.
