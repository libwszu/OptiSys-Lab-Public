# G2 Compute Budget

Measured hardware (this machine, 2026-10-19):

| Item | Measured value | Method |
|---|---|---|
| CPU | AMD Ryzen 5 4600G, 6 physical / 12 logical | `psutil` + registry |
| RAM total / available at start | 31.41 GB / ~16.2 GB | `psutil.virtual_memory()` |
| Disk free (`E:`) | 216.6 GB / 465.5 GB | `psutil.disk_usage` |
| GPU | GTX 1660 SUPER 6144 MB, driver 566.07, CC 7.5 | `nvidia-smi` |
| CUDA usability | **not available** — torch not installed | import probe |
| Python | CPython 3.14.3 in `.venv` | `sys.version` |

GPU status for this round: **NOT_USED**. The workload is a scalar/array
per-frame loop with no tensor batch large enough to amortise host↔device
transfers; PyTorch is not installed and no CUDA evidence exists. This is
reported as `GPU_NOT_USED`, which is not a defect.

## 1. Measured unit costs (this machine)

| Operation | Measured |
|---|---|
| G1 `render_frame` (1280×1024) | 111 ms (median, 3 repeats) |
| G1 `detect_roi` | 21 ms |
| `centroid` | 0.6 ms |
| `gaussian_1d` | 26 ms |
| `gaussian_2d` | 5.5 ms |
| full `pytest` | 128.6 s (194 tests, exit 0) |

The G2 renderer (`imaging/sensor_g2.py`) replaces the array-`lambda` Poisson
draw with a scalar-background draw plus a sparse correction over the signal
support. It is distribution-equivalent (verified in `tests/unit/test_sensor_g2.py`)
and is expected to cut the render cost by roughly 2–3×.

## 2. Stage budgets (frozen)

| Stage | Frames | Notes |
|---|---|---|
| G2-A trace validation | ~2 000 ray sets | three distances × three apertures × two focuses |
| G2-B imaging validation | ~200 frames | V4-B1…B6 |
| OAT | 175 frames | 5 vars × 7 levels × 5 frames |
| precheck LHS | 1 000 frames | 200 assemblies × 5 scenes |
| search | ≤ 300 evaluations × 12 frames ≈ 3 600 frames | differential evolution, 3 variables |
| final | 2 000 assemblies × 21 frames = 42 000 frames | 3 candidates share the assemblies |

Estimated wall clock uses the **measured** per-frame time and the measured
parallel speed-up, not a paper calculation:

```
estimated = N_frames × t_frame / speedup + overhead
```

The measured speed-up is re-measured on the actual G2 workload (1/2/4/6
workers) before the final stage. If the measured speed-up is < 1.3×, the run
is single-process regardless of core count.

## 3. Resource protection

* BLAS/OpenMP/MKL/NUMEXPR threads pinned to 1 in every worker.
* Live frames: one batch per worker, never the whole dataset.
* At least 20 % of system RAM kept free; RSS sampled during the run.
* Checkpoints every 200 assembly draws, with input hash + completed IDs.
* On budget exhaustion: persist partial results, report
  `RESOURCE_LIMIT_PARTIAL`, never delete failed samples.

## 4. What is *not* budgeted

* Full 4 920-frame × 2 000-assembly cross product (9.84 M frames) — forbidden
  by the task book and by this plan.
* GPU paths.
* Huygens PSF on the full grid — used only as a spot check (≈ 4.4 s per field
  point, measured).
