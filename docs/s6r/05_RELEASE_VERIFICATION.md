# Release Verification

## Release states

- `S6R_ENGINEERING_RELEASE_STATUS=PASS_WITH_DECLARED_DEVIATIONS`; the final GPT audit package independently verified.
- `S6R_PORTFOLIO_MEDIA_STATUS=PARTIAL`: no new S6 PNG and no real video were delivered; remote CI was not run.
- `S6R_SCIENCE_VERIFICATION_STATUS=PASS` for the registered assumed P1 scope.
- `S6R_GPT_AUDIT_STATUS=PASS`; the final ZIP and external SHA-256 sidecar are in the local `_AUDIT/20261021_100205_S6R/` folder.
- `S6_C_ALL_SCENARIO_VERDICT=TRADEOFF_OR_NO_SUPPORTED_GAIN`.
- `G2_SCIENCE_INHERITED=QUALIFIED_ONLY`; `G4_SCIENCE_INHERITED=QUALIFIED`.

## Claims corrected at intake

The original candidate stated that an S6 `released_demo/` and an S6 GPT ZIP were available and marked Edge E2E complete. The only browser record and A/C/F images identified S5 run `20261020_210201_S5_HNA`. R0 recorded their original hashes, corrected README/checklist/manifest, and retained the S5 files unchanged. A separate IAB session showed the A/C/F pages and a Pareto-tab interaction, but the formal browser E2E remains `NOT_RUN_POLICY_BLOCKED` because the browser tool did not expose a local PNG path or browser version and the native Windows Chrome path was blocked by the active-URL safety check.

## Reproducible local commands

From the repository root in PowerShell:

```powershell
py -3.11 -m venv .venv_s6r_release
.\.venv_s6r_release\Scripts\python.exe -m pip install -e ".[dev,ui,optics]"
.\.venv_s6r_release\Scripts\python.exe -m pytest -q
.\.venv_s6r_release\Scripts\python.exe -m streamlit run app/main.py
```

The S6-R clean-install log verifies the install command. The release README includes the exact reduced demo commands and warns that the 976 nm sample is `PARTIAL`.

## Images and audience

The S6 assembly/scan figures are source-linked scientific plots. Existing A/C/F UI PNGs remain identified as historical S5 browser captures. New S6 browser screenshots and authentic video are `NOT_DELIVERED`.

No Git remote is configured. No upload was made to the account's unrelated optical education repositories. Publication requires an exact destination repository and visibility choice from the user.
