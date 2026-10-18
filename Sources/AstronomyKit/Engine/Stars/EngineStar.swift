//
//  EngineStar.swift
//  AstronomyKit
//
//  Immutable fixed-star definitions and native position calculations.
//

import Foundation

extension Engine {
    /// A fixed star at a catalog position on the mean equator and equinox of J2000.
    struct Star: Equatable, Hashable, Sendable {
        /// The C engine's conversion, retained as part of the fixed-star distance contract.
        static let astronomicalUnitsPerLightYear = 63_241.077_088_075_46

        struct Motion: Equatable, Hashable, Sendable {
            let parallax: Double
            let properMotionRightAscension: Double
            let properMotionDeclination: Double
            let radialVelocity: Double
            let epoch: Double
        }

        /// Right ascension in sidereal hours on the J2000 equator.
        let rightAscension: Double

        /// Declination in degrees on the J2000 equator.
        let declination: Double

        /// Distance from the Sun in light-years.
        let distance: Double

        /// ICRS catalog motion, using Gaia's μα* convention.
        let motion: Motion?

        init(rightAscension: Double, declination: Double, distance: Double, motion: Motion? = nil) {
            self.rightAscension = rightAscension
            self.declination = declination
            self.distance = distance
            self.motion = motion
        }

        init(rightAscension: Double, declination: Double, motion: Motion) {
            self.init(
                rightAscension: rightAscension,
                declination: declination,
                distance: 206_264_806.247_096_36 / motion.parallax / Self.astronomicalUnitsPerLightYear,
                motion: motion
            )
        }

        /// The star's fixed heliocentric position on J2000 axes.
        func heliocentricPosition(at time: Engine.Time) throws -> Engine.Vector<Engine.EQJ> {
            try validate()
            try Engine.checkAcceptedTime(time)
            let sphere = Engine.Spherical(
                latitude: declination,
                longitude: 15 * rightAscension,
                distance: distance * Self.astronomicalUnitsPerLightYear
            )
            return try Engine.Positions.checked(Engine.Vector(sphere, time: time))
        }

