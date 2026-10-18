# Downstream acceptance baseline

This report records a partial downstream qualification of AstronomyKit `68d80a16b150a2c22d972cdf7db0bbe75e0ff3d3` performed on 2026-10-18. It is a historical baseline for issue #98. It does not qualify current main `4ee2aa6cea1ffd48b064b62a95c36fb7cb543b50`, which subsequently merged the fixed-star motion, eclipse convention, event-search acceptance, and civil UTC observer changes from pull requests #309, #311, #313, and #314. Final release acceptance remains unmet until the same consumer scope is replayed against the release candidate and every incomplete or blocked area required by #98 is resolved.

## Reproduction boundary

The qualification used unchanged manifests and tests from the two direct, non-archived Heirloom Logic Swift-package consumers found by enumerating organization repositories and inspecting their manifests. AstrologyKit was pinned at `347eddf5bc69837fff9f986a074d577032d7aae3`; its `Package.swift` SHA-256 was `0fdcb5635e0df53cf3891718e6dde29246176928aed06d3b854b31965abc736a` and declared AstronomyKit exactly `3.2.0+upstream-2.1.19`. ElectionalKit was pinned at `b9cd413e5db3a64304d2afcb5e1bbe42e1910925`; its manifest SHA-256 was `09bd04c7506ee5142601e69a4e388bda5ce06a50f20e28441725e42fbfe01d4b` and declared AstronomyKit from `3.1.0` plus AstrologyKit on `main`.

Each consumer ran in an isolated checkout. SwiftPM mirrors redirected the declared dependency URLs to local bare repositories: the candidate commit was exposed only inside the mirror under the consumer's required `3.2.0+upstream-2.1.19` tag, and ElectionalKit's AstrologyKit `main` resolved to the pinned revision above. No consumer source, manifest, published dependency, scientific tolerance, runtime fixture, or workflow was changed.

The machine was an Apple M1 Max with 64 GiB running macOS 27.0.0 and Apple Swift 6.4 (`swiftlang-6.4.0.34.1 clang-2100.3.34.1`) for `arm64-apple-macosx27.0.0`. Commands ran with `TZ=UTC`. The candidate reported `AstronomyConfig.ephemerisVersion` as `3.0.0+vsop87b-comp.poly-v2.iau2000b.utc-c72.deltat-iers-c04-20260917-pred-20271004-smh2020.native-libm`; downstream persisted numerical caches must continue to bind that identifier together with platform, architecture, OS, and toolchain.

The exact candidate revision also has a completed scheduled [Deep validation run](https://github.com/heirloomlogic/AstronomyKit/actions/runs/39125287365). Its thread-sanitizer job passed. Its macOS Debug job failed because the independent apparent-integration reference differed, before the Swift test step, which was skipped. That hosted run is not a green exact-revision gate.

Run the bounded workflow and inspect its timeout behavior with the commands in [`Scripts/downstream-qualification/README.md`](../../Scripts/downstream-qualification/README.md). The machine-readable measurements are in [`results.json`](../../Scripts/downstream-qualification/results.json). A run stopped by its time bound is recorded as incomplete, never as a failure or pass.

## Observed results

AstrologyKit's declared-version Release baseline completed but failed: its main target reported 1,040 tests in 116 suites with 12 issues, including three known issues, and its public consumer target reported 59 tests in seven suites with three issues. A serial replay produced the same stderr-capture and known-vacuity failures under Swift 6.4/macOS 27. The command took 117.66 seconds and reached 2,653,208,576 bytes maximum resident size.

With the candidate override, AstrologyKit's Debug test build passed in 52.26 seconds with 5,179,654,144 bytes maximum resident size. The full Debug suite was stopped after 665.10 seconds without a test summary and is incomplete. Release test compilation was blocked in both supported build paths: the default build could not resolve a compatible testable AstrologyKit module, while the deprecated native fallback reported that AstrologyKit was not compiled for testing. Release and Debug durations therefore are not a performance comparison.

Focused AstrologyKit Debug checks passed for fixed-star longitudes (4 tests), polar edge regression (6), multi-decade positions (3), and election event service behavior (17). Analytic event motion emitted no summary before its 120-second bound and is incomplete. The public consumer target reported one failure among 59 tests: its published Regulus assertion remained within 0.001 degrees of 150.1977 degrees, but its separate expectation that AstrologyKit and AstronomyKit differ by more than 0.3 degrees failed after both APIs returned ecliptic-of-date values. This identifies a stale cross-library-difference expectation; the single surviving published-position assertion does not by itself prove improved scientific accuracy.

ElectionalKit's Debug test build passed in 57.15 seconds with 5,184,880,640 bytes maximum resident size. Its public consumer (31 tests), published elections (8), assessment (20), and search-horizon (22) filters passed. The one-day and seven-day production search benchmarks passed without exhausting their work limits. They respectively measured 58,368 and 439,281 event evaluations, 23 and 100 candidates, 90 and 648 unresolved intervals, unresolved shares of 0.0005208354 and 0.0005365431, and no unresolved interval over three seconds.

The existing one-day terrestrial-window recorder passed in 47.86 seconds of workload time. It returned 10 candidates without exhaustion or cancellation, performed 403,556 event evaluations, charged 543 chart evaluations from 14,628 logical evaluations after 14,085 cache hits, made 30 contact-fact build attempts, and measured 168 unresolved intervals with an unresolved share of 0.0005049548. The seven-day version produced no result file or test summary before its 240-second bound and is incomplete.

## Acceptance inventory

- Verified at the pinned historical candidate: both direct consumers resolve and build in Debug; representative fixed-star, polar, multi-decade, election-event, published-election, assessment, search-horizon, one-day search, seven-day search, and one-day terrestrial-window paths have the outcomes above.
- Failed at the pinned historical candidate: AstrologyKit's unchanged public consumer expectation that its Regulus value differ from AstronomyKit by more than 0.3 degrees.
- Blocked by the pinned consumer/toolchain combination: AstrologyKit Release test compilation, so no candidate Release test result or Release resource measurement was established.
- Incomplete at the recorded bounds: AstrologyKit's full Debug suite, AstrologyKit analytic event motion, and ElectionalKit's seven-day terrestrial-window workload.
- Untested: a final run against current main or another release-candidate revision; ElectionalKit's declared dependency baseline; Chiron through a production consumer call; startup latency and allocation counts; non-macOS platforms; Xcode application integration; and any consumer outside the enumerated direct Swift-package manifests.

No production consumer call to Chiron was present in the pinned manifests and source trees; the only downstream occurrence was documentation in a dependency-pin test. Chiron remains unqualified downstream. The main-revision evidence merged after this baseline supplies library-level reference qualification, but it does not substitute for a downstream replay.

Issue #98 remains open. A release decision needs a fresh exact-revision run, explicit disposition of the Regulus expectation, complete required long-running scenarios or an owner-approved bound, Release coverage, Chiron coverage where a real consumer exists, and the remaining resource and platform evidence requested by the issue.
