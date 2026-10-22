# G2-PRE report: baseline re-verification and audit-risk repair

Executed on the real workspace `<PROJECT_ROOT>` (Windows 11, CPython 3.14.3 in
`.venv`). No historical run, ZIP or source file was modified.

## 1. Baseline identity

| Item | Verified value | Task book | Match |
|---|---|---|---|
| `OptiSys_Lab_Job_Oriented_Development_Plan_2026.pdf` | `25d0a727…6319d`, 582 816 B | `25d0a727…6319d` | yes |
| G0 audit ZIP | `3967d064…34c44`, 993 189 B | `3967d064…34c44` | yes |
| G1 audit ZIP | `a81641f7…584c5`, 7 507 224 B | `a81641f7…584c5` | yes |
| G1 source-tree digest (`src/**/*.py`) | `1c80c3e1…704d5` | `1c80c3e1…704d5` | yes |
| G1 config SHA-256 | `54c9e3fb…50b6` | `54c9e3fb…50b6` | yes |

Working Git HEAD at G2 start: `e9040d1`. The G1 package reported `be21dfa`.
The two intervening commits (`fbc0fbb`, `e9040d1`) touch `docs/` and
`.workbuddy/memory/` only — confirmed with `git diff --stat be21dfa HEAD`,
no file under `src/` is in the diff, which is why the source digest still
matches.

## 2. Real regression (PRE-01)

Command actually executed:

```
.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider \
    --basetemp=artifacts/g2_pre/pytest_tmp --durations=25 \
    --junitxml=artifacts/g2_pre/pytest_g2pre.xml
```

| Metric | Value |
|---|---|
| Result | **194 passed, 0 failed, 0 skipped** |
| Exit code | 0 |
| Duration | 128.58 s |
| JUnit | `artifacts/g2_pre/pytest_g2pre.xml` (`tests=194 failures=0 errors=0 skipped=0`) |
| Slowest test | `tests/integration/test_cli.py::test_runs_never_overwrite_each_other` 24.47 s |

A first attempt exited 1 **after** every test had passed; the cause was the
host's delete guard intercepting pytest's temporary-directory cleanup, not a
test failure. Re-running with a project-local `--basetemp` produced a clean
exit 0. Both runs are kept; the first one is not cited as evidence.

Reproduction scripts:

```
repro/verify_g0.py  -> REPRO_STATUS: PASS   (max |u_a - u_ref| = 2.274e-13 px)
repro/verify_g1.py  -> REPRO_STATUS: PASS   (energy 0, quadrature 4.06e-16,
                                             noise z=0.049, var ratio 0.9943,
                                             2-D error 7.813e-05 px)
```

## 3. PRE-02 — discretisation vs fitting model

Claim under test: the forward model integrates the spot over pixel area, while
`estimators/gaussian_2d.py` fits a Gaussian sampled at pixel centres. The
mismatch was assumed harmless at `sigma = 2.5 px`.

Method: build a pixel-integrated Gaussian as truth, then fit (a) a
point-sampled Gaussian and (b) an area-integrated Gaussian, at
`sigma = 0.6, 1.0, 1.5, 2.5, 5.0 px` and three sub-pixel phases.
Data: `artifacts/g2_pre/pre02_discretisation.csv`.

| `sigma_true` [px] | relative `sigma` bias, point-sampled fit | relative bias, area-integrated fit |
|---:|---:|---:|
| 0.6 | **+11.7 %** | 0.00 % |
| 1.0 | **+4.2 %** | 0.00 % |
| 1.5 | +1.9 % | 0.00 % |
| 2.5 | +0.7 % | 0.00 % |
| 5.0 | +0.2 % | 0.00 % |

The centroid bias is negligible (< 0.004 px) at every `sigma`; the damage is
in the *width* estimate. Consequences:

1. At the G1 operating point (`sigma = 2.5 px`) the mismatch is 0.7 % — small
   enough that G1's conclusion stands.
2. At the L1 operating point (`sigma ≈ 0.9 px`) it is 4–12 %, and G1's frozen
   quality gate (`1.0 <= sigma <= 8.0`) rejects the frame outright.
3. Therefore a **new** estimator `gaussian_2d_integrated` was added
   (`src/optisys/estimators/gaussian_2d_integrated.py`) that fits the same
   area-integrated model the generator uses. The three G1 estimators are
   untouched and remain in the baseline; their source hash is unchanged.

This is why `MODEL_MISMATCH` is expected and *reported* for the point-sampled
fitter on L1 frames, rather than being suppressed by widening its bounds.

## 4. PRE-04 — calibration identifiability

The G1 chain identifies only `a = fx·B` and `b = cx - fx·tan(theta)` from a
1-D `u(Z)` curve. G2 keeps that restriction and adds:

* **Strategy A** (factory nominal): one fit per design on a *nominal* unit,
  applied unchanged to every perturbed assembly. Never reads assembly truth.
* **Strategy B** (per unit): every assembly is recalibrated from its own
  frames; the fitter sees only measured spot positions.

Measured on the nominal L1 unit at the baseline design (9 calibration
distances, medium condition):

| estimator | `a` [px·mm] | `b` [px] | calibration RMS [px] | residual over the 7 test distances [mm] |
|---|---:|---:|---:|---|
| centroid | 47 654.06 | 641.79 | 0.280 | 0.06 … 0.43 |
| gaussian_2d_integrated | 47 688.55 | 641.43 | 0.311 | 0.07 … 0.36 |

So a correctly refitted two-parameter system calibration leaves ≈0.23 mm RMS
on the *nominal* unit. The remaining error is the residual curvature of the
`a/Z + b` model against the real lens, not a calibration bug.

Model family M1 (`a/Z+b`) vs M2 (`a/(Z-c)+b`) is selected on the **validation**
split only. On the baseline design M2 collapses to M1 (`c → 0`), i.e. the
extra parameter buys nothing at this working range; the selection rule
therefore keeps M1 and records the decision.

## 5. Other PRE items

| ID | Resolution |
|---|---|
| PRE-05 | `tests_binding.json` binds totals to `code_sha256`, JUnit SHA-256, the exact command line and the exit code; disagreements mark the gate check failed. Tamper tests in `tests/unit/test_config_g2.py`. |
| PRE-06 | the duplicated `test_worker_policy_follows_measured_speedup` was replaced by a distinct property test (`test_worker_policy_defaults_to_single_process_without_measured_gain`); collection verified. |
| PRE-07 | `collect_environment` records total and available RAM, disk, CPU utilisation and GPU memory at run start; peak RSS is logged per stage. |
| PRE-08 | `FULL_WELL_SATURATION` and `ADC_CLIPPING` are separate flags and separate fractions; the ADC ceiling is 11 985 e⁻, below the 15 000 e⁻ full well. Tests in `tests/unit/test_tolerance_g2.py`. |
| PRE-09 | the CI workflow gained a G1 reproduction step; the remote run status is reported as `REMOTE_CI_NOT_VERIFIED` and is not claimed. |

## 6. Verdict

`G2_PRE_STATUS = PASS`. The baseline is unchanged, the regression was really
executed on this machine, and the two findings that matter
(discretisation mismatch, pinhole-vs-lens discrepancy) are quantified instead
of being smoothed over.
