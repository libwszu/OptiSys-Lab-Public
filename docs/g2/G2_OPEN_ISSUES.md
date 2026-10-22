# G2 Open Issues Register

Opened 2026-10-19. Status is updated as evidence appears; entries are never
deleted, only closed with a pointer to the evidence.

| ID | Sev | Issue | G2 treatment | Status |
|---|---|---|---|---|
| PRE-01 | P1 | Full integration suite timed out in a foreign environment; the historical 194-test number cannot stand in for a local run | full `pytest` re-executed locally with JUnit + exit code | **CLOSED** — 194 passed / 0 failed / 0 skipped, exit 0, 128.58 s |
| PRE-02 | P1 | 2-D estimator fits a point-sampled Gaussian while the forward model integrates over pixel area; model mismatch at small σ | discretisation scan at σ = 0.6/1.0/1.5/2.5/5.0 px; area-integrated fitter added | **CLOSED** — σ bias +11.7 % at 0.6 px, +0.7 % at 2.5 px; area-integrated fitter 0.00 %; see `G2_PRE_REPORT.md` §3 |
| PRE-03 | P1 | weak-signal 2-D valid rate was 241/280 with `MODEL_MISMATCH` screening | frozen thresholds kept; L1 failure rate reported on all attempts | **OPEN** (carried into G2-E reporting) |
| PRE-04 | P1 | calibration only identifies `a = fx·B`, `b = cx − fx·tan θ` | strategy A / B strictly separated; model family M1/M2 selected on validation | **CLOSED** — M2 collapses to M1 at this working range; refitted calibration leaves 0.23 mm RMS, see `G2_PRE_REPORT.md` §4 |
| PRE-05 | P1 | gate accepted an externally supplied `tests_summary.json` | test evidence bound to code hash + JUnit hash + command + exit code; tamper tests added | **CLOSED** — `tests_summary_binding` check |
| PRE-06 | P2 | duplicate `test_worker_policy_follows_measured_speedup` definition (second shadowed the first) | renamed to a distinct semantic test; collection verified | **CLOSED** |
| PRE-07 | P2 | no measured RSS peak in G1 | process-tree RSS sampling + available-RAM logging | **CLOSED** |
| PRE-08 | P2 | ADC ceiling (11 985 e⁻) is reached before the 15 000 e⁻ full well; two different saturation causes | separate `FULL_WELL_SATURATION` / `ADC_CLIPPING` flags and tests | **CLOSED** |
| PRE-09 | P2 | CI workflow lacks a G1 reproduction command; remote CI never verified | workflow updated; remote status reported as `REMOTE_CI_NOT_VERIFIED` | **CLOSED** |
| PRE-10 | P3 | some report arrays rendered as raw Python lists | minimal display formatting only | **DEFERRED** (no data change) |

## G2-specific issues found during execution

| ID | Sev | Issue | Status |
|---|---|---|---|
| G2-01 | P1 | The L0 pinhole law and a real finite-conjugate singlet differ by up to **13.49 px** (3.58 % of the spot offset) at the baseline design. | **OPEN** — quantified in `run/optics/field_distortion.csv`; recalibration absorbs most of it, reuse of G1 `(a,b)` does not |
| G2-02 | P1 | A singlet at 11° field is aberration-dominated | **OPEN** — quantified; RMS spot 3.8–8.4 µm over 100–300 mm vs a 1.39 px Airy radius; the best RMS focus is displaced ≈0.1 mm from the paraxial focus by field aberration |
| G2-03 | P2 | `z_focus` is only meaningful in the L1 model | **CLOSED** — modelled as a detector axial offset, `NOT_MODELED` for L0 |
| G2-05 | P1 | First implementation applied the tolerance offsets to the **baseline** design instead of to each candidate, so every candidate was evaluated on the same 20/8/0 instrument | **CLOSED** — `make_design_assembly` applies the shared offsets to each candidate's own nominal geometry; a comment records the trap |
| G2-04 | P2 | Absolute radiometry is unavailable; electron counts are design assumptions | **OPEN** — two signal modes kept separate; no absolute claim |
| G2-06 | P1 | The condition-stratified sub-panel of the first full run scored with an empty calibration map (100 % invalid) | **CLOSED** — D-024, fixed and re-executed |
| G2-07 | P2 | The robust candidate buys RMSE with failure rate: 1.90 mm RMSE but 25.3 % failures vs 22.2 % for baseline | **OPEN** — the objective's failure weight (0.15) is too weak near the saturation boundary |
