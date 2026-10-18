//
//  EngineJupiterMoonsJup365.swift
//  AstronomyKit
//
//  JPL jup365 states and the finite joins to the L1.2 fallback.
//

import Foundation

extension Engine.JupiterMoons {
    /// The qualified mixed-precision jup365 table compiled into the package.
    enum Jup365 {
        struct Component {
            let recordDays: Double
            let recordCount: Int
            let sourceCoefficientCount: Int
            let keptCoefficientCount: Int
            let float32CoefficientCount: Int
            let recordBytes: Int
            let tailScales: [[Double]]
            let chunks: [StaticString]

            var encodedRecordBytes: Int { 4 * recordBytes / 3 }
            var encodedLineBytes: Int { encodedRecordBytes + 1 }
        }

        struct SourceState {
            let positionKm: SIMD3<Double>
            let velocityKmPerTDBDay: SIMD3<Double>
        }

        /// The exterior bridge is finite. The complete half-open source domain remains an unblended jup365 evaluation.
        static let transitionDays = 32.0
        static let j2000 = 2_451_545.0
        static let startTDBDays = startJDTDB - j2000
        static let exclusiveEndTDBDays = exclusiveEndJDTDB - j2000
    }
}

extension Engine.JupiterMoons.Jup365 {
    static func decodedByte(_ raw: Int, recordBase: Int, bytes: UnsafeBufferPointer<UInt8>) -> UInt8? {
        let group = recordBase + raw / 3 * 4
        let slot = raw % 3
        guard group + slot + 1 < bytes.count, let a = sextet(bytes[group + slot]),
            let b = sextet(bytes[group + slot + 1])
        else { return nil }
        switch slot {
        case 0: return UInt8((a << 2) | (b >> 4))
        case 1: return UInt8(((a << 4) | (b >> 2)) & 255)
        default: return UInt8(((a << 6) | b) & 255)
        }
    }

    static func sextet(_ byte: UInt8) -> UInt64? {
        switch byte {
        case 65...90: UInt64(byte - 65)
        case 97...122: UInt64(byte - 71)
        case 48...57: UInt64(byte + 4)
        case 43: 62
        case 47: 63
        default: nil
        }
    }

    static func coefficient(
        axis: Int, degree: Int, component: Component, recordBase: Int, bytes: UnsafeBufferPointer<UInt8>
    ) -> Double? {
        let tailCount = component.keptCoefficientCount - component.float32CoefficientCount
        let axisBytes = 4 * component.float32CoefficientCount + 2 * tailCount
        let axisBase = axis * axisBytes
        if degree < component.float32CoefficientCount {
            let raw = axisBase + 4 * degree
            guard let b0 = decodedByte(raw, recordBase: recordBase, bytes: bytes),
                let b1 = decodedByte(raw + 1, recordBase: recordBase, bytes: bytes),
                let b2 = decodedByte(raw + 2, recordBase: recordBase, bytes: bytes),
                let b3 = decodedByte(raw + 3, recordBase: recordBase, bytes: bytes)
            else { return nil }
            let bits = UInt32(b0) | UInt32(b1) << 8 | UInt32(b2) << 16 | UInt32(b3) << 24
            return Double(Float(bitPattern: bits))
        }
        let tail = degree - component.float32CoefficientCount
        guard tail >= 0, tail < tailCount,
            let b0 = decodedByte(
                axisBase + 4 * component.float32CoefficientCount + 2 * tail, recordBase: recordBase, bytes: bytes),
            let b1 = decodedByte(
                axisBase + 4 * component.float32CoefficientCount + 2 * tail + 1, recordBase: recordBase, bytes: bytes)
        else { return nil }
        let integer = Int16(bitPattern: UInt16(b0) | UInt16(b1) << 8)
        return Double(integer) * component.tailScales[axis][tail]
    }

    static func recordIndex(_ component: Component, atTDBDays tdb: Double, includingExclusiveEnd: Bool) -> Int? {
        let inDomain =
            tdb >= startTDBDays && (tdb < exclusiveEndTDBDays || includingExclusiveEnd && tdb == exclusiveEndTDBDays)
        guard tdb.isFinite, inDomain else { return nil }
        var record = min(Int(((tdb - startTDBDays) / component.recordDays).rounded(.down)), component.recordCount - 1)
        if tdb < startTDBDays + Double(record) * component.recordDays { record -= 1 }
        if tdb >= startTDBDays + Double(record + 1) * component.recordDays { record += 1 }
        return (0..<component.recordCount).contains(record) ? record : nil
    }