        /// Propagates ICRS catalog data with the light-time and special-relativity steps from SOFA `iauStarpm` 2023-10-11. This is an independent Swift adaptation and is not SOFA software or endorsed by the SOFA Board. Unlike SOFA, invalid parallaxes and excessive speeds are rejected instead of replaced by fallback values.
        func catalogPosition(
            at time: Engine.Time, observer: SIMD3<Double> = .zero
        ) throws -> Engine.Vector<Engine.ICRS> {
            try validate()
            try Engine.checkAcceptedTime(time)
            guard let motion, observer.x.isFinite, observer.y.isFinite, observer.z.isFinite else {
                throw AstronomyError.invalidParameter
            }

            let alpha = rightAscension / Engine.hoursPerRadian
            let delta = declination / Engine.degreesPerRadian
            let cosAlpha = cos(alpha)
            let sinAlpha = sin(alpha)
            let cosDelta = cos(delta)
            let sinDelta = sin(delta)
            let radius = 206_264_806.247_096_36 / motion.parallax
            let radialRate = motion.radialVelocity * 86_400 / Engine.kilometersPerAU
            let rateScale = Engine.radiansPerArcsecond / 1_000 / 365.25
            let alphaRate = motion.properMotionRightAscension * rateScale
            let deltaRate = motion.properMotionDeclination * rateScale
            let unit = SIMD3(cosDelta * cosAlpha, cosDelta * sinAlpha, sinDelta)
            let alphaTangent = SIMD3(-sinAlpha, cosAlpha, 0)
            let deltaTangent = SIMD3(-sinDelta * cosAlpha, -sinDelta * sinAlpha, cosDelta)
            let position = radius * unit
            let observedVelocity = radius * (alphaRate * alphaTangent + deltaRate * deltaTangent) + radialRate * unit
            let speed = Self.length(observedVelocity)
            guard speed.isFinite, speed / Engine.speedOfLightAUPerDay <= 0.5 else {
                throw AstronomyError.invalidParameter
            }

            let observedRadial = Self.dot(unit, observedVelocity)
            let observedTangential = observedVelocity - observedRadial * unit
            let radialBeta = observedRadial / Engine.speedOfLightAUPerDay
            let tangentialBeta = Self.length(observedTangential) / Engine.speedOfLightAUPerDay
            var correctedRadialBeta = radialBeta
            var correctedTangentialBeta = tangentialBeta
            var d = 0.0
            var correction = 0.0
            var previousD = 0.0
            var previousCorrection = 0.0
            var previousDeltaD = 0.0
            var previousDeltaCorrection = 0.0
            var converged = false
            for iteration in 0..<100 {
                d = 1 + correctedRadialBeta
                let betaSquared =
                    correctedRadialBeta * correctedRadialBeta + correctedTangentialBeta * correctedTangentialBeta
                guard betaSquared < 1 else { throw AstronomyError.invalidParameter }
                correction = -betaSquared / (sqrt(1 - betaSquared) + 1)
                correctedRadialBeta = d * radialBeta + correction
                correctedTangentialBeta = d * tangentialBeta
                if iteration > 0 {
                    let deltaD = abs(d - previousD)
                    let deltaCorrection = abs(correction - previousCorrection)
                    if iteration > 1, deltaD >= previousDeltaD, deltaCorrection >= previousDeltaCorrection {
                        converged = true
                        break
                    }
                    previousDeltaD = deltaD
                    previousDeltaCorrection = deltaCorrection
                }
                previousD = d
                previousCorrection = correction
            }
            guard converged else { throw AstronomyError.invalidParameter }

            let inertialVelocity =
                d * observedTangential + Engine.speedOfLightAUPerDay * (d * radialBeta + correction) * unit
            let sourceLightTime = radius / Engine.speedOfLightAUPerDay
            let interval = time.tt - (motion.epoch - 2_000) * 365.25
            let geometricPosition = position + (interval + sourceLightTime) * inertialVelocity
            let geometricDisplacement = geometricPosition - observer
            let distanceSquared = Self.dot(geometricDisplacement, geometricDisplacement)
            let radialProduct = Self.dot(geometricDisplacement, inertialVelocity)
            let speedSquared = Self.dot(inertialVelocity, inertialVelocity)
            let lightDenominator = Engine.speedOfLightAUPerDay * Engine.speedOfLightAUPerDay - speedSquared
            guard distanceSquared.isFinite, radialProduct.isFinite, lightDenominator > 0 else {
                throw AstronomyError.badTime
            }
            let targetLightTime =
                (-radialProduct + sqrt(radialProduct * radialProduct + lightDenominator * distanceSquared))
                / lightDenominator
            let result = position + (interval + sourceLightTime - targetLightTime) * inertialVelocity
            return try Engine.Positions.checked(Engine.Vector(x: result.x, y: result.y, z: result.z, time: time))
        }

        /// The star's position relative to Earth on J2000 axes.
        func geocentricPosition(at time: Engine.Time, aberration: Aberration) throws -> Engine.Vector<Engine.EQJ> {
            try apparentPosition(at: time, site: nil, aberration: aberration)
        }

        /// The apparent topocentric coordinates on the requested equator.
        func equatorial(
            at time: Engine.Time,
            from observer: Observer,
            equatorDate: EquatorDate
        ) throws -> Engine.Equatorial {
            try validate()
            try Self.validate(observer)
            let j2000 = try apparentPosition(at: time, site: observer, aberration: .corrected)
            let result =
                switch equatorDate {
                case .j2000:
                    try Engine.Positions.coordinates(j2000)
                case .ofDate:
                    try Engine.Positions.coordinates(Engine.FrameRotation.eqjToEqd(time).apply(to: j2000))
                }
            guard result.rightAscension.isFinite, result.declination.isFinite, result.distance.isFinite else {
                throw AstronomyError.badTime
            }
            return result
        }

        /// The apparent geocentric coordinates on the true ecliptic and equinox of date.
        func ecliptic(at time: Engine.Time) throws -> Engine.Ecliptic {
            let result = Engine.Ecliptic(try geocentricPosition(at: time, aberration: .corrected))
            guard result.vector.x.isFinite, result.vector.y.isFinite, result.vector.z.isFinite,
                result.latitude.isFinite, result.longitude.isFinite
            else { throw AstronomyError.badTime }
            return result
        }

