//
//  FixedStar.swift
//  AstronomyKit
//
//  Position calculations for user-defined fixed stars.
//

/// A star defined by equatorial catalog coordinates and an optional space motion.
///
/// The original initializer stores fixed J2000 mean-equator coordinates. The catalog-motion initializer accepts barycentric ICRS coordinates at its explicit TCB epoch and propagates proper motion and radial velocity.
///
/// Unlike solar system bodies (which require orbital calculations), fixed stars
/// are defined by their J2000 mean equator coordinates and distance. The library
/// handles precession, nutation, and aberration automatically. Ecliptic results
/// are in the true ecliptic and equinox of date, like the planet positions.
///
/// ## Example
///
/// ```swift
/// let algol = FixedStar(
///     name: "Algol",
///     rightAscension: 3.136148,  // J2000 RA in hours
///     declination: 40.9556,      // J2000 Dec in degrees
///     distance: 92.95    // Light-years
/// )
///
/// let longitude = try algol.eclipticLongitude(at: .now)
/// print("Algol is at \(longitude)°")
/// ```
///
/// ## Coordinate Sources
///
/// J2000 coordinates can be found from:
/// - [SIMBAD Astronomical Database](https://simbad.cds.unistra.fr/simbad/)
/// - Hipparcos Catalog
/// - Yale Bright Star Catalog
///
/// ## Concurrency
///
/// Each calculation reads this value's immutable catalog coordinates. Concurrent calls do not share mutable star definitions.
public struct FixedStar: Sendable, Hashable {
    // MARK: - Properties

    /// The star's display name.
    public let name: String

    /// Right ascension in sidereal hours (0-24), at J2000 for a legacy value or at ``catalogMotion``'s epoch for an opt-in catalog value.
    public let rightAscension: Double

    /// Declination in degrees (-90 to +90), at J2000 for a legacy value or at ``catalogMotion``'s epoch for an opt-in catalog value.
    public let declination: Double

    /// Catalog distance in light-years. This supplies geometric parallax.
    public let distance: Double

    /// Optional catalog epoch and space motion. `nil` retains the fixed J2000 behavior.
    public let catalogMotion: StarCatalogMotion?

    // MARK: - Initialization

    /// Creates a fixed star from J2000 catalog coordinates.
    ///
    /// - Parameters:
    ///   - name: A display name for the star.
    ///   - rightAscension: Right ascension in sidereal hours (0-24).
    ///   - declination: Declination in degrees (-90 to +90).
    ///   - distance: Distance from Earth in light-years (minimum 1.0).
    public init(name: String, rightAscension: Double, declination: Double, distance: Double) {
        self.name = name
        self.rightAscension = rightAscension
        self.declination = declination
        self.distance = distance
        self.catalogMotion = nil
    }

    /// Creates a star with opt-in catalog space motion.
    ///
    /// - Parameters:
    ///   - name: A display name for the star.
    ///   - rightAscension: Barycentric ICRS right ascension in sidereal hours (0-24) at `catalogMotion`'s epoch.
    ///   - declination: Barycentric ICRS declination in degrees (-90 to +90) at `catalogMotion`'s epoch.
    ///   - distance: Barycentric catalog distance in light-years (minimum 1.0). This remains the geometric-parallax input.
    ///   - catalogMotion: Catalog epoch, proper motion, and radial velocity.
    public init(
        name: String,
        rightAscension: Double,
        declination: Double,
        distance: Double,
        catalogMotion: StarCatalogMotion
    ) {
        self.name = name
        self.rightAscension = rightAscension
        self.declination = declination
        self.distance = distance
        self.catalogMotion = catalogMotion
    }

    private var native: Engine.Star {
        Engine.Star(
            rightAscension: rightAscension, declination: declination, distance: distance, catalogMotion: catalogMotion)
    }

    // MARK: - Position Calculations

