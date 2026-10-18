import Foundation
import Testing

@testable import AstronomyKit

struct IndependentReferenceArchive: Decodable {
    let schemaVersion: Int
    let provenance: [String: Provenance]
    let fixedStars: [FixedStar]
    let constellations: [ConstellationName]
    let constellationBoundaries: [ConstellationBoundary]
    let constellationBoundaryTies: [ConstellationBoundaryTie]
    let constellationNearBoundaryStars: [ConstellationReference]
    let constellationPublishedExamples: [ConstellationReference]
    let observations: [Observation]
    let chironObservations: [Observation]
    let vectors: [Vector]
    let horizontal: [Horizontal]
    let elongations: [Elongation]
    let relativeLongitudeEvents: [RelativeLongitudeEvent]
    let maximumElongationEvents: [MaximumElongationEvent]
    let saturnApsides: [PlanetaryApsis]
    let saturnRings: [SaturnRing]
    let geocentricStates: [GeocentricState]
    let seasons: [Season]
    let lunarPhases: [LunarPhase]
    let apparentLunarPhases: [ApparentLunarPhase]
    let lunarNodes: [LunarNode]
    let lunarApsides: [Apsis]
    let earthApsides: [Apsis]
    let riseSet: [RiseSet]
    let lunarEclipses: [LunarEclipse]
    let lunarEclipseObscurations: [LunarEclipseObscuration]
    let globalSolarEclipses: [GlobalSolarEclipse]
    let localSolarEclipses: [LocalSolarEclipse]
    let transits: [Transit]

    struct Provenance: Decodable {
        let version: String?
        let serviceVersion: String?
        let frame: String
        let origin: String
        let units: String
        let timeScale: String
        let aberration: String
        let refraction: String
        let domain: String
        let license: String
        let url: String
        let recipe: String
    }

    struct FixedStar: Decodable {
        let rightAscensionHours: Double
        let declinationDegrees: Double
        let distanceLightYears: Double
        let utJulianDate: Double
        let ttJulianDate: Double
        let latitudeDegrees: Double
        let longitudeDegrees: Double
        let heightMeters: Double
        let j2000RightAscensionHours: Double
        let j2000DeclinationDegrees: Double
        let ofDateRightAscensionHours: Double
        let ofDateDeclinationDegrees: Double
        let topocentricRightAscensionHours: Double
        let topocentricDeclinationDegrees: Double
        let eclipticLongitudeDegrees: Double
        let eclipticLatitudeDegrees: Double
        let azimuthDegrees: Double
        let unrefractedAltitudeDegrees: Double
        let sampledMaximumResidualArcseconds: Double
        let sampledToleranceArcseconds: Double
        let sofaStarpmRightAscensionRadians: Double
        let sofaStarpmDeclinationRadians: Double
        let barnardJ2000RightAscensionHours: Double
        let barnardJ2000DeclinationDegrees: Double
        let barnardHipparcosEpochRightAscensionHours: Double
        let barnardHipparcosEpochDeclinationDegrees: Double
        let barnardCatalogDirectionX: Double
        let barnardCatalogDirectionY: Double
        let barnardCatalogDirectionZ: Double
        let barnardPmpxSSBDirectionX: Double
        let barnardPmpxSSBDirectionY: Double
        let barnardPmpxSSBDirectionZ: Double
        let barnardPmpxObserverDirectionX: Double
        let barnardPmpxObserverDirectionY: Double
        let barnardPmpxObserverDirectionZ: Double
    }

    struct ConstellationName: Decodable {
        let symbol: String
        let name: String
    }

    struct ConstellationBoundary: Decodable {
        let rightAscensionLowerHours: Double
        let rightAscensionUpperHours: Double
        let declinationLowerDegrees: Double
        let symbol: String
    }

    struct ConstellationBoundaryTie: Decodable {
        let boundaryIndex: Int
        let kind: String
        let rightAscensionHours: Double
        let declinationDegrees: Double
        let symbol: String
    }

    struct ConstellationReference: Decodable {
        let boundaryIndex: Int?
        let rightAscensionHoursJ2000: Double
        let declinationDegreesJ2000: Double
        let rightAscensionHoursB1875: Double
        let declinationDegreesB1875: Double
        let symbol: String
    }

