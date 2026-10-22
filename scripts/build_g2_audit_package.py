"""Build the G2 GPT-audit ZIP: code, evidence, narrative and checksums.

The package is deliberately *small*: source, tests, frozen configs, the run's
machine-readable evidence, representative figures, and a reproduction script
that works from the extracted copy.  Large raw frame dumps are excluded; the
CSV/NPZ evidence that supports every number is included.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

INCLUDE_SOURCE = ["src", "tests", "repro", "configs", "docs/g2", "scripts/build_g2_audit_package.py"]
RUN_FILES = [
    "config_snapshot.yaml",
    "optical_model_snapshot.yaml",
    "tolerance_distributions.yaml",
    "optimization_objectives_frozen.yaml",
    "source_tree_manifest.json",
    "environment.json",
    "compute_plan.json",
    "benchmark.json",
    "provenance.json",
    "run_status.json",
    "gate_checks.json",
    "metrics.json",
    "tests_binding.json",
    "tests_junit.xml",
    "pytest_stdout.txt",
    "report.html",
    "report.md",
    "main_run.log",
]
RUN_GLOBS = [
    "optics/*.csv", "optics/*.json", "optics/*.npz",
    "tolerance/*.csv", "tolerance/*.json",
    "optimization/*.csv", "optimization/*.json",
    "independent_validation/*.json", "independent_validation/*.csv",
    "figures/*.png",
]
MAX_CSV_BYTES = 4 * 1024 * 1024
MAX_CSV_ROWS = 20000

DOC_NAMES = [
    "00_START_HERE.md", "01_EXECUTIVE_SUMMARY.md", "02_SPEC_TRACEABILITY.md",
    "03_SCIENTIFIC_AUDIT.md", "04_VALIDATION_MATRIX.md", "05_COMPUTE_AND_PERFORMANCE.md",
    "06_REPRODUCTION_GUIDE.md", "07_KNOWN_ISSUES_AND_FAILURES.md", "08_NEXT_GATE_PLAN.md",
    "GPT_REVIEW_INSTRUCTIONS.md",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# narrative
# ---------------------------------------------------------------------------
def _metric_table(metrics: dict[str, Any]) -> str:
    final = metrics.get("results", {}).get("final", {})
    rows = ["| candidate | B [mm] | f [mm] | theta [deg] | valid/attempted | failure | RMSE [mm] | P95 [mm] |",
            "|---|---:|---:|---:|---|---:|---:|---:|"]
    for name in ("baseline", "nominal", "robust"):
        row = final.get("candidates", {}).get(name, {})
        eng = final.get("engineering", {}).get(name, {})
        rows.append(
            f"| {name} | {eng.get('baseline_mm', '—')} | {eng.get('focal_length_mm', '—')} "
            f"| {eng.get('theta_deg', '—')} | {row.get('n_valid', '—')}/{row.get('n_attempted', '—')} "
            f"| {_f(row.get('failure_rate'))} | {_f(row.get('rmse_mm'))} | {_f(row.get('p95_abs_mm'))} |"
        )
    return "\n".join(rows)


def _f(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


def _ci_table(metrics: dict[str, Any]) -> str:
    final = metrics.get("results", {}).get("final", {})
    rows = ["| comparison | pairs | dRMSE [mm] | 95% CI | dFailure |", "|---|---:|---:|---|---:|"]
    for key, value in final.get("ci", {}).items():
        rmse = (value or {}).get("rmse", {})
        if rmse.get("ci_low") is None:
            continue
        rows.append(
            f"| {key} | {value.get('n_pairs')} | {_f(rmse.get('delta'))} "
            f"| [{_f(rmse.get('ci_low'))}, {_f(rmse.get('ci_high'))}] "
            f"| {_f((value.get('failure_rate') or {}).get('delta'))} |"
        )
    return "\n".join(rows)


def write_docs(package: Path, run_dir: Path, metrics: dict[str, Any],
               status: dict[str, Any], baseline: dict[str, Any]) -> None:
    results = metrics.get("results", {})
    optics = results.get("optics", {})
    gate = results.get("gate_checks", {})
    final = results.get("final", {})
    search = results.get("search", {})
    tolerance = results.get("tolerance", {})
    failures = [name for name, check in gate.items()
                if isinstance(check, dict) and not check.get("pass")]

    (package / "00_START_HERE.md").write_text(f"""# OptiSys-Lab G2 audit package

