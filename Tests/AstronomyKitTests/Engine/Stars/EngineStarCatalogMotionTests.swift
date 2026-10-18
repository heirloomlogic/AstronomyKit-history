//
//  EngineStarCatalogMotionTests.swift
//  AstronomyKit
//
//  Catalog space-motion propagation and its accepted domain.
//

import Foundation
import Testing

@testable import AstronomyKit

@Suite("Engine star catalog motion")
struct EngineStarCatalogMotionTests {
    typealias Motion = Engine.Star.CatalogMotion
    typealias Star = Engine.Star

    private var sofaInput: Star {
        get throws {
            Star(
                rightAscension: 0.016_867_56 * 12 / .pi,
                declination: -1.093_989_828 * 180 / .pi,
                distance: 206_264.806_247_096_36 / 0.747_23 / Star.astronomicalUnitsPerLightYear,
                catalogMotion: try Motion(
                    epochJulianYear: 2_000 + (2_400_000.5 + 50_083 - 2_451_545) / 365.25,
                    rightAscensionCosDeclinationMilliarcsecondsPerJulianYear: -1.783_235_16e-5
                        * cos(-1.093_989_828) * 180 / .pi * 3_600_000,
                    declinationMilliarcsecondsPerJulianYear: 2.336_024_047e-6 * 180 / .pi * 3_600_000,
                    radialVelocityKilometersPerSecond: -21.6
                )
            )
        }
    }

    private struct Archive: Decodable {
        struct Catalog: Decodable {
            struct Row: Decodable {
                let sourceID: String
                let referenceEpoch: String
                let ra: String
                let dec: String
                let parallax: String
                let pmra: String
                let pmdec: String
                let radialVelocity: String

                private enum CodingKeys: String, CodingKey {
                    case sourceID = "source_id"
                    case referenceEpoch = "ref_epoch"
                    case ra, dec, parallax, pmra, pmdec
                    case radialVelocity = "radial_velocity"
                }
            }

            let rows: [Row]
        }

        struct Reference: Decodable {
            let sourceID: String
            let targetTDBJulianYear: Double
            let rightAscensionRadians: Double
            let declinationRadians: Double
            let rightAscensionRateRadiansPerJulianYear: Double
            let declinationRateRadiansPerJulianYear: Double
            let parallaxArcseconds: Double
            let radialVelocityKilometersPerSecond: Double
        }

        struct ObserverReference: Decodable {
            let observerBarycentricICRSAstronomicalUnits: [Double]
            let oneAstronomicalUnitLightTimeSeconds: Double
            let directionICRS: [Double]
        }

        let catalog: Catalog
        let rows: [Reference]
        let observerReference: ObserverReference
    }

    private var archive: Archive {
        get throws {
            var root = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
            for _ in 0..<4 { root.deleteLastPathComponent() }
            let data = try Data(contentsOf: root.appendingPathComponent("Scripts/star-motion-data/sofa-reference.json"))
            return try JSONDecoder().decode(Archive.self, from: data)
        }
    }

    @Test("Official SOFA starpm example propagates to its published direction")
    func officialStarpmExample() throws {
        let targetJD = 2_400_000.5 + 53_736
        let time = Engine.Time(ut: targetJD - 2_451_545, tt: targetJD - 2_451_545, deltaTModel: .espenakMeeus)
        let input = try sofaInput
        let motion = try #require(input.catalogMotion)
        let position = try Engine.StarCatalogPropagation.position(
            rightAscensionHours: input.rightAscension,
            declinationDegrees: input.declination,
            distanceLightYears: input.distance,
            motion: motion,
            at: time,
            targetTCBDaysFromJ2000: targetJD - 2_451_545
        )
        let result = try Engine.Spherical(position)

        #expect(abs(result.longitude * .pi / 180 - 0.016_689_190_694_142_561_49) < 2e-15)
        #expect(abs(result.latitude * .pi / 180 - -1.093_966_454_217_127_897) < 2e-15)
    }

    @Test("Catalog ICRS axes receive the SOFA J2000 frame bias exactly once")
    func catalogFrameBias() throws {
        let motion = try Motion(
            epochJulianYear: 2_000, rightAscensionCosDeclinationMilliarcsecondsPerJulianYear: 0,
            declinationMilliarcsecondsPerJulianYear: 0, radialVelocityKilometersPerSecond: 0)
        let star = Star(rightAscension: 0, declination: 0, distance: 10, catalogMotion: motion)
        let position = try star.barycentricCatalogPosition(at: Engine.Time(ut: 0, tt: 0, deltaTModel: .espenakMeeus))
        let direction = SIMD3(position.x, position.y, position.z) / position.length

        #expect(abs(direction.x - 0.999_999_999_999_994_1) < 3e-16)
        #expect(abs(direction.y - 7.078_368_694_637_678e-8) < 2e-16)
        #expect(abs(direction.z - -8.056_214_211_620_057e-8) < 2e-16)
    }