    struct Observation: Decodable {
        let series: String
        let body: String
        let utc: String
        let rightAscensionDegrees: Double
        let declinationDegrees: Double
        let rightAscensionRateArcsecondsPerHour: Double
        let declinationRateArcsecondsPerHour: Double
        let apparentRangeAU: Double
        let rangeRateKmPerSecond: Double
        let eclipticLongitudeDegrees: Double
        let eclipticLatitudeDegrees: Double
        let angularToleranceArcminutes: Double
    }

    struct Vector: Decodable {
        let body: String
        let origin: String
        let julianDateTDB: Double
        let tdb: String
        let positionAU: [Double]
        let velocityAUPerDay: [Double]
        let relativeTolerance: Double?
        let sanityToleranceAU: Double?
    }

    /// A Horizons azimuth and elevation from the Asheville site, with or
    /// without Horizons' refraction.
    struct Horizontal: Decodable {
        let body: String
        let refracted: Bool
        let utc: String
        let azimuthDegrees: Double
        let elevationDegrees: Double
        let angularToleranceArcminutes: Double
    }

    /// A Horizons elongation from the Sun, with whether the body trails it
    /// (`/T`, evening) or leads it (`/L`, morning), and the apparent ecliptic
    /// of date.
    struct Elongation: Decodable {
        let body: String
        let utc: String
        let elongationDegrees: Double
        let trailsSun: Bool
        let eclipticLongitudeDegrees: Double
        let eclipticLatitudeDegrees: Double
    }

    struct RelativeLongitudeEvent: Decodable {
        let body: String
        let targetRelativeLongitudeDegrees: Double
        let direction: Int
        let startUTC: String
        let lowerJulianDateTDB: Double
        let upperJulianDateTDB: Double
        let estimatedJulianDateTDB: Double
        let lowerOffsetDegrees: Double
        let upperOffsetDegrees: Double
        let sampleResolutionSeconds: Double
        let timeScaleAllowanceSeconds: Double
        let timeToleranceSeconds: Double
    }

    struct MaximumElongationEvent: Decodable {
        let body: String
        let startUTC: String
        let lowerUTC: String
        let sampleUTC: String
        let upperUTC: String
        let sampledMaximumDegrees: Double
        let trailsSun: Bool
        let sampleResolutionSeconds: Double
        let timeToleranceSeconds: Double
        let angleToleranceDegrees: Double
    }

    struct PlanetaryApsis: Decodable {
        let body: String
        let kind: String
        let julianDateTT: Double
        let distanceAU: Double
        let sourceRangeRateAUPerDay: Double
        let sourceToleranceSeconds: Double
        let acceptanceToleranceSeconds: Double
    }

    /// Saturn's planetodetic sub-observer latitude from Earth's center, with
    /// the radii Horizons gives for it, its distances from the Sun and from
    /// Earth, and its phase angle.
    struct SaturnRing: Decodable {
        let utc: String
        let subObserverPlanetodeticLatitudeDegrees: Double
        let heliocentricDistanceAU: Double
        let geocentricDistanceAU: Double
        let phaseAngleDegrees: Double
        let equatorialRadiusKm: Double
        let polarRadiusKm: Double
    }

    /// A Horizons state of the Moon or the Earth-Moon barycenter from
    /// Earth's center, with Astronomy Engine's relative limits.
    struct GeocentricState: Decodable {
        let body: String
        let julianDateTDB: Double
        let positionAU: [Double]
        let velocityAUPerDay: [Double]
        let relativePositionTolerance: Double
        let relativeVelocityTolerance: Double
    }

    struct Season: Decodable {
        let event: String
        let utc: String
        let toleranceSeconds: Double
    }

    struct LunarPhase: Decodable {
        let phase: String
        let sourceTime: String
        let toleranceSeconds: Double
    }

    /// A JPL Horizons TT root that replaces one January 2100 USNO label as the native phase acceptance reference.
    struct ApparentLunarPhase: Decodable {
        let phase: String
        let targetDegrees: Double
        let usnoSourceTime: String
        let lowerJulianDateTT: Double
        let upperJulianDateTT: Double
        let lowerOffsetDegrees: Double
        let upperOffsetDegrees: Double
        let julianDateTT: Double
        let sampleResolutionSeconds: Double
        let toleranceSeconds: Double
    }

    struct LunarNode: Decodable {
        let kind: String
        let utc: String
        let rightAscensionHours: Double
        let declinationDegrees: Double
        let timeToleranceSeconds: Double
        let positionToleranceArcminutes: Double
    }

