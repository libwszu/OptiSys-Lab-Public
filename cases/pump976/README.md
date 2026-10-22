# Case: pump976 (second case)

Status: **NOT_IMPLEMENTED** — scheduled for G4 per the master prompt.

Planned starting assumptions (all unverified, from PDF section 11.1):

| parameter | starting value | note |
|---|---|---|
| wavelength | 976 nm | no gain/oscillator physics |
| fibre core / NA | 105 um / 0.22 | must be checked against the fibre datasheet |
| collimator L1 | f = 25 mm | sensitivity scan 15–45 mm |
| focus lens L2 | f = 100 mm | aperture, working distance, defocus |
| source model | multimode ray bundle | NOT an ideal single-mode Gaussian |

No measured data, lens part numbers, or efficiency figures exist for this case
in the repository. Anything produced here in future must be labelled
`SIMULATED_ONLY` until independent measurement exists. The laser safety rules
of the host laboratory apply; this project does not require building a
high-power 976 nm source.
