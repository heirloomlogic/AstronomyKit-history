#!/usr/bin/env python3
"""Freeze direct DE441 records for bounded native lunar event qualification."""
import argparse
import hashlib
import importlib.util
import json
import math
import struct
import subprocess
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEPENDENCY_SPEC = importlib.util.spec_from_file_location("moon_event_dependencies", ROOT / "Scripts/evidence_dependencies.py")
dependencies = importlib.util.module_from_spec(DEPENDENCY_SPEC)
DEPENDENCY_SPEC.loader.exec_module(dependencies)
EVIDENCE = ROOT / "Scripts/moon-data/de441-compact-evidence.json"
OUTPUT = ROOT / "Scripts/moon-data/de441-event-fixtures.json"
FIXTURE_SHA256 = "94f77aad56bb3e136edcd7a04c04113f723cbd10371ea88c586f4504d2375ea6"
APPARENT_PHASE_OUTPUT = ROOT / "Scripts/moon-data/apparent-phase-references.json"
APPARENT_PHASE_SOURCES = {
    "sun": ROOT / "Scripts/moon-data/horizons-apparent-phase-sun.json",
    "moon": ROOT / "Scripts/moon-data/horizons-apparent-phase-moon.json",
}
APPARENT_PHASE_RESPONSES_SHA256 = {
    "sun": "ca66b540ea33705ca5a320270eb13b036f6e1af1a10428f32142420c78f90329",
    "moon": "3bdcddda7d80323e80f392b0624dd9baed84129e601c89ad525935ee8aae95a8",
}
APPARENT_PHASE_EVENTS = [
    ("firstQuarter", 90, 2_460_682.497_222_222),
    ("full", 180, 2_460_689.435_416_667),
    ("lastQuarter", 270, 2_460_697.354_861_111),
    ("new", 0, 2_460_705.025),
]
SOURCE_HASH_EVIDENCE = (
    ROOT / "Scripts/moon-data/de441-event-evidence.json",
)


def windows():
    half_span = 1461000 - 32.25
    result = [{"id": f"uniform-{index:02d}", "startTT": -half_span + index * 2 * half_span / 16 - 32,
               "endTT": -half_span + index * 2 * half_span / 16 + 32} for index in range(17)]
    result += [{"id": "blend-1900", "startTT": -36588.5, "endTT": -36492.5},
               {"id": "blend-2131", "startTT": 47814.5, "endTT": 47910.5},
               {"id": "source-segment", "startTT": -11144.5, "endTT": -11080.5}]
    return result


def required_records(selected, start):
    result = set()
    for window in selected:
        first = math.floor((window["startTT"] - .01 - start) / 4)
        last = math.floor((window["endTT"] + .01 - start) / 4)
        result.update(range(first, last + 1))
    return result


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def apparent_phase_query(command):
    dates = [round(center + minute / 1440, 9) for _, _, center in APPARENT_PHASE_EVENTS for minute in range(-3, 4)]
    return {
        "COMMAND": f"'{command}'", "OBJ_DATA": "'NO'", "MAKE_EPHEM": "'YES'", "EPHEM_TYPE": "'OBSERVER'",
        "CENTER": "'500@399'", "TLIST": f"'{','.join(str(value) for value in dates)}'", "QUANTITIES": "'31'",
        "REF_SYSTEM": "'ICRF'", "CAL_FORMAT": "'CAL'", "TIME_DIGITS": "'SECONDS'", "ANG_FORMAT": "'DEG'",
        "APPARENT": "'AIRLESS'", "RANGE_UNITS": "'AU'", "CSV_FORMAT": "'YES'", "EXTRA_PREC": "'YES'",
    }


def parse_apparent_longitudes(data):
    result = json.loads(data)["result"]
    rows = result[result.index("$$SOE") + len("$$SOE"):result.index("$$EOE")].strip().splitlines()
    parsed = []
    for row in rows:
        columns = [column.strip() for column in row.split(",")]
        parsed.append((datetime.strptime(columns[0], "%Y-%b-%d %H:%M:%S.%f").replace(tzinfo=timezone.utc), float(columns[3])))
    return parsed


def apparent_phase_references(source_data=None):
    if source_data is None:
        source_data = {name: path.read_bytes() for name, path in APPARENT_PHASE_SOURCES.items()}
    sun = parse_apparent_longitudes(source_data["sun"])
    moon = parse_apparent_longitudes(source_data["moon"])
    if len(sun) != 28 or [row[0] for row in sun] != [row[0] for row in moon]:
        raise ValueError("Apparent phase source samples differ")
    roots = []
    for index, (phase, target, _) in enumerate(APPARENT_PHASE_EVENTS):
        samples = []
        for sample in range(index * 7, index * 7 + 7):
            offset = (moon[sample][1] - sun[sample][1] - target + 180) % 360 - 180
            samples.append((sun[sample][0], offset))
        brackets = [(first, last) for first, last in zip(samples, samples[1:]) if first[1] <= 0 <= last[1]]
        if len(brackets) != 1 or brackets[0][1][1] <= brackets[0][0][1]:
            raise ValueError(f"Apparent {phase} samples do not contain one ascending root")
        first, last = brackets[0]
        fraction = -first[1] / (last[1] - first[1])
        root = first[0] + fraction * (last[0] - first[0])
        roots.append({
            "phase": phase, "targetDegrees": target, "utc": root.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "lowerUTC": first[0].isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "upperUTC": last[0].isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "samplingAllowanceSeconds": 1.0,
        })
    return roots