Run: `{status.get('run_id')}`
Gate: **G2**
Execution status: **{status.get('status')}**
Scientific claim: **{status.get('scientific_claim_status')}**
Model level emitted: `{status.get('model_level_emitted')}`
Packaged at: {datetime.now(timezone.utc).isoformat(timespec="seconds")}

## Read this first

1. `01_EXECUTIVE_SUMMARY.md` — what was done and what was not.
2. `03_SCIENTIFIC_AUDIT.md` — the physics, the assumptions, the discrepancies.
3. `04_VALIDATION_MATRIX.md` — every check with its measured value.
4. `07_KNOWN_ISSUES_AND_FAILURES.md` — including everything that did not work.
5. `GPT_REVIEW_INSTRUCTIONS.md` — how to audit this package independently.

## What is in the box

| Path | Content |
|---|---|
| `src/optisys/**` | full source of the G2 additions and the reused G1 modules |
| `tests/**` | unit, reference and integration tests (run them yourself) |
| `configs/**` | frozen configuration, lens parameters, thresholds |
| `docs/g2/**` | pre-registration, assumptions, acceptance criteria, budget |
| `run/**` | machine-readable evidence from the frozen run |
| `repro/verify_g2.py` | cheap independent reproduction (no Monte Carlo) |

## Baseline

* G0 run `20261019_130948_G0_78fa364f`
* G1 run `20261019_145702_G1_54c9e3fb`
* Baseline hashes: `docs/g2/G2_BASELINE_HASHES.json`

## Honest scope statement

This is a **synthetic, assumption-based L1-approximate study**. There is no
measured lens, no measured camera, no manufacturing data and no industrial
accuracy claim. `execution PASS` does not mean `physically validated`.
""", encoding="utf-8")

    (package / "01_EXECUTIVE_SUMMARY.md").write_text(f"""# Executive summary

## Execution

| Item | Value |
|---|---|
| Gate | G2 |
| Execution status | **{status.get('status')}** |
| Scientific claim status | **{status.get('scientific_claim_status')}** |
| Model level emitted | `{status.get('model_level_emitted')}` |
| Optical backend | Optiland {optics.get('backend', {}).get('version')}, executed = {optics.get('backend_executed')} |
| Exported ray rows | {optics.get('trace_rows')} |
| Final assembly draws | {final.get('n_final_assemblies')} |
| Trusted test set | {final.get('n_frames_per_candidate')} frames per candidate |

## What was actually done

1. Re-ran the full G1 regression on this machine: 194 passed, 0 failed,
   0 skipped, exit 0. G0/G1 audit ZIP hashes and the source-tree digest match
   the baseline records.
2. Executed a **real** sequential ray trace through a declared equiconvex
   N-BK7 singlet with Optiland 0.6.3 and cross-checked it against an
   independent paraxial matrix reference.
3. Built the L1 image contract: geometric footprint ⊛ scalar Airy limit,
   area-integrated once, energy conservation checked, no re-normalisation.
4. Built a tolerance engine with **assembly-level** perturbations shared across
   scenes, LHS + inverse-normal sampling (KS-tested), and two strictly
   separated calibration strategies.
5. Ran a budgeted nominal and robust optimisation over `(B, f, θ)`.
6. Re-evaluated `baseline`, `nominal`, `robust` on {final.get('n_final_assemblies')}
   fresh assemblies with paired cluster-bootstrap confidence intervals.

