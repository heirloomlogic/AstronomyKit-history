# Generated model resources

Issue [#245](https://github.com/heirloomlogic/AstronomyKit/issues/245) and the [owner-approved contract amendment](https://github.com/heirloomlogic/AstronomyKit/issues/245#issuecomment-6251331976) authorize bundled runtime-read binary resources for the Moon, Pluto, Saturn, and planet-polynomial coefficient tables. These resources remain generated build inputs: AstronomyKit does not download model data or fall back to another source at runtime.

Each `.bin` file is a sequence of little-endian IEEE 754 binary64 bit patterns in the same order used by its former generated Swift payload. Generated Swift metadata gives the resource name, exact byte count, and SHA-256 digest. `Engine.MappedBytes` opens the file read-only, checks its size, maps it with `MAP_PRIVATE`, verifies its digest before use, and unmaps it when the owning object is released. A missing, truncated, corrupt, or unexpected resource fails closed. The complete DE441 Moon is split into 90 independently verified chunks so a query maps only the chunk it needs.

SwiftPM copies `Sources/AstronomyKit/Resources/ModelTables` into `Bundle.module`. The clean consumer executable is built and run on macOS and Linux in hosted CI so resource packaging is tested outside the repository target. Apple SDK build jobs verify that the resource declaration remains portable to iOS, tvOS, and watchOS.

The six model generators own their resource prefixes and reject missing, extra, empty, or changed files in `--check` mode. `Scripts/verify-model-resource-migration.py --check` compares every migrated resource with the decoded payload at base revision `667bc909b7025f434e822a353cd7e7fe4baf32c8`; `Scripts/model-resource-migration.json` records 107 payload-bearing sources and resources, plus the two metadata-only files in the 109-file generated-source baseline. The mapping covers 300,274,800 bytes and requires byte-for-byte equality.

## Measurements

The before and after measurements use fresh Release scratch builds and separate first-use processes on the same development host. Build time and maximum resident size come from `/usr/bin/time -l`; archive, executable, and resource sizes are byte counts from the resulting files. First-use latency is wall time inside each process and includes the table's initial validation and mapping. These local measurements compare revisions and are not hosted performance gates.

The final measured results are recorded in `Scripts/model-resource-measurements.json` after the implementation source is frozen.
