import importlib.util
import json
import math
from pathlib import Path
import tempfile
import unittest


PATH = Path(__file__).with_name("record-pluto-de441-evidence.py")


def module():
    spec = importlib.util.spec_from_file_location("record_pluto_de441_evidence", PATH)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


class PlutoDE441EvidenceRecorderTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(PATH.is_file(), "the Pluto-native evidence recorder is missing")
        self.tool = module()

    def test_source_inventory_is_explicit_and_keeps_conservative_runtime_owners(self):
        paths = self.tool.source_paths()
        self.assertEqual(list(self.tool.dependencies.paths("pluto-native")), paths)
        for path in ["Scripts/record-pluto-de441-evidence.py", "Scripts/test_record_pluto_de441_evidence.py", "Sources/AstronomyKit/Engine/Gravity/EnginePlutoDE441.swift", "Sources/AstronomyKit/Engine/Moon/EngineMoonEphemeris.swift"]:
            self.assertIn(path, paths)
        self.assertNotIn("Sources/AstronomyKit/Engine/NewUnrelatedEngineFile.swift", paths)

    def test_capture_validation_rejects_missing_nonfinite_and_configuration_drift(self):
        boundary = {"count": 273939, "maximumPositionKm": 1e-6, "maximumRateKmPerTDBDay": 1e-10}
        direct = {"bodySamples": 4320, "integratedSamples": 48, "maximumBodyPositionKm": 0.2, "maximumBodyRateKmPerTDBDay": 0.04, "maximumIntegratedAngleArcminutes": 1e-7, "maximumIntegratedPositionKm": 0.2, "maximumIntegratedRateKmPerTTDay": 0.01}
        references = {"rows": [{"angularDifferenceArcminutes": 0.1, "body": "pluto", "centerWeight": 1, "julianDateTDB": 2451545, "positionDifferenceKm": 0.2, "velocityDifferenceKmPerSecond": 1e-8}]}
        self.tool.validate_capture_pair(boundary, boundary, direct, direct, references, references)
        for changed in [dict(boundary, count=0), dict(boundary, maximumPositionKm=math.nan), {"count": 273939}]:
            with self.subTest(changed=changed), self.assertRaises(ValueError):
                self.tool.validate_capture_pair(boundary, changed, direct, direct, references, references)
        changed = json.loads(json.dumps(references))
        changed["rows"][0]["positionDifferenceKm"] += 1
        with self.assertRaisesRegex(ValueError, "Debug and Release"):
            self.tool.validate_capture_pair(boundary, boundary, direct, direct, references, changed)

    def test_reference_summary_preserves_center_semantics(self):
        rows = [
            {"angularDifferenceArcminutes": 0.1, "body": "pluto", "centerWeight": 1, "julianDateTDB": 1, "positionDifferenceKm": 2, "velocityDifferenceKmPerSecond": 3},
            {"angularDifferenceArcminutes": 0.2, "body": "pluto", "centerWeight": 0.5, "julianDateTDB": 2, "positionDifferenceKm": 4, "velocityDifferenceKmPerSecond": 5},
            {"angularDifferenceArcminutes": 0.3, "body": "pluto-barycenter", "centerWeight": 0, "julianDateTDB": 3, "positionDifferenceKm": 6, "velocityDifferenceKmPerSecond": 7},
        ]
        summary = self.tool.reference_summary(rows)
        self.assertEqual(1, summary["centralCenter"]["count"])
        self.assertEqual(4, summary["outerOrBlendedCenter"]["positionDifferenceKm"])
        self.assertEqual(0.3, summary["outerBarycenter"]["angularDifferenceArcminutes"])

    def test_size_output_and_atomic_publication(self):
        self.assertEqual(1234, self.tool.cstring_bytes("Section (__TEXT, __cstring): 1234\ntotal 5678\n"))
        with self.assertRaises(ValueError):
            self.tool.cstring_bytes("total 5678\n")
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "evidence.json"
            output.write_text("old\n")
            self.tool.publish(output, {"schemaVersion": 2, "value": 1})
            self.assertEqual({"schemaVersion": 2, "value": 1}, json.loads(output.read_bytes()))
            self.assertEqual([], list(output.parent.glob(".pluto-evidence-*")))


if __name__ == "__main__":
    unittest.main()
