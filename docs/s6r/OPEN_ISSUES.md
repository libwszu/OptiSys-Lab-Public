# S6-R Open Issues and Declared Deviations

## P1 — media delivery

- `S6R_BROWSER_E2E=NOT_RUN_POLICY_BLOCKED`: partial IAB interactions opened A/C/F and switched the C-page Pareto tab at a verified localhost URL. The browser version, live console/error log, and local PNG evidence were not available; the native Windows Chrome path was stopped by the Computer Use URL safety check with no workaround.
- `S6R_SCREENSHOTS=NOT_DELIVERED`: CUA displayed page state but did not expose a local PNG destination.
- `S6R_VIDEO=NOT_DELIVERED`: no authorized screen recording was made.
- `S6R_PORTFOLIO_STATUS=PARTIAL`: media remains incomplete even though local code, UI and science verification passed.

## P1 — GitHub destination

- No Git remote is configured.
- The connected GitHub account has multiple optical repositories, but the accessible `engineering-optics-lab` / `engineering-optics-lab-demo` repositories are unrelated educational projects. No repository named OptiSys-Lab was found in the account list.
- Do not push into either unrelated repository. The user must provide the exact destination URL or create/select a new repository and specify its visibility before upload.

## P2 — source-document provenance

- The standalone `docs/s6/S6_PRE_REGISTRATION.md` is `MISSING_SOURCE`. The frozen acceptance criteria and pre-result holdout freeze contain the applicable rule; Amendment 03 matches that rule and changes no metrics, thresholds, or samples.
- The S6 model uses assumed P1 N-BK7 optics and simulated tolerance/source distributions. Physical validation remains `NOT_AVAILABLE`.
- S6-B remains `OPTIMUM_NOT_BRACKETED` for both focus and L2 position. S6-C does not revise that boundary result.

## Open external validation

- Remote CI: `NOT_RUN`.
- GPU workload: `NOT_TESTED`.
- Physical experiment / vendor part verification: `NOT_AVAILABLE` / `NOT_VERIFIED`.
