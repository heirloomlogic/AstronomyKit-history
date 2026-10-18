//
//  FixedStarCatalogMotionTests.swift
//  AstronomyKit
//
//  Public catalog-motion API behavior.
//

import Testing

@testable import AstronomyKit

@Suite("Fixed-star catalog motion")
struct FixedStarCatalogMotionTests {
    private let motion = try! StarCatalogMotion(
        epochJulianYear: 2_016,
        rightAscensionCosDeclinationMilliarcsecondsPerJulianYear: -801.550_978_368_470_9,
        declinationMilliarcsecondsPerJulianYear: 10_362.394_206_546_573,
        radialVelocityKilometersPerSecond: -110.468_22
    )

    @Test("Catalog motion is an explicit opt-in value")
    func valueSemantics() {
        let star = FixedStar(
            name: "Barnard's Star", rightAscension: 269.448_502_525_438_36 / 15, declination: 4.739_420_051_112_412,
            distance: 5.963, catalogMotion: motion)
        #expect(star.catalogMotion == motion)
        #expect(FixedStar(name: "Legacy", rightAscension: 1, declination: 2, distance: 3).catalogMotion == nil)
    }

    @Test("Motion participates in every public position path")
    func publicPaths() throws {
        let star = FixedStar(
            name: "Barnard's Star", rightAscension: 269.448_502_525_438_36 / 15, declination: 4.739_420_051_112_412,
            distance: 5.963, catalogMotion: motion)
        let time = AstroTime(year: 2_050, month: 1, day: 1)
        let observer = Observer(latitude: 51.5, longitude: -0.1)

        let equatorial = try star.equatorial(at: time, from: observer, equatorDate: .ofDate)
        let ecliptic = try star.ecliptic(at: time)
        let horizon = try star.horizon(at: time, from: observer, refraction: .none)
        let constellation = try star.constellation(at: time)
        #expect(equatorial.rightAscension.isFinite)
        #expect(ecliptic.longitude.isFinite)
        #expect(horizon.altitude.isFinite)
        #expect(!constellation.name.isEmpty)
    }

    @Test("Invalid public motion values are rejected")
    func invalidMotionValues() {
        #expect(throws: AstronomyError.invalidParameter) {
            _ = try StarCatalogMotion(
                epochJulianYear: .nan, rightAscensionCosDeclinationMilliarcsecondsPerJulianYear: 0,
                declinationMilliarcsecondsPerJulianYear: 0, radialVelocityKilometersPerSecond: 0)
        }
        #expect(throws: AstronomyError.invalidParameter) {
            _ = try StarCatalogMotion(
                epochJulianYear: 2_000, rightAscensionCosDeclinationMilliarcsecondsPerJulianYear: .infinity,
                declinationMilliarcsecondsPerJulianYear: 0, radialVelocityKilometersPerSecond: 0)
        }
        #expect(throws: AstronomyError.invalidParameter) {
            _ = try StarCatalogMotion(
                epochJulianYear: 2_000, rightAscensionCosDeclinationMilliarcsecondsPerJulianYear: 0,
                declinationMilliarcsecondsPerJulianYear: -.infinity, radialVelocityKilometersPerSecond: 0)
        }
        #expect(throws: AstronomyError.invalidParameter) {
            _ = try StarCatalogMotion(
                epochJulianYear: 2_000, rightAscensionCosDeclinationMilliarcsecondsPerJulianYear: 0,
                declinationMilliarcsecondsPerJulianYear: 0, radialVelocityKilometersPerSecond: .nan)
        }
        #expect(throws: AstronomyError.invalidParameter) {
            _ = try StarCatalogMotion(
                epochJulianYear: Double(-2_000).nextDown, rightAscensionCosDeclinationMilliarcsecondsPerJulianYear: 0,
                declinationMilliarcsecondsPerJulianYear: 0, radialVelocityKilometersPerSecond: 0)
        }
        #expect(throws: AstronomyError.invalidParameter) {
            _ = try StarCatalogMotion(
                epochJulianYear: 6_000.nextUp, rightAscensionCosDeclinationMilliarcsecondsPerJulianYear: 0,
                declinationMilliarcsecondsPerJulianYear: 0, radialVelocityKilometersPerSecond: 0)
        }
    }

    @Test("Catalog epoch boundaries are accepted")
    func epochBoundaries() throws {
        _ = try StarCatalogMotion(
            epochJulianYear: -2_000, rightAscensionCosDeclinationMilliarcsecondsPerJulianYear: 0,
            declinationMilliarcsecondsPerJulianYear: 0, radialVelocityKilometersPerSecond: 0)
        _ = try StarCatalogMotion(
            epochJulianYear: 6_000, rightAscensionCosDeclinationMilliarcsecondsPerJulianYear: 0,
            declinationMilliarcsecondsPerJulianYear: 0, radialVelocityKilometersPerSecond: 0)
    }
}