    struct Apsis: Decodable {
        let kind: String
        let utc: String
        let timeToleranceSeconds: Double
        let distanceAU: Double?
        let distanceKM: Double?
        let distanceToleranceAU: Double?
        let distanceToleranceKM: Double?
    }

    struct RiseSet: Decodable {
        let sourceLine: Int
        let body: String
        let longitudeDegrees: Double
        let latitudeDegrees: Double
        let utc: String
        let direction: String
        let timeToleranceSeconds: Double
    }

    struct RiseSetStream: CustomTestStringConvertible {
        let body: String
        let longitudeDegrees: Double
        let latitudeDegrees: Double
        var events: [RiseSet]

        var testDescription: String {
            "\(body) \(longitudeDegrees)/\(latitudeDegrees), \(events.count) events"
        }
    }

    var riseSetStreams: [RiseSetStream] {
        var streams: [RiseSetStream] = []
        for event in riseSet {
            if let last = streams.indices.last,
                streams[last].body == event.body,
                streams[last].longitudeDegrees == event.longitudeDegrees,
                streams[last].latitudeDegrees == event.latitudeDegrees
            {
                streams[last].events.append(event)
            } else {
                streams.append(
                    RiseSetStream(
                        body: event.body,
                        longitudeDegrees: event.longitudeDegrees,
                        latitudeDegrees: event.latitudeDegrees,
                        events: [event]))
            }
        }
        return streams
    }

    struct LunarEclipse: Decodable {
        let universalTime: String
        let kind: String
        let gammaEarthRadii: Double
        let penumbralMagnitude: Double
        let umbralMagnitude: Double
        let penumbralSemiDurationMinutes: Double?
        let partialSemiDurationMinutes: Double
        let totalSemiDurationMinutes: Double
        let toleranceSeconds: Double
        let durationToleranceMinutes: Double
    }

    struct LunarEclipseObscuration: Decodable {
        let universalTimeSearchSeed: String
        let obscuration: Double
        let roundingLowerBound: Double
        let roundingUpperBound: Double
        let peakToleranceSeconds: Double
    }

    struct GlobalSolarEclipse: Decodable {
        let terrestrialTime: String
        let kind: String
        let latitudeDegrees: Double
        let longitudeDegrees: Double
        let timeToleranceSeconds: Double
        let locationToleranceDegrees: Double
    }

    struct LocalSolarEclipse: Decodable {
        let latitudeDegrees: Double
        let longitudeDegrees: Double
        let kind: String
        let partialBeginUTC: String
        let partialBeginAltitudeDegrees: Double
        let totalBeginUTC: String?
        let totalBeginAltitudeDegrees: Double?
        let peakUTC: String
        let peakAltitudeDegrees: Double
        let totalEndUTC: String?
        let totalEndAltitudeDegrees: Double?
        let partialEndUTC: String
        let partialEndAltitudeDegrees: Double
        let timeToleranceSeconds: Double
        let altitudeToleranceDegrees: Double
    }

    struct Transit: Decodable {
        let body: String
        let startUTC: String
        let peakUTC: String
        let finishUTC: String
        let separationArcminutes: Double
        let timeToleranceSeconds: Double
        let separationToleranceArcminutes: Double
    }

    static let shared: IndependentReferenceArchive = {
        let url = URL(fileURLWithPath: #filePath)
            .deletingLastPathComponent()
            .appendingPathComponent("Fixtures/IndependentReferences/reference-fixtures.json")
        do {
            return try JSONDecoder().decode(IndependentReferenceArchive.self, from: Data(contentsOf: url))
        } catch {
            fatalError("Independent reference fixture is invalid: \(error)")
        }
    }()
}

enum IndependentReferenceDate {
    /// The engine time at `text`'s UT, under Espenak-Meeus.
    static func engine(_ text: String) -> Engine.Time {
        Engine.Time(ut: universal(text, deltaTModel: .espenakMeeus).universalTime, deltaTModel: .espenakMeeus)
    }

    /// The civil UTC instant `text` under `deltaTModel`. TT comes from the
    /// offset table whatever the model; UT follows the model's inverse.
    static func civil(_ text: String, deltaTModel: DeltaTModel) -> AstroTime {
        AstroTime(date(text), deltaTModel: deltaTModel)
    }

    static func universal(_ text: String, deltaTModel: DeltaTModel) -> AstroTime {
        AstroTime(ut: AstroTime.civilDays(of: date(text)), deltaTModel: deltaTModel)
    }

