#!/usr/bin/env python3
"""Replay disclosed 2026 SVS lunar-eclipse conventions from DE421."""

import argparse
import csv
import hashlib
import html
import json
import math
import re
import struct
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCES = HERE / "sources"
RECEIPTS = HERE / "de421-source-receipts.json"
RESULTS = HERE / "de421-convention-matrix.json"
BASELINE_RESULTS = HERE / "results.json"
J2000 = 2_451_545.0
SECONDS_PER_DAY = 86_400.0
EARTH_RADIUS_KILOMETERS = 6_378.1366
MOON_RADIUS_KILOMETERS = 1_737.4
SUN_RADIUS_KILOMETERS = 695_700.0
TARGET_JD = 2_461_280.676_452_763
PRINT_INTERVAL = (0.9625, 0.9635)


class EvidenceError(ValueError):
    """A source, declared convention, or replay invariant changed."""


def load_json(path):
    return json.loads(path.read_text())


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_path(relative, label):
    candidate = Path(relative)
    if candidate.is_absolute():
        raise EvidenceError(f"{label} path must be repository-relative")
    resolved = (ROOT / candidate).resolve()
    try:
        resolved.relative_to(SOURCES.resolve())
    except ValueError as error:
        raise EvidenceError(f"{label} path is outside the issue source archive") from error
    return resolved


def verify_file(relative, expected, label):
    path = source_path(relative, label)
    if not path.is_file():
        raise EvidenceError(f"{label} is missing")
    actual = sha256(path)
    if actual != expected:
        raise EvidenceError(f"{label} SHA-256 changed: expected {expected}, found {actual}")
    return path


def verify_receipts(receipts):
    if receipts.get("schemaVersion") != 1:
        raise EvidenceError("unsupported DE421 receipt schema")
    for label, source in receipts.get("documents", {}).items():
        text = verify_file(source["path"], source["sha256"], label).read_text(errors="replace")
        for required in source.get("requiredText", []):
            if required not in text:
                raise EvidenceError(f"{label} no longer contains required source text: {required}")
    for label, source in receipts.get("horizons", {}).items():
        response = verify_file(source["path"], source["sha256"], label)
        query = verify_file(source["queryPath"], source["querySHA256"], f"{label} query")
        query_data = load_json(query)
        if query_data.get("responseSHA256") != source["sha256"]:
            raise EvidenceError(f"{label} query does not bind its response")
        if load_json(response).get("signature", {}).get("source") != "NASA/JPL Horizons API":
            raise EvidenceError(f"{label} response signature changed")
    manifest_source = receipts.get("de421Kernel", {})
    manifest_path = verify_file(manifest_source["manifestPath"], manifest_source["manifestSHA256"], "DE421 range manifest")
    manifest = load_json(manifest_path)
    if manifest.get("schemaVersion") != 1 or manifest.get("source") != {
        "bytes": manifest_source["bytes"],
        "sha256": manifest_source["sha256"],
        "url": manifest_source["url"],
    }:
        raise EvidenceError("DE421 range manifest source identity changed")
    if not manifest.get("ranges"):
        raise EvidenceError("DE421 range manifest is empty")
    identities = set()
    for row in manifest["ranges"]:
        identity = (row.get("start"), row.get("end"))
        if identity in identities:
            raise EvidenceError("DE421 range manifest has duplicate intervals")
        identities.add(identity)
        if not all(isinstance(value, int) for value in identity) or identity[0] < 0 or identity[1] < identity[0]:
            raise EvidenceError("DE421 range manifest has an invalid interval")
        path = verify_file(row["path"], row["sha256"], f"DE421 range {identity[0]}-{identity[1]}")
        if path.stat().st_size != identity[1] - identity[0] + 1:
            raise EvidenceError("DE421 range length changed")
    return manifest


class StoredRangeReader:
    def __init__(self, manifest):
        self.ranges = {}
        self.used = set()
        for row in manifest["ranges"]:
            start = row["start"]
            count = row["end"] - start + 1
            self.ranges[(start, count)] = source_path(row["path"], "DE421 range").read_bytes()

    def read(self, start, count):
        key = (start, count)
        if key not in self.ranges:
            raise EvidenceError(f"DE421 archive lacks required byte range {start}-{start + count - 1}")
        self.used.add(key)
        return self.ranges[key]

    def assert_inventory_used(self):
        unused = set(self.ranges) - self.used
        if unused:
            raise EvidenceError(f"DE421 archive has unused ranges: {sorted(unused)}")


