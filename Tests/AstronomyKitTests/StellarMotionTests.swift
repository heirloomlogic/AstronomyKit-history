import Foundation
import Testing

@testable import AstronomyKit

@Suite("Catalog-epoch stellar motion")
struct StellarMotionTests {
    static let barnardMotion = FixedStar.CatalogMotion(
        parallax: 546.975_939_730_948,
        properMotionRightAscension: -801.550_978_368_470_9,
        properMotionDeclination: 10_362.394_206_546_573,
        radialVelocity: -110.468_22,
        epoch: 2_016.0
    )
    static let barnard = FixedStar(
        name: "Barnard's star",
        rightAscension: 269.448_502_525_438_36 / 15,
        declination: 4.739_420_051_112_412,
        catalogMotion: barnardMotion
    )

    @Test("Catalog motion retains Gaia units and derives distance from parallax")
    func catalogValue() {
        #expect(Self.barnard.catalogMotion == Self.barnardMotion)
        #expect(Self.barnard.distance == 206_264_806.247_096_36 / Self.barnardMotion.parallax / 63_241.077_088_075_46)
    }

    @Test("SOFA starpm published validation row is reproduced")
    func sofaStarpm() throws {
        let reference = try #require(IndependentReferenceArchive.shared.fixedStars.first)
        let declinationRadians = -1.093_989_828
        let star = Engine.Star(
            rightAscension: 0.016_867_56 * Engine.hoursPerRadian,
            declination: declinationRadians * Engine.degreesPerRadian,
            motion: .init(
                parallax: 747.23,
                properMotionRightAscension: -1.783_235_16e-5 * cos(declinationRadians) / Engine.radiansPerArcsecond
                    * 1_000,
                properMotionDeclination: 2.336_024_047e-6 / Engine.radiansPerArcsecond * 1_000,
                radialVelocity: -21.6,
                epoch: 2_000 + (2_450_083.5 - 2_451_545) / 365.25
            )
        )
        let target = Engine.Time(ut: 2_191.5, tt: 2_191.5, deltaTModel: .espenakMeeus)
        let position = try Engine.Spherical(star.catalogPosition(at: target))

        #expect(abs(position.longitude * Engine.radiansPerDegree - reference.sofaStarpmRightAscensionRadians) < 1e-13)
        #expect(abs(position.latitude * Engine.radiansPerDegree - reference.sofaStarpmDeclinationRadians) < 1e-13)
    }

    @Test("Gaia DR3 Barnard's star propagates to J2000 and the Hipparcos epoch")
    func catalogEpochs() throws {
        let reference = try #require(IndependentReferenceArchive.shared.fixedStars.first)
        let engine = Engine.Star(
            rightAscension: Self.barnard.rightAscension,
            declination: Self.barnard.declination,
            motion: .init(
                parallax: Self.barnardMotion.parallax,
                properMotionRightAscension: Self.barnardMotion.properMotionRightAscension,
                properMotionDeclination: Self.barnardMotion.properMotionDeclination,
                radialVelocity: Self.barnardMotion.radialVelocity,
                epoch: Self.barnardMotion.epoch
            )
        )
        let gaia = try Engine.Spherical(
            engine.catalogPosition(at: .init(ut: 5_844, tt: 5_844, deltaTModel: .espenakMeeus)))
        let j2000 = try Engine.Spherical(engine.catalogPosition(at: .init(ut: 0, tt: 0, deltaTModel: .espenakMeeus)))
        let hipparcos = try Engine.Spherical(
            engine.catalogPosition(at: .init(ut: -3_195.9375, tt: -3_195.9375, deltaTModel: .espenakMeeus)))

        #expect(abs(gaia.longitude / 15 - Self.barnard.rightAscension) < 1e-13)
        #expect(abs(gaia.latitude - Self.barnard.declination) < 1e-13)
        #expect(abs(j2000.longitude / 15 - reference.barnardJ2000RightAscensionHours) < 1e-13)
        #expect(abs(j2000.latitude - reference.barnardJ2000DeclinationDegrees) < 1e-13)
        #expect(abs(hipparcos.longitude / 15 - reference.barnardHipparcosEpochRightAscensionHours) < 1e-13)
        #expect(abs(hipparcos.latitude - reference.barnardHipparcosEpochDeclinationDegrees) < 1e-13)
    }