def apparent_phase_document(source_data):
    return {
        "schemaVersion": 1,
        "source": "NASA/JPL Horizons API",
        "frame": "Earth-centered IAU76/80 apparent ecliptic and equinox of date",
        "corrections": "Horizons quantity 31 includes light time, gravitational deflection, and stellar aberration",
        "timeScale": "UTC",
        "method": "Linear interpolation of one-minute apparent longitude-difference brackets; the one-second allowance covers sampling and printed precision",
        "responseSHA256": {name: hashlib.sha256(data).hexdigest() for name, data in source_data.items()},
        "roots": apparent_phase_references(source_data),
    }


def check_apparent_phase_sources():
    source_data = {name: path.read_bytes() for name, path in APPARENT_PHASE_SOURCES.items()}
    for name, data in source_data.items():
        if hashlib.sha256(data).hexdigest() != APPARENT_PHASE_RESPONSES_SHA256[name]:
            raise ValueError(f"Apparent phase {name} response digest differs")
        query_path = APPARENT_PHASE_SOURCES[name].with_suffix(".query.json")
        query = json.loads(query_path.read_bytes())
        response_sha = query.pop("_responseSHA256", None)
        if query != apparent_phase_query("10" if name == "sun" else "301") or response_sha != hashlib.sha256(data).hexdigest():
            raise ValueError(f"Apparent phase {name} query differs")
    if encoded(apparent_phase_document(source_data)) != APPARENT_PHASE_OUTPUT.read_bytes():
        raise ValueError("Apparent phase derived references differ")


def capture_apparent_phase_sources():
    source_data = {}
    for name, command in (("sun", "10"), ("moon", "301")):
        query = apparent_phase_query(command)
        url = "https://ssd.jpl.nasa.gov/api/horizons.api?" + urllib.parse.urlencode({"format": "json", **query})
        request = urllib.request.Request(url, headers={"User-Agent": "AstronomyKit apparent lunar phase reference capture"})
        with urllib.request.urlopen(request, timeout=30) as response:
            data = response.read()
        APPARENT_PHASE_SOURCES[name].write_bytes(data)
        query["_responseSHA256"] = hashlib.sha256(data).hexdigest()
        APPARENT_PHASE_SOURCES[name].with_suffix(".query.json").write_bytes(encoded(query))
        source_data[name] = data
        print(f"{name} response SHA-256: {hashlib.sha256(data).hexdigest()}")
    APPARENT_PHASE_OUTPUT.write_bytes(encoded(apparent_phase_document(source_data)))


def generate(cache):
    spec = importlib.util.spec_from_file_location("qualification", ROOT / "Scripts/qualify-moon-de441.py")
    q = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(q)
    evidence = json.loads(EVIDENCE.read_bytes())
    reader = q.CachedReader(cache / "ranges", evidence["source"]["retrievedByteRangesSHA256"])
    start = evidence["coverage"]["segments"][0]["firstRecordStartJulianDateTDB"] - 2451545
    chosen = required_records(windows(), start)
    rows = []
    global_index = 0
    for _, _, count, ranges in q.batches(q.layout(reader)):
        selected = sorted(index - global_index for index in chosen if global_index <= index < global_index + count)
        if selected:
            data = [reader.read(*r) for r in ranges]
            for index in selected:
                moon, earth = (struct.unpack_from("<41d", item, index * 41 * 8) for item in data)
                coefficients = [[moon[2 + axis * 13 + k] - earth[2 + axis * 13 + k] for k in range(13)] for axis in range(3)]
                position, velocity = q.evaluate(coefficients, 0)
                rows.append({"index": global_index + index, "coefficientsKm": coefficients,
                             "midpointPositionKm": position, "midpointVelocityKmPerTDBDay": velocity})
        global_index += count
    if {row["index"] for row in rows} != chosen:
        raise ValueError("Source records do not cover every frozen window")
    return encoded({"schemaVersion": 1, "sourceEvidenceSHA256": hashlib.sha256(EVIDENCE.read_bytes()).hexdigest(),
                    "frame": "geometric geocentric ICRF", "timeScale": "coefficients TDB; windows TT days from J2000",
                    "sourceStartTDB": start, "recordDays": 4, "windows": windows(), "records": rows})


