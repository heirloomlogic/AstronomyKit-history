#!/usr/bin/env python3
"""Archive and validate native observer-event observations without portable runtime gates."""
import argparse
import ast
import functools
import datetime
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT/'Scripts/observer-event-data'
CAPTURES = DATA/'native-captures.json'
OUTPUT = DATA/'native-evidence.json'
RETAINED_USNO_TOOL_PATHS = {
    'Scripts/observer-event-data/native-captures.json',
    'Scripts/record-observer-event-evidence.py',
    'Scripts/test_observer_events.py',
}
spec = importlib.util.spec_from_file_location('observer_references', ROOT/'Scripts/capture-observer-events.py')
references = importlib.util.module_from_spec(spec)
spec.loader.exec_module(references)


def finite(value):
    if isinstance(value, dict):
        return all(finite(v) for v in value.values())
    if isinstance(value, list):
        return all(finite(v) for v in value)
    return not isinstance(value, (int, float)) or math.isfinite(value)


def sources(capture_bytes=None):
    paths = list((ROOT/'Sources/AstronomyKit/Engine').rglob('*.swift'))
    paths += list((ROOT/'Tests/AstronomyKitTests/Engine/Events').glob('EngineObserver*Tests.swift'))
    paths += list((DATA/'sources').rglob('*.json'))
    paths += [ROOT/p for p in [
        'Scripts/capture-observer-events.py', 'Scripts/record-observer-event-evidence.py',
        'Scripts/test_observer_events.py', 'Scripts/observer-event-data/README.md', 'Scripts/observer-event-data/reference-fixtures.json',
        'Scripts/observer-event-data/native-captures.json', 'Sources/CLibAstronomy/astronomy.c',
        'Sources/AstronomyKit/RiseSet.swift', 'Sources/AstronomyKit/Time.swift',
        'Sources/AstronomyKit/Observer.swift', 'Sources/AstronomyKit/CelestialBody.swift',
        'Sources/AstronomyKit/AstronomyError.swift',
        'Tests/AstronomyKitTests/IndependentReferenceFixtures.swift',
        'Tests/AstronomyKitTests/Fixtures/IndependentReferences/reference-fixtures.json',
        'Fuzzing/corpus/fixed-riseset-infinite-limit', 'Fuzzing/corpus/fixed-riseset-stall',
    ]]
    return {str(p.relative_to(ROOT)): hashlib.sha256(capture_bytes if p == CAPTURES and capture_bytes is not None else p.read_bytes()).hexdigest() for p in sorted(paths)}


def git_bytes(*arguments):
    return subprocess.check_output(['git', *arguments], cwd=ROOT)


def allowed_retained_usno_engine_change(path):
    return path in {
        'Sources/AstronomyKit/Engine/Bodies/EngineJupiterMoons.swift',
        'Sources/AstronomyKit/Engine/Bodies/EngineJupiterMoonsJup365.swift',
    } or path.startswith('Sources/AstronomyKit/Engine/Bodies/Generated/Jup365/')


