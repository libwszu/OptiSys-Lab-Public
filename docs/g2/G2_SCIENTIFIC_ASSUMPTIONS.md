# G2 Scientific Assumptions (ASSUMED parameters and their provenance)

Every number in this file is either **DERIVED** from a stated formula,
**ASSUMED** by the author, or **CONFIG** (a design choice, not physics).
Nothing here is a datasheet value or a measurement. This matters because the
G2 conclusions are conditional on these assumptions.

## 1. Coordinate and sign conventions

| Item | Convention | Source |
|---|---|---|
| Origin | camera pinhole `O = (0,0,0)` | G0/G1 inheritance |
| Optical axis | `+Z`, pointing from the camera into the scene | G0/G1 |
| Lateral axis | `+X` | G0/G1 |
| Laser exit | `(B, 0, 0)` | PDF §4.1 |
| Laser direction | `(-sin θ, 0, cos θ)` | PDF §4.1 |
| Scene point | `X_L(Z) = B - Z tan θ` | DERIVED |
| Virtual image plane (L0) | *in front of* the pinhole, no flip, `u = cx + fx·X_L/Z` | G1 contract |
| Real image plane (L1) | *behind* the lens, inverted | DERIVED (geometric optics) |
| L1 pixel mapping | `u = cx - x_img/p`, `v = cy + y_img/p` | DERIVED, verified by the flip test |

**Why the minus sign.** A positive object height produces a negative image
height in a real lens. The L0 pinhole contract places the virtual image plane
in front of the pinhole, where the sign is the opposite. Therefore the L1→L0
mapping must flip `u`. This is checked numerically (V4-B4) and never assumed.

`θ` sign: a positive `θ` tilts the beam toward `-X`, so `X_L` decreases with
`Z`. `dZ/du = -Z²/(fx·B)` is negative for `B > 0` (SD-001, unchanged).

## 2. Optical system (L1)

| Parameter | Value | Status | Rationale |
|---|---|---|---|
| Model | single equiconvex singlet | **CONFIG** | the smallest genuinely refracting system that shows real aberration |
| Material | N-BK7 (`n = 1.5168` at 650 nm) | **ASSUMED** | common, well-characterised glass; no vendor part number |
| Element thickness | 3.0 mm | **ASSUMED** | mechanically plausible for a 6–12 mm focal length singlet |
| Clear aperture (EPD) | 1.2 mm | **ASSUMED** | f/7 at f = 8.5 mm: a realistic small triangulation receiver; also keeps the geometric spot within a few pixels |
| Front radius | solved from `f`, `n`, `t` | **DERIVED** | thick-lens equiconvex solution, see §2.1 |
| Focus distance | 200 mm | **CONFIG** | mid-range of the 100–300 mm working envelope |
| Wavelength | 650 nm | **ASSUMED** | the PDF design wavelength, not a measured laser line |
| Stop | at the front surface, EPD-sized | **CONFIG** | entrance pupil = stop (nothing precedes it) |
| Barrel vignetting | rear clear radius = `D/2 + 0.35 mm` | **CONFIG** | a barrel has a fixed mechanical clearance; scaling the rear aperture with the stop would clip the off-axis chief ray when the stop closes |
| Pupil sampling | 17 x 17 cartesian grid inside the stop disc (194 rays) + 1 explicit chief ray | **CONFIG** | uniform-area sampling with explicitly auditable weights |

### 2.1 Radius solution

For an equiconvex thick lens of focal length `f`, index `n`, thickness `t`:

```
1/f = (n-1) [ 2/R - (n-1) t / (n R²) ]
```

Solved for the positive root `R > 0`. Back focal distance from the rear vertex:

```
BFL = f [ 1 - (n-1) t / (n R) ]
```

The sensor plane is placed at the paraxial image distance for `z_focus`:

```
s'(z_focus) = f · z_focus / (z_focus - f)     (from the rear principal plane)
sensor_distance = s'(z_focus) - H'            (measured from the rear vertex)
```

