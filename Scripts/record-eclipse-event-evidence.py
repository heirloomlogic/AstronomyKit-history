#!/usr/bin/env python3
"""Record and verify native lunar-eclipse observations and source bindings."""

import argparse
import ast
import datetime
import functools
import importlib.util
import json
import math
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "Scripts/eclipse-data"
CAPTURES = DATA / "native-captures.json"
OUTPUT = DATA / "native-evidence.json"
DEPENDENCY_SPEC = importlib.util.spec_from_file_location("eclipse_dependencies", ROOT / "Scripts/evidence_dependencies.py")
dependencies = importlib.util.module_from_spec(DEPENDENCY_SPEC)
DEPENDENCY_SPEC.loader.exec_module(dependencies)


def source_hashes(capture_bytes=None):
    overrides = None if capture_bytes is None else {str(CAPTURES.relative_to(ROOT)): capture_bytes}
    return dependencies.source_hashes("eclipse-native", overrides=overrides)


def finite(value):
    if isinstance(value, dict):
        return all(finite(item) for item in value.values())
    if isinstance(value, list):
        return all(finite(item) for item in value)
    return not isinstance(value, (int, float)) or math.isfinite(value)


# Debug and Release libm rounding moves a native event time by up to this many days.
TIME_TOLERANCE_DAYS = 2.0e-10


def near(first, second, path=()):
    if isinstance(first, dict):
        return first.keys() == second.keys() and all(near(first[key], second[key], path + (key,)) for key in first)
    if isinstance(first, list):
        return len(first) == len(second) and all(near(a, b, path + (str(index),)) for index, (a, b) in enumerate(zip(first, second)))
    if isinstance(first, float):
        name = path[-1] if path else ""
        # A residual in seconds is a peak time differenced from a source time,
        # so it gets the same allowance as the peak time itself.
        if name.endswith("Seconds"):
            unit_tolerance = TIME_TOLERANCE_DAYS * 86_400
        elif name.endswith("Minutes"):
            unit_tolerance = 1.0e-8
        elif name in {"tt", "ut"} or name.endswith(("TT", "UT")):
            unit_tolerance = TIME_TOLERANCE_DAYS
        else:
            unit_tolerance = 1.0e-10
        return isinstance(second, (int, float)) and abs(first - second) <= max(unit_tolerance, 16 * math.ulp(first))
    return first == second


def references():
    archive = json.loads((ROOT / "Tests/AstronomyKitTests/Fixtures/IndependentReferences/reference-fixtures.json").read_bytes())
    return {row["universalTime"]: row for row in archive["lunarEclipses"]}


def arithmetic(expression, variables):
    node = ast.parse(expression.replace("p.u", "u**"), mode="eval").body

    def value(item):
        if isinstance(item, ast.Constant) and isinstance(item.value, (int, float)):
            return item.value
        if isinstance(item, ast.Name):
            return variables[item.id]
        if isinstance(item, ast.UnaryOp) and isinstance(item.op, ast.USub):
            return -value(item.operand)
        if isinstance(item, ast.BinOp):
            first, second = value(item.left), value(item.right)
            if isinstance(item.op, ast.Add):
                return first + second
            if isinstance(item.op, ast.Sub):
                return first - second
            if isinstance(item.op, ast.Mult):
                return first * second
            if isinstance(item.op, ast.Div):
                return first / second
            if isinstance(item.op, ast.Pow):
                return first**second
        raise ValueError("unrecognized Delta T expression")

    return value(node)


@functools.lru_cache(maxsize=1)
def delta_pieces():
    text = (ROOT / "Sources/AstronomyKit/Engine/Foundation/EngineDeltaT.swift").read_text()
    result = []
    for stop, body in re.findall(r"if y < (-?\d+) \{(.*?)\n            \}", text, re.S):
        result.append((int(stop), re.search(r"let u = ([^\n]+)", body)[1], " ".join(re.search(r"return (.*)", body, re.S)[1].split())))
    if [row[0] for row in result] != [-500, 500, 1600, 1700, 1800, 1860, 1900, 1920, 1941, 1961, 1986, 2005, 2050, 2150]:
        raise ValueError("changed Delta T layout")
    return result