    @Test("Observer displacement applies SOFA's proper-motion Roemer term")
    func observerRoemerTerm() throws {
        let reference = try archive.observerReference
        try #require(reference.observerBarycentricICRSAstronomicalUnits.count == 3)
        try #require(reference.directionICRS.count == 3)
        let observer = reference.observerBarycentricICRSAstronomicalUnits
        let expected = reference.directionICRS
        let motion = try Motion(
            epochJulianYear: 2_000, rightAscensionCosDeclinationMilliarcsecondsPerJulianYear: 1_000,
            declinationMilliarcsecondsPerJulianYear: 0, radialVelocityKilometersPerSecond: 0)
        let time = Engine.Time(ut: 0, tt: 0, deltaTModel: .espenakMeeus)
        let position = try Engine.StarCatalogPropagation.position(
            rightAscensionHours: 0, declinationDegrees: 0, distanceLightYears: 10, motion: motion, at: time,
            targetTCBDaysFromJ2000: 0, observerBarycentricICRS: SIMD3(observer[0], observer[1], observer[2]))
        let relative = SIMD3(position.x - observer[0], position.y - observer[1], position.z - observer[2])
        let direction = relative / (relative * relative).sum().squareRoot()

        #expect(abs(reference.oneAstronomicalUnitLightTimeSeconds - 499.004_783_836) < 1e-9)
        #expect(abs(direction.x - expected[0]) < 2e-15)
        #expect(abs(direction.y - expected[1]) < 2e-15)
        #expect(abs(direction.z - expected[2]) < 2e-15)
    }

