//
//  SolarAltitudeObservation.swift
//  AstronomyKit
//
//  Geometric solar altitude with its inputs and derived numerical error bound.
//

import Foundation

/// The Sun's geometric altitude, the inputs that produced it, and the derived
/// numerical error bound from <doc:SolarAltitudeNumerics>.
///
/// Get one from ``Sun/altitudeObservation(at:from:deltaTModel:)``,
/// ``Sun/altitudeObservation(terrestrialTime:from:deltaTModel:)``, or
/// ``Sun/altitudeObservation(universalTime:from:deltaTModel:)``. Each builds
/// time with the native model and an explicit ``DeltaTModel``, then records
/// its two scales in an ``AstroTime``. The result keeps every input the calculation read:
/// both time scales, the model, and the observer. A later
/// ``AstronomyConfig/setDeltaTModel(_:)`` call does not change what a
/// repeated call returns.
///
/// ``altitude`` is bit-identical to
/// `CelestialBody.sun.horizon(at: time, from: observer, refraction: .none).altitude`.
/// ``errorBound`` sums the terms of the article's budget that apply to how
/// the time was built. It covers only what the article derives. The terms the
/// article measures (polynomial evaluation, frame rotation, sidereal time, the
/// horizon transform, the math library, and Delta T evaluation) are
/// excluded from this bound. The article distinguishes their sampled
/// differences from the coarse guards used only to classify supported inputs.
///
/// A case the article excludes throws ``Unsupported`` instead of returning a
/// bound.
public struct SolarAltitudeObservation: Sendable, Equatable, Hashable {
    /// The input scale that names the instant the bound is measured from.
    public enum Reference: Sendable, Hashable {
        /// A civil UTC date from 1961 on: TT comes from the bundled offset
        /// table and UT from the model's inverse.
        case civilUTC

        /// A civil date before 1961, taken as UT1: UT is the civil day count
        /// and TT follows the model.
        case civilUT1

        /// A Terrestrial Time; UT comes from the model's inverse.
        case terrestrialTime

        /// A Universal Time; TT follows the model.
        case universalTime
    }

    /// The derived terms that apply to one observation, in degrees.
    public struct ErrorBound: Sendable, Equatable, Hashable {
        /// Calendar rounding and, from 1961 on, the civil UTC to TT
        /// conversion, with what that error carries into the scale the model
        /// derives from it. Zero unless the time came from a `Date`.
        public let civilConversion: Double

        /// The TT to UT inverse when the engine derived UT, or the UT to TT
        /// rounding when it derived TT.
        public let scaleConversion: Double

        /// Light-time termination and one possible reception ephemeris join, including its velocity jump in aberration. Emission uses TT/TDB directly and crosses no Delta T branch.
        public let lightTimeTermination: Double

        /// Earth Rotation Angle rounding.
        public let earthRotationAngle: Double

        /// The sum of the four terms. Each addition rounds up when its
        /// floating-point result fell short, so the total is never below the
        /// exact sum.
        public var total: Double {
            let conversions = Self.addingUp(civilConversion, scaleConversion)
            return Self.addingUp(Self.addingUp(conversions, lightTimeTermination), earthRotationAngle)
        }

        /// `a + b`, moved up one unit when the rounded sum is below the exact sum.
        static func addingUp(_ a: Double, _ b: Double) -> Double {
            let sum = a + b
            // Two-sum: the exact error of a rounded sum of finite operands.
            let bVirtual = sum - a
            let error = (a - (sum - bVirtual)) + (b - bVirtual)
            return error > 0 ? sum.nextUp : sum
        }
    }

    /// The observed Delta T model's published physical uncertainty and its
    /// propagated effect on altitude. These figures are about one standard
    /// error, not proved bounds, and are not part of ``ErrorBound/total``.
    public struct StatedUncertainty: Sendable, Equatable, Hashable {
        /// The model's stated Delta T uncertainty at the recorded UT, in seconds.
        public let deltaTSeconds: Double

        /// The stated Delta T uncertainty propagated through the applicable
        /// UT or TT altitude sensitivity, in degrees.
        public let altitudeDegrees: Double
    }

