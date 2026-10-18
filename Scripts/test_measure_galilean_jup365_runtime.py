import copy
import importlib.util
from pathlib import Path
from unittest import mock
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
        self.assertEqual(self.tool.parse_time_log(log.replace(" 2.50 real 1.0 user 0.2 sys", "real 2.50"))["wallSeconds"], 2.5)
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

    def test_source_inventory_covers_the_compiled_target_and_measurement_owners(self):
        compiled = {
            path.relative_to(self.tool.ROOT)
            for path in (self.tool.ROOT / "Sources/AstronomyKit").rglob("*.swift")
        }
        inventory = set(self.tool.source_paths())
        self.assertTrue(compiled)
        self.assertTrue(compiled.issubset(inventory))
        for path in (
            Path("Package.swift"),
            Path("Scripts/jupiter-moon-data/jup365-runtime-probe.swift"),
            Path("Scripts/measure-galilean-jup365-runtime.py"),
            Path("Scripts/test_measure_galilean_jup365_runtime.py"),
        ):
            self.assertIn(path, inventory)

    def test_inventory_changes_invalidate_recorded_measurements(self):
        candidate = self.candidate()
        added = Path("Sources/AstronomyKit/AddedAfterCapture.swift")
        for observed in (
            {**candidate["sourceSHA256"], str(added): "f" * 64},
            dict(list(candidate["sourceSHA256"].items())[1:]),
        ):
            with mock.patch.object(self.tool, "source_hashes", return_value=observed), self.assertRaises(ValueError):
                self.tool.validate(candidate)

    def test_capture_rejects_source_changes_before_publication(self):
        before = {"Package.swift": "a" * 64}
        after = {"Package.swift": "b" * 64}
        with mock.patch.object(self.tool, "source_hashes", return_value=after), self.assertRaisesRegex(
            ValueError, "changed during runtime measurement"
        ):
            self.tool.require_stable_source_snapshot(before)

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