    @Test("Every archived Gaia row matches independent SOFA propagation")
    func gaiaSOFAArchive() throws {
        let archive = try archive
        let catalog = Dictionary(uniqueKeysWithValues: archive.catalog.rows.map { ($0.sourceID, $0) })
        for reference in archive.rows {
            let input = try #require(catalog[reference.sourceID])
            let distance =
                206_264.806_247_096_36 / (try #require(Double(input.parallax)) / 1_000)
                / Star.astronomicalUnitsPerLightYear
            let motion = try Motion(
                epochJulianYear: try #require(Double(input.referenceEpoch)),
                rightAscensionCosDeclinationMilliarcsecondsPerJulianYear: try #require(Double(input.pmra)),
                declinationMilliarcsecondsPerJulianYear: try #require(Double(input.pmdec)),
                radialVelocityKilometersPerSecond: try #require(Double(input.radialVelocity))
            )
            let star = Star(
                rightAscension: try #require(Double(input.ra)) / 15,
                declination: try #require(Double(input.dec)),
                distance: distance,
                catalogMotion: motion
            )
            let targetTDB = (reference.targetTDBJulianYear - 2_000) * 365.25
            var tt = targetTDB
            for _ in 0..<3 { tt = targetTDB - Engine.TDB.offsetSeconds(tt: tt) / Engine.secondsPerDay }
            let time = Engine.Time(ut: tt, tt: tt, deltaTModel: .espenakMeeus)
            let result = try Engine.Spherical(
                Engine.StarCatalogPropagation.position(
                    rightAscensionHours: star.rightAscension,
                    declinationDegrees: star.declination,
                    distanceLightYears: star.distance,
                    motion: motion,
                    at: time
                )
            )
            #expect(abs(result.longitude * .pi / 180 - reference.rightAscensionRadians) < 3e-15)
            #expect(abs(result.latitude * .pi / 180 - reference.declinationRadians) < 3e-15)
            let actualParallax = 206_264.806_247_096_36 / result.distance
            #expect(abs(actualParallax - reference.parallaxArcseconds) < 3e-15)
        }
    }

    @Test("The exact catalog TCB epoch retains its input direction")
    func catalogEpochIdentity() throws {
        let archive = try archive
        for input in archive.catalog.rows {
            let distance =
                206_264.806_247_096_36 / (try #require(Double(input.parallax)) / 1_000)
                / Star.astronomicalUnitsPerLightYear
            let motion = try Motion(
                epochJulianYear: try #require(Double(input.referenceEpoch)),
                rightAscensionCosDeclinationMilliarcsecondsPerJulianYear: try #require(Double(input.pmra)),
                declinationMilliarcsecondsPerJulianYear: try #require(Double(input.pmdec)),
                radialVelocityKilometersPerSecond: try #require(Double(input.radialVelocity))
            )
            let star = Star(
                rightAscension: try #require(Double(input.ra)) / 15, declination: try #require(Double(input.dec)),
                distance: distance, catalogMotion: motion)
            let time = Engine.Time(ut: 0, tt: 0, deltaTModel: .espenakMeeus)
            let result = try Engine.Spherical(
                Engine.StarCatalogPropagation.position(
                    rightAscensionHours: star.rightAscension,
                    declinationDegrees: star.declination,
                    distanceLightYears: star.distance,
                    motion: motion,
                    at: time,
                    targetTCBDaysFromJ2000: (motion.epochJulianYear - 2_000) * 365.25
                )
            )
            #expect(abs(result.longitude / 15 - star.rightAscension) < 2e-14)
            #expect(abs(result.latitude - star.declination) < 2e-14)
        }
    }

    @Test("Barycentric catalog origin composes with existing observer corrections")
    func observerComposition() throws {
        let archive = try archive
        let input = try #require(archive.catalog.rows.first)
        let distance =
            206_264.806_247_096_36 / (try #require(Double(input.parallax)) / 1_000) / Star.astronomicalUnitsPerLightYear
        let motion = try Motion(
            epochJulianYear: try #require(Double(input.referenceEpoch)),
            rightAscensionCosDeclinationMilliarcsecondsPerJulianYear: try #require(Double(input.pmra)),
            declinationMilliarcsecondsPerJulianYear: try #require(Double(input.pmdec)),
            radialVelocityKilometersPerSecond: try #require(Double(input.radialVelocity))
        )
        let star = Star(
            rightAscension: try #require(Double(input.ra)) / 15, declination: try #require(Double(input.dec)),
            distance: distance, catalogMotion: motion)
        let time = Engine.Time(ut: 18_262.499, tt: 18_262.5, deltaTModel: .espenakMeeus)
        let catalog = try star.barycentricCatalogPosition(at: time)
        let earth = try Engine.ApparentPlace.earthBarycentricKinematics(tt: time.tt).motion.value
        let earthICRS = Engine.FrameBias.icrsToEqj.inverse.apply(to: earth)
        let observedICRS = try Engine.StarCatalogPropagation.position(
            rightAscensionHours: star.rightAscension,
            declinationDegrees: star.declination,
            distanceLightYears: star.distance,
            motion: motion,
            at: time,
            observerBarycentricICRS: earthICRS
        )
        let observed = Engine.FrameBias.icrsToEqj.apply(to: observedICRS)
        let uncorrected = try star.geocentricPosition(at: time, aberration: .none)
        #expect(uncorrected.x == observed.x - earth.x)
        #expect(uncorrected.y == observed.y - earth.y)
        #expect(uncorrected.z == observed.z - earth.z)
        #expect(uncorrected.y.bitPattern != (catalog.y - earth.y).bitPattern)

        let corrected = try star.geocentricPosition(at: time, aberration: .corrected)
        #expect(corrected.x.bitPattern != uncorrected.x.bitPattern)
        let geocentric = try star.equatorial(at: time, from: .geocentric, equatorDate: .j2000)
        let topocentric = try star.equatorial(
            at: time, from: Observer(latitude: 35, longitude: -105, height: 2_000), equatorDate: .j2000)
        #expect(geocentric.rightAscension.bitPattern != topocentric.rightAscension.bitPattern)
        #expect(geocentric.declination.bitPattern != topocentric.declination.bitPattern)
    }

    @Test("A zero-rate polar catalog is accepted")
    func polarZeroRate() throws {
        let motion = try Motion(
            epochJulianYear: 2_000, rightAscensionCosDeclinationMilliarcsecondsPerJulianYear: 0,
            declinationMilliarcsecondsPerJulianYear: 0, radialVelocityKilometersPerSecond: 0)
        let star = Star(rightAscension: 12, declination: -90, distance: 10, catalogMotion: motion)
        let result = try star.barycentricCatalogPosition(at: EngineStarTests.time)
        #expect(result.x.isFinite)
        #expect(result.y.isFinite)
        #expect(result.z.isFinite)
    }

    @Test("Excessive radial speed is rejected")
    func excessiveSpeed() throws {
        let motion = try Motion(
            epochJulianYear: 2_000, rightAscensionCosDeclinationMilliarcsecondsPerJulianYear: 0,
            declinationMilliarcsecondsPerJulianYear: 0, radialVelocityKilometersPerSecond: 200_000)
        let star = Star(rightAscension: 0, declination: 0, distance: 10, catalogMotion: motion)
        #expect(throws: AstronomyError.invalidParameter) {
            _ = try star.barycentricCatalogPosition(at: EngineStarTests.time)
        }
    }

    @Test("Zero rates still use the explicit barycentric catalog frame")
    func zeroMotion() throws {
        let time = Engine.Time(ut: 18_263, tt: 18_263, deltaTModel: .espenakMeeus)
        let fixed = Star(rightAscension: 13.419_883_06, declination: -11.161_319_44, distance: 250)
        let zero = Star(
            rightAscension: fixed.rightAscension,
            declination: fixed.declination,
            distance: fixed.distance,
            catalogMotion: try Motion(
                epochJulianYear: 1_991.25,
                rightAscensionCosDeclinationMilliarcsecondsPerJulianYear: 0,
                declinationMilliarcsecondsPerJulianYear: 0,
                radialVelocityKilometersPerSecond: 0
            )
        )

        let legacy = try fixed.heliocentricPosition(at: time)
        let barycentric = try zero.barycentricCatalogPosition(at: time)
        let heliocentric = try zero.heliocentricPosition(at: time)
        let catalog = try Engine.Spherical(Engine.FrameBias.icrsToEqj.inverse.apply(to: barycentric))
        #expect(abs(catalog.longitude / 15 - fixed.rightAscension) < 1e-14)
        #expect(abs(catalog.latitude - fixed.declination) < 1e-14)
        #expect(heliocentric.x.bitPattern != legacy.x.bitPattern)
    }

    @Test("Radial velocity changes the perspective component of proper motion")
    func perspectiveAcceleration() throws {
        let epoch = 2_000.0
        let transverseOnly = Star(
            rightAscension: 10,
            declination: 25,
            distance: 4,
            catalogMotion: try Motion(
                epochJulianYear: epoch,
                rightAscensionCosDeclinationMilliarcsecondsPerJulianYear: 5_000,
                declinationMilliarcsecondsPerJulianYear: -3_000,
                radialVelocityKilometersPerSecond: 0
            )
        )
        let approaching = Star(
            rightAscension: transverseOnly.rightAscension,
            declination: transverseOnly.declination,
            distance: transverseOnly.distance,
            catalogMotion: try Motion(
                epochJulianYear: epoch,
                rightAscensionCosDeclinationMilliarcsecondsPerJulianYear: 5_000,
                declinationMilliarcsecondsPerJulianYear: -3_000,
                radialVelocityKilometersPerSecond: -100
            )
        )
        let target = Engine.Time(ut: 36_525, tt: 36_525, deltaTModel: .espenakMeeus)
        let first = try Engine.Spherical(transverseOnly.barycentricCatalogPosition(at: target))
        let second = try Engine.Spherical(approaching.barycentricCatalogPosition(at: target))

        #expect(abs(first.longitude - second.longitude) > 1e-5)
        #expect(abs(first.latitude - second.latitude) > 1e-5)
    }

    @Test("A pmsafe distance override is rejected")
    func distanceOverride() throws {
        let motion = try Motion(
            epochJulianYear: 2_000,
            rightAscensionCosDeclinationMilliarcsecondsPerJulianYear: 1_000_000,
            declinationMilliarcsecondsPerJulianYear: 0,
            radialVelocityKilometersPerSecond: 0
        )
        let star = Star(rightAscension: 0, declination: 0, distance: 10, catalogMotion: motion)
        #expect(throws: AstronomyError.invalidParameter) {
            _ = try star.heliocentricPosition(at: EngineStarTests.time)
        }
    }

    @Test("Nonzero right-ascension motion at a pole is rejected")
    func poleDegeneracy() throws {
        let motion = try Motion(
            epochJulianYear: 2_016,
            rightAscensionCosDeclinationMilliarcsecondsPerJulianYear: 1,
            declinationMilliarcsecondsPerJulianYear: 0,
            radialVelocityKilometersPerSecond: 0
        )
        let star = Star(rightAscension: 0, declination: 90, distance: 10, catalogMotion: motion)
        #expect(throws: AstronomyError.invalidParameter) {
            _ = try star.heliocentricPosition(at: EngineStarTests.time)
        }
    }
}
