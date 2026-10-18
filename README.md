<p align="center">
  <img src="Sources/AstronomyKit/Documentation.docc/Resources/AstronomyKit-logo@2x.png" alt="AstronomyKit" width="256">
</p>

# AstronomyKit

A Swift library for calculating positions of the Sun, Moon, planets, and fixed stars. Predicts moon phases, eclipses, transits, and rise/set times. Accurate to ±1 arcminute, with DE-backed planet trajectories in the modern source window and retained VSOP87/NOVAS models elsewhere, validated against JPL Horizons. Runs entirely on-device.

Built on Don Cross' [Astronomy Engine](https://github.com/cosinekitty/astronomy) C library.

[![Swift 6.0](https://img.shields.io/badge/Swift-6.0-orange.svg)](https://swift.org)
[![Platform](https://img.shields.io/badge/Platform-macOS%20|%20iOS%20|%20tvOS%20|%20watchOS%20|%20Linux-blue.svg)](https://swift.org)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Documentation](https://img.shields.io/badge/Documentation-DocC-blue.svg)](https://heirloomlogic.github.io/AstronomyKit/documentation/astronomykit/)

## Features

- Positions for the Sun, Moon, planets, and Jupiter's moons
- Ecliptic position and velocity in one call: longitude, latitude, distance, and their rates
- Moon phase angles, quarters, illumination, and libration
- User-defined fixed stars from static J2000 coordinates or ICRS catalog motion
- Position for 2060 Chiron from a table fitted to JPL Horizons
- Rise, set, and culmination times
- Lunar and solar eclipse predictions
- Equinoxes and solstices
- Coordinate transforms across equatorial, ecliptic, horizon, and galactic systems
- Planetary conjunctions, oppositions, and relative longitude search
- Apsides, elongation, and transits
- Generic root-finding search for custom astronomical events
- Full `Sendable` conformance for Swift 6

## Supported dates

Positions, states, distances, and the searches built on them accept a Terrestrial Time within 4,000 Julian years of J2000, roughly the years −2000 to +6000, and throw `AstronomyError.badTime` outside it. Pluto accepts the same range. From 1800 through 2199 its position is the planet's center, from DE440 and PLU060. Outside that span it is the Pluto-system barycenter from DE441. The two differ by at most 0.1 arcsecond at the 29 sampled center dates, but the center is not independently verified outside 1800–2199. Comparisons with JPL Horizons at 41 sampled dates across the range stay within the 1 arcminute target. See "Accepted Range" in the `AstroTime` documentation.

## Planetary calculation performance

From 1900 through 2130 TT, AstronomyKit evaluates compiled binary64 DE-backed records for Mercury through Neptune, with 32-day blends to the retained model. Earth and the giant planets include their physical-center offsets; gravity uses their system-center trajectories. Outside the blends, the existing polynomial approximations and complete VSOP87B series remain. Supported dates are unchanged.

The selected DE payloads occupy 68,073,240 bytes before base64 source encoding. They follow the package’s compiled-table convention and decode one record at a time; no files are downloaded or loaded at runtime. Issue #245 tracks a possible mapped-resource representation.

## Numerical compatibility

AstronomyKit uses platform-native math. Linux is supported with the same astronomical accuracy tests. Results may differ slightly across platforms, architectures, OS releases, toolchains, and build configurations; cross-platform bit identity is not guaranteed. Event-time calculations can amplify these rounding differences.

For persisted numerical caches, include `AstronomyConfig.ephemerisVersion` and the platform, architecture, OS, and toolchain identity. Review stored positions and event times when upgrading. Numerical regression tolerances are separate from absolute astronomical accuracy limits.

## Installation

### Swift Package Manager

Add to your `Package.swift`:

```swift
dependencies: [
    .package(url: "https://github.com/heirloomlogic/AstronomyKit", from: "3.0.0")
]
```

Or in Xcode: **File → Add Package Dependencies** and enter the repository URL.

## Quick Start

```swift
import AstronomyKit

// Your location
let observer = Observer(latitude: 40.7128, longitude: -74.0060)  // NYC

// Current moon phase
let angle = try Moon.phaseAngle(at: .now)
print("\(Moon.emoji(for: angle)) \(Moon.phaseName(for: angle))")

// Next sunrise
if let sunrise = try CelestialBody.sun.riseTime(after: .now, from: observer) {
    print("Sunrise: \(sunrise.date)")
}

// Where is Mars?
let mars = try CelestialBody.mars.horizon(at: .now, from: observer)
print("Mars: \(mars.altitude)° \(mars.compassDirection)")
```

## Usage

### Time

```swift
// Current time
let now = AstroTime.now

// From components
let time = AstroTime(year: 2025, month: 6, day: 21, hour: 12)

// From Foundation Date
let time = AstroTime(Date())

// Time arithmetic
let tomorrow = now.addingDays(1)
let nextHour = now.addingHours(1)
```

### Observer Location

```swift
let seattle = Observer(latitude: 47.6062, longitude: -122.3321)
let denver = Observer(latitude: 39.7392, longitude: -104.9903, height: 1609)

// Built-in
let greenwich = Observer.greenwich
```

### Celestial Bodies

```swift
// Available bodies
let planets = CelestialBody.planets  // Mercury through Neptune
let galileanMoons = CelestialBody.galileanMoons  // Io, Europa, Ganymede, Callisto

// Body properties
print(CelestialBody.mars.name)           // "Mars"
print(CelestialBody.mars.orbitalPeriod)  // ~686 days
```

### Position Calculations

```swift
// Horizon coordinates (altitude/azimuth)
let horizon = try CelestialBody.jupiter.horizon(at: .now, from: observer)
print("Altitude: \(horizon.altitude)°")
print("Azimuth: \(horizon.azimuth)° (\(horizon.compassDirection))")

// Equatorial coordinates (RA/Dec)
let eq = try CelestialBody.saturn.equatorial(at: .now)
print("RA: \(eq.rightAscensionFormatted)")   // "02h 15m 30.2s"
print("Dec: \(eq.declinationFormatted)")     // "+12° 34' 56.7""

// Distance from Sun
let au = try CelestialBody.mars.distanceFromSun(at: .now)
```

### Position and Velocity

```swift
// Apparent geocentric ecliptic position and rates, true ecliptic and equinox of date
let mars = try CelestialBody.mars.geocentricEclipticState(at: .now)
print("Longitude: \(mars.longitude)°, rate: \(mars.longitudeRate)°/day")
if mars.longitudeRate < 0 { print("Mars is retrograde") }

// Sun and Moon
let sun = try Sun.eclipticState(at: .now)
let moon = try Moon.eclipticState(at: .now)
```

The position fields match the corresponding position call bit for bit. Rates are per Terrestrial Time day; see the DocC article on celestial positions for what they include.

### Moon Phases

```swift
// Current phase
let angle = try Moon.phaseAngle(at: .now)
print(Moon.phaseName(for: angle))     // "Waxing Gibbous"
print(Moon.emoji(for: angle))         // "🌔"
print(Moon.illumination(for: angle))  // 0.0 to 1.0

// Find specific phases (nil if not found within the search window)
if let nextFull = try Moon.searchPhase(.full, after: .now) {
    print("Next full moon: \(nextFull)")
}

// All quarters in January 2025
let quarters = try Moon.quarters(
    from: AstroTime(year: 2025, month: 1, day: 1),
    to: AstroTime(year: 2025, month: 2, day: 1)
)
```

### Fixed Stars

```swift
// Define a star from J2000 catalog coordinates
let algol = FixedStar(
    name: "Algol",
    rightAscension: 3.136148,  // Right ascension in hours
    declination: 40.9556,      // Declination in degrees
    distance: 92.95    // Distance in light-years
)

// Or opt in to ICRS catalog-epoch propagation with Gaia/Hipparcos-style values.
let barnardsStar = FixedStar(
    name: "Barnard's star",
    rightAscension: 269.44850252543836 / 15,
    declination: 4.739420051112412,
    catalogMotion: .init(
        parallax: 546.975939730948,
        properMotionRightAscension: -801.5509783684709,
        properMotionDeclination: 10362.394206546573,
        radialVelocity: -110.46822,
        epoch: 2016.0
    )
)

// Ecliptic longitude (true ecliptic and equinox of date, same frame as the planets)
let longitude = try algol.eclipticLongitude(at: .now)
print("Algol is at \(longitude)°")

// Horizon coordinates
let horizon = try algol.horizon(at: .now, from: observer)
print("Algol: \(horizon.altitude)° altitude")
```

### Chiron

```swift
// Chiron's ecliptic longitude (commonly used in astrology)
let longitude = try Chiron.eclipticLongitude(at: .now)
print("Chiron is at \(longitude)°")

// Full ecliptic coordinates
let ecliptic = try Chiron.ecliptic(at: .now)
print("Longitude: \(ecliptic.longitude)°, Latitude: \(ecliptic.latitude)°")

// Horizon position for an observer
let horizon = try Chiron.horizon(at: .now, from: observer)
print("Chiron altitude: \(horizon.altitude)°")
```

### Rise/Set Times

```swift
let sunrise = try CelestialBody.sun.riseTime(after: .now, from: observer)
let sunset = try CelestialBody.sun.setTime(after: .now, from: observer)
let moonrise = try CelestialBody.moon.riseTime(after: .now, from: observer)

// Upper culmination (transit)
let transit = try CelestialBody.sun.culmination(after: .now, from: observer)
print("Max altitude: \(transit.horizon.altitude)°")
```

### Seasons

```swift
let seasons = try Seasons.forYear(2025)
print("Spring: \(seasons.marchEquinox)")
print("Summer: \(seasons.juneSolstice)")
print("Autumn: \(seasons.septemberEquinox)")
print("Winter: \(seasons.decemberSolstice)")
```

### Eclipses

```swift
// Next lunar eclipse
let lunar = try Eclipse.searchLunar(after: .now)
print("\(lunar.kind) lunar eclipse at \(lunar.peak)")

// Next solar eclipse
let solar = try Eclipse.searchGlobalSolar(after: .now)
if solar.kind == .total, let lat = solar.latitude, let lon = solar.longitude {
    print("Total solar eclipse visible at \(lat)°, \(lon)°")
}

// All eclipses in 2025
let eclipses = try Eclipse.lunarEclipses(
    from: AstroTime(year: 2025, month: 1, day: 1),
    to: AstroTime(year: 2026, month: 1, day: 1)
)
```

### Conjunctions and Oppositions

```swift
// When is Mars next at opposition? (closest to Earth, brightest)
let opposition = try CelestialBody.mars.searchOpposition(after: .now)
print("Mars opposition: \(opposition.date)")

// When is Jupiter next in superior conjunction? (behind the Sun)
let conjunction = try CelestialBody.jupiter.searchSuperiorConjunction(after: .now)
print("Jupiter conjunction: \(conjunction.date)")

// Relative ecliptic longitude between two bodies
let angle = try CelestialBody.venus.pairLongitude(with: .mars, at: .now)
print("Venus-Mars separation: \(angle)°")
```

## API Reference

| Type | Description |
|------|-------------|
| `Apsis` | Perihelion/aphelion or perigee/apogee events |
| `AstroTime` | Time representation with UT/TT and `Date` conversion |
| `CelestialBody` | Enum of Sun, Moon, planets, and moons |
| `Chiron` | Position for 2060 Chiron from a table fitted to JPL Horizons |
| `Constellation` | Constellation identification |
| `Ecliptic` | Ecliptic longitude and latitude coordinates |
| `EclipticState` | Ecliptic position plus longitude, latitude, and distance rates |
| `Elongation` | Angular separation from the Sun |
| `Equatorial` | Right ascension and declination coordinates |
| `FixedStar` | User-defined star from static J2000 coordinates or ICRS catalog motion |
| `GlobalSolarEclipse` | Solar eclipse with peak location |
| `GravitySimulation` | N-body gravity simulation |
| `Horizon` | Altitude and azimuth for local sky position |
| `Illumination` | Visual magnitude and phase fraction |
| `LagrangePoint` | L1-L5 point calculations |
| `Libration` | Lunar libration angles and distance |
| `LocalSolarEclipse` | Solar eclipse visibility from observer |
| `LunarEclipse` | Lunar eclipse event with timing and duration |
| `LunarNode` | Ascending/descending node events |
| `MoonPhase` | Lunar phase enum (new, first quarter, full, third quarter) |
| `Observer` | Geographic location (latitude, longitude, height) |
| `RotationMatrix` | Coordinate system transformations |
| `AstroSearch` | Generic root-finding search for custom events |
| `Seasons` | Equinox and solstice times for a year |
| `StateVector` | Position and velocity state vector |
| `Sun` | Sun position and ecliptic longitude search |
| `Transit` | Mercury/Venus solar transit |

## Beyond Astronomy Engine

AstronomyKit includes features not present in the upstream C library:

| Feature | Description |
|---------|-------------|
| `Chiron` | Positions for 2060 Chiron from 1900 to 2150, read from a Chebyshev table fitted to JPL Horizons and within 10 km of every archived Horizons vector. Astronomy Engine has no built-in Chiron support. |
| `FixedStar` | Thread-safe immutable value for static J2000 stars or opt-in ICRS catalog-epoch propagation with proper motion, parallax-derived distance and radial velocity. |

All other AstronomyKit types wrap Astronomy Engine C functions directly.

## Documentation

The DocC documentation is hosted at [heirloomlogic.github.io/AstronomyKit](https://heirloomlogic.github.io/AstronomyKit/documentation/astronomykit/).

To build it locally, enable the dev tooling first (the DocC plugin is gated behind the same sentinel as the formatter; see [Toolchain Alignment](#toolchain-alignment)):

```bash
touch .dev-tooling
swift package generate-documentation --target AstronomyKit
```

Or in Xcode: **Product → Build Documentation**

## Requirements

**Runtime:** Swift 6.0+, macOS 15+ / iOS 18+ / tvOS 18+ / watchOS 11+ / Linux.

**Development:** Xcode 26.3 (Swift 6.3). The swift-format build tool plugin is pinned to a toolchain; see [Toolchain Alignment](#toolchain-alignment).

## Toolchain Alignment

The swift-format build tool plugin is pinned to a specific toolchain version. To contribute, your local toolchain must match CI:

| Context | Toolchain |
|---------|-----------|
| **Consumers** (SPM dependency) | Swift 6.0+ — any compatible toolchain |
| **Contributors** (building from source) | Xcode 26.3 / Swift 6.3 — must match CI |

The format plugin is **dev-gated** and does not ship to consumers: it only resolves when a gitignored `.dev-tooling` sentinel is present. Run `touch .dev-tooling` once before building from source to enable it (see [CONTRIBUTING](CONTRIBUTING.md#code-style)). With it enabled, if your toolchain doesn't match, `swift build` will surface lint errors from the format plugin — update Xcode or install the matching Swift toolchain before submitting a PR.

## Built With AstronomyKit

- [Fallow](https://heirloomlogic.com/fallow), a lunar fasting companion. Calculates Ekadashi and moon cycle timing.
- [Edict](https://heirloomlogic.com/edict), an electional astrology planner. Scans planetary positions to find timing windows for decisions.

## Contributing

Contributions are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## Credits

- [Astronomy Engine](https://github.com/cosinekitty/astronomy) by Don Cross, the underlying C library (see [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES))
- [ERFA](https://github.com/liberfa/erfa), derived from the IAU SOFA library, for the time and frame routines of the bundled Moon and Pluto ephemerides
- NASA/JPL DE440, DE441, PLU060, SAT441, JUP365, NEP098 and URA184 ephemerides (URA184 carries the DE442 Uranus barycenter), from which the bundled Moon, Pluto, Saturn and planet coefficients are derived, and NASA/JPL Horizons states for Chiron (see [THIRD_PARTY_NOTICES](THIRD_PARTY_NOTICES))

## License

MIT License. See [LICENSE](LICENSE) for details.
