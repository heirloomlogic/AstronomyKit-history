# Downstream qualification

`qualify.py` checks out the pinned direct consumers in an isolated directory, verifies each unchanged `Package.swift`, redirects only SwiftPM dependency resolution to a local bare mirror of the requested AstronomyKit commit, and runs bounded consumer tests. It never edits a consumer source file or a published dependency.

Run the focused qualification from an AstronomyKit checkout with `python3 Scripts/downstream-qualification/qualify.py run --candidate . --workspace /tmp/astronomykit-downstream --output /tmp/astronomykit-downstream/results.json`. Add `--include-full` to attempt AstrologyKit's full Debug suite with an 11-minute bound. A timed-out command is recorded as `incomplete`; it is not reported as a failure or a pass.

The runner terminates captured descendants before their parent on timeout because SwiftPM's testing helper can create another process group. Check the committed evidence shape and the cleanup behavior with `python3 -m unittest Scripts/downstream-qualification/test_qualify.py -v`, and validate the checked-in record with `python3 Scripts/downstream-qualification/qualify.py validate Scripts/downstream-qualification/results.json`.

`results.json` records the 2026-10-18 run against AstronomyKit `68d80a16b150a2c22d972cdf7db0bbe75e0ff3d3`. It is a historical baseline and does not qualify the later `4ee2aa6cea1ffd48b064b62a95c36fb7cb543b50` main revision.
