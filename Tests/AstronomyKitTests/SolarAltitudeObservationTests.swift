import Foundation
import Testing

@testable import AstronomyKit

/// `Sun.altitudeObservation` returns the geometric altitude with the inputs
/// that produced it and the derived terms of the error budget, and refuses the
/// cases the budget excludes. Nothing here changes the process default model.
@Suite("Solar altitude observation")
struct SolarAltitudeObservationTests {
    typealias Unsupported = SolarAltitudeObservation.Unsupported
    typealias Bounds = SolarAltitudeBounds

    private static let observer40N = Observer(latitude: 40, longitude: 0)

    private static func date(_ iso8601: String) throws -> Date {
        try #require(ISO8601DateFormatter().date(from: iso8601))
    }

    /// The civil `Date` whose day count since J2000 noon is `civilDays`.
    private static func date(civilDays: Double) -> Date {
        Date(timeIntervalSince1970: civilDays * 86_400 + AstroTime.j2000UnixOffset)
    }

    private static func observe(
        _ date: Date, from observer: Observer = observer40N, deltaTModel: DeltaTModel = .espenakMeeus
    ) throws -> SolarAltitudeObservation {
        try Sun.altitudeObservation(at: date, from: observer, deltaTModel: deltaTModel)
    }

    private static func observe(
        tt: Double, from observer: Observer = observer40N, deltaTModel: DeltaTModel = .espenakMeeus
    ) throws -> SolarAltitudeObservation {
        try Sun.altitudeObservation(terrestrialTime: tt, from: observer, deltaTModel: deltaTModel)
    }

    private static func observe(
        ut: Double, from observer: Observer = observer40N, deltaTModel: DeltaTModel = .espenakMeeus
    ) throws -> SolarAltitudeObservation {
        try Sun.altitudeObservation(universalTime: ut, from: observer, deltaTModel: deltaTModel)
    }

    private static func nativeTime(_ date: Date, deltaTModel model: DeltaTModel) -> AstroTime {
        let native = Engine.Time.civil(utcDays: AstroTime.civilDays(of: date), deltaTModel: model).time
        return AstroTime(tt: native.tt, ut: native.ut, deltaTModel: model)
    }

    private static func nativeTime(tt: Double, deltaTModel model: DeltaTModel) -> AstroTime {
        let native = Engine.Time(tt: tt, deltaTModel: model)
        return AstroTime(tt: native.tt, ut: native.ut, deltaTModel: model)
    }

    private static func nativeTime(ut: Double, deltaTModel model: DeltaTModel) -> AstroTime {
        let native = Engine.Time(ut: ut, deltaTModel: model)
        return AstroTime(tt: native.tt, ut: native.ut, deltaTModel: model)
    }

    private static func geometricAltitude(_ time: AstroTime) throws -> Double {
        try CelestialBody.sun.horizon(at: time, from: observer40N, refraction: .none).altitude
    }

    @Test("Each entry point records native model time and repeats the ordinary horizon result")
    func entryPointsMatchHorizon() throws {
        let date = try Self.date("2026-07-24T06:30:00Z")
        let time = Self.nativeTime(date, deltaTModel: .jplHorizons)

        let civil = try Self.observe(date, deltaTModel: .jplHorizons)
        #expect(civil.time.universalTime == time.universalTime)
        #expect(civil.time.terrestrialTime == time.terrestrialTime)
        #expect(civil.time.deltaTModel == .jplHorizons)
        #expect(civil.deltaTModel == .jplHorizons)
        #expect(civil.observer == Self.observer40N)
        #expect(civil.reference == .civilUTC)
        #expect(civil.altitude == (try Self.geometricAltitude(time)))

        let terrestrial = try Self.observe(tt: time.terrestrialTime, deltaTModel: .jplHorizons)
        let fromTT = Self.nativeTime(tt: time.terrestrialTime, deltaTModel: .jplHorizons)
        #expect(terrestrial.reference == .terrestrialTime)
        #expect(terrestrial.time.terrestrialTime == time.terrestrialTime)
        #expect(terrestrial.time.universalTime == fromTT.universalTime)
        #expect(terrestrial.altitude == (try Self.geometricAltitude(fromTT)))

        let universal = try Self.observe(ut: time.universalTime, deltaTModel: .jplHorizons)
        let fromUT = Self.nativeTime(ut: time.universalTime, deltaTModel: .jplHorizons)
        #expect(universal.reference == .universalTime)
        #expect(universal.time.universalTime == time.universalTime)
        #expect(universal.time.terrestrialTime == fromUT.terrestrialTime)
        #expect(universal.altitude == (try Self.geometricAltitude(fromUT)))

        // The same inputs give the same value and the same bound.
        let again = try Self.observe(date, deltaTModel: .jplHorizons)
        #expect(again == civil)
        #expect(again.hashValue == civil.hashValue)
    }

