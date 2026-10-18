import Foundation
import Testing

@testable import AstronomyKit

// Scripts/solar-numerics/measure_altitude.py supplies the canonical request grid.
@Suite(.enabled(if: ProcessInfo.processInfo.environment["ASTRONOMYKIT_ALTITUDE_INPUT"] != nil))
struct NativeAltitudeProbe {
    struct Request: Codable {
        let id: String
        let value: Double
        let scale: String
        let model: String
        let observer: [Double]
    }

    struct Record: Codable {
        let request: Request
        let values: [String: String]
        let trace: [[String: String]]
        let observation: [String: String]?
        let unsupported: String?
    }

    enum InvalidRequest: Error { case observer, time, model, scale }

    static func evaluate(_ request: Request) throws -> Record {
        guard request.value.isFinite else { throw InvalidRequest.time }
        let model: DeltaTModel
        switch request.model {
        case "iersObserved": model = .iersObserved
        case "espenakMeeus": model = .espenakMeeus
        case "jplHorizons": model = .jplHorizons
        default: throw InvalidRequest.model
        }
        guard request.observer.count == 3, request.observer.allSatisfy(\.isFinite),
            abs(request.observer[0]) <= 90, abs(request.observer[2]) <= 10_000
        else { throw InvalidRequest.observer }
        let time: Engine.Time
        switch request.scale {
        case "ut": time = Engine.Time(ut: request.value, deltaTModel: model)
        case "tt": time = Engine.Time(tt: request.value, deltaTModel: model)
        case "date":
            let date = Date(timeIntervalSinceReferenceDate: request.value)
            time = Engine.Time.civil(utcDays: AstroTime.civilDays(of: date), deltaTModel: model).time
        default: throw InvalidRequest.scale
        }
        let observer = Observer(
            latitude: request.observer[0], longitude: request.observer[1], height: request.observer[2])
        let altitude = try Engine.Positions.horizontal(of: .sun, at: time, from: observer, refraction: .none)
        var trace: [[String: String]] = []
        let earth = try Engine.ApparentPlace.earthBarycentricKinematics(tt: time.tt)
        let site = try Engine.ApparentPlace.siteKinematics(observer, at: time)
        let origin = Engine.ApparentPlace.Kinematics(
            motion: earth.motion + site.motion, acceleration: earth.acceleration + site.acceleration)
        let retarded = try Engine.ApparentPlace.retardedState(atTT: time.tt, observer: origin.motion) { emission in
            let sun = try Engine.ApparentPlace.bodyMotion(.sun, tt: emission)
            let displacement = sun.value - origin.motion.value
            let numbers = ["tt": emission, "x": displacement.x, "y": displacement.y, "z": displacement.z]
            trace.append(numbers.mapValues { String($0.bitPattern, radix: 16) })
            return sun
        }
        let solarOrigin = try Engine.ApparentPlace.sunBarycentricKinematics(tt: time.tt)
        let vector = try Engine.ApparentPlace.correctedMotion(
            retarded.displacement, sunToObserver: origin.motion - solarOrigin.motion,
            beta: Engine.ApparentPlace.observerBeta(origin, atTT: time.tt), solarSource: true
        ).value
        let numbers = [
            "ut": time.ut, "tt": time.tt, "altitude": altitude.altitude,
            "azimuth": altitude.azimuth, "sunX": vector.x, "sunY": vector.y, "sunZ": vector.z,
        ]
        guard numbers.values.allSatisfy(\.isFinite) else { throw AstronomyError.badTime }
        var observed: [String: String]?
        var unsupported: String?
        do {
            let observation: SolarAltitudeObservation
            switch request.scale {
            case "ut":
                observation = try Sun.altitudeObservation(
                    universalTime: request.value, from: observer, deltaTModel: model)
            case "tt":
                observation = try Sun.altitudeObservation(
                    terrestrialTime: request.value, from: observer, deltaTModel: model)
            default:
                observation = try Sun.altitudeObservation(
                    at: Date(timeIntervalSinceReferenceDate: request.value), from: observer, deltaTModel: model)
            }
            guard observation.altitude.bitPattern == altitude.altitude.bitPattern,
                observation.time.universalTime.bitPattern == time.ut.bitPattern,
                observation.time.terrestrialTime.bitPattern == time.tt.bitPattern
            else { throw InvalidRequest.time }
            let budget = observation.errorBound
            observed = [
                "altitude": observation.altitude, "civil": budget.civilConversion,
                "scale": budget.scaleConversion, "light": budget.lightTimeTermination,
                "era": budget.earthRotationAngle, "total": budget.total,
            ]
            .mapValues { String($0.bitPattern, radix: 16) }
            if let stated = observation.statedUncertainty {
                observed?["statedDeltaT"] = String(stated.deltaTSeconds.bitPattern, radix: 16)
                observed?["statedAltitude"] = String(stated.altitudeDegrees.bitPattern, radix: 16)
            }
        } catch let error as SolarAltitudeObservation.Unsupported {
            unsupported = String(describing: error)
        }
        return Record(
            request: request, values: numbers.mapValues { String($0.bitPattern, radix: 16) }, trace: trace,
            observation: observed, unsupported: unsupported)
    }

