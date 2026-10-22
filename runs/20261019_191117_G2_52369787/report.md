# OptiSys-Lab G2 report — triangulation_g2_l1

- run: `20261019_191117_G2_52369787`
- execution status: **PASS**
- scientific claim: **GAIN_SUPPORTED_WITHIN_ASSUMED_L1_MODEL**
- model level emitted: `L1-approximate`

## Candidates

| candidate | B [mm] | f [mm] | theta [deg] | valid/attempted | failure | RMSE [mm] | P95 [mm] |
|---|---:|---:|---:|---|---:|---:|---:|
| baseline | 20.0000 | 8.0000 | 0.0000 | 32693/42000 | 0.2216 | 3.1481 | 6.6430 |
| nominal | 15.0000 | 11.1000 | 4.0000 | 35337/42000 | 0.1586 | 3.0176 | 6.5663 |
| robust | 34.4000 | 7.2724 | 4.0000 | 31373/42000 | 0.2530 | 1.9031 | 3.8349 |

## Paired comparisons

| comparison | pairs | dRMSE [mm] | 95% CI |
|---|---:|---:|---|
| baseline_vs_nominal|centroid | 14000 | -0.1459 | [-0.2443, -0.0492] |
| baseline_vs_robust|centroid | 14000 | -1.1760 | [-1.2180, -1.1322] |
| nominal_vs_robust|centroid | 14000 | -1.0250 | [-1.1118, -0.9449] |
| baseline_vs_nominal|gaussian_2d | 14000 | -0.2217 | [-0.3515, -0.1000] |
| baseline_vs_robust|gaussian_2d | 14000 | -1.5569 | [-1.6683, -1.4506] |
| nominal_vs_robust|gaussian_2d | 14000 | -1.6678 | [-1.7897, -1.5510] |
| baseline_vs_nominal|gaussian_2d_integrated | 14000 | -0.1068 | [-0.2037, -0.0073] |
| baseline_vs_robust|gaussian_2d_integrated | 14000 | -1.1257 | [-1.1715, -1.0782] |
| nominal_vs_robust|gaussian_2d_integrated | 14000 | -0.9868 | [-1.0728, -0.9064] |

## Limitations

- single ASSUMED singlet; no vendor part number, no measured lens
- geometric footprint convolved with a scalar Airy limit, not a wavefront PSF
- tolerance sigmas are ASSUMED examples, not a manufacturing study
- synthetic data only; no measured camera
