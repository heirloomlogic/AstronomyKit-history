import Foundation

extension Engine {
    /// DE441's Pluto-system barycenter relative to the Sun; the physical Pluto-center offset is absent.
    enum PlutoDE441 {}
}

extension Engine.PlutoDE441 {
    static let acceptedTTDays = Engine.acceptedTTDays

    /// Shared endpoint positions in ICRF km and analytic derivatives in km per TDB day.
    struct Table: Sendable {
        let start: Double
        let days: Double
        let recordCount: Int
        let data: Engine.MappedBytes

        init(start: Double, days: Double, recordCount: Int, resource: Engine.TableResource) {
            precondition(resource.byteCount == (recordCount + 1) * 6 * 8)
            self.start = start
            self.days = days
            self.recordCount = recordCount
            self.data = Engine.MappedBytes.bundled(resource)
        }

        func evaluate(tdb: Double) -> (position: SIMD3<Double>, velocity: SIMD3<Double>)? {
            guard tdb.isFinite, tdb >= start else { return nil }
            let offset = tdb - start
            let interval = offset / days
            guard interval < Double(recordCount) else { return nil }
            let record = Int(interval.rounded(.down))
            return evaluate(record: record, x: 2 * (offset - Double(record) * days) / days - 1)
        }

        /// Reconstructs the cubic and returns AU and AU per TDB day.
        func evaluate(record: Int, x: Double) -> (position: SIMD3<Double>, velocity: SIMD3<Double>) {
            precondition((0..<recordCount).contains(record))
            return data.withUnsafeBytes { raw in
                func value(_ offset: Int) -> Double {
                    Double(bitPattern: UInt64(littleEndian: raw.loadUnaligned(fromByteOffset: offset, as: UInt64.self)))
                }
                let left = record * 48
                let right = left + 48
                var position = SIMD3<Double>()
                var velocity = SIMD3<Double>()
                for axis in 0..<3 {
                    let pl = value(left + axis * 8)
                    let pr = value(right + axis * 8)
                    let dl = value(left + (axis + 3) * 8) * days / 2
                    let dr = value(right + (axis + 3) * 8) * days / 2
                    let even = (pr + pl) / 2
                    let odd = (pr - pl) / 2
                    let c2 = (dr - dl) / 8
                    let c3 = (dr + dl - 2 * odd) / 16
                    let coefficients = [even - c2, odd - c3, c2, c3]
                    var (b1, b2, d1, d2) = (0.0, 0.0, 0.0, 0.0)
                    for k in stride(from: 3, to: 0, by: -1) {
                        let b = 2 * x * b1 - b2 + coefficients[k]
                        let d = 2 * b1 + 2 * x * d1 - d2
                        (b2, b1) = (b1, b)
                        (d2, d1) = (d1, d)
                    }
                    position[axis] = (coefficients[0] + x * b1 - b2) / Engine.kilometersPerAU
                    velocity[axis] = (b1 + x * d1 - d2) * 2 / (days * Engine.kilometersPerAU)
                }
                return (position, velocity)
            }
        }
    }

    /// Transforms the heliocentric barycenter state from ICRF/TDB into EQJ with rates per TT day.
    static func state(tt: Double) -> (position: SIMD3<Double>, velocity: SIMD3<Double>)? {
        guard tt.isFinite, abs(tt) <= acceptedTTDays else { return nil }
        let conversion = Engine.TDB.offsetAndRate(tt: tt)
        let tdb = tt + conversion.offsetSeconds / Engine.secondsPerDay
        guard let p = pluto.evaluate(tdb: tdb), let s = sun.evaluate(tdb: tdb) else { return nil }
        let bias = Engine.FrameBias.icrsToEqj
        return (
            bias.apply(to: p.position - s.position),
            bias.apply(to: (p.velocity - s.velocity) * conversion.rate)
        )
    }
}
