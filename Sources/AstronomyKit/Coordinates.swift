//
//  Coordinates.swift
//  AstronomyKit
//
//  Coordinate types for astronomical calculations.
//

import Foundation

// MARK: - Vector3D

/// A 3D Cartesian vector in astronomical units (AU).
public struct Vector3D: Sendable, Equatable, Hashable {
    /// The x-coordinate in AU.
    public let x: Double

    /// The y-coordinate in AU.
    public let y: Double

    /// The z-coordinate in AU.
    public let z: Double

    /// The time at which this vector is valid.
    public let time: AstroTime

    /// Creates a vector with the specified components.
    public init(x: Double, y: Double, z: Double, time: AstroTime) {
        self.x = x
        self.y = y
        self.z = z
        self.time = time
    }

    /// The magnitude (length) of the vector in AU.
    public var magnitude: Double {
        (x * x + y * y + z * z).squareRoot()
    }

    /// Returns a unit vector in the same direction.
    ///
    /// Returns `self` unchanged when the magnitude is zero, since a zero
    /// vector has no direction to normalize.
    public var normalized: Vector3D {
        let length = magnitude
        guard length > 0 else { return self }
        return Vector3D(x: x / length, y: y / length, z: z / length, time: time)
    }
}

extension Vector3D: CustomStringConvertible {
    /// A textual representation of the vector in AU.
    public var description: String {
        String(format: "(%.6f, %.6f, %.6f) AU", x, y, z)
    }
}

// MARK: - Vector Conversions

extension Vector3D {
    /// Converts this Cartesian vector to spherical coordinates.
    public func toSpherical() -> Spherical {
        guard let result = try? Engine.Spherical(engineVector(in: Engine.EQJ.self)) else {
            return Spherical(latitude: .nan, longitude: .nan, distance: .nan)
        }
        return Spherical(result)
    }

    /// Converts this equatorial J2000 vector to equatorial coordinates.
    public func toEquatorial() -> Equatorial {
        let sphere = toSpherical()
        return Equatorial(
            rightAscension: sphere.longitude / 15,
            declination: sphere.latitude,
            distance: sphere.distance,
            time: time
        )
    }

    /// Converts this equatorial J2000 vector to the true ecliptic and equinox
    /// of date, using the vector's associated time.
    ///
    /// - Throws: `AstronomyError.badTime` if the latitude, longitude, or
    ///   distance is not finite. That happens when the vector's time is far
    ///   enough from J2000 that the rotation into the ecliptic of date is not
    ///   finite, and for a vector longer than about 1e154 AU, whose distance
    ///   overflows.
    public func toEcliptic() throws -> Ecliptic {
        try Ecliptic(Engine.Ecliptic(engineVector(in: Engine.EQJ.self)))
    }

    /// Creates a Cartesian vector from spherical coordinates.
    public static func from(sphere: Spherical, at time: AstroTime) -> Vector3D {
        Vector3D(Engine.Vector<Engine.EQJ>(sphere.engineSpherical, time: time.engine), at: time)
    }

    /// Creates a Cartesian vector from horizontal coordinates.
    /// Uses the supplied altitude without refraction correction when the inverse iteration cannot converge.
    public static func from(
        horizon: Spherical,
        at time: AstroTime,
        refraction: Refraction = .normal
    ) -> Vector3D {
        Vector3D(
            Engine.Vector<Engine.HOR>(
                horizon: horizon.engineSpherical, time: time.engine, refraction: refraction
            ),
            at: time
        )
    }

    /// Calculates the angle in degrees between this vector and another.
    public func angle(to other: Vector3D) throws -> Double {
        try engineVector(in: Engine.EQJ.self).angle(to: other.engineVector(in: Engine.EQJ.self))
    }
}

extension Spherical {
    /// Creates spherical coordinates from a Cartesian vector in the horizontal frame.
    public static func fromHorizonVector(
        _ vector: Vector3D,
        refraction: Refraction = .normal
    ) -> Spherical {
        guard
            let result = try? Engine.Spherical(
                horizon: vector.engineVector(in: Engine.HOR.self), refraction: refraction)
        else {
            return Spherical(latitude: .nan, longitude: .nan, distance: .nan)
        }
        return Spherical(result)
    }
}

