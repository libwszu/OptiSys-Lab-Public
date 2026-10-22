# GPT Independent Review Instructions

Review this package as a technical and scientific audit, not as a request to improve the result.

1. Verify `manifest.json` and `SHA256SUMS.txt`; confirm no missing, extra, duplicated, absolute, traversal, or unexpected executable members.
2. Run `python repro/verify_s6r.py --root .` from the extracted package. Confirm 800 unique scenario-assembly pairs, 1,600 design rows, 8,000 exact bootstrap matches, source-weight closure, and agreement with both original statistics JSON files.
3. Inspect the frozen acceptance criteria and pre-result holdout freeze. Determine whether Amendment 03 applies the existing cross-scenario rule without changing samples, thresholds, or metrics. The standalone `S6_PRE_REGISTRATION.md` is missing and is disclosed.
4. Keep the nominal 1× estimand separate from the four-scenario aggregate verdict. In particular, do not conflate stress marginal P05 values (27.51% / 32.91%) with the paired P05 difference (−5.69 pp).
5. Consider the finite 200-assembly stress tail and assumed P1/tolerance model. Do not treat a bootstrap interval as a manufacturing-yield certification or the one-ray L2 clipping difference as standalone failure-rate proof.
6. Preserve G2 `QUALIFIED_ONLY`, G4 `QUALIFIED`, S5 `P1_SUPPORTED_TRADEOFF`, empirical `NOT_AVAILABLE`, remote CI `NOT_RUN`, GPU `NOT_TESTED`, and the browser screenshot/video deviations.
7. Report any failure with the exact file and value. Do not modify source evidence or replace an adverse result with a new simulation.
