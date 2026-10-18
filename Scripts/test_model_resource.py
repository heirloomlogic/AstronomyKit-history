import hashlib
import importlib.util
from pathlib import Path
import tempfile
import unittest


SPEC = importlib.util.spec_from_file_location('model_resource', Path(__file__).with_name('model_resource.py'))
resource = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(resource)


class ModelResourceTests(unittest.TestCase):
    def descriptor(self, data=b'abc', name='sample'):
        return f'Engine.TableResource(name: "{name}", byteCount: {len(data)}, sha256: "{hashlib.sha256(data).hexdigest()}")'

    def test_reads_only_the_exact_verified_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'sample.bin').write_bytes(b'abc')
            self.assertEqual(b'abc', resource.payload(self.descriptor(), root))

    def test_missing_corrupt_malformed_and_duplicate_mappings_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            descriptor = self.descriptor()
            with self.assertRaisesRegex(ValueError, 'unreadable'):
                resource.payload(descriptor, root)
            (root/'sample.bin').write_bytes(b'abd')
            with self.assertRaisesRegex(ValueError, 'digest differs'):
                resource.payload(descriptor, root)
            (root/'sample.bin').write_bytes(b'ab')
            with self.assertRaisesRegex(ValueError, 'byte count differs'):
                resource.payload(descriptor, root)
            for source in ['', descriptor.replace('sha256:', 'digest:'), descriptor+'\n'+descriptor, descriptor.replace('sample', '../sample')]:
                with self.subTest(source=source), self.assertRaisesRegex(ValueError, 'missing, duplicated, or malformed'):
                    resource.payload(source, root)


if __name__ == '__main__':
    unittest.main()