    static func evaluate(
        component index: Int, at julianDateTDB: Double, includingExclusiveEnd: Bool = false
    ) -> SourceState? {
        evaluate(component: index, atTDBDays: julianDateTDB - j2000, includingExclusiveEnd: includingExclusiveEnd)
    }

    static func evaluate(
        component index: Int, atTDBDays tdb: Double, includingExclusiveEnd: Bool = false
    ) -> SourceState? {
        guard components.indices.contains(index) else { return nil }
        let component = components[index]
        guard let record = recordIndex(component, atTDBDays: tdb, includingExclusiveEnd: includingExclusiveEnd) else {
            return nil
        }
        let recordStart = startTDBDays + Double(record) * component.recordDays
        let x = 2 * (tdb - recordStart) / component.recordDays - 1
        guard x.isFinite, (-1...1).contains(x) else { return nil }
        let recordInChunk = record % recordsPerChunk
        let chunk = component.chunks[record / recordsPerChunk]
        return chunk.withUTF8Buffer { bytes in
            let recordBase = recordInChunk * component.encodedLineBytes
            guard recordBase + component.encodedRecordBytes <= bytes.count else { return nil }
            var position = SIMD3<Double>()
            var velocity = SIMD3<Double>()
            for axis in 0..<3 {
                guard
                    let c0 = coefficient(
                        axis: axis, degree: 0, component: component, recordBase: recordBase, bytes: bytes),
                    let c1 = coefficient(
                        axis: axis, degree: 1, component: component, recordBase: recordBase, bytes: bytes)
                else { return nil }
                var value = c0 + c1 * x
                var derivative = c1
                var priorPolynomial = 1.0
                var polynomial = x
                var priorDerivative = 0.0
                var polynomialDerivative = 1.0
                if component.keptCoefficientCount > 2 {
                    for degree in 2..<component.keptCoefficientCount {
                        guard
                            let coefficient = coefficient(
                                axis: axis, degree: degree, component: component, recordBase: recordBase, bytes: bytes)
                        else { return nil }
                        let nextPolynomial = 2 * x * polynomial - priorPolynomial
                        let nextDerivative = 2 * polynomial + 2 * x * polynomialDerivative - priorDerivative
                        value += coefficient * nextPolynomial
                        derivative += coefficient * nextDerivative
                        (priorPolynomial, polynomial) = (polynomial, nextPolynomial)
                        (priorDerivative, polynomialDerivative) = (polynomialDerivative, nextDerivative)
                    }
                }
                position[axis] = value
                velocity[axis] = derivative * 2 / component.recordDays
            }
            guard position.x.isFinite, position.y.isFinite, position.z.isFinite,
                velocity.x.isFinite, velocity.y.isFinite, velocity.z.isFinite
            else { return nil }
            return SourceState(positionKm: position, velocityKmPerTDBDay: velocity)
        }
    }

    static func state(
        of moon: Engine.JupiterMoons.Moon, atJulianDateTDB julianDateTDB: Double, rate: Double,
        time: Engine.Time, includingExclusiveEnd: Bool = false
    ) -> Engine.State<Engine.EQJ>? {
        state(
            of: moon, atTDBDays: julianDateTDB - j2000, rate: rate, time: time,
            includingExclusiveEnd: includingExclusiveEnd)
    }

    static func state(
        of moon: Engine.JupiterMoons.Moon, atTDBDays tdb: Double, rate: Double,
        time: Engine.Time, includingExclusiveEnd: Bool = false
    ) -> Engine.State<Engine.EQJ>? {
        guard
            let target = evaluate(
                component: moon.rawValue, atTDBDays: tdb, includingExclusiveEnd: includingExclusiveEnd),
            let center = evaluate(component: 4, atTDBDays: tdb, includingExclusiveEnd: includingExclusiveEnd)
        else { return nil }
        return state(target: target, center: center, rate: rate, time: time)
    }

    static func state(
        target: SourceState, center: SourceState, rate: Double, time: Engine.Time
    ) -> Engine.State<Engine.EQJ> {
        let position = (target.positionKm - center.positionKm) / Engine.kilometersPerAU
        let velocity = (target.velocityKmPerTDBDay - center.velocityKmPerTDBDay) * rate / Engine.kilometersPerAU
        let source = Engine.State<Engine.ICRS>(
            x: position.x, y: position.y, z: position.z,
            vx: velocity.x, vy: velocity.y, vz: velocity.z, time: time)
        return Engine.FrameBias.icrsToEqj.apply(to: source)
    }

