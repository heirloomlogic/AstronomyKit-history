//
//  FixedStar.swift
//  AstronomyKit
//
//  Position calculations for user-defined fixed stars.
//

/// A star defined by static J2000 coordinates or by ICRS catalog coordinates and space motion.
///
/// The distance initializer preserves the original static J2000 behavior. The catalog-motion initializer propagates proper motion, parallax-derived distance and radial velocity from its catalog epoch before applying observer parallax and apparent-place corrections.
///
/// The library handles precession, nutation, aberration and solar deflection automatically. Ecliptic results are in the true ecliptic and equinox of date, like the planet positions.
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
    /// Catalog measurements that propagate a star from its reference epoch.
    ///
    /// Coordinates are ICRS. Parallax and both proper-motion components are in milliarcseconds; radial velocity is in kilometers per second and is positive when the star is receding. `properMotionRightAscension` is the catalog convention μα* = dα/dt cos(δ), in milliarcseconds per Julian year. `epoch` is a Julian epoch such as 1991.25 for Hipparcos or 2016.0 for Gaia DR3. Propagation uses the requested `AstroTime` TT coordinate; treating TT as the catalog's TCB coordinate follows SOFA's documented practical convention for stellar propagation.
    public struct CatalogMotion: Sendable, Hashable {
        /// Annual parallax in milliarcseconds. It must be finite and greater than zero when used.
        public let parallax: Double

        /// Proper motion in right ascension, μα*, in milliarcseconds per Julian year.
        public let properMotionRightAscension: Double

        /// Proper motion in declination in milliarcseconds per Julian year.
        public let properMotionDeclination: Double

        /// Barycentric radial velocity in kilometers per second, positive when receding.
        public let radialVelocity: Double

        /// The Julian epoch of the catalog values, interpreted on the catalog time scale.
        public let epoch: Double

        /// Creates catalog motion using the units and frame documented by `CatalogMotion`.
        public init(
            parallax: Double, properMotionRightAscension: Double, properMotionDeclination: Double,
            radialVelocity: Double, epoch: Double
        ) {
            self.parallax = parallax
            self.properMotionRightAscension = properMotionRightAscension
            self.properMotionDeclination = properMotionDeclination
            self.radialVelocity = radialVelocity
            self.epoch = epoch
        }
    }

    // MARK: - Properties

    /// The star's display name.
    public let name: String

    /// Right ascension in sidereal hours (0-24), on the J2000 mean equator for legacy stars or ICRS at the catalog epoch for propagated stars.
    public let rightAscension: Double

    /// Declination in degrees (-90 to +90), on the J2000 mean equator for legacy stars or ICRS at the catalog epoch for propagated stars.
    public let declination: Double

    /// Catalog distance in light-years, supplied directly for legacy stars or derived from parallax for propagated stars.
    public let distance: Double

    /// Measurements used to propagate this star, or `nil` for a legacy static J2000 definition.
    public let catalogMotion: CatalogMotion?

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
        catalogMotion = nil
    }

    /// Creates a star from ICRS catalog coordinates and motion at a catalog epoch.
    ///
    /// This initializer derives `distance` from `catalogMotion.parallax`. Gaia `pmra` values can be passed directly as `properMotionRightAscension`; do not divide them by cos(declination). Hipparcos and Gaia catalog epochs are Julian epochs.
    public init(name: String, rightAscension: Double, declination: Double, catalogMotion: CatalogMotion) {
        self.name = name
        self.rightAscension = rightAscension
        self.declination = declination
        self.catalogMotion = catalogMotion
        distance = 206_264_806.247_096_36 / catalogMotion.parallax / Engine.Star.astronomicalUnitsPerLightYear
    }

    private var native: Engine.Star {
        Engine.Star(
            rightAscension: rightAscension,
            declination: declination,
            distance: distance,
            motion: catalogMotion.map {
                Engine.Star.Motion(
                    parallax: $0.parallax,
                    properMotionRightAscension: $0.properMotionRightAscension,
                    properMotionDeclination: $0.properMotionDeclination,
                    radialVelocity: $0.radialVelocity,
                    epoch: $0.epoch
                )
            }
        )
    }

    // MARK: - Position Calculations

    /// Calculates the star's equatorial coordinates at a given time.
    ///
    /// Returns apparent coordinates with observer parallax, solar deflection and relativistic annual and diurnal aberration. A star created with `catalogMotion` is first propagated from its catalog epoch. The legacy distance initializer keeps its static J2000 behavior. The `.ofDate` frame also includes precession and nutation.
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