def retained_debug_usno(revision):
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('retained Debug USNO revision must be a full commit SHA')
    subprocess.run(['git', 'merge-base', '--is-ancestor', revision, 'HEAD'], cwd=ROOT, check=True)
    capture_path = str(CAPTURES.relative_to(ROOT))
    evidence_path = str((DATA/'native-evidence.json').relative_to(ROOT))
    capture_bytes = git_bytes('show', f'{revision}:{capture_path}')
    prior = json.loads(capture_bytes)
    prior_hashes = json.loads(git_bytes('show', f'{revision}:{evidence_path}'))['sourceSHA256']
    prior_engine_paths = {path for path in prior_hashes if path.startswith('Sources/AstronomyKit/Engine/')}
    current_engine_paths = {str(path.relative_to(ROOT)) for path in (ROOT/'Sources/AstronomyKit/Engine').rglob('*.swift')}
    changed_engine_paths = sorted(set(git_bytes('diff', '--name-only', revision, '--', 'Sources/AstronomyKit/Engine').decode().splitlines()) | (current_engine_paths-prior_engine_paths))
    unsupported = [path for path in changed_engine_paths if not allowed_retained_usno_engine_change(path)]
    if unsupported:
        raise ValueError('retained Debug USNO runtime inputs changed: ' + ', '.join(unsupported))
    for path, expected in prior_hashes.items():
        if path in RETAINED_USNO_TOOL_PATHS or allowed_retained_usno_engine_change(path):
            continue
        current = ROOT/path
        if not current.is_file() or hashlib.sha256(current.read_bytes()).hexdigest() != expected:
            raise ValueError(f'retained Debug USNO source differs: {path}')
    rows = prior['debug']['usno']
    rows_sha256 = hashlib.sha256(json.dumps(rows, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    provenance = {
        'kind': 'retainedUnchangedInput',
        'sourceRevision': revision,
        'sourceCapturePath': capture_path,
        'sourceCaptureSHA256': hashlib.sha256(capture_bytes).hexdigest(),
        'rowsSHA256': rows_sha256,
        'excludedEngineChanges': changed_engine_paths,
        'scope': 'Only the historical Debug USNO rows are retained. Their Sun/Moon runtime and reference inputs are unchanged; the listed Galilean-only Engine changes cannot enter these rows. Release USNO rows, other Debug observations, resources, binary sizes, and build receipts are current captures.',
    }
    return rows, provenance


def validate_debug_usno_provenance(captures):
    provenance = captures.get('debugUSNOProvenance')
    if not isinstance(provenance, dict):
        raise ValueError('missing Debug USNO provenance')
    rows_sha256 = hashlib.sha256(json.dumps(captures['debug']['usno'], sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if provenance.get('kind') == 'retainedUnchangedInput':
        rows, expected = retained_debug_usno(provenance.get('sourceRevision', ''))
        if captures['debug']['usno'] != rows or provenance != expected or provenance['rowsSHA256'] != rows_sha256:
            raise ValueError('retained Debug USNO provenance differs')
    elif provenance != {'kind': 'fresh', 'runtimeRevision': provenance.get('runtimeRevision'), 'rowsSHA256': rows_sha256} or not re.fullmatch(r'[0-9a-f]{40}', provenance.get('runtimeRevision', '')):
        raise ValueError('fresh Debug USNO provenance differs')


def usno_references():
    return json.loads((ROOT/'Tests/AstronomyKitTests/Fixtures/IndependentReferences/reference-fixtures.json').read_bytes())['riseSet']


def arithmetic(expression, variables):
    node = ast.parse(expression.replace('p.u', 'u**'), mode='eval').body
    def value(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)): return n.value
        if isinstance(n, ast.Name): return variables[n.id]
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub): return -value(n.operand)
        if isinstance(n, ast.BinOp):
            a, b = value(n.left), value(n.right)
            if isinstance(n.op, ast.Add): return a+b
            if isinstance(n.op, ast.Sub): return a-b
            if isinstance(n.op, ast.Mult): return a*b
            if isinstance(n.op, ast.Div): return a/b
            if isinstance(n.op, ast.Pow): return a**b
        raise ValueError('unrecognized Delta T expression')
    return value(node)


@functools.lru_cache(maxsize=1)
def delta_pieces():
    text = (ROOT/'Sources/AstronomyKit/Engine/Foundation/EngineDeltaT.swift').read_text()
    result = []
    for stop, body in re.findall(r'if y < (-?\d+) \{(.*?)\n            \}', text, re.S):
        result.append((int(stop), re.search(r'let u = ([^\n]+)', body)[1],
                       ' '.join(re.search(r'return (.*)', body, re.S)[1].split())))
    if [r[0] for r in result] != [-500,500,1600,1700,1800,1860,1900,1920,1941,1961,1986,2005,2050,2150]:
        raise ValueError('changed Delta T layout')
    return result


def modeled_tt(ut):
    # The frozen USNO corpus is Gregorian, 1750–2050. Do not extrapolate this replay to other calendars.
    # The native and public reference pairs both use the engine's calendar decimal year.
    date = datetime.datetime(2000,1,1,12)+datetime.timedelta(days=ut)
    if not 1750 <= date.year <= 2051: raise ValueError('outside recorded USNO calendar scope')
    start, end = datetime.datetime(date.year,1,1), datetime.datetime(date.year+1,1,1)
    y = date.year+(date-start).total_seconds()/(end-start).total_seconds()
    for stop, origin, expression in delta_pieces():
        if y < stop:
            u = arithmetic(origin, {'y': y})
            return ut+arithmetic(expression, {'y': y, 'u': u})/86400
    raise ValueError('outside recorded Delta T scope')


@functools.lru_cache(maxsize=16)
def tdb_offset(tt):
    text = (ROOT/'Sources/AstronomyKit/Engine/Moon/Generated/TDBTerms.swift').read_text()
    groups = re.split(r'// t\^\d: \d+ terms\.', text)[1:]
    terms = [[tuple(map(float, row)) for row in re.findall(r'Term\(([^,]+), ([^,]+), ([^)]+)\)', group)] for group in groups]
    if list(map(len,terms)) != [474,205,85,20,3]: raise ValueError('changed TDB coefficient layout')
    t = tt/365250
    sums = [math.fsum(a*math.sin(f*t+p) for a,f,p in reversed(group)) for group in terms]
    wf = t*(t*(t*(t*sums[4]+sums[3])+sums[2])+sums[1])+sums[0]
    wj = .00065e-6*math.sin(6069.776754*t+4.021194)+.00033e-6*math.sin(213.299095*t+5.543132)-.00196e-6*math.sin(6208.294251*t+5.696701)-.00173e-6*math.sin(74.781599*t+2.435900)+.03638e-6*t*t
    return wf+wj


def same_time(a, b):
    return abs(a-b) <= 4*max(math.ulp(a), math.ulp(b))


def parity(a, b):
    # Arithmetic/serialization comparison, not a new physical accuracy allowance.
    if isinstance(a, dict): return a.keys() == b.keys() and all(parity(a[k], b[k]) for k in a)
    if isinstance(a, list): return len(a) == len(b) and all(parity(x,y) for x,y in zip(a,b))
    if isinstance(a, float): return isinstance(b, (int,float)) and abs(a-b) <= max(1e-10,16*math.ulp(a))
    return a == b


def validate_measurements(measured):
    if set(measured) != {'usno', 'points', 'semidiameters', 'polar'} or not finite(measured):
        raise ValueError('invalid measurement fields or nonfinite observation')
    fixture = references.fixture()
    expected = usno_references()
    rows = measured['usno']
    if len(rows) != 5909 or [r['sourceLine'] for r in rows] != [r['sourceLine'] for r in expected]:
        raise ValueError('USNO row selection differs')
    for row, source in zip(rows, expected):
        if set(row) != {'sourceLine','nativeTT','nativeUT','referenceTT','referenceUT','residualSeconds','direction'}:
            raise ValueError('USNO observation fields differ')
        if not same_time(row['nativeTT'], modeled_tt(row['nativeUT'])) or not same_time(row['referenceTT'], modeled_tt(row['referenceUT'])):
            raise ValueError('USNO recorded time scales disagree')
        ut = (datetime.datetime.fromisoformat(source['utc'].removesuffix('Z'))-datetime.datetime(2000, 1, 1, 12)).total_seconds()/86400
        residual = abs(row['nativeTT']-row['referenceTT'])*86400
        if row['referenceUT'] != ut or row['direction'] != source['direction']:
            raise ValueError('USNO time interpretation or direction differs')
        if abs(row['residualSeconds']-residual) > 1e-9 or residual > source['timeToleranceSeconds']:
            raise ValueError('USNO unchanged timing criterion failed')
    if len(measured['points']) != len(fixture['rows']):
        raise ValueError('observer point count differs')
    for row, source in zip(measured['points'], fixture['rows']):
        if set(row) != {'body','tt','ut','altitudeDegrees','hourAngleHours','altitudeErrorArcminutes','hourAngleErrorArcminutes'}:
            raise ValueError('observer point fields differ')
        ut = source['tt']-(source['tdbMinusUTSeconds']-tdb_offset(source['tt'])-(source['dut1Seconds'] or 0))/86400
        if not same_time(row['ut'], ut):
            raise ValueError('observer source UT1/TT relation differs')
        altitude_error = abs(row['altitudeDegrees']-source['altitudeDegrees'])*60
        ha_error = abs(((row['hourAngleHours']-source['hourAngleHours'])*15+180)%360-180)*60
        if row['body'] != source['body'] or row['tt'] != source['tt']:
            raise ValueError('observer point selection differs')
        if abs(row['altitudeErrorArcminutes']-altitude_error) > 1e-9 or abs(row['hourAngleErrorArcminutes']-ha_error) > 1e-9:
            raise ValueError('observer point residual differs')
        if max(altitude_error, ha_error) > fixture['angularToleranceArcminutes']:
            raise ValueError('observer point criterion failed')
    if len(measured['semidiameters']) != 3 or len(measured['polar']) != 4:
        raise ValueError('optical source sample count differs')
    for row, source in zip(measured['semidiameters'], fixture['semidiameters']):
        if set(row) != {'universalTime','opticalDegrees','nominalDegrees','sourceDegrees','opticalResidualDegrees'}:
            raise ValueError('semidiameter observation fields differ')
        if not 0 < row['nominalDegrees'] < row['opticalDegrees'] < 1 or abs(math.sin(math.radians(row['nominalDegrees']))-math.sin(math.radians(row['opticalDegrees']))*695700/696000) > 1e-15:
            raise ValueError('native limb radii do not share a distance')
        if row['universalTime'] != source['universalTime'] or row['sourceDegrees'] != source['semidiameterDegrees']:
            raise ValueError('semidiameter source selection differs')
        residual = row['opticalDegrees']-source['semidiameterDegrees']
        if abs(row['opticalResidualDegrees']-residual) > 1e-15 or abs(residual) > fixture['semidiameterComparisonDegrees']:
            raise ValueError('semidiameter convention check failed')
        if abs(row['nominalDegrees']-row['sourceDegrees']) <= 100*fixture['semidiameterComparisonDegrees']:
            raise ValueError('nominal-radius negative control failed')
    for row, source in zip(measured['polar'], fixture['polar']):
        if set(row) != {'tt','nativeAltitudeDegrees','sourceAltitudeDegrees','nativeDistanceAU','nativeApparentICRFDeg','sourceNominalResidualDegrees','sourceOpticalResidualDegrees'}:
            raise ValueError('polar observation fields differ')
        if abs(row['nativeAltitudeDegrees']-source['altitudeDegrees'])*60 > fixture['angularToleranceArcminutes']:
            raise ValueError('polar source altitude criterion failed')
        angles = row['nativeApparentICRFDeg']
        if row['nativeDistanceAU'] <= 0 or len(angles) != 2 or not 0 <= angles[0] < 360 or not -90 <= angles[1] <= 90:
            raise ValueError('invalid polar state observation')
        if row['tt'] != source['tt'] or row['sourceAltitudeDegrees'] != source['altitudeDegrees']:
            raise ValueError('polar source selection differs')
        for radius, key in [(695700, 'sourceNominalResidualDegrees'), (696000, 'sourceOpticalResidualDegrees')]:
            value = source['altitudeDegrees']+math.degrees(math.asin(radius/149597870.7/source['distanceAU']))+34/60
            if abs(row[key]-value) > 1e-14:
                raise ValueError('polar limb composition differs')


def summary(measured):
    worst = max(measured['usno'], key=lambda r: r['residualSeconds'])
    nonpolar = max((r for r in measured['usno'] if r['sourceLine'] != 2923), key=lambda r: r['residualSeconds'])
    return dict(usnoRows=len(measured['usno']), worstUSNO=worst, worstOtherUSNO=nonpolar,
                maximumAltitudeErrorArcminutes=max(r['altitudeErrorArcminutes'] for r in measured['points']),
                maximumHourAngleErrorArcminutes=max(r['hourAngleErrorArcminutes'] for r in measured['points']),
                maximumSemidiameterResidualDegrees=max(abs(r['opticalResidualDegrees']) for r in measured['semidiameters']))


def evidence(captures, hashes):
    validate_debug_usno_provenance(captures)
    for configuration in ['debug', 'release']:
        validate_measurements(captures[configuration])
    if not parity(captures['debug'], captures['release']):
        raise ValueError('Debug/Release observer observations disagree')
    resources = captures['resources']
    if not finite(resources) or resources['eventsPerWorkload'] != 100:
        raise ValueError('invalid resource observation')
    if set(resources['seconds']) != {'sunRise', 'moonRise', 'sunHourAngle', 'publicCSunRise'}:
        raise ValueError('resource workload differs')
    if any(v < 0 for v in resources['seconds'].values()) or resources['coldSunRiseSeconds'] < 0:
        raise ValueError('negative duration')
    peaks = [resources[k] for k in ['peakBeforeBytes', 'peakAfterColdBytes', 'peakAfterWorkloadsBytes']]
    if peaks != sorted(peaks) or any(not isinstance(v, int) or v <= 0 for v in peaks) or not resources['host']:
        raise ValueError('invalid RSS or host')
    if captures['releaseExecutableBytes'] <= 0 or captures['observerObjectBytes'] <= 0 or not captures['toolchain']:
        raise ValueError('invalid build observation')
    build = {c: float(re.search(r'Build complete! \(([^ ]+) sec\)', captures['buildReceipts'][c]).group(1)) for c in ['debug', 'release']}
    return dict(schemaVersion=2, sourceSHA256=hashes, debugUSNOProvenance=captures['debugUSNOProvenance'],
                debug=summary(captures['debug']), release=summary(captures['release']),
                resources=resources, buildSeconds=build, toolchain=captures['toolchain'],
                releaseExecutableBytes=captures['releaseExecutableBytes'], observerObjectBytes=captures['observerObjectBytes'], baseline=captures['baseline'],
                criteria='All 5909 archived USNO rows retain their source-specific allowance, including 70.8 TT seconds at line 2923. Sixteen sampled altitude/hour-angle points retain one arcminute. Three printed USNO semidiameters discriminate the optical convention at 0.000001 degree; this is not an asserted physical solar-radius accuracy.',
                limitations='USNO navigation output supports the chosen optical limb; the rise/set service implementation is unavailable. Horizon refraction remains a conventional atmosphere, not a prediction of weather. The public observer APIs run on these searches since the #96 cutover. Planetary apsis qualification is outside this observer artifact. Resource values are host observations, not portable ceilings.')


def capture(directory, retained_debug_usno_revision=None):
    directory = Path(directory)
    result = {}
    for configuration in ['debug', 'release']:
        path = directory/f'observer-{configuration}'
        rows = sum((json.loads(p.read_bytes()) for p in sorted(path.glob('usno-*.json'))), [])
        result[configuration] = dict(usno=sorted(rows, key=lambda r: r['sourceLine']),
                                    **{name: json.loads((path/f'{name}.json').read_bytes()) for name in ['points', 'semidiameters', 'polar']})
    if retained_debug_usno_revision:
        result['debug']['usno'], result['debugUSNOProvenance'] = retained_debug_usno(retained_debug_usno_revision)
    else:
        result['debugUSNOProvenance'] = {
            'kind': 'fresh',
            'runtimeRevision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
            'rowsSHA256': hashlib.sha256(json.dumps(result['debug']['usno'], sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
        }
    result['resources'] = json.loads((directory/'observer-resources/resources.json').read_bytes())
    result['baseline'] = json.loads((directory/'baseline-binary.json').read_bytes())
    result['buildReceipts'] = {c: re.search(r'Build complete! \([^\n]+', (directory/f'link3-full-{c}.log').read_text()).group(0) for c in ['debug', 'release']}
    result['toolchain'] = subprocess.check_output(['swift', '--version'], text=True).strip()
    result['releaseExecutableBytes'] = (ROOT/'.build/out/Products/Release/AstronomyKitTests.xctest/Contents/MacOS/AstronomyKitTests').stat().st_size
    result['observerObjectBytes'] = (ROOT/'.build/out/Intermediates.noindex/AstronomyKit.build/Release/AstronomyKit-t.build/Objects-normal/arm64/EngineObserverEvents.o').stat().st_size
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--capture', type=Path)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--retain-debug-usno-from', metavar='REVISION')
    args = parser.parse_args()
    if args.retain_debug_usno_from and not args.capture:
        parser.error('--retain-debug-usno-from requires --capture')
    captures = capture(args.capture, args.retain_debug_usno_from) if args.capture else json.loads(CAPTURES.read_bytes())
    encoded = (json.dumps(captures, indent=2, sort_keys=True, allow_nan=False)+'\n').encode()
    expected = evidence(captures, sources(encoded if args.capture else None))
    if args.check:
        if json.loads(OUTPUT.read_bytes()) != expected:
            raise SystemExit('recorded observer evidence differs from source-bound captures')
    else:
        if args.capture:
            CAPTURES.write_bytes(encoded)
        OUTPUT.write_text(json.dumps(expected, indent=2, sort_keys=True, allow_nan=False)+'\n')
    print('observer event evidence verified')


if __name__ == '__main__':
    main()
