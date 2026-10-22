# S6-R Recovery Plan

Captured on 2026-10-21T08:16:45.223517+00:00 from `<PROJECT_ROOT>` at commit `PRIVATE_SOURCE_REVISION` on branch `main`.

## Current checkpoint

- R0 complete: pre-change hashes are recorded; S5-mislabeled claims were corrected in `RELEASE_CANDIDATE_V2/`; all nine historic audit ZIPs and the S6 freeze/amendment hashes were rechecked.
- R1 complete: `repro/verify_s6r.py` independently verified 800 assembly pairs, reconciled the 1,600 design rows and weight ledgers, and exactly replayed all 8,000 bootstrap rows. See `S6R_SCIENCE_RECOMPUTATION.md`.
- R2 complete: clean install, full pytest, CLI demos and reports, six-page AppTest, and Streamlit server smoke all have logs and real exit codes. The 976 nm reduced demo has `run_status=PARTIAL` as expected for its smaller sample.
- R3 browser interaction complete in the verified in-app browser URL; no local S6 PNG was saved. Native Windows Chrome capture stopped at the Computer Use URL safety check. Video is `NOT_DELIVERED`.
- R4/R5 audit package verification is complete; the final ZIP, external SHA-256 sidecar, clean extraction/replay, manifest coverage, same-environment rebuild, and tamper/deletion negative controls are recorded in `S6R_FINAL_STATUS.json` and `AUDIT_VERIFY_RESULT.json`.

## Preservation boundary

- Preserve the original S6 run tree hash in `BASELINE_HASHES.json`; do not modify `runs/20261021_024715_S6_P1/` or `docs/s6/` frozen source files.
- The existing `RELEASE_CANDIDATE_V2/` was an unverified draft at intake. Its original tree hash is recorded; the README, evidence index, checklist, and manifest were corrected in place, with before/after details in `R0_CLAIM_CORRECTIONS.md`.
- Record all new diagnostics, test outputs, and the GPT audit package under new S6-R paths.
- G0–G4/S5 historical artifacts remain read-only. See the freeze-manifest verification records in `BASELINE_HASHES.json`.

## Work order

1. R0: finish intake hash checks, record missing sources, and correct the release claims.
2. R1: independently recompute S6-C pairing, weight ledger, percentiles, and paired cluster bootstrap from original per-assembly records; compare to frozen criteria and Amendment 03 while retaining original automatic status.
3. R2: run the isolated Python 3.11.9 install/CLI reports, six-page AppTest, clean-basetemp full pytest, and real Streamlit server smoke with captured exit codes and logs.
4. R3: build a linked and internally consistent verified release copy; attempt browser evidence only if the active browser URL can be verified safely.
5. R4/R5: package the complete required science and run evidence, verify hashes after clean extraction, and prove tamper/deletion rejection before recording the final state.

## Initial environment

- Python 3.11.9 is available at `<PROJECT_ROOT>\.venv_s6_release_check\Scripts\python.exe`.
- S6-R created and validated the clean environment at `.venv_s6r_release/`; the installed package versions are in `artifacts/s6r/environment/`.
- The host has 12 logical CPUs, 31.41 GiB RAM, and approximately 14.38 GiB free at intake.
- No process command line identified an OptiSys, Streamlit, or pytest task at intake; unrelated Python and browser processes were present.
- No Git remote is configured. The GitHub account has multiple unrelated optical repositories, so no remote is selected yet.
