#!/usr/bin/env python3
"""Capture and independently replay the archived Galilean-moon residuals."""
import argparse
import csv
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DATA = 'Scripts/jupiter-moon-data'
OUTPUT = ROOT / DATA / 'residual-evidence.json'
FIXTURE = 'Tests/AstronomyKitTests/Fixtures/IndependentReferences/reference-fixtures.json'
MOONS = {'io': 501, 'europa': 502, 'ganymede': 503, 'callisto': 504}
AU_KM = 149597870.7
DOMAIN = (2426545.0, 2476545.0)
EPOCHS = [2415020.5, 2451544.5, 2488069.5]
DOMAIN_EPOCHS = [DOMAIN[0] - 1] + [DOMAIN[0] + i * 2500 for i in range(21)] + [DOMAIN[1] + 1]
dependency_spec = importlib.util.spec_from_file_location('galilean_dependencies', ROOT / 'Scripts/evidence_dependencies.py')
dependencies = importlib.util.module_from_spec(dependency_spec)
dependency_spec.loader.exec_module(dependencies)


def encoded(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n').encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def archive_paths():
    return [f'Scripts/reference-data/sources/horizons/{body}{suffix}.{extension}'
            for body in MOONS for suffix in ('-vector', '-domain-vector') for extension in ('json', 'query.json')]


REPLAY_OWNERS = {'Scripts/galilean-residuals.py', 'Scripts/test_galilean_residuals.py'}


def source_paths():
    return list(dependencies.paths('galilean-residuals', root=ROOT))


def source_hashes():
    return {path: digest((ROOT / path).read_bytes()) for path in source_paths()}


def check_bindings(bindings):
    # The replay owners are this script and its tests; editing them changes the replay, not the capture.
    current = source_hashes()
    if set(bindings) != set(current) or any(bindings[p] != current[p] for p in current if p not in REPLAY_OWNERS):
        raise ValueError('Source binding coverage or digest differs')


def references(root=ROOT):
    result = []
    for body, target in MOONS.items():
        for suffix, dates in [('-vector', EPOCHS), ('-domain-vector', DOMAIN_EPOCHS)]:
            path = root / f'Scripts/reference-data/sources/horizons/{body}{suffix}.json'
            raw = path.read_bytes()
            query = json.loads(path.with_suffix('.query.json').read_bytes())
            expected = {k: "'" + v + "'" for k, v in dict(COMMAND=str(target), OBJ_DATA='NO', MAKE_EPHEM='YES',
                        EPHEM_TYPE='VECTORS', CENTER='500@599', TLIST=','.join(str(v) for v in dates),
                        REF_SYSTEM='ICRF', REF_PLANE='FRAME', OUT_UNITS='AU-D', VEC_TABLE='2',
                        VEC_CORR='NONE', CSV_FORMAT='YES').items()}
            expected['_responseSHA256'] = digest(raw)
            if query != expected:
                raise ValueError('Horizons recipe or response digest differs: ' + str(path))
            document = json.loads(raw)
            text = document['result']
            headers = dict(line.split(':', 1) for line in text.split('$$SOE')[0].splitlines() if ':' in line)
            headers = {k.strip(): v.strip() for k, v in headers.items()}
            for key, value in [('Target body name', f'{body.capitalize()} ({target})'),
                               ('Center body name', 'Jupiter (599)')]:
                if headers.get(key, '').split('{')[0].strip() != value:
                    raise ValueError('Horizons target or center differs')
            for key, value in [('Center-site name', 'BODY CENTER'), ('Output units', 'AU-D'),
                               ('Output type', 'GEOMETRIC cartesian states'), ('Reference frame', 'ICRF'),
                               ('Output format', '2 (position and velocity)')]:
                if headers.get(key) != value:
                    raise ValueError('Horizons coordinate convention differs')
            header = next((line for line in text.splitlines() if line.strip().startswith('JDTDB,')), '')
            if [v.strip() for v in next(csv.reader([header]))] != ['JDTDB', 'Calendar Date (TDB)', 'X', 'Y', 'Z', 'VX', 'VY', 'VZ', '']:
                raise ValueError('Horizons clock or columns differ')
            rows = list(csv.reader(text.split('$$SOE\n')[1].split('$$EOE')[0].splitlines()))
            if len(rows) != len(dates):
                raise ValueError('Horizons record inventory differs')
            for date, row in zip(dates, rows):
                if len(row) != 9 or float(row[0]) != date:
                    raise ValueError('Horizons epoch or row layout differs')
                position, velocity = [float(v) for v in row[2:5]], [float(v) for v in row[5:8]]
                vector(position); vector(velocity)
                result.append(dict(body=body, origin='jupiter', julianDateTDB=date,
                                   tdb=row[1].strip().removeprefix('A.D. '), positionAU=position,
                                   velocityAUPerDay=velocity, relativeTolerance=9e-4 if DOMAIN[0] <= date <= DOMAIN[1] else None,
                                   sanityToleranceAU=None))
    archive = json.loads((root / FIXTURE).read_bytes())['vectors']
    fixture = [r for body in MOONS for r in archive if r['origin'] == 'jupiter' and r['body'] == body]
    if sum(r['origin'] == 'jupiter' for r in archive) != 104:
        raise ValueError('Galilean fixture contains unexpected bodies')
    if fixture != result or len(result) != 104:
        raise ValueError('Galilean fixture projection or inventory differs')
    return result


def vector(value):
    if not isinstance(value, list) or len(value) != 3 or any(type(v) not in (int, float) or not math.isfinite(v) for v in value):
        raise ValueError('Expected a finite three-component vector')
    return value


def eqj(value):
    # Independent row-matrix replay of the published IAU 2006 J2000 bias angles.
    r = [[1., 0., 0.], [0., 1., 0.], [0., 0., 1.]]
    arcsecond = math.pi / 648000
    for axis, angle in [('z', -0.052928), ('x', 84381.412819), ('z', 0.041775), ('x', -84381.406)]:
        c, s = math.cos(angle * arcsecond), math.sin(angle * arcsecond)
        a, b = (0, 1) if axis == 'z' else (1, 2)
        first, second = r[a], r[b]
        r[a] = [c * x + s * y for x, y in zip(first, second)]
        r[b] = [-s * x + c * y for x, y in zip(first, second)]
    return [sum(a * b for a, b in zip(row, value)) for row in r]


def clock(jd):
    text = (ROOT / 'Sources/AstronomyKit/Engine/Moon/Generated/TDBTerms.swift').read_text()
    groups = [re.findall(r'Term\(([^,]+), ([^,]+), ([^)]+)\)', block) for block in re.split(r'// t\^\d:', text)[1:]]
    if list(map(len, groups)) != [474, 205, 85, 20, 3]:
        raise ValueError('TDB term inventory differs')

    def offset_rate(tt):
        t = tt / 365250
        offset, derivative = 0., 0.
        for power, group in enumerate(groups):
            for a, f, p in reversed(group):
                amplitude, frequency, phase = float(a), float(f), float(p)
                sine = amplitude * math.sin(frequency * t + phase)
                offset += t ** power * sine
                derivative += t ** power * amplitude * frequency * math.cos(frequency * t + phase)
                if power:
                    derivative += power * t ** (power - 1) * sine
        for a, f, p in [(0.00065e-6, 6069.776754, 4.021194), (0.00033e-6, 213.299095, 5.543132),
                        (-0.00196e-6, 6208.294251, 5.696701), (-0.00173e-6, 74.781599, 2.435900)]:
            offset += a * math.sin(f * t + p)
            derivative += a * f * math.cos(f * t + p)
        offset += 0.03638e-6 * t * t
        derivative += 2 * 0.03638e-6 * t
        return offset, 1 + derivative / (365250 * 86400)

    tdb = jd - 2451545
    tt = tdb
    for _ in range(3):
        tt = tdb - offset_rate(tt)[0] / 86400
    offset, rate = offset_rate(tt)
    return tt, offset, rate


def norm(value):
    return math.hypot(*value)


def analyze(capture):
    refs = references()
    if set(capture) != {'schemaVersion', 'rows', 'transitions'} or capture['schemaVersion'] != 3 or len(capture['rows']) != len(refs):
        raise ValueError('Native capture inventory differs')
    rows = []
    for raw, ref in zip(capture['rows'], refs):
        tt, offset, rate = clock(ref['julianDateTDB'])
        identity = dict(body=ref['body'], target=MOONS[ref['body']], center=599, frame='EQJ', epochScale='TDB', julianDateTDB=ref['julianDateTDB'])
        expected_keys = set(identity) | {'ttDays', 'tdbMinusTTSeconds', 'tdbPerTTRate', 'positionAU', 'velocityAUPerTTDay'}
        if set(raw) != expected_keys or any(raw[k] != v for k, v in identity.items()):
            raise ValueError('Native row identity, frame, or clock differs')
        for key, expected, allowance in [('ttDays', tt, 2e-11), ('tdbMinusTTSeconds', offset, 2e-15), ('tdbPerTTRate', rate, 3e-16)]:
            if type(raw[key]) not in (int, float) or not math.isfinite(raw[key]) or abs(raw[key] - expected) > allowance:
                raise ValueError('Native clock replay differs: ' + key)
        position = vector(raw['positionAU'])
        velocity = vector(raw['velocityAUPerTTDay'])
        reference_position = eqj(ref['positionAU'])
        reference_velocity = [v * rate for v in eqj(ref['velocityAUPerDay'])]
        position_error = norm([a - b for a, b in zip(position, reference_position)])
        velocity_error = norm([a - b for a, b in zip(velocity, reference_velocity)])
        tolerance = ref['relativeTolerance']
        if position_error * AU_KM > .25 or velocity_error * AU_KM > 35:
            raise ValueError('Qualified jup365 sampled-residual limit exceeded')
        if tolerance is not None and (position_error / norm(reference_position) > tolerance or velocity_error / norm(reference_velocity) > tolerance):
            raise ValueError('Existing bounded-row tolerance exceeded')
        rows.append(dict(body=ref['body'], julianDateTDB=ref['julianDateTDB'], ttDays=raw['ttDays'],
                         relativeTolerance=tolerance, positionErrorKm=position_error * AU_KM,
                         velocityErrorKmPerTTDay=velocity_error * AU_KM,
                         unscaledVelocityErrorKmPerDay=norm([a - b for a, b in zip(velocity, eqj(ref['velocityAUPerDay']))]) * AU_KM))
    moons = {}
    for body in MOONS:
        moons[body] = {}
        for subset in ('all', 'bounded'):
            eligible = [r for r in rows if r['body'] == body and (subset == 'all' or r['relativeTolerance'] is not None)]
            maxima = dict(count=len(eligible))
            for field in ('positionErrorKm', 'velocityErrorKmPerTTDay'):
                worst = max(eligible, key=lambda row: row[field])
                maxima[field] = dict(value=worst[field], julianDateTDB=worst['julianDateTDB'])
            moons[body][subset] = maxima
    identities = [(side, body) for side in ('beforeStart', 'afterEnd') for body in MOONS]
    transitions = []
    if len(capture['transitions']) != len(identities):
        raise ValueError('Native transition inventory differs')
    for raw, (side, body) in zip(capture['transitions'], identities):
        if set(raw) != {'body', 'side', 'sampleCount', 'maximumPositionCorrectionKm', 'maximumVelocityCorrectionKmPerTTDay'}:
            raise ValueError('Native transition row shape differs')
        if raw['body'] != body or raw['side'] != side or raw['sampleCount'] != 4097:
            raise ValueError('Native transition identity differs')
        for key in ('maximumPositionCorrectionKm', 'maximumVelocityCorrectionKmPerTTDay'):
            if type(raw[key]) not in (int, float) or not math.isfinite(raw[key]) or raw[key] < 0:
                raise ValueError('Native transition metric differs')
        transitions.append(raw)
    return dict(rows=rows, moons=moons, transitions=transitions)


def record(capture, toolchain, sources):
    return dict(schemaVersion=4, toolchain=toolchain, sourceSHA256=sources,
                captureSHA256=digest(encoded(capture)), capture=capture, analysis=analyze(capture))


def validate_record(data):
    if set(data) != {'schemaVersion', 'toolchain', 'sourceSHA256', 'captureSHA256', 'capture', 'analysis'} or data['schemaVersion'] != 4:
        raise ValueError('Evidence schema differs')
    if not data['toolchain']:
        raise ValueError('Capture toolchain missing')
    check_bindings(data['sourceSHA256'])
    if data['captureSHA256'] != digest(encoded(data['capture'])) or data['analysis'] != analyze(data['capture']):
        raise ValueError('Capture digest or replayed metrics differ')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--capture', action='store_true', help='run the native Swift test and publish validated evidence')
    choice.add_argument('--check', action='store_true', help='offline archive, clock, frame, ownership, and metric replay')
    args = parser.parse_args()
    if args.capture:
        before = source_hashes()
        toolchain = subprocess.check_output(['swift', '--version'], cwd=ROOT, text=True).strip()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'native.json'
            env = dict(os.environ, GALILEAN_RESIDUAL_OUTPUT=str(path))
            subprocess.run(['swift', 'test', '--no-parallel', '--filter', 'EngineGalileanResidualCaptureTests'], cwd=ROOT, env=env, check=True)
            if source_hashes() != before:
                raise ValueError('Sources changed during native capture')
            data = record(json.loads(path.read_bytes()), toolchain, before)
            validate_record(data)
            with tempfile.NamedTemporaryFile(dir=OUTPUT.parent, prefix='.residual-', delete=False) as staged:
                temporary = Path(staged.name)
                staged.write(encoded(data))
            try:
                os.replace(temporary, OUTPUT)
            finally:
                temporary.unlink(missing_ok=True)
    else:
        data = json.loads(OUTPUT.read_bytes())
        validate_record(data)
    print('Replayed 104 Galilean rows: separate position km and returned velocity km/TT-day')
    for body, maxima in data['analysis']['moons'].items():
        print(body, json.dumps(maxima, sort_keys=True))


if __name__ == '__main__':
    main()