// MARK: - Spherical

/// Spherical coordinates (latitude, longitude, distance).
public struct Spherical: Sendable, Equatable, Hashable {
    /// The latitude angle in degrees (-90 to +90).
    public let latitude: Double

    /// The longitude angle in degrees (0 to 360).
    public let longitude: Double

    /// The distance in AU.
    public let distance: Double

    /// Creates spherical coordinates.
    public init(latitude: Double, longitude: Double, distance: Double) {
        self.latitude = latitude
        self.longitude = longitude
        self.distance = distance
    }
}

extension Spherical: CustomStringConvertible {
    /// A textual representation showing latitude, longitude, and distance.
    public var description: String {
        String(format: "lat: %.2f°, lon: %.2f°, dist: %.4f AU", latitude, longitude, distance)
    }
}

// MARK: - Equatorial

/// Equatorial coordinates (right ascension and declination).
///
/// These coordinates are commonly used in astronomy to specify the
/// position of objects on the celestial sphere.
public struct Equatorial: Sendable, Equatable, Hashable {
    /// Right ascension in sidereal hours (0 to 24).
    public let rightAscension: Double

    /// Declination in degrees (-90 to +90).
    public let declination: Double

    /// Distance from the observer in AU.
    public let distance: Double

    /// The time at which these coordinates are valid.
    public let time: AstroTime

    /// Creates equatorial coordinates.
    public init(rightAscension: Double, declination: Double, distance: Double, time: AstroTime) {
        self.rightAscension = rightAscension
        self.declination = declination
        self.distance = distance
        self.time = time
    }

    /// Right ascension formatted as hours:minutes:seconds.
    public var rightAscensionFormatted: String {
        // Round to the displayed 0.1 s precision first so that e.g. 59.96 s
        // rolls over into the next minute instead of printing "60.0s", and
        // wrap at 24 h so values rounding up to exactly 24 display as 0 h.
        let totalTenths = (rightAscension * 36_000).rounded()
            .truncatingRemainder(dividingBy: 864_000)
        let hours = Int(totalTenths / 36_000)
        let minutes = Int(totalTenths.truncatingRemainder(dividingBy: 36_000) / 600)
        let seconds = totalTenths.truncatingRemainder(dividingBy: 600) / 10
        return String(format: "%02dh %02dm %.1fs", hours, minutes, seconds)
    }

    /// Declination formatted as degrees:arcminutes:arcseconds.
    public var declinationFormatted: String {
        let sign = declination >= 0 ? "+" : "-"
        // Round to the displayed 0.1" precision first so seconds cannot
        // print as "60.0" (see rightAscensionFormatted).
        let totalTenths = (abs(declination) * 36_000).rounded()
        let degrees = Int(totalTenths / 36_000)
        let arcminutes = Int(totalTenths.truncatingRemainder(dividingBy: 36_000) / 600)
        let arcseconds = totalTenths.truncatingRemainder(dividingBy: 600) / 10
        return String(format: "%@%02d° %02d' %.1f\"", sign, degrees, arcminutes, arcseconds)
    }
}

extension Equatorial: CustomStringConvertible {
    /// A textual representation showing formatted right ascension and declination.
    public var description: String {
        "RA: \(rightAscensionFormatted), Dec: \(declinationFormatted)"
    }
}

// MARK: - Ecliptic

/// Ecliptic coordinates (latitude, longitude, distance).
public struct Ecliptic: Sendable, Equatable, Hashable {
    /// Ecliptic latitude in degrees (-90 to +90).
    public let latitude: Double

    /// Ecliptic longitude in degrees (0 to 360).
    public let longitude: Double

    /// Distance in AU.
    public let distance: Double

    /// Creates ecliptic coordinates.
    public init(latitude: Double, longitude: Double, distance: Double) {
        self.latitude = latitude
        self.longitude = longitude
        self.distance = distance
    }
}

extension Ecliptic: CustomStringConvertible {
    /// A textual representation showing ecliptic longitude and latitude.
    public var description: String {
        String(format: "λ: %.2f°, β: %.2f°", longitude, latitude)
    }
}

// MARK: - Ecliptic State

