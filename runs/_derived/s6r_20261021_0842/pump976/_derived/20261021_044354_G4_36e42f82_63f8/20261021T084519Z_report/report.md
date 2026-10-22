# OptiSys-Lab G4 工程报告 · 20261021_044354_G4_36e42f82_63f8

**SIMULATED · P1_QUALIFIED**  
Engineering: `PARTIAL` · Optical verification: `QUALIFIED` · Tolerance: `PARTIAL` · Empirical validation: `NOT_AVAILABLE`

**Inherited G2 science status: `QUALIFIED_ONLY`.**

G2 tokens: `G2_PREREG_FEASIBILITY_NOT_ESTABLISHED, G2_FINAL_PANEL_DEVIATION, G2_FINAL_DISTANCE_LEAK_INTO_DEVELOPMENT, CALIBRATION_MODEL_SELECTION_NOT_EXECUTED_AS_REGISTERED`.

## Scope

Geometric ray density proxy from a 976 nm multimode fiber through two assumed lenses. Absolute power is `UNKNOWN`; no result is W/mm². No experimental validation was available.

## Run files

- `target_plane_metrics.csv`: 8 rows
- `ray_balance.csv`: 8 rows
- `design_comparison.csv`: 3 rows
- `ray_count_convergence.csv`: fixed 2k/8k/32k counts × three source seeds per design; status `PASS`
- `oat.csv`: 30 rows
- `tolerance_samples.csv`: 8 rows (complete file; HTML table is only a preview)
- core CSV/NPZ/JSON evidence SHA-256 values are embedded in the HTML provenance block.
- Status: `PARTIAL`; claim: `QUALIFIED`

## Limitations

- G4-01: no vendor part numbers / measured source power / empirical pump spot; all are ASSUMED or UNKNOWN
- G4-02: P0 ideal thin-lens full-NA result differs materially from assumed P1 singlet trace; no full-NA physical validation
- G4-03: P1 adapter covers centered singlets only; tolerance/misalignment sweep is P0
- G4-04: no experiment; empirical validation NOT_AVAILABLE

No Fresnel/coating loss, diffraction, modal interference, scatter, crystal absorption, or Er:YAP resonator physics is included. Inherited G2 conclusions remain `QUALIFIED_ONLY`.
