import copy
import importlib.util
from pathlib import Path
import tempfile
import unittest


PATH = Path(__file__).with_name("measure-galilean-jup365-runtime.py")


class Jup365RuntimeMeasurementTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("measure_galilean_jup365_runtime", PATH)
        self.tool = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.tool)

    def candidate(self):
        return {
            "schemaVersion": 1,
            "host": {"machine": "arm64", "platform": "test", "swift": "Swift test"},
            "sourceSHA256": self.tool.source_hashes(),
            "build": {"command": "test", "wallSeconds": 2.0, "swiftPMSeconds": 1.0, "maximumResidentSetBytes": 3, "peakMemoryFootprintBytes": 4},
            "sizes": {"generatedSwiftBytes": 1, "astronomyKitSourcesBytes": 2, "staticLibraryBytes": 3, "astronomyKitObjectBytes": 4, "probeExecutableBytes": 5},
            "publicAPI": {"iterations": 100_000, "firstPublicCallMilliseconds": 1.0, "sameEpochMicrosecondsPerCall": 2.0, "spanningMicrosecondsPerCall": 3.0, "processLaunchAndFirstCallMilliseconds": [4.0] * 7, "processLaunchAndFirstCallMedianMilliseconds": 4.0},
        }

    def test_time_log_parser_requires_all_build_measurements(self):
        log = "Build complete! (1.25 sec)\n 2.50 real 1.0 user 0.2 sys\n 300 maximum resident set size\n 400 peak memory footprint\n"
        self.assertEqual(self.tool.parse_time_log(log), {"wallSeconds": 2.5, "swiftPMSeconds": 1.25, "maximumResidentSetBytes": 300, "peakMemoryFootprintBytes": 400})
        for line in log.splitlines():
            with self.subTest(line=line), self.assertRaises(ValueError):
                self.tool.parse_time_log(log.replace(line + "\n", ""))

    def test_validation_rejects_source_metric_and_inventory_changes(self):
        self.tool.validate(self.candidate())
        mutations = [
            lambda report: report.update(schemaVersion=2),
            lambda report: report["sourceSHA256"].pop(next(iter(report["sourceSHA256"]))),
            lambda report: report["build"].update(wallSeconds=0),
            lambda report: report["sizes"].update(extra=1),
            lambda report: report["publicAPI"].update(iterations=10),
            lambda report: report["publicAPI"]["processLaunchAndFirstCallMilliseconds"].pop(),
        ]
        for mutation in mutations:
            candidate = copy.deepcopy(self.candidate())
            mutation(candidate)
            with self.subTest(mutation=mutation), self.assertRaises(ValueError):
                self.tool.validate(candidate)

    def test_exactly_one_rejects_missing_and_ambiguous_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(ValueError):
                self.tool.exactly_one(root, "artifact")
            (root / "artifact").touch()
            self.assertEqual(self.tool.exactly_one(root, "artifact"), root / "artifact")
            (root / "nested").mkdir()
            (root / "nested/artifact").touch()
            with self.assertRaises(ValueError):
                self.tool.exactly_one(root, "artifact")


if __name__ == "__main__":
    unittest.main()
