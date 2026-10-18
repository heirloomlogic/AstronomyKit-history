//
//  DeltaTIersObservedTests.swift
//  AstronomyKit
//
//  Checks the default observed Delta T model against the raw IERS records it
//  was generated from, parsed here independently of the generator, and runs
//  rise and set through the civil path against JPL Horizons.
//

import Foundation
import Testing

@testable import AstronomyKit

/// Raw IERS rows parsed from the pinned files in `Scripts/deltat-data`.
private enum IERSRecords {
    struct Row {
        /// Modified Julian Date of the UTC sample.
        let mjd: Double
        /// UT1 − UTC in seconds.
        let ut1MinusUTC: Double
    }

    static let directory = URL(fileURLWithPath: #filePath)
        .deletingLastPathComponent()
        .deletingLastPathComponent()
        .deletingLastPathComponent()
        .appendingPathComponent("Scripts/deltat-data")

    static func lines(_ name: String) throws -> [Substring] {
        let text = try String(contentsOf: directory.appendingPathComponent(name), encoding: .utf8)
        return text.split(separator: "\n", omittingEmptySubsequences: true)
    }

    /// IERS EOP 20 C04: whitespace-separated, MJD in field 5, UT1 − UTC in field 8.
    static func c04(_ name: String) throws -> [Row] {
        try lines(name).compactMap { line in
            guard !line.hasPrefix("#") else { return nil }
            let fields = line.split(separator: " ", omittingEmptySubsequences: true)
            guard fields.count == 21, let mjd = Double(fields[4]), let dut = Double(fields[7]) else {
                throw ParseError.malformed(String(line))
            }
            return Row(mjd: mjd, ut1MinusUTC: dut)
        }
    }

    /// IERS Bulletin A finals2000A: fixed columns 8–15 (MJD), 58 (flag), 59–68 (UT1 − UTC).
    static func finals() throws -> [(row: Row, predicted: Bool)] {
        try lines("finals2000A.all").compactMap { line in
            let characters = Array(line.utf8)
            guard characters.count >= 68, characters[57] != UInt8(ascii: " ") else { return nil }
            func field(_ range: Range<Int>) -> Double? {
                Double(String(decoding: characters[range], as: UTF8.self).trimmingCharacters(in: .whitespaces))
            }
            guard let mjd = field(7..<15), let dut = field(58..<68) else {
                throw ParseError.malformed(String(line))
            }
            return (Row(mjd: mjd, ut1MinusUTC: dut), characters[57] == UInt8(ascii: "P"))
        }
    }

    enum ParseError: Error {
        case malformed(String)
    }
}

@Suite("Observed Delta T (IERS)", .serialized)
struct DeltaTIersObservedTests {
    struct CivilReference: Decodable {
        struct Site: Decodable {
            let latitudeDegrees: Double
            let longitudeDegrees: Double
            let heightMeters: Double
        }

        struct Horizons: Decodable {
            struct Row: Decodable {
                let utc: String
                let azimuthDegrees: Double
                let altitudeDegrees: Double
                let ut1MinusUTCSeconds: Double
            }

            struct Event: Decodable {
                let utc: String
            }

            let rows: [Row]
            let sunrise: Event
            let sunset: Event
        }

        let model: String
        let site: Site
        let horizons: Horizons
    }

    static func civilReference() throws -> CivilReference {
        let root = (0..<3).reduce(URL(fileURLWithPath: #filePath)) { url, _ in
            url.deletingLastPathComponent()
        }
        return try JSONDecoder().decode(
            CivilReference.self,
            from: Data(contentsOf: root.appendingPathComponent("Scripts/deltat-data/civil-horizon/reference.json"))
        )
    }

    static func date(_ text: String) throws -> Date {
        let formatter = ISO8601DateFormatter()
        formatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]
        return try #require(formatter.date(from: text))
    }

    /// Days from the Unix epoch to J2000 noon, as `AstroTime` uses.
    static let j2000UnixDays = 946_728_000.0 / 86_400

    /// UT1 − UTC in seconds that the civil path assigns to a UTC instant.
    static func civilUT1MinusUTC(mjd: Double) -> Double {
        let utcDays = mjd - 51_544.5
        let time = AstroTime(Date(timeIntervalSince1970: (utcDays + j2000UnixDays) * 86_400))
        return (time.universalTime - utcDays) * 86_400
    }

    /// The UT1 day coordinate of a Julian epoch year.
    static func ut(year: Double) -> Double { (year - 2_000) * 365.25 }

    // MARK: - Civil path against the raw IERS rows

