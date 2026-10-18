import Foundation

extension Engine {
    /// Complete DE441 Moon-minus-Earth binary64 polynomials, stored as independently addressable compiled records.
    enum MoonDE441Full {}
}

extension Engine.MoonDE441Full {
    private static let resourceCache = Engine.MappedResourceCache(chunks)

    /// Reads one record without allocating or retaining a decoded copy of the complete table.
    static func coefficients(record: Int) -> [Double]? {
        guard (0..<recordCount).contains(record) else { return nil }
        let localRecord = record % recordsPerChunk
        return resourceCache.resource(at: record / recordsPerChunk).withUnsafeBytes { bytes in
            let base = localRecord * 312
            guard base + 312 <= bytes.count else { return nil }
            var values = [Double]()
            values.reserveCapacity(39)
            for coefficient in 0..<39 {
                let bits = UInt64(
                    littleEndian: bytes.loadUnaligned(fromByteOffset: base + coefficient * 8, as: UInt64.self))
                let value = Double(bitPattern: bits)
                guard value.isFinite else { return nil }
                values.append(value)
            }
            return values
        }
    }

    /// Selects the source record using the original TDB, including representable neighbours of every seam.
    static func recordIndex(tdb: Double) -> Int? {
        let end = start + Double(recordCount) * 4
        guard tdb.isFinite, tdb >= start, tdb < end else { return nil }
        // Subtraction may round an interior upper neighbour to the endpoint; the original-time guard owns acceptance.
        var record = min(Int(((tdb - start) / 4).rounded(.down)), recordCount - 1)
        if tdb < start + Double(record) * 4 { record -= 1 }
        if tdb >= start + Double(record + 1) * 4 { record += 1 }
        return record
    }

    /// Geometric ICRF position in AU and its derivative per TDB day. The upper source endpoint is exclusive.
    static func evaluate(tdb: Double) -> (position: SIMD3<Double>, velocity: SIMD3<Double>)? {
        guard let record = recordIndex(tdb: tdb) else { return nil }
        let recordStart = start + Double(record) * 4
        return evaluate(record: record, x: (tdb - recordStart) / 2 - 1)
    }

    static func evaluate(record: Int, x: Double) -> (position: SIMD3<Double>, velocity: SIMD3<Double>)? {
        guard x.isFinite, (-1...1).contains(x), let c = coefficients(record: record) else { return nil }
        var position = SIMD3<Double>()
        var velocity = SIMD3<Double>()
        for axis in 0..<3 {
            let base = axis * 13
            var (b1, b2, d1, d2) = (0.0, 0.0, 0.0, 0.0)
            for k in stride(from: 12, to: 0, by: -1) {
                let b = 2 * x * b1 - b2 + c[base + k]
                let d = 2 * b1 + 2 * x * d1 - d2
                (b2, b1) = (b1, b)
                (d2, d1) = (d1, d)
            }
            position[axis] = (c[base] + x * b1 - b2) / Engine.kilometersPerAU
            velocity[axis] = (b1 + x * d1 - d2) / (2 * Engine.kilometersPerAU)
        }
        return (position, velocity)
    }

    /// Applies the ICRF-to-EQJ bias and analytic TT-to-TDB derivative; the coefficients remain in their source clock and frame.
    static func state(tt: Double) -> (position: SIMD3<Double>, velocity: SIMD3<Double>)? {
        guard tt.isFinite else { return nil }
        let conversion = Engine.TDB.offsetAndRate(tt: tt)
        guard let source = evaluate(tdb: tt + conversion.offsetSeconds / Engine.secondsPerDay) else { return nil }
        let bias = Engine.FrameBias.icrsToEqj
        return (bias.apply(to: source.position), bias.apply(to: source.velocity * conversion.rate))
    }
}
