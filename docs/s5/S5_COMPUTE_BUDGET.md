# Stage 5 compute budget (frozen before new scientific results)

Run ID: `20261020_210201_S5_HNA`

## Detected host

- Windows 11; AMD Ryzen 5 4600G, 6 physical / 12 logical cores.
- 32,940,972 KiB visible memory at S5 start (approximately 31.4 GiB); 14,217,144 KiB free in the captured snapshot.
- NVIDIA GTX 1660 SUPER 6 GiB is visible via `nvidia-smi`; GPU workload is not needed and remains `NOT_TESTED` unless later profiling justifies it.
- `.venv`: CPython 3.14.3, NumPy 2.5.4, SciPy 1.18.1, Optiland 0.6.3, Streamlit 1.66.0, pytest 9.1.1.
- Thread limits for all new profile/science runs: OMP/OpenBLAS/MKL/NumExpr = 1.

## Profile before sizing work

Profile the actual high-NA baseline P1 model with a deterministic representative subset of the original 4,096 source rays (uniformly spaced ray IDs): 256, 512 and 2,048 rays. Measure one cold call and at least three warmed calls at worker counts 1, 2 and 4. Child processes use spawn and initialize an independent NumPy Optiland backend. Record input/output hashes, per-call wall, p50/p95, process-tree peak RSS and scale-up ratios. Process execution is selected only if it gives at least 1.30x speedup without material memory growth; otherwise fix at one worker. No GPU migration.

## Hard limits

- Each subprocess/task: 180 seconds hard timeout; set by the parent and record termination status.
- Total new scientific CPU wall: 1,200 seconds. Engineering/UI/test work is tracked separately. Any breach stops additional sampling and leaves completed checkpoints intact.
- Peak process-tree RSS: below the stricter of 8 GiB or 50% of free RAM captured at launch.
- Checkpoint by design, source case, target/focus and ray block. Each completed output block is independently hashed; interruption is `TIMEOUT/PARTIAL`.
- S5-A full 4,096-ray baseline and candidate replay runs once after profile, not in an unbounded optimizer.
- S5-B fixed analyses follow the registered grids; S5-C is capped at five 512-ray candidate cases and two 4,096-ray holdout traces (baseline and selected candidate), plus 5,000 inexpensive bootstrap replicates.
- No G2 2,000-assembly rerun, no P1 assembly Monte Carlo, no large search, no GPU, no COMSOL/FDTD or wave-optics expansion.

The previous G4 benchmark showed one worker remained preferable (2 workers 1.06x; 4 and 6 slower in the recorded profile). That history is context only; the S5 workload is separately benchmarked before use.
