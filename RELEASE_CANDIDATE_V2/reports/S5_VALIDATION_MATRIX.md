# Stage 5 validation matrix

| Gate | Result | Evidence / scope |
|---|---|---|
| S5-BASE | PASS | G0–G3 protected snapshot: 21/21 checks; G4 run tree 37 files and digest unchanged; G4 audit ZIP SHA matches and full extraction replay/tamper verification passes; 169 pre-existing dirty/untracked files were hashed at takeover and preserved. |
| S5-REF | PASS | 4,096 NA=0.22 rays/design × four spherical interfaces; 32,768 surface rows; max surface coordinate delta `1.42e-13 mm`; max direction delta `1.89e-15`; zero classification/terminal mismatches and closed source-weight ledgers. |
| S5-ANG | PASS | Frozen five angular bins recomputed with the total source-weight denominator; radius, angle, azimuth and surface-incidence marginal tables retain denominators and failure outcomes. |
| S5-FCS | PASS | Five registered target planes per design; independent sphere/Snell retrace and Optiland rerun at all planes; 40,960 per-ray comparison rows; target coordinate differences remain below `3.8e-14 mm`. |
| S5-TGT | PASS | Four circle radii and one 2 x 2 mm square, with source-weight denominator fixed at 1.0; unconditional encircled-weight curves retained. |
| S5-MECH | QUALIFIED | Surface radii, sag and edge thickness recomputed; edges positive. G4 candidate L1 gets a non-manufacturing `EDGE_THICKNESS_ASSUMED_LOW` warning at 0.158 mm; no vendor drawing or outer diameter. |
| S5-DES | PASS_WITH_SCOPE | Equal 12/12 mm clear apertures and fixed 1 mm target; position-only search and independent 4,096-ray holdout; `P1_SUPPORTED_TRADEOFF`; paired ray bootstrap, no assembly-level tolerance. |
| S5-UI | PASS | All six page scripts exercised through AppTest in the full suite; separate real Streamlit process returned `/_stcore/health=ok`, root HTTP 200, clean shutdown and port release; broken-import negative control documented the HTTP health limitation. |
| S5-PORT | PARTIAL | Clean install, reduced CLI examples, derived G3/G4 reports, real Edge screenshots for A/C/F and browser interaction completed. Video not delivered; remote CI not run. |
| S5-TEST | PASS | Final fresh-environment suite: 461 passed / 0 failed / 0 errors / 0 skipped (after adding the report-routing regression guard); exact outer wall and JUnit time recorded in test evidence. |
| S5-AUDIT | PASS | Final ZIP member count, manifest coverage, exact size and SHA are recorded outside the ZIP. Clean extraction replay passes; altered target-coordinate evidence and deleted mechanical evidence are both rejected; security/path scan passes. |

Historical G2 remains `QUALIFIED_ONLY`; historical G4 optical verification remains `QUALIFIED`. Empirical status is `NOT_AVAILABLE`. S5 statuses do not overwrite either historical record.
