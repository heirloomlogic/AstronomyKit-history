#!/usr/bin/env python3
"""Capture and replay the current native Pluto DE441 evidence."""
import argparse
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
DEPENDENCY_SPEC = importlib.util.spec_from_file_location("pluto_native_dependencies", ROOT / "Scripts/evidence_dependencies.py")
dependencies = importlib.util.module_from_spec(DEPENDENCY_SPEC)
DEPENDENCY_SPEC.loader.exec_module(dependencies)
RESOURCE_SPEC = importlib.util.spec_from_file_location("model_resource", ROOT / "Scripts/model_resource.py")
model_resource = importlib.util.module_from_spec(RESOURCE_SPEC)
RESOURCE_SPEC.loader.exec_module(model_resource)
OUTPUT = ROOT / "Scripts/pluto-data/de441-native-evidence.json"
REPLAY_OWNERS = {"Scripts/record-pluto-de441-evidence.py", "Scripts/test_record_pluto_de441_evidence.py"}
PRESERVED_KEYS = {
    "apparentIntegrationCaptureRevision",
    "baselineCommit",
    "baselineModification",
    "baselineRelease",
    "baselineStorage",
    "centerExtensionBase",
    "fullPrecisionFoundationCaptureRevision",
    "fullPrecisionIntegrationCaptureRevision",
    "limits",
    "measurementWorkloadsTTDays",
    "rangeExtensionBase",
}
TABLES = {
    "generatedTables": {
        "PlutoDE441PlutoData": "Sources/AstronomyKit/Engine/Gravity/Generated/DE441/PlutoDE441PlutoData.swift",
        "PlutoDE441SunData": "Sources/AstronomyKit/Engine/Gravity/Generated/DE441/PlutoDE441SunData.swift",
    },
    "centerGeneratedTables": {
        "PlutoBarycenterCoefficients": "Sources/AstronomyKit/Engine/Gravity/Generated/PlutoBarycenterCoefficients.swift",
        "PlutoCenterCoefficients": "Sources/AstronomyKit/Engine/Gravity/Generated/PlutoCenterCoefficients.swift",
        "PlutoSunCoefficients": "Sources/AstronomyKit/Engine/Gravity/Generated/PlutoSunCoefficients.swift",
    },
}


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def source_paths(root=ROOT):
    return list(dependencies.paths("pluto-native", root=root))


def source_hashes(root=ROOT):
    return dependencies.source_hashes("pluto-native", root=root)


def finite(value):
    if isinstance(value, dict):
        return all(finite(item) for item in value.values())
    if isinstance(value, list):
        return all(finite(item) for item in value)
    return not isinstance(value, float) or math.isfinite(value)


def validate_keys(value, keys, name):
    if set(value) != set(keys) or not finite(value):
        raise ValueError(f"{name} capture schema or finiteness differs")


def validate_capture_pair(debug_boundary, release_boundary, debug_direct, release_direct, debug_references, release_references):
    boundary_keys = {"count", "maximumPositionKm", "maximumRateKmPerTDBDay"}
    direct_keys = {"bodySamples", "integratedSamples", "maximumBodyPositionKm", "maximumBodyRateKmPerTDBDay", "maximumIntegratedAngleArcminutes", "maximumIntegratedPositionKm", "maximumIntegratedRateKmPerTTDay"}
    for name, value, keys in [("Debug boundary", debug_boundary, boundary_keys), ("Release boundary", release_boundary, boundary_keys), ("Debug direct-source", debug_direct, direct_keys), ("Release direct-source", release_direct, direct_keys)]:
        validate_keys(value, keys, name)
    for name, value in [("Debug references", debug_references), ("Release references", release_references)]:
        validate_keys(value, {"rows"}, name)
        if not value["rows"]:
            raise ValueError(f"{name} is empty")
    if debug_boundary["count"] <= 0 or debug_direct["bodySamples"] <= 0 or debug_direct["integratedSamples"] <= 0:
        raise ValueError("Pluto capture counts must be positive")
    if debug_boundary != release_boundary or debug_direct != release_direct or debug_references != release_references:
        raise ValueError("Debug and Release Pluto captures differ")