def source_time_tt(text):
    date = datetime.datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    epoch = datetime.datetime(2000, 1, 1, 12)
    ut = (date - epoch).total_seconds() / 86_400
    start, end = datetime.datetime(date.year, 1, 1), datetime.datetime(date.year + 1, 1, 1)
    year = date.year + (date - start).total_seconds() / (end - start).total_seconds()
    for stop, origin, expression in delta_pieces():
        if year < stop:
            u = arithmetic(origin, {"y": year})
            return ut + arithmetic(expression, {"y": year, "u": u}) / 86_400
    raise ValueError("outside recorded Delta T scope")


def validate_published(rows):
    expected = references()
    if len(rows) != len(expected) or {row["sourceTime"] for row in rows} != set(expected):
        raise ValueError("lunar eclipse row selection differs")
    for row in rows:
        source = expected[row["sourceTime"]]
        fields = {
            "sourceTime", "kind", "nativePeakTT", "peakResidualSeconds", "penumbralDurationMinutes",
            "partialDurationMinutes", "totalDurationMinutes", "obscuration",
        }
        if "penumbralSemiDurationMinutes" in source:
            fields.add("penumbralDurationResidualMinutes")
        if set(row) != fields or row["kind"] != source["kind"]:
            raise ValueError("lunar eclipse observation fields or type differ")
        expected_tt = source_time_tt(row["sourceTime"])
        residual = abs(row["nativePeakTT"] - expected_tt) * 86_400
        relation_tolerance = max(1.0e-9, 8 * max(math.ulp(row["nativePeakTT"]), math.ulp(expected_tt)) * 86_400)
        if row["peakResidualSeconds"] < 0 or abs(residual - row["peakResidualSeconds"]) > relation_tolerance:
            raise ValueError("lunar eclipse peak residual relation failed")
        if residual > source["toleranceSeconds"]:
            raise ValueError("lunar eclipse peak criterion failed")
        if abs(row["partialDurationMinutes"] - source["partialSemiDurationMinutes"]) > source["durationToleranceMinutes"]:
            raise ValueError("lunar eclipse partial-duration criterion failed")
        if abs(row["totalDurationMinutes"] - source["totalSemiDurationMinutes"]) > source["durationToleranceMinutes"]:
            raise ValueError("lunar eclipse total-duration criterion failed")
        if "penumbralSemiDurationMinutes" in source:
            residual = abs(row["penumbralDurationMinutes"] - source["penumbralSemiDurationMinutes"])
            if abs(residual - row["penumbralDurationResidualMinutes"]) > 1.0e-10 or residual > source["durationToleranceMinutes"]:
                raise ValueError("lunar eclipse penumbral-duration criterion failed")
        if not 0 <= row["obscuration"] <= 1:
            raise ValueError("invalid lunar eclipse obscuration")


def validate_obscurations(rows):
    archive = json.loads((ROOT / "Tests/AstronomyKitTests/Fixtures/IndependentReferences/reference-fixtures.json").read_bytes())
    expected = {row["universalTimeSearchSeed"]: row for row in archive["lunarEclipseObscurations"]}
    if len(rows) != len(expected) or {row["sourceTimeSearchSeed"] for row in rows} != set(expected):
        raise ValueError("lunar obscuration row selection differs")
    for row in rows:
        if set(row) != {"sourceTimeSearchSeed", "nativePeakTT", "obscuration"} or not 0 <= row["obscuration"] <= 1:
            raise ValueError("invalid lunar obscuration observation")
        source = expected[row["sourceTimeSearchSeed"]]
        expected_tt = source_time_tt(row["sourceTimeSearchSeed"])
        if abs(row["nativePeakTT"] - expected_tt) * 86_400 > source["peakToleranceSeconds"]:
            raise ValueError("lunar obscuration event time differs from the published event")
        inside = source["roundingLowerBound"] <= row["obscuration"] <= source["roundingUpperBound"]
        if row["sourceTimeSearchSeed"].startswith("2026-08-28"):
            if inside:
                raise ValueError("#275 unexpectedly matches the print interval; reassess the known discrepancy")
        elif not inside:
            raise ValueError("lunar obscuration print interval criterion failed")