    @Test("Each construction sums its own terms of the budget")
    func termsFollowTheConstruction() throws {
        let civil = try Self.observe(try Self.date("1972-07-01T12:00:00Z"))
        #expect(civil.reference == .civilUTC)
        #expect(civil.errorBound.civilConversion == Bounds.civilToTTDegrees)
        #expect(civil.errorBound.scaleConversion == Bounds.ttInverseDegrees)

        let proxy = try Self.observe(try Self.date("1950-06-01T12:00:00Z"))
        #expect(proxy.reference == .civilUT1)
        #expect(proxy.errorBound.civilConversion == Bounds.civilToUTDegrees)
        #expect(proxy.errorBound.scaleConversion == Bounds.forwardTTDegrees)

        let terrestrial = try Self.observe(tt: 9_000.25)
        #expect(terrestrial.errorBound.civilConversion == 0)
        #expect(terrestrial.errorBound.scaleConversion == Bounds.ttInverseDegrees)

        let universal = try Self.observe(ut: 9_000.25)
        #expect(universal.errorBound.civilConversion == 0)
        #expect(universal.errorBound.scaleConversion == Bounds.forwardTTDegrees)

        for observation in [civil, proxy, terrestrial, universal] {
            let bound = observation.errorBound
            #expect(bound.lightTimeTermination == Bounds.lightTimeDegrees)
            #expect(bound.earthRotationAngle == Bounds.eraDegrees)
            let plainSum = bound.civilConversion + bound.scaleConversion + Bounds.lightTimeDegrees + Bounds.eraDegrees
            #expect(bound.total >= plainSum)
            #expect(bound.total <= plainSum.nextUp.nextUp.nextUp)
        }
        // TT inversion dominates the partial light-time/ERA budget; constants are independently derived and replayed.
        #expect(terrestrial.errorBound.scaleConversion > terrestrial.errorBound.lightTimeTermination)
        #expect(terrestrial.errorBound.total > universal.errorBound.total)
        #expect(universal.errorBound.total > 0)
    }

    @Test("A Date's civil term covers the rounding carried into UT")
    func civilTermReachesUniversalTime() throws {
        // From 1961 on the table's TT seeds init(tt:), which derives UT from
        // it; before 1961 the civil day count is UT. Either way the calendar
        // rounding reaches UT, and UT turns the Earth more than 360 degrees a
        // day, so the civil term is at least that rounding times 360. The floor
        // does not read the civil constants it checks.
        let civil = try Self.observe(try Self.date("1972-07-01T12:00:00Z"))
        let fromTT = Self.nativeTime(tt: civil.time.terrestrialTime, deltaTModel: .espenakMeeus)
        #expect(civil.time.universalTime == fromTT.universalTime)
        let proxy = try Self.observe(try Self.date("1950-06-01T12:00:00Z"))
        #expect(proxy.time.universalTime == AstroTime.civilDays(of: try Self.date("1950-06-01T12:00:00Z")))

        let earthTurn = Bounds.civilCalendarDays * 360
        for observation in [civil, proxy] {
            let bound = observation.errorBound
            #expect(bound.civilConversion >= earthTurn)
            let others = bound.scaleConversion + bound.lightTimeTermination + bound.earthRotationAngle
            #expect(bound.total >= earthTurn + others)
        }
    }

    @Test("A rounded sum is moved up to cover the exact sum")
    func addingUp() {
        typealias Bound = SolarAltitudeObservation.ErrorBound
        // 1 + 2^-53 ties to 1; the exact sum is above it.
        #expect(Bound.addingUp(1, Double.ulpOfOne / 2) == 1.0.nextUp)
        // 1 + 0.75 ulp rounds up already; no second step.
        #expect(Bound.addingUp(1, 0.75 * Double.ulpOfOne) == 1.0.nextUp)
        // Exact sums are untouched.
        #expect(Bound.addingUp(0.25, 0.5) == 0.75)
        #expect(Bound.addingUp(1, 0) == 1)
        #expect(Bound.addingUp(1, -Double.ulpOfOne / 2) == 1.0.nextDown)
    }

