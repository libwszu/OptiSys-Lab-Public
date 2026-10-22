# Stage 5 audit reproduction

Extract the GPT audit ZIP to a clean directory. From that directory run:

```powershell
python repro/verify_s5.py
```

The verifier uses the standard library only. It independently evaluates SCHOTT N-BK7 Sellmeier dispersion, paraxial ABCD EFL/BFL, four global spherical interfaces with vector Snell refraction, full-NA target outcomes and source-weight ledgers, angle-bin capture, focus-plane propagation, target-shape sensitivity, spherical edge thickness, equal-aperture candidate selection, holdout paired deltas, and a separate paired ray bootstrap.

To validate the ZIP itself, including extraction replay and changed/deleted evidence rejection, run the packaged `scripts/verify_s5_audit_package.py <archive.zip>` before extraction, or use the outside-the-ZIP verification log. The archive intentionally contains the small original G4 inputs needed by this S5 replay; it does not recursively embed the original 10 MB G4 ZIP.

All outputs remain `SIMULATED / ASSUMED P1`. No power, efficiency, manufacturing or experimental claim is made.
