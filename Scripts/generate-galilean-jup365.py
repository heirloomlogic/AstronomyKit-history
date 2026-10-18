#!/usr/bin/env python3
"""Extract and qualify a compact jup365 representation for the Galilean moons."""

import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import re
import struct
import subprocess
import tempfile
from typing import NamedTuple
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "Scripts/jupiter-moon-data/jup365"
MANIFEST = DATA / "representation.json"
COMMENT = DATA / "jup365.cmt"
PERFORMANCE = DATA / "performance.json"
PROBE = DATA.parent / "jup365-probe.swift"
SOURCE_URL = "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/spk/satellites/jup365.bsp"
COMMENT_URL = "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/spk/satellites/jup365.cmt"
SOURCE_IDENTITY = (1_136_581_632, None, "Sun, 14 Mar 2021 15:29:22 GMT")
SOURCE_CENTER = 5
COVERAGE = (2_305_456.5, 2_524_602.5)
SOURCE_SEAM = 2_450_464.5
J2000 = 2_451_545.0
AU_KM = 149_597_870.7
BATCH_RECORDS = 8_192
MOONS = ("io", "europa", "ganymede", "callisto")
POSITION_LIMIT_KM = 0.25
VELOCITY_LIMIT_KM_PER_TDB_DAY = 35.0


class CandidateSpec(NamedTuple):
    target: int
    source_coefficients: int
    kept_coefficients: int
    float32_coefficients: int


SPECS = {
    "io": CandidateSpec(501, 16, 11, 6),
    "europa": CandidateSpec(502, 16, 9, 4),
    "ganymede": CandidateSpec(503, 10, 7, 3),
    "callisto": CandidateSpec(504, 11, 7, 4),
    "jupiter": CandidateSpec(599, 16, 10, 2),
}

PLANET_SPEC = importlib.util.spec_from_file_location("planet_de441", ROOT / "Scripts/generate-planet-de441.py")
planet = importlib.util.module_from_spec(PLANET_SPEC)
PLANET_SPEC.loader.exec_module(planet)
spk = planet.spk

GALILEAN_SPEC = importlib.util.spec_from_file_location("galilean_residuals", ROOT / "Scripts/galilean-residuals.py")
galilean = importlib.util.module_from_spec(GALILEAN_SPEC)
GALILEAN_SPEC.loader.exec_module(galilean)


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def upward(value):
    if value < 0 or math.isnan(value):
        raise ValueError("outward bound input is negative or NaN")
    if math.isinf(value):
        return value
    return math.nextafter(value, math.inf)


def upper_absolute_difference(left, right):
    if left == right:
        return 0.0
    return upward(abs(left - right))


def upper_add(left, right):
    if left == 0:
        return right
    if right == 0:
        return left
    return upward(left + right)


def upper_multiply(left, right):
    if left == 0 or right == 0:
        return 0.0
    return upward(left * right)


def upper_divide(left, right):
    if left == 0:
        return 0.0
    return upward(left / right)


def upper_sum(values):
    result = 0.0
    for value in values:
        result = upper_add(result, value)
    return result


def upper_vector_norm(values):
    squared = upper_sum(upper_multiply(value, value) for value in values)
    if squared == 0:
        return 0.0
    return upward(math.sqrt(squared))


def payload_path(name):
    return DATA / f"{name}.bin"


def source_bindings():
    return sorted(
        {
            "Scripts/generate-galilean-jup365.py",
            "Scripts/test_generate_galilean_jup365.py",
            "Scripts/jupiter-moon-data/jup365-probe.swift",
            "Scripts/generate-planet-de441.py",
            "Scripts/assess-moon-de441.py",
            "Scripts/galilean-residuals.py",
            "Scripts/test_galilean_residuals.py",
            galilean.FIXTURE,
            *galilean.archive_paths(),
        }
    )


def binding_hashes():
    return {path: digest((ROOT / path).read_bytes()) for path in source_bindings()}


def record_bytes(spec):
    tail = spec.kept_coefficients - spec.float32_coefficients
    return 3 * (4 * spec.float32_coefficients + 2 * tail)


