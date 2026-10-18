# jup365 representation qualification

This directory holds a reproducible mixed-precision representation of JPL's jup365 Galilean-satellite kernel. It is qualification input for issue #254, not a runtime table: `Engine.JupiterMoons` still uses the truncated L1.2 series. The later runtime change must select this representation only inside its documented domain, preserve L1.2 outside it, and supply derivative-consistent endpoint transitions.

## Source and coordinates

The pinned source is NAIF's `jup365.bsp`, 1,136,581,632 bytes with HTTP `Last-Modified: Sun, 14 Mar 2021 15:29:22 GMT`. `representation.json` records SHA-256 values for the 113 byte ranges needed to parse and extract it. `jup365.cmt` is the checked-in source comment, with its URL and digest in the report.

The source contains two contiguous SPK type-2 segment sets on ICRF axes and TDB time. Its actual segment domain is JD TDB `[2305456.5, 2524602.5)`, with a segment seam at JD TDB 2450464.5. Targets 501 through 504 and Jupiter's body center 599 are all relative to Jupiter-system barycenter 5, so the qualified jovicentric state subtracts target 599. The final Chebyshev record extends beyond the final segment endpoint as source padding; the report and evaluator stop at the segment endpoint.

The source comment states a 16 m Chebyshev interpolation error. That statement describes the upstream kernel interpolation and is neither a measured physical-orbit error nor part of the representation bounds below.

## Representation

Each axis stores its leading coefficients as little-endian Float32 values and the remaining retained coefficients as little-endian signed Int16 values with one binary64 scale for each axis and degree. Later coefficients are zero. The scale is the largest absolute source coefficient at that axis and degree divided by 32,767. The selection followed exhaustive scans of every source record; it was not chosen from the 104 Horizons samples.

| Component | Records | Days per record | Source / kept / Float32 coefficients | Encoded bytes |
|---|---:|---:|---:|---:|
| Io | 194,797 | 1.125 | 16 / 11 / 6 | 19,869,294 |
| Europa | 194,797 | 1.125 | 16 / 9 / 4 | 15,194,166 |
| Ganymede | 194,797 | 1.125 | 10 / 7 / 3 | 11,687,820 |
| Callisto | 97,399 | 2.25 | 11 / 7 / 4 | 6,428,334 |
| Jupiter center | 97,399 | 2.25 | 16 / 10 / 2 | 7,012,728 |

The five payloads total 60,192,342 decoded bytes. Their base64 payload alone would occupy 80,256,456 bytes before Swift syntax. Full Float32 storage for every source coefficient would occupy 129,734,964 decoded bytes. A fixed-truncation Float32 candidate that kept the combined position bound below 1 km occupied about 73.6 MB but had a combined derivative bound as high as 143 km per TDB day. The selected candidate uses about 46% of full Float32 storage and leaves substantially tighter derivative bounds.

For a source coefficient `c_n`, represented coefficient `ĉ_n`, and normalized record coordinate `x` in `[-1, 1]`, the generator uses `|T_n(x)| ≤ 1` and `|T'_n(x)| ≤ n²`. For each record and axis it sums `|c_n - ĉ_n|` for position and `2 n² |c_n - ĉ_n| / recordDays` for velocity, takes the Euclidean norm of the three axis sums, and retains the maximum over every source record. Adding each moon's component bound to Jupiter's by the triangle inequality gives a continuous jovicentric bound over the complete half-open source domain.

| Moon | Position bound (km) | Analytic derivative bound (km/TDB day) |
|---|---:|---:|
| Io | 0.206162 | 33.735439 |
| Europa | 0.228247 | 21.898472 |
| Ganymede | 0.223438 | 7.527488 |
| Callisto | 0.197329 | 5.479946 |

These bounds cover coefficient truncation and packing relative to the pinned source polynomials. They exclude binary64 evaluation rounding and do not certify jup365's physical accuracy.

## Independent comparisons

The generator also compares the jovicentric candidate with all 104 archived Horizons states, 26 per moon, using their pinned recipes: center 500@599, geometric vectors, ICRF axes, TDB epochs, and AU-D units. The largest sampled position residual is 0.127337 km, for Ganymede at JD TDB 2471545.0. The largest sampled velocity residual is 20.386433 km per TDB day, for Io at JD TDB 2469045.0. These finite samples check origin, axes, clock, units, and the decoded payload; they are not continuous bounds or a statement of physical accuracy.

Forty-five direct fixtures cover every component at the source start, both sides of the actual internal segment seam, a representative record seam and interior, and the last representable time before the source end. Offline replay recomputes the candidate side. Remote source replay recomputes every coefficient bound, every source comparison, and all payload bytes from the pinned kernel ranges.

## Size and latency measurements

The unchanged base at `b6f0cc0c4027ef626e2ba8686914cd472f99de80` contained 461,284 KiB under `Sources/AstronomyKit`, including 63,556 KiB of generated DE441 source. A clean arm64 Release build with Swift 6.4 completed in 45.57 seconds wall time (`swift build` reported 31.77 seconds), produced a 471,846,304-byte static library and a 471,779,496-byte AstronomyKit object, and reported 8,356,184,064 bytes maximum resident set size and 743,180,352 bytes peak memory footprint. The command was `/usr/bin/time -lp swift build -c release -j 2 --scratch-path .context/issue-254/baseline-build`.

`performance.json` binds a standalone Swift probe to this representation. On the recorded arm64 macOS host with Swift 6.4 and `swiftc -O`, mapping the manifest and five payloads took 1.916 ms. A first pass over 200,000 jovicentric states spanning the full domain took 0.847 µs per state; a second pass took 0.841 µs per state. The checksum was identical across passes. This measures the candidate lookup and polynomial evaluation from memory-mapped binary payloads on that host. It does not predict the final package, compile, launch, or cache cost of link 2's compiled representation.

## Reproduction

Run the local controls from the repository root:

```sh
python3 -m unittest Scripts/test_generate_galilean_jup365.py -v
python3 Scripts/generate-galilean-jup365.py --check
python3 Scripts/generate-galilean-jup365.py --measure --iterations 200000
```

`--check` is offline. It checks generator and reference bindings, payload shapes and digests, coverage and coordinate semantics, all direct fixtures, all 104 archived Horizons rows, the continuous bound limits, and the performance-record bindings. `--measure` recompiles the checked-in Swift probe and replaces `performance.json` with a host-specific measurement.

The source replay uses the official kernel, the cached ranges when available, and the checked-in range hashes:

```sh
python3 Scripts/generate-galilean-jup365.py --verify-source --cache .context/issue-254/ranges
```

`--capture` is the supported replacement workflow. It extracts and packs every source record, rebuilds the continuous bounds and finite comparisons, validates the result, and atomically replaces the payloads, comment, and report. Run it after changing a bound owner, layout, source parser, or reference input, then rerun `--measure` because the performance record is bound to the report digest.
