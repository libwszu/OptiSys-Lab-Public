# Stage 5 measured compute profile

Run ID: `20261020_210201_S5_HNA`  
Host: Windows 11, AMD Ryzen 5 4600G (6C/12T), 32,940,972 KiB visible memory, 14,217,144 KiB free at start, NVIDIA GTX 1660 SUPER 6 GiB (visible; not used).  
Clean project environment: CPython 3.14.3, Optiland 0.6.3, NumPy 2.5.4, SciPy 1.18.1, Streamlit 1.66.0, pytest 9.1.1.

## Actual high-NA Optiland profile

The benchmark traced a deterministic uniformly spaced subset of the immutable G4 NA=0.22 baseline source. Each worker count was measured on 256, 512 and 2,048 rays, with three warmed calls per scale and a logged cold call. Thread environment was OMP/OpenBLAS/MKL/NumExpr = 1. Warm hashes matched within every profile cell.

| Workers | Rays | Wall p50 / p95 (s) | Throughput p50 (rays/s) | Peak process-tree RSS |
|---:|---:|---:|---:|---:|
| 1 | 256 | 0.03257 / 0.03759 | 7,861 | 334.6 MiB |
| 1 | 512 | 0.04912 / 0.05089 | 10,423 | 334.6 MiB |
| 1 | 2,048 | 0.04916 / 0.05394 | 41,656 | 334.6 MiB |
| 2 | 256 | 0.03328 / 0.03617 | 7,692 | 696.8 MiB |
| 2 | 512 | 0.04438 / 0.04932 | 11,536 | 696.8 MiB |
| 2 | 2,048 | 0.03574 / 0.04051 | 57,306 | 696.8 MiB |
| 4 | 256 | 0.03695 / 0.03776 | 6,929 | 733.9 MiB |
| 4 | 512 | 0.03589 / 0.03794 | 14,265 | 733.9 MiB |
| 4 | 2,048 | 0.03257 / 0.03438 | 62,882 | 733.9 MiB |

At 2,048 rays, four workers yielded `1.51x` warmed throughput relative to one worker, but process-tree RSS was `2.19x` and process startup is larger than one warmed 0.05 s trace. The registered S5 work uses a handful of 4,096-ray runs rather than a large parallel assembly batch, so one worker was selected for the formal science path. GPU was not tested.

## S5 science resource use

The final measured reference, diagnostics and equal-aperture comparison took `12.367 s`, `24.849 s` and `11.094 s` outer wall, respectively. Combined with the 25.345 s profile, the final scientific path used approximately `73.7 s` CPU wall. Measured peak RSS was `697.4 MiB` for S5-B; the profile maximum was `733.9 MiB`, below both frozen RSS limits. No timeout, memory-budget breach or GPU use occurred.

The CLI examples, real Streamlit service probe, clean install and pytest are engineering/portfolio work and are reported separately. Full-suite suite time and outer wall are in the test evidence JSON; the first run's README-token regression and the passing rerun are retained as distinct logs.
