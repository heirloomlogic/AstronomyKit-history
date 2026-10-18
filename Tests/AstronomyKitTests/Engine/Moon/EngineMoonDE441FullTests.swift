import Foundation
import Testing

@testable import AstronomyKit

@Suite("Complete binary64 DE441 Moon foundation")
struct EngineMoonDE441FullTests {
    typealias Table = Engine.MoonDE441Full

    @Test("Every native mapped coefficient matches the bundled bytes bit for bit")
    func everyCoefficient() throws {
        var count = 0
        for (index, chunk) in Table.chunks.enumerated() {
            let raw = Engine.MappedBytes.bundled(chunk)
            let records = raw.count / 312
            var matches = true
            for record in 0..<records {
                let values = try #require(Table.coefficients(record: index * Table.recordsPerChunk + record))
                for k in 0..<39 {
                    let expected = raw.withUnsafeBytes {
                        UInt64(littleEndian: $0.loadUnaligned(fromByteOffset: record * 312 + k * 8, as: UInt64.self))
                    }
                    if values[k].bitPattern != expected { matches = false }
                    count += 1
                }
            }
            #expect(matches, "Chunk \(index) differs")
        }
        #expect(count == 28_489_578)
    }

    @Test("Domain guards preserve source endpoints and representable interior neighbours")
    func domain() throws {
        let end = Table.start + Double(Table.recordCount) * 4
        for tdb in [Table.start, Table.start.nextUp, end.nextDown, -1_461_002, -1_461_000, 1_461_000] {
            #expect(Table.evaluate(tdb: tdb) != nil)
        }
        for tdb in [Table.start.nextDown, end, end.nextUp, .nan, .infinity, -.infinity] {
            #expect(Table.evaluate(tdb: tdb) == nil)
        }
        #expect(Table.coefficients(record: -1) == nil)
        #expect(Table.coefficients(record: Table.recordCount) == nil)
        for tt in [-Engine.acceptedTTDays - 2, -Engine.acceptedTTDays, Engine.acceptedTTDays] {
            #expect(Table.state(tt: tt) != nil)
        }
    }

    @Test("Complete source polynomials match the retained independently computed state fixtures")
    func sourceFixtures() throws {
        struct Row: Decodable {
            let record: Int
            let x: Double
            let positionKm: [Double]
            let velocityKmPerTDBDay: [Double]
        }
        struct Fixture: Decodable { let rows: [Row] }
        let root = (0..<5).reduce(URL(fileURLWithPath: #filePath)) { url, _ in url.deletingLastPathComponent() }
        let fixture = try JSONDecoder().decode(
            Fixture.self,
            from: Data(contentsOf: root.appendingPathComponent("Scripts/moon-data/de441-native-fixtures.json")))
        for row in fixture.rows {
            let state = try #require(Table.evaluate(record: row.record + 1, x: row.x))
            for axis in 0..<3 {
                #expect(abs(state.position[axis] * Engine.kilometersPerAU - row.positionKm[axis]) < 1e-9)
                #expect(abs(state.velocity[axis] * Engine.kilometersPerAU - row.velocityKmPerTDBDay[axis]) < 1e-9)
            }
        }
    }

    @Test("Malformed records fail closed")
    func malformed() {
        #expect(Table.coefficients(record: -1) == nil)
        #expect(Table.coefficients(record: Int.max) == nil)
        #expect(Table.evaluate(record: 0, x: .nan) == nil)
        #expect(Table.evaluate(record: 0, x: 1.nextUp) == nil)
    }

    @Test("Every source seam selects the correct exact and adjacent record")
    func everySeam() {
        for record in 1..<Table.recordCount {
            let seam = Table.start + Double(record) * 4
            let matches =
                Table.recordIndex(tdb: seam.nextDown) == record - 1 && Table.recordIndex(tdb: seam) == record
                && Table.recordIndex(tdb: seam.nextUp) == record
            if !matches {
                Issue.record("Record selection differs at \(record), TDB \(seam)")
                return
            }
        }
    }

    @Test("Selected source and chunk seams dispatch to their actual one-sided polynomial")
    func seams() throws {
        var records = Array(stride(from: Table.recordsPerChunk, to: Table.recordCount, by: Table.recordsPerChunk))
        records += [1, 362_473, Table.recordCount - 1]
        for record in records {
            let seam = Table.start + Double(record) * 4
            for tdb in [seam.nextDown, seam, seam.nextUp] {
                let selected = tdb < seam ? record - 1 : record
                let expected = try #require(
                    Table.evaluate(record: selected, x: (tdb - (Table.start + Double(selected) * 4)) / 2 - 1))
                let actual = try #require(Table.evaluate(tdb: tdb))
                #expect(actual.position == expected.position)
                #expect(actual.velocity == expected.velocity)
            }
        }
    }

    @Test("Cold first access and random full-domain record costs can be recorded")
    func measurement() throws {
        guard let path = ProcessInfo.processInfo.environment["MOON_FULL_MEASUREMENT"] else { return }
        let started = ProcessInfo.processInfo.systemUptime
        let first = try #require(Table.state(tt: 0))
        let firstSeconds = ProcessInfo.processInfo.systemUptime - started
        let loop = ProcessInfo.processInfo.systemUptime
        var checksum = first.position.sum()
        for index in 0..<20_000 {
            let record = (index * 7919) % Table.recordCount
            checksum += try #require(Table.evaluate(record: record, x: 0.125)).position.sum()
        }
        let result: [String: Any] = [
            "firstStateSeconds": firstSeconds, "randomRecords": 20_000,
            "randomSeconds": ProcessInfo.processInfo.systemUptime - loop, "checksum": checksum,
        ]
        try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys, .prettyPrinted]).write(
            to: URL(fileURLWithPath: path))
    }

    @Test("Analytic TT rates include TDB clock scaling and frame bias")
    func rates() throws {
        for tt in stride(from: -1_460_000.0, through: 1_460_000.0, by: 20_000) {
            let state = try #require(Table.state(tt: tt))
            let h = 1.0 / 64
            func p(_ t: Double) throws -> SIMD3<Double> { try #require(Table.state(tt: t)).position }
            let difference = try (p(tt - 2 * h) - 8 * p(tt - h) + 8 * p(tt + h) - p(tt + 2 * h)) / (12 * h)
            let speed = (state.velocity * state.velocity).sum().squareRoot()
            #expect(
                EngineMoonEphemerisTests.largest(state.velocity - difference) <= EngineMoonStatesTests.allowance(tt: tt)
                    * speed)
        }
    }
}
