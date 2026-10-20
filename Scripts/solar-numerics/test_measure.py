import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import measure
import solar_reference as solar


class MeasurementProvenanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.saved = json.loads(Path(__file__).with_name("evidence").joinpath("macos-arm64-debug.json").read_text())

    def recheck(self, report):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "report.json"
            path.write_text(json.dumps(report))
            with patch("sys.argv", ["measure.py", "--recheck", "--output", str(path)]), contextlib.redirect_stdout(io.StringIO()):
                measure.main()

    def test_recheck_requires_the_complete_canonical_request_sequence(self):
        for mutation in ["delete", "reorder", "rename", "duplicate"]:
            with self.subTest(mutation=mutation):
                changed = copy.deepcopy(self.saved)
                for field in ["requests", "rows"]:
                    if mutation == "delete":
                        del changed[field][0]
                    elif mutation == "reorder":
                        changed[field][0], changed[field][1] = changed[field][1], changed[field][0]
                    elif mutation == "rename":
                        changed[field][0]["id"] = "different-request"
                    else:
                        changed[field][0] = copy.deepcopy(changed[field][1])
                with self.assertRaisesRegex(SystemExit, "canonical request grid"):
                    self.recheck(changed)

    def test_saved_reference_is_reexecuted(self):
        rows = measure.comparisons(self.saved["rows"][:1], self.saved["requests"][:1])
        self.assertEqual(measure.comparisons(rows, self.saved["requests"][:1]), rows)
        changed = copy.deepcopy(rows)
        changed[0]["reference"]["earthX"] = "0"
        self.assertNotEqual(measure.comparisons(changed, self.saved["requests"][:1]), changed)

    def test_earth_rows_follow_selected_ecliptic_model(self):
        earth = solar.SelectedEarth()
        routes = {"selected": 0, "blend": 0, "retained": 0}
        for record, request in zip(self.saved["rows"], self.saved["requests"]):
            tt = measure.ref.exact(measure.decode(record["values"]["tt"]))
            weight, _ = earth.weight(tt)
            retained = earth.retained.position(tt)
            expected = retained
            if weight:
                x, y, z = earth.source(tt)[0]
                mp = measure.ref.mp
                source = [x - mp.mpf("0.000000479966") * y,
                          mp.mpf("0.000000440360") * x + mp.mpf("0.917482137087") * y + mp.mpf("0.397776982902") * z,
                          -mp.mpf("0.000000190919") * x - mp.mpf("0.397776982902") * y + mp.mpf("0.917482137087") * z]
                expected = [a + weight * (b - a) for a, b in zip(retained, source)]
            routes["selected" if weight == 1 else "blend" if weight else "retained"] += 1
            row = measure.comparisons([record], [request])[0]
            for name, value in zip(["earthX", "earthY", "earthZ"], expected):
                self.assertAlmostEqual(measure.ref.mp.mpf(row["reference"][name]), value, delta=measure.ref.mp.mpf("1e-70"), msg=request["id"])
        self.assertEqual(routes, {"selected": 132, "blend": 8, "retained": 22})

    def test_retained_route_does_not_apply_an_equatorial_round_trip(self):
        earth = solar.SelectedEarth()
        tt = measure.ref.mp.mpf("-40000")
        with patch.object(earth, "source", side_effect=AssertionError("source outside selection")):
            self.assertEqual(measure.ecliptic_earth(earth, tt), earth.retained.position(tt))

    def test_selected_reference_dependencies_invalidate_reports(self):
        import measure_altitude
        paths = ["Scripts/model_resource.py", "Scripts/solar-numerics/solar_reference.py", "Scripts/solar-numerics/apparent_reference.py",
                 "Scripts/apparent-place-data/dtdb.c", "Sources/AstronomyKit/Resources/ModelTables/planet-polynomial-earth.bin",
                 "Sources/AstronomyKit/Resources/ModelTables/pluto-de441-sun.bin", "Sources/AstronomyKit/Resources/ModelTables/saturn-sun.bin", *measure.BINDINGS]
        for path in paths:
            self.assertIn(path, measure.BINDINGS + measure.TOOLS)
            self.assertIn(path, measure_altitude.PATHS)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for path in paths:
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes((measure.ROOT / path).read_bytes())
            hashes = measure.source_hashes(root, paths)
            for path in paths[:3]:
                target = root / path
                original = target.read_bytes()
                target.write_bytes(original + b"\n")
                with self.assertRaises(ValueError):
                    measure.check_hashes(root, hashes)
                target.write_bytes(original)

    def test_altered_summary_is_rejected(self):
        changed = copy.deepcopy(self.saved)
        changed["sampledMaximumAbsoluteError"]["earthX"] = "0"
        with self.assertRaisesRegex(ValueError, "maxima"):
            measure.verify_summary(changed)

    def test_wrong_request_association_is_rejected(self):
        row = copy.deepcopy(self.saved["rows"][:1])
        row[0]["id"] = "wrong-epoch"
        with self.assertRaisesRegex(ValueError, "wrong request"):
            measure.comparisons(row, self.saved["requests"][:1])

    def test_lost_input_bits_are_rejected(self):
        row = copy.deepcopy(self.saved["rows"][:1])
        row[0]["values"]["input"] = "0"
        with self.assertRaisesRegex(ValueError, "input bits"):
            measure.comparisons(row, self.saved["requests"][:1])

    def test_missing_or_duplicate_output_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Missing or duplicate"):
            measure.comparisons([], self.saved["requests"][:1])
        with self.assertRaisesRegex(ValueError, "Missing or duplicate"):
            measure.comparisons(self.saved["rows"][:1] * 2, self.saved["requests"][:2])


if __name__ == "__main__":
    unittest.main()
