# Known Issues

- No standalone `docs/s6/S6_PRE_REGISTRATION.md` was found. The result-before-holdout acceptance criteria and holdout freeze supply the operative rule; Amendment 03 is post-result and consistent with them.
- Formal browser E2E is `NOT_RUN_POLICY_BLOCKED`; partial in-app interaction showed A/C/F and a Pareto-tab change. Browser version, live console/error log, and local PNG files were not captured. Native Windows Chrome capture was stopped by its URL safety check, with no bypass.
- S6 screenshots and real video are `NOT_DELIVERED`.
- The 976 nm CLI showcase uses 512 rays × 2 assemblies and returns a run marked `PARTIAL`. It is a reduced demo, not the frozen G4 holdout.
- S6-A is a model-internal cross-check, not a manufacturer lens qualification. S6-B remains `OPTIMUM_NOT_BRACKETED`. S6-C applies only to assumed P1 geometry and simulated errors.
- Stress paired P05 uses a tail estimated from 200 assemblies and is sensitive to tail sampling/model assumptions. Its bootstrap interval does not certify yield.
- Absolute optical power, real source far field, actual vendor lens part, mechanical travel, crystal size, heat response, and physical validation remain unavailable.
- Remote CI is `NOT_RUN`; GPU is `NOT_TESTED`; empirical validation is `NOT_AVAILABLE`.
- A GitHub destination is not configured or selected. Existing account repositories are unrelated to this software project.