    @Test("Civil UTC at every daily C04 and Bulletin A row reproduces IERS UT1 − UTC")
    func civilPathMatchesDailyRows() throws {
        let c04 = try IERSRecords.c04("eopc04.1962-now")
        let lastC04 = try #require(c04.last).mjd
        let bulletinA = try IERSRecords.finals().map(\.row).filter { $0.mjd > lastC04 }
        let rows = c04 + bulletinA
        #expect(rows.count > 24_000)
        #expect(rows.first?.mjd == 37_665)

        // At a row's own epoch interpolation contributes nothing; what is left
        // is the precision of a UT1 day coordinate near 1e4 days (~1e-7 s)
        // and the TT inverse's 1e-12-day tolerance.
        var worst = 0.0
        for row in rows {
            worst = max(worst, abs(Self.civilUT1MinusUTC(mjd: row.mjd) - row.ut1MinusUTC))
        }
        #expect(worst < 1e-6, "Largest departure \(worst) s")
    }

    @Test("Civil UTC at 12h matches the 12h C04 samples within the stated interpolation error")
    func civilPathMatchesMidday() throws {
        let midday = try IERSRecords.c04("eopc04.12h.1984-now")
        #expect(midday.count > 15_000)
        var worst = 0.0
        for row in midday {
            worst = max(worst, abs(Self.civilUT1MinusUTC(mjd: row.mjd) - row.ut1MinusUTC))
        }
        // The documented interpolation error: at most 0.16 ms against these samples.
        #expect(worst <= 0.000_16, "Largest departure \(worst) s")
    }

    // MARK: - Joins

    @Test("Bulletin A agrees with C04 over the year before the join")
    func bulletinAMeetsC04() throws {
        let c04 = try IERSRecords.c04("eopc04.1962-now")
        let lastC04 = try #require(c04.last).mjd
        let byMJD = Dictionary(uniqueKeysWithValues: c04.map { ($0.mjd, $0.ut1MinusUTC) })
        let overlap = try IERSRecords.finals().map(\.row).filter { $0.mjd > lastC04 - 365 && $0.mjd <= lastC04 }
        #expect(overlap.count == 365)
        for row in overlap {
            let c04Value = try #require(byMJD[row.mjd])
            #expect(abs(row.ut1MinusUTC - c04Value) < 0.000_1, "MJD \(row.mjd)")
        }
    }

    /// Knots of Table S15 v2020 inside the historical regime, -100 through 1959.
    static let splineKnots: [Double] = [
        -100, 400, 1_000, 1_150, 1_300, 1_500, 1_600, 1_650, 1_720, 1_800, 1_810, 1_820, 1_830,
        1_840, 1_850, 1_855, 1_860, 1_865, 1_870, 1_875, 1_880, 1_885, 1_890, 1_895, 1_900,
        1_905, 1_910, 1_915, 1_920, 1_925, 1_930, 1_935, 1_940, 1_945, 1_950, 1_953, 1_956, 1_959,
    ]

    /// The first C04 row: 1962-01-01 0h UTC plus its UT1 − UTC.
    static let firstObservedUT = (37_665 - 51_544.5) + 0.032_633_8 / 86_400

    /// The last Bulletin A prediction's UT1.
    static func lastPredictedUT() throws -> Double {
        let last = try #require(try IERSRecords.finals().last(where: \.predicted)).row
        return (last.mjd - 51_544.5) + last.ut1MinusUTC / 86_400
    }

    static func deltaT(_ ut: Double) -> Double { AstronomyConfig.deltaTIersObserved(universalTime: ut) }

    /// One-sided Delta T rates in seconds per day, second-order differences
    /// over 0.01 and 0.02 day on each side, so curvature cancels on each side
    /// and only the third derivative and rounding remain (below 1e-9 s/day).
    /// Rounding in the Table S15 polynomials made the two differ by up to
    /// 1.1e-6 s/day.
    static func rates(at ut: Double) -> (before: Double, after: Double) {
        let step = 0.01
        return (
            (3 * deltaT(ut) - 4 * deltaT(ut - step) + deltaT(ut - 2 * step)) / (2 * step),
            (-3 * deltaT(ut) + 4 * deltaT(ut + step) - deltaT(ut + 2 * step)) / (2 * step)
        )
    }

    /// Value continuity: 1e-9 s, against the published table's 1 ms rounding jumps.
    static let valueTolerance = 1e-9

    /// Rate continuity: 1e-8 s/day, against the published table's 1.1e-6 s/day.
    static let rateTolerance = 1e-8

