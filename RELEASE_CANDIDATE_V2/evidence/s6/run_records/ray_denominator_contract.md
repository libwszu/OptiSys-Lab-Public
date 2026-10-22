# Ray denominator contract for S6-B

Capture fraction is captured source weight divided by the weight of every input ray. Aperture blocks, outside-target rays, no-intersection, TIR, invalid source, and trace failure remain in that denominator.

`r80_all_plane_reachers_mm`, `r90_all_plane_reachers_mm`, and `rms_all_plane_reachers_mm` use every ray that reaches the selected world-z plane, even when it falls outside the 1 mm active circle; their radii are measured from the fixed world-axis center (x=0,y=0). `conditional_r90_within_1mm_mm` is a separate statistic over captured rays only. It is not a replacement for all-plane focus quality. Source weights remain dimensionless; absolute power is UNKNOWN.

The focus scan changes only the target plane and keeps both lenses fixed. The L2 scan changes only L2 axial position and keeps target z=225 mm. These are separate exploratory axes.
