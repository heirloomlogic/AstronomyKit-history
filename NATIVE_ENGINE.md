# Native engine contract

AstronomyKit's engine is Swift. The public API calls it; the vendored C engine under `Sources/CLibAstronomy` is no longer a dependency of the shipping target, and #97 and #99 remove its sources and tooling. This file is the internal contract the Swift modules are written against: where each module's files live and who edits them, units and frames, how time and the Delta T model are owned, how errors are reported, and how caches are owned and reset. The plan and its sub-issues are in epic #79.

A section marked **Planned** describes code that is not in the tree yet. The PR that adds the code replaces the section with what it actually added.

## Layout and ownership

Engine code is internal and lives in the `Engine` namespace (`enum Engine` in `Sources/AstronomyKit/Engine/Foundation/Engine.swift`). Each area below has one directory and one owning issue. Only that issue's PRs edit the directory; a change another module needs goes through the owner. Tests mirror the layout under `Tests/AstronomyKitTests/Engine/<Area>/`.

| Directory under `Sources/AstronomyKit/Engine/` | Owner | Responsibility |
|---|---|---|
| `Foundation/` | #84 | Namespace, frames, time and Delta T, calendar, vectors and states, constants, root search, light-travel iteration, caches and reset |
| `Planets/` | #85, #248 | Selected-window DE trajectories with retained VSOP87B series and polynomial evaluation |
| `Orientation/` | #86 | Nutation, precession, sidereal time, rotations, coordinate conversions, observers, atmosphere, refraction |
| `Moon/` | #87 | Lunar series, Moon positions and states, Earth-Moon barycenter, libration |
| `Gravity/` | #88 | Pluto, gravity simulation, Chiron table |
| `Positions/` | #89 | Heliocentric, barycentric, geocentric and apparent positions and states, ecliptic states, illumination |
| `Bodies/` | #90 | Jupiter's moons, rotation axes, Lagrange points |
| `Stars/` | #91 | Fixed stars and constellations |
| `Events/` | #92 | Rise/set, altitude and hour-angle searches, seasons, lunar phases, nodes and apsides, planetary event searches |
| `Eclipses/` | #93 | Lunar and solar eclipses, transits |

