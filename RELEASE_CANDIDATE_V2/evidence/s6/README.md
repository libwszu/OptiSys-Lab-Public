# S6 evidence index

Run ID: `20261021_024715_S6_P1`. This folder contains source-level S6 records copied from the local run. Original source hashes and the full run-tree hash are recorded in `docs/s6r/BASELINE_HASHES.json`.

## Available evidence

- `run_records/`: compute plan and measured profile, S6-A reference summary, S6-B boundary results, holdout freeze, assembly statistics, and final C adjudication.
- `raw_data/`: full assembly-by-design samples, pair comparisons, 2,000 bootstrap replicates per scenario, failure breakdown, assembly manifest, plot data, and selected S6-A/B cross-check records.
- `../s6/`: figures for boundary scans and the assembly comparison; table data are in `raw_data/`.
- `reports/s6/S6_ASSEMBLY_SCIENTIFIC_AUDIT_FINAL.md`: the original report. It predates the independent S6-R recomputation and remains a historical source document.

## S6-R verification status

- Formal S6 browser E2E: `NOT_RUN_POLICY_BLOCKED`. A separate CUA in-app browser at verified URL `http://127.0.0.1:8508/` partially showed A/C/F and a Pareto-tab change, but browser version, live console/error log, and local PNGs were not captured.
- New S6 screenshot PNGs: `NOT_DELIVERED`. The browser tool did not expose a local screenshot output path. The native Windows Chrome capture path was stopped by its active-URL safety check; no bypass was attempted.
- S6-R GPT audit ZIP: `PASS` after manifest/hash verification, independent extraction/replay, tamper rejection, missing-file rejection, and same-environment byte rebuild. Its local location and external SHA-256 sidecar are recorded in `docs/s6r/S6R_FINAL_STATUS.json`.
- The files here document assumed P1 and simulated tolerance distributions. They are not experimental or vendor validation.

The existing screenshots in `screenshot_evidence/` are explicitly S5 historical images. The S6 browser action log and status are in `docs/s6r/S6R_BROWSER_E2E.json`.
