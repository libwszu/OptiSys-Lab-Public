# Validation Matrix

| Area | Result | Evidence / scope |
|---|---|---|
| R0 intake hashes | `PASS_WITH_DOCUMENTED_SOURCE_EVOLUTION` | `BASELINE_HASHES.json`; all nine G0–G4/S5 ZIP hashes pass; G3 pre-change source differences reconcile to later immutable G4/S5 source members |
| S6 original run preservation | `PASS` | Full original S6 tree SHA-256 compared before and after; final hash comparison in `S6R_FINAL_STATUS.json` |
| Release false claims | `0` | V2 README, evidence index, checklist and manifest corrected; S5 screenshot record remains labeled historical |
| S6-C row completeness and pairing | `PASS` | 800 unique scenario-assembly IDs, 1,600 design rows, 800 pairs, source and input hashes match |
| S6-C source-weight ledger | `PASS` | 1,600 design ledgers; maximum absolute residual `0` |
| S6-C metrics and plots | `PASS` | Recomputed from full source samples and reconciled against both statistics JSON files and plot data |
| S6-C bootstrap | `PASS` | 2,000 per scenario, seed `8064001`, complete assembly resampling; 8,000 exact row matches |
| Amendment 03 traceability | `PASS` with missing standalone prereg file disclosed | Frozen acceptance criteria and holdout freeze agree; Amendment 03 is post-result and changes no metrics/sample/thresholds |
| S6-A | `PASS` subject to model scope | Summary hash matches the pre-holdout freeze; 25 matrix cases and 10 controls reported passing |
| S6-B | `OPTIMUM_NOT_BRACKETED` | Focus and L2 searches remain boundary/plateau diagnostics |
| S6-C nominal 1× | `VERIFIED_CONDITIONAL_GAIN` | Assumed P1 model only |
| S6-C all scenarios | `TRADEOFF_OR_NO_SUPPORTED_GAIN` | Stress paired P05 negative with CI below zero; one extra L2 blocked ray |
| Fresh install | `PASS` | Python 3.11.9; `.[dev,ui,optics]`; actual pip freeze and logs included |
| Full pytest | `PASS` | 482 passed, 0 failed, 0 errors, 0 skipped; exit 0; wall 191.27 s |
| AppTest | `PASS` | 18 passed; six A–F page checks each pass without exceptions |
| Streamlit real serve | `PASS` | Port 20274; exact health body `ok`, root 200/6,467 bytes, no traceback, shutdown released port |
| 650 nm CLI + report | `PASS_WITH_DECLARED_SCOPE` | G3 demo exit 0; 1 assembly, 63 rows; HTML and Markdown report generated |
| 976 nm CLI + report | `PASS_WITH_DECLARED_SCOPE` | Exit 0; 512 rays × 2 assemblies; run status `PARTIAL`; HTML and Markdown report generated |
| Formal browser E2E | `NOT_RUN_POLICY_BLOCKED` | Partial IAB interaction showed A/C/F and the C-page Pareto-tab change at verified URL `http://127.0.0.1:8508/`; browser version/console log were not captured and no local PNG path was available; native system-browser capture was stopped by URL safety policy |
| New S6 screenshots | `NOT_DELIVERED` | Computer Use blocked native Chrome screenshot path; IAB screenshot API did not expose local PNG path |
| Video | `NOT_DELIVERED` | No authentic recording produced |
| Remote CI / GPU / physical test | `NOT_RUN` / `NOT_TESTED` / `NOT_AVAILABLE` | No remote CI run, GPU workload, or hardware data |
| GPT audit package | `PASS` | Final archive under `_AUDIT/20261021_100205_S6R/`; 445 members (443 managed), clean replay, release-link/claim check, tamper/deletion rejection, same-environment byte rebuild; outer hash in `AUDIT_ZIP_SHA256.txt` |