    @Test("Delta T is continuous in value and rate at every Table S15 knot")
    func splineKnotsAreC1() {
        for knot in Self.splineKnots {
            let ut = Self.ut(year: knot)
            #expect(AstronomyConfig.deltaTIersObservedRegime(universalTime: ut) == .historical)
            let step = Self.deltaT(ut) - Self.deltaT(ut.nextDown)
            #expect(abs(step) < Self.valueTolerance, "Knot \(knot): value step \(step) s")
            let rates = Self.rates(at: ut)
            let rateStep = rates.after - rates.before
            #expect(abs(rateStep) < Self.rateTolerance, "Knot \(knot): rate step \(rateStep) s/day")
        }
    }

    @Test(
        "Every regime join is continuous in value",
        arguments: ["-720 spline start", "1962 IERS start", "last prediction"]
    )
    func joinsAreContinuous(join: String) throws {
        let ut: Double
        switch join {
        case "-720 spline start": ut = Self.ut(year: -720)
        case "1962 IERS start": ut = Self.firstObservedUT
        default: ut = try Self.lastPredictedUT()
        }
        let before = Self.deltaT(ut.nextDown)
        let after = Self.deltaT(ut.nextUp)
        let regimes = [ut - 1e-6, ut + 1e-6].map { AstronomyConfig.deltaTIersObservedRegime(universalTime: $0) }
        #expect(abs(after - before) < Self.valueTolerance, "\(join): \(before) → \(after)")
        #expect(regimes[0] != regimes[1], "\(join) separates two regimes")
    }

    @Test("The 1962 join is also continuous in rate")
    func observedJoinIsC1() {
        // The 1959–1962 segment ends on the first C04 interval's rate. The
        // long-term joins at -720 and after the predictions are C0 only.
        let rates = Self.rates(at: Self.firstObservedUT)
        #expect(abs(rates.after - rates.before) < Self.rateTolerance, "Rate step \(rates.after - rates.before) s/day")
    }

    @Test("A five-point second derivative across each knot sees no step")
    func secondDerivativeAcrossKnots() {
        // The stencil downstream event searches use, with ±0.01 and ±0.02 day
        // steps. A 1 ms value step at the centre would read about 12 s/day²; the
        // physical second derivative here is below 1e-6 s/day².
        let h = 0.01
        for knot in Self.splineKnots + [1_962] {
            let ut = knot == 1_962 ? Self.firstObservedUT : Self.ut(year: knot)
            for centre in [ut - h / 2, ut, ut + h / 2] {
                let samples = [-2.0, -1, 0, 1, 2].map { Self.deltaT(centre + $0 * h) }
                let weighted = -samples[0] + 16 * samples[1] - 30 * samples[2] + 16 * samples[3] - samples[4]
                let second = weighted / (12 * h * h)
                #expect(abs(second) < 1e-4, "Knot \(knot): \(second) s/day²")
            }
        }
    }

    // MARK: - Historical and extrapolated values against HMNAO's tables

    /// Delta T tabulated by HM Nautical Almanac Office (https://astro.ukho.gov.uk/nao/lvm/,
    /// archived 2021-06-18), with the rounding step of each table.
    @Test(
        "Historical spline reproduces HMNAO's tabulated Delta T",
        arguments: [
            (-720.0, 20_370.0, 10.0), (-500, 16_940, 10), (0, 10_440, 10), (500, 5_590, 10),
            (1_000, 1_650, 10), (1_500, 290, 10), (1_600, 109, 1), (1_700, 14, 1), (1_750, 17, 1),
            (1_800, 18.4, 0.1), (1_850, 9.3, 0.1), (1_875, -1.13, 0.01), (1_900, -1.98, 0.01),
            (1_925, 23.79, 0.01), (1_950, 28.93, 0.01),
        ] as [(Double, Double, Double)]
    )
    func historicalMatchesHMNAO(year: Double, deltaT: Double, rounding: Double) {
        let ut = Self.ut(year: year)
        #expect(AstronomyConfig.deltaTIersObservedRegime(universalTime: ut) == .historical)
        let value = AstronomyConfig.deltaTIersObserved(universalTime: ut)
        #expect(abs(value - deltaT) <= rounding / 2 + 1e-9, "\(year): \(value) s")
    }