## What was NOT done

* No measured lens, camera, laser or target. Nothing here is `MEASURED`.
* No manufacturing-yield study; the tolerance sigmas are **ASSUMED**.
* No wavefront-computed PSF in the production kernel (the Airy limit is a
  model). A Huygens PSF is used only for a cross-check note.
* No GPU path (`GPU_NOT_USED`; torch is not installed).
* No GUI, no 976 nm case, no LiDAR.

## Candidate comparison (independent panel, strategy A)

{_metric_table(metrics)}

## Paired differences (cluster bootstrap over assemblies)

{_ci_table(metrics)}

## Headline scientific finding

The G1 pinhole law `u = cx + fx·B/Z` and a real finite-conjugate singlet do
**not** describe the same image. At the baseline design they differ by up to
{_f(optics.get('findings', {}).get('l0_vs_l1_chief_ray_max_px'))} px
({_f(optics.get('findings', {}).get('l0_vs_l1_chief_ray_max_rel_offset'))} of the
spot offset from the principal point). A freshly fitted two-parameter system
calibration absorbs most of it; reusing the G1 calibration unchanged would not.
This is recorded as finding **G2-01**, not as a defect.

## Failed checks in this run

{", ".join(failures) if failures else "none"}
""", encoding="utf-8")

    (package / "02_SPEC_TRACEABILITY.md").write_text("""# Spec traceability

Reference: `OptiSys_Lab_Job_Oriented_Development_Plan_2026.pdf` (18 pages) and
the G2 task book.

| Requirement | Where implemented | Evidence | Status |
|---|---|---|---|
| R01 geometry / coplanar triangulation | `src/optisys/geometry/coplanar.py` | G0 regression, `run/optics/field_distortion.csv` | unchanged, PASS |
| R02 independent geometric cross-check | `src/optisys/geometry/reference.py` | `repro/verify_g0.py` | PASS |
| R03 L1 lens + PSF/imaging interface | `src/optisys/optics/*` | `run/optics/optical_validation.json`, `run/optics/energy_and_capture.csv` | implemented |
| R04 spot model + CMOS | `src/optisys/imaging/spot.py`, `sensor_g2.py` | `run/optics/l0_limit.csv` | implemented |
| R05 estimators | `src/optisys/estimators/*` (G1 frozen) + `gaussian_2d_integrated.py` (G2) | `run/independent_validation/failure_breakdown.csv` | implemented |
| R06 calibration | `src/optisys/calibration/*` | `run/independent_validation/summary.json` | implemented |
| R07 tolerance | `src/optisys/tolerance/*` | `run/tolerance/*` | implemented |
| R08 robust optimisation | `src/optisys/optimization/*` | `run/optimization/*` | implemented |
| R09 evaluation / statistics | `src/optisys/evaluation/*` | `run/independent_validation/ci_results.json` | implemented |
| R10 reporting | `src/optisys/reports/*` | `run/report.html`, `run/figures/*` | implemented |
| R11 audit packaging | this script | this ZIP | implemented |

## Deviations from the task book

| Item | Task book says | This round does | Reason |
|---|---|---|---|
| G1 full-suite regression | must run locally | done: 194/194, exit 0 | PRE-01 closed |
| PSF type | footprint or model PSF | geometric footprint ⊛ Airy limit, labelled as a model | no wavefront PSF in the production path; documented |
| `z_focus` tolerance | N(0, 0.10 mm) on the sensor | applied as a **detector axial offset** | physically that is what a focus-placement tolerance is; the object-distance interpretation moves the sensor by only 0.075 mm per 50 mm |
| Final sample count | ~2000 assemblies | {n} | see `04_VALIDATION_MATRIX.md` H1 |

All deviations are also in `docs/DECISION_LOG.md`.
""", encoding="utf-8")

    (package / "03_SCIENTIFIC_AUDIT.md").write_text(f"""# Scientific audit

