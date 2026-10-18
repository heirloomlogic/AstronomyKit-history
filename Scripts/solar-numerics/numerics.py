"""Exact-rational bounds for the native Earth polynomial, not an altitude certificate."""
import argparse
import base64
from fractions import Fraction as Q
import hashlib
import json
import math
from pathlib import Path
import re
import struct
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "Scripts"))
import model_resource
ENGINE = "Sources/AstronomyKit/Engine/"
EARTH = ENGINE + "Planets/Generated/PlanetPolynomialEarth.swift"
EARTH_RESOURCE = "Sources/AstronomyKit/Resources/ModelTables/planet-polynomial-earth.bin"
MODEL_RESOURCE_READER = "Scripts/model_resource.py"
COVERAGE = ENGINE + "Planets/Generated/PlanetPolynomialCoverage.swift"
SELECTED_EARTH_BINDINGS = [
    ENGINE + "Foundation/EngineDirectChebyshevTable.swift",
    ENGINE + "Moon/EngineFrameBias.swift", ENGINE + "Moon/EngineMoonEphemeris.swift",
    ENGINE + "Moon/EngineTDB.swift", ENGINE + "Moon/Generated/TDBTerms.swift",
    ENGINE + "Planets/EnginePlanetDE441.swift", ENGINE + "Planets/EngineSaturnEphemeris.swift",
    ENGINE + "Planets/Generated/DE441/PlanetDE441EarthBarycenterData.swift",
    ENGINE + "Planets/Generated/DE441/PlanetDE441EarthOffsetData.swift",
    ENGINE + "Planets/Generated/Saturn/SaturnSunData.swift",
    "Sources/AstronomyKit/Resources/ModelTables/saturn-sun.bin",
]
BINDINGS = [
    ENGINE + "Foundation/EngineTime.swift", ENGINE + "Foundation/EngineDeltaT.swift",
    ENGINE + "Foundation/EngineCalendar.swift", ENGINE + "Foundation/EngineConstants.swift",
    ENGINE + "Foundation/EngineSearch.swift", ENGINE + "Foundation/EngineTables.swift",
    ENGINE + "Foundation/EngineMappedResource.swift",
    ENGINE + "Foundation/EngineCache.swift", ENGINE + "Foundation/EngineChebyshev.swift",
    ENGINE + "Foundation/EngineVector.swift", ENGINE + "Orientation/EngineCoordinates.swift",
    "Sources/AstronomyKit/AstronomyKit.swift", "Package.swift",
    ENGINE + "Planets/EnginePlanetPolynomial.swift", ENGINE + "Planets/EnginePlanetPositions.swift",
    ENGINE + "Planets/EngineVSOP87B.swift", ENGINE + "Planets/EnginePlanets.swift",
    ENGINE + "Planets/Generated/VSOP87BTerms.swift", EARTH, COVERAGE,
    ENGINE + "Orientation/EngineEarthRotation.swift", ENGINE + "Orientation/EngineNutation.swift",
    ENGINE + "Orientation/Generated/IAU2000ATerms.swift",
    "Sources/AstronomyKit/CivilTime.swift", "Sources/AstronomyKit/UTCOffsetTable.swift",
    "Scripts/solar-numerics/numerics.py", MODEL_RESOURCE_READER, EARTH_RESOURCE, *SELECTED_EARTH_BINDINGS,
]


def source_hashes(root, paths):
    return {path: hashlib.sha256((root / path).read_bytes()).hexdigest() for path in paths}


def check_hashes(root, expected):
    for path, digest in expected.items():
        if hashlib.sha256((root / path).read_bytes()).hexdigest() != digest:
            raise ValueError(f"Source changed without regenerated derivation: {path}")


