# Advanced Features

N-body simulations, Lagrange points, Jupiter's moons, and more.

## Overview

Gravity simulations, Lagrange points, Jupiter's Galilean moons, rotation axes, atmospheric modeling, fixed stars, and Chiron.

## N-Body Gravity Simulation

Simulate the gravitational motion of objects in the solar system.

### Creating a Simulation

```swift
// Initial state for a small body (e.g., a comet)
let initialState = StateVector(...)  // Position and velocity

let sim = try GravitySimulation(
    origin: .sun,
    time: .now,
    initialState: initialState
)
```

### Running the Simulation

```swift
// Advance 30 days
try sim.update(to: .now.addingDays(30))

// Get the current simulation time
let currentTime = sim.currentTime()

// Get state of a major body
let jupiterState = try sim.state(of: .jupiter)
print("Jupiter position: \(jupiterState.position)")
```

### Reversing Time

```swift
// Switch direction (forward ↔ backward)
sim.swap()

// Now updates go backward in time
try sim.update(to: .now.addingDays(-30))
```

## Lagrange Points

Lagrange points are stable/semi-stable locations in a two-body gravitational system.

### Calculate Lagrange Point Position

```swift
// Sun-Earth L2 (where JWST orbits)
let l2 = try LagrangePoint.calculate(
    point: .l2,
    at: .now,
    majorBody: .sun,
    minorBody: .earth
)
print("L2 position: \(l2.position)")
print("L2 velocity: \(l2.velocity)")
```

### The Five Lagrange Points

| Point | Location | Stability |
|-------|----------|-----------|
| L1 | Between bodies | Unstable |
| L2 | Beyond smaller body | Unstable |
| L3 | Beyond larger body | Unstable |
| L4 | 60° ahead | Stable |
| L5 | 60° behind | Stable |

## Jupiter's Galilean Moons

Get positions of Io, Europa, Ganymede, and Callisto.

### Moon States

```swift
let moons = try Jupiter.moons(at: .now)

// Each moon has position and velocity relative to Jupiter
print("Io: \(moons.io.position)")
print("Europa: \(moons.europa.position)")
print("Ganymede: \(moons.ganymede.position)")
print("Callisto: \(moons.callisto.position)")
```

### Checking Moon Position

```swift
let moons = try Jupiter.moons(at: .now)

// X > 0 means east of Jupiter
if moons.io.position.x > 0 {
    print("Io is east of Jupiter")
} else {
    print("Io is west of Jupiter")
}
```

### Using as CelestialBodies

The moons are also available as celestial bodies:

```swift
for moon in CelestialBody.galileanMoons {
    let eq = try moon.equatorial(at: .now)
    print("\(moon.name): RA \(eq.rightAscension)h")
}
```

## Planetary Rotation Axes

Get the orientation of a body's rotation axis and prime meridian.

```swift
let axis = try CelestialBody.mars.rotationAxis(at: .now)

// North pole direction (J2000)
print("Pole RA: \(axis.rightAscension) hours")
print("Pole Dec: \(axis.declination)°")

// Prime meridian rotation
print("Spin angle: \(axis.spin)°")

// Unit vector toward north pole
let north = axis.north
```

This is useful for:
- Calculating solar angles on planetary surfaces
- Determining which hemisphere faces Earth
- Rendering accurate planetary graphics

## Atmospheric Modeling

Model Earth's atmosphere based on elevation.

### Atmosphere at Elevation

```swift
let atmosphere = try Atmosphere.at(elevation: 5000)  // 5000m
print("Pressure: \(atmosphere.pressure) mbar")
print("Temperature: \(atmosphere.temperature)°C")
print("Density: \(atmosphere.density)")  // Relative to sea level
```

### Observer's Atmosphere

```swift
let observer = Observer(latitude: 39.7, longitude: -104.9, height: 1600)
let atm = try observer.atmosphere
print("Local pressure: \(atm.pressure) mbar")
```

### Extreme Altitudes

```swift
// Mount Everest summit
let everest = try Atmosphere.at(elevation: 8848.86)
print("Pressure: \(Int(everest.pressure)) mbar")  // ~314 mbar (vs 1013 at sea level)
```

## Fixed Stars

> Note: `FixedStar` is an AstronomyKit addition: an immutable value type that carries its own catalog coordinates, so any number of stars can be used from any thread.