def parse_summary_record(data):
    if len(data) != 1_024:
        raise EvidenceError("SPK summary record must contain 1024 bytes")
    following, _, count = struct.unpack_from("<3d", data)
    if count != int(count) or not 0 <= count <= 25:
        raise EvidenceError("SPK summary count is invalid")
    rows = []
    for index in range(int(count)):
        offset = 24 + index * 40
        start, end, target, center, frame, kind, first, last = struct.unpack_from("<2d6i", data, offset)
        rows.append((start, end, target, center, frame, kind, first, last))
    return int(following), rows


def read_segments(reader):
    header = reader.read(0, 1_024)
    if header[:8] != b"DAF/SPK " or header[88:96] != b"LTL-IEEE" or struct.unpack_from("<2i", header, 8) != (2, 6):
        raise EvidenceError("DE421 source is not the expected little-endian SPK")
    record = struct.unpack_from("<i", header, 76)[0]
    seen = set()
    segments = []
    while record:
        if record in seen:
            raise EvidenceError("SPK summary list is cyclic")
        seen.add(record)
        record, batch = parse_summary_record(reader.read((record - 1) * 1_024, 1_024))
        segments.extend(batch)
    return segments


def segment_for(segments, center, target, jd):
    seconds = (jd - J2000) * SECONDS_PER_DAY
    matches = [row for row in segments if row[3] == center and row[2] == target and row[0] <= seconds < row[1]]
    if len(matches) != 1:
        raise EvidenceError(f"expected one DE421 segment for {center}->{target}, found {len(matches)}")
    return matches[0]


def read_record(reader, segment, jd):
    _, _, _, _, frame, kind, first, last = segment
    if (frame, kind) != (1, 2):
        raise EvidenceError("DE421 segment is not type-2 ICRF")
    start_seconds, record_seconds, words, count = struct.unpack("<4d", reader.read((last - 4) * 8, 32))
    if words != int(words) or count != int(count):
        raise EvidenceError("DE421 record shape is nonintegral")
    index = math.floor(((jd - J2000) * SECONDS_PER_DAY - start_seconds) / record_seconds)
    if not 0 <= index < int(count):
        raise EvidenceError("DE421 epoch is outside its segment")
    values = struct.unpack(f"<{int(words)}d", reader.read((first - 1 + index * int(words)) * 8, int(words) * 8))
    x = ((jd - J2000) * SECONDS_PER_DAY - values[0]) / values[1]
    if not -1 <= x <= 1 or not all(math.isfinite(value) for value in values):
        raise EvidenceError("DE421 record has an invalid interpolation domain")
    return values, x


def chebyshev(coefficients, x, record_days):
    values = [1.0, x]
    derivatives = [0.0, 1.0]
    for _ in range(2, len(coefficients)):
        values.append(2 * x * values[-1] - values[-2])
        derivatives.append(2 * values[-2] + 2 * x * derivatives[-1] - derivatives[-2])
    value = math.fsum(coefficient * values[index] for index, coefficient in enumerate(coefficients))
    slope = math.fsum(coefficient * derivatives[index] for index, coefficient in enumerate(coefficients))
    return value, slope * 2 / record_days


def state(reader, segments, center, target, jd):
    record, x = read_record(reader, segment_for(segments, center, target, jd), jd)
    count = (len(record) - 2) // 3
    if count * 3 + 2 != len(record):
        raise EvidenceError("DE421 coefficient inventory is invalid")
    position = []
    velocity = []
    record_days = record[1] * 2 / SECONDS_PER_DAY
    for axis in range(3):
        value, rate = chebyshev(record[2 + axis * count : 2 + (axis + 1) * count], x, record_days)
        position.append(value)
        velocity.append(rate / SECONDS_PER_DAY)
    return tuple(position), tuple(velocity)


def add(left, right):
    return tuple(a + b for a, b in zip(left, right))


