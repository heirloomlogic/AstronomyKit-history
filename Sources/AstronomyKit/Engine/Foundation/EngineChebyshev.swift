//
//  EngineChebyshev.swift
//  AstronomyKit
//
//  Chebyshev records of a JPL ephemeris, as the Moon and Pluto tables hold
//  them.
//

import Foundation

extension Engine {
    /// Consecutive records of equal length, each a Chebyshev series per axis,
    /// in the layout of a JPL SPK type 2 segment.
    ///
    /// Record `k` holds `start + k·recordDays ≤ tdb < start + (k + 1)·recordDays`
    /// and maps it onto −1 to 1. `coefficients` runs record by record, then x,
    /// y and z, then by ascending degree.
    struct ChebyshevTable: Sendable {
        /// The start of the first record, in TDB days from J2000.
        let start: Double
        /// The length of each record in TDB days.
        let recordDays: Double
        let recordCount: Int
        /// Coefficients per axis in each record.
        let degreeCount: Int
        let coefficients: Engine.Binary64Table

        /// Traps when `coefficients` does not hold `recordCount` records of
        /// three axes of `degreeCount` each, which only a damaged generated
        /// table can cause.
        init(start: Double, recordDays: Double, recordCount: Int, degreeCount: Int, coefficients: [Double]) {
            self.init(
                start: start, recordDays: recordDays, recordCount: recordCount, degreeCount: degreeCount,
                coefficients: Engine.Binary64Table(coefficients))
        }

        init(
            start: Double, recordDays: Double, recordCount: Int, degreeCount: Int,
            coefficients: Engine.Binary64Table
        ) {
            precondition(
                recordDays > 0 && degreeCount > 0 && coefficients.count == recordCount * 3 * degreeCount,
                "A Chebyshev table's coefficients do not match its shape")
            self.start = start
            self.recordDays = recordDays
            self.recordCount = recordCount
            self.degreeCount = degreeCount
            self.coefficients = coefficients
        }

        /// The value and its derivative per TDB day at `tdb` days of TDB from
        /// J2000, or `nil` outside the records or for a time that is not
        /// finite.
        ///
        /// Clenshaw's recurrence gives the series and its derivative
        /// together, in the order of operations of the C engine's evaluator.
        /// Domain checks use the original TDB. If subtracting the start rounds
        /// an interior time to the end, the last record still owns that time.
        func evaluate(tdb: Double) -> (position: SIMD3<Double>, velocity: SIMD3<Double>)? {
            guard tdb.isFinite, tdb >= start, tdb < start + Double(recordCount) * recordDays else { return nil }
            let offset = tdb - start
            let interval = offset / recordDays
            guard interval.isFinite else { return nil }
            let record = min(Int(interval.rounded(.down)), recordCount - 1)
            let x = 2 * (offset - Double(record) * recordDays) / recordDays - 1
            var position = SIMD3<Double>()
            var velocity = SIMD3<Double>()
            for axis in 0..<3 {
                let base = (3 * record + axis) * degreeCount
                var (b1, b2, d1, d2) = (0.0, 0.0, 0.0, 0.0)
                for k in stride(from: degreeCount - 1, to: 0, by: -1) {
                    let b = 2 * x * b1 - b2 + coefficients[base + k]
                    let d = 2 * b1 + 2 * x * d1 - d2
                    (b2, b1) = (b1, b)
                    (d2, d1) = (d1, d)
                }
                position[axis] = coefficients[base] + x * b1 - b2
                velocity[axis] = (b1 + x * d1 - d2) * (2 / recordDays)
            }
            return (position, velocity)
        }
    }
}