    @Test("The model is an input, not an error: 2049-12-21T12:00Z under both models")
    func modelIsAnInput() throws {
        // DeltaTModelCaptureTests measures the 5.2e-4 degree difference between
        // the models at this date; it is far above either bound, which
        // describes rounding under one model.
        let date = try Self.date("2049-12-21T12:00:00Z")
        let em = try Self.observe(date, deltaTModel: .espenakMeeus)
        let jpl = try Self.observe(date, deltaTModel: .jplHorizons)
        #expect(em.time.terrestrialTime == jpl.time.terrestrialTime)
        #expect(abs(em.altitude - jpl.altitude) > 5e-4)
        let largerBound = max(em.errorBound.total, jpl.errorBound.total)
        #expect(abs(em.altitude - jpl.altitude) > 10_000 * largerBound)
    }

    @Test("Times outside the polynomial coverage are refused")
    func coverage() throws {
        let coverage = SolarAltitudeObservation.polynomialCoverage
        #expect(coverage == -36_524.5..<36_889.5)

        #expect(throws: Unsupported.outsidePolynomialCoverage) {
            try Self.observe(try Self.date("1899-12-31T12:00:00Z"))
        }
        // 2101-01-01T00:00Z civil is 36889.5 days of UTC; TT is 69 s later, past the end.
        #expect(throws: Unsupported.outsidePolynomialCoverage) {
            try Self.observe(try Self.date("2101-01-01T00:00:00Z"))
        }
        _ = try Self.observe(try Self.date("2100-12-31T23:00:00Z"))

        // Earth is held at reception. Solar emission padding no longer excludes the first covered minutes.
        let backdate = SolarAltitudeObservation.maximumLightTimeDays
        #expect(backdate > 0.0059 && backdate <= 0.006)
        _ = try Self.observe(tt: coverage.lowerBound + backdate / 2)
        _ = try Self.observe(tt: coverage.lowerBound + backdate + 1e-3)

        // The last UT whose TT is inside the coverage is accepted; the next one is not.
        let deltaTDays = Engine.DeltaT.seconds(ut: coverage.upperBound, model: .espenakMeeus) / 86_400
        _ = try Self.observe(ut: coverage.upperBound - deltaTDays - 1e-6)
        #expect(throws: Unsupported.outsidePolynomialCoverage) {
            try Self.observe(ut: coverage.upperBound - deltaTDays + 1e-6)
        }
    }

    @Test("A TT inside a Delta T gap is refused; a TT with two UTs is accepted")
    func deltaTGaps() throws {
        // Native model pieces meet at Gregorian 1 January UT.
        func boundary(year: Double) -> Double { Engine.DeltaT.Gregorian.start(year: year) }
        func forward(_ ut: Double) -> Double { Self.nativeTime(ut: ut, deltaTModel: .espenakMeeus).terrestrialTime }

        // 1961: Delta T steps up by 0.0296 s, leaving TT values with no UT.
        let gapBoundary = boundary(year: 1_961)
        let below = forward(gapBoundary - 1e-6)
        let above = forward(gapBoundary + 1e-6)
        #expect(abs((above - below - 2e-6) * 86_400 - 0.0296) < 0.001)
        let inGap = (below + above) / 2
        let clamped = Self.nativeTime(tt: inGap, deltaTModel: .espenakMeeus)
        #expect(clamped.terrestrialTime == inGap)
        let residual = abs(inGap - forward(clamped.universalTime))
        #expect(residual > SolarAltitudeObservation.inverseTolerance(terrestrialTime: inGap))
        #expect(throws: Unsupported.terrestrialTimeInDeltaTGap) {
            try Self.observe(tt: inGap)
        }
        // Either side of the gap is an ordinary TT.
        for edge in [below - 1e-6, above + 1e-6] {
            _ = try Self.observe(tt: edge)
        }

        // 2005: Delta T steps down by 0.05 s, so a TT just before the boundary
        // has two UTs; the inverse converges to one and the budget applies.
        let twoSolutions = forward(boundary(year: 2_005) - 1e-7)
        let observation = try Self.observe(tt: twoSolutions)
        #expect(observation.time.terrestrialTime == twoSolutions)
        #expect(observation.errorBound.scaleConversion >= Bounds.ttInverseDegrees + Bounds.arrivalJumpInverseDegrees)
    }

    @Test("The inverse tolerance is the engine's expression")
    func inverseTolerance() {
        #expect(SolarAltitudeObservation.inverseTolerance(terrestrialTime: 0) == 1e-12)
        #expect(SolarAltitudeObservation.inverseTolerance(terrestrialTime: 36_889.5) == 2 * Double.ulpOfOne * 36_889.5)
        #expect(SolarAltitudeObservation.inverseTolerance(terrestrialTime: -10_000) == 2 * Double.ulpOfOne * 10_000)
    }

    @Test("A civil date at a UTC segment start is refused; a second away is accepted")
    func civilSegmentStarts() throws {
        // The table's first segment (1961-01-01) and a leap second (1972-07-01).
        for start in [CivilTime.segments[0].start, CivilTime.segments[13].start] {
            #expect(throws: Unsupported.civilDateAtSegmentStart) {
                try Self.observe(Self.date(civilDays: start))
            }
            #expect(throws: Unsupported.civilDateAtSegmentStart) {
                try Self.observe(Self.date(civilDays: start + Bounds.civilCalendarDays / 2))
            }
            let before = try Self.observe(Self.date(civilDays: start - 1 / 86_400))
            let after = try Self.observe(Self.date(civilDays: start + 1 / 86_400))
            #expect(after.time.universalTime > before.time.universalTime)
        }
        // The first segment start separates the UT1 proxy from the table.
        let proxy = try Self.observe(Self.date(civilDays: CivilTime.segments[0].start - 1 / 86_400))
        #expect(proxy.reference == .civilUT1)
        let table = try Self.observe(Self.date(civilDays: CivilTime.segments[0].start + 1 / 86_400))
        #expect(table.reference == .civilUTC)
    }

    @Test("Observers outside the budget or the validated range are refused")
    func observers() throws {
        #expect(SolarAltitudeObservation.maximumObserverHeight == 10_000)
        let tt = 9_000.25
        _ = try Self.observe(tt: tt, from: Observer(latitude: 40, longitude: 0, height: 10_000))
        _ = try Self.observe(tt: tt, from: Observer(latitude: -90, longitude: 180, height: -10_000))
        for height in [Double(10_000).nextUp, Double(-10_000).nextDown, Observer.geocentric.height] {
            #expect(throws: Unsupported.observerHeightOutsideBudget) {
                try Self.observe(tt: tt, from: Observer(latitude: 40, longitude: 0, height: height))
            }
        }
        for observer in [
            Observer(latitude: 91, longitude: 0), Observer(latitude: .nan, longitude: 0),
            Observer(latitude: 0, longitude: .infinity), Observer(latitude: 0, longitude: 0, height: .nan),
        ] {
            #expect(throws: AstronomyError.invalidParameter) {
                try Self.observe(tt: tt, from: observer)
            }
        }
    }

    @Test("The observed model covers every time reference and keeps the existing exclusions")
    func observedModelReferencesAndExclusions() throws {
        let modernDate = try Self.date("2026-07-24T06:30:00Z")
        let historicalDate = try Self.date("1950-06-01T12:00:00Z")
        let observations = [
            try Self.observe(modernDate, deltaTModel: .iersObserved),
            try Self.observe(historicalDate, deltaTModel: .iersObserved),
            try Self.observe(tt: 9_000.25, deltaTModel: .iersObserved),
            try Self.observe(ut: 9_000.25, deltaTModel: .iersObserved),
        ]
        #expect(Set(observations.map(\.reference)) == [.civilUTC, .civilUT1, .terrestrialTime, .universalTime])
        for observation in observations {
            #expect(observation.deltaTModel == .iersObserved)
            #expect(observation.time.deltaTModel == .iersObserved)
            #expect(observation.altitude == (try Self.geometricAltitude(observation.time)))
            #expect(observation.errorBound.total > 0)
        }

        #expect(throws: Unsupported.outsidePolynomialCoverage) {
            try Self.observe(try Self.date("1899-12-31T12:00:00Z"), deltaTModel: .iersObserved)
        }
        #expect(throws: Unsupported.civilDateAtSegmentStart) {
            try Self.observe(Self.date(civilDays: CivilTime.segments[0].start), deltaTModel: .iersObserved)
        }
        #expect(throws: Unsupported.observerHeightOutsideBudget) {
            try Self.observe(
                tt: 9_000.25, from: Observer(latitude: 40, longitude: 0, height: 10_000.nextUp),
                deltaTModel: .iersObserved)
        }
        #expect(throws: AstronomyError.invalidParameter) {
            try Self.observe(tt: 9_000.25, from: Observer(latitude: 91, longitude: 0), deltaTModel: .iersObserved)
        }
    }

    @Test("Observed regimes and their joins return arithmetic bounds")
    func observedModelRegimesAndJoins() throws {
        let rows = Engine.DeltaT.Observed.rows
        let first = rows.ut[0]
        let predictionBoundary = rows.ut[Engine.DeltaT.Observed.firstPredictedRow - 1]
        let last = try #require(rows.ut.last)
        let samples = [
            first.nextDown, first, first.nextUp,
            predictionBoundary.nextDown, predictionBoundary, predictionBoundary.nextUp,
            last.nextDown, last, last.nextUp,
        ]
        #expect(Engine.DeltaT.Observed.regime(ut: first.nextDown) == .historical)
        #expect(Engine.DeltaT.Observed.regime(ut: first) == .observed)
        #expect(Engine.DeltaT.Observed.regime(ut: predictionBoundary) == .observed)
        #expect(Engine.DeltaT.Observed.regime(ut: predictionBoundary.nextUp) == .predicted)
        #expect(Engine.DeltaT.Observed.regime(ut: last.nextUp) == .extrapolatedFuture)
        let pastJoin = (Engine.DeltaT.Observed.spline[0].start - 2_000) * 365.25
        #expect(Engine.DeltaT.Observed.regime(ut: pastJoin.nextDown) == .extrapolatedPast)
        #expect(Engine.DeltaT.Observed.regime(ut: pastJoin) == .historical)
        for ut in [pastJoin.nextDown, pastJoin, pastJoin.nextUp] {
            #expect(throws: Unsupported.outsidePolynomialCoverage) {
                try Self.observe(ut: ut, deltaTModel: .iersObserved)
            }
        }
        for ut in samples {
            let observation = try Self.observe(ut: ut, deltaTModel: .iersObserved)
            #expect(observation.errorBound.scaleConversion == Bounds.observedForwardTTDegrees)
            #expect(observation.altitude == (try Self.geometricAltitude(observation.time)))
        }
    }

    @Test("Observed physical uncertainty stays separate from the arithmetic total")
    func observedStatedUncertainty() throws {
        let ut = 9_000.25
        let fromUT = try Self.observe(ut: ut, deltaTModel: .iersObserved)
        let fromTT = try Self.observe(tt: fromUT.time.terrestrialTime, deltaTModel: .iersObserved)
        let forward = try #require(fromUT.statedUncertainty)
        let inverse = try #require(fromTT.statedUncertainty)
        #expect(forward.deltaTSeconds == AstronomyConfig.deltaTIersObservedUncertainty(universalTime: ut))
        #expect(
            inverse.deltaTSeconds
                == AstronomyConfig.deltaTIersObservedUncertainty(
                    universalTime: fromTT.time.universalTime))
        #expect(forward.altitudeDegrees > 0)
        #expect(inverse.altitudeDegrees > 100 * forward.altitudeDegrees)
        #expect(fromUT.errorBound.total < forward.altitudeDegrees)
        #expect(fromTT.errorBound.total < inverse.altitudeDegrees)
        #expect(try Self.observe(ut: ut, deltaTModel: .espenakMeeus).statedUncertainty == nil)
        #expect(try Self.observe(ut: ut, deltaTModel: .jplHorizons).statedUncertainty == nil)
    }

    @Test("Non-finite times throw badTime")
    func nonFiniteTimes() {
        #expect(throws: AstronomyError.badTime) { try Self.observe(tt: .nan) }
        #expect(throws: AstronomyError.badTime) { try Self.observe(ut: .infinity, deltaTModel: .jplHorizons) }
        #expect(throws: AstronomyError.badTime) { try Self.observe(Date(timeIntervalSince1970: .nan)) }
    }

    @Test("Public constants mirror the generated bounds")
    func constants() {
        #expect(SolarAltitudeObservation.polynomialSegmentDays == 8)
        #expect(SolarAltitudeObservation.joinDiscontinuityDegrees == Bounds.joinDegrees)
        #expect(SolarAltitudeObservation.maximumLightTimeDays == Bounds.backdateMaxDays)
        // Nine thousand one hundred seventy-seven eight-day segments span the coverage.
        let coverage = SolarAltitudeObservation.polynomialCoverage
        let segments = (coverage.upperBound - coverage.lowerBound) / SolarAltitudeObservation.polynomialSegmentDays
        #expect(segments.rounded(.up) == 9_177)
        // Baseline partial terms remain below one tenth of a microdegree; model-step supplements are tested separately.
        let bounds = [
            Bounds.civilToTTDegrees, Bounds.civilToUTDegrees, Bounds.forwardTTDegrees,
            Bounds.lightTimeDegrees, Bounds.eraDegrees, Bounds.joinDegrees,
        ]
        for bound in bounds {
            #expect(bound > 0 && bound < 1e-7)
        }
    }
}