def evaluate_axis(coefficients, x, days):
    values = [1.0, x]
    derivatives = [0.0, 1.0]
    for _ in range(2, len(coefficients)):
        values.append(2 * x * values[-1] - values[-2])
        derivatives.append(2 * values[-2] + 2 * x * derivatives[-1] - derivatives[-2])
    position = math.fsum(coefficient * value for coefficient, value in zip(coefficients, values))
    velocity = math.fsum(coefficient * derivative for coefficient, derivative in zip(coefficients, derivatives)) * 2 / days
    return position, velocity


def evaluate_axes(axes, x, days):
    values = [evaluate_axis(axis, x, days) for axis in axes]
    return tuple(value[0] for value in values), tuple(value[1] for value in values)


def tail_scales(records, spec):
    tail = spec.kept_coefficients - spec.float32_coefficients
    maxima = [[0.0] * tail for _ in range(3)]
    for _, _, axes in records:
        for axis in range(3):
            for offset in range(tail):
                degree = spec.float32_coefficients + offset
                maxima[axis][offset] = max(maxima[axis][offset], abs(axes[axis][degree]))
    return tuple(tuple(value / 32_767 if value else 1.0 for value in axis) for axis in maxima)


def packed_axis(axis, spec, scales):
    result = bytearray()
    decoded = []
    for value in axis[: spec.float32_coefficients]:
        result.extend(struct.pack("<f", value))
        decoded.append(struct.unpack("<f", result[-4:])[0])
    for degree, scale in zip(range(spec.float32_coefficients, spec.kept_coefficients), scales):
        integer = max(-32_767, min(32_767, round(axis[degree] / scale)))
        result.extend(struct.pack("<h", integer))
        decoded.append(integer * scale)
    decoded.extend([0.0] * (spec.source_coefficients - spec.kept_coefficients))
    return bytes(result), tuple(decoded)


def pack_records(records, spec):
    records = list(records)
    if not records:
        raise ValueError("candidate has no source records")
    scales = tail_scales(records, spec)
    payload = bytearray()
    maximum_position = 0.0
    maximum_velocity = 0.0
    worst_position = None
    worst_velocity = None
    for index, (start, days, axes) in enumerate(records):
        if len(axes) != 3 or any(len(axis) != spec.source_coefficients for axis in axes):
            raise ValueError("source coefficient shape differs")
        position_axes = []
        velocity_axes = []
        for axis, scale in zip(axes, scales):
            packed, decoded = packed_axis(axis, spec, scale)
            payload.extend(packed)
            errors = [upper_absolute_difference(left, right) for left, right in zip(axis, decoded)]
            position_axes.append(upper_sum(errors))
            weighted = []
            for degree, error in enumerate(errors):
                term = upper_multiply(error, degree)
                term = upper_multiply(term, degree)
                term = upper_multiply(term, 2.0)
                weighted.append(upper_divide(term, days))
            velocity_axes.append(upper_sum(weighted))
        position = upper_vector_norm(position_axes)
        velocity = upper_vector_norm(velocity_axes)
        if position > maximum_position:
            maximum_position = position
            worst_position = {"record": index, "startJDTDB": start, "axisBoundsKm": position_axes}
        if velocity > maximum_velocity:
            maximum_velocity = velocity
            worst_velocity = {"record": index, "startJDTDB": start, "axisBoundsKmPerTDBDay": velocity_axes}
    result = bytes(payload)
    validate_payload(result, spec, scales, len(records))
    return result, scales, {
        "positionKm": maximum_position,
        "velocityKmPerTDBDay": maximum_velocity,
        "worstPosition": worst_position,
        "worstVelocity": worst_velocity,
    }


def validate_payload(data, spec, scales, record_count):
    if len(data) != record_count * record_bytes(spec):
        raise ValueError("candidate payload length differs")
    tail = spec.kept_coefficients - spec.float32_coefficients
    if len(scales) != 3 or any(len(axis) != tail for axis in scales):
        raise ValueError("candidate scale shape differs")
    if any(not math.isfinite(value) or value <= 0 for axis in scales for value in axis):
        raise ValueError("candidate scale is not positive and finite")
    offset = 0
    for _ in range(record_count * 3):
        for _ in range(spec.float32_coefficients):
            value = struct.unpack_from("<f", data, offset)[0]
            if not math.isfinite(value):
                raise ValueError("candidate head coefficient is not finite")
            offset += 4
        offset += 2 * tail


