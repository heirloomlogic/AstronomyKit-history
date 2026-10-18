#!/usr/bin/env python3
"""Bind fresh native planetary-event measurements to their source and runtime files."""
import argparse
import importlib.util
import json
import math
import re
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT/'Scripts/saturn-data/native-evidence.json'
CAPTURES = ROOT/'Scripts/saturn-data/native-captures.json'
dependency_spec = importlib.util.spec_from_file_location('planetary_dependencies', ROOT/'Scripts/evidence_dependencies.py')
dependencies = importlib.util.module_from_spec(dependency_spec)
dependency_spec.loader.exec_module(dependencies)


def source_hashes(capture_bytes=None):
    overrides = None if capture_bytes is None else {str(CAPTURES.relative_to(ROOT)): capture_bytes}
    return dependencies.source_hashes('planetary-events', overrides=overrides)


def measurements(directory, configuration):
    directory = Path(directory)
    result = {name: json.loads((directory/f'link3-{name}-{configuration}.json').read_bytes()) for name in ['saturn', 'source']}
    result['parity'] = json.loads((directory/f'link3-{configuration}.json').read_bytes())
    result['cycle'] = json.loads((directory/f'link3-cycle-{configuration}.json').read_bytes())
    result['coefficients'] = json.loads((directory/f'saturn-assessment/source-{configuration}.json').read_bytes())
    return result


def finite_numbers(value):
    if isinstance(value, dict):
        return all(finite_numbers(v) for v in value.values())
    if isinstance(value, list):
        return all(finite_numbers(v) for v in value)
    return not isinstance(value, (int, float)) or math.isfinite(value)


def validate(result):
    if not finite_numbers(result):
        raise ValueError('nonfinite native measurement')
    parity = result['parity']
    for key, limit in [('maximumElongationParitySeconds', 10), ('peakMagnitudeParitySeconds', 10), ('planetaryApsisParitySeconds', 60)]:
        if not 0 <= parity[key] < limit:
            raise ValueError('native parity criterion failed')
    bodies = ['mercury', 'venus', 'earth', 'mars', 'jupiter', 'uranus']
    if parity['planetaryApsisBodies'] != len(bodies) or [r['body'] for r in parity['apsisEvents']] != bodies:
        raise ValueError('parity selection differs')
    if parity['planetaryApsisWorstBody'].lower() not in bodies:
        raise ValueError('parity worst body differs')
    if any(r['kind'] not in ['pericenter', 'apocenter'] or abs(r['jdtt'] - 2451545) > 1461000 for r in parity['apsisEvents']):
        raise ValueError('invalid parity event')
    references = json.loads((ROOT/'Tests/AstronomyKitTests/Fixtures/IndependentReferences/reference-fixtures.json').read_bytes())['saturnApsides']
    if [r['referenceJulianDateTT'] for r in result['saturn']] != [r['julianDateTT'] for r in references]:
        raise ValueError('Saturn selection differs')
    if any(not math.isfinite(r['signedTimingErrorSeconds']) or abs(r['signedTimingErrorSeconds']) >= 60 for r in result['saturn']):
        raise ValueError('Saturn sixty-second criterion failed')
    for row, reference in zip(result['saturn'], references):
        residual = (row['nativeJulianDateTT'] - row['referenceJulianDateTT']) * 86400
        if abs(residual - row['signedTimingErrorSeconds']) > 2 * math.ulp(row['referenceJulianDateTT']) * 86400 or row['sourceRangeRateAUPerDay'] != reference['sourceRangeRateAUPerDay']:
            raise ValueError('Saturn measured residual or source rate differs')
    expected = json.loads((ROOT/'Scripts/reference-data/planetary-apsis-evidence.json').read_bytes())['cases']
    if [r['body'] for r in result['source']] != [r['body'] for r in expected]:
        raise ValueError('planetary source selection differs')
    for measured, source in zip(result['source'], expected):
        bracket = (measured['sourceLowerJDTT'], measured['sourceUpperJDTT'])
        if bracket not in [(r['lowerJDTT'], r['upperJDTT']) for r in source['roots']]:
            raise ValueError('source bracket changed')
        residual = (measured['nativeJDTT'] - sum(bracket)/2)*86400
        if not math.isfinite(residual) or abs(residual - measured['nativeMinusSourceSeconds']) > 1e-9:
            raise ValueError('invalid residual')
        if abs(residual) >= 60:
            raise ValueError('qualified source case missed sixty seconds')
    census = json.loads((ROOT/'Scripts/planet-data/de441-cycle-census.json').read_bytes())['cases']
    if len(result['cycle']) != 6 or {row['body'] for row in result['cycle']} != set(census):
        raise ValueError('complete-cycle measurement inventory differs')
    for measured in result['cycle']:
        source = census[measured['body']]
        if measured['sourceIndex'] not in source['principalPhysicalCrossingIndices']:
            raise ValueError('complete-cycle principal selection differs')
        crossing = source['physicalCrossings'][measured['sourceIndex']]
        if measured['kind'] != crossing['kind'] or measured['sourceTT'] != crossing['tt'] or measured['physicalCrossingCount'] != source['physicalCrossingCount'] or measured['systemCrossingCount'] != source['systemCrossingCount']:
            raise ValueError('complete-cycle source measurement differs')
        residual = (measured['nativeTT'] - measured['sourceTT'])*86400
        if not math.isfinite(residual) or abs(residual-measured['nativeMinusSourceSeconds']) > 1e-9 or abs(residual) >= 60:
            raise ValueError('complete-cycle sixty-second criterion failed')
    if result['coefficients']['rows'] != len(json.loads((ROOT/'Scripts/saturn-data/direct-fixtures.json').read_bytes())['rows']):
        raise ValueError('coefficient sample selection differs')


