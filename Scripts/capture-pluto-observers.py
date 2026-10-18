#!/usr/bin/env python3
"""Capture and replay the frozen Pluto geocentric observer references."""
import argparse
import csv
import hashlib
import importlib.util
import json
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'Scripts/pluto-data'
SPEC = importlib.util.spec_from_file_location('references', ROOT / 'Scripts/reference-data/build-fixtures.py')
references = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(references)
DEPENDENCY_SPEC = importlib.util.spec_from_file_location('pluto_dependencies', ROOT / 'Scripts/evidence_dependencies.py')
dependencies = importlib.util.module_from_spec(DEPENDENCY_SPEC)
DEPENDENCY_SPEC.loader.exec_module(dependencies)
EPOCHS = {
    9: [-1461000., -1460999., -1100000., -766524., -600000., -400000., -200000., 200000., 400000., 600000., 766524., 1100000., 1460999., 1461000.],
    999: [-58400., -36556.5, -36556.25, -36540.5, -36524.5, 0., 47846.5, 47846.75, 47862.5, 47878.5, 47878.75, 58400.],
}


EXTENDED_EPOCHS = [-73046.5, -73039.5, -73031.5, -73023.5, -73015.5, -73014.5, -72000., 72000., 73013.5, 73014.5, 73022.5, 73030.5, 73038.5, 73044.5, 73045.5]


def query(target, epochs=None):
    result = references.observer_query(str(target), [2451545. + t for t in (EPOCHS[target] if epochs is None else epochs)])
    result.update({key: references.quoted(value) for key, value in {
        'TIME_TYPE': 'TT', 'TLIST_TYPE': 'JD', 'CAL_FORMAT': 'JD',
        'QUANTITIES': '1,2,21,45', 'EXTRA_PREC': 'YES',
    }.items()})
    return result


def parse(target, data, epochs=None):
    epochs = EPOCHS[target] if epochs is None else epochs
    try:
        references.validate_horizons_response(str(target), data)
    except RuntimeError as error:
        raise ValueError(str(error)) from error
    result = json.loads(data)['result']
    name, source = ('Pluto Barycenter', 'DE441') if target == 9 else ('Pluto', 'plu060_merged')
    requirements = [
        rf'Target body name: {name} \({target}\) +\{{source: {source}\}}',
        r'Center body name: Earth \(399\) +\{source: DE441\}',
        r'Center-site name: GEOCENTRIC', r'Atmos refraction: NO \(AIRLESS\)',
    ]
    if any(re.search(pattern, result) is None for pattern in requirements):
        raise ValueError('unexpected target, source, observer, or refraction semantics')
    header = next((line for line in result.splitlines() if line.startswith('Date_')), '')
    expected = ['Date_________JDTT', '', '', 'R.A.___(ICRF)', 'DEC____(ICRF)',
                'R.A.__(a-app)', 'DEC___(a-app)', '1-way_down_LT', 'RA_(ICRF-a-app)', 'DEC_(ICRF-a-app)', '']
    if [c.strip() for c in next(csv.reader([header]))] != expected:
        raise ValueError('unexpected time scale, frame, or column layout')
    lines = result.split('$$SOE\n')[1].split('$$EOE')[0].splitlines()
    if len(lines) != len(epochs):
        raise ValueError('missing or extra observer epochs')
    rows = []
    for tt, line in zip(epochs, lines):
        columns = [c.strip() for c in next(csv.reader([line]))]
        if len(columns) != 11 or columns[1:3] != ['', ''] or columns[-1] != '':
            raise ValueError('unexpected row layout')
        jd, *values = [float(columns[i]) for i in [0, 3, 4, 5, 6, 7, 8, 9]]
        if not all(math.isfinite(v) for v in [jd, *values]) or jd != tt + 2451545.:
            raise ValueError('invalid value or changed epoch')
        for ra, dec in [values[0:2], values[2:4], values[5:7]]:
            if not (0 <= ra < 360 and -90 <= dec <= 90):
                raise ValueError('invalid direction')
        if not 0 < values[4] < 1440:
            raise ValueError('invalid light time')
        rows.append(dict(tt=tt, target=target, astrometricICRFDeg=values[:2], apparentEQDDeg=values[2:4],
                         lightTimeMinutes=values[4], apparentICRFDeg=values[5:7]))
    return rows


