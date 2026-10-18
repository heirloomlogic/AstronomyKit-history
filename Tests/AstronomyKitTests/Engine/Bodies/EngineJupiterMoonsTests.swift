//
//  EngineJupiterMoonsTests.swift
//  AstronomyKit
//
//  Jupiter's moons against the published L1.2 theory and JPL Horizons, and
//  the engine's guards.
//

import Foundation
import Testing

@testable import AstronomyKit

@Suite("Engine.JupiterMoons")
struct EngineJupiterMoonsTests {
    typealias Moons = Engine.JupiterMoons
    typealias Horizons = PlutoSegmentSuites.EnginePlutoHorizonsTests

    static func time(tt: Double) -> Engine.Time { PlanetTestSupport.time(tt: tt) }

    typealias States = EngineMoonStatesTests

    struct Representation: Decodable {
        struct Fixture: Decodable {
            let component: String
            let julianDateTDB: Double
            let candidatePositionKm: [Double]
            let candidateVelocityKmPerTDBDay: [Double]
        }

        let directFixtures: [Fixture]
    }

    static let representation: Representation = {
        let root = (0..<5).reduce(URL(fileURLWithPath: #filePath)) { url, _ in url.deletingLastPathComponent() }
        let url = root.appendingPathComponent("Scripts/jupiter-moon-data/jup365/representation.json")
        return try! JSONDecoder().decode(Representation.self, from: Data(contentsOf: url))
    }()

    /// A Fortran `D` exponent number as `BisL1.2.dat` and `TestL1.2.res` print it,
    /// or NaN, which equals nothing, for text that is not one.
    static func published(_ text: String) -> Double {
        Double(text.replacingOccurrences(of: "D", with: "e")) ?? .nan
    }

    // MARK: - The published theory

    /// Transcribed from `BisL1.2.dat` (SHA-256 in
    /// `Scripts/jupiter-moon-data/manifest.json`): the time origin, the
    /// angles Ψ and I, and, as the file prints them, Io's first L term and
    /// Callisto's last kept z term. The engine keeps the leading terms of
    /// L1.2's 38, 32, 23 and 15 terms of Io's a, L, z and ζ, 38, 36, 41 and
    /// 25 of Europa's, 38, 31, 50 and 18 of Ganymede's and 22, 19, 46 and 18
    /// of Callisto's. `Scripts/generate-jupiter-moon-series.py --published`
    /// compares every kept term, mass and mean longitude with the file.
    @Test("Published L1.2 values")
    func publishedValues() {
        #expect(Moons.epochTT == Self.published("0.2433282500D+07") - 2_451_545)
        #expect(Moons.psi == Self.published("0.6249501830657150D+01"))
        #expect(Moons.inclination == Self.published("0.4450947364976650D+00"))
        let counts = Moons.models.map { [$0.a.count, $0.l.count, $0.z.count, $0.zeta.count] }
        #expect(counts == [[1, 4, 3, 2], [2, 8, 7, 4], [2, 8, 8, 4], [3, 6, 9, 4]])
        let io = Moons.models[Moons.Moon.io.rawValue].l[0]
        #expect(io.amplitude == -0.0001925258348666)
        #expect(io.phase == Self.published("0.49369589722645D+01"))
        #expect(io.frequency == Self.published("0.13584836583050D-01"))
        let callisto = Moons.models[Moons.Moon.callisto.rawValue].z[8]
        #expect(callisto.amplitude == -0.0000489596900866)
        #expect(callisto.phase == Self.published("0.46218149483338D+01"))
        #expect(callisto.frequency == Self.published("-0.62695712529519D+00"))
    }

    /// `TestL1.2.res` (SHA-256 in the manifest) prints each moon's mean
    /// motion √(μ/a³) in radians per day, from μ and the first a term, to
    /// 16 digits.
    @Test("Mean motions match TestL1.2.res")
    func meanMotions() {
        let motions = [3.547107064991332, 1.768264377426076, 0.8778944470559955, 0.3763306844621929]
        for moon in Moons.Moon.allCases {
            let model = Moons.models[moon.rawValue]
            let a = model.a[0].amplitude
            #expect(model.a[0].frequency == 0 && model.a[0].phase == 0, "\(moon)")
            let motion = (model.mu / (a * a * a)).squareRoot()
            // Half a unit in the 16th printed digit, plus rounding.
            #expect(abs(motion / motions[moon.rawValue] - 1) < 1e-15, "\(moon) \(motion)")
        }
    }

    /// L1.2.f's rotation from its jovicentric frame to J2000, written out:
    /// X = x cos Ψ − y sin Ψ cos I + z sin I sin Ψ, Y = x sin Ψ + y cos Ψ cos I − z sin I cos Ψ,
    /// Z = y sin I + z cos I.
    @Test("The rotation to J2000 is L1.2.f's")
    func rotation() {
        let (psi, i) = (Moons.psi, Moons.inclination)
        for v in [SIMD3(1.0, 0, 0), SIMD3(0, 1.0, 0), SIMD3(0, 0, 1.0), SIMD3(0.3, -0.7, 0.2)] {
            let expected = SIMD3(
                v.x * cos(psi) - v.y * sin(psi) * cos(i) + v.z * sin(i) * sin(psi),
                v.x * sin(psi) + v.y * cos(psi) * cos(i) - v.z * sin(i) * cos(psi),
                v.y * sin(i) + v.z * cos(i))
            // The two sides round three products and two sums in different orders.
            #expect(EngineGravityTests.length(Moons.jupiterToEQJ.apply(to: v) - expected) < 1e-15, "\(v)")
        }
        PublishedOrientation.expectProperRotation(PublishedOrientation.matrix(Moons.jupiterToEQJ))
    }

    // MARK: - JPL Horizons

    /// Horizons' Galilean moons from Jupiter's center: 1900, 2000 and 2100
    /// (`sources/horizons/<moon>-vector.json`), and both ends of JD
    /// 2426545.0 to 2476545.0, every 2,500 days between and a day outside
    /// each end (`<moon>-domain-vector.json`).
    static let vectors = IndependentReferenceArchive.shared.vectors.filter { $0.origin == "jupiter" }

    static let domain = 2_426_545.0...2_476_545.0

    static let moons: [String: Moons.Moon] = [
        "io": .io, "europa": .europa, "ganymede": .ganymede, "callisto": .callisto,
    ]

    /// The position and velocity errors over Horizons' distance and speed,
    /// as `AuditValidationTests` measures them, with Horizons' ICRF axes
    /// rotated to EQJ.
    static func errors(
        _ state: Engine.State<Engine.EQJ>, _ reference: IndependentReferenceArchive.Vector
    ) -> (position: Double, velocity: Double) {
        (
            States.relativeError(States.position(state), States.eqj(reference.positionAU)),
            States.relativeError(States.velocity(state), States.eqj(reference.velocityAUPerDay))
        )
    }

    @Test("The samples cover the domain from end to end and step outside it")
    func samplesCoverTheDomain() {
        let ends = [Self.domain.lowerBound, Self.domain.upperBound]
        let outside = [Self.domain.lowerBound - 1, Self.domain.upperBound + 1]
        for moon in ["io", "europa", "ganymede", "callisto"] {
            let rows = Self.vectors.filter { $0.body == moon }
            let bounded = Set(rows.filter { $0.relativeTolerance != nil }.map(\.julianDateTDB))
            let between = stride(from: Self.domain.lowerBound + 2_500, to: Self.domain.upperBound, by: 2_500)
            #expect(bounded == Set(ends + between + [2_451_544.5]), "\(moon)")
            let unbounded = Set(rows.filter { $0.relativeTolerance == nil }.map(\.julianDateTDB))
            #expect(unbounded == Set(outside + [2_415_020.5, 2_488_069.5]), "\(moon)")
        }
    }

    /// The qualified representation limits are continuous coefficient bounds relative to jup365. The 104 Horizons rows independently check the complete public clock, origin, frame and unit path at finite epochs.
    @Test("States match all archived Horizons rows within the qualified km limits", arguments: vectors)
    func horizons(reference: IndependentReferenceArchive.Vector) throws {
        let moon = try #require(Self.moons[reference.body], "unexpected Galilean moon \(reference.body)")
        let tt = Horizons.tt(reference)
        let state = try Moons.state(of: moon, at: Self.time(tt: tt))
        let positionError = EngineGravityTests.length(States.position(state) - States.eqj(reference.positionAU))
        let referenceVelocity = States.eqj(reference.velocityAUPerDay) * Engine.TDB.rate(tt: tt)
        let velocityError = EngineGravityTests.length(States.velocity(state) - referenceVelocity)
        #expect(positionError * Engine.kilometersPerAU <= 0.25, "\(reference.body) \(reference.julianDateTDB)")
        #expect(velocityError * Engine.kilometersPerAU <= 35, "\(reference.body) \(reference.julianDateTDB)")
    }

    @Test("The check fails for the wrong moon or an hour off")
    func negativeControls() throws {
        let reference = try #require(Self.vectors.first { $0.body == "io" && $0.relativeTolerance != nil })
        let tt = Horizons.tt(reference)
        let europa = try Moons.state(of: .europa, at: Self.time(tt: tt))
        #expect(Self.errors(europa, reference).position * Engine.kilometersPerAU > 0.25)
        let late = try Moons.state(of: .io, at: Self.time(tt: tt + 1.0 / 24))
        #expect(Self.errors(late, reference).position * Engine.kilometersPerAU > 0.25)
        #expect(Self.errors(late, reference).velocity * Engine.kilometersPerAU > 35)
    }

    // MARK: - jup365 representation and selection

    @Test("Every qualified direct fixture decodes from the compiled table")
    func directFixtures() throws {
        let indices = ["io": 0, "europa": 1, "ganymede": 2, "callisto": 3, "jupiter": 4]
        #expect(Self.representation.directFixtures.count == 45)
        for fixture in Self.representation.directFixtures {
            let index = try #require(indices[fixture.component])
            let state = try #require(Moons.Jup365.evaluate(component: index, at: fixture.julianDateTDB))
            let expectedPosition = SIMD3(fixture.candidatePositionKm)
            let expectedVelocity = SIMD3(fixture.candidateVelocityKmPerTDBDay)
            #expect(
                EngineGravityTests.length(state.positionKm - expectedPosition) < 1e-6,
                "\(fixture.component) \(fixture.julianDateTDB)")
            #expect(
                EngineGravityTests.length(state.velocityKmPerTDBDay - expectedVelocity) < 1e-4,
                "\(fixture.component) \(fixture.julianDateTDB)")
        }
    }