def validate_recording(result, captures=None):
    # Raw observations are archived separately. Check derivation and integrity, not
    # equality with a new host's performance or a new universal resource ceiling.
    captures = captures if captures is not None else json.loads(CAPTURES.read_bytes())
    expected_keys = {'schemaVersion', 'sourceSHA256', 'debug', 'release', 'resources', 'encodingBoundaryLimits', 'buildSeconds', 'toolchain', 'releaseExecutableBytes', 'baseline'} | set(metadata())
    if set(result) != expected_keys:
        raise ValueError('recorded evidence fields differ')
    for configuration in ['debug', 'release']:
        validate(result[configuration])
        if result[configuration] != captures[configuration]:
            raise ValueError('native capture differs')
    for key in ['resources', 'toolchain', 'releaseExecutableBytes', 'baseline']:
        if result[key] != captures[key]:
            raise ValueError(f'recorded {key} differs from capture')
    expected_build = {c: float(re.search(r'Build complete! \(([^ ]+) sec\)', captures['buildReceipts'][c]).group(1)) for c in ['debug', 'release']}
    if result['buildSeconds'] != expected_build or any(v < 0 or not math.isfinite(v) for v in expected_build.values()):
        raise ValueError('build evidence differs')
    resource = result['resources']
    if not finite_numbers(resource):
        raise ValueError('nonfinite resource observation')
    timings = [resource[k] for k in ['centerColdSeconds', 'retainedColdSeconds', 'eventSeconds']] + list(resource['seconds'].values())
    peaks = [resource[k] for k in ['peakBeforeBytes', 'peakAfterRetainedBytes', 'peakAfterCenterBytes', 'peakAfterWorkloadsBytes']]
    if any(v < 0 for v in timings) or any(not isinstance(v, int) or v <= 0 for v in peaks) or peaks != sorted(peaks):
        raise ValueError('invalid resource observation')
    if resource['evaluationsPerModel'] != 2000 or resource['eventCount'] != 100 or set(resource['seconds']) != {'retained', 'center'}:
        raise ValueError('resource workload differs')
    if not resource['host'] or not result['toolchain'] or result['releaseExecutableBytes'] <= 0:
        raise ValueError('resource host or executable differs')
    if result['schemaVersion'] != 2 or any(result.get(key) != value for key, value in metadata().items()):
        raise ValueError('representation metadata differs')


def encoding_boundary_limits():
    spec = importlib.util.spec_from_file_location('saturn_assessment', ROOT/'Scripts/assess-saturn-apsides.py')
    assessment = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(assessment)
    candidate = json.loads(assessment.OUTPUT.read_bytes())['candidates']['float64']
    minimum_distances = []
    for root in candidate['roots']:
        tdb = assessment.tt_to_tdb(root['rootJDTT'])
        distances = []
        for body in candidate['bodies'].values():
            fraction = (tdb-body['startJDTDB'])/body['recordDays']
            distances.append(abs(fraction-round(fraction))*body['recordDays']*86400)
        minimum_distances.append(dict(referenceJDTT=root['referenceJDTT'], nearestRecordJoinSeconds=min(distances)))
    return dict(finiteDifferenceWidthDays=0.001,
                encodingOnlySlopePerturbationBoundAUPerDay=2*candidate['bodies']['699']['positionBoundKm']/0.001/assessment.d.AU_KM,
                existingStateDerivativeComparisonAllowanceAUPerDay=2e-9,
                roots=minimum_distances,
                scope='Binary64 position-encoding contribution only, using the Lipschitz property of vector norm. Evaluator roundoff and the physical source are separate. This does not bound event-time error near shallow roots; the six qualified roots do not test join-adjacent events.')


