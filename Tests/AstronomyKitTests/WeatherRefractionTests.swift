import Foundation
import Testing

@testable import AstronomyKit

@Suite("Weather-dependent refraction")
struct WeatherRefractionTests {
    struct PALArchive: Decodable {
        struct Row: Decodable {
            let apparentAltitudeDegrees: Double
            let pressureMillibars: Double
            let temperatureCelsius: Double
            let refractionDegrees: Double
        }

        let rows: [Row]
    }

    @Test("Conditions expose their units and preserve standard refraction")
    func standardConditions() throws {
        let conditions = try RefractionConditions(pressureMillibars: 1_010, temperatureCelsius: 10)
        #expect(conditions.pressureMillibars == 1_010)
        #expect(conditions.temperatureCelsius == 10)

        let weather = Refraction.weather(conditions)
        for altitude in [-90.0, -45, -1, 0, 5, 45, 90] {
            #expect(weather.refractionAngle(at: altitude) == Refraction.normal.refractionAngle(at: altitude))
            #expect(
                weather.inverseRefractionAngle(at: altitude)
                    == Refraction.normal.inverseRefractionAngle(at: altitude)
            )
        }
    }

    @Test("Pressure and temperature scale the published Sæmundsson correction")
    func publishedScaling() throws {
        let conditions = try RefractionConditions(pressureMillibars: 800, temperatureCelsius: -20)
        let model = Refraction.weather(conditions)
        #expect(abs(model.refractionAngle(at: 0) - 0.427_967_254_975_898_05) <= 1e-15)
    }

    @Test("The public horizon path applies the selected weather correction")
    func publicHorizon() throws {
        let time = AstroTime(tt: 9_496)
        let observer = Observer(latitude: 40, longitude: -74)
        let model = Refraction.weather(
            try RefractionConditions(pressureMillibars: 780, temperatureCelsius: -5)
        )
        let geometric = try CelestialBody.sun.horizon(
            at: time, from: observer, refraction: .none
        )
        let apparent = try CelestialBody.sun.horizon(
            at: time, from: observer, refraction: model
        )
        #expect(
            abs(
                apparent.altitude - geometric.altitude
                    - model.refractionAngle(at: geometric.altitude)
            ) <= 1e-12
        )
    }

    @Test(
        "Conditions reject values outside the declared computational domain",
        arguments: [
            (-Double.leastNonzeroMagnitude, 10.0), (10_000.0.nextUp, 10), (.nan, 10), (.infinity, 10),
            (1_010, (-173.15).nextDown), (1_010, 226.85.nextUp), (1_010, .nan), (1_010, .infinity),
            (10_000, 226.85),
        ]
    )
    func invalidConditions(pressureMillibars: Double, temperatureCelsius: Double) {
        #expect(throws: AstronomyError.invalidParameter) {
            try RefractionConditions(
                pressureMillibars: pressureMillibars,
                temperatureCelsius: temperatureCelsius
            )
        }
    }

    @Test("The accepted scale endpoints remain finite and invertible")
    func conditionEndpoints() throws {
        let maximumPressure = 2.0 * 1_010 * (273 - 100) / 283
        let conditions = [
            try RefractionConditions(pressureMillibars: 0, temperatureCelsius: -173.15),
            try RefractionConditions(pressureMillibars: maximumPressure, temperatureCelsius: -100),
        ]
        for conditions in conditions {
            let model = Refraction.weather(conditions)
            for apparent in [-89.0, -1, 0, 45, 89] {
                let geometric = apparent + model.inverseRefractionAngle(at: apparent)
                #expect(model.refractionAngle(at: geometric).isFinite)
                #expect(abs(geometric + model.refractionAngle(at: geometric) - apparent) <= 1e-12)
            }
        }
    }

    @Test("The maximum accepted scale stays increasing across the taper and derivative minimum")
    func monotonicExtrema() throws {
        let maximumPressure = 2.0 * 1_010 * (273 - 100) / 283
        let model = Refraction.weather(
            try RefractionConditions(pressureMillibars: maximumPressure, temperatureCelsius: -100)
        )
        let altitudes = [-90.0, -89, -1.000_000_01, -1, -0.999_999_99, -0.9, -0.8, -0.78, -0.7, 0, 45, 90]
        let mapped = altitudes.map { $0 + model.refractionAngle(at: $0) }
        for (lower, upper) in zip(mapped, mapped.dropFirst()) {
            #expect(lower < upper)
        }
    }

    @Test("The inverse undoes the weather-dependent forward correction")
    func inverseRoundTrip() throws {
        let model = Refraction.weather(
            try RefractionConditions(pressureMillibars: 780, temperatureCelsius: -5)
        )
        for apparent in [-80.0, -45, -1, 0, 0.5, 5, 45, 89] {
            let geometric = apparent + model.inverseRefractionAngle(at: apparent)
            let restored = geometric + model.refractionAngle(at: geometric)
            #expect(abs(restored - apparent) <= 1e-12, "apparent altitude \(apparent)")
        }
    }

    @Test("Horizon vectors use the same weather model in both directions")
    func horizonVectorRoundTrip() throws {
        let model = Refraction.weather(
            try RefractionConditions(pressureMillibars: 650, temperatureCelsius: 2)
        )
        let apparent = Spherical(latitude: 0.25, longitude: 123, distance: 1)
        let vector = Vector3D.from(horizon: apparent, at: AstroTime(tt: 9_496), refraction: model)
        let restored = Spherical.fromHorizonVector(vector, refraction: model)
        #expect(abs(restored.latitude - apparent.latitude) <= 1e-12)
        #expect(abs(restored.longitude - apparent.longitude) <= 1e-12)
        #expect(abs(restored.distance - apparent.distance) <= 1e-15)
    }

    @Test("Altitude input behavior matches the existing modes")
    func altitudeDomain() throws {
        let model = Refraction.weather(
            try RefractionConditions(pressureMillibars: 1_010, temperatureCelsius: 10)
        )
        #expect(model.refractionAngle(at: .nan).isNaN)
        for altitude in [-Double.infinity, Double(-90).nextDown, Double(90).nextUp, .infinity] {
            #expect(model.refractionAngle(at: altitude) == 0)
            #expect(model.inverseRefractionAngle(at: altitude) == 0)
        }
    }

    @Test("Sampled inverse correction stays within its recorded PAL ray-trace residuals")
    func palReferenceGrid() throws {
        let root = (0..<3).reduce(URL(fileURLWithPath: #filePath)) { url, _ in
            url.deletingLastPathComponent()
        }
        let data = try Data(
            contentsOf: root.appendingPathComponent("Scripts/refraction-data/pal-reference.json")
        )
        let archive = try JSONDecoder().decode(PALArchive.self, from: data)
        #expect(archive.rows.count == 180)

        for row in archive.rows {
            let model = Refraction.weather(
                try RefractionConditions(
                    pressureMillibars: row.pressureMillibars,
                    temperatureCelsius: row.temperatureCelsius
                )
            )
            let actual = -model.inverseRefractionAngle(at: row.apparentAltitudeDegrees)
            let residualArcseconds = abs(actual - row.refractionDegrees) * 3_600
            let limitArcseconds =
                if row.apparentAltitudeDegrees >= 5 { 16.0 } else if row.apparentAltitudeDegrees >= 0.5 { 140.0 } else {
                    220.0
                }
            #expect(
                residualArcseconds <= limitArcseconds,
                "P=\(row.pressureMillibars) mbar, T=\(row.temperatureCelsius)°C, h=\(row.apparentAltitudeDegrees)°"
            )
        }
    }
}