    @Test("Record selection keeps the half-open source domain and actual internal seam")
    func sourceBoundaries() throws {
        let table = Moons.Jup365.self
        #expect(table.evaluate(component: 0, at: table.startJDTDB.nextDown) == nil)
        #expect(table.evaluate(component: 0, at: table.startJDTDB) != nil)
        #expect(table.evaluate(component: 0, at: table.exclusiveEndJDTDB.nextDown) != nil)
        #expect(table.evaluate(component: 0, at: table.exclusiveEndJDTDB) == nil)
        #expect(table.evaluate(component: 0, at: table.exclusiveEndJDTDB, includingExclusiveEnd: true) != nil)
        for epoch in [table.sourceSeamJDTDB.nextDown, table.sourceSeamJDTDB, table.sourceSeamJDTDB.nextUp] {
            let state = try #require(table.evaluate(component: 0, at: epoch))
            #expect(EngineGravityTests.length(state.positionKm).isFinite)
            #expect(EngineGravityTests.length(state.velocityKmPerTDBDay).isFinite)
        }
        let recordSeam = table.startJDTDB + table.components[0].recordDays
        for epoch in [recordSeam.nextDown, recordSeam, recordSeam.nextUp] {
            #expect(table.evaluate(component: 0, at: epoch) != nil)
        }
        for epoch in [Double.nan, .infinity, -.infinity] {
            #expect(table.evaluate(component: 0, at: epoch) == nil)
        }
        #expect(table.evaluate(component: -1, at: table.startJDTDB) == nil)
        #expect(table.evaluate(component: 5, at: table.startJDTDB) == nil)
    }

