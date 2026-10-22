# Demo capture checklist

- Install in a fresh virtual environment with `python -m pip install -e ".[dev,ui,optics]"`.
- Run the full test suite and the real Streamlit health probe before recording.
- Start with `python -m streamlit run app/main.py`; confirm `/_stcore/health` returns `ok` and `/` returns HTTP 200.
- Use a desktop viewport and wait for the Streamlit `Running...` state to disappear before each capture.
- Capture overview page A, optimization page C, and 976 nm page F. Final PNG evidence is under `screenshot_evidence/`.
- Keep G2 `QUALIFIED_ONLY`, G4 `QUALIFIED`, `source_power=UNKNOWN`, and all `SIMULATED` labels visible when quoting numbers.
- Video status: `NOT_DELIVERED`. No video capture executable was available in this run; no synthetic interface video was created.