def decode_record(data, spec, scales, record):
    offset = record * record_bytes(spec)
    if record < 0 or offset + record_bytes(spec) > len(data):
        raise ValueError("candidate record is outside the payload")
    axes = []
    tail = spec.kept_coefficients - spec.float32_coefficients
    for axis in range(3):
        coefficients = list(struct.unpack_from(f"<{spec.float32_coefficients}f", data, offset))
        offset += 4 * spec.float32_coefficients
        integers = struct.unpack_from(f"<{tail}h", data, offset)
        offset += 2 * tail
        coefficients.extend(integer * scale for integer, scale in zip(integers, scales[axis]))
        coefficients.extend([0.0] * (spec.source_coefficients - spec.kept_coefficients))
        axes.append(tuple(coefficients))
    return tuple(axes)


def evaluate_table(data, spec, scales, report, julian_date_tdb):
    start = report["startJDTDB"]
    end = report["exclusiveEndJDTDB"]
    days = report["recordDays"]
    if not math.isfinite(julian_date_tdb) or not start <= julian_date_tdb < end:
        return None
    record = math.floor((julian_date_tdb - start) / days)
    if record < 0 or record >= report["recordCount"]:
        return None
    record_start = start + record * days
    x = 2 * (julian_date_tdb - record_start) / days - 1
    return evaluate_axes(decode_record(data, spec, scales, record), x, days)


def sorted_ranges(ranges):
    return dict(sorted(ranges.items(), key=lambda item: int(item[0].split("-", 1)[0])))


def source_layout(reader, spec):
    selected = []
    for segment in spk.read_segments(reader):
        if (segment.target, segment.center) != (spec.target, SOURCE_CENTER):
            continue
        if (segment.frame, segment.kind) != (1, 2):
            raise ValueError("jup365 component is not type-2 ICRF")
        metadata = spk.read_metadata(reader, segment)
        if (metadata.record_words - 2) // 3 != spec.source_coefficients:
            raise ValueError("jup365 source coefficient count differs")
        selected.append((segment, metadata))
    selected.sort(key=lambda value: value[0].start_seconds_tdb)
    if len(selected) != 2:
        raise ValueError("jup365 component segment inventory differs")
    cursor = COVERAGE[0]
    for segment, metadata in selected:
        start = J2000 + segment.start_seconds_tdb / 86_400
        end = J2000 + segment.end_seconds_tdb / 86_400
        if start != cursor or metadata.start_jd_tdb != start:
            raise ValueError("jup365 component coverage is gapped or shifted")
        record_end = metadata.start_jd_tdb + metadata.record_days * metadata.record_count
        if not end <= record_end or not end > record_end - metadata.record_days:
            raise ValueError("jup365 component record domain does not cover its segment")
        cursor = end
    if cursor != COVERAGE[1] or J2000 + selected[0][0].end_seconds_tdb / 86_400 != SOURCE_SEAM:
        raise ValueError("jup365 component endpoints or seam differ")
    first_shape = (selected[0][1].record_days, selected[0][1].record_words)
    if any((metadata.record_days, metadata.record_words) != first_shape for _, metadata in selected):
        raise ValueError("jup365 component record shape changes")
    return selected


def iter_source_records(reader, spec):
    for segment, metadata in source_layout(reader, spec):
        for first in range(0, metadata.record_count, BATCH_RECORDS):
            count = min(BATCH_RECORDS, metadata.record_count - first)
            start = (segment.first_word - 1 + first * metadata.record_words) * 8
            raw = reader.read(start, count * metadata.record_words * 8)
            for offset in range(count):
                values = struct.unpack_from(f"<{metadata.record_words}d", raw, offset * metadata.record_words * 8)
                record = first + offset
                record_start = metadata.start_jd_tdb + record * metadata.record_days
                expected = ((record_start - J2000 + metadata.record_days / 2) * 86_400, metadata.record_days * 43_200)
                if values[:2] != expected or any(not math.isfinite(value) for value in values):
                    raise ValueError("jup365 record metadata or coefficient differs")
                count_per_axis = spec.source_coefficients
                axes = tuple(tuple(values[2 + axis * count_per_axis : 2 + (axis + 1) * count_per_axis]) for axis in range(3))
                yield record_start, metadata.record_days, axes


