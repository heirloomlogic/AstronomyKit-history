import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    'generated_binary_resource', Path(__file__).with_name('generated-binary-resource.py'))
binary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(binary)


class GeneratedBinaryResourceTests(unittest.TestCase):
    def test_roundtrip_and_fail_closed_checks(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(binary, 'RESOURCE_DIRECTORY', Path(directory)):
            expected = {'test-one.bin': b'abc'}
            binary.publish(expected, ['test-'], False)
            binary.publish(expected, ['test-'], True)
            path = Path(directory)/'test-one.bin'
            path.write_bytes(b'abd')
            with self.assertRaisesRegex(SystemExit, 'resource differs'):
                binary.publish(expected, ['test-'], True)
            path.unlink()
            with self.assertRaisesRegex(SystemExit, 'file set differs'):
                binary.publish(expected, ['test-'], True)
            path.write_bytes(b'abc')
            (Path(directory)/'test-retired.bin').write_bytes(b'x')
            with self.assertRaisesRegex(SystemExit, 'file set differs'):
                binary.publish(expected, ['test-'], True)
            binary.publish(expected, ['test-'], False)
            self.assertEqual(['test-one.bin'], sorted(p.name for p in Path(directory).iterdir()))

    def test_descriptor_records_exact_size_and_digest(self):
        value = binary.descriptor('sample', b'abc')
        self.assertIn('byteCount: 3', value)
        self.assertIn('ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad', value)
        for name, count, digest in [('', 3, 'a'*64), ('sample', 0, 'a'*64), ('sample', 3, 'short')]:
            with self.assertRaisesRegex(ValueError, 'malformed'):
                binary.descriptor_from_digest(name, count, digest)


if __name__ == '__main__':
    unittest.main()
