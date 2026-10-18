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

        /// Right ascension in sidereal hours on the J2000 equator.
        let rightAscension: Double

        /// Declination in degrees on the J2000 equator.
        let declination: Double

        /// Distance from the Sun in light-years.
        let distance: Double

        /// Optional catalog epoch and space motion.
        let catalogMotion: StarCatalogMotion?

        typealias CatalogMotion = StarCatalogMotion

        init(
            rightAscension: Double,
            declination: Double,
            distance: Double,
            catalogMotion: StarCatalogMotion? = nil
        ) {
            self.rightAscension = rightAscension
            self.declination = declination
            self.distance = distance
            self.catalogMotion = catalogMotion
        }

        /// The star's fixed heliocentric position on J2000 axes.
        func heliocentricPosition(at time: Engine.Time) throws -> Engine.Vector<Engine.EQJ> {
            try validate()
            try Engine.checkAcceptedTime(time)
            guard hasCatalogMotion else { return try fixedPosition(at: time) }
            let catalog = try barycentricCatalogPosition(at: time)
            let sun = try Engine.ApparentPlace.sunBarycentricKinematics(tt: time.tt).motion.value
            return try Engine.Positions.checked(
                Engine.Vector(x: catalog.x - sun.x, y: catalog.y - sun.y, z: catalog.z - sun.z, time: time)
            )
        }

        /// The fixed-position path retained for legacy values without catalog motion.
        private func fixedPosition(at time: Engine.Time) throws -> Engine.Vector<Engine.EQJ> {
            let sphere = Engine.Spherical(
                latitude: declination,
                longitude: 15 * rightAscension,
                distance: distance * Self.astronomicalUnitsPerLightYear
            )
            return try Engine.Positions.checked(Engine.Vector(sphere, time: time))
        }

        /// The propagated barycentric catalog position, rotated from ICRS to the engine's EQJ axes.
        func barycentricCatalogPosition(at time: Engine.Time) throws -> Engine.Vector<Engine.EQJ> {
            try validate()
            try Engine.checkAcceptedTime(time)
            guard let catalogMotion, hasCatalogMotion else { return try fixedPosition(at: time) }
            let icrs = try Engine.StarCatalogPropagation.position(
                rightAscensionHours: rightAscension,
                declinationDegrees: declination,
                distanceLightYears: distance,
                motion: catalogMotion,
                at: time
            )
            return Engine.FrameBias.icrsToEqj.apply(to: icrs)
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

        /// Catalog light time is implicit in a fixed-star definition (Kaplan 1998, section 2).
        private func apparentPosition(
            at time: Engine.Time, site: Observer?, aberration: Aberration
        ) throws -> Engine.Vector<Engine.EQJ> {
            try validate()
            try Engine.checkAcceptedTime(time)
            let earth = try Engine.ApparentPlace.earthBarycentricKinematics(tt: time.tt)
            let sun = try Engine.ApparentPlace.sunBarycentricKinematics(tt: time.tt)
            let offset =
                try site.map { try Engine.ApparentPlace.siteKinematics($0, at: time) }
                ?? Engine.ApparentPlace.Kinematics(motion: .init(.zero), acceleration: .zero)
            let observer = Engine.ApparentPlace.Kinematics(
                motion: earth.motion + offset.motion, acceleration: earth.acceleration + offset.acceleration)
            let solarOffset = observer.motion - sun.motion
            let displacement: Engine.ApparentPlace.VectorRate
            if let catalogMotion {
                let observerICRS = Engine.FrameBias.icrsToEqj.inverse.apply(to: observer.motion.value)
                let icrs = try Engine.StarCatalogPropagation.position(
                    rightAscensionHours: rightAscension,
                    declinationDegrees: declination,
                    distanceLightYears: distance,
                    motion: catalogMotion,
                    at: time,
                    observerBarycentricICRS: observerICRS
                )
                let star = Engine.FrameBias.icrsToEqj.apply(to: icrs)
                displacement = Engine.ApparentPlace.VectorRate(SIMD3(star.x, star.y, star.z)) - observer.motion
            } else {
                let star = try fixedPosition(at: time)
                displacement = Engine.ApparentPlace.VectorRate(SIMD3(star.x, star.y, star.z)) - solarOffset
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
        }

        private var hasCatalogMotion: Bool {
            catalogMotion != nil
        }

        /// Checks the public observer limits without constructing a C observer.
        private static func validate(_ observer: Observer) throws {
            guard observer.latitude.isFinite, observer.longitude.isFinite, observer.height.isFinite,
                (-90...90).contains(observer.latitude)
            else { throw AstronomyError.invalidParameter }
        }
    }
}
