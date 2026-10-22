# S5 baseline verification

Run ID: `20261020_210201_S5_HNA`
Checked UTC: `2026-10-21T01:07:55+00:00`

| Protected baseline | Result | SHA-256 / detail |
|---|---|---|
| G0-G3 official protected paths | PASS (21 checks, 0 failures) | snapshot from G4 |
| G4 official run tree | PASS | `c0151ad8acec01f7db07e7a958537ded4a549948418b7db81db56d450cac1378` (37 files) |
| G4 audit archive | PASS | `866d305aa87920c2068fb964ba4c3c7ff401964391ddf452bb022ed76ce9914d`; 282 members / 280 manifest files |
| Git HEAD | unchanged | `PRIVATE_SOURCE_REVISION` |

The worktree was already dirty: 169 porcelain entries (169 flattened modified/untracked files) were hashed at S5 takeover. No reset/clean or prior-run edit was performed.

G4 ZIP verifier command: `python scripts/verify_g4_audit_package.py _AUDIT/20261020_133555_G4_ec3e2813_0e48/OptiSysLab_G4_20261020_133555_G4_ec3e2813_0e48_GPT_AUDIT.zip`. Exit code 0; outer wall 1.329 s. Full stdout/stderr are in the run evidence.
