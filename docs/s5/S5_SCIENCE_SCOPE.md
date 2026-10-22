# Stage 5 scientific scope and assumptions (frozen before new scientific results)

Run ID: `20261020_210201_S5_HNA`

## Question

Does the G4 high-NA discrepancy between the ideal P0 thin-lens model and the assumed P1 two-singlet model persist when the P1 spherical surfaces, coordinates, refractions, ray exits, apertures and target classification are independently checked? If so, how do angle, focus, target shape/size and assumed lens mechanics explain the observed model difference?

## Inherited facts to verify

The official G4 run is `20261020_133555_G4_ec3e2813_0e48`; its audit archive SHA-256 is `866d305aa87920c2068fb964ba4c3c7ff401964391ddf452bb022ed76ce9914d`. Source assumptions are 976 nm, 105 µm core, NA 0.22, output index 1, uniform-area near-field and uniform-solid-angle far-field, seed 976051, 4,096 equal dimensionless weights, and unknown absolute power. The two P1 designs are centered 2 mm thick equiconvex N-BK7 singlets derived from ideal focal lengths, without vendor part numbers, coatings/Fresnel loss, decenter/tilt or diffraction. The target radius 1 mm is an assumed receiving region.

The official G4 status remains `G4_OPTICAL_MODEL_VERIFICATION=QUALIFIED` and overall design claim `NO_SUPPORTED_IMPROVEMENT`; S5 results cannot edit or upgrade those fields.

## Assumptions and evidence classes

| Item | Frozen value/source | Evidence class |
|---|---|---|
| Source distribution | G4 config and immutable `source_samples.csv` | `ASSUMED / SIMULATED` |
| Absolute pump power | unknown; not inferable from normalized weights | `UNKNOWN` |
| Glass | N-BK7 only; reject any other material until its dispersion and geometry are rebuilt from a verified source | `ASSUMED` |
| Dispersion | N-BK7 Sellmeier coefficients in frozen source code; cross-check index with Optiland 0.6.3 material catalog at 0.976 µm | `MODEL INPUT`, not measured |
| Lens surfaces | G4 `optics_model.json`: signed spherical radii and vertices; 2 mm center thickness | `DERIVED / ASSUMED` |
| Clear apertures | G4 YAML configuration; not a lens outer diameter | `ASSUMED` |
| Receiving region | registered circles/square; not an Er:YAP crystal drawing | `ASSUMED` |
| Empirical spot, efficiency, W/mm², crystal absorption/thermal response | no authorized measurements or calibrated power | `NOT_AVAILABLE` |

## Models kept distinct

- P0 is an ideal thin-lens geometric reference. Under 4f-style conjugacy, angular cancellation may be a valid paraxial property; equality across NA is not automatically a software bug.
- P1 is a nonparaxial geometric ray trace through four spherical interfaces. Its broadening may be consistent with spherical aberration, finite conjugacy, aperture clipping or target choice only after independent cross-check and focus analysis. No single cause is asserted in advance.
- `capture_fraction` and encircled weight always use the original total source weight denominator. Conditional radii are explicitly conditional on the named surviving set.
- Outcomes outside an assumed target are geometric receiving-region misses, not measured pump power losses.

## Explicit exclusions

No full Er:YAP laser digital twin, gain/threshold, absolute pump efficiency, absorption, thermal lens, real manufacturing tolerance, measured beam profile, coherent field, speckle, diffraction, commercial Zemax comparison, laser experiment or source-power claim.
