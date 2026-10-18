import Foundation

extension Engine {
    /// Direct type-2 SPK coefficients with their source record grid and scalar encoding.
    struct DirectChebyshevTable: Sendable {
        let start: Double
        let days: Double
        let recordCount: Int
        let coefficientCount: Int
        let scalarBytes: Int
        let data: Data
        private let mappedData: Engine.MappedBytes?
        private let recordsPerChunk: Int
        private let chunks: [StaticString]

        var byteCount: Int { mappedData?.count ?? data.count }

        init(start: Double, days: Double, recordCount: Int, coefficientCount: Int, scalarBytes: Int, data: Data) {
            precondition(days > 0 && recordCount > 0 && coefficientCount > 0)
            precondition(scalarBytes == 4 || scalarBytes == 8)
            precondition(data.count == recordCount * 3 * coefficientCount * scalarBytes)
            self.start = start
            self.days = days
            self.recordCount = recordCount
            self.coefficientCount = coefficientCount
            self.scalarBytes = scalarBytes
            self.data = data
            self.mappedData = nil
            self.recordsPerChunk = 0
            self.chunks = []
        }

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
            self.data = Data()
            self.mappedData = Engine.MappedBytes.bundled(resource)
            self.recordsPerChunk = 0
            self.chunks = []
        }

        init(
            start: Double, days: Double, recordCount: Int, coefficientCount: Int, scalarBytes: Int,
            data: Engine.MappedBytes
        ) {
            precondition(days > 0 && recordCount > 0 && coefficientCount > 0)
            precondition(scalarBytes == 4 || scalarBytes == 8)
            precondition(data.count == recordCount * 3 * coefficientCount * scalarBytes)
            self.start = start
            self.days = days
            self.recordCount = recordCount
            self.coefficientCount = coefficientCount
            self.scalarBytes = scalarBytes
            self.data = Data()
            self.mappedData = data
            self.recordsPerChunk = 0
            self.chunks = []
        }

        init(
            start: Double, days: Double, recordCount: Int, coefficientCount: Int,
            recordsPerChunk: Int, chunks: [StaticString]
        ) {
            precondition(days > 0 && recordCount > 0 && coefficientCount > 0)
            precondition(recordsPerChunk > 0 && chunks.count == (recordCount + recordsPerChunk - 1) / recordsPerChunk)
            self.start = start
            self.days = days
            self.recordCount = recordCount
            self.coefficientCount = coefficientCount
            self.scalarBytes = 8
            self.data = Data()
            self.mappedData = nil
            self.recordsPerChunk = recordsPerChunk
            self.chunks = chunks
        }

        func evaluate(tdb: Double) -> (position: SIMD3<Double>, velocity: SIMD3<Double>)? {
            let end = start + Double(recordCount) * days
            guard tdb.isFinite, tdb >= start, tdb < end else { return nil }
            var record = min(Int(((tdb - start) / days).rounded(.down)), recordCount - 1)
            if tdb < start + Double(record) * days { record -= 1 }
            if tdb >= start + Double(record + 1) * days { record += 1 }
            let x = 2 * (tdb - (start + Double(record) * days)) / days - 1
            return evaluate(record: record, x: x)
        }

        func acceleration(tdb: Double) -> SIMD3<Double>? {
            let end = start + Double(recordCount) * days
            guard tdb.isFinite, tdb >= start, tdb < end else { return nil }
            var record = min(Int(((tdb - start) / days).rounded(.down)), recordCount - 1)
            if tdb < start + Double(record) * days { record -= 1 }
            if tdb >= start + Double(record + 1) * days { record += 1 }
            let x = 2 * (tdb - (start + Double(record) * days)) / days - 1
            return acceleration(record: record, x: x)
        }

        /// Clenshaw value and analytic derivative, in source units per TDB day.
        func evaluate(record: Int, x: Double) -> (position: SIMD3<Double>, velocity: SIMD3<Double>)? {
            precondition((0..<recordCount).contains(record) && x.isFinite && (-1...1).contains(x))
            if chunks.isEmpty {
                return withRawBytes { raw in
                    evaluate(record: record, x: x) { index in
                        let offset = index * scalarBytes
                        if scalarBytes == 4 {
                            return Double(
                                Float(
                                    bitPattern: UInt32(
                                        littleEndian: raw.loadUnaligned(fromByteOffset: offset, as: UInt32.self))))
                        }
                        return Double(
                            bitPattern: UInt64(
                                littleEndian: raw.loadUnaligned(fromByteOffset: offset, as: UInt64.self)))
                    }
                }
            }
            let local = record % recordsPerChunk
            let encodedRecordBytes = coefficientCount * 32
            return chunks[record / recordsPerChunk].withUTF8Buffer { bytes in
                let base = local * (encodedRecordBytes + 1)
                guard base + encodedRecordBytes <= bytes.count else { return nil }
                func sextet(_ byte: UInt8) -> UInt64? {
                    switch byte {
                    case 65...90: UInt64(byte - 65)
                    case 97...122: UInt64(byte - 71)
                    case 48...57: UInt64(byte + 4)
                    case 43: 62
                    case 47: 63
                    default: nil
                    }
                }
                return withUnsafeTemporaryAllocation(of: Double.self, capacity: 3 * coefficientCount) {
                    coefficients in
                    for index in coefficients.indices {
                        let raw = index * 8
                        var bits: UInt64 = 0
                        for byteIndex in 0..<8 {
                            let byte = raw + byteIndex
                            let group = base + (byte / 3) * 4
                            let slot = byte % 3
                            guard let a = sextet(bytes[group + slot]), let b = sextet(bytes[group + slot + 1])
                            else { return nil }
                            let value: UInt64
                            if slot == 0 {
                                value = (a << 2) | (b >> 4)
                            } else if slot == 1 {
                                value = ((a << 4) | (b >> 2)) & 255
                            } else {
                                value = ((a << 6) | b) & 255
                            }
                            bits |= value << (byteIndex * 8)
                        }
                        let value = Double(bitPattern: bits)
                        guard value.isFinite else { return nil }
                        coefficients[index] = value
                    }
                    return evaluate(record: 0, x: x) { coefficients[$0] }
                }
            }
        }

