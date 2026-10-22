# Reproduction Guide

## Independent science check

In the complete source checkout:

```powershell
py -3.11 -m venv .venv_s6r_release
.\.venv_s6r_release\Scripts\python.exe -m pip install -e ".[dev,ui,optics]"
.\.venv_s6r_release\Scripts\python.exe repro\verify_s6r.py --root . --output artifacts\s6r\S6R_SCIENCE_RECOMPUTATION.json
```

In the extracted GPT audit package, install `requirements-verify.txt`, then run `python repro/verify_s6r.py --root .`. The package preserves the original relative paths for the frozen S6 acceptance criteria, holdout freeze, and assembly data.

The verifier reads all 1,600 design-assembly rows, pairs by `assembly_id`, checks the full source-weight ledger, recomputes the formal percentiles and r90/failure summaries, and regenerates 2,000 paired-cluster bootstrap replicates per scenario with seed `8064001`. It verifies the original programmatic and Amendment 03 outputs without editing either one.

## Full test and UI records

The full repository run used a new empty basetemp and the recorded clean environment. Full stdout, stderr, JUnit and exit metadata are in `validation/tests/`. Six-page AppTest, Streamlit serve smoke, CLI demos and report files are in `validation/ui/` and `validation/cli_demo/`.

The package's selected `src/` and `scripts/` files are the source code necessary to inspect the S6 reference and statistics. The package does not include the local virtual environment or the million-plus ray trace dump.