    /// A case <doc:SolarAltitudeNumerics> excludes from the budget.
    public enum Unsupported: Error, Sendable, Equatable, Hashable {
        /// The input TT, or its conservative reception-time enclosure, is outside ``SolarAltitudeObservation/polynomialCoverage``.
        case outsidePolynomialCoverage

        /// The TT lies in a positive Delta T step of the model (1920, 1941,
        /// 1961, or 1986), where the model has no UT and the inverse stores a
        /// pair the model does not relate. A civil input whose rounding
        /// interval can reach a gap is also refused.
        case terrestrialTimeInDeltaTGap

        /// The civil date is within the calendar rounding of a UTC segment
        /// start, where the stored TT can land on either side of the step.
        case civilDateAtSegmentStart

        /// The observer is farther than
        /// ``SolarAltitudeObservation/maximumObserverHeight`` from the
        /// ellipsoid.
        case observerHeightOutsideBudget
    }

    /// The time the altitude was evaluated at, with both scales and the model.
    public let time: AstroTime

    /// The Delta T model that relates the reception time's two scales. The light-time solve uses TT/TDB directly.
    public let deltaTModel: DeltaTModel

    /// The observer.
    public let observer: Observer

    /// Which input scale names the instant ``errorBound`` is measured from.
    public let reference: Reference

    /// The geometric altitude in degrees, without refraction.
    public let altitude: Double

    /// The derived numerical error bound.
    public let errorBound: ErrorBound

    /// The observed model's published physical uncertainty, kept separate
    /// from the proved arithmetic terms in ``errorBound``. `nil` for the two
    /// comparison models, which publish no corresponding estimate.
    public let statedUncertainty: StatedUncertainty?

    /// The reception TT domain of this partial budget: 1900-01-01 through the end of 2100. The entire admitted uncertainty hull lies inside the selected DE Earth's full-weight window.
    public static let polynomialCoverage: Range<Double> =
        SolarAltitudeBounds.polynomialStart..<SolarAltitudeBounds.polynomialStop

    /// The retained Earth polynomial's eight-TT-day spacing, kept as compatibility metadata. It does not locate the selected DE trajectory's record joins.
    public static let polynomialSegmentDays = SolarAltitudeBounds.polynomialSegmentDays

    /// A position-and-velocity jump allowance for the selected Earth trajectory, in degrees. It sums the maximum join of each source component, including simultaneous joins. The point budget includes this allowance once for its reception uncertainty hull.
    ///
    /// Selected component joins occur on the TDB grid `-36560.5 + 4*k`; the barycenter and Sun have joins at `-36568.5 + 16*k`. Convert reception TT to TDB before enumerating joins. An interval enclosure adds this allowance for every grid point crossed, even when it crosses no retained eight-TT-day boundary. A conservative alternative for an interval of `d` TT days is `floor(d / 3.999999) + 1` allowances, including when `d` is zero; this avoids dependence on a rounded TT-to-TDB boundary classification.
    public static let joinDiscontinuityDegrees = SolarAltitudeBounds.joinDegrees

    /// The derived exact-model solar light-time upper bound, in TT days, used by this partial budget. This excludes interpolation, norm and clock-evaluation errors and is not an unconditional upper bound on every native callback.
    public static let maximumLightTimeDays = SolarAltitudeBounds.backdateMaxDays

    /// The largest observer height above or below the ellipsoid the budget
    /// covers, in meters.
    public static let maximumObserverHeight = SolarAltitudeBounds.observerHeightMeters