def evaluate_source(records, julian_date_tdb):
    if not math.isfinite(julian_date_tdb) or not COVERAGE[0] <= julian_date_tdb < COVERAGE[1]:
        return None
    days = records[0][1]
    record = math.floor((julian_date_tdb - records[0][0]) / days)
    start, record_days, axes = records[record]
    if start > julian_date_tdb or julian_date_tdb >= start + record_days:
        raise ValueError("jup365 source record selection differs")
    x = 2 * (julian_date_tdb - start) / record_days - 1
    return evaluate_axes(axes, x, record_days)


def vector_difference(left, right):
    return tuple(a - b for a, b in zip(left, right))


def vector_sum(left, right):
    return tuple(a + b for a, b in zip(left, right))


def fixture_epochs(record_days):
    representative_start = COVERAGE[0] + math.floor((J2000 - COVERAGE[0]) / record_days) * record_days
    return (
        COVERAGE[0],
        math.nextafter(SOURCE_SEAM, -math.inf),
        SOURCE_SEAM,
        math.nextafter(SOURCE_SEAM, math.inf),
        representative_start,
        representative_start + record_days / 2,
        math.nextafter(representative_start + record_days, -math.inf),
        representative_start + record_days,
        math.nextafter(COVERAGE[1], -math.inf),
    )


def component_fixture_rows(name, data, spec, scales, report, records):
    rows = []
    for julian_date in fixture_epochs(report["recordDays"]):
        source = evaluate_source(records, julian_date)
        candidate = evaluate_table(data, spec, scales, report, julian_date)
        if source is None or candidate is None:
            raise ValueError("fixture epoch is outside the represented source")
        position_error = math.dist(source[0], candidate[0])
        velocity_error = math.dist(source[1], candidate[1])
        bounds = report["coefficientRepresentationBound"]
        if position_error > bounds["positionKm"] or velocity_error > bounds["velocityKmPerTDBDay"]:
            raise ValueError("fixture exceeds the continuous coefficient bound")
        rows.append(
            {
                "component": name,
                "julianDateTDB": julian_date,
                "candidatePositionKm": list(candidate[0]),
                "candidateVelocityKmPerTDBDay": list(candidate[1]),
                "sourcePositionErrorKm": position_error,
                "sourceVelocityErrorKmPerTDBDay": velocity_error,
            }
        )
    return rows


def candidate_state(payloads, reports, julian_date_tdb, name):
    target_report = reports[name]
    center_report = reports["jupiter"]
    target = evaluate_table(payloads[name], SPECS[name], target_report["tailScales"], target_report, julian_date_tdb)
    center = evaluate_table(payloads["jupiter"], SPECS["jupiter"], center_report["tailScales"], center_report, julian_date_tdb)
    if target is None or center is None:
        return None
    return vector_difference(target[0], center[0]), vector_difference(target[1], center[1])


def sampled_horizons_residuals(payloads, reports):
    rows = []
    for reference in galilean.references():
        state = candidate_state(payloads, reports, reference["julianDateTDB"], reference["body"])
        if state is None:
            raise ValueError("archived Horizons row is outside jup365 coverage")
        reference_position = tuple(value * AU_KM for value in reference["positionAU"])
        reference_velocity = tuple(value * AU_KM for value in reference["velocityAUPerDay"])
        rows.append(
            {
                "body": reference["body"],
                "julianDateTDB": reference["julianDateTDB"],
                "positionErrorKm": math.dist(state[0], reference_position),
                "velocityErrorKmPerTDBDay": math.dist(state[1], reference_velocity),
            }
        )
    summary = {}
    for body in MOONS:
        body_rows = [row for row in rows if row["body"] == body]
        position = max(body_rows, key=lambda row: row["positionErrorKm"])
        velocity = max(body_rows, key=lambda row: row["velocityErrorKmPerTDBDay"])
        summary[body] = {
            "count": len(body_rows),
            "maximumPositionErrorKm": position["positionErrorKm"],
            "maximumPositionErrorJDTDB": position["julianDateTDB"],
            "maximumVelocityErrorKmPerTDBDay": velocity["velocityErrorKmPerTDBDay"],
            "maximumVelocityErrorJDTDB": velocity["julianDateTDB"],
        }
    return {"rows": rows, "summary": summary}


