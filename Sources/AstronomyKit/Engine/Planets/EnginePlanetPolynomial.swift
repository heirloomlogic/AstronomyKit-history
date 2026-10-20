//
//  EnginePlanetPolynomial.swift
//  AstronomyKit
//
//  Chebyshev fits of the compensated VSOP87B series from 1900 through 2100 TT.
//

extension Engine {
    /// Chebyshev polynomial fits of each planet's heliocentric position in
    /// the VSOP87B frame (ecliptic and equinox of J2000), from ``start`` up to
    /// ``stop``.
    ///
    /// Each planet's span is cut into segments of equal width in days, each
    /// with its own polynomials in x, y and z, of degree 12 in the shipped
    /// tables. A segment that did not
    /// meet the fit budget is excluded, and a caller uses the full series
    /// there, as it does outside the span.
    enum PlanetPolynomial {
        /// One planet's segments.
        struct Model: Sendable {
            /// The degree of every segment's polynomial.
            let degree: Int
            /// The width of every segment in days.
            let width: Double
            /// For each segment, for each of x, y and z, the coefficients of
            /// the Chebyshev polynomials T₀ to T_degree, in AU.
            let coefficients: Engine.Binary64Table
            /// Whether each segment has a usable polynomial.
            let included: [Bool]

            /// Traps unless the coefficients fill whole segments that reach
            /// ``PlanetPolynomial/stop``.
            init(degree: Int, width: Double, excludedSegments: [Int], coefficients: [Double]) {
                self.init(
                    degree: degree, width: width, excludedSegments: excludedSegments,
                    coefficients: Engine.Binary64Table(coefficients))
            }

            init(
                degree: Int, width: Double, excludedSegments: [Int],
                coefficients: Engine.Binary64Table
            ) {
                let count = coefficients.count / (3 * (degree + 1))
                precondition(count * 3 * (degree + 1) == coefficients.count, "Partial polynomial segment")
                precondition(
                    Double(count) * width >= PlanetPolynomial.stop - PlanetPolynomial.start,
                    "Polynomial segments end before the span does")
                var included = [Bool](repeating: true, count: count)
                for segment in excludedSegments { included[segment] = false }
                self.degree = degree
                self.width = width
                self.coefficients = coefficients
                self.included = included
            }

            /// The number of segments.
            var segmentCount: Int { included.count }

            /// Segments with no usable polynomial, in increasing order.
            var excludedSegments: [Int] { included.indices.filter { !included[$0] } }

            /// The first TT of segment `k`, an exact double.
            func start(ofSegment k: Int) -> Double {
                PlanetPolynomial.start + Double(k) * width
            }

            /// The segment whose interval holds `tt`, or `nil` when `tt` is
            /// not from ``PlanetPolynomial/start`` up to
            /// ``PlanetPolynomial/stop``, including when it is not finite.
            ///
            /// Segment `k` holds `start + k·width ≤ tt < start + (k + 1)·width`.
            /// Every boundary is an exact double. The subtraction `tt − start`
            /// can round the double just below a boundary up to the boundary's
            /// offset (dividing by a power-of-two width is exact), so such a
            /// `tt` is moved back to the segment below.
            func segment(containing tt: Double) -> Int? {
                guard PlanetPolynomial.covers(tt) else { return nil }
                var segment = Int((tt - PlanetPolynomial.start) / width)
                if segment > 0, start(ofSegment: segment) > tt { segment -= 1 }
                return segment
            }

            /// The position in AU at `tt`, or `nil` outside the span or in an
            /// excluded segment.
            func position(tt: Double) -> SIMD3<Double>? {
                evaluate(tt: tt, velocity: false)?.position
            }

            /// The position in AU and the velocity in AU per TT day at `tt`,
            /// or `nil` outside the span or in an excluded segment. The
            /// position is the same double for double as ``position(tt:)``.
            func state(tt: Double) -> (position: SIMD3<Double>, velocity: SIMD3<Double>)? {
                evaluate(tt: tt, velocity: true)
            }

            /// Clenshaw's recurrence for the value and, when `velocity` is
            /// true, its derivative, with `x` running from −1 to 1 across the
            /// segment.
            private func evaluate(tt: Double, velocity: Bool) -> (position: SIMD3<Double>, velocity: SIMD3<Double>)? {
                guard let segment = segment(containing: tt), included[segment] else { return nil }
                let half = width / 2
                let x = (tt - start(ofSegment: segment)) / half - 1
                let n = degree + 1
                var position = SIMD3<Double>()
                var rate = SIMD3<Double>()
                for axis in 0..<3 {
                    let first = (segment * 3 + axis) * n
                    var b1 = 0.0
                    var b2 = 0.0
                    var d1 = 0.0
                    var d2 = 0.0
                    for k in stride(from: degree, through: 1, by: -1) {
                        let b = 2 * x * b1 - b2 + coefficients[first + k]
                        if velocity {
                            let d = 2 * b1 + 2 * x * d1 - d2
                            d2 = d1
                            d1 = d
                        }
                        b2 = b1
                        b1 = b
                    }
                    position[axis] = x * b1 - b2 + coefficients[first]
                    if velocity { rate[axis] = (b1 + x * d1 - d2) / half }
                }
                return (position, rate)
            }
        }

        /// Whether `tt` is from ``start`` up to ``stop``; false when it is not
        /// finite.
        static func covers(_ tt: Double) -> Bool {
            tt >= start && tt < stop
        }

        /// The fits for `planet`. The first call for a planet decodes its
        /// table.
        static func model(_ planet: Planet) -> Model {
            switch planet {
            case .mercury: mercury
            case .venus: venus
            case .earth: earth
            case .mars: mars
            case .jupiter: jupiter
            case .saturn: saturn
            case .uranus: uranus
            case .neptune: neptune
            }
        }

        /// The position of `planet` in AU at `tt`, or `nil` where the fits do
        /// not apply. A `tt` outside the span does not decode the table.
        static func position(_ planet: Planet, tt: Double) -> SIMD3<Double>? {
            guard covers(tt) else { return nil }
            return model(planet).position(tt: tt)
        }

        /// The position of `planet` in AU and its velocity in AU per TT day at
        /// `tt`, or `nil` where the fits do not apply. A `tt` outside the span
        /// does not decode the table.
        static func state(_ planet: Planet, tt: Double) -> (position: SIMD3<Double>, velocity: SIMD3<Double>)? {
            guard covers(tt) else { return nil }
            return model(planet).state(tt: tt)
        }
    }
}