def subtract(left, right):
    return tuple(a - b for a, b in zip(left, right))


def scale(vector, factor):
    return tuple(value * factor for value in vector)


def norm(vector):
    return math.sqrt(math.fsum(value * value for value in vector))


def dot(left, right):
    return math.fsum(a * b for a, b in zip(left, right))


def unit(vector):
    length = norm(vector)
    if not math.isfinite(length) or length == 0:
        raise EvidenceError("direction vector is degenerate")
    return scale(vector, 1 / length)


def de421_geocentric(reader, segments, jd):
    earth_barycenter, _ = state(reader, segments, 0, 3, jd)
    earth_offset, _ = state(reader, segments, 3, 399, jd)
    moon_offset, _ = state(reader, segments, 3, 301, jd)
    sun_barycenter, _ = state(reader, segments, 0, 10, jd)
    earth = add(earth_barycenter, earth_offset)
    return subtract(moon_offset, earth_offset), subtract(sun_barycenter, earth)


def circle_overlap_fraction(first_radius, second_radius, separation):
    if separation >= first_radius + second_radius:
        return 0.0
    if separation <= abs(first_radius - second_radius):
        return min(1.0, (second_radius / first_radius) ** 2)
    first_angle = math.acos((separation * separation + first_radius * first_radius - second_radius * second_radius) / (2 * separation * first_radius))
    second_angle = math.acos((separation * separation + second_radius * second_radius - first_radius * first_radius) / (2 * separation * second_radius))
    product = (-separation + first_radius + second_radius) * (separation + first_radius - second_radius) * (separation - first_radius + second_radius) * (separation + first_radius + second_radius)
    area = first_radius * first_radius * first_angle + second_radius * second_radius * second_angle - 0.5 * math.sqrt(product)
    return area / (math.pi * first_radius * first_radius)


def overlap(vector_moon, vector_sun, shadow):
    moon_distance = norm(vector_moon)
    sun_distance = norm(vector_sun)
    cosine = max(-1.0, min(1.0, dot(unit(vector_moon), scale(unit(vector_sun), -1))))
    separation_angle = math.acos(cosine)
    moon_parallax = math.asin(EARTH_RADIUS_KILOMETERS / moon_distance)
    sun_semidiameter = math.asin(SUN_RADIUS_KILOMETERS / sun_distance)
    sun_parallax = math.asin(EARTH_RADIUS_KILOMETERS / sun_distance)
    if shadow == "geometric":
        umbra_angle = moon_parallax - sun_semidiameter + sun_parallax
    elif shadow == "fiveMillenniumDanjon":
        umbra_angle = 1.01 * moon_parallax - sun_semidiameter + sun_parallax
    elif shadow == "danjonExpandedTerms":
        umbra_angle = (1 + 1 / 85 - 1 / 594) * moon_parallax - sun_semidiameter + sun_parallax
    elif shadow == "chauvenet":
        umbra_angle = 1.02 * (0.998340 * moon_parallax - sun_semidiameter + sun_parallax)
    else:
        raise EvidenceError(f"unknown shadow convention: {shadow}")
    moon_radius = moon_distance * math.tan(math.asin(MOON_RADIUS_KILOMETERS / moon_distance))
    umbra_radius = moon_distance * math.tan(umbra_angle)
    axis_distance = moon_distance * math.tan(separation_angle)
    result = {
        "axisDistanceKilometers": axis_distance,
        "moonDistanceKilometers": moon_distance,
        "moonRadiusKilometers": moon_radius,
        "obscuration": circle_overlap_fraction(moon_radius, umbra_radius, axis_distance),
        "separationArcseconds": math.degrees(separation_angle) * 3_600,
        "sunDistanceKilometers": sun_distance,
        "umbraRadiusKilometers": umbra_radius,
    }
    if not all(math.isfinite(value) for value in result.values()):
        raise EvidenceError("convention row contains a nonfinite result")
    return result


