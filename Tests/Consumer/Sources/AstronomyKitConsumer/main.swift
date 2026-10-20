import AstronomyKit

let time = AstroTime(year: 2026, month: 1, day: 2)
for body in [CelestialBody.moon, .mercury, .saturn, .pluto] {
    let position = try body.geocentricPosition(at: time)
    precondition(position.x.isFinite && position.y.isFinite && position.z.isFinite)
}