    @Test(
        "Extrapolation agrees with HMNAO's extrapolated Delta T within its error estimate",
        arguments: [
            (-2_000.0, 46_080.0, 1_080.0), (-1_000, 25_560, 720),  // 12.8 ± 0.3 h, 7.1 ± 0.2 h
            (2_050, 70, 6), (2_100, 80, 10), (2_200, 160, 20), (2_300, 330, 30), (2_500, 1_000, 100),
        ] as [(Double, Double, Double)]
    )
    func extrapolationMatchesHMNAO(year: Double, deltaT: Double, epsilon: Double) {
        let ut = Self.ut(year: year)
        let value = AstronomyConfig.deltaTIersObserved(universalTime: ut)
        #expect(abs(value - deltaT) <= epsilon, "\(year): \(value) s")
        #expect(AstronomyConfig.deltaTIersObservedUncertainty(universalTime: ut) == epsilon)
    }

    // MARK: - Regimes and uncertainty

    @Test(
        "Regime boundaries",
        arguments: [
            (-1_000.0, DeltaTRegime.extrapolatedPast), (1_000, .historical), (1_961.99, .historical),
            (1_962.01, .observed), (2_026.78, .observed), (2_026.80, .predicted), (2_027.7, .predicted),
            (2_028, .extrapolatedFuture), (3_000, .extrapolatedFuture),
        ] as [(Double, DeltaTRegime)]
    )
    func regimes(year: Double, regime: DeltaTRegime) {
        #expect(AstronomyConfig.deltaTIersObservedRegime(universalTime: Self.ut(year: year)) == regime)
    }

    @Test("Non-finite UT has no regime and no finite value")
    func nonFinite() {
        #expect(AstronomyConfig.deltaTIersObservedRegime(universalTime: .nan) == nil)
        #expect(AstronomyConfig.deltaTIersObserved(universalTime: .nan).isNaN)
        #expect(AstronomyConfig.deltaTIersObservedUncertainty(universalTime: .nan).isNaN)
        #expect(AstronomyConfig.deltaTIersObservedRegime(universalTime: .infinity) == .extrapolatedFuture)
        #expect(AstronomyConfig.deltaTIersObservedRegime(universalTime: -.infinity) == .extrapolatedPast)
        #expect(AstronomyConfig.deltaTIersObserved(universalTime: .infinity) == .infinity)
        #expect(AstronomyConfig.deltaTIersObserved(universalTime: -.infinity) == .infinity)
    }

    @Test("Uncertainty takes each regime's stated figure")
    func statedUncertainty() throws {
        // C04's formal error for 1962-01-01, at the row's own epoch.
        let first = (37_665 - 51_544.5) + 0.032_633_8 / 86_400
        #expect(abs(AstronomyConfig.deltaTIersObservedUncertainty(universalTime: first) - 0.002) < 1e-12)

        // Midday adds at most the 0.16 ms interpolation allowance.
        let midday = first + 0.5
        let middayUncertainty = AstronomyConfig.deltaTIersObservedUncertainty(universalTime: midday)
        #expect(middayUncertainty > 0.002 && middayUncertainty <= 0.002_16 + 1e-12)

        // Bulletin A's stated error for its last prediction.
        let last = try #require(try IERSRecords.finals().last(where: \.predicted)).row
        let lastUT = (last.mjd - 51_544.5) + last.ut1MinusUTC / 86_400
        #expect(abs(AstronomyConfig.deltaTIersObservedUncertainty(universalTime: lastUT) - 0.024_472_3) < 1e-9)

        // HMNAO's estimate, floored by the spline's 0.68 s departure from C04.
        #expect(AstronomyConfig.deltaTIersObservedUncertainty(universalTime: Self.ut(year: 1_000)) == 15)
        let modern = AstronomyConfig.deltaTIersObservedUncertainty(universalTime: Self.ut(year: 1_900))
        #expect(modern > 0.67 && modern < 0.68)

        // Beyond HMNAO's last estimate the uncertainty keeps growing.
        let far = [2_500.0, 3_000, 5_000].map {
            AstronomyConfig.deltaTIersObservedUncertainty(universalTime: Self.ut(year: $0))
        }
        #expect(far[0] == 100 && far[0] < far[1] && far[1] < far[2])
    }

    // MARK: - Engine wiring

    @Test("The ephemeris version names the generated table")
    func versionNamesTable() {
        #expect(AstronomyConfig.ephemerisVersion.contains(".deltat-\(Engine.DeltaT.Observed.tableID)."))
    }

    @Test("The observed model is the process default")
    func isDefault() {
        #expect(AstroTime(ut: 0).deltaTModel == .iersObserved)
        #expect(DeltaTModel.allCases.first == .iersObserved)
        for year in [-1_000.0, 1_900, 1_990, 2_026.79, 2_027.5, 2_126] {
            let ut = Self.ut(year: year)
            let expected = ut + AstronomyConfig.deltaTIersObserved(universalTime: ut) / 86_400
            #expect(AstroTime(ut: ut).terrestrialTime == expected, "\(year)")
        }
    }