def horizons_vector(receipts, label):
    source = receipts["horizons"][label]
    query = load_json(source_path(source["queryPath"], f"{label} query"))
    expected = {
        "CENTER": "'500@399'",
        "CSV_FORMAT": "'YES'",
        "EPHEM_TYPE": "'VECTORS'",
        "MAKE_EPHEM": "'YES'",
        "OBJ_DATA": "'NO'",
        "OUT_UNITS": "'KM-S'",
        "REF_PLANE": "'FRAME'",
        "REF_SYSTEM": "'ICRF'",
        "TIME_TYPE": "'TDB'",
        "TLIST": f"'{TARGET_JD}'",
        "VEC_CORR": "'NONE'",
        "VEC_TABLE": "'2'",
    }
    if {key: query.get("parameters", {}).get(key) for key in expected} != expected:
        raise EvidenceError(f"{label} Horizons query convention changed")
    if query.get("parameters", {}).get("COMMAND") != source.get("command"):
        raise EvidenceError(f"{label} Horizons target changed")
    response = load_json(source_path(source["path"], label))["result"]
    if "{source: DE441}" not in response or "Reference frame : ICRF" not in response or "Output units    : KM-S" not in response:
        raise EvidenceError(f"{label} Horizons response convention changed")
    rows = list(csv.reader(response.split("$$SOE", 1)[1].split("$$EOE", 1)[0].splitlines()))
    matches = [row for row in rows if row and row[0].strip() == str(TARGET_JD)]
    if len(matches) != 1 or len(matches[0]) < 8:
        raise EvidenceError(f"{label} Horizons response lacks its canonical row")
    vector = tuple(float(value) for value in matches[0][2:5])
    if not all(math.isfinite(value) for value in vector):
        raise EvidenceError(f"{label} Horizons vector is nonfinite")
    return vector


def catalog(receipts):
    source = receipts["documents"]["catalog"]
    text = source_path(source["path"], "catalog").read_text(errors="replace")
    line = next(line for line in text.splitlines() if "2026 Aug 28  04:14:04" in line)
    fields = html.unescape(re.sub(r"<[^>]+>", " ", line)).split()
    if len(fields) != 18 or fields[5] != "75":
        raise EvidenceError("catalog peak row or Delta T changed")
    return {"deltaTSeconds": int(fields[5]), "greatestEclipseUT": fields[4]}


def gregorian_jd(year, month, day, hour, minute, second):
    if month <= 2:
        year -= 1
        month += 12
    century = year // 100
    correction = 2 - century + century // 4
    fraction = (hour + (minute + second / 60) / 60) / 24
    return math.floor(365.25 * (year + 4_716)) + math.floor(30.6001 * (month + 1)) + day + fraction + correction - 1_524.5


def minimum_epoch(reader, segments, metric):
    lower = TARGET_JD - 300 / SECONDS_PER_DAY
    upper = TARGET_JD + 300 / SECONDS_PER_DAY
    window_lower = lower
    window_upper = upper
    ratio = (math.sqrt(5) - 1) / 2

    def value(jd):
        moon, sun = de421_geocentric(reader, segments, jd)
        row = overlap(moon, sun, "fiveMillenniumDanjon")
        return row[metric]

    left = upper - ratio * (upper - lower)
    right = lower + ratio * (upper - lower)
    for _ in range(64):
        if value(left) < value(right):
            upper, right = right, left
            left = upper - ratio * (upper - lower)
        else:
            lower, left = left, right
            right = lower + ratio * (upper - lower)
    result = (lower + upper) / 2
    step = 0.1 / SECONDS_PER_DAY
    if not window_lower < result < window_upper or not value(result) < value(result - step) or not value(result) < value(result + step) or not value(result) < value(window_lower) or not value(result) < value(window_upper):
        raise EvidenceError(f"DE421 {metric} minimum is not locally bracketed")
    return result