def check(data):
    if hashlib.sha256(data).hexdigest() != FIXTURE_SHA256:
        raise ValueError("Direct event fixture digest differs")
    value = json.loads(data)
    if value["sourceEvidenceSHA256"] != hashlib.sha256(EVIDENCE.read_bytes()).hexdigest():
        raise ValueError("Direct event fixture source evidence differs")
    if value["windows"] != windows() or {r["index"] for r in value["records"]} != required_records(windows(), value["sourceStartTDB"]):
        raise ValueError("Direct event fixture coverage differs")


def event_source_paths():
    return list(dependencies.paths("moon-events"))


def check_source_hashes(evidence_path, root=ROOT, required_sources=None):
    evidence_path = Path(evidence_path)
    try:
        evidence = json.loads(evidence_path.read_bytes())
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read evidence JSON: {evidence_path}") from error
    source_hashes = evidence.get("sourceSHA256")
    if not isinstance(source_hashes, dict) or not source_hashes:
        raise ValueError(f"{evidence_path}: sourceSHA256 must be a non-empty object")
    if required_sources is not None and set(source_hashes) != set(required_sources):
        raise ValueError(f"{evidence_path}: source binding coverage differs")
    for source_name, expected in sorted(source_hashes.items()):
        relative = Path(source_name)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError(f"{evidence_path}: named source must be repository-relative: {source_name}")
        if not isinstance(expected, str) or len(expected) != 64 or any(character not in "0123456789abcdef" for character in expected):
            raise ValueError(f"{evidence_path}: invalid SHA-256 for {source_name}")
        source = root / relative
        if not source.is_file():
            raise ValueError(f"{evidence_path}: named source is missing: {source_name}")
        actual = hashlib.sha256(source.read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"{evidence_path}: source digest differs for {source_name}: recorded {expected}, actual {actual}")
    return len(source_hashes)


def collect_results(prefix):
    results = {name: json.loads(Path(str(prefix) + "-" + name + ".json").read_bytes())
               for name in ("apparent", "published", "source", "transitions")}
    summaries = {}
    for name in ("apparent", "published", "source"):
        summaries[name] = {}
        for event in sorted({row["event"] for row in results[name]}):
            # Non-gating diagnostic rows (the January 2100 USNO phase labels) stay in results only.
            rows = [row for row in results[name] if row["event"] == event and row.get("gating", True)]
            summaries[name][event] = {"count": len(rows),
                                     "maximumAbsoluteResidualSeconds": max(abs(row["residualSeconds"]) for row in rows)}
    result = {"schemaVersion": 1,
              "runtimeBaseRevision": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
              "toolchain": subprocess.check_output(["swift", "--version"], text=True, stderr=subprocess.STDOUT).strip(),
              "sourceSHA256": dependencies.source_hashes("moon-events"),
              "apparentPhaseReferences": json.loads(APPARENT_PHASE_OUTPUT.read_bytes()),
              "summaries": summaries, "results": results,
              "scope": "Published tolerances retain their existing reference scope. Production searches are paired with direct-source roots in frozen full-span and transition windows; no universal event-time or velocity bound is inferred.",
              "remainingDependencies": ["#92 planetary and observer search ports", "#184 broader qualification and closure"]}
    path = ROOT / "Scripts/moon-data/de441-event-evidence.json"
    path.write_bytes(encoded(result))
    print("Recorded event evidence:", path.relative_to(ROOT))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=ROOT / ".context/issue-184/compact")
    parser.add_argument("--check", action="store_true", help="verify the pinned committed fixture offline")
    parser.add_argument("--check-source", action="store_true", help="rebuild against the verified source cache and compare")
    parser.add_argument("--collect-results", type=Path, metavar="PREFIX", help="record PREFIX-published/source/transitions.json emitted by Swift tests")
    parser.add_argument("--capture-apparent-phases", action="store_true", help="capture the pinned Horizons apparent-phase samples")
    args = parser.parse_args()
    if args.collect_results:
        collect_results(args.collect_results)
        return
    if args.capture_apparent_phases:
        capture_apparent_phase_sources()
        return
    if args.check:
        check(OUTPUT.read_bytes())
        check_apparent_phase_sources()
        for evidence_path in SOURCE_HASH_EVIDENCE:
            check_source_hashes(evidence_path, required_sources=event_source_paths() if evidence_path == SOURCE_HASH_EVIDENCE[0] else None)
    elif args.check_source:
        if generate(args.cache) != OUTPUT.read_bytes():
            raise ValueError("Direct event fixture differs from verified source records")
    else:
        data = generate(args.cache)
        OUTPUT.write_bytes(data)
        print("Fixture SHA-256:", hashlib.sha256(data).hexdigest())
    print("Verified direct event fixtures" if args.check or args.check_source else "Generated direct event fixtures")


if __name__ == "__main__":
    main()
