#!/usr/bin/env python3
"""Capture and verify an external PAL ray-trace reference grid."""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path
import subprocess
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "Scripts/refraction-data/pal-reference.json"
REVISION = "75017db16bb3efe9031e0f01921caa1b9554e922"
SOURCE_URL = f"https://raw.githubusercontent.com/Starlink/pal/{REVISION}"
SOURCE_FILES = {
    "COPYING": ("8ceb4b9ee5adedde47b31e975c1d90c73ad27b6b165a1dcd80c7c545eb65b903", "GPL-3.0-or-later"),
    "COPYING.LESSER": ("da7eabb7bafdf7d3ae5e9f223aa5bdc1eece45ac569dc21b3b037520b4464768", "LGPL-3.0-or-later"),
    "pal.h": ("3647545712aab504259413ea064dfef722cbff7f39eec0eb2c7bc9f0424e5d4d", "LGPL-3.0-or-later"),
    "pal1.h": ("06cc38c6a5d9513564029ad11158d6f681e856c639b0ac11d051d9eadd6fc5c4", "GPL-3.0-or-later"),
    "palmac.h": ("2722df19f737134681650a5cc761447affd8fb8f0a82ae75b820302c0de7e7d0", "LGPL-3.0-or-later"),
    "palRefro.c": ("f401e72dd8e32d0f2185fff215f8e5ebede4d679f75ce34d3a7580369988b294", "GPL-3.0-or-later"),
    "pal1Atmt.c": ("63918188d423bbf3bb38db0f00fb9baa442496596122c7c23a5c5dfc6e1c40a9", "GPL-3.0-or-later"),
    "pal1Atms.c": ("639f921b87cbc05b2e770d2ead45343560fef7dbe98608d1a3bec16141ef5ec4", "GPL-3.0-or-later"),
    "palDrange.c": ("48388bc5af02f3c4184f1f3be0c69e80bde75a844b2f32eb8b79962361140180", "LGPL-3.0-or-later"),
}
OWNERS = [
    "Sources/AstronomyKit/Coordinates.swift",
    "Sources/AstronomyKit/Engine/Orientation/EngineRefraction.swift",
    "Tests/AstronomyKitTests/WeatherRefractionTests.swift",
    "Scripts/capture-pal-refraction.py",
    "Scripts/test_capture_pal_refraction.py",
]
PRESSURES = [300.0, 600.0, 800.0, 1010.0, 1100.0]
TEMPERATURES = [-40.0, 0.0, 10.0, 40.0]
ALTITUDES = [0.0, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 45.0, 80.0]
CONFIGURATION = {
    "observerHeightMeters": 0.0,
    "relativeHumidity": 0.5,
    "wavelengthMicrometers": 0.55,
    "latitudeDegrees": 45.0,
    "troposphericLapseRateKelvinPerMeter": 0.0065,
    "integrationToleranceRadians": 1e-12,
}
OFFICIAL_REGRESSIONS = [
    {
        "arguments": [1.4, 3456.7, 280.0, 678.9, 0.9, 0.55, -0.3, 0.006, 1e-9],
        "expectedRadians": 0.00106715763018568,
    },
    {
        "arguments": [1.4, 3456.7, 280.0, 678.9, 0.9, 1000.0, -0.3, 0.006, 1e-9],
        "expectedRadians": 0.001296416185295403,
    },
]
DRIVER = r'''#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include "pal.h"
int main(int argc, char **argv) {
    if (argc != 10) return 64;
    double a[9];
    for (int i = 0; i < 9; i++) {
        errno = 0;
        char *end = NULL;
        a[i] = strtod(argv[i + 1], &end);
        if (errno || !end || *end) return 65;
    }
    double result = 0;
    palRefro(a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7], a[8], &result);
    printf("%.17g\n", result);
    return 0;
}
'''


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_hashes() -> dict[str, str]:
    return {path: digest(ROOT / path) for path in OWNERS}


def prepare_sources(cache: Path) -> None:
    cache.mkdir(parents=True, exist_ok=True)
    for name, (expected, _) in SOURCE_FILES.items():
        path = cache / name
        if not path.exists() or digest(path) != expected:
            with urllib.request.urlopen(f"{SOURCE_URL}/{name}") as response:
                data = response.read()
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError(f"PAL source digest mismatch: {name}")
            path.write_bytes(data)
        if digest(path) != expected:
            raise ValueError(f"PAL cache digest mismatch: {name}")


def compile_oracle(cache: Path, work: Path) -> Path:
    driver = work / "driver.c"
    executable = work / "pal-refro"
    driver.write_text(DRIVER)
    subprocess.run(
        [
            "cc", "-O2", "-I", str(cache), str(driver),
            *(str(cache / name) for name in ["palRefro.c", "pal1Atmt.c", "pal1Atms.c", "palDrange.c"]),
            "-lm", "-o", str(executable),
        ],
        check=True,
    )
    return executable


def evaluate(executable: Path, arguments: list[float]) -> float:
    output = subprocess.check_output([str(executable), *(format(value, ".17g") for value in arguments)], text=True)
    result = float(output)
    if not math.isfinite(result):
        raise ValueError("PAL returned a nonfinite refraction")
    return result


