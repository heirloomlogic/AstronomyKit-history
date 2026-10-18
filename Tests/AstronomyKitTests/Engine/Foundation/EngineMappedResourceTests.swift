import Foundation
import Testing

@testable import AstronomyKit

@Suite("Mapped model resources")
struct EngineMappedResourceTests {
    private let abcDigest = "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"

    private func file(_ bytes: [UInt8]) throws -> URL {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let url = directory.appendingPathComponent("table.bin")
        try Data(bytes).write(to: url)
        return url
    }

    @Test("A valid file is mapped read-only with bounded access")
    func validAndBounded() throws {
        let url = try file([97, 98, 99])
        defer { try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }
        let mapped = try Engine.MappedBytes(url: url, byteCount: 3, sha256: abcDigest)
        #expect(mapped.count == 3)
        #expect(mapped.withUnsafeBytes { Array($0) } == [97, 98, 99])
        #expect(mapped.littleEndianUInt64(at: -1) == nil)
        #expect(mapped.littleEndianUInt64(at: 0) == nil)
        #expect(mapped.littleEndianUInt64(at: 3) == nil)
    }

    @Test("Missing, truncated, and corrupt resources fail closed")
    func damaged() throws {
        let missing = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        #expect(throws: Engine.MappedBytes.MappingError.cannotOpen) {
            try Engine.MappedBytes(url: missing, byteCount: 3, sha256: abcDigest)
        }
        let url = try file([97, 98, 100])
        defer { try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }
        #expect(throws: Engine.MappedBytes.MappingError.byteCount(expected: 2, actual: 3)) {
            try Engine.MappedBytes(url: url, byteCount: 2, sha256: abcDigest)
        }
        #expect(
            throws: Engine.MappedBytes.MappingError.checksum(
                expected: abcDigest, actual: "a52d159f262b2c6ddb724a61840befc36eb30c88877a4030b65cbe86298449c9")
        ) {
            try Engine.MappedBytes(url: url, byteCount: 3, sha256: abcDigest)
        }
    }

    @Test("Concurrent readers retain one immutable mapping")
    func concurrentReaders() async throws {
        let bytes = Array(repeating: UInt8(97), count: 8)
        let url = try file(bytes)
        defer { try? FileManager.default.removeItem(at: url.deletingLastPathComponent()) }
        let mapped = try Engine.MappedBytes(
            url: url, byteCount: 8, sha256: "1f3ce40415a2081fa3eee75fc39fff8e56c22270d1a978a7249b592dcebd20b4")
        await withTaskGroup(of: Bool.self) { group in
            for _ in 0..<64 {
                group.addTask { mapped.littleEndianUInt64(at: 0) == 0x6161_6161_6161_6161 }
            }
            for await valid in group { #expect(valid) }
        }
    }
}
