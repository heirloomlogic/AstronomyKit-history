import AstronomyKit
import Foundation

let firstOnly = CommandLine.arguments.dropFirst().first == "--first-only"
let iterations = CommandLine.arguments.dropFirst().first.flatMap(Int.init) ?? 100_000
let sameTime = AstroTime(tt: 0, deltaTModel: .espenakMeeus)

func nanoseconds(_ body: () throws -> Double) rethrows -> (Double, Double) {
    let start = DispatchTime.now().uptimeNanoseconds
    let checksum = try body()
    let elapsed = DispatchTime.now().uptimeNanoseconds - start
    return (Double(elapsed), checksum)
}

let first = try nanoseconds {
    let moons = try Jupiter.moons(at: sameTime)
    return moons.io.position.x + moons.callisto.velocity.z
}
if firstOnly {
    let result: [String: Any] = [
        "firstPublicCallMilliseconds": first.0 / 1_000_000,
        "firstChecksum": first.1,
    ]
    let data = try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
    print(String(decoding: data, as: UTF8.self))
    exit(EXIT_SUCCESS)
}
precondition(iterations > 0)
let span = (0..<4096).map { index in
    AstroTime(tt: -146_000 + Double(index) / 4095 * 218_900, deltaTModel: .espenakMeeus)
}
let same = try nanoseconds {
    var checksum = 0.0
    for _ in 0..<iterations {
        let moons = try Jupiter.moons(at: sameTime)
        checksum += moons.io.position.x + moons.callisto.velocity.z
    }
    return checksum
}
let spanning = try nanoseconds {
    var checksum = 0.0
    for index in 0..<iterations {
        let moons = try Jupiter.moons(at: span[index % span.count])
        checksum += moons.europa.position.y + moons.ganymede.velocity.x
    }
    return checksum
}
let result: [String: Any] = [
    "iterations": iterations,
    "firstPublicCallMilliseconds": first.0 / 1_000_000,
    "sameEpochMicrosecondsPerCall": same.0 / Double(iterations) / 1_000,
    "spanningMicrosecondsPerCall": spanning.0 / Double(iterations) / 1_000,
    "firstChecksum": first.1,
    "sameEpochChecksum": same.1,
    "spanningChecksum": spanning.1,
]
let data = try JSONSerialization.data(withJSONObject: result, options: [.sortedKeys])
print(String(decoding: data, as: UTF8.self))