No file under `Sources/AstronomyKit` imports `CLibAstronomy` or names an `Astronomy_` entry point in code, and files under `Engine/` never use `Mutex` (see [Caches and reset](#caches-and-reset)); `EngineContractTests` checks all three, and that the `AstronomyKit` target in `Package.swift` declares no dependency. Comments may still name the C function a Swift function replaced. Generated tables live in a `Generated/` subdirectory of the module that reads them, with a generator under `Scripts/` that has a `--check` mode. Model data is compiled in; nothing is loaded at runtime.

## Conventions

- Engine functions are synchronous. They do not suspend, and they never hold a lock while running caller code or a cache computation.
- Failures are thrown as `AstronomyError` (see [Errors](#errors)). An error thrown by a caller's closure propagates unchanged.
- Units: distances in AU, velocities in AU per TT day, angles in degrees, right ascension and sidereal time in sidereal hours, times in days since 2000-01-01 12:00 on the named scale. A name says so when it departs from this, for example `radians`.
- Bodies are the public `CelestialBody` enum. A function that does not support a body throws `invalidBody` where the C function returns `ASTRO_INVALID_BODY`.
- Constants shared by more than one module live in `Foundation/`, with the published source of each value (see [Constants](#constants)). A constant used by one module stays in that module.

## Frames, vectors and rotations

In the tree: `Engine.swift` and `EngineVector.swift`.

A frame is a type parameter, so a vector moves between frames only through a rotation and a signature states its frame. The origin is not part of the type; the function name states it (heliocentric, barycentric, geocentric, topocentric).

| Type | Axes | C name |
|---|---|---|
| `Engine.EQJ` | Mean equator and equinox of J2000 | EQJ |
| `Engine.EQD` | True equator and equinox of the vector's time | EQD |
| `Engine.ECL` | Mean ecliptic and equinox of J2000 | ECL |
| `Engine.ECT` | True ecliptic and equinox of the vector's time | ECT |
| `Engine.HOR` | Observer's horizon: x north, y west, z zenith | HOR |
| `Engine.GAL` | Galactic | GAL |

A module that needs another frame, such as Jupiter's equator for its moons, declares it in its own directory. `Engine.EQM`, the mean equator and equinox of date, is declared in `Orientation/` (see [Earth orientation](#earth-orientation)).

- `Engine.Vector<F>`: `x`, `y`, `z` in AU and the `time` it is valid at.
- `Engine.State<F>`: position `x`, `y`, `z` in AU, velocity `vx`, `vy`, `vz` in AU per TT day, and `time`.
- `Engine.Rotation<From, To>`: `rot` in the C engine's index order, which the public `RotationMatrix[row:col:]` exposes unchanged. Applied to a vector `v`, component `j` of the result is `rot[0][j]·v.x + rot[1][j]·v.y + rot[2][j]·v.z`. `identity` exists only where `From == To`.

```swift
extension Engine.Vector {
    var length: Double { get }
    func angle(to other: Self) throws -> Double
}
extension Engine.State {
    var position: Engine.Vector<F> { get }
}
extension Engine.Rotation {
    func apply(to vector: Engine.Vector<From>) -> Engine.Vector<To>
    func apply(to state: Engine.State<From>) -> Engine.State<To>
}
```

- `length` is `sqrt(x² + y² + z²)` with no scaling, as in `Astronomy_VectorLength`, so a component above about 1e154 gives an infinite length.
- `angle(to:)` returns degrees from 0 through 180, as `Astronomy_AngleBetween` does. It throws `badVector` when the product of the two lengths is below 1e-8 or not finite, and returns exactly 0 or 180 when the cosine rounds to 1 or −1 or beyond.
- `apply(to:)` uses the formula above, and for a state applies it to the position and to the velocity. The result keeps the input's time. It cannot fail: `Astronomy_RotateVector` and `Astronomy_RotateState` return `ASTRO_INVALID_PARAMETER` only for an input that carries an error status, and Swift values have no status.

Combining, inverting and pivoting rotations, and the rotations between frames, are in `Orientation/` (see [Earth orientation](#earth-orientation)). Other vector arithmetic stays in the module that uses it until a second module needs it, and then moves here (see [Changing this contract](#changing-this-contract)).

## Constants

In the tree: `EngineConstants.swift`. Each constant is the double nearest its definition. `EngineConstantsTests` derives each one from its definition, not from the C engine.

| Constant | Definition |
|---|---|
| `Engine.secondsPerDay` | 86,400 SI seconds |
| `Engine.kilometersPerAU` | 149,597,870.7 km: IAU 2012 Resolution B2 defines the au as exactly 149,597,870,700 m |
| `Engine.speedOfLightAUPerDay` | 173.144 632 674 240 33 AU per day: the SI speed of light, exactly 299,792,458 m/s, times 86,400 s, over the au. Light crosses one au in 499.004 783 836 s, the IAU 2009 value |
| `Engine.radiansPerDegree`, `Engine.degreesPerRadian` | π/180 and 180/π |
| `Engine.radiansPerHour`, `Engine.hoursPerRadian` | π/12 and 12/π |
| `Engine.radiansPerArcsecond` | π/648,000 |

The C engine's `C_AUDAY`, 173.1446326846693, is 86,400 s over 499.0047838061 s, the DE405 light time for one au, and its `KM_PER_AU`, 149,597,870.69098932, is derived from `C_AUDAY`. Both differ from the published values by 6.0e-11 of their size: about 3e-8 s of light time and 9 m per au. The C angle factors (`DEG2RAD`, `RAD2DEG`, `HOUR2RAD`, `RAD2HOUR`, `ASEC2RAD`) are the same doubles as the engine's. `SearchCallbackContractTests` "Fixed positions within one light-day" and "Positions beyond one light-day" test the public API against the published light-day (#166).

## Compiled-in tables and the accepted range

In the tree: `EngineTables.swift` and `EngineChebyshev.swift`. `acceptedTTDays`, `unpackDoubles` and the planets' range check moved here from `Planets/` when the Moon became their second user, and the Moon's Chebyshev evaluator when Pluto became its second (#88).

```swift
extension Engine {
    static let acceptedTTDays: Double  // 1,461,000
    static func checkAcceptedTime(_ time: Engine.Time) throws
    static func unpackDoubles(count: Int, _ text: StaticString) -> [Double]
    struct ChebyshevTable {
        init(start: Double, recordDays: Double, recordCount: Int, degreeCount: Int, coefficients: [Double])
        func evaluate(tdb: Double) -> (position: SIMD3<Double>, velocity: SIMD3<Double>)?
    }
}
```

- `acceptedTTDays` is 4,000 Julian years, the C engine's `EPHEMERIS_MAX_TT_DAYS`. `checkAcceptedTime` throws `badTime` for a TT beyond it either way, or not finite; the planet and Moon functions call it first.
- `unpackDoubles` decodes a generated table: a base64 string literal of the doubles' little-endian bit patterns, skipping characters outside the base64 alphabet. It traps when the text does not hold exactly `count` doubles, which only a damaged generated file can cause.
- `ChebyshevTable` holds records in the layout of a JPL SPK type 2 segment: equal records from `start` in TDB days, coefficients record by record, then x, y and z, then by ascending degree. `evaluate(tdb:)` is the evaluator of the C engine's `ephemeris.c`: record `k` holds `start + k·recordDays ≤ tdb < start + (k + 1)·recordDays`, and Clenshaw's recurrence gives the value and its derivative per TDB day together. It returns `nil` before the first record, from the end on, and for a time that is not finite; as in C, the last doubles before the end can round up to it when the start is subtracted and fall outside. The initializer traps when the coefficients do not match the shape.

## Time and the Delta T model

In the tree: `EngineTime.swift`, `EngineDeltaT.swift`, `EngineDeltaTObserved.swift`, `EngineCalendar.swift`, and `Generated/DeltaTObservedTable.swift`, which `Scripts/generate-deltat-table.py` writes.

`Engine.Time` holds `ut` (modeled UT1 days), `tt` (Terrestrial Time days) and `deltaTModel`, the public `DeltaTModel` that relates them.

```swift
extension Engine.Time {
    init(ut: Double, tt: Double, deltaTModel: DeltaTModel)
    static func fromPair(ut: Double, tt: Double, deltaTModel: DeltaTModel) -> Engine.Time
    init(ut: Double, deltaTModel: DeltaTModel)
    init(tt: Double, deltaTModel: DeltaTModel)
    func adding(days: Double) -> Engine.Time
    func derived(ut: Double) -> Engine.Time
    static func civil(utcDays: Double, deltaTModel: DeltaTModel) -> (time: Engine.Time, fromTable: Bool)
    var utcDays: Double { get }
    static func days(year: Int, month: Int, day: Int, hour: Int, minute: Int, second: Double) -> Double
}
extension Engine.DeltaT {
    static func seconds(ut: Double, model: DeltaTModel) -> Double
}
```

- `init(ut:tt:deltaTModel:)` stores both scales as given. It keeps the model only when both are finite; otherwise the time is invalid and its scales stay as given, so a huge UT with an infinite TT still reports that UT.
- `fromPair(ut:tt:deltaTModel:)` rebuilds a time from recorded scales, as `AstroTime(tt:ut:deltaTModel:)` does, and returns `Engine.Time.invalid` (NaN scales, no model) when either scale is not finite.
- `isValid` is true when both scales are finite.
- `init(ut:deltaTModel:)` sets `tt = ut + ΔT(ut) / 86400`. Under every model, TT overflows from about |ut| = 8.7e157 days and the time is invalid with its UT kept.
- `init(tt:deltaTModel:)` is the bounded inverse of local patch 10 in MAINTAINING.md. It returns exactly the requested TT. It starts from `ut = tt`, iterates at most 128 times, and accepts a UT whose model TT is within `max(1e-12, 2ε|tt|)` days, where ε = 2.22e-16 is the double epsilon, so a large TT converges at the precision a double holds. In the TT gap left by a positive Delta T jump it bisects to the first representable UT after the jump. In the overlap of a negative jump it returns the solution iteration reaches first: the later one where Delta T is positive and the earlier one where it is negative (1900). A TT that is not finite, an iterate that is not finite, or no convergence gives `invalid`.
- `civil(utcDays:deltaTModel:)` and `utcDays` convert civil UTC with the existing generated table in `UTCOffsetTable.swift` (`CivilTime`), from 1961 on. Before 1961 the civil day count is taken as UT1. A TT inside a positive leap second maps to the following midnight, and where a negative historical step repeats civil times the later occurrence wins.
- `days(year:month:day:hour:minute:second:)` is the proleptic Gregorian day count from 2000-01-01 12:00, with every integer component clamped to `Int32`.
- `Engine.DeltaT.seconds(ut:model:)` evaluates `Observed.seconds(ut:)`, `espenakMeeus(ut:)` or `jplHorizons(ut:)`, which holds UT at 17 tropical years after J2000.
- `Engine.DeltaT.Observed` is `DeltaTModel.iersObserved`, the process default: daily IERS EOP 20 C04 and Bulletin A rows at 0h UTC from 1962-01-01, linear in UT1 between rows; before them the Table S15 v2020 spline in Julian epoch years, rebuilt by the generator as C0 and C1 cubic Hermite segments whose last ends on the first C04 value and rate; before −720 and after the last prediction the integral of HMNAO's long-term length-of-day model, continuous with the value at the join. `uncertainty(ut:)` and `regime(ut:)` give the stated uncertainty and the source. The rows hold the generator's exact integers in units of 1e-7 s, and each function performs the 3.2.0 C engine's `Astronomy_DeltaT_IersObserved`, `Astronomy_DeltaTUncertainty_IersObserved` and `Astronomy_DeltaTRegime_IersObserved` operations in the same order on the same values. The generator writes that C header from the same run and checks both. The model is continuous, so the TT inverse never meets a gap with it.

A UT-derived time (adding days or a search step) derives TT with the source time's model, so one calculation uses one model from its input to its result. The process default belongs to the public layer, not to `Engine`: engine functions take a model or a time that carries one, and the public layer reads the default once per call, when the caller passes no model.

A time derived from an invalid time, which has no model, is invalid too, even where its UT is finite: it keeps that UT and has a NaN TT. Engine code that derives a time from another uses `adding(days:)` or `derived(ut:)`, which apply this rule, so no engine function takes a fallback model.

There is no separate calculation-context object. The C engine kept per-call state in two places: the Delta T function captured in `astro_time_t`, which `Engine.Time` now carries, and the nutation and sidereal-time memo fields (`psi`, `eps`, `st`). The engine recomputes those values, reading nutation from the shared nutation cache (#86). Everything else a calculation needs is an argument or immutable model data.

`Engine.Time` is not `Equatable`. The public `AstroTime` keeps UT-only equality, ordering, hashing and `Codable`; engine code compares the scale it means. `AstroTimeTests` pins the public contract: two times with the same UT are equal and hash alike whatever their TT and model, signed zero UTs included, and the encoded form is exactly the UT, so decoding derives TT again. That loses a TT the model cannot give from the UT, such as a TT in the gap of a positive Delta T jump, which no UT reaches. Such a time is rebuilt from both scales: `fromPair` and `AstroTime(tt:ut:deltaTModel:)` give back every valid time bit for bit, and the times derived from it too (`EngineTimeTests`, `DeltaTModelCaptureTests`). A time whose recorded scales are not both finite is invalid, so it rebuilds as `invalid` with NaN scales and loses a finite UT it held, such as `Engine.Time(ut: 1e160)`.

The process default is a `Synchronization.Atomic` in the public layer (`AstronomyConfig`); `AstronomyConfig.setDeltaTModel` stores it and every public initializer given no model reads it once.

### Differences from the C engine

- `days(year:...)` normalizes the month with floor division before counting days. `Astronomy_MakeTime`'s Fliegel and Van Flandern formula truncates instead. The two agree for months 1 to 14 from year −999,999 on, where every division in that formula has a non-negative numerator. Outside that range the C formula can miss the Gregorian date by a day or two, though not every such month does: month 15 of 2001 gives 2002-03-03 instead of March 1, while months 26 and 38 of 2001 land on the right day.
- Espenak-Meeus takes NASA's decimal year, not the C engine's `2000 + (ut − 14) / 365.24217`, which puts 2000.0 at 2000-01-15 12:00 UT, about 14.5 days after NASA's 1 January (#165). NASA defines only the middle of each month, `year + (month − 0.5) / 12`. `Engine.DeltaT.decimalYear(ut:)` makes it continuous in the calendar the Canon's dates use: year `Y` is exactly `Y` at 1 January 0:00 UT, Julian through 1582 and Gregorian from 1583, and grows evenly through that year's days. 1582 has 355 days, so there is no jump at the reform. Beyond years −999,999 and 1,000,001 it grows by one mean Julian or Gregorian year. Each polynomial piece starts exactly at 1 January of its year. The C engine reaches each decimal year later than this: by 12.7 to 15.3 days from 1583 through 3000, depending on the leap cycle. Just before the reform the lag is smallest, about 4 days in 1581, because the Canon's Julian 1 January falls up to 10 days after the Gregorian one there, and it grows going back: about 9 days at 1000, 13 at 500, 21 at −500 and 32 at −1999. Within 1582's 355 days it grows from 4.3 to 14.5 days. Delta T moves from the C value by its rate of change times that lag: about 0.02 s in 2026, 0.3 s in 3000, 1.0 s at −500 and 2.1 s at −1999. `EngineDeltaTTests` checks the decimal year against Foundation's calendar, which switches on 1582-10-15 as the Canon does, and against NASA's month middles to within two days. The #94 solar-altitude observations now construct native time and record both scales explicitly. Ordinary Sun horizon uses native positions/orientation for named-model times, including a time pair constructed by an older public initializer; custom C-function times retain their staged C path. Other public time constructors and body horizon paths retain their existing staged contracts. `Scripts/solar-numerics` derives source/data-bound partial altitude terms and a finite public-input light-time return certificate, with separate runtime-classification guards and raw Debug/Release higher-precision measurements. Polynomial/frame/libm and Delta T evaluation altitude errors remain excluded from the public budget. `SolarAltitudeNumerics.md` documents the model-step allowances, gap/coverage rejection and within-build paired-altitude identity.
- A time derived from an invalid time is invalid. Under local patch 18, `Astronomy_AddDays` on a time with no Delta T function used the process-wide one, so `AstroTime(ut: 1e160).addingDays(-1e160)` was a valid time at J2000 in 3.1.0. This needs a time whose UT is finite and whose TT is not: with Espenak-Meeus, |ut| above about 8.7e157 days, which a caller passes or a search step at such magnitudes produces. The public API now follows the engine: the derived time keeps its UT, has a NaN TT and no model. The owner chose this on #168; `NativeCutoverTests` covers the public case.

### Published-value checks

Tests under `Tests/AstronomyKitTests/Engine/Foundation/` check the time code against published sources, not against C output; `DeltaTIersObservedTests` checks the observed model:

- Espenak-Meeus against NASA's polynomial page, transcribed independently, at ten points in each bounded piece, two in each open-ended one, and on both sides of every piece boundary; against Table 1 from −500 to +500 within the 4 seconds that page states, from 600 to 1800 within each value's published standard error, and against Table 2 (1955 to 2005) within the 0.1 s it is published to.
- The TT inverse in the gap or overlap of every Espenak-Meeus discontinuity, under both models where the model reaches it.
- Civil UTC against every row of `Scripts/time-data/tai-utc.dat`, read directly, at the start of each row and halfway to the next; IERS Bulletin C's 37 s; the ERFA `t_utctai` reference; the 2016 leap second and the 1961 negative step.
- Day counts against Meeus (Astronomical Algorithms, chapter 7), ERFA `eraCal2jd`, and Julian Day 0, with the 146,097-day 400-year cycle, normalization and `Int32` clamping.
- The observed model against the raw IERS files in `Scripts/deltat-data/`, parsed in the test independently of the generator: civil UTC at every daily C04 and Bulletin A row reproduces IERS UT1 − UTC within 1 µs, and the 12h C04 samples within the stated 0.16 ms interpolation error; Bulletin A against C04 over the year before the join; value continuity at every spline knot and regime join, rate continuity at every knot and at 1962, and a five-point second derivative across each; HMNAO's tabulated historical and extrapolated Delta T; and civil sunrise and sunset at Asheville against JPL Horizons with its EOP-based UT1 within 0.25 s.

The JPL Horizons model is a reverse-engineered approximation with no published values; its tests check that it equals Espenak-Meeus before the hold and is constant after it.

### Time test dispositions

Issue #96 required a recorded disposition for each test that imported `CLibAstronomy` or pinned C output. The time suites are here; the others are under their modules.

| Test | Disposition |
|---|---|
| `CivilTimeTests` | Kept, now on the engine. The suite uses `@testable` access to the internal `CivilTime.terrestrialTime` and `CivilTime.segments`, which the engine shares, and reaches the engine through `AstroTime` construction, `Sun.searchLongitude`, `Sun.position` and `AstronomyConfig.deltaTEspenakMeeus`. `EngineCivilTimeTests` and `EngineTimeConversionTests` hold the engine's own civil and TT-inverse checks. |
| `DeltaTThreadSafetyTests` | Rewritten by #95 to use only the public Swift API, which now runs on the engine's `Atomic` default. It checks that an existing time and its derived time retain the named model after the process default changes, and that concurrent public model swaps publish complete named models to time construction. |

## Errors

Engine code throws the public `AstronomyError`; there is no status enum. Each C status maps as follows.

| C status | Engine behavior |
|---|---|
| `ASTRO_SUCCESS` | Return the value |
| `ASTRO_INVALID_BODY` | Throw `invalidBody` |
| `ASTRO_NO_CONVERGE` | Throw `noConvergence` |
| `ASTRO_BAD_TIME` | Throw `badTime`, including for a result that is not finite and for a TT outside the accepted range |
| `ASTRO_BAD_VECTOR` | Throw `badVector` |
| `ASTRO_SEARCH_FAILURE` | The generic root search returns `nil`. Other searches keep each public API's current choice between returning `nil` and throwing `searchFailure` |
| `ASTRO_EARTH_NOT_ALLOWED` | Throw `earthNotAllowed` |
| `ASTRO_NO_MOON_QUARTER`, `ASTRO_WRONG_MOON_QUARTER` | Throw `noMoonQuarter`, `wrongMoonQuarter` |
| `ASTRO_INTERNAL_ERROR` | Throw `internalError` for a failed self-check. A caller's closure error is rethrown as is; the Swift trampolines in `Search.swift` return this status only to stop the C iteration |
| `ASTRO_INVALID_PARAMETER` | Throw `invalidParameter` |
| `ASTRO_FAIL_APSIS` | Throw `failApsis` |
| `ASTRO_INCONSISTENT_TIMES` | Throw `inconsistentTimes` |
| `ASTRO_NOT_INITIALIZED` | Not thrown by engine code. The public `GravitySimulation` throws `notInitialized` itself when it has no simulation handle |
| `ASTRO_BUFFER_TOO_SMALL` | Not thrown. Only `Astronomy_FormatTime` returns it, and the Swift layer does not call it |
| `ASTRO_OUT_OF_MEMORY` | Not thrown. Swift traps on allocation failure |
| Any other value | Not thrown; `AstronomyError.unknown` stays for API compatibility |

## Root search and light travel

In the tree: `EngineSearch.swift`.

```swift
extension Engine.Search {
    static let iterationLimit: Int  // 20
    static func ascendingRoot(
        from start: Engine.Time, to end: Engine.Time, toleranceSeconds: Double,
        _ function: (Engine.Time) throws -> Double
    ) throws -> Engine.Time?
}
extension Engine.LightTravel {
    static let iterationLimit: Int  // 10
    static func correct<F: Engine.Frame>(
        at time: Engine.Time, _ position: (Engine.Time) throws -> Engine.Vector<F>
    ) throws -> Engine.Vector<F>
}
```

The closures are synchronous and non-escaping. They take the place of the C callbacks, which the public `Search.swift` reaches through trampolines. An error a closure throws ends the call and propagates unchanged, and the closure is not called again.

`ascendingRoot` keeps `Astronomy_Search`'s expressions, branch order and 20-pass limit, after which it throws `noConvergence`. It includes local patch 20's ascending-bracket checks, so it does not report the descending root or the short constant window of #142. It returns `nil` where the C function returns `ASTRO_SEARCH_FAILURE`: for a single descending root, a function that never rises through zero in the window, or any window it cannot bracket. A function that is negative up to the later end and zero at it does rise through zero there, so the search does not return `nil` for it. Each time it derives takes the model of the time it comes from, and is invalid when that time is. Midpoints and interpolated roots come from the window's first bound in argument order, which begins as `start`.

`correct` keeps `Astronomy_CorrectLightTravel`. It calls `position` at most 10 times. Each backdate is `time.adding(days: -distance / Engine.speedOfLightAUPerDay)`, a UT offset whose TT comes from the observation time's model, and the iteration stops when TT moves less than 1e-9 days. A distance beyond one light-day throws `invalidParameter`, and a tenth call without convergence throws `noConvergence`. The result is the last vector `position` returned, with its time set to the time that call received, as the public `AstroSearch.correctLightTravel` reports it. The light-day is the published one (see [Constants](#constants)).

## Earth orientation

In the tree: `Orientation/EngineNutation.swift`, `Orientation/EngineEquationOfEquinoxes.swift`, `Orientation/EnginePrecession.swift`, `Orientation/EngineEarthRotation.swift`, `Orientation/EngineRotations.swift`, `Orientation/EngineFrameRotations.swift`, `Orientation/EngineCoordinates.swift`, `Orientation/EngineObserver.swift`, `Orientation/EngineAtmosphere.swift`, `Orientation/EngineRefraction.swift`, `Orientation/EngineHorizon.swift` and the generated `Orientation/Generated/IAU2000ATerms.swift` and `Orientation/Generated/EquinoxComplementaryTerms.swift`. Every C entry point listed for #86 under [C entry points by owner](#c-entry-points-by-owner) has a native counterpart here.

```swift
extension Engine.Nutation {
    struct Angles { var longitude, obliquity, longitudeRate, obliquityRate: Double }
    static func evaluate(centuries t: Double) -> Angles
    static let cache: Engine.BoundedCache<Engine.ExactKey, Angles>
    static func angles(tt: Double, cache: Engine.BoundedCache<Engine.ExactKey, Angles> = cache) -> Angles
    static func complementaryEquationOfEquinoxes(centuries t: Double) -> Double  // radians
}
extension Engine.EarthTilt {
    init(tt: Double, cache: Engine.BoundedCache<Engine.ExactKey, Engine.Nutation.Angles> = Engine.Nutation.cache)
    var tt: Double
    var nutation: Engine.Nutation.Angles
    var meanObliquity, meanObliquityRate: Double
    var trueObliquity, trueObliquityRate, equationOfEquinoxes: Double { get }
    var nutationRotation: Engine.Rotation<Engine.EQM, Engine.EQD> { get }
    var nutationRate: Engine.RotationRate<Engine.EQM, Engine.EQD> { get }
}
extension Engine.Precession {
    static func meanObliquity(tt: Double) -> Double
    static func meanObliquityRate(tt: Double) -> Double
    static func rotation(tt: Double) -> Engine.Rotation<Engine.EQJ, Engine.EQM>
    static func rate(tt: Double) -> Engine.RotationRate<Engine.EQJ, Engine.EQM>
}
extension Engine.EarthRotation {
    static func angle(ut: Double) -> Double
    static func meanSiderealTime(_ time: Engine.Time) -> Double
    static func apparentSiderealTime(
        _ time: Engine.Time,
        cache: Engine.BoundedCache<Engine.ExactKey, Engine.Nutation.Angles> = Engine.Nutation.cache
    ) -> Double
}
extension Engine.Rotation {
    func apply(to state: Engine.State<From>, rate: Engine.RotationRate<From, To>) -> Engine.State<To>
    var inverse: Engine.Rotation<To, From> { get }
    func then<Next>(_ next: Engine.Rotation<To, Next>) -> Engine.Rotation<From, Next>
    func pivoted(axis: Int, angle: Double) throws -> Self
}
extension Engine.FrameRotation {
    static let eqjToEcl: Engine.Rotation<Engine.EQJ, Engine.ECL>      // and eclToEqj
    static let eqjToGal: Engine.Rotation<Engine.EQJ, Engine.GAL>      // and galToEqj
    static func eqjToEqd(_ time: Engine.Time) -> Engine.Rotation<Engine.EQJ, Engine.EQD>
    // eqdToEqj, eqjToEct, ectToEqj, eqdToEct, ectToEqd, eqdToEcl, eclToEqd take a time;
    // eqdToHor, horToEqd, eqjToHor, horToEqj, eclToHor, horToEcl take a time and an Observer.
}
extension Engine.Spherical { init<F>(_ vector: Engine.Vector<F>) throws }      // latitude, longitude, distance
extension Engine.Vector { init(_ sphere: Engine.Spherical, time: Engine.Time) }
extension Engine.Equatorial { init<F>(_ vector: Engine.Vector<F>) throws }     // rightAscension, declination, distance
extension Engine.Ecliptic { init(_ vector: Engine.Vector<Engine.EQJ>) }        // vector in ECT, latitude, longitude
extension Engine.Observers {
    static func vectorOfDate(_ observer: Observer, at time: Engine.Time) -> Engine.Vector<Engine.EQD>  // and vector, J2000
    static func stateOfDate(_ observer: Observer, at time: Engine.Time) -> Engine.State<Engine.EQD>    // and state, J2000
    static func observer(atVectorOfDate vector: Engine.Vector<Engine.EQD>) -> Observer          // and atVector:, J2000
    static func gravity(latitude: Double, height: Double) -> Double
}
extension Engine.Atmosphere { init(elevation: Double) throws }               // pressure (Pa), temperature (K), density
extension Engine.AtmosphericRefraction {
    static func angle(_ refraction: Refraction, altitude: Double) -> Double
    static func inverseAngle(_ refraction: Refraction, altitude: Double) -> Double
}
extension Engine.Horizontal {   // azimuth, altitude, rightAscension, declination
    init(time: Engine.Time, observer: Observer, rightAscension: Double, declination: Double, refraction: Refraction)
}
extension Engine.Spherical { init(horizon vector: Engine.Vector<Engine.HOR>, refraction: Refraction) throws }
extension Engine.Vector where F == Engine.HOR {
    init(horizon sphere: Engine.Spherical, time: Engine.Time, refraction: Refraction)
}
```

- Nutation is IAU 2000A with the IAU 2006 adjustments, as SOFA's `iauNut06a` evaluates it: the 678 luni-solar and 687 planetary terms of `iauNut00a`, free core nutation omitted, then Δψ multiplied by 1 + 0.4697e-6 − 2.7774e-6·t and Δε by 1 − 2.7774e-6·t, with t in Julian centuries of TT. The luni-solar series takes its Delaunay arguments as `iauNut00a` does: l, F and Ω from the IERS 2003 polynomials, l′ and D from MHB2000's. The planetary series reads MHB2000's linear l, F, D, Ω and Neptune, the IERS 2003 mean longitudes of Mercury through Uranus, and the general precession in longitude. Each series is summed smallest term first, with each argument reduced to one turn. `Scripts/generate-nutation-table.py` writes both tables and the two adjustment factors from ERFA 2.0.1's `nut00a.c` and `nut06a.c`, pinned in `Scripts/orientation-data` with their SHA-256, and `--check` runs in CI. The rates are the derivatives of the same expressions. Angles are in degrees and rates in degrees per TT day.
- One evaluation costs about 20 times what IAU 2000B did. In Release on an Apple M1 Max (macOS 27.0.1, Swift 6.4), uncached calls averaged 41.3 to 42.7 µs over five rounds of 4,096 instants from about −2000 to 6000, against 2.09 to 2.18 µs for IAU 2000B at the parent commit, and cached reads 48 to 50 ns, against 51 to 52 ns. `EngineNutationCacheTests/latency` writes these figures to the file `NUTATION_LATENCY_OUTPUT` names. They are observations from one host, not limits.
- `angles(tt:)` reads the shared cache, keyed by the exact TT in Julian centuries (`tt / 36525`), the value the series reads. One evaluation gives the angles and the rates, so an angle caller warms the entry a rate caller reads. `Engine.Time` carries no counterpart of the C engine's `psi`, `eps` and `st` memo fields, and reading the cache leaves a time's scales and model untouched. In C a caller could pre-fill those fields and have them used, but no public API does: `AstroTime` gets its `astro_time_t` from the C time constructors, which set them to NaN, or from a C result, which holds only values the C engine computed for that TT, and each public call works on a local copy. So the memo only saved recomputing within one call, and the shared cache now does that with the same values. `EngineNutationCacheTests` counts the evaluations.
- Precession and mean obliquity use Vondrák, Capitaine & Wallace (2011), with the 2012 corrigendum, following ERFA 2.0.1 `eraLtp`, `eraLtpequ` and `eraLtpecl`. The equator pole is the third matrix row; the normalized cross product of equator and ecliptic poles is the equinox row, and their cross product supplies the second row. Mean obliquity is the angle between those same poles. Analytic derivatives include the harmonic series, pole square roots and equinox normalization. EQJ remains mean J2000 without the ICRS frame bias of `eraLtpb`. ERFA’s rounded coefficients leave a 4.8482443e-12 rad (one microarcsecond) J2000 matrix residual; the implementation retains that published residual rather than applying another frame correction. The fixed J2000 ecliptic tilt remains 84381.406 arcseconds. [Source recipes, interval bounds and limits](Scripts/orientation-data/long-term/README.md) accompany the pinned archive.
- The nutation matrix is R1(−εA − Δε)·R3(−Δψ)·R1(εA), SOFA's `iauNumat`, from EQM to EQD.
- `Engine.RotationRate` holds the derivative of a rotation per TT day in the rotation's own slots, so it cannot be applied as a rotation. `apply(to:rate:)` takes a state through a rotation that moves with time: the position is rotated, and the velocity is rotated plus the rate applied to the position. They port local patch 12's `precession_rot_rate` and `nutation_rot_rate`.
- `inverse` is the transpose. `then(_:)` is `Astronomy_CombineRotation`: the first rotation, then the second. `pivoted(axis:angle:)` is `Astronomy_Pivot`: after the rotation, it turns vectors `angle` degrees counterclockwise about axis 0, 1 or 2, seen from the axis's positive end. It throws `invalidParameter` for another axis or an angle that is not finite.
- `Engine.FrameRotation` has one rotation for each C frame pair, built the way the C engine builds it: EQJ to EQD is precession then nutation, EQD and ECT differ by R1(εA + Δε), EQJ and ECL by R1(ε0), and the horizon rotations turn the observer's zenith, north and west by apparent sidereal time. Each reverse rotation is the transpose. The horizon rotations read only the observer's latitude and longitude; the public layer validates the observer. Rotations at a time read nutation through the shared cache.
- The galactic rotation is the J2000 frame of the Hipparcos Catalogue (Vol. 1, §1.5.3; Murray 1989), built from its defining angles: north galactic pole at αG = 192.85948°, δG = +27.12825°, and the ascending node at galactic longitude lΩ = 32.93192°. This replaces the C engine's matrix, which converts the IAU 1958 B1950 constants through the true equator of B1950 and is 8.77″ from those axes (#152). The public `RotationMatrix.equatorialJ2000ToGalactic()` and `galacticToEquatorialJ2000()` already return it, ahead of #96.
- `Engine.Spherical(_:)` is `Astronomy_SphereFromVector`: longitude counterclockwise from x seen from +z, in [0, 360), and latitude in degrees. A vector on the z axis has longitude 0 and latitude ±90; one where x² + y² and z are both zero throws `invalidParameter`. `Engine.Equatorial(_:)` is the same with the longitude in hours. `Engine.Ecliptic(_:)` is `Astronomy_Ecliptic`: the J2000 vector rotated to the true ecliptic of date, with longitude 0 on the ecliptic pole. Longitudes that round up to 360 when moved into range are returned as 0.
- Observer positions use the ellipsoid of the IERS Conventions (2010), Table 1.1: equatorial radius 6,378.1366 km and flattening 1/298.25642, in SOFA's `iauGd2gce` form, turned by apparent sidereal time. The velocity of date is the IERS nominal angular velocity 7.292115e-5 rad/s crossed into the position; the J2000 state rotates position and velocity without the rotation rate, as the C engine does. Distances convert with the published au (see [Constants](#constants)), not the C engine's. The inverse runs the C engine's Newton iteration on the ellipsoid, at most 11 steps with tolerance 2e-8 km, and puts a point within 1 mm of the axis at latitude ±90 and longitude 0. A component that is not finite, or too large to convert to kilometres, and an iteration that does not converge give NaN latitude, longitude and height; off the axis the C engine ends the process in both cases (#174), and for an of-date vector on the axis it returns ±90 for a non-finite z (a J2000 one leaves the axis under precession, so C exits). Gravity is the WGS 84 normal gravity of NIMA TR8350.2 (equations 4-1 and 4-3).
- `Observer.geocentric` is at latitude 0 and height −6,378,136.6 m, the ellipsoid's equatorial radius, so its vector is exactly zero (#154). The public constant changed with #86, so the C engine also puts it at the centre.
- `Engine.Atmosphere(elevation:)` is the 1976 U.S. Standard Atmosphere (NOAA-S/T 76-1562) from −500 to 100,000 m geopotential height, the range the C engine accepts; it throws `invalidParameter` outside that or for a value that is not finite. Below 86 km geometric height (84,852 m geopotential) it uses the standard's seven layers, each computed from the defining constants g0, M0, R*, sea-level pressure and temperature and the lapse rates, so the troposphere exponent is g0·M0/(R*·L) = 5.2558761 and the 11 km and 20 km base pressures are 22,632.064 and 5,474.889 Pa (#153). The temperature it returns there is the kinetic temperature: the molecular-scale temperature times table 8's M/M0, interpolated linearly in geometric height from 80 to 86 km. Above 86 km it converts to geometric height with eq 19 and integrates eqs 35 to 38 for N2, O, O2, Ar and He from table 9's densities with fourth-order Runge-Kutta in 100 m steps, restarting at 91, 95, 97 and 100 km; pressure is Σn·R*·T/NA and density Σn·M/NA (#175). The public `Atmosphere.at(elevation:)` already uses it; rise/set searches still read the C engine's atmosphere for horizon refraction at the observer's ground height until #96. Up to 32 km the two densities agree to about 3e-5 relative; above 32 km C keeps its +1 K/km layer, and its density differs by 2.5% at 40 km, 21% at 60 km and a factor of 3.3 at 100 km. The largest absolute difference, 1.2e-4 of sea-level density near 36 km, moves the horizon refraction by about 0.25″.
- `AtmosphericRefraction.angle` is `Astronomy_Refraction`: Sæmundsson's formula as Meeus gives it (Astronomical Algorithms, 2nd ed., eq. 16.4) with the altitude held at −1° below that, as JPL Horizons does. `.normal` scales the result below −1° linearly to zero at −90°; `.jplHorizons` does not. `.none` gives 0 for any altitude; the other models give 0 outside −90 to 90 and NaN for NaN, as in C. `inverseAngle` is `Astronomy_InverseRefraction`, with the same 1,000-step iteration, 1e-14 tolerance, two-cycle rule and zero results. Sæmundsson's formula is slightly negative at the zenith (−0.0019′); the engine keeps it, as C does, without Meeus's +0.0019279′ correction.
- `Engine.Horizontal` is `Astronomy_Horizon`: azimuth east of north in [0, 360), 0 where the direction has no horizontal component, and azimuth 0 with a NaN altitude for a right ascension or declination that is not finite; with refraction, the altitude rises by the refraction at the geometric altitude and the right ascension and declination turn toward the zenith by the same amount unless the refraction is not positive or the result is within 3e-4° of the zenith. `Engine.Spherical(horizon:refraction:)` and `Engine.Vector(horizon:time:refraction:)` are `Astronomy_HorizonFromVector` and `Astronomy_VectorFromHorizon`.
- The Earth rotation angle is SOFA's `iauEra00`, in degrees from 0 up to 360. Mean sidereal time is `iauGmst06`: the angle at `time.ut` plus the IAU 2006 polynomial at `time.tt`. Apparent sidereal time adds the equation of the equinoxes, `iauEe00`: Δψ·cos εA plus the complementary terms of IAU 1994 Resolution C7 (IERS Conventions (2010), Table 5.2e; SOFA `iauEect00`). Both sidereal times are in hours from 0 up to 24; a value that rounds up to the period is returned as 0. A time or day count that is not finite gives NaN, and nutation for it is computed without touching the cache. The complementary terms are the 33 terms and the one multiplied by t that `Scripts/generate-nutation-table.py` writes from ERFA 2.0.1's `eect00.c`, pinned beside `nut00a.c`. The series reads the IERS 2003 fundamental arguments (`iauFal03`, `iauFalp03`, `iauFaf03`, `iauFad03`, `iauFaom03`, `iauFave03`, `iauFae03`, `iauFapa03`) and is summed smallest term first, as SOFA sums it. It reaches about 2.65 mas between 1950 and 2050. `Engine.EarthTilt` evaluates it when `equationOfEquinoxes` is read, not with the cached nutation, so the rotations that never read that property do not pay for it.

### Differences from the C engine

- The galactic rotation (#152), the atmosphere's constants (#153) and the observer inverse's non-convergence (#174), as described above.
- Above 32 km `Astronomy_Atmosphere` keeps its 20 to 32 km layer (+1 K/km) up to 100 km; the native atmosphere follows the standard's later layers (#175). At 47 km C gives 243.65 K and the standard 270.65 K.
- Nutation is IAU 2006/2000A (#250); the C engine evaluates IAU 2000B with its full 77-term table (local patch 7). Sampled every half day with pyerfa 2.0.1.5, the largest differences in Δψ·sin ε and Δε are 0.99 and 0.93 mas from 1995 to 2050, 1.6 and 2.6 mas within ten years of 1800, 1.7 and 2.2 mas of 2200, 26 and 35 mas of 1000, 27 and 35 mas of 3000, 394 and 527 mas of −2000, and 441 and 574 mas of 6000. Most of the growth comes from the t² terms that IAU 2000B leaves out of its arguments. Every native function that reads `Engine.Nutation` or `Engine.EarthTilt` inherits the difference: the nutation and frame rotations of date, apparent sidereal time and everything built on it, and the true ecliptic of date.
- Apparent sidereal time includes the complementary terms of the equation of the equinoxes (#170); `Astronomy_SiderealTime` leaves them out. The two differ by up to about 2.65 mas of rotation angle between 1950 and 2050 (about 8 cm of position at the equator). Every native function that reads `Engine.EarthRotation.apparentSiderealTime` inherits the difference: the observer's position and state, of date and J2000 (`Engine.Observers.vectorOfDate`, `vector`, `stateOfDate`, `state`); the observer recovered from a vector, of date and J2000 (`observer(atVectorOfDate:)`, `observer(atVector:)`), where it shifts the longitude by the same angle; the horizon rotations from and to the equator of date, J2000 and the ecliptic (`Engine.FrameRotation.eqdToHor`, `eqjToHor`, `eclToHor` and their inverses); and `Engine.Horizontal(time:observer:rightAscension:declination:refraction:)`. The nutation matrix, the precession matrix and the ecliptic rotations do not read it.

### Published-value checks

Tests under `Tests/AstronomyKitTests/Engine/Orientation/` check against SOFA through ERFA 2.0.1 (the commit `THIRD_PARTY_NOTICES` pins), including the separately compiled official ERFA long-term oracle:

- The values in ERFA's own test program, `t_erfa_c.c`: `t_nut06a`, `t_numat`, `t_era00` and `t_gmst06`, each within SOFA's tolerance or tighter; the Vondrák `t_ltp`, `t_ltpequ` and `t_ltpecl` values within their published 1e-14 tolerance; `t_gst06a` and `t_ee06a` within 1e-12 (ERFA's tolerance for `t_gst06a`): SOFA forms both through the CIO locator, and its equation of the equinoxes differs from the engine's `iauEe00` form by 8.4e-13 rad there; `t_ee00` within 1e-18 on SOFA's own inputs; and `t_eect00` within 1e-20.
- pyerfa 2.0.1.5 at eight epochs from 1600 to 2500, with UT1 and TT apart: nutation to 1e-15 rad, which it also meets at about −2000 and 6000, the Earth rotation angle and mean sidereal time to 1e-12 rad, `eect00` to 1e-20 rad, and the eight fundamental arguments it reads to 5e-12 rad.
- `t_rx`, `t_ry` and `t_rz` for pivoting, `t_c2s`, `t_p2s`, `t_s2c` and `t_s2p` for the spherical conversions, `t_hd2ae` through the horizon rotation, and `t_icrs2g` through the galactic rotation. The galactic matrix matches `eraIcrs2g`'s to 1e-15 and the Hipparcos Catalogue's printed A_G to its ten decimals.
- At the eight pyerfa epochs, the frame rotations against N·P, R1(εA + Δε) and R1(ε0) built from the archived long-term precession matrix, its pole-derived obliquity and the SOFA nutation angles, to 2e-15, and the ecliptic of date against the same rotation followed by SOFA's `eraC2s` definition.
- Observer positions against pyerfa `gd2gce` on the IERS 2010 ellipsoid at seven latitudes and heights, including both poles, 2,000 km up and 500 m down, to 1e-6 m; the inverse against `gc2gde` to 1 mm in height; gravity against TR8350.2's equations; and the geocentric observer's zero vector.
- The atmosphere's layer base pressures and temperatures as the 1976 standard prints them, the closed form at 1e-12 at twenty-one heights up to 79 km, including both sides of the 11 km and 20 km layer boundaries, and table 8's kinetic-temperature ratios. From 86 km, table I's temperature, pressure and density at twelve heights, table VIII's number densities at seven, continuity at 86, 91, 95, 97 and 100 km, and the 100 km geopotential endpoint against eq 27 and table I. Some printed values stray from the standard's own equations by more than half a unit in their last figure: table I's pressure by 1.18e-5 beyond its rounding at 47 km, 5.6e-6 at 51 km and at most 4.3e-6 from 86 km, and table VIII's O and He densities by 1.85e-5 at 102 km. Each comparison allows its table's largest excess, rounded up to 1.5e-5, 5e-6 or 2e-5, on top of half a unit.
- Refraction against Sæmundsson's formula as Meeus prints it, at the horizon (28.98′), across both branches, at −90°, 90° and outside the range; the inverse on both models and on every double from −80° for 2,000 ulps; `t_hd2ae` through `Engine.Horizontal`.
- Unbiased precession matrices and pole-derived obliquity from the pinned, unmodified ERFA C oracle across TT ±1461000 days, including exact endpoints and adjacent interior doubles, to 1e-15. The biased `eraLtpb` matrices remain distinct controls. Public forward/reverse date-frame and horizon composition, observer states and nonfinite propagation are checked at the same epochs under both named time models.
- Rates against five-point differences of the values on exact binary-fraction stencils, and the moving-rotation state against the derivative of the rotated position.
- The nutation cache's work counts with a private registry: one evaluation per instant across angle, rate, tilt and sidereal-time callers, signed-zero keys, nonfinite bypass, eviction of the oldest of 32, reset, and simultaneous callers.

### Orientation test dispositions

| Test | Disposition |
|---|---|
| `NutationCacheTests`, `Scripts/performance/test-nutation-cache.sh`, `nutation_cache_probe.c` and `nutation_output_probe.c` | Retired by #95. `EngineNutationCacheTests` replaces the C implementation checks with native work counts, a zero-capacity negative control, exact-key, bypass, eviction, reset, concurrency, and series-equality checks. |
| `InverseRefractionTests` | Kept, on the engine since the geometry link: it checks termination of the public inverse refraction and pins its recorded bits. `EngineRefractionTests` checks the native inverse against Sæmundsson's formula. |
| `ReproducibilityTests` | The C bit patterns it pinned across modules (positions, rates, events) were engine output, not published values, and were retired at the cutover rather than re-recorded. The Chiron repeatability check and the Swift-side illumination value stay. The orientation parts the retired rows reached are checked against SOFA here. |
| `RotationTests`, `AtmosphereTests`, `ObserverVectorTests` | Public-API checks against published values, as normal assertions for #152, #153 and #154; they need no C. |

## Planetary trajectories

In the tree: `Planets/EnginePlanets.swift`, `Planets/EnginePlanetDE441.swift`, `Planets/EnginePlanetPolynomial.swift`, `Planets/EngineVSOP87B.swift`, `Planets/EnginePlanetPositions.swift`, `Foundation/EngineDirectChebyshevTable.swift` and the generated tables in `Planets/Generated/`.

```swift
extension Engine {
    enum Planet: Int, CaseIterable { case mercury, venus, earth, mars, jupiter, saturn, uranus, neptune }
    // init?(_ body: CelestialBody): nil for every other body
}
extension Engine.VSOP87B {
    struct Model { let termCounts: [[Int]]; let terms: [Double] }   // A, B, C of each term
    static func model(_ planet: Engine.Planet) -> Model
    static func coordinates(_ model: Model, millennia t: Double) -> SIMD3<Double>   // longitude, latitude, radius
    static func derivatives(_ model: Model, millennia t: Double) -> SIMD3<Double>   // per Julian millennium
    static func rectangular(_ sphere: SIMD3<Double>) -> SIMD3<Double>
    static func velocity(_ sphere: SIMD3<Double>, rates: SIMD3<Double>) -> SIMD3<Double>   // AU per day
    final class Cache { init(capacity: Int = 32, registry: Engine.CacheRegistry); let registry: Engine.CacheRegistry }
    static let cache: Cache
    static func coordinates(_ planet: Engine.Planet, millennia t: Double, cache: Cache = cache) -> SIMD3<Double>   // and derivatives
    static let toEquatorial: Engine.Rotation<Engine.VSOP87Ecliptic, Engine.EQJ>
}
extension Engine.Planet {
    func heliocentricEclipticPosition(at time: Engine.Time, cache: Engine.VSOP87B.Cache = VSOP87B.cache) throws -> Engine.Vector<Engine.VSOP87Ecliptic>
    func heliocentricEclipticState(at time: Engine.Time, cache: Engine.VSOP87B.Cache = VSOP87B.cache) throws -> Engine.State<Engine.VSOP87Ecliptic>
    func heliocentricPosition(at time: Engine.Time, cache: Engine.VSOP87B.Cache = VSOP87B.cache) throws -> Engine.Vector<Engine.EQJ>   // and heliocentricState
    func heliocentricDistance(at time: Engine.Time, cache: Engine.VSOP87B.Cache = VSOP87B.cache) throws -> Double
}
extension Engine.PlanetPolynomial {
    static let start: Double  // −36,524.5: 1900-01-01 00:00 TT
    static let stop: Double   // 36,889.5: 2101-01-01 00:00 TT
    static func covers(_ tt: Double) -> Bool  // start ≤ tt < stop
    struct Model {
        let degree: Int, width: Double, coefficients: [Double], included: [Bool]
        var excludedSegments: [Int] { get }
        func start(ofSegment k: Int) -> Double
        func segment(containing tt: Double) -> Int?
        func position(tt: Double) -> SIMD3<Double>?
        func state(tt: Double) -> (position: SIMD3<Double>, velocity: SIMD3<Double>)?
    }
    static func model(_ planet: Engine.Planet) -> Model
    static func position(_ planet: Engine.Planet, tt: Double) -> SIMD3<Double>?   // and state
}
```

- From 1900-01-01 through 2131-01-01 TT, with 32-day exterior blends, every public planet position, state and distance uses a compiled binary64 DE-backed physical-center trajectory. Mercury, Venus, Earth, Mars, Jupiter and Neptune use DE441 barycenters; Earth adds its DE441 center offset, Jupiter adds JUP365, Neptune adds NEP098, and Saturn adds SAT441. The issue #248 owner decision authorizes Uranus alone to combine the DE442 barycenter embedded in URA184 with the DE441 Sun and URA184 center offset.
- `systemHeliocentricState` uses the system center inside the same window. Gravity and GM-weighted origins use that route, while public body states use the physical center. Position and velocity convert TDB records to TT analytically, including the blend derivative; exact endpoints and adjacent representable values are tested for every planet. The retained polynomial/VSOP87B model remains outside the blends.
- `Scripts/generate-planet-de441.py`, `Scripts/generate-saturn-tables.py` and `Scripts/generate-planet-cycle-census.py` read pinned official ranges and the independent `Scripts/apparent-place-data/dtdb.c` clock copy. No selected DE generator reads `Sources/CLibAstronomy`. The generated representation is compiled static Swift data, consistent with the full-DE441 Moon; issue #245 owns any move to mapped SwiftPM resources.
- The direct-source complete-cycle census samples physical and system-center range rate every three hours and repeats at 1.5 hours, retaining exact-zero samples and every sign change. Jupiter has 4 physical/2 system crossings, Uranus 6/2 and Neptune 430/6. System-center global extrema select the nearest same-kind physical candidates, matching the existing Neptune global-distance search contract; all six native principal events are within 10 seconds of the direct-source roots under the unchanged 60-second criterion.
- `Scripts/generate-planet-tables.py` writes the tables from the C engine's `vsop87b_full.h` and `polynomial-data.h`, whose SHA-256 hashes `Scripts/planet-data/manifest.json` pins, and `--check` runs in CI on macOS and Linux. The headers stay where the C engine reads them; when #96 removes the C target, it moves them to `Scripts/planet-data` and updates the manifest. `--published DIR` also compares the VSOP87B table with the eight files IMCCE publishes, whose URLs and hashes are in the manifest: all 35,080 terms in 135 series match in order and value.
- Each table is a base64 string literal of the doubles' little-endian bit patterns, decoded once per planet on first use. Array literals do not scale: a 100,002-element `[Double]` literal took 390 s and 1.66 GB to compile in Debug, and the polynomial tables hold 1,431,768 doubles. The data is still compiled in; nothing is read from a file. `Engine.unpackDoubles` decodes them (see [Compiled-in tables and the accepted range](#compiled-in-tables-and-the-accepted-range)). Decoded, the polynomial tables take 11.5 MB and the VSOP87B terms 0.8 MB, kept for the life of the process.
- VSOP87B gives heliocentric ecliptic longitude and latitude in radians and radius in AU, referred to the dynamical ecliptic and equinox of J2000, as Poisson series in Julian millennia of TT. The tables keep the published term order. `coordinates` and `derivatives` port `VsopCoords` and `VsopDeriv`: every term in table order, with Neumaier compensation inside each power of t and, for the coordinates, across the powers; each longitude power's contribution is reduced modulo 2π. At the four t the tests use, the compensated coordinates equal an exactly rounded sum of the same terms bit for bit, and plain addition is off by 1.4e-12 to 2.2e-10 rad in Mercury's longitude. A t that is not finite gives NaN.
- `Engine.VSOP87Ecliptic` is the frame of VSOP87, declared in `Planets/` with its rotation to EQJ, since only this module uses it. It is not ECL: `toEquatorial`, the rotation to FK5 J2000 that `vsop87.doc` prints, tilts by an obliquity 0.003″ larger than IAU 2006's and adds rotations of up to 0.1″. The engine takes FK5 J2000 as EQJ, as the C engine does.
- The polynomials are AstronomyKit's degree-12 Chebyshev fits of the compensated VSOP87B position in the same frame, in segments of 8 days (Mercury, Earth), 16 (Saturn, Neptune) or 32 (the others), from `start` up to `stop`. 413 segments that did not meet the 1e-12 AU fit budget are excluded: 409 of Mercury's and 4 of Venus's.
- Segment `k` holds `start + k·width ≤ tt < start + (k + 1)·width`, as in `polynomial.h`: the index is `Int((tt − start) / width)`, moved back one where the subtraction rounded the double below a boundary up to the boundary's offset. Every width is a power of two, so the division is exact. Outside the span, including a TT that is not finite, and in an excluded segment, the functions return `nil` and the caller uses the full series. The static functions check the span before they decode a table.
- Clenshaw's recurrence gives the position and its derivative together; velocity is in AU per TT day. A state's position is the same double as the position.
- The `Engine.Planet` functions give heliocentric position, state and distance on the VSOP87 axes or in EQJ. They throw `badTime` when |TT| is above `Engine.acceptedTTDays` or is not finite, before touching the cache, and when a result component is not finite. Inside the DE window they compose the selected source tables. Outside it, qualified polynomial segments avoid the series and cache; elsewhere the retained series provides the rectangular position, chain-rule velocity and radius. The EQJ results rotate the ecliptic state.
- `VSOP87B.cache` keeps, for each planet, 32 coordinate and 32 derivative results, keyed by the exact bits of t, in two `BoundedCache`s registered with `CacheRegistry.shared`. A position, a state and a distance at one instant share one evaluation of each series they need; the distance reads the coordinates entry. A t that is not finite bypasses it. The C engine keeps the radius separately so a distance alone sums only the radius series; here a distance alone sums all three coordinates.

### Published-value checks

Tests under `Tests/AstronomyKitTests/Engine/Planets/`:

- VSOP87B terms as IMCCE prints them in `VSOP87B.mer`, `VSOP87B.ear` and `VSOP87B.nep`, the 135 series and 35,080 terms in all, and the term counts of Mercury's series. The comparison of every term is the generator's `--published` mode, which needs the IMCCE files and does not run in CI.
- The IMCCE check values in `vsop87.chk` (VSOP87B, every planet at ten dates from 1100 to 2000, SHA-256 in `PublishedVSOP87.swift`): the series coordinates and their rates within 1e-10, and the ecliptic position and velocity from the planet functions against the rectangular form of the published values, through the polynomials at J2000 and the series at the other nine dates. This pins the axis order and the frame. The rotation's entries equal `vsop87.doc`'s.
- The heliocentric distance from the polynomials alone against the JPL Horizons vectors in `Scripts/reference-data/sources/distance/heldout`, within the allowances `DistanceAccuracyTests` applies to the public distance: 1,067 of the 1,072 planet records. The other 5 fall in excluded segments.
- All 1,072 records through the planet functions, including five outside qualified retained polynomial segments: distance stays within the existing allowances and EQJ direction stays within 1′ of Horizons' ICRF vector. The selected-window rows exercise the DE-backed route; retained rows keep their prior checks.
- The `JPLValidationTests` geocentric suites for the Sun and Mercury to Neptune and the Asheville suites for Mercury to Neptune, at their tolerances (1′, and 1.5′ for Asheville Neptune): the astrometric J2000 direction, Horizons' definition, from `Engine.Positions.geocentricPosition` with no aberration, which backdates the planet functions through `Engine.LightTravel`, and the Asheville observer through `Engine.Observers`. The geocentric distances of the same bodies in `distance-fixtures.json` (1,072 records) within their allowances. The parallax at Asheville is at most about 13″ on these dates, too small for the 1′ check to see, so the shift between an Asheville row and the geocentric row on the same date is checked against the engine's within 0.2″; the rows are printed to 0.01 s and 0.1″. Mercury's 02-11 row has no geocentric row on that date, so it is skipped. The check fails with no observer or with a negated one; an observer misplaced by less than about a degree would still pass it.
- Cache work counts with private registries: no lookups inside the polynomial span; one evaluation per series shared by position, state and distance; reuse in an excluded segment; separate entries per planet; signed-zero keys; non-finite bypass; eviction of the oldest of 32; reset through a registry; a hit returning the caller's own time; simultaneous callers; and a cache with no capacity, which evaluates every time. Separately, the shared cache is checked to be registered with `CacheRegistry.shared`, which `Engine.resetCaches()` empties.
- Compensated summation against exact summation, and the accepted range's ends, NaN, infinities and an invalid time on every planet function.
- Clenshaw's recurrence against T_k(cos θ) = cos kθ and dT_k/dx = k·U_{k−1}(x) for every degree; every boundary of every planet and the double below it; every segment at its first, middle and last double, excluded or not; velocity against five-point differences of the position; and adjacent segments, which meet within 2e-12 AU (2.0e-13 at most).

### Planet test dispositions

| Test | Disposition |
|---|---|
| `PolynomialTests` | Moved onto the public API: it checks that `heliocentricPosition` and `heliocentricState` read the same representation at the coverage boundaries, selected by TT. `EnginePlanetPolynomialTests` checks the Swift polynomials at every segment boundary. |
| `VsopCacheTests`, `Scripts/performance/test-vsop-cache.sh` and `vsop_cache_probe.c` | Retired by #95. `EngineVSOP87BCacheTests` replaces the C implementation checks with native work counts, caller-model, exact-key, bypass, eviction, reset, concurrency, and zero-capacity negative-control checks. |
| `ReproducibilityTests` planetary cases | Retired at the cutover, as recorded under [Earth orientation](#earth-orientation). The planet series is checked against IMCCE and Horizons here. |
| `DistanceAccuracyTests` and the `JPLValidationTests` planet suites | Published-value checks of the public API on the engine. `EnginePlanetPositionsTests` and `EnginePlanetHorizonsTests` apply the same fixtures and allowances to the Swift planet functions. `EnginePlanetHorizonsTests` reads the geocentric vector from `Engine.Positions.geocentricPosition` (see [Positions](#positions)). |

## Moon

In the tree: `Moon/EngineMoon.swift`, `Moon/EngineMoonStates.swift`, `Moon/EngineLibration.swift`, `Moon/EngineMoonEphemeris.swift`, `Moon/EngineMoonDE441Full.swift`, `Moon/EngineTDB.swift`, `Moon/EngineFrameBias.swift` and the generated `Moon/Generated/MoonDE440Coefficients.swift` and `Moon/Generated/TDBTerms.swift`. Every C entry point listed for #87 under [C entry points by owner](#c-entry-points-by-owner) has a native counterpart here: `Astronomy_GeoMoon`, `Astronomy_EclipticGeoMoon`, `Astronomy_GeoMoonState`, `Astronomy_GeoEmbState`, `Astronomy_MoonEclipticState` and `Astronomy_Libration`.

```swift
extension Engine {
    enum ECM: Frame {}    // mean ecliptic and equinox of date
    enum ICRS: Frame {}
    struct EclipticState { var state: State<ECT>; var longitude, latitude, distance, longitudeRate, latitudeRate, distanceRate: Double }   // in Foundation/, with tilted(by:) and tiltRate(by:rate:)
    struct Libration { var latitude, longitude, moonLatitude, moonLongitude, distanceKilometers, diameter: Double }
    static func normalizedLongitude(_ longitude: Double) -> Double    // [0, 360), the C engine's NormalizeLongitude
    static func longitudeOffset(_ difference: Double) -> Double       // (−180, 180], the C engine's LongitudeOffset
}
extension Engine.Moon {
    typealias Cache = Engine.BoundedCache<Engine.ExactKey, SIMD3<Double>>
    static let cache: Cache
    static func coordinates(tt: Double, cache: Cache = cache) -> SIMD3<Double>   // longitude, latitude (radians, ECM), distance (AU)
    static func evaluate(tt: Double) -> SIMD3<Double>      // the same, without the cache
    static func meanEclipticPosition(tt: Double, outer: Bool = false) -> SIMD3<Double>?  // selected DE440 or DE441 source, ECM
    static func meanEclipticSourceState(tt: Double, outer: Bool = false) -> (position: SIMD3<Double>, velocity: SIMD3<Double>)?
    static func meanEclipticState(at time: Engine.Time, cache: Cache = cache) -> (state: Engine.State<Engine.ECM>, distance: Double, distanceRate: Double)
    static func rectangular(_ sphere: SIMD3<Double>) -> SIMD3<Double>
    static func eclipticAngles(_ vector: Engine.Vector<Engine.ECT>) -> (longitude: Double, latitude: Double)   // degrees, longitude in [0, 360)
    static func meanEquatorToEcliptic(tt: Double) -> Engine.Rotation<Engine.EQM, Engine.ECM>
    static func geocentricPosition(at time: Engine.Time, cache: Cache = cache) throws -> Engine.Vector<Engine.EQJ>
    static func eclipticPosition(at time: Engine.Time, cache: Cache = cache) throws -> Engine.Spherical       // ECT, degrees, AU
    static func geocentricState(at time: Engine.Time, cache: Cache = cache) throws -> Engine.State<Engine.EQJ>
    static func barycenterState(at time: Engine.Time, cache: Cache = cache) throws -> Engine.State<Engine.EQJ>
    static func eclipticState(at time: Engine.Time, cache: Cache = cache) throws -> Engine.EclipticState
    static let earthMoonMassRatio: Double // 81.30056
    static func libration(at time: Engine.Time, cache: Cache = cache) -> Engine.Libration
    static func eclipticLongitude(at time: Engine.Time, cache: Cache = cache) throws -> Double   // degrees, true ecliptic of date
    static func distance(at time: Engine.Time, cache: Cache = cache) throws -> Double            // AU
    static let meanRadiusKilometers: Double   // 1,737.4
    static let equatorInclination: Double     // 1°32′32.7″
}
extension Engine.MoonEphemeris {
    static let start, recordDays: Double              // −36,560.5 TDB days, 4
    static let recordCount, degreeCount: Int          // 21,111, 13
    static let coefficients: [Double]
    static let fullWeightStart, fullWeightEnd, blendDays: Double   // −36,524.5, 47,846.5, 32
    static func weight(tt: Double) -> (weight: Double, rate: Double)
    static func evaluate(tdb: Double) -> (position: SIMD3<Double>, velocity: SIMD3<Double>)?   // ICRS, per TDB day
    static func state(tt: Double) -> (position: SIMD3<Double>, velocity: SIMD3<Double>)?       // EQJ, per TT day
    static func position(tt: Double) -> SIMD3<Double>?                                          // EQJ
}

extension Engine.TDB {
    static func offsetSeconds(tt: Double) -> Double
    static func rate(tt: Double) -> Double
    static func offsetSeconds(date1: Double, date2: Double, ut: Double, longitude: Double, u: Double, v: Double) -> Double
}
extension Engine.FrameBias {
    static func fukushimaWilliams(gamma: Double, phi: Double, psi: Double, epsilon: Double) -> [[Double]]
    static let icrsToEqj: Engine.Rotation<Engine.ICRS, Engine.EQJ>
}
extension Engine.Rotation {
    func apply(to vector: SIMD3<Double>) -> SIMD3<Double>   // as apply(to: Vector), for values with no time
}
extension Engine.RotationRate {
    func apply(to vector: SIMD3<Double>) -> SIMD3<Double>
    var inverse: Engine.RotationRate<To, From> { get }        // the transpose
}
```

- The native lunar model uses DE440 from 1900-01-01 through 2131-01-01 TT and the complete binary64 DE441 polynomials elsewhere in the accepted range. The 32-day transitions use the existing quintic smoothstep x³(10 − 15x + 6x²). `coordinates(tt:cache:)` caches the model's mean-ecliptic longitude, latitude and distance.
- `MoonDE440Coefficients.swift` holds DE440's Chebyshev records for the Moon minus those for Earth, both relative to the Earth-Moon barycenter, divided by the au: 21,111 four-day records of 13 coefficients per axis on ICRS axes, from 1899-11-26 to 2131-02-07 TDB. `Scripts/generate-moon-tables.py` writes it from the C engine's `moon_data.inc`, whose SHA-256 `Scripts/moon-data/manifest.json` pins, and `--check` runs in CI on macOS and Linux. `--published DIR` reads `de440s.bsp` as NAIF publishes it (URL and SHA-256 in the manifest) and checks all 823,329 coefficients against the DE440 records bit for bit. The table uses the encoding of [Compiled-in tables and the accepted range](#compiled-in-tables-and-the-accepted-range); decoded, it takes 6.6 MB for the life of the process.
- `evaluate(tdb:)` reads the records through `table`, an `Engine.ChebyshevTable` (see [Compiled-in tables and the accepted range](#compiled-in-tables-and-the-accepted-range)): record `k` holds `start + 4k ≤ tdb < start + 4(k + 1)`.
- `state(tt:)` reads the records at TDB = TT + `Engine.TDB.offsetSeconds(tt:)`, scales the velocity by `Engine.TDB.rate(tt:)`, and rotates both by `Engine.FrameBias.icrsToEqj`. `position(tt:)` is its position without the rate, which is all `evaluate(tt:)` reads.
- `Engine.TDB` is SOFA's `iauDtdb`: Fairhead and Bretagnon's 787 terms, JPL's planetary mass adjustments and the topocentric terms. `TDBTerms.swift` is generated by the same script from ERFA 2.0.1's `dtdb.c`, which the C engine already vendors and the manifest pins with its URL; that file equals ERFA's at the commit `THIRD_PARTY_NOTICES` pins. The Moon reads the geocentric offset at TT, as the C engine does. The rate is the analytic derivative of the same TT-to-TDB series.
- `Engine.FrameBias.icrsToEqj` is SOFA's `iauPmat06` at J2000: `iauFw2m` at the Fukushima-Williams angles of `iauPfw06` and `iauObl06` for t = 0, where precession is the identity. It is about 23 mas.
- DE440 positions reach the mean ecliptic of date as in the C engine: precession to the mean equator of date, then the mean obliquity. `geocentricPosition(at:)` takes the model's coordinates back through the mean obliquity and the inverse precession. `eclipticPosition(at:)` takes them through the mean obliquity, nutation and the true obliquity, and reports the model's distance. Both throw `badTime` for a TT beyond `Engine.acceptedTTDays` or not finite, and for a result that is not finite. The ecliptic longitude is in [0, 360) and 0 where the vector has no component in the ecliptic plane.
- Pluto (#88) also reads `TDB`, `FrameBias` and `weight(tt:)`. They stay in `Moon/`, beside the TDB terms the Moon's generator writes; the Chebyshev evaluator moved to `Foundation/`. `EclipticState`, with an initializer that works out the longitude and latitude rates from the state, and `Engine.tilted(by:)` and `Engine.tiltRate(by:rate:)` moved to `Foundation/EngineEclipticState.swift` when #89's ecliptic states became their second user. `tilted(by:)` repeats the arithmetic of `Engine.FrameRotation`'s private ecliptic rotation, which belongs to the closed #86. `eclipticAngles(_:)`, which repeats `Engine.Ecliptic`'s, and the SIMD and rotation-rate helpers are used only by the Moon; when another module needs them, they move to `Foundation/` (see [Changing this contract](#changing-this-contract)). The evaluator is not the planet polynomials' Clenshaw recurrence: each keeps its C original's order of operations, so the two are not interchangeable bit for bit.
- `Engine.Moon.cache` is the lunar cache of local patch 14: 32 entries of longitude, latitude and distance, keyed by the exact bits of the TT days `coordinates(tt:cache:)` reads, registered with `CacheRegistry.shared`. `0.0` and `-0.0` are different keys, and TT days that are not finite bypass it. It holds only model values, so a hit returns the caller's own time.
- `meanEclipticState(at:cache:)` reads one cached position epoch. Both DE440 and DE441 velocities are analytic polynomial derivatives, scaled from TDB to TT and carried through frame bias, precession, and mean obliquity with their rates. Each blend includes the weight's rate times the difference between the positions. The distance rate is the position/velocity dot product divided by distance. States and positions retain identical position bits.
- `geocentricState(at:cache:)` is `Astronomy_GeoMoonState`: that state through the mean obliquity and precession with their rates. Its position is the same double for double as `geocentricPosition(at:cache:)`. `barycenterState(at:cache:)` is `Astronomy_GeoEmbState`, the Moon's state divided by 1 + 81.30056, the C engine's Earth/Moon mass ratio. `eclipticState(at:cache:)` is `Astronomy_MoonEclipticState`: through the mean obliquity, nutation and the true obliquity with their rates; its longitude, latitude and distance are `eclipticPosition(at:cache:)`'s, the distance and its rate are the model's, and it throws `badVector` when the position has no component in the ecliptic plane. All three throw `badTime` as the positions do, including for a rate that is not finite.
- `libration(at:cache:)` is `Astronomy_Libration`: Meeus, Astronomical Algorithms, chapter 53, the optical libration from the model's mean ecliptic coordinates at `time.tt` / 36,525 centuries and the physical libration from the series ρ, σ and τ, with the C engine's sums in its order and its `NormalizeLongitude` and `LongitudeOffset` reductions (`Engine.normalizedLongitude(_:)`, `Engine.longitudeOffset(_:)`, declared in `Moon/` for the phase and search code of #92 to share). The longitude is in (−180, 180]. The Moon's latitude and longitude are on the mean ecliptic of date, in degrees. The distance is the model's in km with the published au, and the diameter is 2·atan(R / √(d² − R²)) with R = 1,737.4 km. Like the C function it does not check the time: a time that is not finite gives NaN in every field.
- The Moon's inputs to the phase and event searches of #92: `eclipticLongitude(at:cache:)` is the Moon's side of `Astronomy_MoonPhase`, the true-ecliptic longitude of `geocentricPosition(at:cache:)`, from which the search subtracts the Sun's; `distance(at:cache:)` is the C engine's `MoonDistance`, with the accepted-range check that `moon_distance_slope` applies; the node search reads the latitude of `eclipticPosition(at:cache:)`.
- `moon_data.inc` and `dtdb.c` stay where the C engine read them; when #97 removes the C target, it moves them to `Scripts/moon-data` and updates the manifest.

### Differences from published values

- The public Moon model uses complete binary64 DE441 outside the unchanged DE440 window and retains the existing one-arcminute and 28.689 km Horizons allowances. The retired compact representation and lunar series remain documented in historical evidence; their numerical errors are not current model bounds. See [the full-source integration method](Scripts/moon-data/de441-full-integration-method.md) for current source, transition, public-route and runtime qualification.
- `Scripts/assess-moon-de441.py` measures a direct DE441 replacement candidate from byte ranges of JPL's published 3,307,878,400-byte SPK. Covering the accepted TT range, including the 1.9 ms TDB−TT margin, takes 730,501 four-day records: 217.36 MiB as Float64 or 108.68 MiB as Float32 before source encoding. At all 30 archived Horizons dates, the fetched Float64 records agree with the independent response to 1.5e-10 km in position and 4.1e-16 km/s in velocity. Float32 coefficient rounding has a 0.000319′ angular bound on those records, and the sampled Python evaluator runs tens of thousands of position-and-rate evaluations per second on the measurement host. `Scripts/moon-data/de441-direct-evidence.json` pins every fetched byte range and records the exact workload. These 30 dates do not qualify Float32 over 730,501 records, and the Python timing is not a production benchmark. The historical compact comparison covers its complete source interval; the current binary64 foundation also includes the additional lower padding record.
- `Engine.MoonDE441Full` stores all thirteen derived binary64 coefficients per axis in individually decoded compiled records. The complete source range includes two-day private emission padding. Its [source method](Scripts/moon-data/de441-full-method.md) records exact coefficient identity, source subtraction rounding, clock/frame conventions and measured storage costs. The compact payload and decoder have been removed.
- Libration latitude is about 1.40′ above NASA SVS's on average, from Meeus's formulas, and at most 1.6692′ from it, at 2020-01-12 08:00 UT.

### Differences from the C engine

- The outer Moon uses complete binary64 DE441 with analytic rates; the C engine used its lunar series and finite-difference outer rates.
- An ecliptic longitude that rounds up to 360 when moved into range is 0; `Astronomy_EclipticGeoMoon` can return 360.
- The libration distance converts the model's distance with the published au, a difference of 6.0e-11 of it.
- `equatorInclination` is the 1°32′32.7″ Meeus prints for I in the chapter 53 model, not the C engine's 1.543°, for which Astronomy Engine cites no source. The libration latitude moves by up to 0.035′, the difference between the two.

### Published-value checks

Tests under `Tests/AstronomyKitTests/Engine/Moon/`:

- The table against DE440 coefficient for coefficient, through the generator's `--published` mode, which needs `de440s.bsp` and does not run in CI. The tests check the table's shape and dates, and that its records reach past both blends with TDB − TT at its largest.
- ERFA's `t_dtdb` within its 1e-15 s, and pyerfa 2.0.1.5's geocentric `dtdb` at eleven dates from −4,000 to +4,000 years within 1e-14 s; the rate against a five-point difference of the offset.
- ERFA's `t_fw2m`, pyerfa's `pmat06` at J2000 within 1e-16, and the IERS Conventions (2010) frame bias offsets ξ0, η0 and dα0 to their printed precision.
- Clenshaw's recurrence against the Chebyshev sums and their derivatives; every record boundary, where adjacent records meet within 1e-12 AU and 1e-12 AU per day; the ends and the inputs that are not finite; velocity against five-point differences.
- The weight: 1 and 0 where it should be, monotonic across each blend, its rate against differences, and its value and rate near each blend end.
- The `JPLValidationTests` geocentric and Asheville Moon suites retain their 1′ limits with the new public apparent Moon route. Existing simultaneous geometric Moon distance vectors continue testing the explicit geometric API. Legacy fixed-Sun-adjusted distance fields remain archived; the barycentric astrometric route now compares the original Horizons range field with the same allowance.
- Horizons geometric vectors at all 30 archived dates from 2002 BCE through 6000 CE, including eleven transition-region dates, within the unchanged 1′ and 28.689 km allowances. The thirteen legacy-series angular failures remain recorded in historical compact-model evidence; those controls were retired with the unused lunar series. Current tests retain the independent wrong-observer, wrong-date and distance controls.
- The complete DE441 evaluator is compared with 1,365 direct-source states across 273 records, including interval interiors, range ends, former worst-bound records and transition regions. Integrated states and ecliptic event inputs retain their existing acceptance limits. [Current integration evidence](Scripts/moon-data/de441-full-integration-method.md) separates sampled agreement, exhaustive source-seam checks and measured runtime costs.
- Every Horizons state in Astronomy Engine's `barystate/GeoMoon.txt` and `GeoEMB.txt` at the pinned revision, 3,196 each every 8 days from 1970 to 2040, within the relative limits its `ctest.c` applies to them: Moon position 4.086e-5 and velocity 5.347e-5, barycenter 4.076e-5 and 5.335e-5. `build-fixtures.py` copies them into `reference-fixtures.json`.
- Rates against fourth-order finite differences at the same thirteen instants in DE441, both blends and DE440: EQJ velocity within (1 + |t|) · 1e-8 of speed, and ecliptic longitude, latitude and distance rates within that fraction of 15° and 6e-4 AU per day. Near a DE441 source seam, the stencil stays within the selected source polynomial. Adjacent independently supplied polynomials have small nonzero endpoint differences; the tests do not establish global C1 or C2 continuity. Direct one-sided position and rate comparisons cover all 730,501 source seams within the existing 1e-12 AU and AU/day limits. The smooth blend weights do not remove those source seams. No numerical tolerance was loosened.
- The state's position against the position, the barycenter against the Moon scaled, and the ecliptic state against the ecliptic position, all double for double.
- Cache work counts with a private registry: one epoch per state for DE440, DE441, and blends; positions share that epoch. Tests also cover disabled caching, signed-zero keys, non-finite bypass, eviction of the oldest of 32, registry reset, caller time, and simultaneous callers.
- Libration against all 26,305 hourly rows of NASA's Scientific Visualization Studio Moon Phase and Libration tables for 2020, 2021 and 2022 (`Scripts/reference-data/sources/mooninfo_2020.txt` to `mooninfo_2022.txt`, as Astronomy Engine pins them), within the limits of its harness of 0.1304′ in longitude, 54.377 km in distance and 0.00009° in diameter, and within 1.67′ in latitude. The harness's 1.6476′ was set for upstream's lunar series; with the DE440 Moon the C engine's 1.543° already reaches 1.6507′. 1.67′ is the largest difference on the three tables, 1.6692′, rounded up: a measured bound, not a published accuracy.
- The phase input: at USNO's twelve quarter times in `reference-fixtures.json`, the Moon's longitude less the Sun's is within 1′ of the quarter, the limit Astronomy Engine's harness sets for those times. The Sun's longitude comes from `Engine.Planet.earth` as the C engine finds it, at the heliocentric origin with no aberration.
- The apsis input: the model's distance at the six published lunar apsides within their 25 km. The node input: the ecliptic latitude at Espenak's six node times within the latitude's rate times the 220.86 s time limit, and its direction matching the node's.
- Test-only event roots against all 26 existing published phase/node/apsis cases at their original time/distance allowances, including the two 1903 geometric Horizons cases. Twenty fixed windows independently discover and pair roots from native Moon states and direct DE441 coefficients, with crossing-direction and finer-bracket checks. The [bounded event qualification](Scripts/moon-data/de441-event-method.md) records each root shift and explains the shared Sun/frame/time dependencies; these sampled results do not qualify every event across the accepted range. The public API cutover and #184 position qualification are complete, while the event evidence retains its recorded limits.
- Routing between DE440, the blend and DE441; no jump at the blends' ends; longitudes across the wrap; the ecliptic position against the J2000 position seen on the true ecliptic of date; the accepted range's ends and the doubles beyond; and NaN and infinite times.

### Moon test dispositions

| Test | Disposition |
|---|---|
| `MoonCacheTests`, `Scripts/performance/test-moon-cache.sh`, `moon_cache_probe.c` and `moon_output_probe.c` | Retired by #95. `EngineMoonCacheTests` replaces the C implementation checks with native DE441/table/blend work counts, caller-time, exact-key, bypass, eviction, concurrency, and zero-capacity negative-control checks. |
| `BundledEphemerisTests` | Retired at the cutover. Its Horizons check of the lunar apsis and node searches and its Moon position/state identity moved onto the public API in `MoonStateIdentityTests`. `EngineMoonEphemerisTests`, `EngineChebyshevTests` and `EngineMoonTests` check the Swift evaluator, blend and routing, `EngineMoonStatesTests` the velocities across the blends, and `EngineMoonCacheTests` and `EnginePlutoCacheTests` concurrent first calls. The legacy Moon and Pluto values it pinned were captured C output, not published values. |
| `ReproducibilityTests` Moon cases | Retired at the cutover, as recorded under [Earth orientation](#earth-orientation). The lunar model is checked against DE440, Horizons and NASA here. |
| `EclipticStateTests` | Kept on the public API; see [Positions](#positions). `EngineMoonStatesTests` checks the Swift Moon's ecliptic state. |
| `MoonTests`, `LibrationTests` and the Moon suites of `JPLValidationTests`, `DistanceAccuracyTests` and `AuditValidationTests` | Public-API checks on the engine. `EngineMoonHorizonsTests`, `EngineMoonStatesTests` and `EngineLibrationTests` apply the published ones, at the same tolerances, to the Swift functions. `LibrationTests` and the illumination checks in `MoonTests` are named sanity checks. |

## Pluto, the gravity simulation and Chiron

In the tree: `Gravity/EngineGravity.swift`, `Gravity/EngineGravitySimulation.swift`, `Gravity/EngineChiron.swift`, `Gravity/EnginePluto.swift`, `Gravity/EnginePlutoEphemeris.swift` and the generated `Gravity/Generated/PlutoBarycenterCoefficients.swift`, `PlutoSunCoefficients.swift`, `PlutoCenterCoefficients.swift`, `PlutoStateTable.swift` and `Chiron/ChironCoefficients.swift`. They port the C engine's `CalcPluto`, the integrator step it shares with the gravity simulation, and the simulation (`Astronomy_GravSimInit`, `Astronomy_GravSimUpdate`, `Astronomy_GravSimSwap`, `Astronomy_GravSimBodyState`, `Astronomy_GravSimTime`, `Astronomy_GravSimNumBodies` and `Astronomy_GravSimFree`). `EngineChiron.swift` gives Chiron's heliocentric state from a Chebyshev table fitted to JPL Horizons (#253); `Positions/EngineChironPositions.swift` composes the apparent positions the public `Chiron` API reports (see [Positions](#positions)).

```swift
extension Engine.Gravity {
    static let sunGM, mercuryGM, venusGM, earthGM, marsGM, jupiterGM, saturnGM, uranusGM, neptuneGM: Double   // AU³/day², DE405
    static let seriesCache: Engine.VSOP87B.Cache   // no capacity
    struct BodyState { var position, velocity: SIMD3<Double> }
    struct MajorBodies {               // sun, jupiter, saturn, uranus, neptune, barycentric
        init(tt: Double) throws
        func acceleration(at position: SIMD3<Double>) -> SIMD3<Double>
    }
    struct SolarSystem {               // sun and planets[Engine.Planet.rawValue], barycentric
        static let planetGM: [Double]  // Earth's includes the Moon's
        init(tt: Double) throws
        func state(of body: CelestialBody) -> BodyState?
        func acceleration(at position: SIMD3<Double>) -> SIMD3<Double>
    }
    static func pull(of gm: Double, at body: SIMD3<Double>, on position: SIMD3<Double>) -> SIMD3<Double>
    struct Step { var tt: Double; var position, velocity, acceleration: SIMD3<Double> }
    static func start(heliocentric position: SIMD3<Double>, velocity: SIMD3<Double>, tt: Double) throws -> (step: Step, bodies: MajorBodies)
    static func start(_ state: Engine.Pluto.TableState) throws -> (step: Step, bodies: MajorBodies)
    static func advance(_ step: Step, to tt: Double) throws -> (step: Step, bodies: MajorBodies)
    static func advance(_ step: Step, to tt: Double, bodies: MajorBodies) -> Step
    static func advance(_ step: Step, to tt: Double, acceleration: (SIMD3<Double>) -> SIMD3<Double>) -> Step
}
extension Engine {
    final class GravitySimulation {
        init(origin: CelestialBody, time: Engine.Time, states: [Engine.State<Engine.EQJ>]) throws
        let origin: CelestialBody
        let bodyCount: Int
        var time: Engine.Time { get }
        func update(to time: Engine.Time) throws -> [Engine.State<Engine.EQJ>]
        func state(of body: CelestialBody) throws -> Engine.State<Engine.EQJ>
        func swap()
    }
}
extension Engine.Chiron {
    static let table: Engine.ChebyshevTable   // km on ICRF axes against TDB, 2,403 records of 38 days
    static let earliestUT, latestTT: Double
    static func checkSupported(_ time: Engine.Time) throws -> DeltaTModel
    static func heliocentricState(at time: Engine.Time) throws -> Engine.State<Engine.EQJ>
    static func heliocentricState(forLightTimeAt time: Engine.Time, observedAt observation: Engine.Time) throws -> Engine.State<Engine.EQJ>
}
extension Engine.PlutoEphemeris {
    static let barycenter, barycenterFromSun, center: Engine.ChebyshevTable
    static func heliocentricState(tt: Double) -> (position: SIMD3<Double>, velocity: SIMD3<Double>)?
}
extension Engine.Pluto {
    typealias Cache = Engine.BoundedCache<Int, Segment>
    static let cache: Cache
    static let stateTable: [TableState]           // 51 states, TT −730,000 to +730,000
    static func heliocentricState(at time: Engine.Time, cache: Cache = cache) throws -> Engine.State<Engine.EQJ>
    static func barycentricState(at time: Engine.Time, cache: Cache = cache) throws -> Engine.State<Engine.EQJ>
    static func heliocentricPosition(at time: Engine.Time, cache: Cache = cache) throws -> Engine.Vector<Engine.EQJ>
    static func modelState(tt: Double, heliocentric: Bool, cache: Cache = cache) throws -> (position: SIMD3<Double>, velocity: SIMD3<Double>)
}
```

- `Engine.Gravity` is the C engine's integrator for a body of negligible mass. `MajorBodies(tt:)` is `MajorBodyBary`: Jupiter to Neptune from `Engine.Planet.heliocentricState`, the barycenter offset from the Sun by Σ GM/(GM + GM☉) times each planet's position and velocity, summed from Jupiter to Neptune, and the Sun at minus that offset. `acceleration(at:)` is `SmallBodyAcceleration`: GM·d/|d|³ from the Sun to Neptune. `start` is `GravFromState`, and `advance` is `GravSim`, given the major bodies at the new time or finding them: a trial position under the old acceleration, then the position and velocity under the mean of the old acceleration and the one at the trial position. A step's error is third order in its length. The GM values are DE405's (Standish 1998, JPL IOM 312.F-98-048): the Sun's is k² with the Gaussian constant, and each planet's is the Sun's over DE405's mass ratio. They stay in `Gravity/` until a second module needs them. Both `MajorBodies` and `SolarSystem` read the planets through `seriesCache`, which stores nothing: a step's planets are at a new TT almost every time, and storing them would only push other callers' entries out of the shared VSOP87B cache. The C engine reads them through its thread-local cache.
- `SolarSystem(tt:)` is `CalcSolarSystem`: the same construction with all eight planets, Mercury first, and Earth pulling with Earth's GM plus the Moon's, Earth's over `Engine.Moon.earthMoonMassRatio`. Its `acceleration(at:)` is `CalcBodyAccelerations`, from the Sun outward. `state(of:)` gives the Sun, a planet, or zero for the barycenter, and `nil` for any other body.
- `Engine.GravitySimulation` holds two moments, current and previous, each a time, a `SolarSystem` and the small bodies' `Step`s. The initializer checks, in the C engine's order: an origin outside Mercury through the barycenter in `CelestialBody`'s numbering (`invalidBody`), the time against `Engine.acceptedTTDays` (`badTime`), each state's TT against the time's, compared exactly (`inconsistentTimes`), and then whether the solar system models the origin: Pluto, the Moon and the Earth-Moon barycenter pass the first check and throw `invalidBody` here. States are moved from the origin to the barycenter, and both moments start equal. `update(to:)` checks the time first, as the C engine does, and stores nothing until the new moment is complete, so a rejected update changes nothing. At the current TT it integrates nothing: the previous moment becomes a copy of the current one, which keeps its own time, as `GravSimDuplicate` does. Otherwise the current moment becomes the previous one and each body takes one `advance` step under the new `SolarSystem`. It returns the bodies relative to the origin, with the caller's time. `state(of:)` gives the Sun or a planet relative to the origin at the current moment's time, and throws `invalidBody` for anything else, the barycenter included, as `Astronomy_GravSimBodyState` does. `swap()` exchanges the moments. The object owns its storage; there is no free call. Like the C engine, an update that produces a non-finite state does not throw.
- One `NSLock` guards the moments. An update reads them under the lock, computes outside it, and stores its result only if no swap or other update came in between; otherwise it starts again from the newer moments. So concurrent calls take effect one at a time, no lock is held while the planets are computed, and an update that throws stores nothing. In a one-off comparison during development, with a harness that was not committed, 302 updates of two bodies (including a swap and a repeated time) from four origins gave the C simulation's results bit for bit; no test checks this.
- `Engine.PlutoEphemeris` holds the complete three-table DE440/PLU060 physical-center model over TDB [−73047.5, +73046.5), 1800-01-02 through 2199-12-30. It adds the Pluto barycenter, negated Sun, and center offset on ICRF axes after km-to-AU conversion, reads at TDB, scales rates by dTDB/dTT, and applies the existing EQJ frame bias. Source guards use SPK summary coverage rather than polynomial padding. The [complete-source qualification](Scripts/pluto-data/PLU060-QUALIFICATION.md) records source provenance, enclosure derivation, independent samples, and limits.
- `Scripts/generate-pluto-tables.py --kernel PATH` verifies the whole PLU060 digest and generates all 62,395 records, with 21,768,120 decoded bytes. `--check` validates the embedded payloads against `plu060-evidence.json`; adding `--kernel PATH` replays every coefficient from the publisher kernel. The legacy C tables and state-table manifest remain intact. `--published DIR` still verifies those legacy sources separately.
- `Engine.Pluto` returns the physical-center state at full weight from TDB −73015.5 through +73014.5. Its own 32-TDB-day quintic tapers lie inside PLU060 coverage; their weights and analytic derivatives are independent of the Moon. Outside coverage it returns the DE441 system barycenter. The complete blend direction bounds are below 0.005945′ against the source center, within the 1′ gate. The barycentric API continues to add the Sun from `Gravity.MajorBodies`. Public and native Pluto position/state entry points accept TT ±1,461,000 days without populating the legacy segment cache.
- The diagnostic `modelState` integrated model remains Astronomy Engine's: 51 heliocentric EQJ states every 29,200 days from TT −730,000 to +730,000 (0001 to 3998), which #119 traced to TOP2013. `modelState` is `CalcPlutoLegacy` with the exact velocity. Segment `k` runs from state `k` to state `k + 1` in 200 steps of 146 days: integrated forward from the first, backward from the last, and mixed so step `i` takes `i`/200 of the backward result, in position, velocity and acceleration. The backward pass reuses the major bodies the forward pass found at the same times. At a time inside the table, the two steps either side are carried to it under the mean of their accelerations and mixed by the fraction of the step elapsed; the velocity is the same mix plus the mix's rate, so it is the derivative of the position within a step. Across a step seam the velocity moves by about 6e-12 AU per day. Indices are `floor` held to the valid range, as `ClampIndex` holds them. A tabulated state's position comes back exactly at its time.
- In the diagnostic integrated model, beyond the table, up to 36,525 days (`crawlLimitDays`) before the first state or after the last, `crawl` integrates from that state to the time in steps of 146 days, the last one shortened to land on it, without the cache: `CalcPlutoOneWay`, at most 251 steps. Further out, and for a TT that is not finite, the functions throw `badTime`, as the C engine's crawl guard does. They also throw `badTime` for a result that is not finite. The diagnostic model's range is narrower than `Engine.acceptedTTDays`, so the functions do not check that; the public Pluto path does not use it and accepts the full range.
- `Engine.Pluto.cache` holds the 50 segments, keyed by index and registered with `CacheRegistry.shared`. A segment is a pure function of its index, so a reset at any moment leaves results unchanged. Unlike the C engine, which integrates a segment while holding its mutex, the `BoundedCache` integrates outside its lock, so two threads that miss the same segment both integrate it and the first result stays. A segment outside 1900 to 2100, where the planets come from their full series, took about 5 s in a Debug build on the development machine; segments 24 and 25 (1920 to 2080) take a fraction of a second, so the cache tests use them.
- The [DE441 feasibility assessment](Scripts/pluto-data/DE441-ASSESSMENT.md) for #252 scans all 91,314 Pluto and 182,627 Sun records across TT ±1,461,000 days, with one day of lower light-time padding and the TT/TDB margin. `Engine.PlutoDE441` embeds its 12.54 MiB Float64 shared-node cubic, whose conservative heliocentric barycenter representation bounds are 0.235244 km and 0.134384 km/TDB day. It decodes both bodies on ICRF axes, subtracts Sun from Pluto, applies the TT/TDB rate, and rotates into EQJ. `generate-pluto-de441.py` owns only `Gravity/Generated/DE441`, separate from the legacy generator's direct outputs. The [native integration evidence](Scripts/pluto-data/de441-native-method.md) records checks and resource measurements. PLU060 center-offset evidence covers only 1800–2199; full-range physical-center position and velocity remain unqualified. The complete available PLU060 physical-center expansion is qualified separately.

- The [native observer qualification](Scripts/pluto-data/OBSERVER-QUALIFICATION.md) covers 41 archived Horizons geocentric observations: fourteen outer DE441 barycenter epochs and twenty-seven PLU060 center epochs, including both expanded blends. Astrometric ICRF, apparent ICRF, and apparent equator-of-date directions all pass the unchanged 1′ target; their sampled debug maxima are 0.00136125′, 0.00136110′, and 0.24345641′. Native light-time composition accepts the exact TT ±1461000-day observation endpoints: it validates the observation first, preserves its Delta T model, and permits an earlier internal Pluto state only inside the compiled Pluto and Sun tables' joint TDB coverage [−1461016.5, +1461015.5). The shared apparent-place model now supplies a two-TT-day internal emission margin for every supported target while holding Earth at reception; public Earth queries remain range-checked. Sun-dependent angles accept the same reception endpoints. The public facade now uses this engine. Its heliocentric position and state are gated on all 29 archived target-999 center/blend epochs and 15 target-9 outer epochs under their existing limits. These sampled results do not establish continuous full-range physical-center accuracy, velocity accuracy, or event timing.

- `Engine.Chiron` reads `Chiron.table`, which `Scripts/generate-chiron-table.py` fits to JPL Horizons' geometric heliocentric ICRF vectors of 2060 Chiron (solution JPL#171, center 500@10, the Sun from DE441). The pinned Horizons queries and responses, the fit and the heldout screen are in `Scripts/chiron-data/`. The table holds 2,403 records of 38 TDB days from JD 2415019.5 (1899-12-31 00:00 TDB) to JD 2506333.5 (2150-01-03), each a degree-15 Chebyshev series per axis, least-squares fitted to 38 daily Horizons vectors inside the record. That is 115,344 doubles, 922,752 bytes decoded, compiled in as a 1.24 MB base64 literal through `Engine.unpackDoubles`. A state converts TT to TDB with `Engine.TDB.offsetAndRate`, reads the one record that holds the TDB through `Engine.ChebyshevTable`, divides kilometres by `Engine.kilometersPerAU`, scales the analytic velocity by dTDB/dTT and rotates ICRF to EQJ with `Engine.FrameBias.icrsToEqj`, so each call costs the same anywhere in the span. Record `k` holds [start + 38k, start + 38(k + 1)); the table's last instant lies two days past the span, so no supported time reaches it. The span is checked on TT alone, since the state depends on nothing else: from 1900-01-01 00:00 UT, as TT with the time's Delta T model, through 2150-01-01 00:00 UTC, which is TT 54,786.5 days plus 69.184 s. The time's UT is not checked, so a pair rebuilt from recorded scales that disagree with its model is judged by its TT. Espenak-Meeus Delta T drops from −2.7016 s to −2.79 s at 1900.0, where its 1860–1900 and 1900–1920 polynomials meet, and both models use those pieces there; so a UT up to 88.4 ms before 1900-01-01 00:00 has a TT after the start's and is accepted. Outside the span, or for an invalid time, the functions throw `badTime`. `heliocentricState(forLightTimeAt:observedAt:)` checks the observation against the span instead and accepts an evaluation up to the observation, with the same Delta T model, back to the table's start a day before the span's: Chiron's light time is under three hours. The table needs no cache or lock.

### Differences from published values

- The legacy integrated model remains up to 5.1′ from DE441 at the ends of its table, and 2.2′ to 2.9′ at the ends of its extrapolation (#190); the public C path used it. The public API now uses DE441 there. Native DE441 meets the existing angular target at all archived barycenter dates, but full-range physical-center accuracy remains unqualified.
- Chiron is within 0.13 km and 0.00021 km per TDB day of the 14,419 Horizons epochs held out of the fit: both ends, every seam and five interior points of every record. That is 16,821 comparisons, since each of the 2,402 interior seams is checked against the records on both sides (`Scripts/chiron-data/report.json`). Horizons' small-body integration depends slightly on the query: Horizons vectors requested as time lists differ from the table by up to 2.3 km, and an offset 38-day series kept as a negative control by 7.1 km. The stated bound is 10 km; the generator fails if any of the 108,136 archived epochs (91,314 training, 14,419 heldout and 2,403 offset) is farther from the table. The archive's second copy of each training epoch, from the aligned half-day queries, is within 0.124 km of the first. These figures measure agreement with Horizons' solution JPL#171, not the physical accuracy of that orbit.

### Differences from the C engine

- Chiron has no C counterpart. Before #253 it stepped the gravity simulation from five Horizons states; the public `Chiron` API now reads `Engine.Chiron` as well, so the earlier differences between the two (anchor times, frame and the anchor chosen near midpoints) are gone.
- The operations follow the C engine's, in its order, but the results are not all the same bits. At Pluto's 44 Horizons epochs below, the heliocentric and barycentric positions are within 2e-15 AU of the C engine's and the velocities within 5e-19 AU per day; 59 of the 88 states match to the bit, and the other 29 differ in the last bits.
- The simulation and Pluto's model read the planets through no cache (see above), and concurrent updates are linearized without holding a lock during the computation. Neither changes a result.

### Published-value checks

Tests under `Tests/AstronomyKitTests/Engine/Gravity/`:

- The tables against `plu060.bsp` coefficient for coefficient, through the generator's `--published` mode, which needs the kernel and does not run in CI. The tests check each table's shape and dates, that the records cover both blends with TDB − TT at its largest, Clenshaw's recurrence against the Chebyshev sums and their derivatives, and that adjacent records meet within 1e-13 AU and 1e-15 AU per day.
- The GM values against k² and DE405's mass ratios, Earth's with the Moon's against DE405's Earth-Moon ratio; the accelerations against Newton's law; the third-order local error of a step; the major bodies and the solar system against the planet functions.
- The simulation against Horizons states of the Pluto system barycenter on 1990, 2000, 2001 and 2010-01-01 (`Scripts/reference-data/sources/horizons/pluto-barycenter-decade.json`): from the 2000 state, one-day steps forward and backward land within 10,000 km, 0.5″ and 5e-6 of the speed (measured: 2,700 km, 0.12″ and 1.5e-6 after ten years; 4- and 16-day steps land as close, so the gap is the force model's).
- Chiron: the table's shape and its margin of a day before the span and two after; adjacent records within 0.2 km and 0.001 km per day of each other (measured 0.136 km and 0.000217 km per day); the 22 Horizons vectors of `chiron-anchor-vector.json` and `chiron-vector.json`, from 1900-01-01 to 2150-01-01, within 5 km and 0.01 km per day (measured 2.3 km and 0.0011 km per day, in 2100); the velocity against five-point differences of the position on 1/64-day stencils within 1e-11 AU per day; the span's ends on TT, including pairs whose UT disagrees with their TT and the UTs just before 1900 that the Delta T drop admits; the light-time evaluation's guards, before the span's start and before the table's; the caller's time and model; and calls on separate threads giving the serial results. `Scripts/generate-chiron-table.py --check`, which the PR gate runs, refits the table from the pinned Horizons responses, repeats the heldout screen and compares the generated Swift source and report byte for byte.
- The simulation's behavior: both moments at the start, no bodies, unsupported origins and the order of errors, bodies independent of each other, origins that only shift the states, the gap after stepping out and back shrinking as the cube of the step (an eighth for half the step), a repeated TT, the caller's time and model, swaps after an update and before any, the light-time pattern of trial and swap, rejected updates leaving every bit of both moments unchanged, the bodies' states relative to the origin, and simultaneous updates to one time stepping once with the serial result.
- The `JPLValidationTests` geocentric (1′) and Asheville (1.5′) Pluto suites as astrometric directions through `Engine.Positions.geocentricPosition` and `Engine.Observers`; the `pluto-observer` rows of 1900, 2000 and 2100 in J2000 and true ecliptic of date coordinates within 1.5′; and the 268 Pluto records of `distance-fixtures.json` within their allowances.
- All 29 archived Horizons physical-center vectors from 1840 to 2159 now lie at full source weight and pass the existing 1 km and 1e-8 relative-rate limits. Nineteen new geometric vectors cover the expanded center span and both transitions; 282 independent SPK states also cover the final source-edge day unavailable from Horizons. The complete blend intervals have separate conservative source/model bounds.
- Horizons vectors of the Pluto system barycenter at 15 dates from 100 BCE to 4098 CE (`pluto-barycenter-vector.json`), where Horizons has no Pluto center: the first and last tabulated states with a day either side, a segment seam in 800 and a step seam in 840, and both ends of the extrapolation. All 15 pass the original 1′ check through the public heliocentric position and state routes. Target 9 evidence does not qualify target 999 outside the center archive; The complete available physical-center coverage and engine-range extension are recorded in the #252 qualification.
- Velocities against five-point differences of the positions: 1/256-day stencils through both blends and the DE440 records within 2e-9 AU per day, the C engine's test, and 1/64-day stencils inside the model's steps within 2e-12.
- Routing, blend arithmetic and continuity at the blend ends, segment and step seams, the step past the last state, both crawl limits, NaN and infinite times.
- Cache work counts with private registries: one integration per segment, reuse within it, no lookups in the DE440 span or the extrapolation, eviction, a registry reset, a cache with no capacity, and simultaneous callers, with resets in progress, getting the serial bits and staying within 1′ of the Horizons vectors in segments 24 and 25.

### Pluto, simulation and Chiron test dispositions

| Test | Disposition |
|---|---|
| `BundledEphemerisTests` Pluto cases | Retired at the cutover. `EnginePlutoEphemerisTests` and `EnginePlutoTests` check the Swift evaluator, weight routing and velocities, and `EnginePlutoCacheTests` concurrent calls. The pinned legacy values were C output, not published values; the Horizons vectors above are the evidence. |
| `ReproducibilityTests` Pluto rows | Retired at the cutover, as recorded under [Earth orientation](#earth-orientation). The Pluto model is checked against Horizons here. |
| `PlutoRangeTests`, `PlutoThreadSafetyTests` | Public-API checks on the engine: the ±1,461,000-day endpoints, rejection just outside them, and the NaN guard, and concurrent calls with `AstronomyConfig.reset()` against seven longitudes the file attributes to the Swiss Ephemeris. `EnginePlutoTests` and `EnginePlutoCacheTests` check the same properties of the Swift functions against Horizons. |
| `ChironTests` "Reference anchors remain exact" and the simulation-reuse cases | Retired with the anchors and the simulation (#253). `ChironTests` "JPL Horizons" checks the public heliocentric position against the 19 `chiron-anchor` Horizons vectors within 5 km. |
| `ChironTests` (other cases) | Public-API checks on the engine: span, continuity, named sanity bounds. `EngineChironTests` checks the engine against Horizons. |
| `ReproducibilityTests` Chiron row | The frozen C distance was replaced by exact repeatability across calls and resets in the geometric-body link. |
| `AuditValidationTests.chironPosition` | A published-value sanity check of the public API (0.01 AU), on the engine. `EngineChironTests` checks the same rows within 5 km. |
| `GravitySimulationTests` | Public-API checks on the engine since the geometric-body link: construction, updates, swaps and errors, with named sanity bounds, not published values. `EngineGravitySimulationTests` checks the Swift simulation against Horizons. |
| The Pluto suites of `JPLValidationTests`, `DistanceAccuracyTests` and `AuditValidationTests` | Published-value checks of the public API on the engine. `EnginePlutoHorizonsTests` applies the same references and allowances to the Swift functions, reading the geocentric vector from `Engine.Positions.geocentricPosition` (see [Positions](#positions)). |

## Positions

In the tree: `Positions/EngineHeliocentric.swift`, `Positions/EngineGeocentric.swift`, `Positions/EngineEcliptic.swift`, `Positions/EngineEquatorial.swift`, `Positions/EngineIllumination.swift` and `Positions/EngineChironPositions.swift`. They port every C entry point listed for #89 under [C entry points by owner](#c-entry-points-by-owner), compose the horizontal coordinates the public `horizon(at:from:refraction:)` reports, and compose Chiron's positions as the public `Chiron` API does. `Engine.EclipticState` and the obliquity rotation and its rate moved from `Moon/` to `Foundation/EngineEclipticState.swift` when this module became their second user.

```swift
extension Engine.Positions {
    static func heliocentricPosition(of body: CelestialBody, at time: Engine.Time) throws -> Engine.Vector<Engine.EQJ>
    static func heliocentricState(of body: CelestialBody, at time: Engine.Time) throws -> Engine.State<Engine.EQJ>
    static func heliocentricDistance(of body: CelestialBody, at time: Engine.Time) throws -> Double
    static func barycentricState(of body: CelestialBody, at time: Engine.Time) throws -> Engine.State<Engine.EQJ>
    static func backdatedPosition(
        of target: CelestialBody, seenFrom observer: CelestialBody, at time: Engine.Time, aberration: Aberration
    ) throws -> Engine.Vector<Engine.EQJ>
    static func geocentricPosition(of body: CelestialBody, at time: Engine.Time, aberration: Aberration) throws -> Engine.Vector<Engine.EQJ>
    static func geocentricState(of body: CelestialBody, at time: Engine.Time, aberration: Aberration) throws -> Engine.State<Engine.EQJ>
    static func geocentricEclipticState(of body: CelestialBody, at time: Engine.Time, aberration: Aberration) throws -> Engine.EclipticState
    static func sunPosition(at time: Engine.Time) throws -> Engine.Ecliptic
    static func sunEclipticState(at time: Engine.Time) throws -> Engine.EclipticState
    static func eclipticLongitude(of body: CelestialBody, at time: Engine.Time) throws -> Double
    static func equatorial(
        of body: CelestialBody, at time: Engine.Time, from observer: Observer, equatorDate: EquatorDate, aberration: Aberration
    ) throws -> Engine.Equatorial
    static func horizontal(of body: CelestialBody, at time: Engine.Time, from observer: Observer, refraction: Refraction) throws -> Engine.Horizontal
    static func illumination(of body: CelestialBody, at time: Engine.Time) throws -> Engine.Illumination
    static func angleFromSun(of body: CelestialBody, at time: Engine.Time) throws -> Double
    static func pairLongitude(_ first: CelestialBody, _ second: CelestialBody, at time: Engine.Time) throws -> Double
    static func elongation(of body: CelestialBody, at time: Engine.Time) throws -> Engine.Elongation
    static func chironGeocentricPosition(at time: Engine.Time) throws -> Engine.Vector<Engine.EQJ>
    static func chironGeocentricState(at time: Engine.Time) throws -> Engine.State<Engine.EQJ>
    static func chironEquatorial(at time: Engine.Time) throws -> Engine.Equatorial
    static func chironEcliptic(at time: Engine.Time) throws -> Engine.Ecliptic
    static func chironHorizontal(at time: Engine.Time, from observer: Observer, refraction: Refraction) throws -> Engine.Horizontal
}
extension Engine {
    struct Illumination { var time: Time; var magnitude, phaseAngle, phaseFraction, heliocentricDistance, ringTilt: Double }
    struct Elongation { var time: Time; var visibility: Visibility; var elongation, eclipticSeparation: Double }
}
```

- The bodies are the Sun, Mercury to Neptune, Pluto, the Moon, the Earth-Moon barycenter and the solar system barycenter. Every function checks the time against `Engine.acceptedTTDays` first and throws `badTime`, then throws `invalidBody` for any other body, as the C functions do in that order. Each also throws `badTime` for a result that is not finite. Results carry the time they were given, except a backdated position, which carries the backdated time.
- Heliocentric positions come from each body's model: `Engine.Planet` for the planets, `Engine.Pluto` for Pluto, the Moon's geocentric position plus Earth's, and Earth's position plus the Moon's over 1 + `Engine.Moon.earthMoonMassRatio` for the Earth-Moon barycenter. The solar system barycenter is offset from the Sun by Σ GM/(GM + GM☉) times the positions of Jupiter to Neptune, the C engine's `CalcSolarSystemBarycenter`, with the masses of `Engine.Gravity`. A heliocentric state is composed the same way from the models' states, so its position is the same double as the position; the solar system barycenter's state is the Sun's from `Engine.Gravity.MajorBodies`, negated. The distance is `Engine.Planet.heliocentricDistance` for a planet, 0 for the Sun, and the position's length otherwise.
- Barycentric states are relative to the barycenter of `MajorBodies`: the Sun and Jupiter to Neptune are its states, Mercury to Mars the Sun's plus the planet's, the Moon and the Earth-Moon barycenter their geocentric states plus the sum of the Sun's and Earth's, in the C engine's order of additions, and Pluto `Engine.Pluto.barycentricState`.
- `backdatedPosition` uses a common compiled-DE441 solar barycentric origin and solves elapsed-TDB light time with the observer held at reception. `.none` returns astrometric displacement. `.corrected` adds finite-source solar deflection and relativistic observer aberration, preserving astrometric range. Emission-time metadata is reconstructed with the input Delta T model; the solve itself does not evaluate Delta T at emission. The Sun-center observer is singular in corrected mode and throws `badVector`; the same supported target/observer returns zero.
- `geocentricPosition` is zero for Earth; every other supported body, including the Moon, follows the shared astrometric/apparent chain at the observation epoch. Explicit `Engine.Moon.geocentricPosition` remains geometric. Every reception is checked against TT ±1461000 days. Internal emission evaluation has a two-TT-day lower margin and checks actual table coverage; public geometric Earth and other reception guards remain unchanged.
- `equatorial` includes the ellipsoid site in the barycentric reception observer before solving light time. Corrected mode uses the full analytic site velocity for diurnal aberration. It then rotates to the requested J2000 or true-of-date frame. `horizontal` uses that apparent topocentric direction and applies the selected refraction. The zero Earth-center direction throws `badVector`.
- `sunPosition` is the shared apparent geocentric Sun on the observation-date true ecliptic. `eclipticLongitude` remains the geometric heliocentric longitude of date and rejects the Sun before checking time.
- `geocentricState` covers Sun, Moon, Mercury to Neptune except Earth, and Pluto. Its position is bit-identical to `geocentricPosition`. Its velocity differentiates the implicit elapsed-TDB equation and both angular maps. If β is velocity per TDB day divided by c, emission TT rate is `(TDBprimeReception/TDBprimeEmission)*(1+n·βobserver)/(1+n·βtarget)`; the displacement rate then subtracts observer velocity. All returned rates are per reception TT day with Delta T held fixed. Coordinate-speed guards use the appropriate reception/emission TDB clocks.
- `geocentricEclipticState` and `sunEclipticState` use the same apparent or astrometric position on the observation-date ecliptic, bit for bit. Rates include all frame-rotation derivatives. A vector with no component in the ecliptic plane throws `badVector`.
- `illumination` is `Astronomy_Illumination`: geometric vectors at the observation time, with no light time, Earth's from `Engine.Planet` and the Moon's from `Engine.Moon.geocentricPosition`; the phase angle between the lines from the body to Earth and to the Sun; the phase fraction (1 + cos phase) / 2; and the C engine's magnitude models: the Sun's absolute magnitude −0.17 at one parsec (648,000/π au), Hilton's (2005, AJ 129, 2902) for Mercury and Venus, polynomials in the phase angle for Mars, Jupiter, Uranus, Neptune and Pluto, the Moon's phase curve scaled from its mean distance of 385,000.6 km, and Paul Schlyter's for Saturn with its rings. Saturn's ring tilt is the latitude of the line of sight above a ring plane inclined 28.06° to the ecliptic with its node at 169.51° + 3.82e-5° per day, positive when Earth is south of the rings, the C engine's sign. Earth throws `earthNotAllowed` before anything else, and a body no magnitude model covers, the barycenters included, `invalidBody`.
- `angleFromSun` is the angle between the Sun's and the body's `geocentricPosition` with aberration (`Astronomy_AngleFromSun`). `pairLongitude` is the difference of the two bodies' ecliptic longitudes of date from `geocentricPosition` without aberration, in [0, 360) (`Astronomy_PairLongitude`). `elongation` (`Astronomy_Elongation`) takes the side and the ecliptic separation from the pair longitude with the Sun, morning beyond 180°, and the elongation from `angleFromSun`. Earth throws `earthNotAllowed`.
- The Chiron functions compose `Engine.Chiron` for the public `Chiron` API, which calls them. `chironGeocentricPosition` corrects for light time with `Engine.Chiron.heliocentricState(forLightTimeAt:observedAt:)`, keeps Earth at the observation time, applies no aberration and reports the backdated time. `chironEquatorial` and `chironEcliptic` are its J2000 equatorial coordinates and its ecliptic of the backdated time. `chironGeocentricState` is Chiron's heliocentric state less Earth's at the same time, with no light time. `chironHorizontal` rotates the light-time position to the true equator of the observation time, with no parallax or aberration, and goes through `Engine.Horizontal`.
- The start of Chiron's span (#197): the observation is checked against the span, and the light-time evaluations may precede its start, which the table covers: at 1900-01-01 01:00 UT light left Chiron 1.56 hours earlier, before 00:00 UT.
- User-defined stars, which the C functions also take, stay with #91: the engine passes star definitions by value, and `CelestialBody` has no star cases.

### Differences from the C engine

- The light time uses the published light-day (see [Constants](#constants)), which moves a backdated time by 6.0e-11 of the light time.
- The ecliptic and equatorial outputs rotate with `Engine.FrameRotation`'s IAU 2006/2000A matrices and apparent sidereal time with the complementary terms (see [Earth orientation](#earth-orientation)), not the C engine's, so their positions are not the C engine's bits; the identities above are between the engine's own functions.
- The Moon's mean distance is converted with the published au, not the C engine's `KM_PER_AU` (see [Constants](#constants)), and Saturn's ring tilt reads `Engine.Ecliptic`.
- Pluto's states carry `Engine.Pluto`'s exact velocity everywhere. `Astronomy_HelioState` and `Astronomy_BaryState` leave out the rate of the integrated model's mix between steps; at 92 times from 1890 to 1899 the two velocities differ by at most 6e-20 AU per day.

### Published-value checks

Tests under `Tests/AstronomyKitTests/Engine/Positions/`:

- Barycentric states of the Sun, Mercury to Neptune, Pluto, the Moon and the Earth-Moon barycenter against JPL Horizons (DE441, `Scripts/reference-data/sources/horizons/*-barycentric-vector.json`), within the limits of Astronomy Engine's `BaryStateTest` in `ctest.c`. Upstream set the Pluto limit against `barystate/Pluto.txt`, the Pluto system barycenter (Horizons 9); the fixture here is Pluto's center (999), which is about 2,100 km from it, under 1e-6 of the limit. 84 states inside the span each limit was set on, every 25 years from 1900 to 2099 for the Sun, the outer planets and Pluto, every 10 years from 1980 to 2020 for Mercury to Mars, and at 5 dates from 1970 to 2040 for the Moon and the barycenter. The largest is Jupiter's velocity, at 0.63 of its limit; positions reach at most 0.57 (the Sun's, absolute). The checks fail for the heliocentric Sun, the barycenter given as the Moon, and a day's error.
- All 2,546 records of `distance-fixtures.json`, in all 19 body and mode series, within their allowances: the heliocentric distance, and the length of the geocentric position with no aberration. The checks fail for the heliocentric distance against a geocentric record, the corrected position and a day's error.
- The `JPLValidationTests` geocentric and Asheville Moon suites retain their 1′ limits with the new public apparent Moon route. Existing simultaneous geometric Moon distance vectors continue testing the explicit geometric API. Legacy fixed-Sun-adjusted distance fields remain archived; the barycentric astrometric route now compares the original Horizons range field with the same allowance.
- The Sun annual-aberration scale is checked against the Bradley leading term and IAU aberration constant. Pinned ERFA cases check each relativistic angular map. Sixty archived Horizons rows separately qualify astrometric-to-apparent correction differences to 0.0002 arcsecond and apparent directions to 0.25 arcsecond, except Uranus/Neptune at 2 arcseconds because their selected astrometric source trajectories exceed 0.25 arcsecond. These are sampled limits, not full-range physical-accuracy bounds.
- The 19 `JPLValidationTests` geocentric and Asheville suites through `equatorial`, J2000 with aberration as the public `equatorial(at:from:equatorDate:)` calls it, at their tolerances: 1′, and 1.5′ for Asheville Neptune and Pluto.
- The twelve archived Horizons observer rows retain their existing direction, angular-rate, range and range-rate limits. The public chain now includes Moon aberration and barycentric elapsed-TDB light time. Angular rates differentiate the same corrected position; old first-order approximation explanations no longer define these unchanged regression limits.
- Azimuth and elevation of the Sun, the Moon and Mars from the Asheville site every three hours on 2026-01-02 and 2026-07-02 against Horizons (`sources/horizons/*-asheville-airless.json` and `*-asheville-refracted.json`, 96 rows), through `horizontal` with no refraction for the airless rows and `.jplHorizons` for the refracted ones, within 1′, above and below the horizon. Horizons' UTC is taken as UT1, which it stays within 0.9 s of. Measured, the largest angle is 5.6″, for the Moon. The checks fail with no refraction near the horizon, with `.normal` below it, and a minute off.
- Magnitudes of the Sun, the Moon, Mercury, Venus, Mars, Jupiter, Uranus, Neptune and Pluto against Horizons every two days from 2010 to 2030 (`Scripts/reference-data/sources/magnitude_*.txt`, as Astronomy Engine pins them; 32,706 rows), within the 0.012 its `MagnitudeTest` allows (measured 0.011, Mercury). The same rows give the phase angle and the distance from the Sun, which Horizons takes with the body where it was when light left it: each row allows the change the body's motion over the light time can make, plus Horizons' aberration of the line to Earth for the phase angle and the `DistanceAccuracyTests` allowance and the Sun's motion for the distance. The check fails for the wrong body and a day off.
- Saturn's ring tilt against Horizons' sub-observer latitude at 11 dates from 2010 to 2035, through the 2025 ring-plane crossing, made planetocentric with Horizons' radii, within 0.02° (measured 0.015°; the ring plane is Schlyter's approximation), and its phase angle within 0.02°. Horizons leaves the rings out of Saturn's magnitude, so the magnitude is checked against its definition, Schlyter's formula evaluated on Horizons' phase angle, ring tilt and distances, within 0.002.
- Elongations of the Moon, Mercury, Venus, Mars and Jupiter every 46 days through 2026 against Horizons' S-O-T (40 rows) within 1′ (measured 0.07′), and their side against its leading or trailing flag, both sides seen; pair longitudes of each two of them against the difference of Horizons' apparent ecliptic longitudes within 1′ (measured 0.69′; the engine's have no aberration, which can differ by 41″ between two bodies).
- Chiron against six Horizons observer rows from 1900-01-01 03:00 UT to 2100: the astrometric direction within 0.02′ and the range within 3e-5 AU (measured 0.011′ and 1.4e-5 AU, in 2100, where Delta T is extrapolated), and the apparent ecliptic of date within the rows' 1′. At 1900-01-01 01:00 UT the observation is in the span and its light-time evaluation, 1.56 hours earlier, falls before the start.
- Mathematical bounds: routing to each body's model double for double; the ecliptic states' positions against `Engine.Ecliptic` of the positions, and the Sun's against `sunPosition`, bit for bit, at 120 and 200 instants from 1901 to 2099 and 4 beyond; their rates against five-point differences of those positions on 1/64-day stencils within the allowances `EclipticStateTests` sets (5e-8° and 2e-9 AU per day, the Moon 5e-7° and 1e-9 AU, Pluto 1e-6° and 2e-9 AU), at 60 instants, the series beyond the fits and the 2026 March equinox, where the Sun's longitude wraps; Pluto's in its integrated model, mid-blend and astride a 146-day step; rates continuous across polynomial segment boundaries, the Moon's blends and Pluto's 1900 blend; Mercury's rate smooth across changes in the light-time iteration count; and Mercury's 2025-08-11 station from the rate within 1 s of the differenced longitude's; states' positions against positions; barycentric states against the Sun's barycentric state plus the heliocentric ones, exactly for the Sun and the planets and within 1e-14 AU and 1e-17 AU per day for the Moon, the barycenter and Pluto; the light-time solution and the backdated time's model; the accepted range at both ends, beyond them and for times that are not finite; and velocities against five-point differences on 1/64-day stencils in 1800, 1945, 2000, 2026 and 2200, within (1 + |t|) · 1e-11 AU per day, t in Julian centuries, plus the documented lunar derivative allowance where it applies.

### Position test dispositions

| Test | Disposition |
|---|---|
| `DistanceAccuracyTests` and the `JPLValidationTests` geocentric and Asheville suites | Published-value checks of the public API on the engine. `EnginePositionsReferenceTests`, `EnginePlanetHorizonsTests` and `EnginePlutoHorizonsTests` apply the same fixtures and allowances to `Engine.Positions`. |
| `EclipticStateTests` | Kept on the public API: it checks the public ecliptic states against the public positions bit for bit, against differenced positions, across the light-time iteration-count switch and at the Mercury and Mars stations. Its direct C checks of the EQJ to ECT rotation rate, the nutation rates and the polynomial seams were retired; `EngineEclipticStateTests`, `EngineNutationTests`, `EnginePrecessionTests` and `EnginePlanetPolynomialTests` hold those for the engine. |
| `ReproducibilityTests` position, equatorial, ecliptic-rate and topocentric rows | Retired at the cutover, as recorded under [Earth orientation](#earth-orientation). The positions, equatorial coordinates, topocentric Moon and ecliptic rates are checked here against Horizons and against differenced positions. |
| `AuditValidationTests.jplGeocentricObservation` and `jplApparentRangeDiagnostic` | Published-value check and named sanity check of the public API on the engine. `EngineObserverRowTests` applies every column of the same rows to the engine, the range under Horizons' definition. |
| `IlluminationTests`, `ElongationTests`, `RelativeLongitudeTests`, `PositionTests` and `CoordinatesTests` | Named sanity checks of the public API on the engine. `EngineIlluminationTests` checks the engine's illumination, elongation and pair longitude against Horizons, and the other `Engine/Positions` suites its positions and coordinates. The searches in `IlluminationTests`, `ElongationTests` and `RelativeLongitudeTests` belong to #92. |
| `ChironTests` geocentric, equatorial, ecliptic and horizon cases, and `AuditValidationTests.chironPosition` | Public-API checks on the engine (see [Pluto, the gravity simulation and Chiron](#pluto-the-gravity-simulation-and-chiron) for the heliocentric cases). `EngineChironPositionsTests` checks the engine's composition against Horizons' observer rows; `ChironTests` checks the public `horizon` against the same rows. |
| `LightTravelTests` | Named sanity checks of the public light-time solver and backdated positions, on the engine. `EngineLightTravelTests` checks the engine's solver, and `EnginePositionsTests` its backdated positions against the light-time equation. |

## Jupiter's moons

In the tree: `Bodies/EngineJupiterMoons.swift` and the generated `Bodies/Generated/JupiterMoonSeries.swift`. They port `Astronomy_JupiterMoons`. Rotation axes are in the next section. `Bodies/EngineLagrange.swift` now implements L1–L5 and fast state-based calculations, with mass-product lookup using the existing native gravity constants. The public Lagrange facade uses it; independent definition checks are in `NativeLagrangeDefinitionTests`, and existing public degenerate-input and bounded-convergence tests remain in `LagrangePointTests`.

```swift
extension Engine {
    enum JUP: Frame {}   // L1.2's jovicentric frame
}
extension Engine.JupiterMoons {
    enum Moon: Int, CaseIterable { case io, europa, ganymede, callisto }
    struct States { var io, europa, ganymede, callisto: Engine.State<Engine.EQJ> }
    struct Term { let amplitude, phase, frequency: Double }
    struct Model { let mu: Double; let meanLongitude: (phase: Double, rate: Double); let a, l, z, zeta: [Term] }
    struct Elements { var a, meanLongitude, k, h, q, p: Double }
    static let models: [Model]                // generated, in Moon order
    static let epochTT: Double                // generated, −18,262.5, 1950-01-01 00:00 TT
    static let psi, inclination: Double       // generated, radians
    static let jupiterToEQJ: Engine.Rotation<Engine.JUP, Engine.EQJ>
    static let keplerIterationLimit: Int      // 10
    static func states(at time: Engine.Time) throws -> States
    static func state(of moon: Moon, at time: Engine.Time) throws -> Engine.State<Engine.EQJ>
    static func state(_ model: Model, at time: Engine.Time) throws -> Engine.State<Engine.EQJ>
    static func elements(of model: Model, tt: Double) -> Elements
    static func eccentricAnomaly(meanLongitude: Double, k: Double, h: Double) throws -> Double
    static func jovicentricState(_ elements: Elements, mu: Double, time: Engine.Time) throws -> Engine.State<Engine.JUP>
}
```

- The model is the L1.2 theory of Lainey, Duriez and Vienne (2006, A&A 456, 783), as IMCCE publishes it in `BisL1.2.dat`. Each moon has a semi-major axis (a cosine series), a mean longitude (a linear term plus a sine series), z = k + ih = e·exp(iϖ) and ζ = q + ip = sin(i/2)·exp(iΩ), with t in TT days from 1950-01-01 00:00 TT (JD 2433282.5). The engine keeps the leading terms of each series, as the C engine does: 75 of the 490 published (Io 10, Europa 21, Ganymede 22, Callisto 22). It leaves out the theory's Chebyshev corrections for long-period effects, which the theory applies only from about 1130 to 2763.
- `elements(of:tt:)` sums each series in its published order and reduces the mean longitude into [0, 2π), with `Engine.normalized` for a tiny negative remainder that would round up to 2π. `jovicentricState` is L1.2's `ELEM2PV`: Kepler's equation in the eccentric longitude, then the position and the Keplerian velocity of those elements in the `JUP` frame. The velocity is the theory's definition, not the derivative of the position.
- `eccentricAnomaly` is Newton's method from L1.2, stopping once a step is below 1e-12 radians. The series keep each eccentricity below 0.0104, the sum of Europa's z amplitudes, and from there the third step is below 1e-22. After `keplerIterationLimit` steps it throws `noConvergence`. A step that is not a number ends the iteration, as in `ELEM2PV`, and the state that follows throws `badTime`.
- `jupiterToEQJ` is built from L1.2's published angles Ψ and I with `L1.2.f`'s formula. L1.2 calls the result the mean equator and equinox of J2000; it was fitted with DE406, whose axes are the ICRF's, so the engine takes it as EQJ, as the C engine does. The 23 mas frame bias between them is at most 0.2 km at Callisto's distance.
- `states(at:)` and `state(of:at:)` check the time against `Engine.acceptedTTDays` first and throw `badTime`. `state(_:at:)` throws `badTime` for a state that is not finite, through `Engine.Positions.checked`. Results carry the time they were given.
- `Scripts/generate-jupiter-moon-series.py` writes `JupiterMoonSeries.swift`: the models from the `jm_*` term arrays and `JupiterMoonModel` of `astronomy.c`, a block whose SHA-256 `Scripts/jupiter-moon-data/manifest.json` pins, and the time origin, Ψ and I, which the C engine does not hold and the generator transcribes from `BisL1.2.dat`. `--check` runs in CI on macOS and Linux. `--published DIR` reads `BisL1.2.dat` (URL and SHA-256 in the manifest; not checked in) and checks every kept term bit for bit as the leading terms of its series, each moon's G × mass and mean longitude, and the transcribed time origin, Ψ and I.

### Differences from published values

- The kept terms and the missing Chebyshev corrections leave the engine short of the full theory. Against Horizons, inside JD 2426545.0 to 2476545.0 (1931-07-22 to 2068-06-12), where Astronomy Engine set its 9e-4 limit, the largest error is Io's: 8.34e-4 of its distance and of its speed. Outside, at 1900-01-01 and 2100-01-01, Io is 1.08e-3 off and the others at most 3.2e-4; no limit applies there. In a one-off comparison during development, with a harness that was not committed, the full theory with its corrections was no closer for Io over 1900 to 2100 (1.11e-3 against 1.14e-3 on a 37-day grid) and closer for Callisto (1.9e-4 against 4.3e-4).

The committed [residual harness](Scripts/jupiter-moon-data/residual-method.md) splits the current model's position error in km and returned Keplerian-velocity error in km per TT day over all 104 archived Horizons rows. Its [evidence](Scripts/jupiter-moon-data/residual-evidence.json) preserves raw captures, source hashes, separate per-moon maxima, and exact worst epochs. It does not reproduce the former full-theory comparison or qualify unsampled epochs.

The [jup365 representation qualification](Scripts/jupiter-moon-data/jup365/README.md) extracts every source record over the kernel's actual JD TDB `[2305456.5, 2524602.5)` domain. Its mixed Float32 and scaled Int16 payload totals 60,192,342 bytes and has continuous coefficient-representation bounds below 0.229 km in jovicentric position and 33.74 km per TDB day in its analytic derivative. The report separately records 104 sampled Horizons residuals, source provenance, size, and a host-specific Swift lookup measurement. These files are not used by `Engine.JupiterMoons`; runtime selection, L1.2 fallback, and endpoint transitions remain for the next #254 change.

### Differences from the C engine

- The rotation is built from Ψ and I. The C engine's `Rotation_JUP_EQJ`, printed to 15 digits, agrees within 4.5e-16.
- Newton's method stops after 10 steps; the C engine's loop has no limit. By the bound above, the series need three.

### Published-value checks

Tests under `Tests/AstronomyKitTests/Engine/Bodies/`:

- Horizons states of each moon from Jupiter's center (jup365): 22 per moon inside the domain where the 9e-4 limit applies, at both ends, every 2,500 days between and 2000-01-01 (`sources/horizons/<moon>-domain-vector.json` and `<moon>-vector.json`), all within 9e-4 in position and velocity, the `ctest.c` limit. The checks assert that the samples reach both ends of the domain, and fail for the wrong moon and an hour off. Outside the domain, a day beyond each end, 1900 and 2100, the states are finite.
- The time origin, Ψ and I as `BisL1.2.dat` prints them; the number of kept terms of each series and two of the terms. The generator's `--published` mode checks all 75 terms, the masses and the mean longitudes.
- Each moon's mean motion √(μ/a³) against `TestL1.2.res` within 1e-15.
- The rotation against `L1.2.f`'s formula, and its orthonormality.
- Mathematical bounds: Kepler's equation solved within 1e-14, and the mean longitude in [0, 2π), at 401 times per moon across the accepted range; the eccentricity bound the iteration limit rests on; `noConvergence` near e = 1; the accepted range at both ends, beyond them and for times that are not finite; `badTime` for a state that is not finite; `states(at:)` equal to each `state(of:at:)`.

### Jupiter moon test dispositions

| Test | Disposition |
|---|---|
| `AuditValidationTests.boundedGalileanMoonState` and `galileanMoonStateObservation` | Published-value check and named sanity check of the public API on the engine. They read the 88 rows inside the domain and the 16 outside it. `EngineJupiterMoonsTests` applies the same rows and limit to the engine. |
| `JupiterMoonsTests`, and the Jupiter moon cases of `AcceptedTimeRangeTests` and `HugeTimeTests` | Named sanity checks and range guards of the public API on the engine. `EngineJupiterMoonsTests` checks the engine's range and guards. |

## Rotation axes

In the tree: `Bodies/EngineRotationAxis.swift`. It ports `Astronomy_RotationAxis`.

```swift
extension Engine {
    struct Axis { var rightAscension, declination, spin: Double; var north: Vector<EQJ> }
}
extension Engine.RotationAxis {
    static let bodies: [CelestialBody]   // the Sun, Mercury to Pluto, the Moon
    static let earthSpinAtJ2000: Double  // 190.41375788700253
    static let earthSpinRate: Double     // 360.9856122880876
    static func axis(of body: CelestialBody, at time: Engine.Time) throws -> Engine.Axis
    static func elements(of body: CelestialBody, tdb: Double) throws -> (ra: Double, dec: Double, spin: Double)
}
```

- Every body but Earth follows the IAU Working Group on Cartographic Coordinates and Rotational Elements: the 2015 report (Archinal et al. 2018, Celest. Mech. Dyn. Astr. 130:22), and for the Moon, which the 2015 report does not cover, the 2009 report (Archinal et al. 2011, 109:101). `elements(of:tt:)` gives the pole's right ascension α0 and declination δ0 and the prime meridian's W in degrees. The reports define d in TDB days and T in Julian centuries of TDB from J2000; the engine evaluates them at TT, as the C engine does and as #90's scope asks. The right ascension is reported in sidereal hours, unreduced as in the C engine; over the accepted range every one stays in 0 to 24 hours. `north` is the unit vector at (α0, δ0). W is measured counterclockwise about that pole from the node of the body's equator on the J2000 equator, at right ascension α0 + 90°, and is not reduced to one turn.
- Earth keeps the C engine's model, as #90's scope asks ("retaining coefficients, frames, time scales, and provenance"). Its pole is the true pole of date, `Engine.FrameRotation.eqdToEqj` applied to the z axis (IAU 2006 precession and IAU 2006/2000A nutation, where the C engine takes IAU 2000B), with its right ascension from 0 up to 24 hours and its declination from `Engine.Equatorial`, as the C engine's `Astronomy_EquatorFromVector` gives them. Its W is `earthSpinAtJ2000` + `earthSpinRate` × UT days: it equals the 2009 report's W at J2000, 190.147° (`BODY399_PM` in `pck00011.tpc`), re-expressed on UT with a Delta T of about 63.85 s, and turns at the rate of the Earth rotation angle (IAU 2000 Resolution B1.8). The report's W turns at 360.9856235° per TDB day, so the two part away from J2000. Measured once with Espenak-Meeus Delta T, Earth's W is 0.69° above the report's in 1900 and 0.15° below in 2026 and 0.99° below in 2100; on the report's pole it puts Greenwich 0.59° off in 1900, 630″ in 2020 and 0.69° in 2100. Earth's returned pole and W do not place Greenwich together: measured with the construction the other bodies follow, they put it 179° off in 1900, 134° at 2000.0 and 0.4° to 0.7° from 2010 to 2100.
- `axis(of:at:)` throws `invalidBody` for any other body before anything else, and `badTime` for a result that is not finite, a time that is not finite included. Like the C function it does not check the time against `Engine.acceptedTTDays`: the expressions hold no ephemeris. The north vector carries the time it was given.

### Differences from published values

- The reports' expressions take TDB; the engine, like the C engine, evaluates them at TT. Over the accepted range `Engine.TDB.offsetSeconds` stays under 1.85 ms in size: its largest, on a 2-day scan refined to 0.001 day, is 1.840 ms at TT −1,457,107.5 days, near the range's early end (1.697 ms on the same scan from 1900 to 2100). That moves W by under 1.9e-5° for Jupiter, the fastest: 1.854e-5° at the largest offset. The test asserts the 1.840 ms there and that every 100th day across the range stays under 1.85 ms.

### Differences from the C engine

- The C function returns a time or result that is not finite as a success; the engine throws `badTime`.

### Published-value checks

Tests under `Tests/AstronomyKitTests/Engine/Bodies/`:

- NAIF's `pck00011.tpc` (`Scripts/reference-data/sources/naif`, URL and SHA-256 in `build-fixtures.py`), NAIF's machine-readable transcription of the 2015 report, and of the 2009 report for Earth and the Moon. The test reads its data blocks and evaluates each body's polynomials and nutation-precession terms as NAIF's PCK required reading defines them, at 81 times a century apart from one end of the accepted range to the other, both ends included, and 61 times 13.37 days apart from 2025-12-31 12:00 TT into 2028. Each time has its UT from Espenak-Meeus Delta T, and the expressions take its TT as TDB. The ten bodies other than Earth match it within 1e-14 of each value's size plus a turn, with right ascensions in 0 to 24 hours. The check fails for the elements evaluated at TDB and for the wrong body.
- For the same ten bodies, the prime meridian that the returned α0, δ0 and W place, by NAIF's construction of the body-fixed frame, against the one the PCK's values place, at the same times and within the same allowances; and perpendicular to the returned pole.
- Earth's pole against the third row of N·P built from SOFA's precession and nutation angles (pyerfa 2.0.1.5, the eight epochs from 1600 to 2500 with UT1 and TT apart that the orientation tests use), within √3 · 2e-15 radians from the 2e-15 those tests allow each element; its right ascension in 0 to 24 hours at every sample time, before and after J2000.
- Earth's W less SOFA's `era00` at UT1 the same at those eight epochs, `earthSpinAtJ2000` less the Earth rotation angle's 280.46061837504° at UT1 0, modulo 360°; its rate 360 × 1.00273781191135448; and over 0.25° away from the same W taken at TT in 2026.
- Earth's W at J2000 against `BODY399_PM`: the Delta T it implies, 63.85 s, within the 0.1 s to which the Astronomical Almanac's observed 63.8 s for 2000.0 is published; and the report's pole with Earth's W at J2000 TT, UT 63.8 s earlier, places the report's prime meridian within that 0.1 s of rotation, 1.5″.
- Earth's returned pole and W, combined as for the other bodies, put Greenwich (the true equator of date at apparent sidereal time) more than 0.25° off in 1900, at 2000.0, in 2026 and in 2100. The other Greenwich figures above are measured, not asserted.
- Mathematical bounds: `invalidBody` for every other `CelestialBody`, with a time that is not finite too; `badTime` for times that are not finite; and the time carried.

### Rotation axis test dispositions

| Test | Disposition |
|---|---|
| `RotationAxisTests` | Named sanity checks of the public API on the engine. `EngineRotationAxisTests` checks the engine against the published elements and orientation. |

## Fixed stars and constellations

In the tree: `Engine/Stars/EngineStar.swift`, `EngineConstellations.swift` and generated `ConstellationData.swift`.

`Engine.Star` is an immutable, `Sendable`, hashable value containing a catalog right ascension in `[0, 24)` hours, declination in `[-90, 90]` degrees and a distance of at least one light-year. It validates on use, as `Astronomy_DefineStar` does, and converts light-years with the C contract's 63,241.07708807546 AU per light-year. A definition is passed directly into each calculation; no shared star slots or mutable definitions exist in the native path.

The heliocentric vector is fixed on J2000 axes and is treated as already corrected for light-travel time, as the C engine treats user-defined stars. A geocentric vector subtracts Earth's native heliocentric position. With annual aberration it adds Earth's heliocentric velocity multiplied by the star-to-Earth distance divided by the published speed of light; this retains the C engine's linear approximation. Equatorial results subtract the observer's J2000 vector and optionally rotate to the true equator and equinox of date. Ecliptic results use the true ecliptic and equinox of date, and horizon results use apparent topocentric equatorial coordinates of date before the requested refraction.

The independent fixture archives the official IAU SOFA 2023-10-11 astrometry example and a recipe that sets its proper motion to zero because the public fixed-star value has no proper-motion terms. One row checks every native star calculation within 0.5 arcsecond, twice the sampled 0.246 arcsecond maximum rounded up. That limit is a sampled regression margin across the engine's IAU 1976/2000B orientation and linear aberration choices, not a published accuracy. The former Sirius row in `ReproducibilityTests`, which pinned C-engine bit patterns, is retired in favor of this published-source comparison. The public `FixedStar` remains on the C engine until #96.

`Engine.Constellations` identifies a mean-J2000 right ascension and declination with Nancy Grace Roman's CDS/VizieR VI/42 rearrangement of Delporte's IAU boundaries. Its immutable J2000-to-B1875 rotation is the Herget mean-place precession in the catalog's published C program, with the program's constants and epoch pair 2000.0 to 1875.0. This deliberately replaces the C path's true-equator-of-date rotation, whose first initialization reads Delta T and nutation for its B1875 instant. A mean-place boundary conversion has no UT, Delta T, or nutation input, so native results do not depend on the process model or first call. `Engine.B1875` names this mean equator and equinox frame.

The generated table contains all 357 VI/42 southern boundary segments and maps their abbreviations to all 88 official IAU names. Lookup follows the published inequalities in source order: declination is on or north of the row's lower boundary, right ascension includes the lower end and excludes the upper end. Right ascension wraps to `[0, 24)`; a declination outside `[-90, 90]` or a coordinate that is not finite throws `invalidParameter`. The public `Constellation` API remains on the C engine until #96.

`EngineConstellationTests` checks every table row at its lower-right-ascension, upper-right-ascension and lower-declination ties, so 1,071 exact ties test the published table semantics without an angular tolerance. It also checks all eight examples printed in the VI/42 ReadMe and 357 generated J2000 points, one near each segment. The generator compiles and runs the archived publisher program on those eight examples, and independently translates its Herget formula for the J2000 samples. The `< 1e-9`-degree/hour coordinate check is cross-language recipe agreement at those generated points, not a certified precession accuracy or continuous-sky claim. `EngineStarConcurrencyTests` repeats every native star calculation and the constellation lookup for 24 distinct immutable stars under two explicit model-bearing times while equivalent process-default function pointers are changed concurrently. A separate direct test proves that two distinct Delta T outputs change the old true-of-date B1875 matrix while the published Herget matrix is fixed.

## Angular event searches

In the tree: `Events/EngineAngularEvents.swift`, `Events/EngineLunarEvents.swift` and `Events/EnginePlanetaryEvents.swift`. The first three #92 links add the shared event namespace; apparent solar-longitude search and seasons; heliocentric planetary relative-longitude search; lunar phase, quarter, node and apsis searches; and planetary maximum-elongation, peak-magnitude and apsis searches. Observer event searches remain for the final #92 link. The public event facades remain on the C engine until #96.

```swift
extension Engine.Events {
    struct Seasons {
        let marchEquinox, juneSolstice, septemberEquinox, decemberSolstice: Engine.Time
        var all: [Engine.Time] { get }
    }
    static func searchSunLongitude(_ targetDegrees: Double, after start: Engine.Time, limitDays: Double) throws -> Engine.Time?
    static func seasons(year: Int, deltaTModel: DeltaTModel) throws -> Seasons
    static func searchRelativeLongitude(of body: CelestialBody, targetDegrees: Double, after start: Engine.Time) throws -> Engine.Time
    static func moonPhaseAngle(at time: Engine.Time) throws -> Double
    static func searchMoonPhase(_ targetDegrees: Double, after start: Engine.Time, limitDays: Double) throws -> Engine.Time?
    static func searchMoonQuarter(after start: Engine.Time) throws -> LunarQuarter
    static func nextMoonQuarter(after quarter: LunarQuarter) throws -> LunarQuarter
    static func searchLunarNode(after start: Engine.Time) throws -> LunarNode
    static func nextLunarNode(after node: LunarNode) throws -> LunarNode
    static func searchLunarApsis(after start: Engine.Time) throws -> LunarApsis
    static func nextLunarApsis(after apsis: LunarApsis) throws -> LunarApsis
    static func searchMaximumElongation(of body: CelestialBody, after start: Engine.Time) throws -> Engine.Elongation
    static func searchPeakMagnitude(of body: CelestialBody, after start: Engine.Time) throws -> Engine.Illumination
    static func searchPlanetaryApsis(of body: CelestialBody, after start: Engine.Time) throws -> PlanetaryApsis
    static func nextPlanetaryApsis(of body: CelestialBody, after apsis: PlanetaryApsis) throws -> PlanetaryApsis
}
```

`searchSunLongitude` follows the apparent geocentric Sun on the true ecliptic and equinox of date and calls the native ascending-root search with the C algorithm's 0.01-second tolerance. The inclusive window may run either direction. A window without an ascending crossing returns `nil`; a target or limit that is not finite throws `invalidParameter`; and either bound outside the native ephemeris range throws `badTime`. Targets wrap by whole turns through `longitudeOffset`.

`seasons` searches from modeled UT midnight on 10 March, June, September and December for 0°, 90°, 180° and 270° respectively, over 20 days. It rejects a year outside the `Int32` range and derives every search time with the explicit model it receives. `EngineAngularEventTests` checks all 924 seasonal crossings from 1900 through 2130 under both Delta T models against independently derived Horizons LT+S vectors rotated with ERFA; every root must be within 60 seconds. The seasonal fixture now contains only this independent reference. The former model-output columns and 10-millisecond regression test were retired because recorded engine output is not accuracy evidence.

`searchRelativeLongitude` supports Mercury, Venus and Mars through Pluto. It follows the original definition: Earth's heliocentric longitude minus the planet's, positive for outer planets and negative for Mercury and Venus. The initial angular error is forced behind the target, so iteration advances from the supplied start; each step uses the body's mean synodic period and the near-root period correction from the original algorithm. It stops inside one second, caps iteration at 100, rejects a step that is not finite or cannot advance, and checks actual native ephemeris coverage after each step. Earth throws `earthNotAllowed`; every other unsupported body throws `invalidBody`. Tests bracket four independently sampled Mars and Venus conjunction/opposition roots derived from SOFA-transformed geometric Sun-centered vectors, exercise every supported planet, and retain target wrapping, body errors, forward ordering, model capture and range guards.

The lunar phase angle is the shared apparent Moon's true-ecliptic longitude east of the shared apparent geocentric Sun at reception. The phase search predicts a bracket from the mean synodic month, clips that bracket to the caller's inclusive forward or backward window and refines the ascending crossing to 0.1 second. The exact lower reception endpoint is supported by the internal emission margin; searches retain the requested endpoint and captured model. Quarter searches select the next multiple of 90 degrees and preserve the time's captured Delta T model. Node searches refine zero crossings of the Moon's true-ecliptic latitude. Apsis searches refine zero crossings of the analytic radial velocity from the native lunar state and report the model distance at the root. Both use bounded forward stepping, one-second root tolerances and checks for progress, alternation, finite values and actual ephemeris coverage.

`EngineLunarEventTests` derives four January 2025 quarter roots from archived NASA/JPL Horizons apparent ecliptic longitudes sampled at one-minute intervals; every native root is within 15 seconds, with a measured maximum residual of 1.615 seconds. It also applies the existing published allowances to the eight 1800 and 2000 minute-rounded USNO phase references, six node references and six apsis references, including the two independent 1903 geometric cases, and checks direction, endpoints, ordering, model capture and range failures. For January 2100 the phase references are four Horizons quantity 31 roots requested in TT, with a 2-second allowance; the native roots fall 0.657 to 0.819 seconds before them. USNO labels its 2100 quarters in UT without documenting the Delta T behind them. Read with Espenak–Meeus Delta T, those labels put the 26 January full moon 92.084 seconds and the 3 January last quarter 108.196 seconds from the native roots, so the native suites record the four USNO 2100 residuals as diagnostics and do not gate on them. The DE441 event harness invokes the same apparent phase definition on its direct and native sides around all 369 direct-source roots in its 20 frozen full-span and transition windows. The sampled source differences remain evidence about the native lunar model, not a continuous full-range event-accuracy claim. Public phase, quarter, node and apsis APIs continue to use the C engine until #96.

Maximum-elongation and peak-magnitude searches retain the original heliocentric relative-longitude windows and central-difference observables. Mercury and Venus maximum elongation refine the descending derivative of apparent Sun separation to ten seconds; Venus peak magnitude refines the ascending derivative of visual magnitude to ten seconds. Each search tries no more than two candidate windows, preserves the start time's Delta T model, validates the final body evaluation against its actual source range and returns the first result at or after the supplied time. Published Horizons S-O-T brackets check both morning and evening maxima for both planets. The archived 2010–2030 Horizons APmag series checks a Venus peak against the actual magnitude minimum rather than a proxy such as illumination fraction.

Planetary apsides are extrema of geometric planet-center distance from the Sun center. Mercury through Uranus retain the original one-second radial-slope root search, with steps of one sixth of the mean orbital period and a two-orbit bound. Neptune and Pluto retain the original bounded sampling search because their distance curves contain short-period structure: 100 samples over a 300-degree arc locate both candidate extrema, and ten-point refinements narrow the entire surviving interval below one minute and return its midpoint. Advancement skips one quarter orbit and requires a later event of the opposite kind. Every evaluation uses the input time's model and the body's actual native source coverage; a search that would sample outside that coverage throws rather than returning an out-of-domain event.

`EnginePlanetaryEventTests` applies the archived Earth apsis time and distance allowances, checks all nine native sequences for order, alternation and exact reported model distance, and retains C algorithm comparisons for the six unchanged search/model paths. Saturn now combines DE441's Saturn-system barycenter and Sun with SAT441's physical-center offset. Native physical-center position, state and distance share this trajectory; analytic velocity includes the TT/TDB rate and blend derivative. GM-weighted origins and gravitational forces use a separate target-6 system-barycenter trajectory without the satellite center offset, including its blend derivative. Saturn body-state APIs and gravity-simulation origin translations retain the physical center. Source-composition regressions cover the four-body and eight-body origins and forces, body-state reconstruction and both transitions. The full-weight TT interval is `[-36524.5, 47846.5]` days from J2000, with 32-day exterior blends `[-36556.5, -36524.5]` and `[47846.5, 47878.5]`. This reversible source-window choice does not change the accepted range or establish a global accuracy policy. All six archived Saturn body-center roots now meet the unchanged 60-second target, with maximum sampled error below 0.58 seconds. The remaining accepted range retains the old trajectory.

The independent eight-body diagnostic windows preserve every locally sampled source crossing and refine each to a sub-second bracket. Mercury, Venus, Earth, Mars and Pluto meet sixty seconds at the tested events. Jupiter, Uranus and Neptune still fail: their current native residuals from the nearest same-kind source crossing are about +19,895, −174,123 and +117,316 seconds. These are unresolved #92 qualification criteria, not approved tolerance exceptions. Multiple local extrema also leave principal orbital-event identity unqualified by these short windows. The API already defines closest/farthest orbital distance; no new canonicalization rule is selected here.

The Neptune/Pluto sampled-refinement helper now stops on the entire surviving span and returns its midpoint. The former `span / 9` stop with a `span / 18` return offset produced a 194.13-second native Pluto error against the frozen source bracket; the correction reduces it to 2.85 seconds. The original public C helper still has this pre-existing defect until #96 cutover. See [the Saturn assessment](Scripts/saturn-data/ASSESSMENT.md), [source bounds and candidate sizes](Scripts/saturn-data/assessment.json), and [source-bound native measurements](Scripts/saturn-data/native-evidence.json) for provenance, costs, replay commands and qualification limits. Public planetary event APIs continue to use C; this native link does not complete #92 or #96.

## Caches and reset

In the tree: `EngineCache.swift`.

- `Engine.ExactKey` is the bit pattern of a finite `Double`. `0.0` and `-0.0` are different keys. A value that is not finite has no key and bypasses the cache.
- `Engine.BoundedCache<Key, Value>` holds at most `capacity` entries and replaces the oldest insertion when full, as the C caches do. All threads share the entries. The computation runs outside the lock, so it may use any cache, including the one it fills. A computation that throws stores nothing. `statistics` counts hits and misses for work-count tests.
- A cached value is a pure function of its key: never the process Delta T default, never a caller's time metadata. Then a hit returns what recomputing would, and a reset at any moment cannot change a result.
- Each module creates its caches as `static let` properties, registered with `Engine.CacheRegistry.shared`, so a cache that has never been used does not exist yet. That is a convention, not a checked rule: a cache made on every call gives correct results but never a hit. The registry holds its caches weakly. Once nobody references a cache, a reset skips it, and the next registration drops its entry, so after each registration the registry holds no more entries than there are caches alive.
- `Engine.resetCaches()` empties every registered cache. It does not touch the Delta T default, fixed star definitions or gravity simulations, which are not caches. `AstronomyConfig.reset()` calls it.
- A reset does not wait for computations in progress. A lookup that missed before a reset stores its value after it, and a computation can itself reset. Either way the stored value is the one its key gives, so the next hit returns what recomputing would.
- Shared mutable state uses `NSLock` or `Synchronization.Atomic`, not `Synchronization.Mutex`. ThreadSanitizer on Linux does not model `Mutex`, and suppressing its reports would also hide races in any computation called through a cache (see `.github/tsan-suppressions.txt`).
- Tests that count work make their own `CacheRegistry` and cache, because the shared caches are process-wide.

| State | Owner | Native form | C counterpart |
|---|---|---|---|
| VSOP87B series results | #85 | `Engine.VSOP87B.cache`: per planet, a 32-entry `BoundedCache` of coordinates and one of derivatives, `ExactKey` of the scaled TT the series read | Thread-local, 32 per body (local patch 8) |
| Nutation angles and rates | #86 | `Engine.Nutation.cache`: `BoundedCache`, 32 entries, `ExactKey` of TT in Julian centuries, shared by angle, rate, tilt and sidereal-time callers | Thread-local, 32 entries (local patch 13) |
| Moon longitude, latitude, distance | #87 | `Engine.Moon.cache`: `BoundedCache`, 32 entries, `ExactKey` of TT in Julian centuries, shared by positions and states | Thread-local, 32 entries (local patch 14) |
| Pluto segments | #88 | `Engine.Pluto.cache`: `BoundedCache` of 50 entries, one per segment, keyed by segment index | Allocated segments behind a mutex, freed by `Astronomy_Reset` (local patch 1) |
| Delta T default | #96 | `Atomic` in the public layer | `_Atomic` function pointer (local patch 2) |
| Gravity simulation | #88 | `Engine.GravitySimulation`: two moments behind its own `NSLock`, updated optimistically | Caller-owned handle |
| Fixed star definitions | #91 | Passed by value | Eight shared slots |
| Constellation B1875 rotation | #91 | `static let` | `pthread_once` (local patch 4) |

## Public layer integration (#96)

The public API runs on the engine. `AstroTime` stores an `Engine.Time`; `AstronomyConfig.setDeltaTModel` writes an `Atomic` process default that each public initializer given no model reads once; `AstronomyConfig.reset()` calls `Engine.resetCaches()`; `AstroTime(year:...)` and `AstroTime.civil(days:deltaTModel:)` call `Engine.Time.days` and `Engine.Time.civil(utcDays:deltaTModel:)`; `AstroTime.siderealTime` is `Engine.EarthRotation.apparentSiderealTime`. Every facade under `Sources/AstronomyKit` converts its arguments to engine values, calls the engine function named in the sections above, and converts the result back; a result that keeps the caller's time keeps the caller's `AstroTime`, and a time the engine derives becomes a new `AstroTime`. Public names, signatures, conformances, `Codable` shape, units, frames and error cases did not change. The three integration links and the measured public differences are recorded in [NativeFacadeIntegration.md](Documentation/Migration/NativeFacadeIntegration.md).

`Astronomy_SetDeltaTFunction` has no replacement: the C target was never a declared product, and the owner chose on #96 to remove the transitive setter at the cutover. The supported surface is `AstronomyConfig.setDeltaTModel(_:)` with the named `DeltaTModel` cases and the per-time `deltaTModel:` initializer parameter.

## C entry points

The Swift layer calls none. `EngineContractTests` fails when a code line under `Sources/AstronomyKit` names an `Astronomy_` function or imports `CLibAstronomy`. The sections above record, per function, which C entry point it replaced; the owner map that assigned each C function to a port issue is in this file's history before the cutover.

## Changing this contract

A module records the signatures it provides here, in the PR that adds them, before a dependent module starts. A change to another module's provided signatures goes through that owner's issue. `Foundation/`'s owner, #84, is closed: the #87 PRs moved `unpackDoubles` and `acceptedTTDays` into it and recorded that here in the same PRs, and no other rule has been set for it. Each change to this file updates the sections it affects rather than appending history.

## Native observer searches

`Engine.Events` now provides hour-angle evaluation and directional search, bounded altitude search, and rise/set search for immutable body or fixed-star targets. The port retains the original 0.1 sidereal-second hour-angle stopping criterion, 0.42-day altitude scan, seventeen-level ascent subdivision, one-second minimum subdivision span, 0.1-second root tolerance, empirical body slope limits, dynamic limb radius, atmosphere and horizon dip. Invalid inputs, source-domain errors and failed progress throw; a missing event returns `nil`. The final altitude step is clipped to the declared window, preventing a valid short upper-domain window from probing past the accepted domain. Same-sign ascent pruning uses the full half-span slope bound, retaining high-altitude crossings that the original quarter-span arithmetic could discard. The original bracket rule requires a strictly negative value at the earlier endpoint and a nonnegative value at the later endpoint. A forward start exactly on the crossing is excluded by that rule; a backward start can be the included later endpoint. A zero-length altitude window returns `nil`. These discovery rules do not certify a census of arbitrarily close tangent events.

The native solar rise/set limb uses 696,000 km, supported by three archived USNO apparent semidiameters and independent Horizons distances. All 5,909 USNO rows pass their unchanged allowances; the South Pole row 2,923 is +50.424815132 TT seconds against 70.8 seconds. The largest other residual is 38.016633969 seconds. Sixteen independent airless altitude/hour-angle points pass the existing one-arcminute angular allowance. The printed semidiameter comparison discriminates the optical convention and does not establish the Sun's physical radius or expose the USNO rise/set implementation. Other radius consumers remain unchanged.

The complete source queries, raw responses, per-row native captures, mutation controls, build/resource observations and reproducible checks are described in [`Scripts/observer-event-data/README.md`](Scripts/observer-event-data/README.md). The retained nominal-radius polar controls remain in [`PolarSunriseReconciliation.md`](Documentation/Migration/PolarSunriseReconciliation.md). The public observer APIs run on these searches: row 2,923 passes its allowance in `AuditValidationTests` (#124), and `NativeCutoverTests` keeps the out-of-window endpoint and quarter-span pruning cases on the public API. The #92 native port has four links, with no additional link planned. Its three outer-planet apsis source mismatches remain unresolved, so this observer qualification does not establish complete #92 acceptance or close the issue.

## Native lunar eclipses

In the tree: `Eclipses/EngineShadowGeometry.swift` and `Eclipses/EngineEclipseEvents.swift`. The first #93 link adds shared conical-shadow and disc-overlap geometry plus native lunar-eclipse search. Global solar search is added by the second link below. Local solar circumstances are added by the third link below; Mercury/Venus transits are supplied by the fourth link below. The public eclipse and transit facades run on them.

`Engine.Shadows.calculate` projects a target onto a Sun-to-casting-body direction and reports the shadow-axis distance plus umbral and penumbral radii at that plane. Distances and radii are in kilometers; input vectors remain in their declared frame and in AU. `obscuration` returns the intersection area of two discs divided by the first disc's area. `lunarEarthShadow` applies the Five Millennium Canon's Danjon equations, `Rp = 1.01 Pm + Ss + Ps` and `Ru = 1.01 Pm - Ss + Ps`, on a tangent plane at the Moon's geocentric distance. The factor includes the Canon's atmospheric enlargement and mean oblateness correction. The Moon uses its 1,737.4 km mean radius projected onto the same plane; the Sun uses 695,700 km.

`searchLunarEclipse` examines no more than twelve consecutive full moons. It prunes a full Moon only above 1.8 degrees true-ecliptic latitude, finds minimum Earth-shadow-axis distance in the original ±0.03-day window and uses strict contact inequalities to classify penumbral, partial and total events. Principal contacts use one-second roots around the peak, and each duration is the average of its two semidurations. `nextLunarEclipse` starts ten days after the previous peak and requires forward progress. Every derived time retains the input's Delta T model. Invalid or unsupported evaluations, missing roots and failed progress throw rather than producing a partially valid eclipse.

The eclipse search rechecks a preceding full Moon inside the peak-refinement window, then selects a phase-sign bracket on an absolute-TT daily grid. This makes refinement independent of the caller's discovery start; exact grid roots are returned directly and grid endpoints are clipped to the accepted domain. An eclipse remains inclusive through the represented endpoint `physicalPeak.tt + 1/86400`. A search start inside that one-second resolution interval clamps only the reported peak to the start, retaining the physical peak for later boundary decisions. Repeated clamps cannot extend the event's acceptance window. Kind, obscuration and semidurations belong to the physical candidate; absolute contacts inferred from the reported peak shift by the presentation clamp, nominally at most one second (subject to the represented TT endpoint). This boundary convention does not change the physical source allowances.

Six pinned NASA catalog cases from 1800, 2000, 2001 and 2099 retain the existing 120-second peak allowance and two-minute phase-duration allowance. NASA's Observer's Handbook 2001 page supplies exact UT peaks for one total, one partial and one penumbral event; their phase durations come from the Danjon-based Five Millennium Catalog and do not reinterpret its TD greatest-eclipse coordinates as UT. NASA lunar magnitude is a diameter fraction, not disc-area obscuration, and the fixture preserves that distinction. NASA SVS pages directly publish Moon-disc area obscuration for 2021 and 2026; the 2021 result retains its ordinary print-interval gate, while the 2026 apparent-input result is an explicit known discrepancy under #275 against the unchanged interval. [`Scripts/eclipse-data/README.md`](Scripts/eclipse-data/README.md) records the source-bound Debug/Release and resource evidence.


### Global solar eclipses

`EngineGlobalSolarEvents.swift` supplies an internal partial/annular/total result, `searchGlobalSolarEclipse` and `nextGlobalSolarEclipse`. The new-moon path reuses the eclipse-private absolute-TT phase-sign bracket while preserving the shared phase API and lunar wrapper. It retains the twelve-lunation bound, ±0.03-day axis-distance peak window, one-second inclusive physical-peak endpoint and ten-day advancement. Results retain the caller's Delta T model. At the lower accepted start a later in-domain eclipse can be found; searches whose required evaluations exceed the accepted range throw. A missing canonical phase bracket or failed geometric refinement throws without a noncanonical fallback.

`EngineGeoidIntersection.swift` scales the ellipsoid to a unit sphere and uses the closest-axis distance rather than subtracting two large quadratic terms to decide miss, tangent or intersection. For an axis miss, it computes the closest surface point in ordinary kilometers. Finite cone overlap is checked even when the axis misses Earth. Where the closest point alone does not decide overlap, convex supporting-plane bounds certify a miss or find a surface witness; bounded nonconvergence throws. The diagnostic test covers a cone that intersects away from the point closest to its axis. No guessed physical-distance epsilon, 14-meter kind bias or 0.9999 annular cap is used.

Partial results have both coordinates nil and obscuration NaN. Total/annular results report a finite geodetic surface location and the obscuration at that same point, total exactly one and annular strictly between zero and one. Coordinates, kind and area belong to the physical peak even if the reported time is clamped inside its existing one-second resolution interval. Non-central locations use a surface witness, not a nonexistent axis intersection; the seven sampled source events satisfy their existing timing/location allowances.

Solar radii, primary-source conventions, the passing direct RP1301 Table 4 area samples, the unresolved finer RP1301 G0 interval and the 1986 mean-limb/beaded-annular distinction are recorded in [the eclipse evidence README](Scripts/eclipse-data/README.md). This is sampled native qualification; it does not establish full RP1301 agreement or physical lunar-limb accuracy. The public non-central classification defect of the C path ended at the cutover; `NativeCutoverTests` keeps the 2014 and 2043 cases on the public API.


### Local solar eclipses

`EngineLocalSolarEvents.swift` adds native local search/next and observer contact records. Canonical new moons feed a ±0.2-day topocentric shadow-axis minimum, exterior contact roots within ±0.2 day and interior roots within ±0.01 day. The solar-specific angular geometry reuses the prior link's 959.63″ solar convention, k1 = 0.272488 for exterior contacts and k2 = 0.272281 for interior contacts and disc area. It does not adopt the rise/set optical radius, C's mean-Moon contact radius, 14-meter kind bias or annular area cap. This smooth-disc convention does not model lunar mountains or remove the existing global source limitations.

Every local result has exterior contacts and a finite peak altitude; total/annular events have paired interior contacts, while partial events have neither. Apparent solar altitudes use native topocentric coordinates and normal refraction. Search retains the existing visibility filter: at least one exterior contact must have the Sun's center above the horizon. The result's `isVisible` also considers the peak. A near-phase candidate exposes geometric events below the horizon for tests. Local iteration has no twelve-lunation cap because a fixed site's next visible event can be years away; strict ten-day phase advancement and the accepted domain bound it. Invalid observers, nonfinite or unsupported epochs, missing roots and failed progress throw. Supported lower-end starts can find a later in-domain event; required evaluations outside the domain throw.

The represented inclusive endpoint remains `physicalPeak.tt + 1/86400`. A later start within that resolution interval clamps only the presented peak/contact altitude; absolute exterior/interior contacts, kind and obscuration retain the physical candidate. Contacts remain ordered around the physical peak, and presentation can differ by up to the represented one-second endpoint. Repeated clamps cannot extend acceptance. Captured Delta T models survive search and next-event progress.

The axis-distance peak approximates the published local maximum; it is not defined as an exact diameter-fraction maximum or midpoint of central contacts. The source-bound Acapulco discriminator measures the difference and retains the unexplained 54.65-second source-peak residual. All three existing EclipseWise contact/altitude cases pass unchanged allowances after correcting their inherited UTC interpretation to the original map's UT1 labels. Independent RP1301 partial/annular local area and contact samples pass their disclosed print intervals and existing contact allowances. NASA's Washington catalog separately supplies consecutive visible-event identities. Full source assumptions, residuals, ordinary-publication rollback limits and host observations are in [the eclipse evidence README](Scripts/eclipse-data/README.md). The fourth link below completes the planned native search surface without establishing complete #93 qualification.

### Planetary transits and final qualification

`EngineTransitEvents.swift` provides internal Mercury/Venus `searchTransit` and `nextTransit`, exterior contacts I/IV, a physical peak separate from its presented time, and minimum geocentric angular center separation in arcminutes. The phase-sign helper canonicalizes inferior conjunctions on the same absolute-TT grid used for eclipses. The established 0.4-degree conjunction prefilter and one-day refinement/contact windows are retained; peak refinement minimizes angular center separation, matching the NASA catalog definition rather than the former C shadow-axis approximation. Apparent geocentric Sun/planet vectors retain native light-time and aberration handling. Spherical discs use NASA fact-sheet volumetric mean radii: Mercury 2,439.7 km, Venus 6,051.8 km and Sun 695,700 km. These are explicit engine conventions, not an assertion about the undocumented constants in the historical Meeus catalog.

External tangencies are roots of the angular-radius sum minus separation, with one-second root resolution and strict positive overlap for a transit. Results preserve the captured Delta T model. The represented physical-peak-plus-one-second endpoint is inclusive, with presentation-only clamping and no extension through repeated clamps. Next search starts 100 days later and requires progress; conjunction iteration is bounded by the accepted domain rather than an arbitrary transit count. Unsupported bodies, nonfinite/out-of-domain evaluations, absent root brackets and failed progress throw. Both accepted start endpoints are tested: the lower can find a later in-domain transit, while a search requiring evaluations beyond the upper endpoint throws.

Six NASA contact/minimum-separation cases retain the existing Mercury 642.6 s/0.2121 arcminute and Venus 546.54 s/0.6772 arcminute allowances. Their original source is geocentric Universal Time, despite legacy fixture keys ending in `UTC`; the public audit now decodes and compares UT coordinates. Complete archived catalogs establish consecutive Mercury 2003/2006, Venus 2012/2117/2125, lunar 2001 January/July/December and global solar 2024 April/October/2025 March identities. Three independent NASA Danjon-model diagrams qualify six actual lunar penumbral contacts at 120 seconds. The older OH2001 December contacts still fail that allowance and remain recorded separately. The final acceptance matrix and source assumptions are in the eclipse evidence README; global G0/1986 and local peak limitations remain unresolved. The four-link native chain ends here, with #93 still open.

## Public integration links

The first #96 integration link routes public rotation matrices, spherical/equatorial and horizon vector conversions, refraction, observer vectors/states/gravity, and the final horizontal conversion in body/star/Chiron horizon APIs through the native engine. It preserves the input `AstroTime` pair and its metadata. Time/default arithmetic, `AstroTime.siderealTime`, and position/state/ecliptic conversion remain on their existing paths until the dependent links. The operation inventory, public contract checks, inherited release-API differences and remaining acceptance are recorded in [NativeFacadeIntegration.md](Documentation/Migration/NativeFacadeIntegration.md).

The second #96 link routes geometric heliocentric/barycentric states, fixed stars and auxiliary body values through native implementations, adds the missing native Lagrange solver, and gives the public gravity facade native ownership. Public reset clears both registries during the transition. Apparent positions and exact ecliptic-state conversion remain coupled to the final time/configuration cutover. Public Chiron kept its original anchors on native gravity until #253 moved it onto `Engine.Chiron`'s table. The integration note above records the measured numerical and runtime changes.

The third link moves apparent positions and states, `Vector3D.toEcliptic()`, the exact ecliptic-state family, every event, eclipse and transit search, the generic search and light-time solvers, time construction and arithmetic, sidereal time and the Delta T default onto the engine together, and drops the C target from the shipping target's dependencies. The integration note records the public differences and the test dispositions.

## Apparent-place integration and current eclipse limitation

`Engine.ApparentPlace` composes the selected trajectories on fixed EQJ axes with a compiled DE441 solar barycentric origin. This internal apparent-place origin is distinct from the retained public `barycentricState` major-body approximation. It does not upgrade the physical accuracy of a VSOP or blended source. Solar deflection uses the finite-source `eraLd` expression and its solar-disk limiter; annual and diurnal aberration use `eraAb`. The Sun does not deflect its own image. Shapiro delay and planetary deflection remain outside this owner-scoped angular model, following Kaplan (1998). Rays inside the solar disk do not establish observable accuracy.

The ellipsoid position is differentiated with analytic second-order jets through GAST, nutation and long-term precession. This supplies the selected site trajectory's TT velocity and acceleration, with Delta T held fixed. The separate legacy public observer-state convention remains unchanged. Fixed stars retain their catalog distance and implicit catalog light time, but their apparent and topocentric routes use the same solar-deflection and relativistic observer corrections.

Eclipse shadow inputs use apparent Sun and Moon directions and distances, following the Explanatory Supplement (1992), section 8.12. Existing radii, Danjon convention, limb omissions and event objectives remain unchanged. The 2026 SVS5672 obscuration print comparison is a known source/model discrepancy tracked in #275: native 0.9624960076722118 lies below the unchanged conditional interval [0.9625,0.9635]. Its assertion remains an expected failure; this is not a NASA uncertainty bound or a satisfied port acceptance gate. Independent arithmetic with archived Horizons inputs also misses that print interval, and the physical/source cause remains unresolved. Ordinary tests separately gate direction, range, observer kinematics and fixed-input shadow/overlap arithmetic. No constant or source value is fitted to restore the print match.