def build_results(receipts, manifest):
    reader = StoredRangeReader(manifest)
    segments = read_segments(reader)
    facts = catalog(receipts)
    delta_t = facts["deltaTSeconds"] / SECONDS_PER_DAY
    epochs = {
        "catalogPeakWithPublishedDeltaT": gregorian_jd(2026, 8, 28, 4, 14, 4) + delta_t,
        "nativeSelectedPeak": TARGET_JD,
        "svsPrintedMinuteWithCatalogDeltaT": gregorian_jd(2026, 8, 28, 4, 13, 0) + delta_t,
    }
    epochs["de421AxisDistanceMinimum"] = minimum_epoch(reader, segments, "axisDistanceKilometers")
    epochs["de421AngularSeparationMinimum"] = minimum_epoch(reader, segments, "separationArcseconds")
    shadows = ["geometric", "fiveMillenniumDanjon", "danjonExpandedTerms", "chauvenet"]
    matrix = []
    for epoch_name, jd in epochs.items():
        moon, sun = de421_geocentric(reader, segments, jd)
        for shadow in shadows:
            row = overlap(moon, sun, shadow)
            matrix.append({"epoch": epoch_name, "jdTDBApproximation": jd, "shadow": shadow, **row})
    identities = [(row["epoch"], row["shadow"]) for row in matrix]
    if len(identities) != len(set(identities)) or set(identities) != {(epoch, shadow) for epoch in epochs for shadow in shadows}:
        raise EvidenceError("convention matrix inventory is incomplete")
    target = next(row for row in matrix if row["epoch"] == "nativeSelectedPeak" and row["shadow"] == "fiveMillenniumDanjon")
    de441 = overlap(horizons_vector(receipts, "de441MoonGeometric"), horizons_vector(receipts, "de441SunGeometric"), "fiveMillenniumDanjon")
    apparent = load_json(BASELINE_RESULTS)["comparison"]["horizonsDE441DanjonReplay"]
    tdb_clock_rows = []
    for offset in (-0.002, 0.002):
        moon, sun = de421_geocentric(reader, segments, epochs["catalogPeakWithPublishedDeltaT"] + offset / SECONDS_PER_DAY)
        tdb_clock_rows.append(overlap(moon, sun, "fiveMillenniumDanjon")["obscuration"])
    reader.assert_inventory_used()
    return {
        "contributions": {
            "de421MinusDE441GeometricObscuration": target["obscuration"] - de441["obscuration"],
            "de441ApparentMinusGeometricObscuration": apparent["obscuration"] - de441["obscuration"],
            "peakAxisMinusNativeSeconds": (epochs["de421AxisDistanceMinimum"] - TARGET_JD) * SECONDS_PER_DAY,
            "peakAngleMinusAxisSeconds": (epochs["de421AngularSeparationMinimum"] - epochs["de421AxisDistanceMinimum"]) * SECONDS_PER_DAY,
            "tdbMinusTtTwoMillisecondObscurationSpan": max(tdb_clock_rows) - min(tdb_clock_rows),
        },
        "de441GeometricControl": de441,
        "matrix": matrix,
        "outcome": {
            "exactSVSConventionReproduced": False,
            "productionDefectEstablished": False,
            "remainingUndisclosedChoices": [
                "full-precision SVS peak epoch, UT realization, and dynamical-time conversion",
                "whether SVS used simultaneous geometric, light-time, or apparent positions",
                "Earth, Sun, and atmospheric shadow radii beyond the named 5MCLE dataset",
                "whether and how LOLA topography changed the lunar limb or covered area",
                "projection, nonspherical overlap, full-precision result, and rounding rule",
            ],
        },
        "scope": {
            "de421": "direct type-2 ICRF SPK interpolation from canonical NAIF byte ranges",
            "limb": "1737.4 km LOLA reference sphere only; no topographic limb is claimed",
            "peak": "five declared epoch interpretations; optimized rows are bracketed local minima inside the fixed plus-or-minus 300-second event window, and published UT rows use the catalog's 75-second Delta T as a TT/TDB approximation",
            "shadow": "four source-published circular formulas; none was selected by proximity to the SVS print",
        },
        "schemaVersion": 1,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--write", action="store_true")
    arguments = parser.parse_args()
    receipts = load_json(RECEIPTS)
    manifest = verify_receipts(receipts)
    result = json.dumps(build_results(receipts, manifest), indent=2, sort_keys=True) + "\n"
    if arguments.check:
        if not RESULTS.is_file() or RESULTS.read_text() != result:
            raise SystemExit("DE421 convention result differs; run --write and review the source change")
        print("DE421 source ranges and convention matrix verified; the exact SVS convention remains unresolved")
    else:
        RESULTS.write_text(result)
        print(RESULTS.relative_to(ROOT))


if __name__ == "__main__":
    main()