def validate_measurement(value, cold):
    validate_keys(value, {"checksum", "coldSeconds", "coldTT", "evaluationsPerWorkload", "host", "peakBytesAfterCold", "peakBytesAfterLoops", "peakBytesBefore", "seconds"}, "Release measurement")
    validate_keys(value["seconds"], {"central", "engineRange", "outer"}, "Release measurement timings")
    if value["coldTT"] != cold or value["evaluationsPerWorkload"] != 2000 or not value["host"]:
        raise ValueError("Release measurement workload differs")
    if value["coldSeconds"] < 0 or any(value[key] <= 0 for key in ("peakBytesAfterCold", "peakBytesAfterLoops", "peakBytesBefore")) or any(seconds < 0 for seconds in value["seconds"].values()):
        raise ValueError("Release measurement contains invalid resource values")


def reference_summary(rows):
    groups = {"centralCenter": [], "outerBarycenter": [], "outerOrBlendedCenter": []}
    for row in rows:
        validate_keys(row, {"angularDifferenceArcminutes", "body", "centerWeight", "julianDateTDB", "positionDifferenceKm", "velocityDifferenceKmPerSecond"}, "Archived reference")
        if row["body"] == "pluto-barycenter":
            groups["outerBarycenter"].append(row)
        elif row["body"] == "pluto" and row["centerWeight"] == 1:
            groups["centralCenter"].append(row)
        elif row["body"] == "pluto" and 0 <= row["centerWeight"] < 1:
            groups["outerOrBlendedCenter"].append(row)
        else:
            raise ValueError("Archived reference center semantics differ")
    result = {}
    for name, selected in groups.items():
        result[name] = {"count": len(selected)}
        for key in ("angularDifferenceArcminutes", "positionDifferenceKm", "velocityDifferenceKmPerSecond"):
            result[name][key] = max((row[key] for row in selected), default=None)
    return result


def cstring_bytes(output):
    match = re.search(r"Section \(__TEXT, __cstring\): (\d+)", output)
    if not match:
        raise ValueError("Release object lacks a reported __cstring section")
    return int(match.group(1))


def release_object(stem, root=ROOT):
    candidates = [path for path in (root / ".build").rglob(f"{stem}.o") if "Release" in path.parts or "release" in path.parts]
    if len(candidates) != 1:
        raise ValueError(f"Expected one Release object for {stem}, found {candidates}")
    return candidates[0]


def release_executable(root=ROOT):
    candidates = []
    for path in (root / ".build").rglob("*"):
        if path.is_file() and "Release" in path.parts and ".xctest" in str(path) and "dSYM" not in str(path) and os.access(path, os.X_OK):
            candidates.append(path)
    if len(candidates) != 1:
        raise ValueError(f"Expected one Release test executable, found {candidates}")
    return candidates[0]


def storage(root=ROOT):
    result = {}
    resource_bytes = {}
    resource_directory = root / "Sources/AstronomyKit/Resources/ModelTables"
    for section, tables in TABLES.items():
        result[section] = {}
        resource_bytes[section] = 0
        for name, relative in tables.items():
            source = root / relative
            object_path = release_object(name, root)
            size_output = subprocess.check_output(["/usr/bin/size", "-m", str(object_path)], text=True)
            mapped = model_resource.payload(source.read_text(), resource_directory)
            result[section][name] = {"cstringSectionBytes": cstring_bytes(size_output), "generatedSourceBytes": source.stat().st_size, "mappedResourceBytes": len(mapped), "releaseObjectBytes": object_path.stat().st_size}
            resource_bytes[section] += len(mapped)
    result["resourcePayloadBytes"] = resource_bytes["generatedTables"]
    result["centerResourcePayloadBytes"] = resource_bytes["centerGeneratedTables"]
    result["testExecutableBytes"] = release_executable(root).stat().st_size
    return result


def check_sources(recorded, current):
    # The replay owners are this script and its tests; editing them changes the replay, not the capture.
    if set(recorded) != set(current) or any(recorded[path] != current[path] for path in current if path not in REPLAY_OWNERS):
        raise ValueError("Pluto evidence source inventory or digest differs")


