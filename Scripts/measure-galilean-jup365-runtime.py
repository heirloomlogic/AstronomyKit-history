#!/usr/bin/env python3
"""Capture or check compiled jup365 build-size and public-call measurements."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import statistics
import subprocess
import tempfile
import time


ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "Scripts/jupiter-moon-data/jup365/runtime-performance.json"
PROBE = ROOT / "Scripts/jupiter-moon-data/jup365-runtime-probe.swift"
GENERATED = ROOT / "Sources/AstronomyKit/Engine/Bodies/Generated/Jup365"
BOUND_PATHS = [
    Path("Package.swift"),
    Path("Scripts/generate-galilean-jup365-swift.py"),
    Path("Scripts/jupiter-moon-data/jup365-runtime-probe.swift"),
    Path("Scripts/jupiter-moon-data/jup365/representation.json"),
    Path("Scripts/measure-galilean-jup365-runtime.py"),
    Path("Scripts/test_measure_galilean_jup365_runtime.py"),
    Path("Sources/AstronomyKit/Engine/Bodies/EngineJupiterMoons.swift"),
    Path("Sources/AstronomyKit/Engine/Bodies/EngineJupiterMoonsJup365.swift"),
]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def encoded(value):
    return json.dumps(value, indent=2, sort_keys=True, allow_nan=False).encode() + b"\n"


def source_hashes():
    paths = BOUND_PATHS + sorted(path.relative_to(ROOT) for path in GENERATED.glob("*.swift"))
    return {str(path): digest((ROOT / path).read_bytes()) for path in paths}


def parse_time_log(log):
    patterns = {
        "maximumResidentSetBytes": r"^\s*(\d+)\s+maximum resident set size$",
        "peakMemoryFootprintBytes": r"^\s*(\d+)\s+peak memory footprint$",
    }
    wall = re.search(r"^\s*(?:real\s+([0-9.]+)|([0-9.]+)\s+real)(?:\s+.*)?$", log, re.MULTILINE)
    if not wall:
        raise ValueError("timed build did not report wallSeconds")
    values = {"wallSeconds": float(wall.group(1) or wall.group(2))}
    for key, pattern in patterns.items():
        match = re.search(pattern, log, re.MULTILINE)
        if not match:
            raise ValueError(f"timed build did not report {key}")
        values[key] = int(match.group(1))
    match = re.search(r"Build complete! \(([0-9.]+) sec\)", log)
    if not match:
        raise ValueError("SwiftPM did not report a build duration")
    values["swiftPMSeconds"] = float(match.group(1))
    return values


def exactly_one(root, name):
    matches = list(root.rglob(name))
    if len(matches) != 1:
        raise ValueError(f"expected one {name}, found {len(matches)}")
    return matches[0]


def compile_probe(build_root, destination):
    library = exactly_one(build_root, "libAstronomyKit.a")
    module = library.parent / "AstronomyKit.swiftmodule"
    object_file = library.parent / "AstronomyKit.o"
    if not module.is_dir() or not object_file.is_file():
        raise ValueError("SwiftPM product directory is incomplete")
    subprocess.run(
        ["swiftc", "-O", str(PROBE), "-I", str(module.parent), "-L", str(library.parent), "-lAstronomyKit", "-o", str(destination)],
        cwd=ROOT,
        check=True,
    )
    return library, object_file


def run_json(command):
    return json.loads(subprocess.run(command, cwd=ROOT, check=True, capture_output=True, text=True).stdout)


def validate(report):
    required = {"schemaVersion", "host", "sourceSHA256", "build", "sizes", "publicAPI"}
    if set(report) != required or report["schemaVersion"] != 1:
        raise ValueError("runtime measurement schema differs")
    if report["sourceSHA256"] != source_hashes():
        raise ValueError("runtime measurement source bindings differ")
    for key in ("wallSeconds", "swiftPMSeconds", "maximumResidentSetBytes", "peakMemoryFootprintBytes"):
        if not isinstance(report["build"].get(key), (int, float)) or report["build"][key] <= 0:
            raise ValueError(f"invalid build measurement {key}")
    if set(report["sizes"]) != {"generatedSwiftBytes", "astronomyKitSourcesBytes", "staticLibraryBytes", "astronomyKitObjectBytes", "probeExecutableBytes"}:
        raise ValueError("runtime size inventory differs")
    if any(type(value) is not int or value <= 0 for value in report["sizes"].values()):
        raise ValueError("invalid runtime size measurement")
    api = report["publicAPI"]
    if api.get("iterations") != 100_000 or len(api.get("processLaunchAndFirstCallMilliseconds", [])) != 7:
        raise ValueError("runtime call measurement inventory differs")
    for key in ("firstPublicCallMilliseconds", "sameEpochMicrosecondsPerCall", "spanningMicrosecondsPerCall"):
        if not isinstance(api.get(key), (int, float)) or api[key] <= 0:
            raise ValueError(f"invalid public API measurement {key}")
    if any(not isinstance(value, (int, float)) or value <= 0 for value in api["processLaunchAndFirstCallMilliseconds"]):
        raise ValueError("invalid launch measurement")


def capture(scratch):
    shutil.rmtree(scratch, ignore_errors=True)
    command = ["/usr/bin/time", "-lp", "swift", "build", "-c", "release", "-j", "2", "--scratch-path", str(scratch)]
    process = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
    build_log = process.stdout + process.stderr
    if process.returncode:
        raise subprocess.CalledProcessError(process.returncode, command, output=build_log)
    probe = scratch / "jup365-runtime-probe"
    library, object_file = compile_probe(scratch, probe)
    api = run_json([str(probe), "100000"])
    launches = []
    for _ in range(7):
        started = time.perf_counter_ns()
        run_json([str(probe), "--first-only"])
        launches.append((time.perf_counter_ns() - started) / 1_000_000)
    api["processLaunchAndFirstCallMilliseconds"] = launches
    api["processLaunchAndFirstCallMedianMilliseconds"] = statistics.median(launches)
    report = {
        "schemaVersion": 1,
        "host": {"machine": platform.machine(), "platform": platform.platform(), "swift": subprocess.run(["swift", "--version"], check=True, capture_output=True, text=True).stdout.strip()},
        "sourceSHA256": source_hashes(),
        "build": {"command": " ".join(command), **parse_time_log(build_log)},
        "sizes": {
            "generatedSwiftBytes": sum(path.stat().st_size for path in GENERATED.glob("*.swift")),
            "astronomyKitSourcesBytes": sum(path.stat().st_size for path in (ROOT / "Sources/AstronomyKit").rglob("*.*")),
            "staticLibraryBytes": library.stat().st_size,
            "astronomyKitObjectBytes": object_file.stat().st_size,
            "probeExecutableBytes": probe.stat().st_size,
        },
        "publicAPI": api,
    }
    validate(report)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{REPORT.name}.", dir=REPORT.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded(report))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, REPORT)
    finally:
        temporary.unlink(missing_ok=True)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--capture", action="store_true")
    group.add_argument("--check", action="store_true")
    parser.add_argument("--scratch", type=Path, default=ROOT / ".context/issue-254/runtime-release")
    args = parser.parse_args()
    if args.capture:
        report = capture(args.scratch)
        print(f"Recorded runtime measurement: {report['publicAPI']['spanningMicrosecondsPerCall']:.3f} microseconds per spanning call")
    else:
        validate(json.loads(REPORT.read_bytes()))
        print("Checked compiled jup365 runtime measurement")


if __name__ == "__main__":
    main()
