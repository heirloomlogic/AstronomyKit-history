#!/usr/bin/env python3
"""Record or verify bit-exact migration from generated Swift payloads to resources."""

import argparse
import base64
import hashlib
import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'Scripts/model-resource-migration.json'
RESOURCE_ROOT = ROOT / 'Sources/AstronomyKit/Resources/ModelTables'
METADATA_ONLY = {
    'Sources/AstronomyKit/Engine/Moon/Generated/DE441Full/MoonDE441FullIndex.swift',
    'Sources/AstronomyKit/Engine/Planets/Generated/PlanetPolynomialCoverage.swift',
}


def generated_paths(revision):
    paths = subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', revision], cwd=ROOT, text=True).splitlines()
    prefixes = (
        'Sources/AstronomyKit/Engine/Gravity/Generated/DE441/PlutoDE441',
        'Sources/AstronomyKit/Engine/Gravity/Generated/PlutoBarycenterCoefficients.swift',
        'Sources/AstronomyKit/Engine/Gravity/Generated/PlutoCenterCoefficients.swift',
        'Sources/AstronomyKit/Engine/Gravity/Generated/PlutoSunCoefficients.swift',
        'Sources/AstronomyKit/Engine/Moon/Generated/DE441Full/MoonDE441Full',
        'Sources/AstronomyKit/Engine/Moon/Generated/MoonDE440Coefficients.swift',
        'Sources/AstronomyKit/Engine/Planets/Generated/PlanetPolynomial',
        'Sources/AstronomyKit/Engine/Planets/Generated/Saturn/Saturn',
    )
    return sorted(path for path in paths if path.endswith('.swift') and path.startswith(prefixes))


def resource_name(path):
    name = Path(path).stem
    if name == 'MoonDE440Coefficients':
        return 'moon-de440.bin'
    if name.startswith('MoonDE441Full'):
        return f'moon-de441-full-{name[-3:]}.bin'
    if name.startswith('PlutoDE441'):
        return f'pluto-de441-{name.removeprefix("PlutoDE441").removesuffix("Data").lower()}.bin'
    if name.startswith('Pluto') and name.endswith('Coefficients'):
        return f'pluto-compact-{name.removeprefix("Pluto").removesuffix("Coefficients").lower()}.bin'
    if name.startswith('PlanetPolynomial'):
        return f'planet-polynomial-{name.removeprefix("PlanetPolynomial").lower()}.bin'
    if name.startswith('Saturn') and name.endswith('Data'):
        return f'saturn-{name.removeprefix("Saturn").removesuffix("Data").lower()}.bin'
    raise ValueError(f'unmapped generated payload: {path}')


def old_payload(revision, path):
    source = subprocess.check_output(['git', 'show', f'{revision}:{path}'], cwd=ROOT, text=True)
    pieces = source.split('"""')
    if len(pieces) != 3:
        raise ValueError(f'generated source does not contain one payload: {path}')
    # The former Saturn generator inserted this separator to avoid a source-scanner false positive; its decoder ignored it.
    encoded = ''.join(pieces[1].split()).replace('#', '')
    return base64.b64decode(encoded, validate=True)


def inventory(revision):
    paths = generated_paths(revision)
    if set(paths) & METADATA_ONLY != METADATA_ONLY:
        raise ValueError('metadata-only generated source inventory differs')
    mappings = []
    for path in paths:
        if path in METADATA_ONLY:
            continue
        resource = resource_name(path)
        before = old_payload(revision, path)
        after = (RESOURCE_ROOT / resource).read_bytes()
        if before != after:
            raise ValueError(f'migrated payload differs: {path}')
        digest = hashlib.sha256(before).hexdigest()
        mappings.append({'oldGeneratedSource': path, 'resource': f'Sources/AstronomyKit/Resources/ModelTables/{resource}', 'bytes': len(before), 'sha256': digest})
    resources = sorted(path for path in RESOURCE_ROOT.glob('*.bin'))
    if {Path(row['resource']) for row in mappings} != {path.relative_to(ROOT) for path in resources}:
        raise ValueError('mapped resource inventory differs')
    return paths, mappings


def record(revision):
    paths, mappings = inventory(revision)
    document = {'schemaVersion': 1, 'baseRevision': revision, 'scopedGeneratedSourceCount': len(paths), 'payloadSourceCount': len(mappings), 'resourceCount': len(mappings), 'metadataOnlyGeneratedSources': sorted(METADATA_ONLY), 'mappings': mappings}
    MANIFEST.write_text(json.dumps(document, indent=2, sort_keys=True) + '\n')
    print(f'Recorded {len(mappings)}/{len(paths)} bit-exact generated payload migrations from {revision}')


def check():
    document = json.loads(MANIFEST.read_text())
    paths, mappings = inventory(document['baseRevision'])
    expected = {'schemaVersion': 1, 'baseRevision': document['baseRevision'], 'scopedGeneratedSourceCount': len(paths), 'payloadSourceCount': len(mappings), 'resourceCount': len(mappings), 'metadataOnlyGeneratedSources': sorted(METADATA_ONLY), 'mappings': mappings}
    if document != expected:
        raise SystemExit('model-resource migration manifest differs')
    print(f'Verified {len(mappings)}/{len(paths)} bit-exact generated payload migrations from {document["baseRevision"]}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--check', action='store_true')
    mode.add_argument('--record', metavar='BASE_REVISION')
    args = parser.parse_args()
    if args.record:
        record(subprocess.check_output(['git', 'rev-parse', args.record], cwd=ROOT, text=True).strip())
    else:
        check()


if __name__ == '__main__':
    main()
