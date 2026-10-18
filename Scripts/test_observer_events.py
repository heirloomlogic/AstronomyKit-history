import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest
from unittest import mock
import tempfile
import shutil
import io

ROOT = Path(__file__).resolve().parents[1]


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, ROOT/'Scripts'/file)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


references = load('observer_reference_test', 'capture-observer-events.py')
record = load('observer_record_test', 'record-observer-event-evidence.py')


class ObserverSourcesTests(unittest.TestCase):
    def source(self):
        return references.read_source(references.DATA/'sources/horizons/sun.json')

    def test_replay_frozen_fixture(self):
        self.assertEqual(references.fixture(), json.loads(references.FIXTURE.read_bytes()))

    def test_nonfinite_epoch_and_values(self):
        for old, new in [('2415020.500000000', 'nan'), ('-18.304851246', 'nan'), ('6.440174497', 'inf')]:
            with self.subTest(old=old):
                document, query = self.source()
                self.assertIn(old, document['result'])
                document['result'] = document['result'].replace(old, new, 1)
                with self.assertRaises(ValueError):
                    references.parse_horizons(document, query, *references.CASES[0])

    def test_changed_time_frame_refraction_site_and_target(self):
        mutations = [('TIME_TYPE', "'UT'"), ('COMMAND', "'399'"), ('APPARENT', "'REFRACTED'"), ('SITE_COORD', "'0,0,0'")]
        for key, value in mutations:
            with self.subTest(key=key):
                document, query = self.source()
                query[key] = value
                with self.assertRaises(ValueError):
                    references.parse_horizons(document, query, *references.CASES[0])
        for old, new in [('Date_________JDTT', 'Date_________JDUT'), ('R.A.__(a-app)', 'R.A.___(ICRF)'), ('Sun (10)', 'Earth (399)')]:
            document, query = self.source()
            document['result'] = document['result'].replace(old, new, 1)
            with self.assertRaises(ValueError):
                references.parse_horizons(document, query, *references.CASES[0])

    def test_missing_and_extra_rows(self):
        for extra in [False, True]:
            document, query = self.source()
            head, rest = document['result'].split('$$SOE\n')
            rows, tail = rest.split('$$EOE')
            lines = rows.splitlines()
            document['result'] = head+'$$SOE\n'+'\n'.join(lines+lines[:1] if extra else lines[:-1])+'\n$$EOE'+tail
            with self.assertRaises(ValueError):
                references.parse_horizons(document, query, *references.CASES[0])

    def test_refresh_preserves_archive_on_invalid_or_failed_download(self):
        for failure in ['semantics', 'late-network']:
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                data = root/'Scripts/observer-event-data'
                shutil.copytree(references.DATA, data)
                before = {p.relative_to(data): p.read_bytes() for p in data.rglob('*') if p.is_file()}
                calls = 0
                recipes = sorted((data/'sources').rglob('*.query.json'))
                def download(*args, **kwargs):
                    nonlocal calls
                    path = recipes[calls].with_name(recipes[calls].name.replace('.query.json', '.json'))
                    calls += 1
                    if failure == 'late-network' and calls == len(recipes):
                        raise OSError('late network failure')
                    document = json.loads(path.read_bytes())
                    if failure == 'semantics' and 'result' in document:
                        document['result'] = document['result'].replace('Sun (10)', 'Earth (399)')
                    return io.BytesIO(json.dumps(document).encode())
                with mock.patch.object(references, 'ROOT', root), mock.patch.object(references, 'DATA', data), mock.patch.object(references, 'FIXTURE', data/'reference-fixtures.json'), mock.patch.object(references.urllib.request, 'urlopen', download), mock.patch('sys.argv', ['capture', '--download']):
                    with self.assertRaises((ValueError, OSError)):
                        references.main()
                self.assertEqual(before, {p.relative_to(data): p.read_bytes() for p in data.rglob('*') if p.is_file()})

    def test_auxiliary_query_semantics(self):
        original = references.read_source
        for name in ['horizons-sd-2000-01-03.json', 'polar-primary.json']:
            for key, value in [('COMMAND', "'399'"), ('CENTER', "'coord@10'"), ('SITE_COORD', "'1,2,3'"), ('TIME_TYPE', "'TDB'"), ('APPARENT', "'REFRACTED'"), ('COORD_TYPE', "'CYLINDRICAL'"), ('QUANTITIES', "'1'"), ('TLIST', "'2451545.0'")]:
                with self.subTest(name=name, key=key):
                    def changed(path):
                        document, recipe = original(path)
                        if path.name == name: recipe[key] = value
                        return document, recipe
                    with mock.patch.object(references, 'read_source', changed), self.assertRaises(ValueError):
                        references.fixture()

    def test_auxiliary_response_metadata_and_usno_recipe(self):
        original = references.read_source
        cases = [('polar-primary.json', 'Center body name: Earth (399)', 'Center body name: Sun (10)'),
                 ('polar-primary.json', 'NO (AIRLESS)', 'YES (REFRACTED)'),
                 ('horizons-sd-2000-01-03.json', 'Sun (10)', 'Earth (399)'),
                 ('horizons-sd-2000-01-03.json', 'Center geodetic : 0.0, 0.0, 0.0', 'Center geodetic : 0.0, 1.0, 0.0'),
                 ('horizons-sd-2000-01-03.json', 'Date_________JDUT', 'Date_________JDTT')]
        for name, old, new in cases:
            with self.subTest(name=name, old=old):
                def changed(path):
                    document, recipe = original(path)
                    if path.name == name:
                        self.assertIn(old, document['result'])
                        document['result'] = document['result'].replace(old, new, 1)
                    return document, recipe
                with mock.patch.object(references, 'read_source', changed), self.assertRaises(ValueError):
                    references.fixture()
        for field in ['query', 'date', 'site', 'time', 'target']:
            def changed_usno(path):
                document, recipe = original(path)
                if path.name == 'usno-sd-2000-01-03.json':
                    if field == 'query': recipe['url'] = recipe['url'].replace('coords=0%2C0', 'coords=1%2C0')
                    if field == 'date': document['properties']['day'] = 4
                    if field == 'site': document['geometry']['coordinates'][0] = 1
                    if field == 'time': document['properties']['time'] = '13:00:00'
                    if field == 'target': document['properties']['data'][0]['object'] = 'Earth'
                return document, recipe
            with self.subTest(field=field), mock.patch.object(references, 'read_source', changed_usno), self.assertRaises(ValueError):
                references.fixture()

    def test_valid_refresh_publishes_complete_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root/'Scripts/observer-event-data'
            shutil.copytree(references.DATA, data)
            recipes = sorted((data/'sources').rglob('*.query.json'))
            payloads = [json.dumps(json.loads(p.with_name(p.name.replace('.query.json', '.json')).read_bytes())).encode() for p in recipes]
            with mock.patch.object(references, 'ROOT', root), mock.patch.object(references, 'DATA', data), mock.patch.object(references, 'FIXTURE', data/'reference-fixtures.json'), mock.patch.object(references.urllib.request, 'urlopen', side_effect=[io.BytesIO(b) for b in payloads]), mock.patch('sys.argv', ['capture', '--download']):
                references.main()
                self.assertEqual(references.fixture(), json.loads((data/'reference-fixtures.json').read_bytes()))
                for path, payload in zip(recipes, payloads):
                    self.assertEqual(json.loads(path.read_bytes())['_responseSHA256'], hashlib.sha256(payload).hexdigest())

    def test_fuzz_corpus_bindings(self):
        for name, digest in [('fixed-riseset-infinite-limit', '6d88cbde5da0ca9da353a20326d522e27c88dde3714498e5d4bc6929753a4e02'),
                             ('fixed-riseset-stall', 'ca78b6218e4c663f595a10afa5cb38a76a73ba5d15e81f3923c133d3454305c8')]:
            self.assertEqual(hashlib.sha256((ROOT/'Fuzzing/corpus'/name).read_bytes()).hexdigest(), digest)