    init(time: AstroTime, reference: Reference, observer: Observer, deltaTModel: DeltaTModel) throws {
        try observer.validate()
        guard abs(observer.height) <= SolarAltitudeBounds.observerHeightMeters else {
            throw Unsupported.observerHeightOutsideBudget
        }
        let ut = time.universalTime
        let tt = time.terrestrialTime
        guard ut.isFinite, tt.isFinite else { throw AstronomyError.badTime }
        let modelBudget = ModelBudget(deltaTModel)

        // The TT the model gives for `ut`. A time built from `ut` has exactly it.
        let forwardTT: Double
        let civilConversion: Double
        let scaleConversion: Double
        switch reference {
        case .terrestrialTime, .civilUTC:
            forwardTT = Engine.Time(ut: ut, deltaTModel: deltaTModel).tt
            // The engine's inverse accepts this residual as converged; a TT in
            // a gap is stored with a UT whose residual exceeds it.
            guard abs(tt - forwardTT) <= Self.inverseTolerance(terrestrialTime: tt) else {
                throw Unsupported.terrestrialTimeInDeltaTGap
            }
            civilConversion = reference == .civilUTC ? modelBudget.civilToTTDegrees : 0
            scaleConversion = modelBudget.ttInverseDegrees
        case .universalTime, .civilUT1:
            forwardTT = tt
            civilConversion = reference == .civilUT1 ? modelBudget.civilToUTDegrees : 0
            scaleConversion = modelBudget.forwardTTDegrees
        }

        if deltaTModel != .iersObserved && (reference == .terrestrialTime || reference == .civilUTC) {
            for gap in SolarAltitudeBounds.positiveGaps {
                let intersects: Bool
                if reference == .terrestrialTime {
                    intersects = tt >= gap.lower && tt < gap.upper
                } else {
                    let lower = (tt - SolarAltitudeBounds.civilToTTDays).nextDown
                    let upper = (tt + SolarAltitudeBounds.civilToTTDays).nextUp
                    intersects = upper >= gap.lowerEnclosure && lower <= gap.upperEnclosure
                }
                guard !intersects else { throw Unsupported.terrestrialTimeInDeltaTGap }
            }
        }

        let coverage = Self.polynomialCoverage
        guard coverage.contains(tt), abs(ut) < SolarAltitudeBounds.classificationUTLimit else {
            throw Unsupported.outsidePolynomialCoverage
        }
        let classificationGuard = SolarAltitudeBounds.classificationGuardDays
        let globalUncertainty =
            (modelBudget.arrivalUncertaintyDays + modelBudget.classificationInverseGuardDays).nextUp
        let arrivalStep = Self.crossesModelStep(
            lower: (ut - globalUncertainty).nextDown, upper: (ut + globalUncertainty).nextUp, model: deltaTModel)
        let uncertainty =
            arrivalStep
            ? globalUncertainty
            : (modelBudget.arrivalUncertaintyBaseDays + modelBudget.classificationInverseGuardDays)
                .nextUp
        let earliestUT = (ut - uncertainty).nextDown
        let latestUT = (ut + uncertainty).nextUp
        guard earliestUT >= -SolarAltitudeBounds.classificationUTLimit,
            latestUT <= SolarAltitudeBounds.classificationUTLimit
        else { throw Unsupported.outsidePolynomialCoverage }
        let receptionStep = Self.crossesModelStep(lower: earliestUT, upper: latestUT, model: deltaTModel)
        let jump = receptionStep ? SolarAltitudeBounds.deltaTJumpDays : 0
        // Within each piece g is increasing. The absolute jump sum also
        // encloses downward steps, for which endpoint images alone fail.
        let earliestTT = Engine.Time(ut: earliestUT, deltaTModel: deltaTModel).tt
        let latestTT = Engine.Time(ut: latestUT, deltaTModel: deltaTModel).tt
        let lowerTT = ((min(tt, forwardTT, earliestTT) - classificationGuard).nextDown - jump).nextDown
        let upperTT = ((max(tt, forwardTT, latestTT) + classificationGuard).nextUp + jump).nextUp
        guard coverage.contains(lowerTT), coverage.contains(upperTT) else {
            throw Unsupported.outsidePolynomialCoverage
        }

        let inverseReference = reference == .terrestrialTime || reference == .civilUTC
        let inverseJump = arrivalStep && inverseReference ? SolarAltitudeBounds.arrivalJumpInverseDegrees : 0
        let civilJump = arrivalStep && reference == .civilUT1 ? SolarAltitudeBounds.arrivalJumpForwardDegrees : 0
        self.time = time
        self.deltaTModel = deltaTModel
        self.observer = observer
        self.reference = reference
        self.altitude = try CelestialBody.sun.horizon(at: time, from: observer, refraction: .none).altitude
        self.errorBound = ErrorBound(
            civilConversion: ErrorBound.addingUp(civilConversion, civilJump),
            scaleConversion: ErrorBound.addingUp(scaleConversion, inverseJump),
            lightTimeTermination: SolarAltitudeBounds.lightTimeDegrees,
            earthRotationAngle: SolarAltitudeBounds.eraDegrees
        )
        if deltaTModel == .iersObserved {
            let seconds = Engine.DeltaT.Observed.uncertainty(ut: ut)
            let degreesPerSecond =
                inverseReference
                ? SolarAltitudeBounds.observedInverseUncertaintyDegreesPerSecond
                : SolarAltitudeBounds.observedForwardUncertaintyDegreesPerSecond
            self.statedUncertainty = StatedUncertainty(
                deltaTSeconds: seconds, altitudeDegrees: (seconds * degreesPerSecond).nextUp)
        } else {
            self.statedUncertainty = nil
        }
    }

