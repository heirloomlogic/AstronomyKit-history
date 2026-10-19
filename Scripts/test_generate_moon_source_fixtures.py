import importlib.util
import hashlib
import json
import unittest
from pathlib import Path


class MoonSourceFixtureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec = importlib.util.spec_from_file_location("moon_fixtures", Path(__file__).with_name("generate-moon-source-fixtures.py"))
        cls.tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.tool)

    def test_pinned_fixture_bytes(self):
        self.tool.check()

    def test_reference_fixtures_pin_the_source_evidence_and_include_interior_rates(self):
        data = json.loads((self.tool.ROOT / "Scripts/moon-data/de441-native-fixtures.json").read_bytes())
        self.assertEqual(hashlib.sha256(self.tool.MANIFEST.read_bytes()).hexdigest(), data["sourceEvidenceSHA256"])
        self.assertEqual(273, data["recordCount"])
        self.assertEqual(1365, len(data["rows"]))
        self.assertEqual({-1, -.5, 0, .5, 1}, {row["x"] for row in data["rows"]})


    def test_changed_fixture_is_rejected_before_publication(self):
        raw = self.tool.OUTPUT.read_bytes()
        with self.assertRaisesRegex(ValueError, "digest"):
            self.tool.check(raw + b" ")

    def test_central_generator_preserves_nested_full_precision_source(self):
        import shutil
        import subprocess
        import sys
        import tempfile
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = json.loads((self.tool.ROOT / "Scripts/moon-data/manifest.json").read_bytes())
            for relative in ["Scripts/generate-moon-tables.py", "Scripts/generated-binary-resource.py", "Scripts/moon-data/manifest.json", *manifest["files"]]:
                destination = root / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(self.tool.ROOT / relative, destination)
            sentinel = root / "Sources/AstronomyKit/Engine/Moon/Generated/DE441Full/MoonDE441Full000.swift"
            sentinel.parent.mkdir(parents=True)
            sentinel.write_bytes(b"complete binary64 source remains owned by its own generator")
            subprocess.run([sys.executable, str(root / "Scripts/generate-moon-tables.py")], check=True, capture_output=True)
            self.assertEqual(sentinel.read_bytes(), b"complete binary64 source remains owned by its own generator")
            subprocess.run([sys.executable, str(root / "Scripts/generate-moon-tables.py"), "--check"], check=True, capture_output=True)
