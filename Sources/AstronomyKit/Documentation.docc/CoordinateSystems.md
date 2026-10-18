# Coordinate Systems

Transform positions between different astronomical coordinate systems.

## Overview

AstronomyKit supports several coordinate systems and provides rotation matrices for transforming between them.

## Coordinate Systems

### Equatorial J2000 (EQJ)

The standard reference frame used by most star catalogs:
- Origin: Earth's center
- Fundamental plane: Earth's equator at J2000.0 epoch
- Primary direction: Vernal equinox at J2000.0

```swift
let eq = try CelestialBody.mars.equatorial(at: .now, equatorDate: .j2000)
print("RA: \(eq.rightAscension)h, Dec: \(eq.declination)°")
```

### Equatorial of Date (EQD)

Accounts for precession of Earth's axis:
- Same as EQJ but referenced to the current date

```swift
let eq = try CelestialBody.mars.equatorial(at: .now, equatorDate: .ofDate)
```

### Ecliptic (ECL)

Referenced to the plane of Earth's orbit:
- Fundamental plane: Ecliptic (Earth's orbital plane)
- Primary direction: Vernal equinox

```swift
let lon = try CelestialBody.jupiter.eclipticLongitude(at: .now)
print("Ecliptic longitude: \(lon)°")

// Full ecliptic position
let sunPos = try Sun.position(at: .now)
print("λ: \(sunPos.longitude)°, β: \(sunPos.latitude)°")
```

Position and velocity together, in the true ecliptic and equinox of date:

```swift
let state = try CelestialBody.mars.geocentricEclipticState(at: .now)
print("λ: \(state.longitude)°, λ̇: \(state.longitudeRate)°/day")
```

See <doc:CelestialPositions> for what the rates include.

### Horizontal (HOR)

Local sky coordinates for an observer:
- Altitude: Height above the horizon
- Azimuth: Compass direction from north

```swift
let observer = Observer(latitude: 40.0, longitude: -74.0)
let hor = try CelestialBody.venus.horizon(at: .now, from: observer)
print("Alt: \(hor.altitude)°, Az: \(hor.azimuth)°")
```

### Galactic (GAL)

Referenced to the Milky Way:
- Fundamental plane: Galactic plane
- Primary direction: Galactic center
- Axes: the J2000 galactic axes of the Hipparcos Catalogue (Murray 1989), with the north galactic pole at right ascension 192.85948° and declination +27.12825°

Available via rotation matrices (see below).

## Rotation Matrices

### Creating Rotation Matrices

```swift
// Equatorial J2000 to Ecliptic
let eqjToEcl = try RotationMatrix.equatorialJ2000ToEcliptic()

// Ecliptic to Equatorial J2000
let eclToEqj = try RotationMatrix.eclipticToEquatorialJ2000()

// Equatorial J2000 to Galactic
let eqjToGal = try RotationMatrix.equatorialJ2000ToGalactic()
```

### Time-Dependent Rotations

Some transformations require a time for precession/nutation:

```swift
// Equatorial J2000 to Equatorial of Date
let time = AstroTime.now
let eqjToEqd = try RotationMatrix.equatorialJ2000ToEquatorialOfDate(at: time)

// Equatorial to Horizontal (requires time and observer)
let observer = Observer.greenwich
let eqjToHor = try RotationMatrix.equatorialJ2000ToHorizon(at: time, from: observer)
```

### Applying Rotations

Transform a vector using a rotation matrix:

```swift
let position = try CelestialBody.mars.geocentricPosition(at: .now)
let rotation = try RotationMatrix.equatorialJ2000ToEcliptic()
let eclipticPosition = position.rotated(by: rotation)
```

### Matrix Operations

```swift
// Identity (no rotation)
let identity = RotationMatrix.identity

// Inverse (reverse rotation)
let forward = try RotationMatrix.equatorialJ2000ToEcliptic()
let reverse = forward.inverse

// Combine rotations
let combined = try forward.combined(with: anotherRotation)

// Pivot around an axis
let rotated = try RotationMatrix.pivot(axis: 2, angle: 45.0)  // 45° around Z
```

## Vector Types

### Vector3D

A 3D Cartesian position vector:

```swift
let pos = try CelestialBody.jupiter.geocentricPosition(at: .now)
print("X: \(pos.x) AU")
print("Y: \(pos.y) AU")
print("Z: \(pos.z) AU")
print("Magnitude: \(pos.magnitude) AU")

// Normalize to unit vector
let direction = pos.normalized
```

### StateVector

Position and velocity together:

```swift
let state = try observer.state(at: .now)
print("Position: \(state.position)")
print("Velocity: \(state.velocity)")  // AU/day
```

## Spherical Coordinates

The `Spherical` type (latitude, longitude, distance) comes from converting a position vector:

```swift
let vector = try CelestialBody.mars.geocentricPosition(at: .now)
let spherical = vector.toSpherical()
print("Longitude: \(spherical.longitude)°")
print("Latitude: \(spherical.latitude)°")
print("Distance: \(spherical.distance) AU")
```

## Atmospheric Effects

### Refraction

Atmospheric refraction bends light, affecting apparent altitude:

```swift
// Normal refraction correction (default)
let apparent = try body.horizon(at: .now, from: observer, refraction: .normal)

// No refraction (geometric position)
let geometric = try body.horizon(at: .now, from: observer, refraction: .none)

// JPL Horizons refraction model
let jpl = try body.horizon(at: .now, from: observer, refraction: .jplHorizons)

// Measured weather: pressure in millibars (hPa), temperature in Celsius
let conditions = try RefractionConditions(pressureMillibars: 780, temperatureCelsius: -5)
let local = try body.horizon(at: .now, from: observer, refraction: .weather(conditions))
```

`Refraction.weather(_:)` multiplies the normal Sæmundsson correction by Meeus's `(P/1010) × (283/(273+T))` factor. `RefractionConditions.standard` is 1010 mbar and 10°C, so `.weather(.standard)` reproduces `.normal` exactly. Construction rejects nonfinite values, pressure outside 0...10,000 mbar, temperature outside -173.15...226.85°C, and pressure/temperature combinations whose factor exceeds 2. The last condition keeps geometric altitude plus refraction strictly increasing and makes the inverse single-valued.

The accepted input limits are computational limits. The independent comparison covers apparent altitudes from 0° through 80°, pressures from 300 through 1,100 mbar, and temperatures from -40 through 40°C against Starlink PAL's Hohenkerk–Sinclair ray trace at sea level, 50% relative humidity, 0.55 µm wavelength, 45° latitude, and a 0.0065 K/m lapse rate. Across those 180 samples, the inverse correction differs by at most 220 arcseconds at the apparent horizon, 140 arcseconds from 0.5° through 2°, and 16 arcseconds at 5° and above. These are sampled residual limits, not certified model accuracy. Below -1° geometric altitude, the weather model uses the legacy `.normal` taper to zero at the nadir; the PAL comparison does not cover that compatibility extension.

### Computing Refraction Directly

Calculate refraction angles independently of a coordinate conversion:

```swift
// How much does refraction raise an object at 5° geometric altitude?
let offset = Refraction.normal.refractionAngle(at: 5.0)
print("Refraction at 5°: +\(offset)°")

// Given an apparent altitude of 5°, what was the geometric altitude?
// The inverse is a signed offset to add to the apparent altitude.
let inverse = Refraction.normal.inverseRefractionAngle(at: 5.0)
let geometric = 5.0 + inverse  // about 4.835°
```

### Aberration

Light-time and stellar aberration affect apparent positions:

```swift
// With aberration correction (default) - what you actually see
let apparent = try body.geocentricPosition(at: .now, aberration: .corrected)

// Without correction - geometric position
let geometric = try body.geocentricPosition(at: .now, aberration: .none)
```

## Available Rotations

| From | To | Method |
|------|-----|--------|
| EQJ | ECL | `equatorialJ2000ToEcliptic()` |
| ECL | EQJ | `eclipticToEquatorialJ2000()` |
| EQJ | EQD | `equatorialJ2000ToEquatorialOfDate(at:)` |
| EQD | EQJ | `equatorialOfDateToEquatorialJ2000(at:)` |
| EQJ | HOR | `equatorialJ2000ToHorizon(at:from:)` |
| HOR | EQJ | `horizonToEquatorialJ2000(at:from:)` |
| EQJ | GAL | `equatorialJ2000ToGalactic()` |
| GAL | EQJ | `galacticToEquatorialJ2000()` |
| ECL | HOR | `eclipticToHorizon(at:from:)` |
| HOR | ECL | `horizonToEcliptic(at:from:)` |
| EQD | ECL | `equatorialOfDateToEcliptic(at:)` |
| ECL | EQD | `eclipticToEquatorialOfDate(at:)` |
| EQD | HOR | `equatorialOfDateToHorizon(at:from:)` |
| HOR | EQD | `horizonToEquatorialOfDate(at:from:)` |
| EQJ | ECT | `equatorialJ2000ToEclipticOfDate(at:)` |
| ECT | EQJ | `eclipticOfDateToEquatorialJ2000(at:)` |
| EQD | ECT | `equatorialOfDateToEclipticOfDate(at:)` |
| ECT | EQD | `eclipticOfDateToEquatorialOfDate(at:)` |
