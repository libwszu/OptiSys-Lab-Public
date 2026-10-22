# R0 Release Claim Corrections

These corrections are derived from the file hashes captured before edits in `BASELINE_HASHES.json`. The original S6 source run, its CSVs, and S5 screenshot files remain unchanged.

| Artifact | Intake claim | Corrected claim | Evidence |
|---|---|---|---|
| `RELEASE_CANDIDATE_V2/README.md` | Said the S6 browser screenshots and run record were in `evidence/s6/released_demo/`, and cited `_AUDIT/20261021_024715_S6_P1/` as an available audit package. | The S6 browser directory and S6-R audit ZIP were absent at intake. README now labels browser E2E `NOT_RUN`, new S6 screenshots `NOT_DELIVERED`, and the audit ZIP `NOT_BUILT` until verified. | Intake map and pre-edit V2 tree hash in `BASELINE_HASHES.json`. |
| `RELEASE_CANDIDATE_V2/DEMO_CAPTURE_CHECKLIST.md` | Checked Edge E2E as complete and claimed S6 captures existed. | Browser E2E and new screenshots are unchecked and explicitly `NOT_RUN` / `NOT_DELIVERED`; historic S5 screenshots are identified by run. | `screenshot_evidence/browser_e2e.json` reports run `20261020_210201_S5_HNA`; its URL, screenshot hashes, and paths identify S5 evidence. |
| `RELEASE_CANDIDATE_V2/release_candidate_manifest.json` | Used an S5 schema with `browser_e2e: PASS` and `audit_status: PASS` next to S6 material. | Replaced with an S6-R status map. The S5 browser PASS is retained only as `PASS_HISTORICAL_ONLY`; current S6 E2E is `NOT_RUN`, screenshots are `S5_HISTORICAL_ONLY`, and GPT audit is `NOT_BUILT` until checked. | Pre-edit manifest hash in `BASELINE_HASHES.json`; corrected file explicitly records the S5 run ID. |
| `RELEASE_CANDIDATE_V2/evidence/s6/README.md` | Said an S6 `GPT_AUDIT.zip` could be replayed and said new S6 screenshots/E2E would be in an absent `released_demo/`. | Marked the S6 browser folder/screenshots and audit ZIP as absent at intake; any later output requires actual files and independent validation. | `S6R_INPUT_MAP.json`. |

## Before and after

- The pre-correction hashes of all 79 files in the draft directory are in `BASELINE_HASHES.json` (`RELEASE_CANDIDATE_V2` tree SHA-256 `cc45bff33647d1a6a2a60cbec276eed75747bc2627327611b08ea2ffb779c6a0`).
- The initial bytes are not regenerated or relabeled as S6 evidence. S5 images and their S5 E2E JSON are left intact as historical evidence.
- After R2 and R3, the README and release manifest will be updated with actual run results, hashes, and any remaining not-run states.