with `H'` the rear principal-plane offset. The implementation solves this
numerically from the traced paraxial data instead of trusting the thin-lens
formula, and the two are cross-checked (V4-A4).

**Known limitation.** A singlet at 11° field is not a production lens. The
spot will be dominated by coma/astigmatism. This is *reported*, not hidden:
it is the physical reason the L1 model cannot be assumed equal to L0.

## 3. Imaging model

`OpticalImageResult.expected_signal_e` is built as:

```
K(u,v)  = [ geometric footprint ] ⊛ [ scalar Airy kernel ]      (normalised)
I_e     = E_total · eta_vignette · eta_collect · K              [electrons/pixel]
```

| Symbol | Meaning | Status |
|---|---|---|
| `geometric footprint` | intensity-weighted histogram of traced image-plane hits | **MEASURED-BY-TRACE** |
| `Airy kernel` | `[2 J1(x)/x]²`, first zero at `1.22 λ F/#`, `F/# = s'/D`, sampled on a **5x** sub-pixel grid (odd on purpose) | **MODEL** (scalar diffraction limit) |
| `eta_vignette` | fraction of launched rays not blocked by an aperture | **MEASURED-BY-TRACE** |
| `eta_collect` | relative light-collection factor `(D/D_ref)² · (Z_ref/Z)²` | **ASSUMED normalisation** |
| `E_total` | electrons at the reference design | **ASSUMED** (G1 design assumption) |

The Airy kernel is a *model*, not a wavefront computation. The production
kernel is never called a "diffraction PSF"; it is called a
**geometric footprint convolved with an Airy diffraction limit**. A real
Huygens PSF computed by Optiland is used only as an independent cross-check at
a few field points, and the discrepancy is reported.

Two signal modes are kept strictly separate:

* `fixed_incident` — `E_total` independent of aperture/distance; isolates
  geometry/PSF/estimator effects. **Never** used to claim flux scaling.
* `relative_photon_budget` — `E_total ∝ (D/D_ref)² (Z_ref/Z)²`; used when the
  aperture is varied. Absolute calibration is impossible without a
  radiometric measurement, and this is stated in every result.

## 4. Sensor

Inherited unchanged from G1 (`configs/triangulation_g1_l0.yaml`): 12-bit ADC,
3 e⁻/ADU, 100 ADU black level, full well 15 000 e⁻, read noise 2–4 e⁻ by
condition. These are **ASSUMED**, not datasheet numbers.

New in G2: `FULL_WELL_SATURATION` and `ADC_CLIPPING` are separated. The
digital ceiling is `(4095 - 100) × 3 = 11 985 e⁻`, which is reached
**before** the 15 000 e⁻ full well. A pixel can therefore saturate for two
different physical reasons, and the two flags are never merged.

## 5. Tolerance distributions

All **ASSUMED**, taken from the task book's example values, *not* from a
manufacturing study:

| Variable | Distribution | Unit | Physical meaning |
|---|---|---|---|
| `ΔB` | N(0, 0.05) | mm | laser-to-camera baseline assembly |
| `Δθ` | N(0, 0.05) | deg | beam tilt assembly |
| `Δf/f` | N(0, 0.002) | – | focal-length fabrication spread |
| `Δcx` | N(0, 0.5) | px | principal-point / detector placement |
| `Δz_focus` | N(0, 0.10) | mm | **detector** axial placement (not the object distance the lens is focused at) |

Independence is an **assumption**, not a fact. A correlation sensitivity study
(`rho = ±0.5` on `ΔB–Δθ`) is run and reported. These numbers must never be
described as manufacturing yield.

## 6. Scene / radiometry

The target is Lambertian with an unspecified reflectance. The G1
`reflectance_proxy` is a bookkeeping label, not a calibrated BRDF. Absolute
electron counts are design assumptions.

## 7. What this round cannot claim

* no measured camera, no measured lens, no measured laser;
* no manufacturing yield;
* no claim that the singlet represents a purchasable lens;
* no claim that the geometric+Airy kernel equals a measured PSF;
* no claim of industrial accuracy.