def combined_bounds(reports):
    center = reports["jupiter"]["coefficientRepresentationBound"]
    return {
        name: {
            "positionKm": upper_add(reports[name]["coefficientRepresentationBound"]["positionKm"], center["positionKm"]),
            "velocityKmPerTDBDay": upper_add(reports[name]["coefficientRepresentationBound"]["velocityKmPerTDBDay"], center["velocityKmPerTDBDay"]),
        }
        for name in MOONS
    }


def verify_manifest(manifest, payloads, comment=None):
    if manifest.get("schemaVersion") != 1 or manifest.get("generatorBindingsSHA256") != binding_hashes():
        raise ValueError("jup365 schema or generator binding differs")
    if manifest.get("coverageJDTDB") != list(COVERAGE) or manifest.get("sourceSeamJDTDB") != SOURCE_SEAM:
        raise ValueError("jup365 coverage or source seam differs")
    if set(manifest.get("components", {})) != set(SPECS) or set(payloads) != set(SPECS):
        raise ValueError("jup365 component inventory differs")
    if manifest.get("source", {}).get("url") != SOURCE_URL or manifest["source"].get("identity") != list(SOURCE_IDENTITY):
        raise ValueError("jup365 source identity differs")
    comment = COMMENT.read_bytes() if comment is None else comment
    if manifest["source"].get("comment") != {"url": COMMENT_URL, "sha256": digest(comment)}:
        raise ValueError("jup365 source comment differs")
    for token in (b"Satellite Ephemeris: JUP365.26", b"Chebyshev interpolation error: 16.00 meters"):
        if token not in comment:
            raise ValueError("jup365 source comment semantics differ")
    ranges = manifest["source"].get("retrievedByteRangesSHA256", {})
    if not ranges or any(not re.fullmatch(r"\d+-\d+", key) or not re.fullmatch(r"[0-9a-f]{64}", value) for key, value in ranges.items()):
        raise ValueError("jup365 source range receipts differ")
    for name, spec in SPECS.items():
        report = manifest["components"][name]
        expected = {
            "target": spec.target,
            "center": SOURCE_CENTER,
            "frame": "ICRF",
            "clock": "TDB",
            "startJDTDB": COVERAGE[0],
            "exclusiveEndJDTDB": COVERAGE[1],
            "sourceCoefficientCount": spec.source_coefficients,
            "keptCoefficientCount": spec.kept_coefficients,
            "float32CoefficientCount": spec.float32_coefficients,
        }
        if any(report.get(key) != value for key, value in expected.items()):
            raise ValueError(f"jup365 component semantics differ: {name}")
        validate_payload(payloads[name], spec, report.get("tailScales", ()), report.get("recordCount", -1))
        if report.get("encodedBytes") != len(payloads[name]) or report.get("sha256") != digest(payloads[name]):
            raise ValueError(f"jup365 payload digest differs: {name}")
    if manifest.get("decodedPayloadBytes") != sum(map(len, payloads.values())):
        raise ValueError("jup365 decoded byte count differs")
    if manifest.get("base64PayloadBytes") != sum(4 * math.ceil(len(data) / 3) for data in payloads.values()):
        raise ValueError("jup365 base64 byte count differs")
    bounds = combined_bounds(manifest["components"])
    if manifest.get("combinedJovicentricRepresentationBound") != bounds:
        raise ValueError("jup365 combined coefficient bound differs")
    if any(row["positionKm"] > POSITION_LIMIT_KM or row["velocityKmPerTDBDay"] > VELOCITY_LIMIT_KM_PER_TDB_DAY for row in bounds.values()):
        raise ValueError("jup365 combined coefficient bound exceeds qualification limit")
    fixtures = manifest.get("directFixtures", [])
    expected_fixture_identities = [(name, julian_date) for name in SPECS for julian_date in fixture_epochs(manifest["components"][name]["recordDays"])]
    actual_fixture_identities = [(row.get("component"), row.get("julianDateTDB")) for row in fixtures]
    if actual_fixture_identities != expected_fixture_identities:
        raise ValueError("jup365 direct fixture identity inventory differs")
    for row in fixtures:
        name = row["component"]
        report = manifest["components"][name]
        candidate = evaluate_table(payloads[name], SPECS[name], report["tailScales"], report, row["julianDateTDB"])
        if candidate is None or list(candidate[0]) != row["candidatePositionKm"] or list(candidate[1]) != row["candidateVelocityKmPerTDBDay"]:
            raise ValueError("jup365 direct candidate fixture differs")
        bound = report["coefficientRepresentationBound"]
        if row["sourcePositionErrorKm"] > bound["positionKm"] or row["sourceVelocityErrorKmPerTDBDay"] > bound["velocityKmPerTDBDay"]:
            raise ValueError("jup365 direct fixture exceeds coefficient bound")
    sampled = sampled_horizons_residuals(payloads, manifest["components"])
    if manifest.get("sampledHorizonsResiduals") != sampled:
        raise ValueError("jup365 sampled Horizons replay differs")
    if len(sampled["rows"]) != 104:
        raise ValueError("jup365 sampled Horizons inventory differs")


