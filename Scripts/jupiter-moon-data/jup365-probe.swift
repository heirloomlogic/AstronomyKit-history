import Foundation

struct Component {
    let data: Data
    let start: Double
    let end: Double
    let days: Double
    let recordCount: Int
    let sourceCoefficientCount: Int
    let keptCoefficientCount: Int
    let float32CoefficientCount: Int
    let scales: [[Double]]

    var recordBytes: Int {
        3 * (4 * float32CoefficientCount + 2 * (keptCoefficientCount - float32CoefficientCount))
    }

    func coefficient(record: Int, axis: Int, degree: Int) -> Double {
        if degree >= keptCoefficientCount {
            return 0
        }
        let tailCount = keptCoefficientCount - float32CoefficientCount
        var offset = record * recordBytes + axis * (4 * float32CoefficientCount + 2 * tailCount)
        if degree < float32CoefficientCount {
            offset += degree * 4
            let bits = UInt32(data[offset]) | UInt32(data[offset + 1]) << 8 | UInt32(data[offset + 2]) << 16 | UInt32(data[offset + 3]) << 24
            return Double(Float(bitPattern: bits))
        }
        offset += 4 * float32CoefficientCount + 2 * (degree - float32CoefficientCount)
        let bits = UInt16(data[offset]) | UInt16(data[offset + 1]) << 8
        return Double(Int16(bitPattern: bits)) * scales[axis][degree - float32CoefficientCount]
    }

    func evaluate(_ julianDateTDB: Double) -> (SIMD3<Double>, SIMD3<Double>)? {
        guard julianDateTDB.isFinite, start <= julianDateTDB, julianDateTDB < end else {
            return nil
        }
        let record = Int(floor((julianDateTDB - start) / days))
        guard record >= 0, record < recordCount else {
            return nil
        }
        let recordStart = start + Double(record) * days
        let x = 2 * (julianDateTDB - recordStart) / days - 1
        var position = SIMD3<Double>(repeating: 0)
        var velocity = SIMD3<Double>(repeating: 0)
        for axis in 0..<3 {
            var previousValue = 1.0
            var value = x
            var previousDerivative = 0.0
            var derivative = 1.0
            position[axis] = coefficient(record: record, axis: axis, degree: 0)
            if sourceCoefficientCount > 1 {
                position[axis] += coefficient(record: record, axis: axis, degree: 1) * value
                velocity[axis] += coefficient(record: record, axis: axis, degree: 1) * derivative
            }
            if sourceCoefficientCount > 2 {
                for degree in 2..<sourceCoefficientCount {
                    let nextValue = 2 * x * value - previousValue
                    let nextDerivative = 2 * value + 2 * x * derivative - previousDerivative
                    let coefficient = coefficient(record: record, axis: axis, degree: degree)
                    position[axis] += coefficient * nextValue
                    velocity[axis] += coefficient * nextDerivative
                    previousValue = value
                    value = nextValue
                    previousDerivative = derivative
                    derivative = nextDerivative
                }
            }
            velocity[axis] *= 2 / days
        }
        return (position, velocity)
    }
}

func milliseconds(_ start: ContinuousClock.Instant, _ end: ContinuousClock.Instant) -> Double {
    let duration = start.duration(to: end)
    return Double(duration.components.seconds) * 1_000 + Double(duration.components.attoseconds) / 1e15
}

guard CommandLine.arguments.count == 3, let iterations = Int(CommandLine.arguments[2]), iterations > 0 else {
    fatalError("usage: jup365-probe DATA-DIRECTORY ITERATIONS")
}
let directory = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true)
let clock = ContinuousClock()
let loadStart = clock.now
let document = try JSONSerialization.jsonObject(with: Data(contentsOf: directory.appendingPathComponent("representation.json"))) as! [String: Any]
let reports = document["components"] as! [String: [String: Any]]
var components: [String: Component] = [:]
for (name, report) in reports {
    components[name] = Component(
        data: try Data(contentsOf: directory.appendingPathComponent("\(name).bin"), options: .mappedIfSafe),
        start: report["startJDTDB"] as! Double,
        end: report["exclusiveEndJDTDB"] as! Double,
        days: report["recordDays"] as! Double,
        recordCount: report["recordCount"] as! Int,
        sourceCoefficientCount: report["sourceCoefficientCount"] as! Int,
        keptCoefficientCount: report["keptCoefficientCount"] as! Int,
        float32CoefficientCount: report["float32CoefficientCount"] as! Int,
        scales: report["tailScales"] as! [[Double]]
    )
}
let loadEnd = clock.now
let names = ["io", "europa", "ganymede", "callisto"]
let start = document["coverageJDTDB"] as! [Double]
func run() -> Double {
    var checksum = 0.0
    for index in 0..<iterations {
        let fraction = (Double(index) + 0.5) / Double(iterations)
        let epoch = start[0] + fraction * (start[1] - start[0])
        let moon = components[names[index % names.count]]!.evaluate(epoch)!
        let jupiter = components["jupiter"]!.evaluate(epoch)!
        let position = moon.0 - jupiter.0
        let velocity = moon.1 - jupiter.1
        checksum += position.x + position.y + position.z + velocity.x + velocity.y + velocity.z
    }
    return checksum
}
let firstStart = clock.now
let firstChecksum = run()
let firstEnd = clock.now
let warmStart = clock.now
let checksum = run()
let warmEnd = clock.now
let firstElapsed = milliseconds(firstStart, firstEnd)
let warmElapsed = milliseconds(warmStart, warmEnd)
let result: [String: Any] = [
    "iterations": iterations,
    "manifestAndPayloadMappingMilliseconds": milliseconds(loadStart, loadEnd),
    "firstEvaluationMilliseconds": firstElapsed,
    "firstMicrosecondsPerJovicentricState": firstElapsed * 1_000 / Double(iterations),
    "firstChecksum": firstChecksum,
    "warmEvaluationMilliseconds": warmElapsed,
    "warmMicrosecondsPerJovicentricState": warmElapsed * 1_000 / Double(iterations),
    "checksum": checksum,
]
let output = try JSONSerialization.data(withJSONObject: result, options: [.prettyPrinted, .sortedKeys])
FileHandle.standardOutput.write(output)
FileHandle.standardOutput.write(Data("\n".utf8))
