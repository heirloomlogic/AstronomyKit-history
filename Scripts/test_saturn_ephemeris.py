import base64
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


a = module('saturn_assessment', 'assess-saturn-apsides.py')
g = module('saturn_generator', 'generate-saturn-tables.py')


class SaturnEphemerisTests(unittest.TestCase):
    def test_generated_source_identifies_the_binary_without_embedding_it(self):
        body = dict(startJDTDB=2451545, recordDays=1, recordCount=1, coefficientCount=1, encoding='float64')
        data = base64.b64decode('ABSK')
        source, name = g.render(data, 'offset', body)
        self.assertEqual('saturn-offset.bin', name)
        self.assertIn(hashlib.sha256(data).hexdigest(), source)
        self.assertNotIn('"""', source)

    def test_both_packed_generators_check_without_retired_moon_generator(self):
        for filename in ('generate-saturn-tables.py', 'generate-pluto-de441.py'):
            with self.subTest(generator=filename):
                result = subprocess.run([sys.executable, str(g.ROOT/'Scripts'/filename), '--check'], capture_output=True, text=True)
                self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_quantization_encloses_position_and_analytic_rate(self):
        records = [(100., 1.5, [(300.123456789, -.112345678, .0987654321, -.0032109876)] * 3)]
        data, rounded, bounds = a.quantize(records, 'float32')
        self.assertEqual(48, len(data))
        for i in range(101):
            exact = a.p.evaluate(records[0][2], i / 50 - 1, 1.5)
            compact = a.p.evaluate(rounded[0][2], i / 50 - 1, 1.5)
            for axis, key in enumerate(('positionBoundKm', 'rateBoundKmPerTDBDay')):
                self.assertLessEqual(a.d.norm([x-y for x, y in zip(exact[axis], compact[axis])]), bounds[key])
        full, _, exact_bounds = a.quantize(records, 'float64')
        self.assertEqual(96, len(full))
        self.assertLess(exact_bounds['positionBoundKm'], 1e-150)
        self.assertLess(exact_bounds['rateBoundKmPerTDBDay'], 1e-150)

    def test_cached_satellite_rejects_corruption_identity_length_and_pinned_digest(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '0-3.bin'
            data = b'abcd'
            path.write_bytes(data)
            receipt = path.with_suffix('.json')
            digest = hashlib.sha256(data).hexdigest()
            receipt.write_text(json.dumps(dict(sha256=digest, identity=a.SAT_ID)))
            self.assertEqual(data, a.SatelliteReader(directory, {'0-3': digest}).read(0, 4))
            with self.assertRaisesRegex(ValueError, 'digest'):
                a.SatelliteReader(directory, {'0-3': '0'*64}).read(0, 4)
            path.write_bytes(b'bad')
            with self.assertRaisesRegex(ValueError, 'identity or digest'):
                a.SatelliteReader(directory).read(0, 4)
            receipt.write_text(json.dumps(dict(sha256=hashlib.sha256(b'bad').hexdigest(), identity=a.SAT_ID)))
            with self.assertRaisesRegex(ValueError, 'length'):
                a.SatelliteReader(directory).read(0, 4)
            receipt.write_text(json.dumps(dict(sha256=hashlib.sha256(b'bad').hexdigest(), identity=[])))
            with self.assertRaisesRegex(ValueError, 'identity'):
                a.SatelliteReader(directory).read(0, 4)

    def test_native_measurement_bindings_and_negative_controls(self):
        recorder = module('planetary_recorder', 'record-planetary-event-evidence.py')
        evidence = json.loads(recorder.OUTPUT.read_bytes())
        self.assertEqual(recorder.source_hashes(), evidence['sourceSHA256'])
        for configuration in ['debug', 'release']:
            recorder.validate(evidence[configuration])
        changed = copy.deepcopy(evidence['debug'])
        changed['saturn'][0]['signedTimingErrorSeconds'] = 60
        with self.assertRaisesRegex(ValueError, 'sixty-second'):
            recorder.validate(changed)
        changed = copy.deepcopy(evidence['debug'])
        changed['source'][0]['sourceLowerJDTT'] += 1
        with self.assertRaisesRegex(ValueError, 'bracket'):
            recorder.validate(changed)

    def test_rejects_corrupt_recorded_sections(self):
        recorder = module('planetary_recorder_negative', 'record-planetary-event-evidence.py')
        original = json.loads(recorder.OUTPUT.read_bytes())
        for configuration in ['debug', 'release']:
            changed = copy.deepcopy(original[configuration])
            changed['parity']['planetaryApsisParitySeconds'] = 999
            with self.assertRaises(ValueError):
                recorder.validate(changed)
        for key, value in [('resources', {}), ('buildSeconds', {'debug': -1, 'release': 1})]:
            changed = copy.deepcopy(original)
            changed[key] = value
            with self.assertRaises(ValueError):
                recorder.validate_recording(changed)

    def test_every_recorded_observation_is_bound_to_raw_capture(self):
        recorder = module('planetary_recorder_integrity', 'record-planetary-event-evidence.py')
        original = json.loads(recorder.OUTPUT.read_bytes())
        recorder.validate_recording(original)
        for path in [('debug', 'parity', 'maximumElongationParitySeconds'), ('release', 'parity', 'apsisEvents', 0, 'jdtt'), ('debug', 'coefficients', 'maximumPositionKm'), ('resources', 'seconds', 'center'), ('resources', 'checksum'), ('buildSeconds', 'debug'), ('releaseExecutableBytes',), ('resourcePayloadBytes',)]:
            changed = copy.deepcopy(original)
            cursor = changed
            for key in path[:-1]:
                cursor = cursor[key]
            cursor[path[-1]] += 0.01
            with self.assertRaises(ValueError, msg=str(path)):
                recorder.validate_recording(changed)

    def test_saturn_storage_uses_verified_mapped_resources(self):
        recorder = module('planetary_recorder_storage', 'record-planetary-event-evidence.py')
        expected = sum(len(recorder.model_resource.payload((recorder.ROOT/path).read_text())) for path in recorder.SATURN_RESOURCE_SOURCES)
        self.assertEqual(expected, recorder.mapped_resource_bytes())
        with tempfile.TemporaryDirectory() as directory:
            resources = Path(directory)
            names = []
            for source in recorder.SATURN_RESOURCE_SOURCES:
                match = recorder.model_resource.DESCRIPTOR.search((recorder.ROOT/source).read_text())
                names.append(match[1]+'.bin')
            for name in names:
                shutil.copyfile(recorder.model_resource.RESOURCE_DIRECTORY/name, resources/name)
            data = bytearray((resources/names[0]).read_bytes());data[0] ^= 1;(resources/names[0]).write_bytes(data)
            with self.assertRaisesRegex(ValueError, 'digest differs'):
                recorder.mapped_resource_bytes(resource_directory=resources)

    def test_check_command_rejects_corrupt_parity_and_resource_json(self):
        recorder = module('planetary_recorder_cli', 'record-planetary-event-evidence.py')
        original = json.loads(recorder.OUTPUT.read_bytes())
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'changed.json'
            for field in ['parity', 'resources']:
                changed = copy.deepcopy(original)
                if field == 'parity':
                    changed['release']['parity']['planetaryApsisParitySeconds'] = 999
                else:
                    changed['resources']['seconds']['center'] *= 2
                output.write_text(json.dumps(changed))
                with patch.object(recorder, 'OUTPUT', output), patch.object(sys, 'argv', ['recorder', '--check']):
                    with self.assertRaises(ValueError):
                        recorder.main()

    def test_packed_payload_identity_and_generator_coexistence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = json.loads((g.ROOT/'Scripts/planet-data/manifest.json').read_bytes())
            generated = Path('Sources/AstronomyKit/Engine/Planets/Generated')
            paths = ['Scripts/generate-planet-tables.py', 'Scripts/generate-saturn-tables.py', 'Scripts/generated-binary-resource.py', 'Scripts/packed-table-payload.py', 'Scripts/planet-data/manifest.json', 'Scripts/saturn-data/assessment.json']
            paths += list(manifest['files'])
            paths += [str(p.relative_to(g.ROOT)) for p in (g.ROOT/generated).rglob('*.swift')]
            paths += [str(p.relative_to(g.ROOT)) for p in g.binary.RESOURCE_DIRECTORY.glob('planet-polynomial-*.bin')]
            paths += [str(p.relative_to(g.ROOT)) for p in g.binary.RESOURCE_DIRECTORY.glob('saturn-*.bin')]
            for relative in paths:
                target = root/relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(g.ROOT/relative, target)
            binaries = root/'binaries'
            binaries.mkdir()
            candidate = json.loads(g.MANIFEST.read_bytes())['candidates']['float64']
            for target, name in g.BODIES.items():
                body = candidate['bodies'][str(target)]
                data = (g.binary.RESOURCE_DIRECTORY/f'saturn-{name}.bin').read_bytes()
                g.common.validate(data, body)
                with self.assertRaisesRegex(ValueError, 'digest'):
                    g.common.validate(bytes([data[0] ^ 1]) + data[1:], body)
                (binaries/f'float64-{target}.bin').write_bytes(data)
            resource_root = root/g.binary.RESOURCE_DIRECTORY.relative_to(g.ROOT)
            tracked = list((root/generated).rglob('*.swift')) + list(resource_root.glob('planet-polynomial-*.bin')) + list(resource_root.glob('saturn-*.bin'))
            expected = {p.relative_to(root): hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked}
            stale = root/generated/'Saturn/Retired.swift'
            stale.write_text('// obsolete owned output\n')
            nested_stale = stale.parent/'Retired/Nested.swift'
            nested_stale.parent.mkdir()
            nested_stale.write_text('// obsolete nested owned output\n')
            check = subprocess.run([sys.executable, str(root/'Scripts/generate-saturn-tables.py'), '--check'], capture_output=True, text=True)
            self.assertNotEqual(0, check.returncode, 'stale owned output must fail check')
            regenerate = subprocess.run([sys.executable, str(root/'Scripts/generate-saturn-tables.py'), '--binaries', str(binaries)], capture_output=True, text=True)
            self.assertEqual(0, regenerate.returncode, regenerate.stdout+regenerate.stderr)
            self.assertFalse(stale.exists())
            self.assertFalse(nested_stale.exists())
            for command in [('generate-planet-tables.py', '--check'), ('generate-planet-tables.py',), ('generate-saturn-tables.py', '--check'), ('generate-saturn-tables.py', '--binaries', str(binaries)), ('generate-planet-tables.py', '--check'), ('generate-saturn-tables.py', '--check')]:
                if '--binaries' in command:
                    shutil.rmtree(root/generated/'Saturn')
                result = subprocess.run([sys.executable, str(root/'Scripts'/command[0]), *command[1:]], capture_output=True, text=True)
                self.assertEqual(0, result.returncode, result.stdout+result.stderr)
                tracked = list((root/generated).rglob('*.swift')) + list(resource_root.glob('planet-polynomial-*.bin')) + list(resource_root.glob('saturn-*.bin'))
                actual = {p.relative_to(root): hashlib.sha256(p.read_bytes()).hexdigest() for p in tracked}
                self.assertEqual(expected, actual)


if __name__ == '__main__':
    unittest.main()
