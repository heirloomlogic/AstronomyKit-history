#!/usr/bin/env python3
"""Capture the canonical DE421 byte ranges used by the issue 275 replay."""

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DESTINATION = HERE / "sources" / "de421"
SOURCE_URL = "https://naif.jpl.nasa.gov/pub/naif/generic_kernels/spk/planets/a_old_versions/de421.bsp"
SOURCE_BYTES = 16_790_528
SOURCE_SHA256 = "08b20db2ae22488650641c5a9033e5bfda4b1c4b440cfeaf20f621cfa18ecdb3"

SPEC = importlib.util.spec_from_file_location("de421_replay", HERE / "de421_replay.py")
REPLAY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPLAY)


class FileRangeReader:
    def __init__(self, path):
        self.path = Path(path)
        self.ranges = {}

    def read(self, start, count):
        if start < 0 or count <= 0 or start + count > self.path.stat().st_size:
            raise REPLAY.EvidenceError("requested DE421 range is invalid")
        key = (start, count)
        if key not in self.ranges:
            with self.path.open("rb") as source:
                source.seek(start)
                data = source.read(count)
            if len(data) != count:
                raise REPLAY.EvidenceError("DE421 source returned a short range")
            self.ranges[key] = data
        return self.ranges[key]


def source_sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def exercise_ranges(reader):
    segments = REPLAY.read_segments(reader)
    delta_t = 75 / REPLAY.SECONDS_PER_DAY
    epochs = [
        REPLAY.TARGET_JD,
        REPLAY.gregorian_jd(2026, 8, 28, 4, 13, 0) + delta_t,
        REPLAY.gregorian_jd(2026, 8, 28, 4, 14, 4) + delta_t,
        REPLAY.minimum_epoch(reader, segments, "axisDistanceKilometers"),
        REPLAY.minimum_epoch(reader, segments, "separationArcseconds"),
    ]
    for epoch in epochs:
        REPLAY.de421_geocentric(reader, segments, epoch)
    for offset in (-0.002, 0.002):
        REPLAY.de421_geocentric(reader, segments, epochs[2] + offset / REPLAY.SECONDS_PER_DAY)


def manifest(reader):
    rows = []
    for (start, count), data in sorted(reader.ranges.items()):
        end = start + count - 1
        rows.append(
            {
                "end": end,
                "path": f"Scripts/svs-lunar-obscuration/sources/de421/{start}-{end}.bin",
                "sha256": hashlib.sha256(data).hexdigest(),
                "start": start,
            }
        )
    return {
        "ranges": rows,
        "schemaVersion": 1,
        "source": {"bytes": SOURCE_BYTES, "sha256": SOURCE_SHA256, "url": SOURCE_URL},
    }


def build(path):
    source = Path(path)
    if source.stat().st_size != SOURCE_BYTES:
        raise REPLAY.EvidenceError(f"DE421 source length differs: {source.stat().st_size}")
    digest = source_sha256(source)
    if digest != SOURCE_SHA256:
        raise REPLAY.EvidenceError(f"DE421 source SHA-256 differs: {digest}")
    reader = FileRangeReader(source)
    exercise_ranges(reader)
    result = manifest(reader)
    if len(result["ranges"]) != len({(row["start"], row["end"]) for row in result["ranges"]}):
        raise REPLAY.EvidenceError("DE421 capture produced duplicate ranges")
    return reader, result


def write_capture(reader, result):
    with tempfile.TemporaryDirectory(dir=DESTINATION.parent) as temporary:
        stage = Path(temporary) / "de421"
        stage.mkdir()
        for row in result["ranges"]:
            data = reader.ranges[(row["start"], row["end"] - row["start"] + 1)]
            (stage / f"{row['start']}-{row['end']}.bin").write_bytes(data)
        (stage / "manifest.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        for row in result["ranges"]:
            path = stage / f"{row['start']}-{row['end']}.bin"
            if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
                raise REPLAY.EvidenceError("staged DE421 range verification failed")
        backup = DESTINATION.with_name("de421.backup")
        if backup.exists():
            shutil.rmtree(backup)
        if DESTINATION.exists():
            DESTINATION.rename(backup)
        try:
            stage.rename(DESTINATION)
        except Exception:
            if backup.exists() and not DESTINATION.exists():
                backup.rename(DESTINATION)
            raise
        if backup.exists():
            shutil.rmtree(backup)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--capture", metavar="DE421_BSP")
    mode.add_argument("--check-source", metavar="DE421_BSP")
    arguments = parser.parse_args()
    path = arguments.capture or arguments.check_source
    reader, result = build(path)
    if arguments.capture:
        write_capture(reader, result)
        print(DESTINATION.relative_to(ROOT))
        return
    expected = json.loads((DESTINATION / "manifest.json").read_text())
    if result != expected:
        raise SystemExit("committed DE421 range manifest differs from the canonical kernel")
    for row in expected["ranges"]:
        path = ROOT / row["path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]:
            raise SystemExit(f"committed DE421 range differs: {row['path']}")
    print(f"canonical DE421 source and {len(expected['ranges'])} committed ranges verified")


if __name__ == "__main__":
    main()