def verify_performance(manifest):
    performance = json.loads(PERFORMANCE.read_bytes())
    expected = {
        "schemaVersion": 1,
        "probeSHA256": digest(PROBE.read_bytes()),
        "representationSHA256": digest(encoded(manifest)),
        "decodedPayloadBytes": manifest["decodedPayloadBytes"],
        "configuration": "swiftc -O",
    }
    if any(performance.get(key) != value for key, value in expected.items()):
        raise ValueError("jup365 performance evidence binding differs")
    measurement = performance.get("measurement", {})
    required = {"iterations", "manifestAndPayloadMappingMilliseconds", "firstEvaluationMilliseconds", "firstMicrosecondsPerJovicentricState", "firstChecksum", "warmEvaluationMilliseconds", "warmMicrosecondsPerJovicentricState", "checksum"}
    if set(measurement) != required or measurement["iterations"] < 100_000:
        raise ValueError("jup365 performance measurement inventory differs")
    if any(type(measurement[key]) not in (int, float) or not math.isfinite(measurement[key]) for key in required):
        raise ValueError("jup365 performance measurement is not finite")
    if any(measurement[key] <= 0 for key in required - {"checksum", "firstChecksum"}) or measurement["checksum"] == 0 or measurement["firstChecksum"] != measurement["checksum"]:
        raise ValueError("jup365 performance measurement is empty")
    if not performance.get("swiftVersion") or not performance.get("host"):
        raise ValueError("jup365 performance environment is missing")


def measure(manifest, iterations):
    with tempfile.TemporaryDirectory() as directory:
        executable = Path(directory) / "jup365-probe"
        subprocess.run(["swiftc", "-O", str(PROBE), "-o", str(executable)], cwd=ROOT, check=True)
        raw = subprocess.check_output([str(executable), str(DATA), str(iterations)], cwd=ROOT)
    measurement = json.loads(raw)
    performance = {
        "schemaVersion": 1,
        "probeSHA256": digest(PROBE.read_bytes()),
        "representationSHA256": digest(encoded(manifest)),
        "decodedPayloadBytes": manifest["decodedPayloadBytes"],
        "configuration": "swiftc -O",
        "swiftVersion": subprocess.check_output(["swift", "--version"], cwd=ROOT, text=True).strip(),
        "host": platform.platform(),
        "measurement": measurement,
    }
    atomic_write(PERFORMANCE, encoded(performance))
    verify_performance(manifest)
    print(json.dumps(measurement, sort_keys=True))