    private static func crossesModelStep(lower: Double, upper: Double, model: DeltaTModel) -> Bool {
        if model == .iersObserved { return false }
        return SolarAltitudeBounds.modelStepUTs.contains { boundary in
            if model == .jplHorizons && boundary > 17 * Engine.DeltaT.daysPerTropicalYear { return false }
            return lower <= boundary && boundary <= upper
        }
    }

    static func recorded(_ time: Engine.Time, model: DeltaTModel) -> AstroTime {
        AstroTime(tt: time.tt, ut: time.ut, deltaTModel: model)
    }

    /// The residual `|tt - time.tt|` the engine's TT to UT inverse accepts as
    /// converged, as it writes the expression.
    static func inverseTolerance(terrestrialTime tt: Double) -> Double {
        max(SolarAltitudeBounds.inverseToleranceFloorDays, SolarAltitudeBounds.inverseTolerancePerDay * abs(tt))
    }

    private struct ModelBudget {
        let civilToTTDegrees: Double
        let civilToUTDegrees: Double
        let forwardTTDegrees: Double
        let ttInverseDegrees: Double
        let arrivalUncertaintyBaseDays: Double
        let arrivalUncertaintyDays: Double
        let classificationInverseGuardDays: Double

        init(_ model: DeltaTModel) {
            if model == .iersObserved {
                civilToTTDegrees = SolarAltitudeBounds.observedCivilToTTDegrees
                civilToUTDegrees = SolarAltitudeBounds.observedCivilToUTDegrees
                forwardTTDegrees = SolarAltitudeBounds.observedForwardTTDegrees
                ttInverseDegrees = SolarAltitudeBounds.observedTTInverseDegrees
                arrivalUncertaintyBaseDays = SolarAltitudeBounds.observedArrivalUncertaintyDays
                arrivalUncertaintyDays = SolarAltitudeBounds.observedArrivalUncertaintyDays
                classificationInverseGuardDays = SolarAltitudeBounds.observedClassificationInverseGuardDays
            } else {
                civilToTTDegrees = SolarAltitudeBounds.civilToTTDegrees
                civilToUTDegrees = SolarAltitudeBounds.civilToUTDegrees
                forwardTTDegrees = SolarAltitudeBounds.forwardTTDegrees
                ttInverseDegrees = SolarAltitudeBounds.ttInverseDegrees
                arrivalUncertaintyBaseDays = SolarAltitudeBounds.arrivalUncertaintyBaseDays
                arrivalUncertaintyDays = SolarAltitudeBounds.arrivalUncertaintyDays
                classificationInverseGuardDays = SolarAltitudeBounds.classificationInverseGuardDays
            }
        }
    }
}

// MARK: - Entry points