        /// Analytic second derivative in source units per TDB day squared.
        func acceleration(record: Int, x: Double) -> SIMD3<Double>? {
            precondition((0..<recordCount).contains(record) && x.isFinite && (-1...1).contains(x))
            return withCoefficients(record: record, x: x) { localRecord, localX, coefficient in
                acceleration(record: localRecord, x: localX, coefficient: coefficient)
            }
        }

        private func withCoefficients<Result>(
            record: Int, x: Double, body: (Int, Double, (Int) -> Double) -> Result
        ) -> Result? {
            if chunks.isEmpty {
                return withRawBytes { raw in
                    body(record, x) { index in
                        let offset = index * scalarBytes
                        if scalarBytes == 4 {
                            return Double(
                                Float(
                                    bitPattern: UInt32(
                                        littleEndian: raw.loadUnaligned(fromByteOffset: offset, as: UInt32.self))))
                        }
                        return Double(
                            bitPattern: UInt64(
                                littleEndian: raw.loadUnaligned(fromByteOffset: offset, as: UInt64.self)))
                    }
                }
            }
            let local = record % recordsPerChunk
            let encodedRecordBytes = coefficientCount * 32
            return chunks[record / recordsPerChunk].withUTF8Buffer { bytes in
                let base = local * (encodedRecordBytes + 1)
                guard base + encodedRecordBytes <= bytes.count else { return nil }
                func sextet(_ byte: UInt8) -> UInt64? {
                    switch byte {
                    case 65...90: UInt64(byte - 65)
                    case 97...122: UInt64(byte - 71)
                    case 48...57: UInt64(byte + 4)
                    case 43: 62
                    case 47: 63
                    default: nil
                    }
                }
                return withUnsafeTemporaryAllocation(of: Double.self, capacity: 3 * coefficientCount) {
                    coefficients in
                    for index in coefficients.indices {
                        let raw = index * 8
                        var bits: UInt64 = 0
                        for byteIndex in 0..<8 {
                            let byte = raw + byteIndex
                            let group = base + (byte / 3) * 4
                            let slot = byte % 3
                            guard let a = sextet(bytes[group + slot]), let b = sextet(bytes[group + slot + 1])
                            else { return nil }
                            let value: UInt64
                            if slot == 0 {
                                value = (a << 2) | (b >> 4)
                            } else if slot == 1 {
                                value = ((a << 4) | (b >> 2)) & 255
                            } else {
                                value = ((a << 6) | b) & 255
                            }
                            bits |= value << (byteIndex * 8)
                        }
                        let value = Double(bitPattern: bits)
                        guard value.isFinite else { return nil }
                        coefficients[index] = value
                    }
                    return body(0, x) { coefficients[$0] }
                }
            }
        }

        private func withRawBytes<Result>(_ body: (UnsafeRawBufferPointer) -> Result) -> Result {
            if let mappedData { return mappedData.withUnsafeBytes(body) }
            return data.withUnsafeBytes(body)
        }

        private func evaluate(
            record: Int, x: Double, coefficient: (Int) -> Double
        ) -> (position: SIMD3<Double>, velocity: SIMD3<Double>) {
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

        private func acceleration(record: Int, x: Double, coefficient: (Int) -> Double) -> SIMD3<Double> {
            var result = SIMD3<Double>()
            for axis in 0..<3 {
                let base = (record * 3 + axis) * coefficientCount
                var (b1, b2, d1, d2, a1, a2) = (0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
                for k in stride(from: coefficientCount - 1, to: 0, by: -1) {
                    let b = 2 * x * b1 - b2 + coefficient(base + k)
                    let d = 2 * b1 + 2 * x * d1 - d2
                    let a = 4 * d1 + 2 * x * a1 - a2
                    (b2, b1) = (b1, b)
                    (d2, d1) = (d1, d)
                    (a2, a1) = (a1, a)
                }
                result[axis] = (2 * d1 + x * a1 - a2) * 4 / (days * days)
            }
            return result
        }
    }
}
