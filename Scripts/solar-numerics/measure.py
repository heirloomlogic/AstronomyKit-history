#!/usr/bin/env python3
"""Run native Swift primitives and retain every high-precision comparison row."""
import argparse
import json
import math
import os
from pathlib import Path
import platform
import struct
import subprocess
import time

import reference as ref
import apparent_reference
import solar_reference as solar
from numerics import ROOT, BINDINGS, source_hashes, check_hashes

TOOLS = ["Scripts/solar-numerics/reference.py", "Scripts/solar-numerics/measure.py",
         "Scripts/solar-numerics/solar_reference.py", "Scripts/solar-numerics/apparent_reference.py",
         "Scripts/apparent-place-data/dtdb.c",
         "Tests/AstronomyKitTests/Engine/Numerics/NativeNumericalProbe.swift", *apparent_reference.PATHS]


def grid():
    rows = []
    def add(label, value, scale):
        for model in ["espenakMeeus", "jplHorizons"]:
            rows.append({"id": f"{label}-{model}", "days": value, "scale": scale, "model": model})
    # Interior grid, fallback on both sides, exact seams and adjacent doubles.
    for index in range(33):
        add(f"coverage-{index}", -36524.5 + index * (36889.5 + 36524.5) / 32, "tt")
    for year in [1800, 1850, 1899, 2101, 2150, 2200]:
        add(f"fallback-{year}", float(ref.year_start(year)) + 100.25, "tt")
    for index in [0, 1, 4565, 9176]:
        boundary = -36524.5 + index * 8
        for label, value in [("below", math.nextafter(boundary, -math.inf)), ("at", boundary),
                             ("above", math.nextafter(boundary, math.inf))]:
            add(f"seam-{index}-{label}", value, "tt")
    for year in [1860, 1900, 1920, 1941, 1961, 1986, 2005, 2050, 2150]:
        boundary = float(ref.year_start(year))
        for label, value in [("below", math.nextafter(boundary, -math.inf)), ("at", boundary),
                             ("above", math.nextafter(boundary, math.inf))]:
            add(f"deltaT-{year}-{label}", value, "ut")
    for label, value in [("below", math.nextafter(17 * 365.24217, -math.inf)),
                         ("at", 17 * 365.24217), ("above", math.nextafter(17 * 365.24217, math.inf))]:
        add(f"hold-{label}", value, "ut")
    return rows


def decode(bits):
    return struct.unpack(">d", int(bits, 16).to_bytes(8, "big"))[0]


def ecliptic_earth(earth, tt):
    weight, _ = earth.weight(tt)
    if not weight:
        return earth.retained.position(tt)
    source, _ = earth.source(tt)
    # Native EQJ-to-VSOP uses the transpose, not a mathematical matrix inverse.
    columns = [solar.equatorial_earth([int(i == j) for i in range(3)]) for j in range(3)]
    selected = [ref.mp.fdot(column, source) for column in columns]
    if weight == 1:
        return selected
    retained = earth.retained.position(tt)
    return [a + weight * (b - a) for a, b in zip(retained, selected)]


def comparisons(records, requests):
    if len(records) != len(requests) or len({row["id"] for row in records}) != len(records):
        raise ValueError("Missing or duplicate native output rows")
    earth = solar.SelectedEarth()
    result = []
    for record, request in zip(records, requests):
        if any(record[key] != request[key] for key in ["id", "model", "scale"]):
            raise ValueError("Native result is associated with the wrong request")
        numbers = {name: decode(bits) for name, bits in record["values"].items()}
        if numbers["input"].hex() != request["days"].hex() or numbers[request["scale"]].hex() != request["days"].hex():
            raise ValueError("Native input bits or supplied time scale changed")
        if not all(math.isfinite(value) for value in numbers.values()):
            raise ValueError("Nonfinite native result")
        ut, tt = ref.exact(numbers["ut"]), ref.exact(numbers["tt"])
        dt = ref.delta_t(ut, record["model"])
        e = ecliptic_earth(earth, tt)
        nutation = ref.nutation(tt)
        reference = {"deltaTSeconds": dt, "forwardTT": ut + dt / 86400,
                     "eraDegrees": ref.era(ut), "earthX": e[0], "earthY": e[1], "earthZ": e[2],
                     "nutationLongitudeDegrees": nutation[0], "nutationObliquityDegrees": nutation[1]}
        errors = {name: ref.exact(numbers[name]) - value for name, value in reference.items()}
        errors["eraDegrees"] = (errors["eraDegrees"] + 180) % 360 - 180
        result.append({**record, "reference": {name: ref.mp.nstr(value, 75) for name, value in reference.items()},
                       "signedError": {name: ref.mp.nstr(value, 25) for name, value in errors.items()},
                       "inverseResidualDays": ref.mp.nstr(tt - (ut + dt / 86400), 25)})
    return result


