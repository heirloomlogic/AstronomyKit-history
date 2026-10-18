# PAL refraction reference

`pal-reference.json` records 180 optical refraction values from Starlink PAL `palRefro` at commit `75017db16bb3efe9031e0f01921caa1b9554e922`. PAL receives observed zenith distance and returns vacuum minus observed zenith distance, so AstronomyKit compares the negated public inverse correction at each apparent altitude. The capture first reproduces PAL's two published `palTest.c` regression values within `1e-12` radians.

The grid fixes observer height at 0 m, relative humidity at 0.5, wavelength at 0.55 µm, astronomical latitude at 45°, tropospheric lapse rate at 0.0065 K/m, and PAL integration tolerance at `1e-12` radians. It varies apparent altitude from 0° through 80°, pressure from 300 through 1,100 mbar, and temperature from -40 through 40°C. This is a finite comparison, not a bound on atmospheric or model error.

PAL's relevant files use mixed licenses. `palRefro.c`, `pal1Atmt.c`, `pal1Atms.c`, and `pal1.h` state GPL-3.0-or-later; `palDrange.c`, `pal.h`, and `palmac.h` state LGPL-3.0-or-later. The capture downloads the pinned upstream files into a caller-selected cache, verifies every SHA-256, compiles them into a temporary external oracle, and deletes the executable after capture. No PAL source or binary is distributed with AstronomyKit or linked into its targets.

Capture from a cache with `python3 Scripts/capture-pal-refraction.py --capture --cache PATH`. Verify the committed archive and its bound source hashes with `python3 Scripts/capture-pal-refraction.py --check`.
