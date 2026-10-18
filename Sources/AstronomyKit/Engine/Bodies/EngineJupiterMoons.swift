//
//  EngineJupiterMoons.swift
//  AstronomyKit
//
//  The states of Jupiter's four largest moons from the L1.2 theory.
//

import Foundation

extension Engine {
    /// The fixed jovicentric frame of the L1.2 theory, close to Jupiter's
    /// equator of J2000 (the C engine's JUP).
    enum JUP: Frame {}

    /// Io, Europa, Ganymede and Callisto from the L1.2 theory of Lainey,
    /// Duriez and Vienne (2006, A&A 456, 783), as IMCCE publishes it in
    /// `BisL1.2.dat` (see `Scripts/jupiter-moon-data/manifest.json`).
    ///
    /// Each moon has six orbital elements, each a series of terms
    /// `amplitude × cos(phase + frequency × t)` or `sin`, with `t` in TT days
    /// from 1950-01-01 00:00 TT. The engine keeps the leading terms of each
    /// series, as the C engine does: 75 of the 490 published, the
    /// generated `models`. It leaves out the theory's Chebyshev corrections
    /// for long-period effects, which apply only from about 1130 to 2763.
    enum JupiterMoons {
        enum Moon: Int, CaseIterable, Sendable {
            case io, europa, ganymede, callisto
        }

        /// The four moons' states at one time.
        struct States: Sendable {
            var io: Engine.State<Engine.EQJ>
            var europa: Engine.State<Engine.EQJ>
            var ganymede: Engine.State<Engine.EQJ>
            var callisto: Engine.State<Engine.EQJ>
        }

        /// One term of a series: amplitude in AU or radians, phase in
        /// radians, frequency in radians per day.
        struct Term: Sendable {
            let amplitude: Double
            let phase: Double
            let frequency: Double

            init(_ amplitude: Double, _ phase: Double, _ frequency: Double) {
                (self.amplitude, self.phase, self.frequency) = (amplitude, phase, frequency)
            }
        }

        /// One moon's series.
        struct Model: Sendable {
            /// G × (Jupiter's mass + the moon's) in AU³ per day².
            let mu: Double
            /// The mean longitude's phase in radians and rate in radians per day.
            let meanLongitude: (phase: Double, rate: Double)
            /// Semi-major axis (cosine terms), mean longitude (sine terms),
            /// z = k + ih = e·exp(iϖ), and ζ = q + ip = sin(i/2)·exp(iΩ).
            let a, l, z, zeta: [Term]
        }

        /// Orbital elements in the ``Engine/JUP`` frame: semi-major axis in
        /// AU, mean longitude in [0, 2π), the eccentricity vector (k, h)
        /// and the inclination vector (q, p).
        struct Elements: Sendable {
            var a, meanLongitude, k, h, q, p: Double
        }
    }
}

extension Engine.JupiterMoons {
    /// From ``Engine/JUP`` to ``Engine/EQJ``, built from the generated ``psi`` and
    /// ``inclination`` as the theory's `L1.2.f` applies them.
    static let jupiterToEQJ: Engine.Rotation<Engine.JUP, Engine.EQJ> = {
        let (sinPsi, cosPsi) = (sin(psi), cos(psi))
        let (sinI, cosI) = (sin(inclination), cos(inclination))
        return Engine.Rotation(
            rot: (
                (cosPsi, sinPsi, 0),
                (-sinPsi * cosI, cosPsi * cosI, sinI),
                (sinI * sinPsi, -sinI * cosPsi, cosI)
            ))
    }()

    /// The most Newton steps ``eccentricAnomaly(meanLongitude:k:h:)`` takes.
    ///
    /// The series keep each eccentricity below 0.0104, the sum of Europa's
    /// z amplitudes. Kepler's equation then has a derivative between
    /// 1 − e and 1 + e and a second derivative below e, so each step
    /// leaves at most e / (2(1 − e)) times the square of the error before
    /// it, and the first guess is within e². The third step is below
    /// 1e-22 and stops the iteration. The limit leaves room.
    static let keplerIterationLimit = 10

    /// The four moons' jovicentric states at `time` (`Astronomy_JupiterMoons`).
    ///
    /// - Throws: `AstronomyError.badTime` when |TT| is above
    ///   ``Engine/acceptedTTDays`` or is not finite, or a state is not
    ///   finite.
    static func states(at time: Engine.Time) throws -> States {
        try Engine.checkAcceptedTime(time)
        if let states = Jup365.states(at: time) { return states }
        return States(
            io: try state(of: .io, at: time),
            europa: try state(of: .europa, at: time),
            ganymede: try state(of: .ganymede, at: time),
            callisto: try state(of: .callisto, at: time)
        )
    }

    /// `moon`'s position in AU and velocity in AU per TT day relative to
    /// Jupiter's center, on the mean equator and equinox of J2000, at
    /// `time`. Inside jup365 the velocity is the analytic derivative of its
    /// Chebyshev position. Outside the finite endpoint bridges it is L1.2's
    /// Keplerian velocity; each bridge matches both returned endpoint states.
    ///
    /// - Throws: As ``states(at:)``.
    static func state(of moon: Moon, at time: Engine.Time) throws -> Engine.State<Engine.EQJ> {
        try Engine.checkAcceptedTime(time)
        return try selectedState(of: moon, at: time)
    }

