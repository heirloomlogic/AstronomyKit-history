# Generated model resources

Issue [#245](https://github.com/heirloomlogic/AstronomyKit/issues/245) and the [owner-approved contract amendment](https://github.com/heirloomlogic/AstronomyKit/issues/245#issuecomment-6251331976) authorize bundled runtime-read binary resources for the Moon, Pluto, Saturn, and planet-polynomial coefficient tables. These resources remain generated build inputs: AstronomyKit does not download model data or fall back to another source at runtime.

Each `.bin` file is a sequence of little-endian IEEE 754 binary64 bit patterns in the same order used by its former generated Swift payload. Generated Swift metadata gives the resource name, exact byte count, and SHA-256 digest. `Engine.MappedBytes` opens the file read-only, checks its size, maps it with `MAP_PRIVATE`, verifies its digest before use, and unmaps it when the owning object is released. A missing, truncated, corrupt, or unexpected resource fails closed. The complete DE441 Moon is split into 90 independently verified chunks so a query maps only the chunk it needs.

SwiftPM copies `Sources/AstronomyKit/Resources/ModelTables` into `Bundle.module`. The clean consumer executable is built and run on macOS and Linux in hosted CI so resource packaging is tested outside the repository target. Apple SDK build jobs verify that the resource declaration remains portable to iOS, tvOS, and watchOS.

The six model generators own their resource prefixes and reject missing, extra, empty, or changed files in `--check` mode. `Scripts/verify-model-resource-migration.py --check` compares every migrated resource with the decoded payload at base revision `667bc909b7025f434e822a353cd7e7fe4baf32c8`; `Scripts/model-resource-migration.json` records 107 payload-bearing sources and resources, plus the two metadata-only files in the 109-file generated-source baseline. The mapping covers 300,274,800 bytes and requires byte-for-byte equality.

## Measurements

The before and after measurements use fresh Release scratch builds and separate first-use processes on the same development host. Build time and maximum resident size come from `/usr/bin/time -l`; archive, executable, and resource sizes are byte counts from the resulting files. First-use latency is wall time inside each process and includes the table's initial validation and mapping. These local measurements compare revisions and are not hosted performance gates.

`Scripts/model-resource-measurements.json` records the raw values, commands, revisions, and limitations. The baseline is `667bc909b7025f434e822a353cd7e7fe4baf32c8`; the measured resource runtime is `d8d8360845fb96f94fb5aa275e5dce49c560bf4e`; the later inventory-only binding revision is `f92d49f6fe1b22b1d17a81a8e3c959bed17d67b7`.

| Measurement | Baseline | Mapped-resource candidate | Change |
|---|---:|---:|---:|
| Fresh Release build wall time | 344.17 s | 215.86 s | −37.3% |
| Fresh Release build maximum RSS | 9,202,417,664 B | 5,388,713,984 B | −41.4% |
| Static library | 554,031,304 B | 152,164,232 B | −72.5% |
| Static library plus resource bundle | 554,031,304 B | 452,439,032 B | −18.3% |
| Test executable | 577,452,304 B | 172,492,112 B | −70.1% |
| Test executable plus resource bundle | 577,452,304 B | 472,766,912 B | −18.1% |
| Scoped generated Swift source | 109 files / 401,903,636 B | 19 files / 27,847 B | −99.99% by bytes |
| Bundled resources | 0 | 107 files / 300,274,800 B | new representation |

The mapped tables reduce retained memory after representative workloads: Moon 366,100,480 B to 279,855,104 B, Pluto 151,945,216 B to 85,442,560 B, and Saturn 99,041,280 B to 72,220,672 B. Their workload checksums are unchanged. Initial validation adds latency because the first access hashes the mapped bytes: Moon 0.000277 s to 0.023725 s, Pluto 0.021895 s to 0.082420 s, and Saturn center 0.029213 s to 0.113092 s. The Moon outer-range sweep rose from 0.760 s to 1.913 s because it first touched and verified all 90 chunks; the central sweep remained 0.367 s versus 0.372 s.