Define and track fixed stars by their J2000 catalog coordinates.

### Defining a Star

```swift
// Algol (Beta Persei) - the "Demon Star"
let algol = FixedStar(
    name: "Algol",
    rightAscension: 3.136148,  // J2000 RA in hours
    declination: 40.9556,      // J2000 Dec in degrees
    distance: 92.95            // Light-years
)

// Sirius - the brightest star
let sirius = FixedStar(
    name: "Sirius",
    rightAscension: 6.7525,
    declination: -16.7161,
    distance: 8.6
)
```

### Getting Positions

```swift
// Ecliptic longitude, true ecliptic and equinox of date (same frame as the planets)
let longitude = try algol.eclipticLongitude(at: .now)

// Position in local sky
let observer = Observer(latitude: 40.7, longitude: -74.0)
let horizon = try algol.horizon(at: .now, from: observer)

// Constellation
let constellation = try sirius.constellation(at: .now)
```

### Finding Catalog Data

J2000 coordinates can be found from:
- [SIMBAD Astronomical Database](https://simbad.cds.unistra.fr/simbad/)
- Hipparcos Catalog
- Yale Bright Star Catalog

### Catalog Proper Motion

The original initializer keeps the coordinates fixed on the J2000 mean equator. To propagate a Hipparcos or Gaia catalog entry, pass ``StarCatalogMotion``. This is an explicit frame change: coordinates with catalog motion are barycentric ICRS at the supplied TCB epoch, even when all three rates are zero.

```swift
let motion = try StarCatalogMotion(
    epochJulianYear: 2016.0,
    rightAscensionCosDeclinationMilliarcsecondsPerJulianYear: -801.5509783684709,
    declinationMilliarcsecondsPerJulianYear: 10362.394206546573,
    radialVelocityKilometersPerSecond: -110.46822
)
let barnardsStar = FixedStar(
    name: "Barnard's Star",
    rightAscension: 269.44850252543836 / 15,
    declination: 4.739420051112412,
    distance: 5.962901729416676,
    catalogMotion: motion
)
let future = try barnardsStar.equatorial(at: AstroTime(year: 2050, month: 1, day: 1))
```

The right-ascension rate is the catalog quantity `mu_alpha*cos(declination)`, in milliarcseconds per Julian year; do not divide it by cosine before constructing the value. Declination motion uses the same unit. Radial velocity is barycentric kilometers per second, positive when receding. Distance remains the geometric-parallax input, so do not apply catalog parallax a second time.

The epoch is a TCB Julian year. AstronomyKit converts each observation's TDB coordinate to TCB with the IAU 2006 linear relation before applying the rates. A nonzero right-ascension motion at either exact pole is undefined and throws ``AstronomyError/invalidParameter`` during calculation. The calculation also rejects a definition for which SOFA `pmsafe` would replace the supplied distance, a speed above half the speed of light, or a failed relativistic iteration.


## Chiron

> Note: `Chiron` is an AstronomyKit addition. Astronomy Engine has no built-in support for 2060 Chiron.

AstronomyKit computes positions for the centaur 2060 Chiron from a table of Chebyshev polynomials fitted to JPL Horizons' heliocentric vectors. Each call reads one 38-day record, so it takes the same time anywhere from 1900 to 2150.

### Getting Chiron's Position

```swift
// Ecliptic longitude
let longitude = try Chiron.eclipticLongitude(at: .now)

// Full ecliptic coordinates
let ecliptic = try Chiron.ecliptic(at: .now)

// Horizon position for an observer
let observer = Observer(latitude: 40.7, longitude: -74.0)
let horizon = try Chiron.horizon(at: .now, from: observer)
```

The heliocentric position is within 10 km of every archived Horizons vector across the span; how far depends on how Horizons was queried, from 0.13 km to 7.1 km. Calculations are limited to years 1900 through 2150; times outside that range throw ``AstronomyError/badTime``. The range is checked on the time's Terrestrial Time.

## Observer Gravity

Calculate local gravitational acceleration:

```swift
let observer = Observer(latitude: 45.0, longitude: 0.0, height: 0)
let gravity = observer.gravity  // m/s²
print("Local g: \(gravity) m/s²")
```

This accounts for:
- Latitude (Earth's oblateness)
- Altitude (distance from Earth's center)