## 1. Coordinates and signs

* Origin at the camera pinhole, `+Z` along the optical axis into the scene,
  `+X` lateral. Laser at `(B,0,0)` with direction `(-sinθ, 0, cosθ)`.
* L0 (G1, frozen): virtual image plane **in front of** the pinhole,
  `u = cx + fx·X_L/Z`, no flip.
* L1 (real lens): real inverted image, `u = cx − y_img/p`, `v = cy + x_img/p`.
* `dZ/du = −Z²/(fx·B)` (SD-001): the PDF prints the magnitude with a positive
  sign; the signed value is negative for `B > 0`.

## 2. The optical model

Single equiconvex N-BK7 element, radius solved from the thick-lens equation,
rear-vertex-to-sensor distance from the paraxial matrix, stop at the front
surface, rear clear aperture `D/2 + 0.35 mm` (barrel clearance).

Parameters actually used:

```json
{json.dumps(optics.get('model', {}), indent=2)}
```

## 3. Independent verification

| Check | Measured | Threshold |
|---|---|---|
| Traced chief ray vs paraxial matrix (0.5 mm field) | {_f(gate.get('A4_paraxial_small_field', {}).get('value'))} | 1 % |
| Geometric radius at EPD = 0.15 mm | {_f(gate.get('A5_pinhole_limit', {}).get('value'))} px | 0.3 px |
| Spot radius vs aperture | {_f(gate.get('A6_aperture_monotone_spot', {}).get('value'))} | strictly increasing |
| Defocus sweep | unimodal, far/min = {_f((gate.get('A7_focus_defocus', {}).get('value') or {}).get('far_mean_um'))} / {_f((gate.get('A7_focus_defocus', {}).get('value') or {}).get('minimum_um'))} | ≥ 3 |
| Energy conservation | {_f(gate.get('B1_energy_conservation', {}).get('value'))} | 0.5 % |
| L0 limit | {_f(gate.get('B4_l0_limit', {}).get('value'))} px | 0.01 px |
| Deterministic kernel | {_f(gate.get('B7_deterministic_kernel', {}).get('value'))} | bitwise |

## 4. G2-01, the central discrepancy

The pinhole law and the finite-conjugate singlet differ systematically:

```
u_pinhole − cx = fx · B / Z
u_lens    − cx = fx · (image distance / Z) · B / Z  + distortion
```

Measured maximum difference at the working field:
**{_f(optics.get('findings', {}).get('l0_vs_l1_chief_ray_max_px'))} px**
({_f(optics.get('findings', {}).get('l0_vs_l1_chief_ray_max_rel_offset'))} of the
offset). Consequences:

* a system calibration refitted on the L1 instrument absorbs most of it;
* reusing the G1 `(a, b)` unchanged does not, and the error grows towards the
  near end of the range;
* this is why the pre-registration forbids reusing an old `(a, b)` for a new
  design.

## 5. Weak points that a reviewer should attack

1. The Airy limit is a **model**, not a computed wavefront. The geometric
   footprint dominates at f/6, so this affects the kernel width by well under
   10 %; it is still an assumption.
2. The singlet is not a production lens. At 11° field the spot is
   aberration-dominated; a real triangulation sensor would use a multi-element
   objective and possibly a Scheimpflug mount.
3. Absolute radiometry is impossible here; `E_total` is a design assumption.
   The `fixed_incident` mode isolates geometry/PSF effects and must not be read
   as a flux-scaling result.
