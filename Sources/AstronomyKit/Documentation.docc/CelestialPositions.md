# Celestial Positions

Calculate the positions of celestial bodies in various coordinate systems.

## Overview

AstronomyKit can calculate positions for the Sun, Moon, planets, Jupiter's moons, and fixed stars. Positions can be expressed in multiple coordinate systems.

## Celestial Bodies

### Available Bodies

```swift
// Major bodies
let sun = CelestialBody.sun
let moon = CelestialBody.moon
let mars = CelestialBody.mars

// All planets (Mercury through Neptune)
for planet in CelestialBody.planets {
    print(planet.name)
}

// Jupiter's Galilean moons
for moon in CelestialBody.galileanMoons {
    print(moon.name)  // Io, Europa, Ganymede, Callisto
}
```

### Body Properties

```swift
let mars = CelestialBody.mars

print(mars.name)           // "Mars"
print(mars.orbitalPeriod)  // ~686 days
print(mars.massProduct)    // Mass × G in AU³/day²
print(mars.isPlanet)       // true
print(mars.isNakedEyeVisible)  // true
```

### Looking Up Bodies by Name

```swift
if let body = CelestialBody(name: "Jupiter") {
    print("Found: \(body)")
}
```

## Horizon Coordinates

Where does a body appear in your local sky?

```swift
let observer = Observer(latitude: 40.7128, longitude: -74.0060)
let mars = try CelestialBody.mars.horizon(at: .now, from: observer)

print("Altitude: \(mars.altitude)°")     // Height above horizon
print("Azimuth: \(mars.azimuth)°")       // Compass bearing
print("Direction: \(mars.compassDirection)")  // N, NE, E, SE, etc.

if mars.isAboveHorizon {
    print("Mars is visible!")
}
```

## Equatorial Coordinates

Right ascension and declination on the celestial sphere:

```swift
let eq = try CelestialBody.saturn.equatorial(at: .now)

print("RA: \(eq.rightAscension) hours")
print("Dec: \(eq.declination)°")
print("Distance: \(eq.distance) AU")

// Formatted output
print(eq.rightAscensionFormatted)   // "02h 15m 30.2s"
print(eq.declinationFormatted)      // "+12° 34' 56.7""
```

### Equator Date Options

Choose the reference equinox:

```swift
// J2000 coordinates (default) - standard reference epoch
let j2000 = try body.equatorial(at: .now, equatorDate: .j2000)

// Coordinates of the observation date - accounts for precession
let ofDate = try body.equatorial(at: .now, equatorDate: .ofDate)
```

## Ecliptic Coordinates

Position relative to the ecliptic plane:

```swift
let longitude = try CelestialBody.venus.eclipticLongitude(at: .now)
print("Venus ecliptic longitude: \(longitude)°")

// Sun's full ecliptic position
let sunPos = try Sun.position(at: .now)
print("Sun: λ=\(sunPos.longitude)°, β=\(sunPos.latitude)°")
```

### Ecliptic Position and Velocity

When you need the rate of motion as well as the position, ask for the state in one call instead of differencing positions:

```swift
// Apparent geocentric position and velocity, true ecliptic and equinox of date
let mars = try CelestialBody.mars.geocentricEclipticState(at: .now)
print("Mars: λ=\(mars.longitude)°, λ̇=\(mars.longitudeRate)°/day")
if mars.longitudeRate < 0 { print("Mars is retrograde") }

// Sun and Moon through their dedicated ephemerides
let sun = try Sun.eclipticState(at: .now)
let moon = try Moon.eclipticState(at: .now)
```

The position fields are bit-identical to the position call each state mirrors: `geocentricPosition(at:aberration:).toEcliptic()`, `Sun.position(at:)`, and `Moon.ecliptic(at:)`. Rates are analytic derivatives per Terrestrial Time day, holding Delta T fixed. Apparent Sun and body states include retarded-time, solar-deflection and relativistic-aberration derivatives where selected, plus frame rotation rates. Geometric Moon states use DE440 in the central 1900–2130 TT interval and complete binary64 DE441 coefficients outside it; the 32-day exterior blends include the derivative of the weight. Pluto states differentiate their selected DE441 and physical-center source composition. These conventions describe implementation derivatives, not independent physical rate accuracy.

## Position Vectors

Cartesian coordinates in 3D space:

```swift
// Geocentric (from Earth's center)
let geo = try CelestialBody.jupiter.geocentricPosition(at: .now)
print("Distance from Earth: \(geo.magnitude) AU")

// Heliocentric (from Sun's center)
let helio = try CelestialBody.mars.heliocentricPosition(at: .now)
print("Distance from Sun: \(helio.magnitude) AU")
```

## Distance Calculations

```swift
// Distance from Sun
let auFromSun = try CelestialBody.mars.distanceFromSun(at: .now)
print("Mars is \(auFromSun) AU from the Sun")

// Angular separation from Sun
let angle = try CelestialBody.venus.angleFromSun(at: .now)
print("Venus is \(angle)° from the Sun")
```

## Constellation Identification

Find which constellation contains a body:

```swift
let constellation = try CelestialBody.mars.constellation(at: .now)
print("\(constellation.symbol) - \(constellation.name)")
// Output: "Tau - Taurus"

// Or from raw coordinates
let orion = try Constellation.find(rightAscension: 5.9195, declination: 7.4071)
print(orion.name)  // "Orion"
```

## Fixed Stars

Define and track fixed stars by their J2000 catalog coordinates using ``FixedStar``:

```swift
// Define Algol (Beta Persei)
let algol = FixedStar(
    name: "Algol",
    rightAscension: 3.136148,  // J2000 RA in hours
    declination: 40.9556,      // J2000 Dec in degrees
    distance: 92.95    // Light-years
)

// Get ecliptic longitude (true ecliptic and equinox of date, same frame as the planets)
let longitude = try algol.eclipticLongitude(at: .now)

// Get position in local sky
let observer = Observer(latitude: 40.7, longitude: -74.0)
let horizon = try algol.horizon(at: .now, from: observer)
```

J2000 coordinates can be found from star catalogs like SIMBAD, Hipparcos, or the Yale Bright Star Catalog. Entries with an epoch, proper motion, and radial velocity can opt into propagation with ``StarCatalogMotion``; see <doc:AdvancedFeatures> for units, frame, time-scale, and validation details. The legacy initializer remains a fixed J2000 value.

## Aberration Correction

Control light-time and aberration corrections:

```swift
// With correction (default) - apparent position
let apparent = try body.geocentricPosition(at: .now, aberration: .corrected)

// Without correction - geometric position
let geometric = try body.geocentricPosition(at: .now, aberration: .none)
```

## Refraction Correction

Atmospheric refraction affects horizon coordinates:

```swift
// Normal refraction (default)
let normal = try body.horizon(at: .now, from: observer, refraction: .normal)

// No refraction
let geometric = try body.horizon(at: .now, from: observer, refraction: .none)

// JPL Horizons model
let jpl = try body.horizon(at: .now, from: observer, refraction: .jplHorizons)
```