def build(reader, comment):
    reports = {}
    payloads = {}
    fixtures = []
    for name, spec in SPECS.items():
        print(f"Packing {name}", flush=True)
        records = list(iter_source_records(reader, spec))
        payload, scales, bounds = pack_records(records, spec)
        payloads[name] = payload
        reports[name] = {
            "target": spec.target,
            "center": SOURCE_CENTER,
            "frame": "ICRF",
            "clock": "TDB",
            "startJDTDB": COVERAGE[0],
            "exclusiveEndJDTDB": COVERAGE[1],
            "recordDays": records[0][1],
            "recordCount": len(records),
            "sourceCoefficientCount": spec.source_coefficients,
            "keptCoefficientCount": spec.kept_coefficients,
            "float32CoefficientCount": spec.float32_coefficients,
            "tailScales": [list(axis) for axis in scales],
            "encodedBytes": len(payload),
            "sha256": digest(payload),
            "coefficientRepresentationBound": bounds,
        }
        fixtures.extend(component_fixture_rows(name, payload, spec, scales, reports[name], records))
    manifest = {
        "schemaVersion": 1,
        "generatorBindingsSHA256": binding_hashes(),
        "coverageJDTDB": list(COVERAGE),
        "sourceSeamJDTDB": SOURCE_SEAM,
        "source": {
            "url": SOURCE_URL,
            "identity": list(SOURCE_IDENTITY),
            "comment": {"url": COMMENT_URL, "sha256": digest(comment)},
            "retrievedByteRangesSHA256": sorted_ranges(reader.ranges),
        },
        "components": reports,
        "combinedJovicentricRepresentationBound": combined_bounds(reports),
        "decodedPayloadBytes": sum(len(payload) for payload in payloads.values()),
        "base64PayloadBytes": sum(4 * math.ceil(len(payload) / 3) for payload in payloads.values()),
        "directFixtures": fixtures,
        "sampledHorizonsResiduals": sampled_horizons_residuals(payloads, reports),
    }
    return payloads, manifest


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def publish(payloads, manifest, comment):
    verify_manifest(manifest, payloads, comment)
    DATA.mkdir(parents=True, exist_ok=True)
    for name, payload in payloads.items():
        atomic_write(payload_path(name), payload)
    atomic_write(COMMENT, comment)
    atomic_write(MANIFEST, encoded(manifest))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--capture", action="store_true")
    parser.add_argument("--verify-source", action="store_true")
    parser.add_argument("--measure", action="store_true")
    parser.add_argument("--iterations", type=int, default=200_000)
    parser.add_argument("--cache", type=Path, default=ROOT / ".context/issue-254/ranges")
    args = parser.parse_args()
    if sum((args.check, args.capture, args.verify_source, args.measure)) != 1:
        parser.error("choose exactly one of --check, --capture, --verify-source, or --measure")
    if args.check:
        manifest = json.loads(MANIFEST.read_bytes())
        payloads = {name: payload_path(name).read_bytes() for name in SPECS}
        verify_manifest(manifest, payloads)
        verify_performance(manifest)
        print("Checked Galilean jup365 representation: 104 Horizons rows and 45 direct fixtures")
        return
    if args.measure:
        manifest = json.loads(MANIFEST.read_bytes())
        payloads = {name: payload_path(name).read_bytes() for name in SPECS}
        verify_manifest(manifest, payloads)
        measure(manifest, args.iterations)
        return
    prior = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    expected_ranges = prior.get("source", {}).get("retrievedByteRangesSHA256")
    reader = planet.CachedReader("jup365", args.cache, expected_ranges)
    with urllib.request.urlopen(COMMENT_URL, timeout=60) as response:
        comment = response.read()
    for token in (b"Satellite Ephemeris: JUP365.26", b"Chebyshev interpolation error: 16.00 meters"):
        if token not in comment:
            raise ValueError("jup365 source comment semantics differ")
    payloads, manifest = build(reader, comment)
    if args.verify_source:
        committed = {name: payload_path(name).read_bytes() for name in SPECS}
        if manifest != prior or payloads != committed or comment != COMMENT.read_bytes():
            raise SystemExit("official jup365 replay differs from the committed representation")
        verify_manifest(manifest, committed)
        print("Verified official jup365 replay")
        return
    publish(payloads, manifest, comment)
    print("Wrote Galilean jup365 representation")


if __name__ == "__main__":
    main()
