# Observed Delta T source archive

`manifest.json` binds the raw IERS EOP 20 C04 daily and midday series, Bulletin A rapid and predicted rows, HMNAO Table S15, and HMNAO's long-term model page. `generate-deltat-table.py --check` parses those files and reproduces the compiled Swift and C tables. The manifest retrieved the current set on 2026-10-17: C04 observations end at 2026-09-17, Bulletin A rapid values end at 2026-10-15, and its predictions end at 2027-10-04. After the last prediction, the runtime uses the documented HMNAO extrapolation. These dates describe this archive; they are not a refresh schedule.

`civil-horizon/` holds the raw primary responses used by `DeltaTIersObservedTests` for the civil observer path. The JPL Horizons response uses DE441, Earth ITRF93 geodetic coordinates, airless apparent azimuth and elevation, UTC tags with UT1−UTC, and EOP file `eop.261016.p270112`. It contains five exact epochs at Asheville, North Carolina: the adjacent seconds around sunrise and sunset plus one daytime horizon point. The response says its EOP file is data-based through 2026-10-16 and predicted through 2027-01-11; every archived sample is on 2025-06-21 or 2025-06-22 and therefore inside the data-based interval. The USNO response requests the local date 2025-06-21 with `TZ=-4`, where USNO defines `TZ` as local time minus UT1. Its 06:15 rise and 20:49 set therefore have the full UT1 dates 2025-06-21 10:15 and 2025-06-22 00:49. The capture converts each JPL UTC crossing to UT1 with its printed UT1−UTC before comparing the dated events: the differences are 3.424 seconds and 9.703 seconds, both within the matching published minute.

`capture-deltat-civil.py` verifies response digests, complete query and output schemas, target, site, frame, time scale, refraction, EOP metadata, finite values, exact epoch and event inventories, and the two limb-crossing brackets. It derives `civil-horizon/reference.json` only after validating the complete candidate. A failed download or rejected response leaves the accepted archive unchanged.

Run the offline replay with:

```sh
python3 -m unittest Scripts/test_capture_deltat_civil.py -v
python3 Scripts/capture-deltat-civil.py --check
python3 Scripts/generate-deltat-table.py --check
swift test --filter DeltaTIersObservedTests
```

Run `python3 Scripts/capture-deltat-civil.py --download` for an explicit staged refresh of the two observer responses. Refreshing the IERS model inputs remains the separate manifest-and-generator operation described by `generate-deltat-table.py`; this archive does not define a release cadence.

The daily-row errors, historical error estimates, and prediction errors are published physical uncertainty estimates, approximately one standard error where the source says so. They are not certified numerical bounds. The five Horizons rows and two event crossings are finite reference samples. The observed model meets the existing one-arcminute horizon and 0.25-second event tolerances at those samples. The older held and polynomial models are separated by the event check; the first-row polynomial horizon residual is 59.31 arcseconds and still falls inside the one-arcminute horizon tolerance. Polar motion and the dX/dY celestial-pole offsets in the IERS files remain unapplied.