def capture_archive(cache: Path) -> dict:
    prepare_sources(cache)
    with tempfile.TemporaryDirectory(prefix="pal-refraction-") as temporary:
        executable = compile_oracle(cache, Path(temporary))
        regressions = []
        for fixture in OFFICIAL_REGRESSIONS:
            actual = evaluate(executable, fixture["arguments"])
            if abs(actual - fixture["expectedRadians"]) > 1e-12:
                raise ValueError("PAL official regression mismatch")
            regressions.append({**fixture, "actualRadians": actual})

        rows = []
        for pressure, temperature, altitude in itertools.product(PRESSURES, TEMPERATURES, ALTITUDES):
            observed_zenith_distance = math.radians(90 - altitude)
            arguments = [
                observed_zenith_distance,
                CONFIGURATION["observerHeightMeters"],
                temperature + 273.15,
                pressure,
                CONFIGURATION["relativeHumidity"],
                CONFIGURATION["wavelengthMicrometers"],
                math.radians(CONFIGURATION["latitudeDegrees"]),
                CONFIGURATION["troposphericLapseRateKelvinPerMeter"],
                CONFIGURATION["integrationToleranceRadians"],
            ]
            rows.append(
                {
                    "apparentAltitudeDegrees": altitude,
                    "pressureMillibars": pressure,
                    "temperatureCelsius": temperature,
                    "refractionDegrees": math.degrees(evaluate(executable, arguments)),
                }
            )

    archive = {
        "schemaVersion": 1,
        "source": {
            "name": "Starlink PAL palRefro",
            "repository": "https://github.com/Starlink/pal",
            "revision": REVISION,
            "semantics": "observed zenith distance to vacuum-minus-observed zenith distance",
            "files": {
                name: {"sha256": sha, "license": license_name}
                for name, (sha, license_name) in SOURCE_FILES.items()
            },
        },
        "configuration": CONFIGURATION,
        "grid": {
            "apparentAltitudeDegrees": ALTITUDES,
            "pressureMillibars": PRESSURES,
            "temperatureCelsius": TEMPERATURES,
        },
        "officialRegressions": regressions,
        "rows": rows,
        "sourceSHA256": source_hashes(),
    }
    validate_archive(archive)
    return archive


def validate_archive(archive: dict) -> None:
    if archive.get("schemaVersion") != 1:
        raise ValueError("unexpected schema version")
    source = archive.get("source", {})
    if source.get("revision") != REVISION or source.get("repository") != "https://github.com/Starlink/pal":
        raise ValueError("unexpected PAL source")
    expected_files = {
        name: {"sha256": sha, "license": license_name}
        for name, (sha, license_name) in SOURCE_FILES.items()
    }
    if source.get("files") != expected_files:
        raise ValueError("PAL source inventory mismatch")
    if archive.get("configuration") != CONFIGURATION:
        raise ValueError("oracle configuration mismatch")
    expected_grid = {
        "apparentAltitudeDegrees": ALTITUDES,
        "pressureMillibars": PRESSURES,
        "temperatureCelsius": TEMPERATURES,
    }
    if archive.get("grid") != expected_grid:
        raise ValueError("reference grid mismatch")

    regressions = archive.get("officialRegressions", [])
    if len(regressions) != len(OFFICIAL_REGRESSIONS):
        raise ValueError("official regression inventory mismatch")
    for expected, actual in zip(OFFICIAL_REGRESSIONS, regressions):
        if actual.get("arguments") != expected["arguments"] or actual.get("expectedRadians") != expected["expectedRadians"]:
            raise ValueError("official regression identity mismatch")
        if abs(actual.get("actualRadians", math.inf) - expected["expectedRadians"]) > 1e-12:
            raise ValueError("official regression value mismatch")

    expected_identities = set(itertools.product(PRESSURES, TEMPERATURES, ALTITUDES))
    rows = archive.get("rows", [])
    identities = {
        (row.get("pressureMillibars"), row.get("temperatureCelsius"), row.get("apparentAltitudeDegrees"))
        for row in rows
    }
    if len(rows) != len(expected_identities) or identities != expected_identities:
        raise ValueError("reference row inventory mismatch")
    if any(not math.isfinite(row.get("refractionDegrees", math.nan)) for row in rows):
        raise ValueError("nonfinite reference result")
    if archive.get("sourceSHA256") != source_hashes():
        raise ValueError("bound source digest mismatch")


def write_archive(archive: dict) -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(archive, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile("w", dir=OUTPUT.parent, delete=False) as staged:
        staged.write(text)
        staged_path = Path(staged.name)
    staged_path.replace(OUTPUT)


def main() -> None:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--capture", action="store_true")
    action.add_argument("--check", action="store_true")
    parser.add_argument("--cache", type=Path, default=ROOT / ".build/pal-refraction-source")
    args = parser.parse_args()
    if args.capture:
        write_archive(capture_archive(args.cache))
        print(f"captured {len(PRESSURES) * len(TEMPERATURES) * len(ALTITUDES)} PAL rows in {OUTPUT}")
        return
    validate_archive(json.loads(OUTPUT.read_text()))
    print(f"verified {OUTPUT}")


if __name__ == "__main__":
    main()