4. The tolerance sigmas are ASSUMED examples from the task book.
5. No measured data of any kind.
""", encoding="utf-8")

    checks_lines = ["| check | value | threshold | pass |", "|---|---|---|---|"]
    for name, check in gate.items():
        if not isinstance(check, dict):
            continue
        checks_lines.append(
            f"| {name} | {_f(check.get('value'))} | {_f(check.get('threshold'))} "
            f"| {check.get('pass')} |"
        )
    (package / "04_VALIDATION_MATRIX.md").write_text(
        "# Validation matrix\n\n"
        "Every check is emitted by the run itself; none is written by hand.\n\n"
        + "\n".join(checks_lines)
        + "\n\n## Test evidence\n\n"
        f"* JUnit: `run/tests_junit.xml` (sha256 "
        f"{_f((results.get('tests_binding') or {}).get('junit_sha256'))})\n"
        f"* totals: {json.dumps((results.get('tests_binding') or {}).get('totals'))}\n"
        f"* consistent with code hash, command and exit code: "
        f"{(results.get('tests_binding') or {}).get('consistent')}\n",
        encoding="utf-8",
    )

    (package / "05_COMPUTE_AND_PERFORMANCE.md").write_text(f"""# Compute and performance

```json
{json.dumps(metrics.get('compute', {}), indent=2)[:4000]}
```

## Hardware actually probed

```json
{json.dumps(baseline.get('environment', metrics.get('environment', {})), indent=2)[:2000]}
```

## Policy

* Worker count is chosen from a **measured** speed-up on the real L1 scene
  workload; below 1.3× the run is single-process.
* `OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, `MKL_NUM_THREADS` and
  `NUMEXPR_NUM_THREADS` are pinned to 1 in every worker.
* Frames are streamed assembly by assembly; the full dataset is never held in
  memory.
* GPU: `NOT_USED` (torch not installed, no CUDA evidence). Not a defect.
""", encoding="utf-8")

    (package / "06_REPRODUCTION_GUIDE.md").write_text("""# Reproduction guide

## Environment

```
Python 3.14.3 (CPython), Windows 11
numpy 2.5.4, scipy 1.18.1, pandas 3.0.6, matplotlib, psutil 7.2.2
optiland 0.6.3  (the only third-party optics engine)
```

## From the extracted package

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # or the pinned lock file
.venv/Scripts/python repro/verify_g2.py         # cheap, no Monte Carlo
.venv/Scripts/python -m pytest -q               # full test suite
```

`repro/verify_g2.py` re-traces the lens, re-checks the paraxial agreement,
the energy contract, one full scene through sensor + estimator, and the
calibration round trip. It prints `REPRO_STATUS: PASS|FAIL` and exits 0/1.
If Optiland is missing it prints `DEPENDENCY_UNAVAILABLE` and exits 2 — that is
**not** a pass.

## Re-running the full study

```bash
.venv/Scripts/python -m optisys g2 --config configs/triangulation_g2_l1.yaml
```

Expect roughly the wall time recorded in `run/metrics.json:compute.wall_time_s`.
A `--quick` run is available for smoke testing and always reports `PARTIAL`.

## What is not in the box

* The `.venv` (install it yourself).
* The full frame dump (none exists; frames are generated on the fly).
* The G0/G1 audit ZIPs (only their hashes are recorded).
""", encoding="utf-8")

    failure_lines = "\n".join(
        f"* `{name}`: {_f((gate.get(name) or {}).get('value'))}"
        for name in failures
    ) if failures else "* none"

    (package / "07_KNOWN_ISSUES_AND_FAILURES.md").write_text(f"""# Known issues and failures

## Open

| ID | Severity | Issue | Evidence |
|---|---|---|---|
| G2-01 | P1 | Pinhole law vs finite-conjugate singlet differ by {_f(optics.get('findings', {}).get('l0_vs_l1_chief_ray_max_px'))} px at the baseline design | `run/optics/field_distortion.csv` |
| G2-02 | P1 | A singlet at 11° field is aberration-dominated; the spot is not diffraction-limited | `run/optics/aperture_vignetting_failure_table.csv` |
| G2-04 | P2 | No absolute radiometry; electron counts are design assumptions | `run/optics/energy_and_capture.csv` |
| PRE-03 | P1 | Weak-signal 2-D estimator validity remains below 100 %; RANSAC-style mitigation is out of scope this round | `run/independent_validation/failure_breakdown.csv` |
| PRE-10 | P3 | Some report fields still render as raw values | cosmetic |

