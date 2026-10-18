#!/usr/bin/env python3
"""Shared deterministic writer and verifier for generated model-table resources."""

import hashlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESOURCE_DIRECTORY = ROOT / 'Sources/AstronomyKit/Resources/ModelTables'


def descriptor(name, data):
    if not data:
        raise ValueError(f'generated resource is empty: {name}')
    return descriptor_from_digest(name, len(data), hashlib.sha256(data).hexdigest())


def descriptor_from_digest(name, byte_count, sha256):
    if not name or byte_count <= 0 or len(sha256) != 64:
        raise ValueError(f'generated resource descriptor is malformed: {name}')
    return f'Engine.TableResource(name: "{name}", byteCount: {byte_count:_}, sha256: "{sha256}")'


def publish(expected, prefixes, check):
    if not expected or any(not name.endswith('.bin') or not data for name, data in expected.items()):
        raise ValueError('generated resource set is malformed')
    owned = {
        path.name for prefix in prefixes for path in RESOURCE_DIRECTORY.glob(prefix + '*.bin')
    } if RESOURCE_DIRECTORY.exists() else set()
    if check:
        if owned != set(expected):
            raise SystemExit(f'generated resource file set differs: expected {sorted(expected)!r}, found {sorted(owned)!r}')
        for name, data in expected.items():
            if (RESOURCE_DIRECTORY / name).read_bytes() != data:
                raise SystemExit(f'generated resource differs: {name}')
        return
    RESOURCE_DIRECTORY.mkdir(parents=True, exist_ok=True)
    for name, data in expected.items():
        path = RESOURCE_DIRECTORY / name
        if not path.exists() or path.read_bytes() != data:
            path.write_bytes(data)
    for name in owned - set(expected):
        (RESOURCE_DIRECTORY / name).unlink()