    @Test("The full source span is unblended and the exterior bridges meet both models")
    func endpointTransitions() throws {
        let table = Moons.Jup365.self
        for moon in Moons.Moon.allCases {
            for (tt, julianDate, includeEnd) in [
                (table.startTT, table.startJDTDB, false),
                (table.endTT, table.exclusiveEndJDTDB, true),
            ] {
                let time = Self.time(tt: tt)
                let rate = Engine.TDB.rate(tt: tt)
                let source = try #require(
                    table.state(
                        of: moon, atJulianDateTDB: julianDate, rate: rate, time: time, includingExclusiveEnd: includeEnd
                    ))
                let selected = try Moons.state(of: moon, at: time)
                #expect(
                    EngineGravityTests.length(States.position(selected) - States.position(source)) < 1e-14,
                    "\(moon) \(julianDate)")
                #expect(
                    EngineGravityTests.length(States.velocity(selected) - States.velocity(source)) < 1e-14,
                    "\(moon) \(julianDate)")
            }
            for tt in [table.startTT - table.transitionDays, table.endTT + table.transitionDays] {
                let time = Self.time(tt: tt)
                let selected = try Moons.state(of: moon, at: time)
                let fallback = try Moons.state(Moons.models[moon.rawValue], at: time)
                #expect(States.position(selected) == States.position(fallback), "\(moon) \(tt)")
                #expect(States.velocity(selected) == States.velocity(fallback), "\(moon) \(tt)")
            }
            for tt in [table.startTT - table.transitionDays / 2, table.endTT + table.transitionDays / 2] {
                let time = Self.time(tt: tt)
                let selected = try Moons.state(of: moon, at: time)
                let fallback = try Moons.state(Moons.models[moon.rawValue], at: time)
                #expect(States.position(selected) != States.position(fallback), "\(moon) \(tt)")
                #expect(States.velocity(selected) != States.velocity(fallback), "\(moon) \(tt)")
            }
        }
    }

    @Test("Representable endpoint neighbors remain finite and continuous")
    func endpointNeighbors() throws {
        let table = Moons.Jup365.self
        for moon in Moons.Moon.allCases {
            for boundary in [table.startTT, table.endTT] {
                let before = try Moons.state(of: moon, at: Self.time(tt: boundary.nextDown))
                let at = try Moons.state(of: moon, at: Self.time(tt: boundary))
                let after = try Moons.state(of: moon, at: Self.time(tt: boundary.nextUp))
                for (side, adjacent) in [("before", before), ("after", after)] {
                    #expect(
                        EngineGravityTests.length(States.position(adjacent) - States.position(at)) < 1e-9,
                        "\(moon) \(boundary) \(side)")
                    #expect(
                        EngineGravityTests.length(States.velocity(adjacent) - States.velocity(at)) < 1e-8,
                        "\(moon) \(boundary) \(side)")
                }
            }
        }
    }

    // MARK: - Composition and guards

    @Test("All four states are each moon's, at the time given")
    func statesAreEachMoons() throws {
        for tt in [-1_000_000.0, -36_525, 0, 9_497.25, 36_525, 1_000_000] {
            let time = Self.time(tt: tt)
            let states = try Moons.states(at: time)
            let all = [states.io, states.europa, states.ganymede, states.callisto]
            for moon in Moons.Moon.allCases {
                let state = try Moons.state(of: moon, at: time)
                let expected = all[moon.rawValue]
                #expect(
                    [state.x, state.y, state.z, state.vx, state.vy, state.vz]
                        == [expected.x, expected.y, expected.z, expected.vx, expected.vy, expected.vz],
                    "\(moon) tt \(tt)")
                #expect(state.time.tt == tt && state.time.ut == time.ut)
            }
        }
    }

    @Test("Times at and beyond the accepted range")
    func acceptedRange() throws {
        for tt in [Engine.acceptedTTDays, -Engine.acceptedTTDays] {
            let states = try Moons.states(at: Self.time(tt: tt))
            #expect(EngineGravityTests.length(States.position(states.callisto)).isFinite)
        }
        for tt in [
            Engine.acceptedTTDays.nextUp, -Engine.acceptedTTDays.nextUp, .nan, .infinity, -.infinity,
        ] {
            #expect(throws: AstronomyError.badTime) { try Moons.states(at: Self.time(tt: tt)) }
            #expect(throws: AstronomyError.badTime) { try Moons.state(of: .io, at: Self.time(tt: tt)) }
        }
    }

    @Test("A state that is not finite throws badTime")
    func nonFiniteState() {
        let model = Moons.models[0]
        let collapsed = Moons.Model(
            mu: model.mu, meanLongitude: model.meanLongitude, a: [Moons.Term(0, 0, 0)], l: model.l, z: model.z,
            zeta: model.zeta)
        #expect(throws: AstronomyError.badTime) { try Moons.state(collapsed, at: Self.time(tt: 0)) }
        let infinite = Moons.Model(
            mu: .infinity, meanLongitude: model.meanLongitude, a: model.a, l: model.l, z: model.z, zeta: model.zeta)
        #expect(throws: AstronomyError.badTime) { try Moons.state(infinite, at: Self.time(tt: 0)) }
    }

    /// The bound ``Engine/JupiterMoons/keplerIterationLimit`` rests on: no
    /// eccentricity above the sum of the z amplitudes, 0.0104 at most.
    @Test("The series bound each eccentricity below 0.0104")
    func eccentricityBound() {
        for model in Moons.models {
            #expect(model.z.map { abs($0.amplitude) }.reduce(0, +) < 0.0104)
        }
    }

    @Test("Kepler's equation and the mean longitude where the series reach, and the bounded iteration")
    func kepler() throws {
        // 401 times from one end of the accepted range to the other, both ends included.
        let times = Array(stride(from: -Engine.acceptedTTDays, through: Engine.acceptedTTDays, by: 7_305))
        #expect(times.count == 401)
        #expect(times.first == -Engine.acceptedTTDays && times.last == Engine.acceptedTTDays)
        for moon in Moons.Moon.allCases {
            for tt in times {
                let e = Moons.elements(of: Moons.models[moon.rawValue], tt: tt)
                let f = try Moons.eccentricAnomaly(meanLongitude: e.meanLongitude, k: e.k, h: e.h)
                let residual = f - e.k * sin(f) + e.h * cos(f) - e.meanLongitude
                #expect(abs(residual) < 1e-14, "\(moon) tt \(tt)")
                #expect((0..<2 * .pi).contains(e.meanLongitude), "\(moon) tt \(tt)")
            }
        }
        // An eccentricity near 1 sends Newton's method far off within the limit.
        #expect(throws: AstronomyError.noConvergence) {
            try Moons.eccentricAnomaly(meanLongitude: 0.0377, k: 0.999, h: 0)
        }
        // A step that is not a number ends the iteration, as in ELEM2PV.
        #expect(try Moons.eccentricAnomaly(meanLongitude: .nan, k: 0, h: 0).isNaN)
    }
}
