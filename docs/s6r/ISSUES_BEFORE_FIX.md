# Issues Before S6-R Fixes

| ID | Priority | Finding at intake | Evidence | Handling |
|---|---|---|---|---|
| R0-01 | P0 | V2 README claims S6 browser captures and a GPT audit ZIP were delivered at paths that do not exist. | `RELEASE_CANDIDATE_V2/README.md`; `S6R_INPUT_MAP.json` marks the claimed path `MISSING_SOURCE`. | Preserve the draft hash; create a corrected verified release copy and retain the old draft unchanged. |
| R0-02 | P0 | V2 capture checklist marks Edge E2E done, while its only browser record is S5 run `20261020_210201_S5_HNA` and points to historical S5 screenshots. | `RELEASE_CANDIDATE_V2/DEMO_CAPTURE_CHECKLIST.md`; `screenshot_evidence/browser_e2e.json`. | Do not count the old record as S6 browser proof. Attempt a safe current-session check only after validating localhost URL; otherwise mark `NOT_RUN_POLICY_BLOCKED`. |
| R0-03 | P0 | Draft release manifest declares S5 browser E2E and audit status as if they described the S6 release. | `RELEASE_CANDIDATE_V2/release_candidate_manifest.json`. | Replace in verified copy with separate engineering, science, media, and audit statuses backed by actual evidence. |
| R0-04 | P1 | The named standalone S6 preregistration file is absent. Existing acceptance criteria, run freeze and holdout freeze are present. | `S6R_INPUT_MAP.json`. | Record `MISSING_SOURCE`; use only located frozen rules and preserve any limitation in the adjudication. |
| R0-05 | P1 | No Git remote is configured and available account repositories are unrelated educational optical repositories. | `BASELINE_HASHES.json`; GitHub repository inventory. | Do not push to an unrelated repo. Confirm or establish an explicitly selected repository after the final files are reviewable. |
| R0-06 | P1 | `.venv_s6_release_check/` is currently untracked and not covered by `.gitignore`. | Intake `git status`; `.gitignore`. | Add a narrow ignore rule before preparing any upload, and exclude local environments from release manifests. |
| R0-07 | P2 | Browser E2E and new S6 screenshots have not yet been proven; video, remote CI, GPU and empirical optics remain undeclared. | V2 evidence map and S6 prompt. | Preserve honest status unless this turn produces direct evidence. |

No frozen G0–G4/S5/S6 source file was edited to create this issue register.