def build_seconds(receipt):
    match = re.search(r"Build complete! \(([^ ]+) sec\)", receipt)
    if not match:
        raise ValueError("missing build duration")
    return float(match.group(1))


def evidence(captures, hashes):
    if not finite(captures):
        raise ValueError("nonfinite native eclipse observation")
    for configuration in ("debug", "release"):
        validate_published(captures[configuration]["published"])
        validate_obscurations(captures[configuration]["obscurations"])
    if not near(captures["debug"], captures["release"]):
        raise ValueError("Debug and Release lunar eclipse observations differ")
    resources = captures["resources"]
    if set(resources) != {
        "checksum", "coldSeconds", "host", "nextEclipseCount", "nextEclipsesSeconds", "peakAfterColdBytes",
        "peakAfterWorkloadBytes", "peakBeforeBytes", "totalEclipseCount",
    }:
        raise ValueError("resource observation fields differ")
    peaks = [resources[key] for key in ("peakBeforeBytes", "peakAfterColdBytes", "peakAfterWorkloadBytes")]
    if peaks != sorted(peaks) or min(peaks) <= 0 or resources["coldSeconds"] < 0 or resources["nextEclipsesSeconds"] < 0:
        raise ValueError("invalid resource observation")
    if resources["nextEclipseCount"] != 99 or resources["totalEclipseCount"] != 100:
        raise ValueError("resource workload count differs")
    if any(value <= 0 for value in captures["releaseObjectBytes"].values()) or captures["releaseExecutableBytes"] <= 0:
        raise ValueError("invalid binary-size observation")
    release_rows = captures["release"]["published"]
    obscuration_references = {
        row["universalTimeSearchSeed"]: row
        for row in json.loads((ROOT / "Tests/AstronomyKitTests/Fixtures/IndependentReferences/reference-fixtures.json").read_bytes())["lunarEclipseObscurations"]
    }
    obscuration_rows = captures["release"]["obscurations"]
    return {
        "schemaVersion": 1,
        "sourceSHA256": hashes,
        "baselineRevision": captures["baselineRevision"],
        "toolchain": captures["toolchain"],
        "buildSeconds": {name: build_seconds(captures["buildReceipts"][name]) for name in ("debug", "release")},
        "releaseExecutableBytes": captures["releaseExecutableBytes"],
        "releaseObjectBytes": captures["releaseObjectBytes"],
        "resources": resources,
        "published": {
            "rows": len(release_rows),
            "maximumPeakResidualSeconds": max(row["peakResidualSeconds"] for row in release_rows),
            "maximumPenumbralDurationResidualMinutes": max(row.get("penumbralDurationResidualMinutes", 0) for row in release_rows),
            "maximumPartialDurationResidualMinutes": max(abs(row["partialDurationMinutes"] - references()[row["sourceTime"]]["partialSemiDurationMinutes"]) for row in release_rows),
            "maximumTotalDurationResidualMinutes": max(abs(row["totalDurationMinutes"] - references()[row["sourceTime"]]["totalSemiDurationMinutes"]) for row in release_rows),
            "obscurationRows": len(obscuration_rows),
            "obscurationOutcomes": [{"sourceTimeSearchSeed": row["sourceTimeSearchSeed"],
                "roundingLowerBound": obscuration_references[row["sourceTimeSearchSeed"]]["roundingLowerBound"],
                "roundingUpperBound": obscuration_references[row["sourceTimeSearchSeed"]]["roundingUpperBound"],
                "withinPrintInterval": obscuration_references[row["sourceTimeSearchSeed"]]["roundingLowerBound"] <= row["obscuration"] <= obscuration_references[row["sourceTimeSearchSeed"]]["roundingUpperBound"],
                "knownDiscrepancyIssue": 275 if row["sourceTimeSearchSeed"].startswith("2026-08-28") else None}
                for row in obscuration_rows],
            "maximumObscurationResidualFromPrintedFraction": max(abs(row["obscuration"] - obscuration_references[row["sourceTimeSearchSeed"]]["obscuration"]) for row in obscuration_rows),
            "minimumObscurationMarginInsidePrintInterval": min(min(row["obscuration"] - obscuration_references[row["sourceTimeSearchSeed"]]["roundingLowerBound"], obscuration_references[row["sourceTimeSearchSeed"]]["roundingUpperBound"] - row["obscuration"]) for row in obscuration_rows),
        },
        "criteria": "All six archived NASA eclipse types and peaks retain the existing 120-second allowance. Partial and total semidurations retain the existing two-minute allowance. Three Danjon-based NASA Five Millennium Catalog penumbral semidurations use the same two-minute allowance. The original NASA SVS Moon-disc print intervals remain visible: 2021 passes, while 2026 is an explicitly expected failure under #275 after apparent-place integration. Neither interval is a NASA uncertainty bound. Strict analytic geometry tests cover no eclipse, penumbral, partial and total boundaries.",
        "limitations": "NASA lunar magnitude is a diameter fraction, not the native disc-area obscuration result. Both obscuration references come from one NASA SVS publisher and DE421/LOLA model family. The pages do not publish their exact rounding rule, lunar and shadow radii, or full-precision area algorithm, so interval agreement does not establish algorithm replication. The public eclipse facades run on this search since the #96 cutover. Runtime, memory, object and executable sizes are host observations, not portable ceilings.",
    }