def fixture():
    sources, rows = [], []
    for target in EPOCHS:
        path = DATA / 'observer-sources' / f'horizons-{target}.json'
        data = path.read_bytes()
        rows += parse(target, data)
        sources.append(dict(path=str(path.relative_to(ROOT)), sha256=hashlib.sha256(data).hexdigest(),
                            query=query(target), url=references.horizons_url(query(target))))
    path = DATA / 'observer-sources' / 'horizons-999-extended.json'
    data = path.read_bytes()
    rows += parse(999, data, EXTENDED_EPOCHS)
    sources.append(dict(path=str(path.relative_to(ROOT)), sha256=hashlib.sha256(data).hexdigest(),
                        query=query(999, EXTENDED_EPOCHS), url=references.horizons_url(query(999, EXTENDED_EPOCHS))))
    boundary = DATA / 'observer-sources/horizons-999-observer-boundary.json'
    boundary_query = json.loads(boundary.with_suffix('.query.json').read_bytes())
    if boundary_query['query'] != query(999, [73046.49]) or boundary_query['sha256'] != hashlib.sha256(boundary.read_bytes()).hexdigest():
        raise ValueError('Horizons boundary response provenance differs')
    if json.loads(boundary.read_bytes()).get('error') != 'No ephemeris for target \"Pluto\" after A.D. 2199-DEC-29 00:00:00.0003 TT':
        raise ValueError('Horizons boundary availability changed')
    return dict(schemaVersion=1, observerSourceBoundary=dict(path=str(boundary.relative_to(ROOT)), **boundary_query), observationTimeScale='JD TT', angularToleranceArcminutes=1,
                selection='Frozen before retrieval: fourteen outer barycenter epochs including both engine endpoints; twenty-seven center epochs retain the twelve archived dates and add both expanded 32-TDB-day blends and interior dates. The earliest new observer epoch is one day inside source coverage to enclose retarded emission.',
                sources=sources, rows=rows)


def source_hashes():
    return dependencies.source_hashes('pluto-observers')


def validate_measurement(measurement):
    expected = fixture()['rows']
    rows = measurement['rows']
    if [(r['tt'], r['target']) for r in rows] != [(r['tt'], r['target']) for r in expected]:
        raise ValueError('measurement selection differs')
    for row, reference in zip(rows, expected):
        if not all(isinstance(v, (float, int)) and math.isfinite(v) for v in row.values()):
            raise ValueError('nonfinite measurement')
        for key in ['astrometricArcminutes', 'apparentICRFArcminutes', 'apparentEQDArcminutes']:
            if not 0 <= row[key] <= 1:
                raise ValueError('one-arcminute target missed')
        if row['horizonsLightTimeMinutes'] != reference['lightTimeMinutes']:
            raise ValueError('reference light time changed')
        if row['target'] == 999 and not (-73047.5 < row['emissionTDB'] < 73046.5 and 0 < row['centerWeight'] <= 1):
            raise ValueError('center emission outside verified source coverage')
        if not row['emissionTT'] < row['tt']:
            raise ValueError('emission does not precede observation')
    for name in ['Earth', 'Frame']:
        count = sum(row[f'omitted{name}Arcminutes'] > 1 for row in rows)
        if count != measurement[f'omitted{name}Failures'] or count < 15:
            raise ValueError('negative control differs')


