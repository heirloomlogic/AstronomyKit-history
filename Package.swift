// swift-tools-version: 6.0

import Foundation
import PackageDescription

let package = Package(
    name: "AstronomyKit",
    platforms: [
        .macOS(.v15),
        .iOS(.v18),
        .tvOS(.v18),
        .watchOS(.v11),
    ],
    products: [
        .library(
            name: "AstronomyKit",
            targets: ["AstronomyKit"]
        ),
    ],
    targets: [
        .target(
            name: "AstronomyKit",
            resources: [.copy("Resources/ModelTables")]
        ),
        .target(
            name: "CLibAstronomy",
            path: "Sources/CLibAstronomy",
            publicHeadersPath: "include",
            cSettings: [
                .headerSearchPath("include")
            ]
        ),
        .testTarget(
            name: "AstronomyKitTests",
            dependencies: ["AstronomyKit"],
            exclude: ["Fixtures"]
        ),
    ]
)

// MARK: - Dev-only tooling
//
// Dev-only tooling (the Persnoop swift-format linter and swift-docc-plugin) must not leak
// into downstream consumers' dependency graphs. A build-tool plugin attached to a shipping
// target follows that target into every consumer — as a forced "trust and enable" prompt in
// Xcode, not merely a wasted checkout. SwiftPM has no first-class dev dependencies, so gate
// them on a gitignored `.dev-tooling` sentinel, present only in this package's own working
// clone (and created as a step in CI, before the first resolve).
//
// `#filePath` anchors the lookup to this manifest's directory, independent of the current
// working directory. Attaching the plugin here, after the package is constructed, keeps the
// target list above free of gating noise.
//
// Toggling the sentinel on an already-evaluated package requires `swift package purge-cache`:
// SwiftPM caches the evaluated manifest keyed on its source text alone, so a gate that reads
// an external file is invisible to that cache key.

let packageDir = URL(fileURLWithPath: #filePath).deletingLastPathComponent()
let devSentinel = packageDir.appendingPathComponent(".dev-tooling").path

if FileManager.default.fileExists(atPath: devSentinel) {
    package.dependencies += [
        .package(url: "https://github.com/apple/swift-docc-plugin", from: "1.5.0"),
        .package(url: "https://github.com/heirloomlogic/Persnicket", from: "2.0.0"),
    ]
    for target in package.targets where target.name != "CLibAstronomy" {
        target.plugins = (target.plugins ?? []) + [.plugin(name: "Persnoop", package: "Persnicket")]
    }
}
