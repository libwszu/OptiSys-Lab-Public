# G2 Execution Plan — L1 optical backend, tolerance, robust design

Status: **FROZEN 2026-10-19 (before any G2 numerical result was produced)**
Owner: OptiSys-Lab G2 round
Predecessor: G1 frozen run `20261019_145702_G1_54c9e3fb` (L0)

## 0. Why this document exists

This plan is written **before** any G2 simulation is executed. Every later
deviation is appended to `docs/DECISION_LOG.md` with a timestamp and a reason;
existing gates are never retro-fitted to a new plan.

## 1. Scope

In scope (G2):

| Work package | Content | Gate evidence |
|---|---|---|
| G2-PRE | real regression of G0/G1, audit-risk repair, frozen pre-registration | `G0_G1_REGRESSION` |
| G2-A | Optiland 0.6.3 **actually executed**; real refracting surfaces; independent thin-lens / pinhole reference | `V4_A` |
| G2-B | footprint/PSF → CMOS contract; energy, capture, vignetting; L0 limit consistency | `V4_B` |
| G2-C | tolerance variables acting on real model parameters; OAT + LHS; two calibration strategies | `V5_SAMPLER` |
| G2-D | nominal and robust optimisation under a common frozen budget | `V5_OPTIMIZER` |
| G2-E | independent seeds/assemblies, paired bootstrap CI, negative results | `V5_HOLDOUT` |
| G2-AUDIT | reproducible ZIP for external review | `AUDIT` |

Out of scope (explicitly): GUI (G3), 976 nm pump case (G4), full LiDAR,
coherent speckle, manufacturing yield, measured-camera validation,
real lens purchasing.

## 2. Model levels

* **L0** — G1 pinhole + circular Gaussian, frozen, untouched.
* **L1-approximate** — real sequential ray trace through a declared singlet,
  the geometric footprint convolved with a scalar Airy diffraction kernel.
  It is an *engineering approximation with declared assumptions*, not a
  wavefront-verified or measured PSF.

`model_level` is never taken from a string in a YAML file alone. The gate
derives it from evidence (see `G2_ACCEPTANCE_CRITERIA.md` §6).

## 3. Execution order and exit conditions

```
PRE → A → B → C → D → E → AUDIT
```

A stage may only start when the previous stage's exit condition is met.
If a stage fails, dependent stages stop; independent work continues and the
run is reported as `PARTIAL` with the blocking reason.

## 4. Baseline policy

The G0/G1 runs and audit ZIPs are read-only. G2 writes only to
`runs/<g2_run_id>/`, `artifacts/g2/`, `docs/g2/` and `_AUDIT/<g2_run_id>/`.
No G1 file is modified, no G1 hash is recomputed by editing sources.

## 5. Software architecture

New modules, reusing G1 wherever possible:

```
src/optisys/optics/optiland_adapter.py    real lens + trace -> footprint
src/optisys/optics/reference_thin_lens.py independent paraxial + pinhole reference
src/optisys/optics/psf_or_footprint.py    kernel construction, support, classification
src/optisys/optics/optical_image_contract.py  OpticalImageResult + status codes
src/optisys/imaging/sensor_g2.py          faster, distribution-equivalent renderer
src/optisys/tolerance/perturbations.py    perturbation vector + physical mapping
src/optisys/tolerance/samplers.py         normal / LHS with correct inverse CDF
src/optisys/tolerance/oat.py              one-at-a-time sweeps
src/optisys/tolerance/assembly_model.py   assembly -> geometry + optics
src/optisys/calibration/assembly_strategies.py  strategy A / B
src/optisys/optimization/*.py             space, constraints, objectives, nominal, robust
src/optisys/evaluation/paired_comparison.py    paired deltas + cluster bootstrap
src/optisys/gates/g2.py                   orchestration + gate checks
src/optisys/reports/figures_g2.py, report_g2.py
repro/verify_g2.py
scripts/build_g2_audit_package.py, verify_g2_audit_package.py
```

G1 modules (`geometry`, `imaging.spot`, `imaging.roi`, `estimators`,
`calibration.system`, `evaluation.metrics`) are imported, not forked.

## 6. Deliverables per stage

See `G2_ACCEPTANCE_CRITERIA.md` §3. Every stage writes machine-readable
JSON/CSV next to the human-readable markdown so the audit package can be
checked without re-running the physics.

## 7. Stop rules

* `STOP_PRE` — G0/G1 regression fails and cannot be localised. No G2-A.
* `V4_A != PASS` — no tolerance/optimisation claim; report `G2_PARTIAL`.
* Numerical instability — save the failing sample, do not widen thresholds.
* Resource exhaustion — persist partial results, mark `RESOURCE_LIMIT_PARTIAL`.

## 8. Non-negotiable statements

1. Third-party Optiland performs the ray trace. What this project contributes
   is the pipeline, the interface contract, the validation, the tolerance
   engine, the objective design, the statistics and the evidence system.
2. No artificial `sigma(Z)` is ever used in place of a traced footprint.
3. `execution PASS` never implies physical accuracy validation.