def native_evidence(debug, release):
    for measurement in [debug, release]:
        validate_measurement(measurement)
    return dict(schemaVersion=1, sourceSHA256=source_hashes(), debug=debug, release=release,
                observationTimeScale='TT reception and emission parameters with elapsed-TDB barycentric light time; jplHorizons supplies the observation UT for frame rotation',
                toleranceArcminutes=1,
                domain=dict(acceptedHeliocentricTTDays=[-1461000, 1461000],
                            retardedSourceTDBInterval=dict(lowerInclusive=-1461016.5, upperExclusive=1461015.5),
                            retardedBodyTTDaysLowerInclusive=-1461002,
                            bodyPaddingScope="Private apparent emission evaluations; reception Earth remains inside the unchanged public range",
                            successfulGeocentricTTDays=[-1461000, -1460999.9, -1460999, 1460999, 1461000],
                            modes=['none', 'corrected'], issue='https://github.com/heirloomlogic/AstronomyKit/issues/227',
                            preexistingBase='00119ad33521b67fa365b33d940404d5739e356b'),
                limitations=[f'{sum(map(len, EPOCHS.values())) + len(EXTENDED_EPOCHS)} sampled public directions, not a full-range bound.',
                             'Outer target 9 references do not qualify the physical center 999.',
                             'Sun-dependent angles now share apparent-source padding at both accepted endpoints; exterior receptions remain rejected.',
                             'Endpoint tests cover velocity composition, not independent velocity accuracy; event qualification remains separate.',
                             'Native uses barycentric TDB light time, finite-source solar deflection and relativistic observer aberration; it omits Shapiro delay and planetary deflection.',
                             'Native and Horizons equator-of-date precession/nutation conventions differ.'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', action='store_true', help='explicitly replace the archived publisher responses')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--record-native', nargs=2, metavar=('DEBUG_JSON', 'RELEASE_JSON'), help='record fresh opt-in Swift test outputs')
    parser.add_argument('--rebind-native', action='store_true', help='rebind the validated archived native measurements after ownership-only changes')
    args = parser.parse_args()
    if sum([args.capture, args.check, args.record_native is not None, args.rebind_native]) > 1:
        parser.error('--capture, --check, --record-native, and --rebind-native are mutually exclusive')
    for target in EPOCHS:
        path = DATA / 'observer-sources' / f'horizons-{target}.json'
        if args.capture:
            data = references.download(references.horizons_url(query(target)))
            references.validate_horizons_response(str(target), data)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
    if args.capture:
        path = DATA / 'observer-sources' / 'horizons-999-extended.json'
        data = references.download(references.horizons_url(query(999, EXTENDED_EPOCHS)))
        parse(999, data, EXTENDED_EPOCHS)
        path.write_bytes(data)
    output = DATA / 'observer-fixtures.json'
    encoded = (json.dumps(fixture(), indent=2, sort_keys=True) + '\n').encode()
    if args.check:
        if output.read_bytes() != encoded:
            raise SystemExit('observer fixtures or archive digests differ; regenerate explicitly')
        evidence = json.loads((DATA / 'observer-evidence.json').read_bytes())
        if evidence != native_evidence(evidence['debug'], evidence['release']):
            raise SystemExit('native evidence source bindings or metadata differ; rerun native qualification')
        print(f'{sum(map(len, EPOCHS.values())) + len(EXTENDED_EPOCHS)} Pluto observer epochs, archive digests, and native evidence bindings verified')
    else:
        output.write_bytes(encoded)
    if args.record_native or args.rebind_native:
        if args.rebind_native:
            retained = json.loads((DATA / 'observer-evidence.json').read_bytes())
            measurements = [retained['debug'], retained['release']]
            dependencies.verify_retained_inputs('pluto-observers', retained['sourceSHA256'])
        else:
            measurements = [json.loads(Path(p).read_bytes()) for p in args.record_native]
        rebound = native_evidence(*measurements)
        if args.rebind_native:
            dependencies.verify_rebound_document(retained, rebound, 'sourceSHA256')
        (DATA / 'observer-evidence.json').write_text(json.dumps(rebound, indent=2, sort_keys=True) + '\n')


if __name__ == '__main__':
    main()
