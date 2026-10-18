import base64
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "generate_galilean_jup365_swift", ROOT / "Scripts/generate-galilean-jup365-swift.py"
)
generator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generator)


class GalileanJup365SwiftGeneratorTests(unittest.TestCase):
    def test_record_lines_round_trip_without_crossing_boundaries(self):
        payload = bytes(range(18))
        lines = generator.record_lines(payload, record_bytes=6)
        self.assertEqual(3, len(lines))
        self.assertTrue(all(len(line) == 8 for line in lines))
        self.assertEqual(payload, b"".join(base64.b64decode(line) for line in lines))

    def test_record_lines_reject_partial_record(self):
        with self.assertRaisesRegex(ValueError, "whole records"):
            generator.record_lines(b"12345", record_bytes=3)

    def test_generated_inventory_reassembles_every_qualified_payload(self):
        manifest, payloads = generator.load_inputs()
        outputs = generator.render(manifest, payloads)
        generator.verify_outputs(outputs, manifest, payloads)
        swift = b"".join(outputs.values())
        for name, payload in payloads.items():
            self.assertIn(manifest["components"][name]["sha256"].encode(), swift)
            self.assertGreater(len(payload), 0)

    def test_failed_capture_preserves_accepted_directory(self):
        manifest, payloads = generator.load_inputs()
        outputs = generator.render(manifest, payloads)
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            marker = destination / "accepted.swift"
            marker.write_bytes(b"accepted")
            broken = dict(outputs)
            first = next(path for path in broken if path.name != generator.INDEX_NAME)
            broken[first] = broken[first].replace(b"A", b"!", 1)
            with self.assertRaises(ValueError):
                generator.publish(destination, broken, manifest, payloads)
            self.assertEqual([marker], list(destination.iterdir()))
            self.assertEqual(b"accepted", marker.read_bytes())

    def test_check_detects_stale_generated_file(self):
        manifest, payloads = generator.load_inputs()
        outputs = generator.render(manifest, payloads)
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            generator.publish(destination, outputs, manifest, payloads)
            (destination / generator.INDEX_NAME).write_text("stale")
            with self.assertRaisesRegex(ValueError, "generated jup365 Swift differs"):
                generator.check(destination, outputs)


if __name__ == "__main__":
    unittest.main()