    private static func date(_ text: String) -> Date {
        let isoFormatter: ISO8601DateFormatter = {
            let formatter = ISO8601DateFormatter()
            formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
            return formatter
        }()

        let isoMinuteFormatter: ISO8601DateFormatter = {
            let formatter = ISO8601DateFormatter()
            formatter.formatOptions = [.withInternetDateTime]
            return formatter
        }()

        let minuteFormatter: DateFormatter = {
            let formatter = DateFormatter()
            formatter.calendar = Calendar(identifier: .gregorian)
            formatter.locale = Locale(identifier: "en_US_POSIX")
            formatter.timeZone = TimeZone(secondsFromGMT: 0)
            formatter.dateFormat = "yyyy-MM-dd'T'HH:mm'Z'"
            return formatter
        }()

        let horizonsFormatter: DateFormatter = {
            let formatter = DateFormatter()
            formatter.calendar = Calendar(identifier: .gregorian)
            formatter.locale = Locale(identifier: "en_US_POSIX")
            formatter.timeZone = TimeZone(secondsFromGMT: 0)
            formatter.dateFormat = "yyyy-MMM-dd HH:mm:ss.SSS"
            return formatter
        }()
        if let date = isoFormatter.date(from: text) ?? isoMinuteFormatter.date(from: text)
            ?? minuteFormatter.date(from: text) ?? horizonsFormatter.date(from: text)
        {
            return date
        }
        fatalError("invalid reference date: \(text)")
    }

    static func terrestrial(julianDateTDB: Double, deltaTModel: DeltaTModel) -> AstroTime {
        AstroTime(tt: julianDateTDB - 2_451_545.0, deltaTModel: deltaTModel)
    }

    static func terrestrialCalendar(_ text: String, deltaTModel: DeltaTModel) -> AstroTime {
        AstroTime(tt: AstroTime.civilDays(of: date(text)), deltaTModel: deltaTModel)
    }

    static func seconds(_ lhs: AstroTime, _ rhs: AstroTime) -> Double {
        abs(lhs.date.timeIntervalSince(rhs.date))
    }

    static func universalSeconds(_ lhs: AstroTime, _ rhs: AstroTime) -> Double {
        abs(lhs.universalTime - rhs.universalTime) * 86_400
    }

    static func terrestrialSeconds(_ lhs: AstroTime, _ rhs: AstroTime) -> Double {
        abs(lhs.terrestrialTime - rhs.terrestrialTime) * 86_400
    }
}

enum IndependentReferenceMath {
    static func angularSeparationArcminutes(
        raDegrees1: Double, decDegrees1: Double, raDegrees2: Double, decDegrees2: Double
    ) -> Double {
        let ra1 = raDegrees1 * .pi / 180
        let ra2 = raDegrees2 * .pi / 180
        let dec1 = decDegrees1 * .pi / 180
        let dec2 = decDegrees2 * .pi / 180
        let cosine = sin(dec1) * sin(dec2) + cos(dec1) * cos(dec2) * cos(ra1 - ra2)
        return acos(min(1, max(-1, cosine))) * 180 / .pi * 60
    }

    static func wrappedDifference(_ lhs: Double, _ rhs: Double) -> Double {
        var difference = lhs - rhs
        while difference < -180 { difference += 360 }
        while difference > 180 { difference -= 360 }
        return difference
    }

    static func relativeVectorError(actual: Vector3D, expected: [Double]) -> Double {
        let dx = actual.x - expected[0]
        let dy = actual.y - expected[1]
        let dz = actual.z - expected[2]
        let difference = (dx * dx + dy * dy + dz * dz).squareRoot()
        let magnitude =
            (expected[0] * expected[0] + expected[1] * expected[1] + expected[2] * expected[2])
            .squareRoot()
        return difference / magnitude
    }

    static func maximumComponentError(actual: Vector3D, expected: [Double]) -> Double {
        max(abs(actual.x - expected[0]), abs(actual.y - expected[1]), abs(actual.z - expected[2]))
    }

    static func sphericalDistanceDegrees(
        latitude1: Double, longitude1: Double, latitude2: Double, longitude2: Double
    ) -> Double {
        let lat1 = latitude1 * .pi / 180
        let lat2 = latitude2 * .pi / 180
        let deltaLongitude = (longitude1 - longitude2) * .pi / 180
        let cosine = sin(lat1) * sin(lat2) + cos(lat1) * cos(lat2) * cos(deltaLongitude)
        return acos(min(1, max(-1, cosine))) * 180 / .pi
    }
}
