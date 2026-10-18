#!/usr/bin/env python3
"""Record full-precision Moon integration captures with complete source ownership."""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DEPENDENCY_SPEC = importlib.util.spec_from_file_location('moon_full_dependencies', ROOT / 'Scripts/evidence_dependencies.py')
dependencies = importlib.util.module_from_spec(DEPENDENCY_SPEC)
DEPENDENCY_SPEC.loader.exec_module(dependencies)
OUTPUT = ROOT / 'Scripts/moon-data/de441-full-integration-evidence.json'
SPEC = importlib.util.spec_from_file_location('moon_events', ROOT / 'Scripts/generate-moon-events.py')
events = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(events)


def source_paths():
    return list(dependencies.paths('moon-full-integration'))


def finite(value):
    if isinstance(value, dict): return all(finite(v) for v in value.values())
    if isinstance(value, list): return all(finite(v) for v in value)
    if isinstance(value, (int, float)): return math.isfinite(value)
    return isinstance(value, str)


def validate(captures):
    expected = {f'{kind}-{configuration}' for kind in ('differential', 'boundaries', 'horizons') for configuration in ('debug', 'release')} | {'measurement-release'}
    if not isinstance(captures, dict) or set(captures) != expected or not finite(captures):
        raise ValueError('Capture inventory or finite values differ')
    for configuration in ('debug', 'release'):
        d = captures['differential-' + configuration]
        if d['samples'] != 1365 or d['integratedSamples'] != 1360:
            raise ValueError('Direct source sample inventory differs')
        limits = {'maximumPositionKm': 1e-8, 'maximumRateKmPerTDBDay': 1e-8,
                  'maximumIntegratedRateKmPerTTDay': 39.085, 'maximumIntegratedAngleArcminutes': 1,
                  'maximumIntegratedDistanceKm': 28.689, 'maximumLongitudeArcminutes': 1,
                  'maximumLatitudeArcminutes': 1}
        if any(not 0 <= d[key] <= limit for key, limit in limits.items()):
            raise ValueError('Direct source comparison exceeds its stated limit')
        b = captures['boundaries-' + configuration]
        if b['boundaries'] != 730501 or any(not 0 <= b[key] < 1e-12 for key in ('maximumPositionJumpAU', 'maximumRateJumpAUPerTDBDay')):
            raise ValueError('Source seam inventory or bound differs')
        h = captures['horizons-' + configuration]
        archive = json.loads((ROOT / 'Tests/AstronomyKitTests/Fixtures/IndependentReferences/reference-fixtures.json').read_bytes())
        dates = {row['julianDateTDB'] for row in archive['vectors'] if row['body'] == 'moon'}
        if len(h) != 30 or len(dates) != 30 or {row['julianDateTDB'] for row in h} != dates:
            raise ValueError('Horizons sample inventory differs')
        for row in h:
            if not 0 <= row['angleArcminutes'] <= 1 or not 0 <= row['distanceKm'] <= 28.689:
                raise ValueError('Existing Horizons acceptance failed')
    m = captures['measurement-release']
    if m['evaluationsPerWorkload'] != 20000 or set(m['seconds']) != {'outer', 'central'}:
        raise ValueError('Resource workload differs')
    if m['coldSeconds'] < 0 or any(v < 0 for v in m['seconds'].values()):
        raise ValueError('Negative resource duration')


def record(directory):
    names = [f'{kind}-{config}' for kind in ('differential', 'boundaries', 'horizons') for config in ('debug', 'release')] + ['measurement-release']
    raw = {name: (directory / (name + '.json')).read_bytes() for name in names}
    captures = {name: json.loads(data) for name, data in raw.items()}
    validate(captures)
    return {'schemaVersion': 1, 'runtimeBaseRevision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
            'sourceSHA256': dependencies.source_hashes('moon-full-integration'),
            'rawSHA256': {name: hashlib.sha256(data).hexdigest() for name, data in raw.items()}, 'captures': captures,
            'scope': 'Complete derived binary64 coefficients; sampled independent state and Horizons checks; exhaustive source-seam jumps. Numerical source agreement is distinct from physical accuracy. Resource observations are single-host measurements.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', type=Path)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    if args.capture:
        data = record(args.capture)
        OUTPUT.write_text(json.dumps(data, indent=2, sort_keys=True, allow_nan=False) + '\n')
    elif args.check:
        data = json.loads(OUTPUT.read_bytes())
        validate(data['captures'])
        events.check_source_hashes(OUTPUT, required_sources=source_paths())
    else:
        parser.error('choose --capture DIRECTORY or --check')
    print('Verified full-precision Moon integration evidence')


if __name__ == '__main__':
    main()