    /// The state `model` gives at `time`, rotated to ``Engine/EQJ``, without
    /// checking the time against the accepted range.
    ///
    /// - Throws: `AstronomyError.badTime` when the state is not finite, or
    ///   as ``eccentricAnomaly(meanLongitude:k:h:)``.
    static func state(_ model: Model, at time: Engine.Time) throws -> Engine.State<Engine.EQJ> {
        let jovian = try jovicentricState(elements(of: model, tt: time.tt), mu: model.mu, time: time)
        return try Engine.Positions.checked(jupiterToEQJ.apply(to: jovian))
    }

    /// The elements of `model` at `tt`, TT days from J2000, summing each
    /// series in its published order.
    static func elements(of model: Model, tt: Double) -> Elements {
        let t = tt - epochTT
        var a = 0.0
        for term in model.a {
            a += term.amplitude * cos(term.phase + t * term.frequency)
        }
        var meanLongitude = model.meanLongitude.phase + t * model.meanLongitude.rate
        for term in model.l {
            meanLongitude += term.amplitude * sin(term.phase + t * term.frequency)
        }
        meanLongitude = Engine.normalized(meanLongitude.truncatingRemainder(dividingBy: 2 * .pi), period: 2 * .pi)
        let (k, h) = complexSum(model.z, t: t)
        let (q, p) = complexSum(model.zeta, t: t)
        return Elements(a: a, meanLongitude: meanLongitude, k: k, h: h, q: q, p: p)
    }

    /// The real and imaginary parts of Σ amplitude × exp(i(phase + frequency × t)).
    private static func complexSum(_ terms: [Term], t: Double) -> (real: Double, imaginary: Double) {
        var (real, imaginary) = (0.0, 0.0)
        for term in terms {
            let argument = term.phase + t * term.frequency
            real += term.amplitude * cos(argument)
            imaginary += term.amplitude * sin(argument)
        }
        return (real, imaginary)
    }

    /// The eccentric longitude F solving Kepler's equation
    /// F − k sin F + h cos F = λ by Newton's method, stopping once a step is
    /// below 1e-12 radians.
    ///
    /// - Throws: `AstronomyError.noConvergence` when no step is below
    ///   1e-12 within ``keplerIterationLimit`` steps. A step that is not a
    ///   number stops the iteration, as in L1.2's `ELEM2PV`, and leaves a
    ///   result that is not a number.
    static func eccentricAnomaly(meanLongitude: Double, k: Double, h: Double) throws -> Double {
        var anomaly = meanLongitude + k * sin(meanLongitude) - h * cos(meanLongitude)
        for _ in 0..<keplerIterationLimit {
            let (cosine, sine) = (cos(anomaly), sin(anomaly))
            let step = (meanLongitude - anomaly + k * sine - h * cosine) / (1 - k * cosine - h * sine)
            anomaly += step
            if !(abs(step) >= 1e-12) { return anomaly }
        }
        throw AstronomyError.noConvergence
    }

    /// The state in AU and AU per day in the ``Engine/JUP`` frame of a body
    /// on the Keplerian orbit `elements` about a center with
    /// G × (total mass) `mu` in AU³ per day²: L1.2's `ELEM2PV`.
    ///
    /// - Throws: As ``eccentricAnomaly(meanLongitude:k:h:)``.
    static func jovicentricState(
        _ elements: Elements, mu: Double, time: Engine.Time
    ) throws -> Engine.State<Engine.JUP> {
        let (a, k, h, q, p) = (elements.a, elements.k, elements.h, elements.q, elements.p)
        let meanMotion = (mu / (a * a * a)).squareRoot()
        let anomaly = try eccentricAnomaly(meanLongitude: elements.meanLongitude, k: k, h: h)
        let (cosine, sine) = (cos(anomaly), sin(anomaly))
        let dle = h * cosine - k * sine
        let rsam1 = -k * cosine - h * sine
        let asr = 1 / (1 + rsam1)
        let phi = (1 - k * k - h * h).squareRoot()
        let psi = 1 / (1 + phi)
        let x1 = a * (cosine - k - psi * h * dle)
        let y1 = a * (sine - h + psi * k * dle)
        let vx1 = meanMotion * asr * a * (-sine - psi * h * rsam1)
        let vy1 = meanMotion * asr * a * (cosine + psi * k * rsam1)
        let f2 = 2 * (1 - q * q - p * p).squareRoot()
        let p2 = 1 - 2 * p * p
        let q2 = 1 - 2 * q * q
        let pq = 2 * p * q
        return Engine.State(
            x: x1 * p2 + y1 * pq,
            y: x1 * pq + y1 * q2,
            z: (q * y1 - x1 * p) * f2,
            vx: vx1 * p2 + vy1 * pq,
            vy: vx1 * pq + vy1 * q2,
            vz: (q * vy1 - vx1 * p) * f2,
            time: time
        )
    }
}
