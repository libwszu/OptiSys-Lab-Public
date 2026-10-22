# Compute and Test Record

## Host and clean installation

- Intake hardware: 12 logical CPUs, 31.41 GiB visible RAM, about 14.38 GiB free. No OptiSys pytest or Streamlit process was active at intake.
- New environment: `.venv_s6r_release`, CPython 3.11.9.
- Installation: `python -m pip install -e ".[dev,ui,optics]"`; exit 0, 218.19 seconds. Full stdout/stderr and `pip freeze` are included in `validation/environment/`.
- Installed key versions: NumPy 2.4.6, pandas 3.0.6, SciPy 1.17.1, Optiland 0.6.3, Streamlit 1.66.0, Matplotlib 3.11.2, PyYAML 6.0.3, pytest 9.1.1, psutil 7.2.2.

## Full regression

Command: `.venv_s6r_release/Scripts/python.exe -m pytest -q --basetemp=<fresh s6r basetemp> --junitxml=artifacts/s6r/tests/full_junit.xml`.

- Exit code `0`; 482 passed, 0 failed, 0 errors, 0 skipped.
- Parent wall clock: `191.27 s`; timeout: `300 s`.
- Basetemp was newly created without deleting any prior run. The older `scripts/make_basetemp.py` deletes stale paths; S6-R used `scripts/s6r_make_basetemp.py` instead.
- Full stdout/stderr, JUnit, run metadata and the exact basetemp are included.

## App, demos and reports

- Standalone AppTest of `tests/ui/test_pages_render.py`: 18 passed, 0 failed/skipped, exit 0, 25.30 s. Six parametrized page checks A–F passed; interaction/failure assertions also passed.
- Streamlit server smoke: loopback port 20274, health endpoint body exactly `ok`, root returned HTTP 200 with a 6,467-byte Streamlit shell, log had no traceback, server exited and port released.
- 650 nm: `g3-demo`, one assembly, one worker; exit 0, 29.70 s, `status=PASS`, 63 rows. Run ID `20261021_084255_G3_ea57a83b`.
- 976 nm: `pump976`, 512 rays and 2 assemblies; exit 0, 13.77 s. Run ID `20261021_044354_G4_36e42f82_63f8`; run status is `PARTIAL`, reflecting the reduced demonstration sample.
- HTML and Markdown report commands completed with exit 0 for both run directories. The original S6 frozen run was not modified.

## Browser and science compute

- A partial browser session used `http://127.0.0.1:8508/` after server health and shell verification. A, C and F rendered; the C-page Pareto tab was switched. The server was stopped and port 8508 released. Formal browser E2E remains `NOT_RUN_POLICY_BLOCKED` because browser-version/console capture and PNG persistence were unavailable.
- A native Windows Chrome screenshot attempt ended when the Computer Use tool rejected the active window because it could not reliably determine the preexisting browser URL. No workaround was attempted. The in-app browser did not expose a local PNG output path; S6 screenshot status is `NOT_DELIVERED`.
- The original registered S6-C work represented 1,638,400 design-ray traces. S6-R did not rerun them. It recalculated assembly-level metrics and exactly regenerated 8,000 bootstrap replicates from the frozen CSVs.
- GPU workload `NOT_TESTED`; physical optics measurements `NOT_AVAILABLE`; remote CI `NOT_RUN`.

## Audit package preflight

- A preflight package built at 12,278,952 bytes with 442 ZIP members, 440 manifest-managed members, and 39,691,725 uncompressed managed bytes.
- Independent extraction and `repro/verify_s6r.py` passed. The manifest and SHA list covered all managed files, `zipfile.testzip()` passed, an altered CSV was rejected (exit 1), a deleted required registry file was rejected (exit 1), and a canonical same-Python/zlib ZIP rebuild matched byte-for-byte.
- The first verifier launch stopped before checks because of a missing `datetime` import; the exact traceback is retained at `artifacts/s6r/audit_trial/verify_attempt_001_error.txt`. The import was fixed; the preflight and final-package checks were rerun.
- The final GPT ZIP is verified separately. Its actual size, SHA-256, manifest coverage, and external checksum path are in `docs/s6r/S6R_FINAL_STATUS.json` and the sibling `_AUDIT/<run-id>/AUDIT_ZIP_SHA256.txt`.