/// Geocentric ecliptic position and velocity in the true ecliptic and equinox of date.
///
/// The position fields are bit-identical to the position function each state function mirrors (see ``CelestialBody/geocentricEclipticState(at:aberration:)``, ``Sun/eclipticState(at:)``, and ``Moon/eclipticState(at:)``). Rates are analytic derivatives per Terrestrial Time day, holding Delta T fixed. Apparent Sun and body states include the retarded-time derivative, solar deflection, relativistic aberration where selected, and frame rotation rates. Geometric Moon states use DE440 from 1900 through 2130 TT and complete binary64 DE441 coefficients elsewhere, with the derivative of the 32-day blend weight. Pluto states differentiate their selected DE441 and physical-center source composition. These derivative conventions do not establish independent physical rate accuracy.
public struct EclipticState: Sendable, Equatable, Hashable {
    /// Ecliptic longitude in degrees (0 to 360).
    public let longitude: Double

    /// Ecliptic latitude in degrees (-90 to +90).
    public let latitude: Double

    /// Distance in AU.
    public let distance: Double

    /// Rate of change of longitude in degrees per TT day.
    public let longitudeRate: Double

    /// Rate of change of latitude in degrees per TT day.
    public let latitudeRate: Double

    /// Rate of change of distance in AU per TT day.
    public let distanceRate: Double

    /// The observation time.
    public let time: AstroTime

    /// Creates an ecliptic state.
    public init(
        longitude: Double,
        latitude: Double,
        distance: Double,
        longitudeRate: Double,
        latitudeRate: Double,
        distanceRate: Double,
        time: AstroTime
    ) {
        self.longitude = longitude
        self.latitude = latitude
        self.distance = distance
        self.longitudeRate = longitudeRate
        self.latitudeRate = latitudeRate
        self.distanceRate = distanceRate
        self.time = time
    }

    /// The position part of the state.
    public var ecliptic: Ecliptic {
        Ecliptic(latitude: latitude, longitude: longitude, distance: distance)
    }
}

extension EclipticState: CustomStringConvertible {
    /// A textual representation showing longitude, latitude, and longitude rate.
    public var description: String {
        String(format: "λ: %.2f°, β: %.2f°, λ̇: %.4f°/day", longitude, latitude, longitudeRate)
    }
}

// MARK: - Horizon

/// Horizontal coordinates (altitude and azimuth) for an observer on Earth.
///
/// These coordinates describe where an object appears in the local sky.
public struct Horizon: Sendable, Equatable, Hashable {
    /// Altitude above the horizon in degrees (-90 to +90).
    ///
    /// Positive values indicate the object is above the horizon.
    /// Negative values indicate it is below the horizon.
    public let altitude: Double

    /// Azimuth angle in degrees (0 to 360).
    ///
    /// Measured clockwise from north: 0° = North, 90° = East,
    /// 180° = South, 270° = West.
    public let azimuth: Double

    /// Right ascension in sidereal hours.
    public let rightAscension: Double

    /// Declination in degrees.
    public let declination: Double

    /// Creates horizon coordinates.
    public init(
        altitude: Double,
        azimuth: Double,
        rightAscension: Double = 0,
        declination: Double = 0
    ) {
        self.altitude = altitude
        self.azimuth = azimuth
        self.rightAscension = rightAscension
        self.declination = declination
    }

    /// Whether the object is currently above the horizon.
    public var isAboveHorizon: Bool {
        altitude > 0
    }

    private static let compassDirections = [
        "N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
        "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW",
    ]

    /// The cardinal/intercardinal direction name for the azimuth.
    public var compassDirection: String {
        let directions = Self.compassDirections
        guard azimuth.isFinite else { return directions[0] }
        // Normalize into [0, 360) so out-of-range azimuths cannot index
        // outside the table.
        let normalized = (azimuth.truncatingRemainder(dividingBy: 360) + 360)
            .truncatingRemainder(dividingBy: 360)
        let index = Int((normalized + 11.25).truncatingRemainder(dividingBy: 360) / 22.5)
        return directions[index]
    }
}

