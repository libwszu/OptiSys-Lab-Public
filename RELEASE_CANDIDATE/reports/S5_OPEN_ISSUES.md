# Stage 5 known issues and failure record

## Still open

- No fiber vendor profile, measured far-field, calibrated source power, lens part number/drawing, coating data, measured target plane or crystal dimensions are available. Absolute efficiency, W/mm², measured spot, crystal absorption and heating remain unavailable.
- The `-25 mm` focus sample is the lower edge of the frozen grid. It shows that target-plane position strongly affects this assumed model, but does not bracket an exact optimum. Moving the physical receiving element is a separate strategy with its own packaging constraints.
- S5-C is a nominal equal-clear-aperture position trade-off with ray-level bootstrap only. No assembly-level P1 tolerance or manufacturing feasibility was tested.
- G4's historical P1 result remains `QUALIFIED`; S5 cross-checks that assumed model and does not validate real optics.
- Video was not captured. Browser screenshots were captured from an actual local Edge session. Remote CI and GPU were not tested.

## Resolved during this run

- A sphere test initially expected no hit for a reverse-propagating ray, but the independent solver correctly found a forward intersection. The test case was changed to a ray directed away from the physical cap. The final test asserts that case and separate L1/L2 aperture-block outcomes.
- The first Stage 5 plotting attempt formatted CSV number strings as categorical values and placed labels under the axes. The plot code now casts metric values to floats, uses separate legends/spacing, and the final PNGs were visually inspected.
- The first clean-environment full pytest run had two README assertions fail because the S5 summary had dropped the inherited G4 literal `NOT_MEASURED`. The README now preserves that G4 status while also stating `S5_EMPIRICAL_STATUS=NOT_AVAILABLE`; the complete suite was rerun and passed with no skips.
- The first CLI derived-report attempt on a G3 demo reached the G2 renderer and failed on a missing `gate_checks` field. `report --run` now routes G3/G4 runs through `ReportService`. New G3 and reduced G4 CLI reports both generate under `_derived`, and both source run directories remain unchanged. A regression test covers G3/G4 routing.
- The first browser screenshots were captured before the Streamlit script finished rendering. They are retained as development attempts in local S5 artifacts; final A/C/F screenshots were recaptured after the `Stop` indicator disappeared and visible content checks passed.
- The first staged audit replay exposed two verifier mapping errors (Optiland coordinate field names and launch-angle use of the exit ray). The independent verifier was corrected; the final standard-library replay passes all 32,768 surface records and registered summaries. The deterministic ZIP has 161 manifest-covered members, clean extraction replay, path/hash validation, changed-coordinate rejection and deleted-evidence rejection.
