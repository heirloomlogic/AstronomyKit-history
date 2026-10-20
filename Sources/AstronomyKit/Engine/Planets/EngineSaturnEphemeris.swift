import Foundation

extension Engine {
    /// Saturn's physical center: DE441 Saturn-system barycenter minus Sun, plus SAT441's center offset, on ICRF axes.
    enum SaturnEphemeris {}
}

extension Engine.SaturnEphemeris {
    /// Direct type-2 binary64 coefficients in km.
    struct Table: Sendable {
        let start: Double
        let days: Double
        let recordCount: Int
        let coefficientCount: Int
        let scalarBytes: Int
        let data: Engine.MappedBytes

        init(
            start: Double, days: Double, recordCount: Int, coefficientCount: Int, scalarBytes: Int,
            resource: Engine.TableResource
        ) {
            precondition(days > 0 && recordCount > 0 && coefficientCount > 0)
            precondition(scalarBytes == 4 || scalarBytes == 8)
            precondition(resource.byteCount == recordCount * 3 * coefficientCount * scalarBytes)
            self.start = start
            self.days = days
            self.recordCount = recordCount
            self.coefficientCount = coefficientCount
            self.scalarBytes = scalarBytes
            self.data = Engine.MappedBytes.bundled(resource)
        }

        func evaluate(tdb: Double) -> (position: SIMD3<Double>, velocity: SIMD3<Double>)? {
            guard tdb.isFinite, tdb >= start else { return nil }
            let interval = (tdb - start) / days
            guard interval < Double(recordCount) else { return nil }
            let record = Int(interval.rounded(.down))
            return evaluate(record: record, x: 2 * ((tdb - start) - Double(record) * days) / days - 1)
        }

        /// Clenshaw value and analytic derivative, in km and km per TDB day.
        func evaluate(record: Int, x: Double) -> (position: SIMD3<Double>, velocity: SIMD3<Double>) {
            precondition((0..<recordCount).contains(record))
            return data.withUnsafeBytes { raw in
                func coefficient(_ index: Int) -> Double {
                    let offset = index * scalarBytes
                    if scalarBytes == 4 {
                        return Double(
                            Float(
                                bitPattern: UInt32(
                                    littleEndian: raw.loadUnaligned(fromByteOffset: offset, as: UInt32.self))))
                    }
                    return Double(
                        bitPattern: UInt64(littleEndian: raw.loadUnaligned(fromByteOffset: offset, as: UInt64.self)))
                }
                var position = SIMD3<Double>()
                var velocity = SIMD3<Double>()
                for axis in 0..<3 {
                    let base = (record * 3 + axis) * coefficientCount
                    var (b1, b2, d1, d2) = (0.0, 0.0, 0.0, 0.0)
                    for k in stride(from: coefficientCount - 1, to: 0, by: -1) {
                        let b = 2 * x * b1 - b2 + coefficient(base + k)
                        let d = 2 * b1 + 2 * x * d1 - d2
                        (b2, b1) = (b1, b)
                        (d2, d1) = (d1, d)
                    }
                    position[axis] = coefficient(base) + x * b1 - b2
                    velocity[axis] = (b1 + x * d1 - d2) * 2 / days
                }
                return (position, velocity)
            }
        }
    }

    /// The 1900–2130 full-weight interval and its 32-day blends deliberately reuse the Moon's DE440 window; this is not a new global accuracy range.
    static func weight(tt: Double) -> (weight: Double, rate: Double) { Engine.PlanetDE441.weight(tt: tt) }

    /// A state in AU and AU per TT day on the retained model’s ecliptic axes. The default includes the physical-center offset; system-mass callers exclude it.
    static func eclipticState(
        at time: Engine.Time, physicalCenter: Bool = true
    ) -> (position: SIMD3<Double>, velocity: SIMD3<Double>)? {
        let tt = time.tt
        guard tt.isFinite, weight(tt: tt).weight > 0 else { return nil }
        let conversion = Engine.TDB.offsetAndRate(tt: tt)
        let tdb = tt + conversion.offsetSeconds / Engine.secondsPerDay
        guard let b = barycenter.evaluate(tdb: tdb), let s = sun.evaluate(tdb: tdb) else { return nil }
        var c = (position: SIMD3<Double>.zero, velocity: SIMD3<Double>.zero)
        if physicalCenter {
            guard let center = offset.evaluate(tdb: tdb) else { return nil }
            c = center
        }
        let position = (b.position - s.position + c.position) / Engine.kilometersPerAU
        let velocity = (b.velocity - s.velocity + c.velocity) * conversion.rate / Engine.kilometersPerAU
        let p = Engine.FrameBias.icrsToEqj.apply(to: position)
        let v = Engine.FrameBias.icrsToEqj.apply(to: velocity)
        let state = Engine.State<Engine.EQJ>(x: p.x, y: p.y, z: p.z, vx: v.x, vy: v.y, vz: v.z, time: time)
        let ecliptic = Engine.VSOP87B.toEquatorial.inverse.apply(to: state)
        return (SIMD3(ecliptic.x, ecliptic.y, ecliptic.z), SIMD3(ecliptic.vx, ecliptic.vy, ecliptic.vz))
    }
}