def metadata():
    return dict(decodedPayloadBytes=19400016,
                resourceScope='macOS arm64 Release test executable; first retained evaluation then first center evaluation in a new process, followed by 2000 states per model and 100 repeated Saturn apsis searches. RSS is process high-water, not isolated object ownership. Baseline executable predates Saturn integration; binary delta also includes tests.',
                fullWeightTT=[-36524.5,47846.5], blendTT=[[-36556.5,-36524.5],[47846.5,47878.5]],
                limitations=['The Jupiter, Uranus and Neptune qualification preserves every direct-source physical-center crossing over one nominal orbital cycle, selects principal candidates from the source system-center extrema, and tests those six native events; it is not a continuous event-time bound.', 'The eight 2025 diagnostic windows remain local checks for all planets and Pluto.', 'The public searches run on these native searches since the #96 cutover; the parity rows record the facade conversion, not a comparison with the former C searches.', 'Outside the selected source window the retained model remains; global physical-center and event accuracy are not established.'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--capture', type=Path, help='directory with fresh Debug and Release Swift measurement files')
    parser.add_argument('--rebind', action='store_true', help='rebind validated archived measurements after ownership-only changes')
    args = parser.parse_args()
    if sum([args.check, args.capture is not None, args.rebind]) != 1:
        parser.error('choose exactly one of --check, --capture, or --rebind')
    if args.check:
        result = json.loads(OUTPUT.read_bytes())
        if result['encodingBoundaryLimits'] != encoding_boundary_limits():
            raise ValueError('encoded boundary qualification differs')
        if result['sourceSHA256'] != source_hashes():
            raise ValueError('native evidence source bindings differ; recapture after source changes')
    elif args.capture:
        release = args.capture/'saturn-assessment/measurement-release.json'
        executable = ROOT/'.build/out/Products/Release/AstronomyKitTests.xctest/Contents/MacOS/AstronomyKitTests'
        captures = dict(debug=measurements(args.capture, 'debug'), release=measurements(args.capture, 'release'),
                        resources=json.loads(release.read_bytes()),
                        buildReceipts={c: re.search(r'Build complete! \([^\n]+', (args.capture/f'link3-full-{c}.log').read_text()).group(0) for c in ['debug', 'release']},
                        toolchain=subprocess.check_output(['swift', '--version'], text=True).strip(),
                        releaseExecutableBytes=executable.stat().st_size,
                        baseline=json.loads((args.capture/'saturn-assessment/baseline-binary.json').read_bytes()))
        capture_bytes = (json.dumps(captures, indent=2, sort_keys=True)+'\n').encode()
        result = dict(schemaVersion=2, sourceSHA256=source_hashes(capture_bytes), debug=measurements(args.capture, 'debug'), release=measurements(args.capture, 'release'),
                      resources=json.loads(release.read_bytes()), encodingBoundaryLimits=encoding_boundary_limits(),
                      buildSeconds={c:float(re.search(r'Build complete! \(([^ ]+) sec\)', (args.capture/f'link3-full-{c}.log').read_text()).group(1)) for c in ['debug','release']},
                      toolchain=subprocess.check_output(['swift', '--version'], text=True).strip(),
                      releaseExecutableBytes=executable.stat().st_size,
                      baseline=json.loads((args.capture/'saturn-assessment/baseline-binary.json').read_bytes()),
                      **metadata())
    else:
        result = json.loads(OUTPUT.read_bytes())
        result['sourceSHA256'] = dependencies.verify_retained_inputs('planetary-events', result['sourceSHA256'])
        dependencies.verify_rebound_document(json.loads(OUTPUT.read_bytes()), result, 'sourceSHA256')
    validate_recording(result, None if args.check or args.rebind else captures)
    if args.capture:
        CAPTURES.write_bytes(capture_bytes)
    if args.capture or args.rebind:
        OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True)+'\n')
    print('Verified native planetary event evidence' if args.check else 'Rebound native planetary event evidence' if args.rebind else 'Recorded native planetary event evidence')


if __name__ == '__main__':
    main()