    @Test("Motion feeds every public fixed-star coordinate path")
    func publicCoordinatePaths() throws {
        let time = AstroTime(tt: (2_050.0 - 2_000) * 365.25, deltaTModel: .espenakMeeus)
        let observer = Observer(latitude: 35.595, longitude: -82.5572, height: 812)
        let staticStar = FixedStar(
            name: Self.barnard.name,
            rightAscension: Self.barnard.rightAscension,
            declination: Self.barnard.declination,
            distance: Self.barnard.distance
        )

        let movingEquatorial = try Self.barnard.equatorial(at: time, from: observer, equatorDate: .j2000)
        let staticEquatorial = try staticStar.equatorial(at: time, from: observer, equatorDate: .j2000)
        #expect(abs(movingEquatorial.declination - staticEquatorial.declination) > 0.05)
        #expect(try Self.barnard.ecliptic(at: time).longitude != staticStar.ecliptic(at: time).longitude)
        #expect(
            try Self.barnard.horizon(at: time, from: observer, refraction: .none).altitude
                != staticStar.horizon(at: time, from: observer, refraction: .none).altitude)
        #expect(try Self.barnard.constellation(at: time).symbol == "Oph")
    }

    @Test("Legacy initializer has no catalog motion and preserves exact engine results")
    func legacyInitializer() throws {
        let star = FixedStar(name: "Spica", rightAscension: 13.419_883_06, declination: -11.161_319_44, distance: 250)
        let engine = Engine.Star(
            rightAscension: star.rightAscension, declination: star.declination, distance: star.distance)
        let time = AstroTime(tt: 9_496.375, ut: 9_496.374_023_437_5, deltaTModel: .espenakMeeus)

        #expect(star.catalogMotion == nil)
        #expect(
            try star.equatorial(at: time)
                == Equatorial(try engine.equatorial(at: time.engine, from: .geocentric, equatorDate: .j2000), at: time))
    }

    @Test(
        "Invalid catalog motion is rejected on use",
        arguments: [
            FixedStar.CatalogMotion(
                parallax: 0, properMotionRightAscension: 0, properMotionDeclination: 0, radialVelocity: 0, epoch: 2_000),
            FixedStar.CatalogMotion(
                parallax: .nan, properMotionRightAscension: 0, properMotionDeclination: 0, radialVelocity: 0,
                epoch: 2_000),
            FixedStar.CatalogMotion(
                parallax: 1, properMotionRightAscension: .infinity, properMotionDeclination: 0, radialVelocity: 0,
                epoch: 2_000),
            FixedStar.CatalogMotion(
                parallax: 1, properMotionRightAscension: 0, properMotionDeclination: -.infinity, radialVelocity: 0,
                epoch: 2_000),
            FixedStar.CatalogMotion(
                parallax: 1, properMotionRightAscension: 0, properMotionDeclination: 0, radialVelocity: .nan,
                epoch: 2_000),
            FixedStar.CatalogMotion(
                parallax: 1, properMotionRightAscension: 0, properMotionDeclination: 0, radialVelocity: 160_000,
                epoch: 2_000),
            FixedStar.CatalogMotion(
                parallax: 1, properMotionRightAscension: 0, properMotionDeclination: 0, radialVelocity: 0,
                epoch: .infinity),
        ]
    )
    func invalidMotion(_ motion: FixedStar.CatalogMotion) {
        let star = FixedStar(name: "Invalid", rightAscension: 0, declination: 0, catalogMotion: motion)
        #expect(throws: AstronomyError.invalidParameter) {
            _ = try star.equatorial(at: AstroTime(tt: 0))
        }
    }

    @Test("Zero motion at a catalog epoch retains the ICRS catalog direction at the pole")
    func zeroMotionBoundary() throws {
        let motion = FixedStar.CatalogMotion(
            parallax: 100, properMotionRightAscension: 0, properMotionDeclination: 0, radialVelocity: 0, epoch: 2_000)
        let moving = FixedStar(name: "Boundary", rightAscension: 0, declination: 90, catalogMotion: motion)
        let engine = Engine.Star(
            rightAscension: moving.rightAscension,
            declination: moving.declination,
            motion: .init(
                parallax: 100, properMotionRightAscension: 0, properMotionDeclination: 0, radialVelocity: 0,
                epoch: 2_000)
        )
        let position = try Engine.Spherical(engine.catalogPosition(at: .init(ut: 0, tt: 0, deltaTModel: .espenakMeeus)))

        #expect(abs(position.latitude - 90) < 1e-13)
    }

    @Test("Immutable catalog motion is repeatable across concurrent calls")
    func concurrent() async throws {
        let times = [1_991.25, 2_000, 2_016, 2_050].map { AstroTime(tt: ($0 - 2_000) * 365.25) }
        let references = try times.map { try Self.barnard.equatorial(at: $0) }

        try await withThrowingTaskGroup(of: Void.self) { group in
            for _ in 0..<16 {
                group.addTask {
                    for (time, reference) in zip(times, references) {
                        let result = try Self.barnard.equatorial(at: time)
                        #expect(result == reference)
                    }
                }
            }
            try await group.waitForAll()
        }
    }
}
