//
//  EngineStarCatalogPropagation.swift
//  AstronomyKit
//
//  Barycentric catalog space-motion propagation.
//

import Foundation

extension Engine {
    /// This implementation uses routines and computations derived from the IAU SOFA `iauPmsafe`, `iauStarpm`, and `iauStarpv` algorithms under the license reproduced in `THIRD_PARTY_NOTICES`. It is a Swift adaptation specialized to return the propagated position vector, rejects every SOFA warning instead of returning a status, and does not itself constitute software provided by or endorsed by SOFA.
    enum StarCatalogPropagation {
        private struct State {
            var position: SIMD3<Double>
            var velocity: SIMD3<Double>
        }

        private static let arcsecondsPerRadian = 206_264.806_247_096_36
        private static let astronomicalUnitMeters = 149_597_870_700.0
        private static let daysPerJulianYear = 365.25
        private static let milliarcsecondsToRadians = Engine.radiansPerArcsecond / 1_000

        static func position(
            rightAscensionHours: Double,
            declinationDegrees: Double,
            distanceLightYears: Double,
            motion: StarCatalogMotion,
            at time: Engine.Time,
            targetTCBDaysFromJ2000 override: Double? = nil
        ) throws -> Engine.Vector<Engine.EQJ> {
            let ra = rightAscensionHours * 15 * Engine.radiansPerDegree
            let dec = declinationDegrees * Engine.radiansPerDegree
            let cosine = cos(dec)
            let alphaStar = motion.rightAscensionCosDeclinationMilliarcsecondsPerJulianYear * milliarcsecondsToRadians
            guard alphaStar == 0 || abs(cosine) > 1e-15 else { throw AstronomyError.invalidParameter }
            let alphaRate = alphaStar == 0 ? 0 : alphaStar / cosine
            let deltaRate = motion.declinationMilliarcsecondsPerJulianYear * milliarcsecondsToRadians
            let parallax = arcsecondsPerRadian / (distanceLightYears * Engine.Star.astronomicalUnitsPerLightYear)
            guard alphaRate.isFinite, deltaRate.isFinite, parallax.isFinite else {
                throw AstronomyError.invalidParameter
            }

            // `iauPmsafe` raises too-small parallaxes to these limits. Reject that warning so the caller's distance is never replaced silently.
            let oneYearMotion = angularSeparation(ra, dec, ra + alphaRate, dec + deltaRate)
            guard oneYearMotion.isFinite, parallax >= max(5e-7, 326 * oneYearMotion) else {
                throw AstronomyError.invalidParameter
            }

            let initial = try catalogState(
                rightAscension: ra,
                declination: dec,
                rightAscensionRate: alphaRate,
                declinationRate: deltaRate,
                parallaxArcseconds: parallax,
                radialVelocityKilometersPerSecond: motion.radialVelocityKilometersPerSecond
            )
            let initialLightTime = norm(initial.position) / Engine.speedOfLightAUPerDay
            let epochTCB = (motion.epochJulianYear - 2_000) * daysPerJulianYear
            let targetTCB = override ?? tcbDaysFromJ2000(at: time)
            let interval = targetTCB - epochTCB
            let geometric = advance(initial, days: interval + initialLightTime)
            let radiusSquared = dot(geometric.position, geometric.position)
            let radialDotVelocity = dot(geometric.position, geometric.velocity)
            let speedSquared = dot(geometric.velocity, geometric.velocity)
            let denominator = Engine.speedOfLightAUPerDay * Engine.speedOfLightAUPerDay - speedSquared
            guard denominator > 0 else { throw AstronomyError.invalidParameter }
            let discriminant = radialDotVelocity * radialDotVelocity + denominator * radiusSquared
            guard discriminant >= 0, discriminant.isFinite else { throw AstronomyError.invalidParameter }
            let finalLightTime = (-radialDotVelocity + sqrt(discriminant)) / denominator
            let result = advance(initial, days: interval + initialLightTime - finalLightTime).position
            guard result.x.isFinite, result.y.isFinite, result.z.isFinite else { throw AstronomyError.badTime }
            return Engine.Vector(x: result.x, y: result.y, z: result.z, time: time)
        }

        /// IAU 2006 TDB to TCB, adapted from SOFA `iauTdbtcb` with J2000 as the fixed first Julian-date part.
        private static func tcbDaysFromJ2000(at time: Engine.Time) -> Double {
            let tdb = time.tt + Engine.TDB.offsetSeconds(tt: time.tt) / Engine.secondsPerDay
            let t77MinusJ2000 = 2_443_144.5 - 2_451_545
            let t77Fraction = 32.184 / Engine.secondsPerDay
            let tdbAt1977TAI = -6.55e-5 / Engine.secondsPerDay
            let barycentricRate = 1.550_519_768e-8
            let rateRatio = barycentricRate / (1 - barycentricRate)
            let fraction = tdb - tdbAt1977TAI
            return fraction - (t77MinusJ2000 - (fraction - t77Fraction)) * rateRatio
        }