extension Sun {
    /// The Sun's geometric altitude at a civil UTC date, with its inputs and
    /// derived error bound.
    ///
    /// The native civil conversion and model inverse construct both time
    /// scales. From 1961 on the bound adds the calendar and civil-to-TT rounding, carried into the
    /// derived UT, and the TT to UT inverse; before 1961 it adds the calendar
    /// rounding taken as UT, carried into the derived TT, and the UT to TT
    /// rounding. Either way it adds light-time termination and Earth Rotation
    /// Angle rounding.
    ///
    /// - Parameters:
    ///   - date: The civil UTC instant.
    ///   - observer: The observer, within 10 km of the ellipsoid.
    ///   - deltaTModel: The Delta T model that relates the time's scales.
    /// - Returns: The altitude, its inputs, and the derived bound.
    /// - Throws: ``SolarAltitudeObservation/Unsupported`` for a case the
    ///   budget excludes, ``AstronomyError/badTime`` for a non-finite date or,
    ///   from 1961 on, a TT the inverse does not converge for,
    ///   ``AstronomyError/invalidParameter`` for an invalid observer.
    public static func altitudeObservation(
        at date: Date,
        from observer: Observer,
        deltaTModel: DeltaTModel
    ) throws -> SolarAltitudeObservation {
        let civilDays = AstroTime.civilDays(of: date)
        let nearSegmentStart = CivilTime.segments.contains { segment in
            abs(civilDays - segment.start) <= SolarAltitudeBounds.civilCalendarDays
        }
        guard !nearSegmentStart else {
            throw SolarAltitudeObservation.Unsupported.civilDateAtSegmentStart
        }
        let civil = Engine.Time.civil(utcDays: civilDays, deltaTModel: deltaTModel)
        return try SolarAltitudeObservation(
            time: SolarAltitudeObservation.recorded(civil.time, model: deltaTModel),
            reference: civil.fromTable ? .civilUTC : .civilUT1,
            observer: observer,
            deltaTModel: deltaTModel
        )
    }

    /// The Sun's geometric altitude at a Terrestrial Time, with its inputs and
    /// derived error bound.
    ///
    /// The time stores the supplied TT exactly and derives UT with the
    /// native model inverse. The bound adds the TT to UT inverse, light-time termination, and Earth
    /// Rotation Angle rounding.
    ///
    /// - Parameters:
    ///   - terrestrialTime: TT days since J2000 noon.
    ///   - observer: The observer, within 10 km of the ellipsoid.
    ///   - deltaTModel: The Delta T model that derives UT.
    /// - Returns: The altitude, its inputs, and the derived bound.
    /// - Throws: ``SolarAltitudeObservation/Unsupported`` for a case the
    ///   budget excludes, ``AstronomyError/badTime`` for a non-finite or
    ///   nonconvergent TT, ``AstronomyError/invalidParameter`` for an invalid
    ///   observer.
    public static func altitudeObservation(
        terrestrialTime: Double,
        from observer: Observer,
        deltaTModel: DeltaTModel
    ) throws -> SolarAltitudeObservation {
        try SolarAltitudeObservation(
            time: SolarAltitudeObservation.recorded(
                Engine.Time(tt: terrestrialTime, deltaTModel: deltaTModel), model: deltaTModel),
            reference: .terrestrialTime,
            observer: observer,
            deltaTModel: deltaTModel
        )
    }

    /// The Sun's geometric altitude at a Universal Time, with its inputs and
    /// derived error bound.
    ///
    /// The time stores the supplied UT exactly and derives TT with the
    /// native model. The bound adds the UT to TT rounding, light-time termination, and Earth
    /// Rotation Angle rounding. A time the engine derived, such as a search
    /// result or an ``AstroTime/addingDays(_:)`` result, is rebuilt exactly
    /// from its ``AstroTime/universalTime`` and ``AstroTime/deltaTModel``.
    ///
    /// - Parameters:
    ///   - universalTime: UT1 days since J2000 noon.
    ///   - observer: The observer, within 10 km of the ellipsoid.
    ///   - deltaTModel: The Delta T model that derives TT.
    /// - Returns: The altitude, its inputs, and the derived bound.
    /// - Throws: ``SolarAltitudeObservation/Unsupported`` for a case the
    ///   budget excludes, ``AstronomyError/badTime`` for a non-finite UT,
    ///   ``AstronomyError/invalidParameter`` for an invalid observer.
    public static func altitudeObservation(
        universalTime: Double,
        from observer: Observer,
        deltaTModel: DeltaTModel
    ) throws -> SolarAltitudeObservation {
        try SolarAltitudeObservation(
            time: SolarAltitudeObservation.recorded(
                Engine.Time(ut: universalTime, deltaTModel: deltaTModel), model: deltaTModel),
            reference: .universalTime,
            observer: observer,
            deltaTModel: deltaTModel
        )
    }
}
