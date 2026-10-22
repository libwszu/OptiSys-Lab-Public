# Case: triangulation (main)

Status at G0: **geometry only (L0)**.

- Active configuration: `configs/triangulation_v0.yaml`
- Run command: `python -m optisys simulate --config configs/triangulation_v0.yaml`
- Evidence: `runs/<run_id>/` and the frozen audit ZIP under `_AUDIT/`

Not implemented yet (see `docs/PROJECT_STATE.md`):
- L0 spot rendering and CMOS noise (G1)
- spot estimators, calibration, test split (G1)
- lens/PSF adapter (G2)
- tolerance and robust optimisation (G2)
- GUI and automated report (G3, report HTML exists but is G0-scoped)