    @Test("The TT inverse converges in every regime")
    func inverseConverges() {
        var ut = Self.ut(year: -3_000)
        while ut < Self.ut(year: 3_000) {
            let time = AstroTime(ut: ut)
            let inverse = AstroTime(tt: time.terrestrialTime)
            #expect(abs(inverse.universalTime - ut) * 86_400 < 1e-5, "UT \(ut)")
            ut += 3_653.3
        }
    }

    // MARK: - Rise and set through the civil path

    @Test("Civil horizon uses the default observed model and matches pinned Horizons rows")
    func civilHorizonMatchesHorizons() throws {
        let fixture = try Self.civilReference()
        #expect(fixture.model == "iersObserved")
        #expect(fixture.horizons.rows.count == 5)
        let site = Observer(
            latitude: fixture.site.latitudeDegrees,
            longitude: fixture.site.longitudeDegrees,
            height: fixture.site.heightMeters
        )
        for row in fixture.horizons.rows {
            let date = try Self.date(row.utc)
            let time = AstroTime(date)
            #expect(time.deltaTModel == .iersObserved)
            let horizon = try CelestialBody.sun.horizon(at: time, from: site, refraction: .none)
            let altitudeResidual = abs(horizon.altitude - row.altitudeDegrees)
            let azimuthResidual = abs(Engine.longitudeOffset(horizon.azimuth - row.azimuthDegrees))
            #expect(altitudeResidual <= 1.0 / 60, "\(row.utc): altitude residual \(altitudeResidual * 60)′")
            #expect(azimuthResidual <= 1.0 / 60, "\(row.utc): azimuth residual \(azimuthResidual * 60)′")
        }

        let discriminator = fixture.horizons.rows[0]
        let date = try Self.date(discriminator.utc)
        func altitudeResidual(_ model: DeltaTModel) throws -> Double {
            let time = AstroTime(date, deltaTModel: model)
            let altitude = try CelestialBody.sun.horizon(at: time, from: site, refraction: .none).altitude
            return abs(altitude - discriminator.altitudeDegrees)
        }
        let observed = try altitudeResidual(.iersObserved)
        let held = try altitudeResidual(.jplHorizons)
        let polynomial = try altitudeResidual(.espenakMeeus)
        #expect(held * 3_600 > 5, "Held-model residual \(held * 3_600)″")
        #expect(polynomial * 3_600 > 50, "Polynomial residual \(polynomial * 3_600)″")
        #expect(observed < held && held < polynomial)
    }

    @Test("Civil sunrise and sunset match JPL Horizons within 0.25 s")
    func riseSetMatchHorizons() throws {
        let fixture = try Self.civilReference()
        let observer = Observer(
            latitude: fixture.site.latitudeDegrees,
            longitude: fixture.site.longitudeDegrees,
            height: fixture.site.heightMeters
        )
        let startDate = try Self.date("2025-06-21T04:00:00.000Z")
        let start = AstroTime(startDate)
        let sunriseReference = try Self.date(fixture.horizons.sunrise.utc)
        let sunsetReference = try Self.date(fixture.horizons.sunset.utc)

        func residuals(from start: AstroTime) throws -> (rise: Double, set: Double) {
            let rise = try #require(try CelestialBody.sun.riseTime(after: start, from: observer))
            let set = try #require(try CelestialBody.sun.setTime(after: rise, from: observer))
            return (
                rise.date.timeIntervalSince(sunriseReference),
                set.date.timeIntervalSince(sunsetReference)
            )
        }

        let observed = try residuals(from: start)
        #expect(abs(observed.rise) < 0.25, "Sunrise off by \(observed.rise) s")
        #expect(abs(observed.set) < 0.25, "Sunset off by \(observed.set) s")

        let held = try residuals(from: AstroTime(startDate, deltaTModel: .jplHorizons))
        #expect(held.rise > 0.75 && held.set > 0.75, "Held-model residuals \(held)")

        // Both older choices fail this 0.25 s comparison. The start time captures
        // the model, and so does every time the search derives from it, without
        // touching the process default.
        let modeledStart = AstroTime(startDate, deltaTModel: .espenakMeeus)
        #expect(modeledStart.deltaTModel == .espenakMeeus)
        let modeled = try residuals(from: modeledStart)
        #expect(modeled.rise > 5 && modeled.set > 5, "Espenak-Meeus residuals \(modeled)")
    }
}
