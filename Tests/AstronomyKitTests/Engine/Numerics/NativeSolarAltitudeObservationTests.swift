import Foundation
import Testing

@testable import AstronomyKit

@Suite("Native solar-altitude certificate integration")
struct NativeSolarAltitudeObservationTests {
    @Test("The observation records native model time and ordinary native Sun altitude")
    func nativeTimeAndAltitude() throws {
        let ut = 1826.5056790659519
        let observer = Observer(latitude: -33.87, longitude: 151.21, height: -10000)
        let native = Engine.Time(ut: ut, deltaTModel: .espenakMeeus)
        let expected = try Engine.Positions.horizontal(of: .sun, at: native, from: observer, refraction: .none)
        let observation = try Sun.altitudeObservation(universalTime: ut, from: observer, deltaTModel: .espenakMeeus)
        #expect(observation.time.terrestrialTime == native.tt)
        #expect(observation.time.universalTime == native.ut)
        #expect(observation.altitude.bitPattern == expected.altitude.bitPattern)
        let ordinary = try CelestialBody.sun.horizon(at: observation.time, from: observer, refraction: .none)
        #expect(observation.altitude.bitPattern == ordinary.altitude.bitPattern)
        // Extended-precision same-model value at the recorded time pair;
        // retained as a regression sample, not a continuous error proof.
        let sample = try EngineApparentIntegrationTests.IntegrationReference.load().altitudeSample
        #expect(sample.ut == native.ut && sample.tt == native.tt)
        let reference = try #require(Double(sample.altitude))
        #expect(abs(observation.altitude - reference) <= observation.errorBound.total)
        #expect(observation.errorBound.lightTimeTermination == SolarAltitudeBounds.lightTimeDegrees)
    }
    @Test(
        "Every reference construction and named model repeats the ordinary geometric altitude",
        arguments: [DeltaTModel.iersObserved, .espenakMeeus, .jplHorizons])
    func referenceIdentity(model: DeltaTModel) throws {
        let observer = Observer(latitude: 89.999, longitude: 180, height: 10000)
        let observations = [
            try Sun.altitudeObservation(universalTime: 9000.25, from: observer, deltaTModel: model),
            try Sun.altitudeObservation(terrestrialTime: 9000.25, from: observer, deltaTModel: model),
            try Sun.altitudeObservation(
                at: Date(timeIntervalSinceReferenceDate: 750_000_000), from: observer, deltaTModel: model),
            try Sun.altitudeObservation(
                at: Date(timeIntervalSinceReferenceDate: -1_700_000_000), from: observer, deltaTModel: model),
        ]
        #expect(Set(observations.map(\.reference)).count == 4)
        for observation in observations {
            #expect(observation.deltaTModel == model)
            #expect(observation.time.deltaTModel == model)
            let repeated = try CelestialBody.sun.horizon(at: observation.time, from: observer, refraction: .none)
            #expect(repeated.altitude.bitPattern == observation.altitude.bitPattern)
        }
    }

    @Test("Neither emission trajectory evaluates the 2050 Delta T step")
    func modelSpecificStep() throws {
        let observer = Observer(latitude: 0, longitude: 0)
        let em = try Sun.altitudeObservation(
            universalTime: 18262.505679351943, from: observer, deltaTModel: .espenakMeeus)
        let jpl = try Sun.altitudeObservation(
            universalTime: 18262.505679351943, from: observer, deltaTModel: .jplHorizons)
        #expect(em.errorBound.lightTimeTermination == SolarAltitudeBounds.lightTimeDegrees)
        #expect(jpl.errorBound.lightTimeTermination == SolarAltitudeBounds.lightTimeDegrees)
    }

    @Test(
        "Adjacent binary64 TT values at every exact model-gap endpoint are classified",
        arguments: [DeltaTModel.espenakMeeus, .jplHorizons])
    func gapEndpoints(model: DeltaTModel) throws {
        let observer = Observer(latitude: 0, longitude: 0)
        for gap in SolarAltitudeBounds.positiveGaps {
            for tt in [gap.lower, gap.upper.nextDown] {
                #expect(throws: SolarAltitudeObservation.Unsupported.terrestrialTimeInDeltaTGap) {
                    try Sun.altitudeObservation(terrestrialTime: tt, from: observer, deltaTModel: model)
                }
            }
            for tt in [gap.lower.nextDown, gap.upper] {
                _ = try Sun.altitudeObservation(terrestrialTime: tt, from: observer, deltaTModel: model)
            }
        }
    }

    @Test("Adjacent values at polynomial seams preserve paired-altitude identity")
    func polynomialSeams() throws {
        let observer = Observer(latitude: -90, longitude: -180, height: -10000)
        for seam in [-36516.5, -4.5, 36883.5] {
            for tt in [seam.nextDown, seam, seam.nextUp] {
                let observation = try Sun.altitudeObservation(
                    terrestrialTime: tt, from: observer, deltaTModel: .espenakMeeus)
                let repeated = try CelestialBody.sun.horizon(at: observation.time, from: observer, refraction: .none)
                #expect(repeated.altitude.bitPattern == observation.altitude.bitPattern)
            }
        }
    }
}
