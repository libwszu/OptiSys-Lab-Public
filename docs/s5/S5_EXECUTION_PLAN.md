# Stage 5 execution plan (frozen before new scientific results)

Run ID: `20261020_210201_S5_HNA`

## S5-PRE: takeover and preregistration

1. Preserve the pre-existing dirty worktree; capture every existing changed/untracked file hash, Git HEAD, source-tree digest, original PDF and prompt hashes.
2. Verify G0–G3 protected baseline snapshot, G4 official run tree, G4 archive sidecar and G4 archive contents without writing into historical runs.
3. Read the original project PDF, Stage 5 prompt, G4 status/matrix/issues/discrepancies, P1 configs and run evidence, core source, tests and six-page UI.
4. Freeze acceptance criteria, scientific scope, compute budget, execution sequence and S5 config hashes before benchmark-derived or scientific outputs.

## Scientific path

### S5-A — independent full-NA reference

- Implement a new global-coordinate, double-precision sphere intersection and vector Snell path that does not import Optiland or call `OptilandPumpTracer.trace`.
- Read G4 geometry values from `optics_model.json`, input rays from the G4 `source_samples.csv`, and aperture/target values from the two frozen YAML configurations.
- Record all rays at each of four physical spherical faces, incoming state, hit, normal, indices, outgoing state, block/failure reason and weight. Independently replay Optiland with `record=True` and compare each surface state from the backend's saved surface arrays.
- Exercise free propagation, plane refraction, sphere-axis/edge behavior, 0/3/6/9/11/12.71 degree rays, critical-angle and invalid-geometry negative controls, material rejection, and ledger masks.
- Freeze `PASS`, `QUALIFIED` or `FAIL`; stop design-gain work after any unexplained physical mismatch.

### S5-B — scoped mechanism and geometry sensitivity

- Recompute original G4 angle capture using original per-ray inputs without changing the G4 run.
- Produce marginal strata for angle, L1/L2 normalized incidence radius, source radius and azimuth; retain all source-weight denominators.
- Trace the same fixed designs through pre-registered source-distribution alternatives; report changes separately from lens-design effects.
- Propagate saved L2 exit states to fixed focus planes and independently retrace a minimum of three target planes through Optiland.
- Produce source-normalized encircled-weight, fixed-target capture, conditional spot radii, target geometry and lens edge-thickness tables/plots. Label all outputs simulated and conditional on assumptions.
- If reference verification is not PASS, label every mechanism plot/table `EXPLORATORY_MODEL_DIAGNOSTICS` and do not infer a physical cause.

### S5-C — conditional equal-aperture position search

- Only enter after S5-A PASS, complete S5-B evidence, valid material/geometry, and budget headroom.
- Search only the pre-registered L2 position grid under the same 12/12 mm clear apertures and fixed 1 mm circular target at z=225 mm. Keep G4 designs intact as historical comparisons.
- Select with the 512-ray search seed and evaluate once on the independent 4,096-ray holdout. Use a paired ray bootstrap as a sampling interval and label that it is not assembly-level tolerance evidence.
- If entry criteria are not met, emit the required status without doing the search.

## Engineering portfolio path (independent of S5-A)

- Run current six-page AppTest, full pytest suite, real Streamlit health/root smoke, main-case and pump-case CLI small-run examples, error-path example, and verify frozen-run read-only behavior.
- Inspect actual browser availability. When a local browser tool is available, exercise the running UI and save actual screenshots; otherwise record unavailability. Do not create false UI/video evidence.
- Prepare a local `RELEASE_CANDIDATE/` with a concise README, two run commands, limitations, dependency roles, verified result plots/tables, demo script and capture checklist.
- Update root README only through a narrow S5 status addition, preserving existing sections and content.
- Do not change existing G0–G4 runs, source PDFs, prior audit archives or their status documents.

## S5-E — regression and independent package audit

- Assemble a minimal cross-platform evidence archive with all new data needed to reproduce conclusions, relevant new source/tests/configs, source-plan/prompt hashes, G4 historical hash/status references and unaltered critical G4 comparison rows.
- Run verifier from a clean temporary extraction; require evidence recomputation, ledger and mechanical checks, exact manifest coverage, hash integrity and tamper rejection.
- Write one final verdict and one terminal summary. Preserve `NOT_AVAILABLE`, `NOT_RUN`, `QUALIFIED`, `PARTIAL` and failures as observed.
