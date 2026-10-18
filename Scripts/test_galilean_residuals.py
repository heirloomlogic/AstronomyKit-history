import copy
import importlib.util
import json
import math
import subprocess
from pathlib import Path
import tempfile
import unittest

PATH = Path(__file__).with_name('galilean-residuals.py')


class GalileanResidualTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(PATH.is_file(), 'the committed replay checker is missing')
        spec = importlib.util.spec_from_file_location('galilean_residuals', PATH)
        self.tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.tool)

    def candidate(self):
        rows = []
        for reference in self.tool.references():
            tt, offset, rate = self.tool.clock(reference['julianDateTDB'])
            position = self.tool.eqj(reference['positionAU'])
            position[0] += .1 / self.tool.AU_KM
            velocity = [v * rate for v in self.tool.eqj(reference['velocityAUPerDay'])]
            velocity[1] += 2 / self.tool.AU_KM
            rows.append(dict(body=reference['body'], target=self.tool.MOONS[reference['body']], center=599,
                             frame='EQJ', epochScale='TDB', julianDateTDB=reference['julianDateTDB'],
                             ttDays=tt, tdbMinusTTSeconds=offset, tdbPerTTRate=rate,
                             positionAU=position, velocityAUPerTTDay=velocity))
        transitions = [
            dict(body=body, side=side, sampleCount=4097, maximumPositionCorrectionKm=.1,
                 maximumVelocityCorrectionKmPerTTDay=2)
            for side in ('beforeStart', 'afterEnd') for body in self.tool.MOONS
        ]
        return dict(schemaVersion=3, rows=rows, transitions=transitions)

    def test_all_rows_have_separate_absolute_metrics_and_exact_worst_epochs(self):
        report = self.tool.analyze(self.candidate())
        self.assertEqual(len(report['rows']), 104)
        self.assertEqual(set(report['moons']), set(self.tool.MOONS))
        for row in report['rows']:
            self.assertAlmostEqual(row['positionErrorKm'], .1, places=7)
            self.assertAlmostEqual(row['velocityErrorKmPerTTDay'], 2, places=7)
        for body, maxima in report['moons'].items():
            self.assertEqual(maxima['all']['count'], 26)
            self.assertEqual(maxima['bounded']['count'], 22)
            for subset in ('all', 'bounded'):
                eligible = [r for r in report['rows'] if r['body'] == body and (subset == 'all' or r['relativeTolerance'] is not None)]
                for field in ('positionErrorKm', 'velocityErrorKmPerTTDay'):
                    expected = max(eligible, key=lambda r: r[field])
                    self.assertEqual(maxima[subset][field], dict(value=expected[field], julianDateTDB=expected['julianDateTDB']))

    def test_identity_omission_duplicate_order_and_metadata_controls(self):
        mutations = [lambda r: r.pop(), lambda r: r.append(copy.deepcopy(r[0])),
                     lambda r: r.__setitem__(1, copy.deepcopy(r[0])), lambda r: r.reverse()]
        mutations += [lambda r, key=k, value=v: r[0].update({key: value}) for k, v in
                      [('body', 'europa'), ('target', 502), ('center', 5), ('frame', 'ICRF'),
                       ('epochScale', 'TT'), ('julianDateTDB', 2451545), ('ttDays', 1),
                       ('tdbPerTTRate', 1.01), ('tdbMinusTTSeconds', 0.1)]]
        for mutate in mutations:
            candidate = self.candidate()
            mutate(candidate['rows'])
            with self.subTest(mutation=mutate), self.assertRaises(ValueError):
                self.tool.analyze(candidate)

    def test_wrong_moon_hour_and_axes_numerical_controls(self):
        original = self.candidate()
        bounded = next(i for i, r in enumerate(self.tool.references()) if r['relativeTolerance'] is not None)
        for vector in ([0, 0, 0], original['rows'][bounded + 26]['positionAU'],
                       original['rows'][bounded]['positionAU'][::-1]):
            candidate = copy.deepcopy(original)
            candidate['rows'][bounded]['positionAU'] = vector
            with self.assertRaises(ValueError): self.tool.analyze(candidate)
        candidate = copy.deepcopy(original)
        candidate['rows'][bounded]['ttDays'] += 1 / 24
        with self.assertRaises(ValueError): self.tool.analyze(candidate)

    def test_nonfinite_and_wrong_shape_fail(self):
        for key, value in [('positionAU', [math.nan, 0, 0]), ('positionAU', [0, 0]),
                           ('velocityAUPerTTDay', [0, math.inf, 0])]:
            candidate = self.candidate()
            candidate['rows'][0][key] = value
            with self.assertRaises(ValueError): self.tool.analyze(candidate)

    def test_transition_inventory_identity_and_metrics_are_strict(self):
        mutations = [lambda rows: rows.pop(), lambda rows: rows.append(copy.deepcopy(rows[0])),
                     lambda rows: rows.__setitem__(1, copy.deepcopy(rows[0])),
                     lambda rows: rows[0].update(sampleCount=4096),
                     lambda rows: rows[0].update(maximumPositionCorrectionKm=math.nan),
                     lambda rows: rows[0].update(maximumVelocityCorrectionKmPerTTDay=-1)]
        for mutation in mutations:
            candidate = self.candidate()
            mutation(candidate['transitions'])
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.tool.analyze(candidate)

    def test_archive_recipe_header_epoch_and_fixture_mutations_fail(self):
        root = self.tool.ROOT
        paths = self.tool.archive_paths()
        with tempfile.TemporaryDirectory() as directory:
            temporary = Path(directory)
            for name in paths + [self.tool.FIXTURE]:
                destination = temporary / name
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes((root / name).read_bytes())
            query_path = temporary / paths[1]
            original_query = json.loads(query_path.read_bytes())
            for key, value in [('COMMAND', "'502'"), ('CENTER', "'500@5'"), ('REF_SYSTEM', "'FK4'"), ('TIME_TYPE', "'TT'"), ('TLIST', "'2451545'"), ('VEC_CORR', "'LT'")]:
                query = copy.deepcopy(original_query); query[key] = value
                query_path.write_text(json.dumps(query))
                with self.subTest(key=key), self.assertRaises(ValueError): self.tool.references(temporary)
            query_path.write_text(json.dumps(original_query))
            response_path = temporary / paths[0]
            original_response = response_path.read_bytes()
            for old, new in [('Io (501)', 'Europa (502)'), ('Jupiter (599)', 'Jupiter (5)'),
                             ('Reference frame : ICRF', 'Reference frame : FK4'), ('JDTDB', 'JDTT'),
                             ('GEOMETRIC cartesian states', 'ASTROMETRIC cartesian states')]:
                response = json.loads(original_response)
                response['result'] = response['result'].replace(old, new)
                data = json.dumps(response).encode()
                response_path.write_bytes(data)
                query = copy.deepcopy(original_query)
                query['_responseSHA256'] = self.tool.digest(data)
                query_path.write_text(json.dumps(query))
                with self.subTest(header=old), self.assertRaises(ValueError): self.tool.references(temporary)
            response_path.write_bytes(original_response); query_path.write_text(json.dumps(original_query))
            fixture_path = temporary / self.tool.FIXTURE
            fixture = json.loads(fixture_path.read_bytes())
            next(r for r in fixture['vectors'] if r['origin'] == 'jupiter')['positionAU'][0] += 1e-10
            fixture_path.write_text(json.dumps(fixture))
            with self.assertRaises(ValueError): self.tool.references(temporary)

    def test_exact_source_owner_and_hash_coverage(self):
        bindings = self.tool.source_hashes()
        self.tool.check_bindings(bindings)
        for path in ['Sources/AstronomyKit/Engine/Bodies/EngineJupiterMoons.swift',
                     'Sources/AstronomyKit/Engine/Moon/EngineTDB.swift',
                     'Sources/AstronomyKit/Engine/Moon/Generated/TDBTerms.swift',
                     'Tests/AstronomyKitTests/Engine/Bodies/EngineGalileanResidualCaptureTests.swift',
                     'Tests/AstronomyKitTests/Engine/Planets/PlanetTestSupport.swift']:
            self.assertIn(path, bindings)
        for mutate in [lambda b: b.pop(next(iter(b))), lambda b: b.update(extra='0' * 64),
                       lambda b: b.__setitem__(next(iter(b)), '0' * 64)]:
            changed = dict(bindings); mutate(changed)
            with self.assertRaises(ValueError): self.tool.check_bindings(changed)

    def test_stored_report_metric_and_capture_hash_controls(self):
        data = self.tool.record(self.candidate(), toolchain='test', sources=self.tool.source_hashes())
        self.tool.validate_record(data)
        for mutate in [lambda d: d['analysis']['rows'][0].update(positionErrorKm=99),
                       lambda d: d['capture']['rows'].pop(),
                       lambda d: d.update(captureSHA256='0' * 64),
                       lambda d: d['sourceSHA256'].pop(next(iter(d['sourceSHA256']))),
                       lambda d: d['sourceSHA256'].__setitem__('Package.swift', '0' * 64),
                       lambda d: d.update(schemaVersion=3)]:
            changed = copy.deepcopy(data); mutate(changed)
            with self.assertRaises(ValueError): self.tool.validate_record(changed)


if __name__ == '__main__':
    unittest.main()
