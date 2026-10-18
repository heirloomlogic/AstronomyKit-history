//
//  StarCatalogMotion.swift
//  AstronomyKit
//
//  Opt-in catalog epoch and space-motion inputs for fixed stars.
//

/// Catalog epoch and space-motion terms for a ``FixedStar``.
///
/// Right-ascension motion uses the Hipparcos and Gaia `mu_alpha*cos(delta)` convention, not the coordinate-angle rate `dRA/dt`. Both proper-motion components are milliarcseconds per Julian year. Radial velocity is barycentric kilometers per second, positive when the source is receding.
///
/// The epoch is a TCB Julian year, where J2000.0 is Julian Date 2451545.0 TCB and one Julian year is exactly 365.25 days. Propagation converts the observation's TDB coordinate to TCB with the IAU 2006 linear transformation before applying the catalog rates.
public struct StarCatalogMotion: Sendable, Equatable, Hashable {
    /// Catalog reference epoch as a Julian year.
    public let epochJulianYear: Double

    /// `mu_alpha*cos(delta)` in milliarcseconds per Julian year.
    public let rightAscensionCosDeclinationMilliarcsecondsPerJulianYear: Double

    /// Declination proper motion in milliarcseconds per Julian year.
    public let declinationMilliarcsecondsPerJulianYear: Double

    /// Barycentric radial velocity in kilometers per second, positive when receding.
    public let radialVelocityKilometersPerSecond: Double

    /// Creates catalog space-motion terms.
    ///
    /// - Throws: ``AstronomyError/invalidParameter`` if a value is not finite or the epoch lies outside the engine's accepted years -2000 through 6000.
    public init(
        epochJulianYear: Double,
        rightAscensionCosDeclinationMilliarcsecondsPerJulianYear: Double,
        declinationMilliarcsecondsPerJulianYear: Double,
        radialVelocityKilometersPerSecond: Double
    ) throws {
        guard
            (-2_000...6_000).contains(epochJulianYear),
            rightAscensionCosDeclinationMilliarcsecondsPerJulianYear.isFinite,
            declinationMilliarcsecondsPerJulianYear.isFinite,
            radialVelocityKilometersPerSecond.isFinite
        else { throw AstronomyError.invalidParameter }
        self.epochJulianYear = epochJulianYear
        self.rightAscensionCosDeclinationMilliarcsecondsPerJulianYear =
            rightAscensionCosDeclinationMilliarcsecondsPerJulianYear
        self.declinationMilliarcsecondsPerJulianYear = declinationMilliarcsecondsPerJulianYear
        self.radialVelocityKilometersPerSecond = radialVelocityKilometersPerSecond
    }
}