def capture(directory):
    directory = Path(directory)
    release_products = ROOT / ".build/out/Products/Release/AstronomyKitTests.xctest/Contents/MacOS/AstronomyKitTests"
    release_objects = ROOT / ".build/out/Intermediates.noindex/AstronomyKit.build/Release/AstronomyKit-t.build/Objects-normal/arm64"
    return {
        "debug": {name: json.loads((directory / f"debug/{name}.json").read_bytes()) for name in ("published", "obscurations")},
        "release": {name: json.loads((directory / f"release/{name}.json").read_bytes()) for name in ("published", "obscurations")},
        "resources": json.loads((directory / "resources/resources.json").read_bytes()),
        "buildReceipts": {name: (directory / f"full-{name}.log").read_text() for name in ("debug", "release")},
        "baselineRevision": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "toolchain": subprocess.check_output(["swift", "--version"], text=True).strip(),
        "releaseExecutableBytes": release_products.stat().st_size,
        "releaseObjectBytes": {
            "EngineEclipseEvents.o": (release_objects / "EngineEclipseEvents.o").stat().st_size,
            "EngineShadowGeometry.o": (release_objects / "EngineShadowGeometry.o").stat().st_size,
        },
    }


def rebind(captures, previous):
    hashes = dependencies.verify_retained_inputs("eclipse-native", previous["sourceSHA256"])
    result = evidence(captures, hashes)
    dependencies.verify_rebound_document(previous, result, "sourceSHA256")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    captures = capture(arguments.capture) if arguments.capture else json.loads(CAPTURES.read_bytes())
    capture_bytes = (json.dumps(captures, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    if arguments.capture or arguments.check:
        result = evidence(captures, source_hashes(capture_bytes if arguments.capture else None))
    else:
        result = rebind(captures, json.loads(OUTPUT.read_bytes()))
    if arguments.check:
        if json.loads(OUTPUT.read_bytes()) != result:
            raise SystemExit("recorded lunar eclipse evidence differs from source-bound captures")
    else:
        if arguments.capture:
            CAPTURES.parent.mkdir(parents=True, exist_ok=True)
            CAPTURES.write_bytes(capture_bytes)
        OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    print("native lunar eclipse evidence verified")


if __name__ == "__main__":
    main()