        /// SOFA `iauStarpv`, specialized to reject all warning statuses.
        private static func catalogState(
            rightAscension ra: Double,
            declination dec: Double,
            rightAscensionRate: Double,
            declinationRate: Double,
            parallaxArcseconds: Double,
            radialVelocityKilometersPerSecond: Double
        ) throws -> State {
            guard parallaxArcseconds >= 1e-7 else { throw AstronomyError.invalidParameter }
            let radius = arcsecondsPerRadian / parallaxArcseconds
            let radialRate = Engine.secondsPerDay * radialVelocityKilometersPerSecond * 1_000 / astronomicalUnitMeters
            let state = sphericalState(
                longitude: ra,
                latitude: dec,
                radius: radius,
                longitudeRate: rightAscensionRate / daysPerJulianYear,
                latitudeRate: declinationRate / daysPerJulianYear,
                radiusRate: radialRate
            )
            guard norm(state.velocity) / Engine.speedOfLightAUPerDay <= 0.5 else {
                throw AstronomyError.invalidParameter
            }
            let unit = state.position / norm(state.position)
            let observedRadialSpeed = dot(unit, state.velocity)
            let observedRadial = observedRadialSpeed * unit
            let observedTransverse = state.velocity - observedRadial
            let betaRadial = observedRadialSpeed / Engine.speedOfLightAUPerDay
            let betaTransverse = norm(observedTransverse) / Engine.speedOfLightAUPerDay
            var transverse = betaTransverse
            var radial = betaRadial
            var scale = 0.0
            var correction = 0.0
            var oldScale = 0.0
            var oldCorrection = 0.0
            var oldScaleDelta = 0.0
            var oldCorrectionDelta = 0.0
            var converged = false
            for iteration in 0..<100 {
                scale = 1 + radial
                let betaSquared = radial * radial + transverse * transverse
                guard betaSquared < 1 else { throw AstronomyError.invalidParameter }
                correction = -betaSquared / (sqrt(1 - betaSquared) + 1)
                radial = scale * betaRadial + correction
                transverse = scale * betaTransverse
                if iteration > 0 {
                    let scaleDelta = abs(scale - oldScale)
                    let correctionDelta = abs(correction - oldCorrection)
                    if iteration > 1, scaleDelta >= oldScaleDelta, correctionDelta >= oldCorrectionDelta {
                        converged = true
                        break
                    }
                    oldScaleDelta = scaleDelta
                    oldCorrectionDelta = correctionDelta
                }
                oldScale = scale
                oldCorrection = correction
            }
            guard converged else { throw AstronomyError.invalidParameter }
            let inertialTransverse = scale * observedTransverse
            let inertialRadial = Engine.speedOfLightAUPerDay * (scale * betaRadial + correction) * unit
            return State(position: state.position, velocity: inertialRadial + inertialTransverse)
        }

        private static func sphericalState(
            longitude: Double,
            latitude: Double,
            radius: Double,
            longitudeRate: Double,
            latitudeRate: Double,
            radiusRate: Double
        ) -> State {
            let sinLongitude = sin(longitude)
            let cosLongitude = cos(longitude)
            let sinLatitude = sin(latitude)
            let cosLatitude = cos(latitude)
            let projectedRadius = radius * cosLatitude
            let x = projectedRadius * cosLongitude
            let y = projectedRadius * sinLongitude
            let latitudeVelocity = radius * latitudeRate
            let radialCombination = latitudeVelocity * sinLatitude - cosLatitude * radiusRate
            return State(
                position: SIMD3(x, y, radius * sinLatitude),
                velocity: SIMD3(
                    -y * longitudeRate - radialCombination * cosLongitude,
                    x * longitudeRate - radialCombination * sinLongitude,
                    latitudeVelocity * cosLatitude + sinLatitude * radiusRate
                )
            )
        }

        private static func angularSeparation(
            _ longitude1: Double, _ latitude1: Double, _ longitude2: Double, _ latitude2: Double
        ) -> Double {
            let first = unit(longitude: longitude1, latitude: latitude1)
            let second = unit(longitude: longitude2, latitude: latitude2)
            return atan2(norm(cross(first, second)), dot(first, second))
        }

        private static func unit(longitude: Double, latitude: Double) -> SIMD3<Double> {
            SIMD3(cos(latitude) * cos(longitude), cos(latitude) * sin(longitude), sin(latitude))
        }

        private static func advance(_ state: State, days: Double) -> State {
            State(position: state.position + days * state.velocity, velocity: state.velocity)
        }

        private static func dot(_ left: SIMD3<Double>, _ right: SIMD3<Double>) -> Double {
            (left * right).sum()
        }

        private static func norm(_ vector: SIMD3<Double>) -> Double {
            sqrt(dot(vector, vector))
        }

        private static func cross(_ left: SIMD3<Double>, _ right: SIMD3<Double>) -> SIMD3<Double> {
            SIMD3(
                left.y * right.z - left.z * right.y, left.z * right.x - left.x * right.z,
                left.x * right.y - left.y * right.x)
        }
    }
}
