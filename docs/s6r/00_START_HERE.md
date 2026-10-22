# OptiSys-Lab S6-R Audit Package

This package audits the local S6-R recovery and release work for S6 run `20261021_024715_S6_P1`. It does not create Stage 7 or alter frozen historical results.

## Current verdict

- S6-C data integrity, pairing, weight ledger, metric recomputation, exact fixed-seed bootstrap replay, and Amendment 03 traceability: `PASS`.
- Nominal 1× estimand: `VERIFIED_CONDITIONAL_GAIN` within the assumed P1 model.
- All four registered scenarios: `TRADEOFF_OR_NO_SUPPORTED_GAIN`; the 2× paired P05 remains negative.
- Full pytest, clean installation, six-page AppTest, Streamlit service smoke, CLI examples, and generated reports have recorded results and logs.
- Formal browser E2E: `NOT_RUN_POLICY_BLOCKED`. A separate in-app browser did show A/C/F and a Pareto-tab interaction at the verified loopback URL, but it did not provide a local PNG path or browser version; native Windows Chrome capture was stopped by the URL safety check. New S6 PNGs and video were not delivered.
- Empirical validation: `NOT_AVAILABLE`; remote CI: `NOT_RUN`; GPU: `NOT_TESTED`.

## Fastest independent science check

From the extracted package root, run:

```powershell
python -m pip install -r requirements-verify.txt
python repro/verify_s6r.py --root .
```

The verifier reads the complete assembly-level data included under `runs/20261021_024715_S6_P1/s6_c_assemblies/`; it does not rerun any ray traces.

## Evidence map

- `02_SCIENTIFIC_REVIEW.md`: estimands, results, rule timeline, model limits.
- `03_VALIDATION_MATRIX.md` and `04_COMPUTE_AND_TESTS.md`: actual commands, exit codes, outputs, and scopes.
- `05_RELEASE_VERIFICATION.md` and `06_KNOWN_ISSUES.md`: publication state and outstanding media/destination issues.
- `docs/s6/`: original criteria, amendments, and freeze hashes.
- `runs/20261021_024715_S6_P1/`: selected immutable run contracts and source data at original relative paths.
- `validation/`: install, test, CLI, AppTest, service, and browser evidence.
- `RELEASE_CANDIDATE_V2/`: verified README, release manifest, figures, raw evidence, and explicitly historical S5 screenshots.

The S6 source tree SHA-256 at intake and final comparison are listed in `docs/s6r/BASELINE_HASHES.json`. G0–G4/S5 package hashes are retained without nesting their historical ZIPs.
