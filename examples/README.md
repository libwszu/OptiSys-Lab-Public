# examples/

Run the minimal reproduction:

```powershell
python repro/verify_g0.py
```

Regenerate the four G0 figures from a configuration without creating a run:

```powershell
python scripts/make_figures.py --config configs/triangulation_v0.yaml --out examples/_figures
```

Full pipeline (creates a new immutable `runs/<run_id>/`):

```powershell
python -m optisys simulate --config configs/triangulation_v0.yaml
```