    /// Calculates the star's equatorial coordinates at a given time.
    ///
    /// Returns apparent coordinates with observer parallax, solar deflection and relativistic annual and diurnal aberration. Catalog light time is implicit in the fixed-star definition. When ``catalogMotion`` is present, its proper and radial motion are propagated before those corrections. The `.ofDate` frame also includes precession and nutation.
    ///
    /// - Parameters:
    ///   - time: The time at which to calculate the position.
    ///   - observer: The observer location. Defaults to Earth's center.
    ///   - equatorDate: The equinox reference. Defaults to J2000.
    /// - Returns: The equatorial coordinates (RA/Dec).
    /// - Throws: `AstronomyError` if the calculation fails.
    public func equatorial(
        at time: AstroTime,
        from observer: Observer = .geocentric,
        equatorDate: EquatorDate = .j2000
    ) throws -> Equatorial {
        Equatorial(try native.equatorial(at: time.engine, from: observer, equatorDate: equatorDate), at: time)
    }

    /// Calculates the star's ecliptic longitude at a given time.
    ///
    /// The longitude is measured from the true equinox of date along the
    /// true ecliptic of date, the same frame as the planet positions. See
    /// ``ecliptic(at:)``.
    ///
    /// - Parameter time: The time at which to calculate the longitude.
    /// - Returns: The ecliptic longitude in degrees (0-360).
    /// - Throws: `AstronomyError` if the calculation fails.
    public func eclipticLongitude(at time: AstroTime) throws -> Double {
        try ecliptic(at: time).longitude
    }

    /// Calculates the star's ecliptic latitude at a given time.
    ///
    /// The latitude is measured from the true ecliptic of date. See
    /// ``ecliptic(at:)``.
    ///
    /// - Parameter time: The time at which to calculate the latitude.
    /// - Returns: The ecliptic latitude in degrees (-90 to +90).
    /// - Throws: `AstronomyError` if the calculation fails.
    public func eclipticLatitude(at time: AstroTime) throws -> Double {
        try ecliptic(at: time).latitude
    }

    /// Calculates the star's full ecliptic coordinates at a given time.
    ///
    /// The coordinates are geocentric, corrected for solar deflection and relativistic annual aberration, and referred to the true ecliptic and equinox of date: the frame
    /// `Vector3D.toEcliptic()` and the geocentric planet, Sun, and Moon
    /// positions use, so a star and a planet at the same instant compare
    /// directly. They are not J2000 ecliptic coordinates, which drift from
    /// these by general precession (about 50″ a year from 2000).
    ///
    /// - Parameter time: The time at which to calculate the position.
    /// - Returns: The ecliptic coordinates (longitude, latitude, distance).
    /// - Throws: `AstronomyError` if the calculation fails.
    public func ecliptic(at time: AstroTime) throws -> Ecliptic {
        try Ecliptic(native.ecliptic(at: time.engine))
    }

    /// Calculates the star's horizontal coordinates for an observer.
    ///
    /// Returns where the star appears in the local sky (altitude and azimuth).
    ///
    /// - Parameters:
    ///   - time: The time at which to calculate the position.
    ///   - observer: The geographic observer location.
    ///   - refraction: Atmospheric refraction correction. Defaults to `.normal`.
    /// - Returns: The horizon coordinates (altitude/azimuth).
    /// - Throws: `AstronomyError` if the calculation fails.
    public func horizon(
        at time: AstroTime,
        from observer: Observer,
        refraction: Refraction = .normal
    ) throws -> Horizon {
        try observer.validate()
        return Horizon(try native.horizontal(at: time.engine, from: observer, refraction: refraction))
    }

    /// Determines which constellation contains the star.
    ///
    /// - Parameter time: The time at which to determine the constellation.
    /// - Returns: The constellation containing the star.
    /// - Throws: `AstronomyError` if the calculation fails.
    public func constellation(at time: AstroTime) throws -> Constellation {
        let eq = try equatorial(at: time)
        return try Constellation.find(rightAscension: eq.rightAscension, declination: eq.declination)
    }
}

// MARK: - CustomStringConvertible

extension FixedStar: CustomStringConvertible {
    /// The display name of the star.
    public var description: String { name }
}
