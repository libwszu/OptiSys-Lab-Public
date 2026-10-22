# OptiSys-Lab

**One simulation platform, two optical engineering cases:** 650 nm laser triangulation and 976 nm multimode pump-path analysis.

The engineering flow connects geometry, optical traces, estimation, calibration, tolerance sampling, reports and reproducible evidence. G2's inherited science status remains `QUALIFIED_ONLY`. G4/S5 pump-path results are simulated with assumed source and lens parameters; no measurement or absolute pump power is available.

Stage 5 independently cross-checked the assumed N-BK7 P1 trace at NA 0.22 across four spherical faces. It also found a nominal equal-clear-aperture L2-position trade-off on a separate ray holdout. Neither result validates a vendor part or assembly tolerance.

Start: `python -m pip install -e ".[dev,ui,optics]"` then `python -m streamlit run app/main.py`.
