#!/usr/bin/env python3
"""Read a generated model-table descriptor and its verified binary resource."""

import hashlib
from pathlib import Path
import re


RESOURCE_DIRECTORY = Path(__file__).resolve().parents[1] / "Sources/AstronomyKit/Resources/ModelTables"
DESCRIPTOR = re.compile(
    r'Engine\.TableResource\(name: "([a-z0-9][a-z0-9-]*)", byteCount: ([0-9][0-9_]*), sha256: "([0-9a-f]{64})"\)'
)


def payloads(source, resource_directory=RESOURCE_DIRECTORY):
    matches = DESCRIPTOR.findall(source)
    if not matches or len(matches) != source.count("Engine.TableResource("):
        raise ValueError("generated model resource descriptor is missing, duplicated, or malformed")
    if len({name for name, _, _ in matches}) != len(matches):
        raise ValueError("generated model resource descriptor names are duplicated")
    result = {}
    for name, encoded_count, expected_digest in matches:
        count = int(encoded_count.replace("_", ""))
        if count <= 0:
            raise ValueError("generated model resource byte count is invalid")
        path = Path(resource_directory) / f"{name}.bin"
        try:
            data = path.read_bytes()
        except OSError as error:
            raise ValueError(f"generated model resource is unreadable: {path}") from error
        if len(data) != count:
            raise ValueError(f"generated model resource byte count differs: {path}")
        if hashlib.sha256(data).hexdigest() != expected_digest:
            raise ValueError(f"generated model resource digest differs: {path}")
        result[name] = data
    return result


def payload(source, resource_directory=RESOURCE_DIRECTORY):
    result = payloads(source, resource_directory)
    if len(result) != 1:
        raise ValueError("generated model resource descriptor is missing, duplicated, or malformed")
    return next(iter(result.values()))