class ObserverRecordingTests(unittest.TestCase):
    retained_revision = '5632b59796ecf34d93cd4e6b490bb0b4c5e63a85'

    def setUp(self):
        self.captures = json.loads(record.CAPTURES.read_bytes())
        self.evidence = json.loads(record.OUTPUT.read_bytes())

    def test_direct_input_source_bindings(self):
        hashes = record.sources()
        for name in ['Observer', 'CelestialBody']:
            self.assertIn(f'Sources/AstronomyKit/{name}.swift', hashes)

    def test_recorded_source_and_scale_relations(self):
        for section, field, change in [('points', 'ut', 1), ('polar', 'nativeAltitudeDegrees', 2), ('usno', 'nativeUT', 1), ('usno', 'referenceTT', 1), ('semidiameters', 'nominalDegrees', .1)]:
            with self.subTest(section=section, field=field):
                changed = copy.deepcopy(self.captures)
                changed['debug'][section][0][field] += change
                with self.assertRaises(ValueError): record.validate_measurements(changed['debug'])
                with self.assertRaises(ValueError): record.evidence(changed, {})

    def test_cross_configuration_observations_must_agree(self):
        changed = copy.deepcopy(self.captures)
        changed['debug']['polar'][0]['nativeApparentICRFDeg'][0] += .01
        record.validate_measurements(changed['debug'])
        with self.assertRaisesRegex(ValueError, 'Debug/Release'):
            record.evidence(changed, {})

    def test_complete_recording(self):
        self.assertEqual(record.evidence(self.captures, record.sources()), self.evidence)

    def current_engine_changes_are_eligible(self):
        changed = set(record.git_bytes('diff', '--name-only', self.retained_revision, '--', 'Sources/AstronomyKit/Engine').decode().splitlines())
        original = record.allowed_retained_usno_engine_change
        return mock.patch.object(record, 'allowed_retained_usno_engine_change', side_effect=lambda path: path in changed or original(path))

    def test_fresh_debug_usno_provenance_is_minimal_and_binds_rows(self):
        provenance = self.captures['debugUSNOProvenance']
        self.assertEqual(set(provenance), {'kind', 'runtimeRevision', 'rowsSHA256'})
        self.assertEqual(provenance['kind'], 'fresh')
        for field, value in [('runtimeRevision', 'bad'), ('rowsSHA256', '0' * 64)]:
            changed = copy.deepcopy(self.captures)
            changed['debugUSNOProvenance'][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'fresh Debug USNO provenance differs'):
                record.validate_debug_usno_provenance(changed)

    def test_retained_debug_usno_names_its_revision_and_exact_rows(self):
        # Eligibility has separate negative controls; isolate the provenance path from the live branch diff.
        with self.current_engine_changes_are_eligible():
            rows, provenance = record.retained_debug_usno(self.retained_revision)
        prior = json.loads(record.git_bytes('show', f'{self.retained_revision}:{record.CAPTURES.relative_to(record.ROOT)}'))
        self.assertEqual(rows, prior['debug']['usno'])
        self.assertEqual(provenance['sourceRevision'], self.retained_revision)
        self.assertEqual(provenance['kind'], 'retainedUnchangedInput')
        changed = copy.deepcopy(self.captures)
        changed['debugUSNOProvenance'] = provenance
        changed['debugUSNOProvenance']['rowsSHA256'] = '0' * 64
        with self.current_engine_changes_are_eligible(), self.assertRaisesRegex(ValueError, 'provenance differs'):
            record.validate_debug_usno_provenance(changed)

    def test_retained_debug_usno_rejects_unrelated_engine_changes(self):
        original = record.git_bytes
        for path in [
            'Sources/AstronomyKit/Engine/Orientation/EngineRefraction.swift',
            'Sources/AstronomyKit/Engine/Events/EngineObserverEvents.swift',
        ]:
            def changed_engine(*arguments):
                if arguments[:3] == ('diff', '--name-only', self.retained_revision):
                    return (path + '\n').encode()
                return original(*arguments)
            with self.subTest(path=path), mock.patch.object(record, 'git_bytes', side_effect=changed_engine):
                with self.assertRaisesRegex(ValueError, 'runtime inputs changed'):
                    record.retained_debug_usno(self.retained_revision)

    def test_retained_debug_usno_rejects_changed_recorded_source(self):
        original = record.git_bytes
        evidence_spec = f'{self.retained_revision}:{record.OUTPUT.relative_to(record.ROOT)}'
        def changed_source(*arguments):
            data = original(*arguments)
            if arguments == ('show', evidence_spec):
                value = json.loads(data)
                value['sourceSHA256']['Sources/AstronomyKit/Observer.swift'] = '0' * 64
                return json.dumps(value).encode()
            return data
        with self.current_engine_changes_are_eligible(), mock.patch.object(record, 'git_bytes', side_effect=changed_source):
            with self.assertRaisesRegex(ValueError, 'source differs'):
                record.retained_debug_usno(self.retained_revision)

    def test_each_published_measurement_section_is_validated(self):
        for section, field in [('usno', 'residualSeconds'), ('points', 'altitudeErrorArcminutes'),
                               ('semidiameters', 'opticalResidualDegrees'), ('polar', 'sourceOpticalResidualDegrees')]:
            with self.subTest(section=section):
                changed = copy.deepcopy(self.captures['debug'])
                changed[section][0][field] += 1
                with self.assertRaises(ValueError):
                    record.validate_measurements(changed)

    def test_no_omitted_duplicate_shifted_or_nonfinite_observations(self):
        for mutation in ['omit', 'duplicate', 'time', 'direction', 'nan']:
            with self.subTest(mutation=mutation):
                changed = copy.deepcopy(self.captures['debug'])
                if mutation == 'omit': changed['usno'].pop()
                if mutation == 'duplicate': changed['usno'][1] = changed['usno'][0]
                if mutation == 'time': changed['usno'][0]['referenceUT'] += 1/86400
                if mutation == 'direction': changed['usno'][0]['direction'] = 'invalid'
                if mutation == 'nan': changed['points'][0]['hourAngleHours'] = float('nan')
                with self.assertRaises(ValueError): record.validate_measurements(changed)

    def test_all_recorded_metadata_and_resources_are_compared(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'mutated.json'
            for key in self.evidence:
                with self.subTest(key=key):
                    changed = copy.deepcopy(self.evidence)
                    changed[key] = None
                    path.write_text(json.dumps(changed))
                    with mock.patch.object(record, 'OUTPUT', path), mock.patch('sys.argv', ['record-observer-event-evidence.py', '--check']):
                        with self.assertRaisesRegex(SystemExit, 'recorded observer evidence differs'):
                            record.main()
        changed = copy.deepcopy(self.captures)
        changed['resources']['seconds']['sunRise'] = -1
        with self.assertRaises(ValueError): record.evidence(changed, {})


if __name__ == '__main__':
    unittest.main()