def validate_evidence(value):
    expected = PRESERVED_KEYS | {"archivedReferenceSummary", "archivedReferences", "centerNativeRelease", "directSourceDebug", "directSourceRelease", "everyBoundaryDebug", "everyBoundaryRelease", "nativeRelease", "nativeStorage", "schemaVersion", "sourceSHA256", "swiftVersion"}
    validate_keys(value, expected, "Pluto evidence")
    if value["schemaVersion"] != 4 or not value["swiftVersion"]:
        raise ValueError("Pluto evidence schema or toolchain differs")
    check_sources(value["sourceSHA256"], source_hashes())
    validate_capture_pair(value["everyBoundaryDebug"], value["everyBoundaryRelease"], value["directSourceDebug"], value["directSourceRelease"], {"rows": value["archivedReferences"]}, {"rows": value["archivedReferences"]})
    if value["archivedReferenceSummary"] != reference_summary(value["archivedReferences"]):
        raise ValueError("Archived Pluto reference summary differs")
    validate_measurement(value["nativeRelease"], -766524.75)
    validate_measurement(value["centerNativeRelease"], -72000.0)
    if value["nativeStorage"]["resourcePayloadBytes"] != 13149264 or value["nativeStorage"]["centerResourcePayloadBytes"] != 21768120 or value["nativeStorage"]["testExecutableBytes"] <= 0:
        raise ValueError("Pluto storage evidence differs")
    for section in ("generatedTables", "centerGeneratedTables"):
        rows = value["nativeStorage"].get(section, {})
        fields = {"cstringSectionBytes", "generatedSourceBytes", "mappedResourceBytes", "releaseObjectBytes"}
        if set(rows) != set(TABLES[section]) or any(set(row) != fields or any(metric <= 0 for metric in row.values()) for row in rows.values()):
            raise ValueError("Pluto table storage evidence differs")


def publish(path, value):
    payload = encoded(value)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".pluto-evidence-", delete=False) as staged:
        temporary = Path(staged.name)
        staged.write(payload)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def run_capture(configuration, directory):
    boundary = directory / f"boundary-{configuration}.json"
    direct = directory / f"direct-{configuration}.json"
    references = directory / f"references-{configuration}.json"
    environment = dict(os.environ, PLUTO_BOUNDARY_OUTPUT=str(boundary), PLUTO_DIFFERENTIAL_OUTPUT=str(direct), PLUTO_REFERENCE_OUTPUT=str(references))
    command = ["swift", "test", "--no-parallel"]
    if configuration == "release":
        command += ["-c", "release"]
    command += ["--filter", "EnginePlutoDE441Tests"]
    subprocess.run(command, cwd=ROOT, env=environment, check=True)
    return json.loads(boundary.read_bytes()), json.loads(direct.read_bytes()), json.loads(references.read_bytes())


def run_measurement(directory, center):
    output = directory / ("measurement-center.json" if center else "measurement-outer.json")
    environment = dict(os.environ, PLUTO_MEASUREMENT_OUTPUT=str(output))
    if center:
        environment["PLUTO_MEASUREMENT_CENTER"] = "1"
    subprocess.run(["swift", "test", "--no-parallel", "-c", "release", "--skip-build", "--filter", "EnginePlutoMeasurementTests"], cwd=ROOT, env=environment, check=True)
    return json.loads(output.read_bytes())


def capture():
    before = source_hashes()
    prior = json.loads(OUTPUT.read_bytes())
    with tempfile.TemporaryDirectory(prefix="pluto-native-evidence-") as directory_name:
        directory = Path(directory_name)
        debug_boundary, debug_direct, debug_references = run_capture("debug", directory)
        release_boundary, release_direct, release_references = run_capture("release", directory)
        outer = run_measurement(directory, False)
        center = run_measurement(directory, True)
    after = source_hashes()
    if after != before:
        raise ValueError("Pluto evidence sources changed during capture")
    validate_capture_pair(debug_boundary, release_boundary, debug_direct, release_direct, debug_references, release_references)
    validate_measurement(outer, -766524.75)
    validate_measurement(center, -72000.0)
    rows = release_references["rows"]
    result = {key: prior[key] for key in PRESERVED_KEYS}
    result.update(schemaVersion=4, sourceSHA256=after, swiftVersion=subprocess.check_output(["swift", "--version"], cwd=ROOT, text=True), everyBoundaryDebug=debug_boundary, everyBoundaryRelease=release_boundary, directSourceDebug=debug_direct, directSourceRelease=release_direct, archivedReferences=rows, archivedReferenceSummary=reference_summary(rows), nativeRelease=outer, centerNativeRelease=center, nativeStorage=storage())
    validate_evidence(result)
    publish(OUTPUT, result)
    print("Recorded Pluto-native evidence")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--capture", action="store_true")
    choice.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    if arguments.capture:
        capture()
    else:
        validate_evidence(json.loads(OUTPUT.read_bytes()))
        print("Pluto-native captures, measurements, storage, and source bindings verified")


if __name__ == "__main__":
    main()