def sqrt_interval(value, digits=40):
    """Enclose sqrt(value) by rationals; integer squares verify both endpoints."""
    if value < 0:
        raise ValueError("Negative squared length")
    scale = 10**digits
    lower = math.isqrt(value.numerator * scale * scale // value.denominator)
    lo = Q(lower, scale)
    hi = lo if lo * lo == value else Q(lower + 1, scale)
    assert lo * lo <= value <= hi * hi
    return lo, hi


def upward(value):
    result = float(value)
    return math.nextafter(result, math.inf) if Q(result) < value else result


def downward(value):
    result = float(value)
    return math.nextafter(result, -math.inf) if Q(result) > value else result


def chebyshev(coefficients, x):
    """Direct T_k recurrence, independent of production's Clenshaw recurrence."""
    total, previous, current = coefficients[0], Q(1), x
    for coefficient in coefficients[1:]:
        total += coefficient * current
        previous, current = current, 2 * x * current - previous
    return total


def derivative_bound(coefficients, width):
    return sum(k * k * abs(a) for k, a in enumerate(coefficients)) / (width / 2)


def unpack(text):
    match = re.search(r'count:\s*([\d_]+),\s*"""(.*?)"""', text, re.S)
    if not match:
        raise ValueError("Missing generated coefficient block")
    data = base64.b64decode("".join(match[2].split()), validate=True)
    count = int(match[1].replace("_", ""))
    if len(data) != 8 * count:
        raise ValueError("Generated coefficient count differs from payload")
    values = struct.unpack(f"<{count}d", data)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("Nonfinite generated coefficient")
    return values


def table_payload(path, text=None, root=ROOT):
    source = (root / path).read_text() if text is None else text
    if "Engine.TableResource(" in source:
        return model_resource.payload(source, root / "Sources/AstronomyKit/Resources/ModelTables")
    parts = source.split('"""', 2)
    if len(parts) != 3:
        raise ValueError(f"Missing coefficient payload: {path}")
    return base64.b64decode("".join(parts[1].split()), validate=True)


def earth_model(root=ROOT):
    text = (root / EARTH).read_text()
    degree = int(re.search(r"degree:\s*(\d+)", text)[1])
    width = Q(re.search(r"width:\s*([\d.]+)", text)[1])
    excluded = re.search(r"excludedSegments:\s*\[(.*?)\]", text, re.S)[1].strip()
    if excluded:
        raise ValueError("Earth exclusions require a separate domain derivation")
    data = table_payload(EARTH, text, root)
    if len(data) % 8:
        raise ValueError("Generated coefficient count differs from payload")
    count = len(data) // 8
    values = struct.unpack(f"<{count}d", data)
    if len(values) % (3 * (degree + 1)):
        raise ValueError("Partial Earth segment")
    coverage = (root / COVERAGE).read_text()
    start, stop = [Q(float.fromhex(re.search(rf"{name}: Double = ([^\s]+)", coverage)[1]))
                   for name in ("start", "stop")]
    if width <= 0 or stop <= start or len(values) // (3 * (degree + 1)) * width < stop - start:
        raise ValueError("Invalid polynomial coverage")
    return degree, width, start, stop, values


def record(value, direction="upper"):
    return {"rational": str(value), "binary64": upward(value) if direction == "upper" else downward(value),
            "rounding": direction}


def derive(root=ROOT):
    degree, width, start, stop, values = earth_model(root)
    n = degree + 1
    speed, radius_lo, radius_hi, join_max, join_sum = Q(0), None, Q(0), Q(0), Q(0)
    previous_end = None
    segments = len(values) // (3 * n)
    # One-day nodes; each point of each segment is within half a day of a node.
    if width.denominator != 1:
        raise ValueError("The one-day covering grid requires an integer segment width")
    for index in range(segments):
        axes = [[Q(value) for value in values[(3 * index + axis) * n:(3 * index + axis + 1) * n]]
                for axis in range(3)]
        segment_speed = sqrt_interval(sum(derivative_bound(axis, width)**2 for axis in axes))[1]
        speed = max(speed, segment_speed)
        for day in range(int(width) + 1):
            x = 2 * Q(day) / width - 1
            vector = [chebyshev(axis, x) for axis in axes]
            lo, hi = sqrt_interval(sum(value * value for value in vector))
            lo -= segment_speed / 2
            hi += segment_speed / 2
            radius_lo = lo if radius_lo is None else min(radius_lo, lo)
            radius_hi = max(radius_hi, hi)
        begin = [chebyshev(axis, Q(-1)) for axis in axes]
        end = [chebyshev(axis, Q(1)) for axis in axes]
        if previous_end is not None:
            jump = sqrt_interval(sum((a - b)**2 for a, b in zip(begin, previous_end)))[1]
            join_max = max(join_max, jump)
            join_sum += jump
        previous_end = end
    if radius_lo <= 0:
        raise ValueError("Derived radius does not exclude the origin")
    return {"schemaVersion": 1, "kind": "derived-native-polynomial-terms",
            "domain": {"startTT": float(start), "stopTTExclusive": float(stop), "segmentDays": float(width),
                       "segments": segments, "degree": degree, "gridSpacingDays": 1},
            "terms": {"speedAUPerTTDay": record(speed), "radiusMinimumAU": record(radius_lo, "lower"),
                      "radiusMaximumAU": record(radius_hi), "joinMaximumAU": record(join_max),
                      "joinSumAU": record(join_sum)},
            "excluded": ["polynomial rounding", "polynomial fit error", "frame and libm rounding",
                         "time conversion", "light-time termination", "altitude sensitivity"],
            "sourceSHA256": source_hashes(root, BINDINGS)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--bindings-only", action="store_true")
    args = parser.parse_args()
    output = Path(__file__).with_name("derived-earth.json")
    if args.bindings_only:
        check_hashes(ROOT, json.loads(output.read_text())["sourceSHA256"])
        print("Native numerical source bindings verified")
        return
    actual = json.dumps(derive(), indent=2, sort_keys=True) + "\n"
    if args.check:
        if output.read_text() != actual:
            raise SystemExit("Native Earth derivation is stale; inspect the source/data change and regenerate")
        print("Exact native Earth derivation verified")
    else:
        output.write_text(actual)
        print(output)


if __name__ == "__main__":
    main()
