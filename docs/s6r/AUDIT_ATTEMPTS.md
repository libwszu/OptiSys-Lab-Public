# Audit Build Attempt Log

1. **Verifier attempt 001:** the first invocation exited before reading the ZIP because `scripts/s6r_verify_audit.py` missed a `datetime` import. The traceback is preserved in `artifacts/s6r/audit_trial/verify_attempt_001_error.txt`. The import was fixed and the verifier rerun; no scientific or release source file changed.
2. **Preflight package:** built under `artifacts/s6r/audit_preflight/20261021_092952_S6R_PREFLIGHT/`. It was 12,288,952 bytes with 442 members, 440 managed files, and 39,691,725 managed uncompressed bytes. ZIP CRC, path safety, manifest coverage, extracted science replay, six-page release link/claim checks, tamper rejection, missing-file rejection, and same-environment byte rebuild all passed.
3. **Intermediate finalization candidates:** `_AUDIT/20261021_092952_S6R/`, `_AUDIT/20261021_094221_S6R/`, `_AUDIT/20261021_094647_S6R/`, and `_AUDIT/20261021_095651_S6R/` passed their respective checks but were superseded by later status/path consistency corrections. They are retained locally for audit history and are not the handoff bundle.
4. **Final package:** built under `_AUDIT/20261021_100205_S6R/`. Its ZIP, content hashes, extracted replay, release link/claim check, tamper control, missing-file control, and same-environment byte rebuild are recorded in the external `AUDIT_VERIFY_RESULT.json` and `AUDIT_ZIP_SHA256.txt` sidecars.

The preflight ZIP is a test artifact under ignored `artifacts/`; only the final ZIP is the handoff bundle.
