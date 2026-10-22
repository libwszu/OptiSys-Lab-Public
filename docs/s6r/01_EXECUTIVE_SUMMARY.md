# Executive Summary

S6-R corrected the release draft's unsupported browser/screenshot/audit claims, preserved the historical S6 run, independently recalculated S6-C from the full assembly-level CSVs, and ran the requested local release checks. It did not rerun the 800 assemblies or change any scientific samples, seeds, thresholds, or frozen criteria.

## Results

- Original S6 run tree: 1,005 files, 39,157,936 bytes, initial tree SHA-256 `975a26c79c59f93f2f1f8827fb72966add4b38e50b51a5bafbaf60273091b8a2`; final comparison is recorded in the final status.
- Science: 800 unique assembly scenarios, 1,600 design rows, 800 matched pairs, zero source-weight ledger residual, 8,000 bootstrap replicates regenerated and matched exactly.
- Nominal 1×: paired mean difference `+18.05 pp` (95% cluster-bootstrap CI `[+17.74,+18.34] pp`); paired P05 `+13.67 pp` (CI `[+12.60,+14.93] pp`).
- Stress 2×: paired mean difference `+12.75 pp` (CI `[+11.65,+13.85] pp`); paired P05 `−5.69 pp` (CI `[−9.28,−0.90] pp`). The baseline/candidate marginal P05 values are 27.51% / 32.91%, which are not the paired P05 estimand.
- Final cross-scenario claim remains `TRADEOFF_OR_NO_SUPPORTED_GAIN`; the original nominal-only automatic claim remains preserved as historical evidence.
- Engineering: 482 pytest passed, 18 AppTest passed (six page render checks included), install PASS, Streamlit serve smoke PASS, CLI demos and reports executed.
- Browser: partial in-app interaction showed A/C/F and a Pareto-tab change at the exact loopback URL. The formal browser E2E is `NOT_RUN_POLICY_BLOCKED` because no local PNG/browser-version evidence could be saved and the native Windows Chrome capture path was stopped by the Computer Use URL safety check; no bypass was attempted. New S6 PNG and video are not delivered.

## Status layers

- `S6R_ENGINEERING_RELEASE_STATUS`: `PASS_WITH_DECLARED_DEVIATIONS` after independent package verification.
- `S6R_PORTFOLIO_MEDIA_STATUS`: `PARTIAL`.
- `S6R_SCIENCE_VERIFICATION_STATUS`: `PASS` for the stated assumed P1 estimands.
- `S6R_GPT_AUDIT_STATUS`: see `docs/s6r/S6R_FINAL_STATUS.json` and the external ZIP verification record.

No physical measurement, vendor lens validation, absolute optical power, or manufacturing yield is established.