    @Test func export() throws {
        let environment = ProcessInfo.processInfo.environment
        let input = try #require(environment["ASTRONOMYKIT_ALTITUDE_INPUT"])
        let output = try #require(environment["ASTRONOMYKIT_ALTITUDE_OUTPUT"])
        let requests = try JSONDecoder().decode([Request].self, from: Data(contentsOf: URL(fileURLWithPath: input)))
        #expect(Set(requests.map(\.id)).count == requests.count)
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        try encoder.encode(requests.map(Self.evaluate)).write(to: URL(fileURLWithPath: output), options: .atomic)
    }
}

@Suite("Native altitude measurement provenance")
struct NativeAltitudeProbeTests {
    @Test func actualLightTravelBranch() throws {
        let request = NativeAltitudeProbe.Request(
            id: "2005-flip", value: 1826.5056790659519, scale: "ut", model: "espenakMeeus", observer: [0, 0, 0])
        let record = try NativeAltitudeProbe.evaluate(request)
        #expect((1...20).contains(record.trace.count))
        let last = try #require(record.trace.last)
        func decoded(_ key: String) throws -> Double {
            let text = try #require(last[key])
            let bits = try #require(UInt64(text, radix: 16))
            return Double(bitPattern: bits)
        }
        let emission = try decoded("tt")
        let timePair = Engine.Time(ut: request.value, deltaTModel: .espenakMeeus)
        let distance = try ["x", "y", "z"].map(decoded).reduce(0) { $0 + $1 * $1 }.squareRoot()
        let elapsed =
            timePair.tt - emission
            + (Engine.TDB.offsetSeconds(tt: timePair.tt) - Engine.TDB.offsetSeconds(tt: emission))
            / Engine.secondsPerDay
        #expect(abs(elapsed - distance / Engine.speedOfLightAUPerDay) < 2e-12)
        #expect(record.values["ut"] == String(request.value.bitPattern, radix: 16))
        let time = Engine.Time(ut: request.value, deltaTModel: .espenakMeeus)
        let expected = try Engine.Positions.horizontal(
            of: .sun, at: time, from: .init(latitude: 0, longitude: 0), refraction: .none)
        #expect(record.values["altitude"] == String(expected.altitude.bitPattern, radix: 16))
    }

    @Test func malformedObserver() {
        for observer in [[0.0, 0], [91, 0, 0], [0, 0, 10_001], [0, .nan, 0]] {
            #expect(throws: NativeAltitudeProbe.InvalidRequest.observer) {
                try NativeAltitudeProbe.evaluate(
                    .init(id: "bad", value: 0, scale: "ut", model: "espenakMeeus", observer: observer))
            }
        }
    }
}