def summary(rows):
    return {name: ref.mp.nstr(max(abs(ref.mp.mpf(row["signedError"][name])) for row in rows), 25)
            for name in rows[0]["signedError"]}


def verify_summary(report):
    if summary(report["rows"]) != report["sampledMaximumAbsoluteError"]:
        raise ValueError("Recorded maxima differ from the comparison rows")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--configuration", choices=["debug", "release"], default="debug")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--recheck", action="store_true", help="Re-execute the reference against recorded native bits")
    args = parser.parse_args()
    if ref.mp.__version__ != "1.3.0":
        raise SystemExit("Install pinned requirements.txt")
    if args.recheck:
        saved = json.loads(args.output.read_text())
        requests = grid()
        if saved["requests"] != requests:
            raise SystemExit("Recorded requests differ from the complete canonical request grid")
        check_hashes(ROOT, saved["sourceSHA256"])
        verify_summary(saved)
        calculated = comparisons(saved["rows"], requests)
        if calculated != saved["rows"]:
            raise SystemExit("Recorded reference is not the current evaluator's output")
        print(f"Re-executed {len(calculated)} reference rows: {args.output}")
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    workspace = ROOT / ".context" / f"solar-numerics-{args.configuration}"
    workspace.mkdir(parents=True, exist_ok=True)
    requests = grid()
    input_path, output_path = workspace / "input.json", workspace / "native.json"
    input_path.write_text(json.dumps(requests, indent=2) + "\n")
    if output_path.exists():
        output_path.unlink()
    command = ["swift", "test", "-c", args.configuration, "--filter", "NativeNumericalProbe.export"]
    build_log = workspace / "build.log"
    with build_log.open("w") as log:
        subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    environment = dict(os.environ, ASTRONOMYKIT_NUMERICS_INPUT=str(input_path), ASTRONOMYKIT_NUMERICS_OUTPUT=str(output_path))
    log_path = workspace / "run.log"
    begin = time.perf_counter()
    with log_path.open("w") as log:
        subprocess.run(["/usr/bin/time", "-l" if platform.system() == "Darwin" else "-v", *command, "--skip-build"], cwd=ROOT, env=environment,
                       stdout=log, stderr=subprocess.STDOUT, check=True)
    seconds = time.perf_counter() - begin
    records = json.loads(output_path.read_text())
    rows = comparisons(records, requests)
    report = {"schemaVersion": 1, "status": "sampled-primitives-only-not-altitude-certificate",
              "configuration": args.configuration, "precisionDecimalDigits": ref.mp.mp.dps,
              "referenceLibrary": "mpmath 1.3.0", "pythonVersion": platform.python_version(), "platform": platform.platform(), "architecture": platform.machine(),
              "swiftVersion": subprocess.check_output(["swift", "--version"], text=True, stderr=subprocess.STDOUT).strip(),
              "gitHead": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
              "sourceSHA256": source_hashes(ROOT, BINDINGS + TOOLS),
              "nativeProcessSecondsIncludingRunner": seconds, "nativeProcessLog": log_path.read_text(),
              "requests": requests, "rows": rows,
              "sampledMaximumAbsoluteError": summary(rows),
              "excluded": ["full altitude", "civil conversion", "apparent/horizon frame transforms", "light-time iteration flips",
                           "continuous arithmetic or libm bounds", "other compilers or architectures"]}
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"rows": len(rows), "maxima": report["sampledMaximumAbsoluteError"]}, indent=2))


if __name__ == "__main__":
    main()
