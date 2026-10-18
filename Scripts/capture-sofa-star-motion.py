#!/usr/bin/env python3
"""Capture and verify Gaia DR3 catalog motion propagated by pinned IAU SOFA."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import subprocess
import tarfile
import tempfile
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "Scripts/star-motion-data"
CATALOG = DATA / "gaia-dr3.csv"
QUERY = DATA / "gaia-dr3.query.json"
OUTPUT = DATA / "sofa-reference.json"
SOFA_ARCHIVE = ROOT / "Scripts/reference-data/sources/sofa/sofa_c-20231011.tar.gz"
SOFA_SHA256 = "d9c10833cae8b4d9361a0ffda31ec361fd1262362025bec4d4e51a880150ace2"
TARGET_YEARS = [1991.25, 2016.0, 2050.0, 2100.0]
EXPECTED_SOURCE_IDS = ["4472832130942575872", "5853498713190525696"]
SOFA_SOURCES = [
    "anp.c", "cp.c", "pdp.c", "pm.c", "pmp.c", "pmsafe.c", "pn.c", "ppp.c", "ppsp.c", "pv2s.c", "pvstar.c", "pvu.c", "pxp.c", "s2c.c", "s2pv.c", "sepp.c", "seps.c", "starpm.c", "starpv.c", "sxp.c", "tdbtcb.c", "zp.c",
]
OWNERS = [
    "Sources/AstronomyKit/StarCatalogMotion.swift",
    "Sources/AstronomyKit/FixedStar.swift",
    "Sources/AstronomyKit/Engine/Stars/EngineStar.swift",
    "Sources/AstronomyKit/Engine/Stars/EngineStarCatalogPropagation.swift",
    "Tests/AstronomyKitTests/FixedStarCatalogMotionTests.swift",
    "Tests/AstronomyKitTests/Engine/Stars/EngineStarCatalogMotionTests.swift",
    "Scripts/capture-sofa-star-motion.py",
    "Scripts/test_capture_sofa_star_motion.py",
    "Scripts/sofa-star-motion-reference.c",
    "Scripts/star-motion-data/gaia-dr3.csv",
    "Scripts/star-motion-data/gaia-dr3.query.json",
    "Scripts/star-motion-data/README.md",
    "Sources/AstronomyKit/Documentation.docc/AdvancedFeatures.md",
    "Sources/AstronomyKit/Documentation.docc/CelestialPositions.md",
    "NATIVE_ENGINE.md",
    "THIRD_PARTY_NOTICES",
]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_hashes() -> dict[str, str]:
    return {path: digest(ROOT / path) for path in OWNERS}


def query_parameters(recipe: dict) -> dict[str, str]:
    return {
        "REQUEST": "doQuery",
        "LANG": recipe["language"],
        "FORMAT": recipe["format"],
        "QUERY": recipe["query"],
    }


def download_catalog() -> bytes:
    recipe = json.loads(QUERY.read_text())
    url = recipe["endpoint"] + "?" + urllib.parse.urlencode(query_parameters(recipe))
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def validate_catalog_bytes(data: bytes) -> list[dict[str, str]]:
    recipe = json.loads(QUERY.read_text())
    if hashlib.sha256(data).hexdigest() != recipe["responseSHA256"]:
        raise ValueError("Gaia response digest mismatch")
    rows = list(csv.DictReader(io.StringIO(data.decode())))
    fields = ["source_id", "ref_epoch", "ra", "dec", "parallax", "pmra", "pmdec", "radial_velocity"]
    if not rows or list(rows[0]) != fields:
        raise ValueError("Gaia column inventory mismatch")
    if [row["source_id"] for row in rows] != EXPECTED_SOURCE_IDS:
        raise ValueError("Gaia row identity or order mismatch")
    for row in rows:
        try:
            valid = all(math.isfinite(float(row[field])) for field in fields[1:])
        except (TypeError, ValueError):
            valid = False
        if not valid:
            raise ValueError("Gaia row contains a missing or nonfinite value")
    return rows


def compile_oracle(work: Path) -> Path:
    if digest(SOFA_ARCHIVE) != SOFA_SHA256:
        raise ValueError("SOFA archive digest mismatch")
    source = work / "sofa"
    source.mkdir()
    with tarfile.open(SOFA_ARCHIVE) as archive:
        prefix = "sofa/20231011/c/src/"
        names = {"sofa.h", "sofam.h", *SOFA_SOURCES}
        members = [member for member in archive.getmembers() if member.name.startswith(prefix) and Path(member.name).name in names]
        for member in members:
            member.name = Path(member.name).name
            archive.extract(member, source)
    executable = work / "sofa-star-motion"
    compilation = subprocess.run(
        [
            "cc", "-std=c99", "-O2", f"-I{source}", str(ROOT / "Scripts/sofa-star-motion-reference.c"),
            *(str(source / name) for name in SOFA_SOURCES), "-lm", "-o", str(executable),
        ],
        capture_output=True,
        text=True,
    )
    if compilation.returncode != 0:
        raise RuntimeError(f"SOFA star-motion compilation failed: {compilation.stderr.strip()}")
    return executable


def evaluate(executable: Path, row: dict[str, str], target: float, clock: str = "full") -> dict[str, float]:
    arguments = [row[name] for name in ["ra", "dec", "parallax", "pmra", "pmdec", "radial_velocity", "ref_epoch"]]
    completed = subprocess.run([str(executable), *arguments, format(target, ".17g"), clock], check=True, capture_output=True, text=True)
    values = [float(value) for value in completed.stdout.split()]
    if len(values) != 6 or any(not math.isfinite(value) for value in values):
        raise ValueError("SOFA returned an invalid result")
    return dict(zip(["rightAscensionRadians", "declinationRadians", "rightAscensionRateRadiansPerJulianYear", "declinationRateRadiansPerJulianYear", "parallaxArcseconds", "radialVelocityKilometersPerSecond"], values))


def angular_separation(left: dict[str, float], right: dict[str, float]) -> float:
    ra1, dec1 = left["rightAscensionRadians"], left["declinationRadians"]
    ra2, dec2 = right["rightAscensionRadians"], right["declinationRadians"]
    first = (math.cos(dec1) * math.cos(ra1), math.cos(dec1) * math.sin(ra1), math.sin(dec1))
    second = (math.cos(dec2) * math.cos(ra2), math.cos(dec2) * math.sin(ra2), math.sin(dec2))
    cross = (first[1] * second[2] - first[2] * second[1], first[2] * second[0] - first[0] * second[2], first[0] * second[1] - first[1] * second[0])
    return math.atan2(math.sqrt(sum(value * value for value in cross)), sum(a * b for a, b in zip(first, second)))


def capture_archive() -> dict:
    catalog_rows = validate_catalog_bytes(CATALOG.read_bytes())
    with tempfile.TemporaryDirectory(prefix="sofa-star-motion-") as temporary:
        executable = compile_oracle(Path(temporary))
        rows = []
        comparisons = []
        for catalog in catalog_rows:
            for target in TARGET_YEARS:
                rows.append({"sourceID": catalog["source_id"], "targetTDBJulianYear": target, **evaluate(executable, catalog, target)})
            full = evaluate(executable, catalog, 2050.0)
            naive = evaluate(executable, catalog, 2050.0, "naive")
            comparisons.append({"sourceID": catalog["source_id"], "targetTDBJulianYear": 2050.0, "fullMinusNaiveMicroarcseconds": angular_separation(full, naive) * 180 / math.pi * 3_600_000_000})
    archive = {
        "schemaVersion": 1,
        "catalog": {
            "name": "Gaia Data Release 3 gaia_source",
            "endpoint": json.loads(QUERY.read_text())["endpoint"],
            "querySHA256": digest(QUERY),
            "responseSHA256": digest(CATALOG),
            "epochTimeScale": "TCB",
            "frame": "barycentric ICRS",
            "properMotionConvention": "pmra = dRA/dt*cos(dec), pmdec = dDec/dt, milliarcseconds per Julian year",
            "radialVelocityConvention": "published barycentric spectroscopic radial_velocity in kilometers per second, positive receding",
            "credit": "ESA/Gaia/DPAC; Gaia DR3 documentation credit and citation instructions",
            "rows": catalog_rows,
        },
        "oracle": {
            "name": "IAU SOFA pmsafe, starpm, and tdbtcb",
            "release": "2023-10-11",
            "archiveSHA256": SOFA_SHA256,
            "recipeSHA256": digest(ROOT / "Scripts/sofa-star-motion-reference.c"),
            "targetTDBJulianYears": TARGET_YEARS,
        },
        "rows": rows,
        "clockComparisons": comparisons,
        "sourceSHA256": source_hashes(),
    }
    validate_archive(archive)
    return archive


def validate_archive(archive: dict) -> None:
    if archive.get("schemaVersion") != 1:
        raise ValueError("unexpected schema version")
    catalog = archive.get("catalog", {})
    if catalog.get("responseSHA256") != digest(CATALOG) or catalog.get("querySHA256") != digest(QUERY):
        raise ValueError("Gaia provenance mismatch")
    catalog_rows = validate_catalog_bytes(CATALOG.read_bytes())
    if catalog.get("rows") != catalog_rows:
        raise ValueError("Gaia source rows mismatch")
    oracle = archive.get("oracle", {})
    if oracle.get("archiveSHA256") != SOFA_SHA256 or oracle.get("recipeSHA256") != digest(ROOT / "Scripts/sofa-star-motion-reference.c"):
        raise ValueError("SOFA provenance mismatch")
    expected = {(source_id, year) for source_id in EXPECTED_SOURCE_IDS for year in TARGET_YEARS}
    rows = archive.get("rows", [])
    identities = {(str(row.get("sourceID")), row.get("targetTDBJulianYear")) for row in rows}
    if len(rows) != len(expected) or identities != expected:
        raise ValueError("SOFA result inventory mismatch")
    numeric = [name for name in rows[0] if name not in {"sourceID"}]
    if any(not isinstance(row.get(name), (int, float)) or isinstance(row.get(name), bool) or not math.isfinite(row[name]) for row in rows for name in numeric):
        raise ValueError("SOFA result contains a missing or nonfinite value")
    comparisons = archive.get("clockComparisons", [])
    if [str(row.get("sourceID")) for row in comparisons] != EXPECTED_SOURCE_IDS or any(not math.isfinite(row.get("fullMinusNaiveMicroarcseconds", math.nan)) or row["fullMinusNaiveMicroarcseconds"] <= 0 for row in comparisons):
        raise ValueError("clock comparison inventory mismatch")
    if archive.get("sourceSHA256") != source_hashes():
        raise ValueError("bound source digest mismatch")


def write_archive(archive: dict) -> None:
    text = json.dumps(archive, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile("w", dir=DATA, delete=False) as staged:
        staged.write(text)
        path = Path(staged.name)
    path.replace(OUTPUT)


def refresh_catalog() -> None:
    data = download_catalog()
    validate_catalog_bytes(data)
    with tempfile.NamedTemporaryFile("wb", dir=DATA, delete=False) as staged:
        staged.write(data)
        path = Path(staged.name)
    path.replace(CATALOG)


def main() -> None:
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--capture", action="store_true")
    action.add_argument("--check", action="store_true")
    action.add_argument("--refresh", action="store_true")
    args = parser.parse_args()
    if args.refresh:
        refresh_catalog()
        print(f"refreshed {CATALOG}")
    elif args.capture:
        write_archive(capture_archive())
        print(f"captured {len(EXPECTED_SOURCE_IDS) * len(TARGET_YEARS)} SOFA rows in {OUTPUT}")
    else:
        validate_archive(json.loads(OUTPUT.read_text()))
        print(f"verified {OUTPUT}")


if __name__ == "__main__":
    main()
