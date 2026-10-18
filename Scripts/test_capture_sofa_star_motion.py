import importlib.util
import json
import math
from pathlib import Path
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


def load_capture():
    path = ROOT / "Scripts/capture-sofa-star-motion.py"
    spec = importlib.util.spec_from_file_location("capture_sofa_star_motion", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CaptureSofaStarMotionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.capture = load_capture()
        cls.archive = json.loads(cls.capture.OUTPUT.read_text()) if cls.capture.OUTPUT.exists() else None

    def test_archive_has_canonical_catalog_and_result_identities(self):
        if self.archive is None:
            self.skipTest("capture artifact has not been generated")
        self.capture.validate_archive(self.archive)
        self.assertEqual(8, len(self.archive["rows"]))
        self.assertEqual(self.capture.EXPECTED_SOURCE_IDS, [row["source_id"] for row in self.archive["catalog"]["rows"]])

    def test_duplicate_result_cannot_replace_a_missing_identity(self):
        if self.archive is None:
            self.skipTest("capture artifact has not been generated")
        changed = json.loads(json.dumps(self.archive))
        changed["rows"][-1] = changed["rows"][0]
        with self.assertRaisesRegex(ValueError, "inventory"):
            self.capture.validate_archive(changed)

    def test_nonfinite_result_is_rejected(self):
        if self.archive is None:
            self.skipTest("capture artifact has not been generated")
        changed = json.loads(json.dumps(self.archive))
        changed["rows"][0]["rightAscensionRadians"] = math.nan
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            self.capture.validate_archive(changed)

    def test_missing_catalog_value_is_rejected(self):
        source = self.capture.CATALOG.read_text().replace(",546.975939730948,", ",,").encode()
        with tempfile.TemporaryDirectory() as temporary:
            query = Path(temporary) / "query.json"
            recipe = json.loads(self.capture.QUERY.read_text())
            recipe["responseSHA256"] = self.capture.hashlib.sha256(source).hexdigest()
            query.write_text(json.dumps(recipe))
            with mock.patch.object(self.capture, "QUERY", query):
                with self.assertRaisesRegex(ValueError, "missing or nonfinite"):
                    self.capture.validate_catalog_bytes(source)

    def test_failed_refresh_preserves_accepted_catalog(self):
        with tempfile.TemporaryDirectory() as temporary:
            catalog = Path(temporary) / "gaia.csv"
            catalog.write_text("accepted\n")
            with (
                mock.patch.object(self.capture, "CATALOG", catalog),
                mock.patch.object(self.capture, "download_catalog", side_effect=RuntimeError("network failed")),
            ):
                with self.assertRaisesRegex(RuntimeError, "network failed"):
                    self.capture.refresh_catalog()
            self.assertEqual("accepted\n", catalog.read_text())


if __name__ == "__main__":
    unittest.main()
