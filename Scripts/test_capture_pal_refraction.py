import copy
import importlib.util
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

PATH = Path(__file__).with_name("capture-pal-refraction.py")
SPEC = importlib.util.spec_from_file_location("capture_pal_refraction", PATH)
assert SPEC and SPEC.loader
capture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(capture)


class CapturePALRefractionTests(unittest.TestCase):
    def archive(self):
        return json.loads(capture.OUTPUT.read_text())

    def test_committed_archive_is_complete(self):
        archive = self.archive()
        capture.validate_archive(archive)
        self.assertEqual(len(archive["rows"]), 180)
        self.assertEqual(len(archive["officialRegressions"]), 2)

    def test_duplicate_row_cannot_replace_a_missing_identity(self):
        archive = self.archive()
        archive["rows"][-1] = copy.deepcopy(archive["rows"][0])
        with self.assertRaisesRegex(ValueError, "row inventory"):
            capture.validate_archive(archive)

    def test_official_regressions_reject_missing_or_nonfinite_results(self):
        for index in range(2):
            for value in (None, math.nan, math.inf, -math.inf):
                with self.subTest(index=index, value=value):
                    archive = self.archive()
                    if value is None:
                        del archive["officialRegressions"][index]["actualRadians"]
                    else:
                        archive["officialRegressions"][index]["actualRadians"] = value
                    with self.assertRaisesRegex(ValueError, "official regression value"):
                        capture.validate_archive(archive)

    def test_changed_bound_source_is_rejected(self):
        archive = self.archive()
        archive["sourceSHA256"][capture.OWNERS[0]] = "0" * 64
        with self.assertRaisesRegex(ValueError, "source digest"):
            capture.validate_archive(archive)

    def test_failed_capture_keeps_the_accepted_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "pal-reference.json"
            output.write_text('{"accepted": true}\n')
            before = output.read_bytes()
            with (
                mock.patch.object(capture, "OUTPUT", output),
                mock.patch.object(capture, "capture_archive", side_effect=RuntimeError("oracle failed")),
                mock.patch.object(sys, "argv", ["capture-pal-refraction.py", "--capture"]),
                self.assertRaisesRegex(RuntimeError, "oracle failed"),
            ):
                capture.main()
            self.assertEqual(output.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