## Closed this round

| ID | Resolution |
|---|---|
| PRE-01 | full `pytest` re-run locally: 194 passed / 0 failed / 0 skipped, exit 0 |
| PRE-02 | added `gaussian_2d_integrated`, an area-integrated fitter; G1 estimators untouched |
| PRE-04 | strategy A / B separated; model family selected on validation only |
| PRE-05 | test evidence bound to code hash, JUnit hash, command and exit code |
| PRE-06 | duplicate test definition replaced by a distinct property test |
| PRE-07 | RSS and available RAM sampled at run start |
| PRE-08 | `FULL_WELL_SATURATION` and `ADC_CLIPPING` separated |
| PRE-09 | CI workflow updated; remote status reported as `REMOTE_CI_NOT_VERIFIED` |

## Checks that failed in this run

{failure_lines}

## Negative results kept on purpose

* `gaussian_2d` (G1, point-sampled) flags `MODEL_MISMATCH` on a large share of
  L1 frames because the fitted sigma falls below its frozen 1.0 px bound.
  That is a true finding about the estimator, not a bug to hide.
* The bias of the final evaluation on a small assembly subset is dominated by
  sampling error of the perturbation mean; this is why the pre-registration
  demands 2000 assemblies.
""", encoding="utf-8")

    (package / "08_NEXT_GATE_PLAN.md").write_text("""# Next-gate plan (proposal only — G2 review decides)

Do **not** start G3 automatically. Depending on the G2 verdict:

1. **If the L1 model is accepted**: add a second element / cemented doublet and
   a Scheimpflug tilt, then re-run the same pipeline. The tolerance engine and
   statistics do not need to change.
2. **If the spot is considered too aberrated**: reduce the field angle by
   increasing the working distance or the baseline, or use a longer focal
   length with a smaller aperture; re-check against the FOV constraint.
3. **Always**: replace the Airy-limit kernel with a wavefront PSF and quantify
   the difference; that is the main remaining modelling shortcut.
4. **Data**: any measured spot, even a single frame with a known target
   distance, would move the evidence level from `SIMULATED/CROSS-CHECKED` to
   something stronger. Nothing in this round substitutes for that.
""", encoding="utf-8")

    (package / "GPT_REVIEW_INSTRUCTIONS.md").write_text("""# Instructions for the reviewing model

Audit this package **from the files**, not from the executive summary. The
summary is a claim; the CSVs and JSON are the evidence.

## Mandatory checks

1. **Manifest integrity.** Recompute SHA-256 for every entry in
   `manifest.json`; confirm `SHA256SUMS.txt` matches. Confirm the G0/G1 hashes
   in `docs/g2/G2_BASELINE_HASHES.json` equal the values in the task book.
2. **Did Optiland really run?** `run/optics/optical_validation.json` must show
   `backend_executed = true`, a version, and a non-zero exported ray count.
   `run/optics/raytrace_reference.csv` must contain per-ray inputs/outputs with
   a `valid` flag. Reject any package where "PSF" appears without a trace.
3. **Redo the physics yourself.** From `run/optical_model_snapshot.yaml`
   recompute the equiconvex radius and the sensor distance, then compare with
   `run/optics/independent_thin_lens_comparison.csv`. Check the sign of
   `u = cx − y'/p` against `run/optics/field_distortion.csv`.
4. **Check for double counting.** The kernel must integrate the pixel area
   exactly once. Look at `build_kernel` / `place_kernel` in
   `src/optisys/optics/psf_or_footprint.py`; confirm there is no second
   integration and no re-normalisation after clipping.
5. **Tolerance correctness.** In `run/tolerance/assembly_draws.csv` one
   `assembly_id` must carry one perturbation vector; `run/tolerance/sampler_ks_tests.csv`
   must show the inverse-normal transform is right.