        /// The apparent topocentric coordinates in an observer's sky.
        func horizontal(
            at time: Engine.Time,
            from observer: Observer,
            refraction: Refraction
        ) throws -> Engine.Horizontal {
            let equatorial = try equatorial(at: time, from: observer, equatorDate: .ofDate)
            return Engine.Horizontal(
                time: time,
                observer: observer,
                rightAscension: equatorial.rightAscension,
                declination: equatorial.declination,
                refraction: refraction
            )
        }

        /// Catalog light time is implicit in a fixed-star definition (Kaplan 1998, section 2). Legacy vectors remain heliocentric; propagated ICRS vectors are barycentric.
        private func apparentPosition(
            at time: Engine.Time, site: Observer?, aberration: Aberration
        ) throws -> Engine.Vector<Engine.EQJ> {
            let earth = try Engine.ApparentPlace.earthBarycentricKinematics(tt: time.tt)
            let sun = try Engine.ApparentPlace.sunBarycentricKinematics(tt: time.tt)
            let offset =
                try site.map { try Engine.ApparentPlace.siteKinematics($0, at: time) }
                ?? Engine.ApparentPlace.Kinematics(motion: .init(.zero), acceleration: .zero)
            let observer = Engine.ApparentPlace.Kinematics(
                motion: earth.motion + offset.motion, acceleration: earth.acceleration + offset.acceleration)
            let solarOffset = observer.motion - sun.motion
            let displacement: Engine.ApparentPlace.VectorRate
            if motion == nil {
                let star = try heliocentricPosition(at: time)
                displacement = Engine.ApparentPlace.VectorRate(SIMD3(star.x, star.y, star.z)) - solarOffset
            } else {
                let icrsObserver = Engine.FrameBias.icrsToEqj.inverse.apply(
                    to: Engine.Vector<Engine.EQJ>(
                        x: observer.motion.value.x,
                        y: observer.motion.value.y,
                        z: observer.motion.value.z,
                        time: time
                    ))
                let star = Engine.FrameBias.icrsToEqj.apply(
                    to: try catalogPosition(
                        at: time,
                        observer: SIMD3(icrsObserver.x, icrsObserver.y, icrsObserver.z)
                    ))
                displacement = Engine.ApparentPlace.VectorRate(SIMD3(star.x, star.y, star.z)) - observer.motion
            }
            let result: Engine.ApparentPlace.VectorRate
            if aberration == .none {
                result = displacement
            } else {
                result = try Engine.ApparentPlace.correctedMotion(
                    displacement, sunToObserver: solarOffset,
                    beta: Engine.ApparentPlace.observerBeta(observer, atTT: time.tt), solarSource: false)
            }
            return try Engine.Positions.checked(
                Engine.Vector(x: result.value.x, y: result.value.y, z: result.value.z, time: time))
        }

        /// Checks the public fixed-star catalog limits.
        private func validate() throws {
            guard rightAscension.isFinite, (0..<24).contains(rightAscension), declination.isFinite,
                (-90...90).contains(declination), distance.isFinite, distance >= 1
            else { throw AstronomyError.invalidParameter }
            if let motion {
                guard motion.parallax.isFinite, motion.parallax > 0,
                    motion.properMotionRightAscension.isFinite, motion.properMotionDeclination.isFinite,
                    motion.radialVelocity.isFinite, motion.epoch.isFinite
                else { throw AstronomyError.invalidParameter }
            }
        }

        /// Checks the public observer limits without constructing a C observer.
        private static func validate(_ observer: Observer) throws {
            guard observer.latitude.isFinite, observer.longitude.isFinite, observer.height.isFinite,
                (-90...90).contains(observer.latitude)
            else { throw AstronomyError.invalidParameter }
        }

        private static func dot(_ a: SIMD3<Double>, _ b: SIMD3<Double>) -> Double {
            a.x * b.x + a.y * b.y + a.z * b.z
        }

        private static func length(_ vector: SIMD3<Double>) -> Double {
            dot(vector, vector).squareRoot()
        }
    }
}