    static func states(at time: Engine.Time) -> Engine.JupiterMoons.States? {
        let conversion = Engine.TDB.offsetAndRate(tt: time.tt)
        let tdb = time.tt + conversion.offsetSeconds / Engine.secondsPerDay
        guard let center = evaluate(component: 4, atTDBDays: tdb) else { return nil }
        var values = [Engine.State<Engine.EQJ>]()
        values.reserveCapacity(4)
        for moon in Engine.JupiterMoons.Moon.allCases {
            guard let target = evaluate(component: moon.rawValue, atTDBDays: tdb) else { return nil }
            values.append(state(target: target, center: center, rate: conversion.rate, time: time))
        }
        return Engine.JupiterMoons.States(io: values[0], europa: values[1], ganymede: values[2], callisto: values[3])
    }

    static func terrestrialDays(atJulianDateTDB julianDateTDB: Double) -> Double {
        let tdb = julianDateTDB - j2000
        var tt = tdb
        for _ in 0..<3 { tt = tdb - Engine.TDB.offsetSeconds(tt: tt) / Engine.secondsPerDay }
        return tt
    }

    static let startTT = terrestrialDays(atJulianDateTDB: startJDTDB)
    static let endTT = terrestrialDays(atJulianDateTDB: exclusiveEndJDTDB)
}

extension Engine.JupiterMoons {
    static func selectedState(of moon: Moon, at time: Engine.Time) throws -> Engine.State<Engine.EQJ> {
        let conversion = Engine.TDB.offsetAndRate(tt: time.tt)
        let tdb = time.tt + conversion.offsetSeconds / Engine.secondsPerDay
        if let source = Jup365.state(of: moon, atTDBDays: tdb, rate: conversion.rate, time: time) {
            return try Engine.Positions.checked(source)
        }
        let fallback = try state(models[moon.rawValue], at: time)
        let boundary: (tt: Double, julianDateTDB: Double, direction: Double)?
        if time.tt >= Jup365.startTT - Jup365.transitionDays && time.tt < Jup365.startTT {
            boundary = (Jup365.startTT, Jup365.startJDTDB, -1)
        } else if time.tt >= Jup365.endTT && time.tt <= Jup365.endTT + Jup365.transitionDays {
            boundary = (Jup365.endTT, Jup365.exclusiveEndJDTDB, 1)
        } else {
            boundary = nil
        }
        guard let boundary, let model = time.deltaTModel else { return fallback }
        let boundaryTime = Engine.Time(tt: boundary.tt, deltaTModel: model)
        let boundaryRate = Engine.TDB.rate(tt: boundary.tt)
        guard
            let source = Jup365.state(
                of: moon, atJulianDateTDB: boundary.julianDateTDB, rate: boundaryRate,
                time: boundaryTime, includingExclusiveEnd: true)
        else { return fallback }
        let boundaryFallback = try state(models[moon.rawValue], at: boundaryTime)
        let distance = boundary.direction * (time.tt - boundary.tt)
        let u = distance / Jup365.transitionDays
        guard (0...1).contains(u) else { return fallback }
        let u2 = u * u
        let u3 = u2 * u
        let h00 = 2 * u3 - 3 * u2 + 1
        let h10 = u3 - 2 * u2 + u
        let dh00 = 6 * u2 - 6 * u
        let dh10 = 3 * u2 - 4 * u + 1
        let positionDelta = SIMD3(
            source.x - boundaryFallback.x, source.y - boundaryFallback.y, source.z - boundaryFallback.z)
        let velocityDelta = SIMD3(
            source.vx - boundaryFallback.vx, source.vy - boundaryFallback.vy, source.vz - boundaryFallback.vz)
        let tangent = velocityDelta * (boundary.direction * Jup365.transitionDays)
        let correction = positionDelta * h00 + tangent * h10
        let correctionVelocity = (positionDelta * dh00 + tangent * dh10) * (boundary.direction / Jup365.transitionDays)
        return try Engine.Positions.checked(
            Engine.State(
                x: fallback.x + correction.x, y: fallback.y + correction.y, z: fallback.z + correction.z,
                vx: fallback.vx + correctionVelocity.x, vy: fallback.vy + correctionVelocity.y,
                vz: fallback.vz + correctionVelocity.z, time: time))
    }
}