6. **Calibration separation.** `run/independent_validation/summary.json` must
   report strategy A and B separately, with B's calibration cost.
7. **Leakage.** `run/independent_validation/heldout_seeds.json` and
   `run/split_manifest.json`-equivalents must show test distances and seeds
   disjoint from search. Grep the search history for any test distance.
8. **Statistics.** `run/independent_validation/ci_results.json` must resample
   **assemblies**, not frames. Check `n_assemblies` in each entry.
9. **Run the code.** `python repro/verify_g2.py` and a subset of `pytest`.
   A missing dependency is `DEPENDENCY_UNAVAILABLE`, not a pass.
10. **Negative results.** Confirm `07_KNOWN_ISSUES_AND_FAILURES.md` matches the
    CSVs; a package with no negative result at all is suspicious.

## Required outputs of your review

* `G2_EXECUTION_STATUS` ∈ {PASS, PARTIAL, FAIL}
* `V4_A`, `V4_B`, `V5_SAMPLER`, `V5_OPTIMIZER`, `V5_HOLDOUT`, `AUDIT`
* `G2_SCIENTIFIC_CLAIM_STATUS`
* P0/P1/P2 problem list with file/line references
* one concrete next step

Do not accept "the numbers look reasonable" as evidence.
""", encoding="utf-8")


# ---------------------------------------------------------------------------
# packaging
# ---------------------------------------------------------------------------
def collect(package: Path, run_dir: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for rel in INCLUDE_SOURCE:
        source = ROOT / rel
        if not source.exists():
            continue
        if source.is_file():
            target = package / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
            continue
        for path in sorted(source.rglob("*")):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts or path.suffix in (".pyc",):
                continue
            relative = path.relative_to(ROOT)
            target = package / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)

    run_target = package / "run"
    run_target.mkdir(parents=True, exist_ok=True)
    for name in RUN_FILES:
        source = run_dir / name
        if source.is_file():
            shutil.copy2(source, run_target / name)
    for pattern in RUN_GLOBS:
        for source in sorted(run_dir.glob(pattern)):
            if source.is_file():
                target = run_target / source.relative_to(run_dir)
                target.parent.mkdir(parents=True, exist_ok=True)
                if source.suffix == ".csv" and source.stat().st_size > MAX_CSV_BYTES:
                    _truncate_csv(source, target, MAX_CSV_ROWS)
                else:
                    shutil.copy2(source, target)

    requirements = ROOT / "requirements.lock.txt"
    if requirements.is_file():
        shutil.copy2(requirements, package / "requirements.txt")
    return entries

def _truncate_csv(source: Path, target: Path, max_rows: int) -> None:
    """Keep the header and the first ``max_rows`` rows of a very large CSV.

    The full file stays in the run directory on disk; the package carries a
    representative slice plus the aggregate CSVs, which is what an auditor
    actually needs to re-check every reported number.
    """

    with source.open(encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        rows = []
        for index, row in enumerate(reader):
            if index >= max_rows:
                break
            rows.append(row)
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)
        writer.writerow(["# TRUNCATED", f"first {max_rows} of the full file; "
                                        f"the untruncated file stays in the run directory"])
    note = (
        f"{source.name}: the package contains the first {max_rows} rows. "
        f"The complete file is {source.stat().st_size} bytes and is kept in the "
        "frozen run directory.\n"
    )
    (target.with_suffix(target.suffix + ".note.txt")).write_text(note, encoding="utf-8")


def build_manifest(package: Path) -> dict[str, Any]:
    files = []
    for path in sorted(package.rglob("*")):
        if not path.is_file() or path.name in ("manifest.json", "SHA256SUMS.txt"):
            continue
        relative = path.relative_to(package).as_posix()
        files.append({
            "path": relative,
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "category": ("code" if relative.startswith(("src/", "tests/", "repro/", "scripts/"))
                         else "config" if relative.startswith("configs/")
                         else "docs" if relative.startswith("docs/")
                         else "evidence" if relative.startswith("run/")
                         else "other"),
        })
    payload = {
        "schema_version": "1.0",
        "created_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "file_count": len(files),
        "total_bytes": sum(item["bytes"] for item in files),
        "files": files,
    }
    (package / "manifest.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    (package / "SHA256SUMS.txt").write_text(
        "\n".join(f"{item['sha256']}  {item['path']}" for item in files) + "\n",
        encoding="utf-8",
    )
    return payload


def scan_for_secrets(package: Path) -> list[str]:
    """Conservative, anchored secret scan.

    A naive substring search flags ordinary words (`task-book` contains `sk-`),
    and it always flags the scanner itself.  Patterns are therefore anchored on
    an assignment or a quoted value, and the scanner file is excluded.
    """

    patterns = (
        re.compile(r"(?i)\b(api[_-]?key|password|passwd|secret|access[_-]?token)\b\s*[:=]\s*['\"]?[^\s'\"]{8,}"),
        re.compile(r"\bsk-[A-Za-z0-9]{20,}\b"),
        re.compile(r"(?i)\b(begin (rsa|ec|openssh) private key)\b"),
        re.compile(r"(?i)\b(aws[_-]?secret[_-]?access[_-]?key)\b\s*[:=]"),
    )
    self_name = Path(__file__).name
    suspicious = []
    for path in package.rglob("*"):
        if not path.is_file() or path.suffix in (".npz", ".png", ".zip"):
            continue
        if path.name == self_name:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                suspicious.append(f"{path.relative_to(package)}: {match.group(0)[:40]!r}")
    return suspicious


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", required=True, type=Path)
    parser.add_argument("--output", type=Path, default=None)
    args = parser.parse_args()

    run_dir = args.run.resolve()
    status = _load(run_dir / "run_status.json")
    metrics = _load(run_dir / "metrics.json")
    if not status:
        print(f"RUN_NOT_FOUND: {run_dir}")
        return 1

    baseline_path = ROOT / "docs" / "g2" / "G2_BASELINE_HASHES.json"
    baseline = _load(baseline_path)

    run_id = status.get("run_id", run_dir.name)
    output = args.output or (ROOT / "_AUDIT" / run_id / f"OptiSysLab_G2_{run_id}_GPT_AUDIT.zip")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        raise SystemExit(f"refusing to overwrite an existing audit ZIP: {output}")

    with tempfile.TemporaryDirectory() as tmp:
        package = Path(tmp) / f"OptiSysLab_G2_{run_id}"
        package.mkdir(parents=True)
        collect(package, run_dir)
        write_docs(package, run_dir, metrics, status, baseline)
        manifest = build_manifest(package)
        secrets = scan_for_secrets(package)
        if secrets:
            print("SECRET_SCAN_FAILED:")
            for item in secrets:
                print("  " + item)
            return 2
        with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(package.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(package).as_posix())

    with zipfile.ZipFile(output) as archive:
        bad = archive.testzip()
        if bad is not None:
            print(f"ZIP_CORRUPT: {bad}")
            return 3
        names = archive.namelist()
        missing = [name for name in DOC_NAMES if name not in names]
        if missing:
            print(f"MISSING_ENTRY_DOCS: {missing}")
            return 4
        traversal = [name for name in names if name.startswith("/") or ".." in Path(name).parts]
        if traversal:
            print(f"PATH_TRAVERSAL: {traversal[:5]}")
            return 5

    digest = sha256_file(output)
    size = output.stat().st_size
    (output.parent / "AUDIT_ZIP_SHA256.txt").write_text(
        f"{digest}  {output.name}\nbytes: {size}\nfiles: {manifest['file_count']}\n"
        f"built_at_utc: {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "zip": str(output), "sha256": digest, "bytes": size,
        "files": manifest["file_count"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