extension Horizon: CustomStringConvertible {
    /// A textual representation showing altitude, azimuth, and compass direction.
    public var description: String {
        let status = isAboveHorizon ? "↑" : "↓"
        return String(
            format: "%@ Alt: %.1f°, Az: %.1f° (%@)",
            status,
            altitude,
            azimuth,
            compassDirection
        )
    }
}

// MARK: - Refraction

/// Pressure and temperature for weather-dependent atmospheric refraction.
///
/// The accepted ranges are the safe numerical limits used by the PAL
/// Hohenkerk–Sinclair reference implementation. They are a computational
/// domain, not a claim that the pressure/temperature scaling is physically
/// accurate throughout the range. A combination is rejected when Meeus's
/// pressure/temperature factor exceeds 2, which keeps the forward altitude
/// mapping strictly increasing throughout its accepted altitude domain.
public struct RefractionConditions: Sendable, Equatable, Hashable {
    /// Atmospheric pressure in millibars (hPa), from 0 through 10,000.
    public let pressureMillibars: Double

    /// Ambient temperature in degrees Celsius, from -173.15 through 226.85.
    public let temperatureCelsius: Double

    /// Conditions that leave the existing Sæmundsson correction unchanged.
    public static let standard = RefractionConditions(
        validatedPressureMillibars: 1_010,
        temperatureCelsius: 10
    )

    /// Creates validated weather conditions for atmospheric refraction.
    ///
    /// - Parameters:
    ///   - pressureMillibars: Atmospheric pressure in millibars (hPa), from
    ///     0 through 10,000.
    ///   - temperatureCelsius: Ambient temperature in degrees Celsius, from
    ///     -173.15 through 226.85.
    /// - Throws: ``AstronomyError/invalidParameter`` when either value is not
    ///   finite, is outside its accepted range, or would make the
    ///   pressure/temperature factor exceed 2.
    public init(pressureMillibars: Double, temperatureCelsius: Double) throws {
        let scale =
            (pressureMillibars / 1_010)
            * (283 / (273 + temperatureCelsius))
        guard
            (0...10_000).contains(pressureMillibars),
            (-173.15...226.85).contains(temperatureCelsius),
            scale <= 2
        else {
            throw AstronomyError.invalidParameter
        }
        self.init(
            validatedPressureMillibars: pressureMillibars,
            temperatureCelsius: temperatureCelsius
        )
    }

    private init(validatedPressureMillibars: Double, temperatureCelsius: Double) {
        self.pressureMillibars = validatedPressureMillibars
        self.temperatureCelsius = temperatureCelsius
    }
}

/// Atmospheric refraction correction modes.
public enum Refraction: Sendable, Equatable, Hashable {
    /// No atmospheric refraction correction (airless).
    case none

    /// Standard atmospheric refraction correction.
    case normal

    /// JPL Horizons compatibility mode.
    case jplHorizons

    /// Sæmundsson refraction scaled for measured pressure and temperature.
    ///
    /// At ``RefractionConditions/standard`` this is identical to ``normal``.
    /// Below -1° geometric altitude it uses the same compatibility taper as
    /// ``normal``; that below-horizon extension is not ray-trace-qualified.
    case weather(RefractionConditions)

    /// Calculates the atmospheric refraction offset for a given altitude.
    ///
    /// Returns the angular adjustment in degrees to add to a geometric
    /// (airless) altitude to obtain the apparent altitude as seen by an
    /// observer through the atmosphere.
    ///
    /// - Parameter altitude: The geometric altitude in degrees above the horizon.
    /// - Returns: The signed refraction offset in degrees.
    public func refractionAngle(at altitude: Double) -> Double {
        Engine.AtmosphericRefraction.angle(self, altitude: altitude)
    }

    /// Calculates the inverse atmospheric refraction for a given apparent altitude.
    ///
    /// Given an apparent (refracted) altitude, returns the signed angular adjustment to add to recover the geometric (airless) altitude.
    ///
    /// - Parameter bentAltitude: The apparent altitude in degrees (after refraction).
    /// - Returns: The inverse refraction offset in degrees, or zero for a nonfinite or out-of-range altitude or an inversion that cannot converge.
    public func inverseRefractionAngle(at bentAltitude: Double) -> Double {
        Engine.AtmosphericRefraction.inverseAngle(self, altitude: bentAltitude)
    }
}
