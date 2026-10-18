import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest import mock


SCRIPT = Path(__file__).with_name("capture-deltat-civil.py")
SPEC = importlib.util.spec_from_file_location("capture_deltat_civil", SCRIPT)
capture = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(capture)


class DeltaTCivilSourceTests(unittest.TestCase):
    def test_replays_frozen_primary_sources(self):
        fixture = capture.fixture()
        self.assertEqual(fixture, json.loads(capture.FIXTURE.read_bytes()))
        self.assertEqual(5, len(fixture["horizons"]["rows"]))
        self.assertEqual(["rise", "set"], sorted(fixture["usno"]["events"]))
        self.assertEqual("iersObserved", fixture["model"])

    def test_rejects_changed_horizons_semantics_and_inventory(self):
        original = capture.read_source(capture.DATA / "horizons.json")
        document, query = original
        mutations = [
            ("query", "TIME_TYPE", "'TT'"),
            ("query", "APPARENT", "'REFRACTED'"),
            ("query", "SITE_COORD", "'0,0,0'"),
            ("response", "Target body name: Sun (10)", "Target body name: Earth (399)"),
            ("response", "{source: DE441}", "{source: DE440}"),
            ("response", "EOP file        : eop.261016.p270112", "EOP file        : missing"),
            ("response", "Date_________JDUT", "Date_________JDTT"),
            ("response", "NO (AIRLESS)", "YES (REFRACTED)"),
            ("response", "$$EOE", "$$MISSING"),
        ]
        for kind, old, new in mutations:
            changed_document = copy.deepcopy(document)
            changed_query = copy.deepcopy(query)
            if kind == "query":
                changed_query[old] = new
            else:
                self.assertIn(old, changed_document["result"])
                changed_document["result"] = changed_document["result"].replace(old, new, 1)
            with self.subTest(kind=kind, old=old), self.assertRaises(ValueError):
                capture.parse_horizons(changed_document, changed_query)

        before, rest = document["result"].split("$$SOE\n")
        rows, after = rest.split("$$EOE")
        lines = rows.splitlines()
        for changed_rows in [lines[:-1], lines + lines[:1]]:
            changed = copy.deepcopy(document)
            changed["result"] = before + "$$SOE\n" + "\n".join(changed_rows) + "\n$$EOE" + after
            with self.assertRaisesRegex(ValueError, "row inventory"):
                capture.parse_horizons(changed, query)

    def test_rejects_nonfinite_values_and_digest_changes(self):
        document, query = capture.read_source(capture.DATA / "horizons.json")
        changed = copy.deepcopy(document)
        changed["result"] = changed["result"].replace("-0.830008682", "nan", 1)
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            capture.parse_horizons(changed, query)

        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "horizons.json"
            source.write_bytes((capture.DATA / "horizons.json").read_bytes() + b" ")
            source.with_suffix(".query.json").write_bytes((capture.DATA / "horizons.query.json").read_bytes())
            with self.assertRaisesRegex(ValueError, "digest"):
                capture.read_source(source)

    def test_rejects_changed_usno_metadata_and_events(self):
        document, query = capture.read_source(capture.DATA / "usno.json")
        for field, change in [
            ("schema", lambda d, q: d.__setitem__("apiversion", "5.0")),
            ("site", lambda d, q: d["geometry"]["coordinates"].__setitem__(0, 0)),
            ("date", lambda d, q: d["properties"]["data"].__setitem__("day", 22)),
            ("query", lambda d, q: q.__setitem__("url", q["url"].replace("tz=0", "tz=1"))),
            ("rise", lambda d, q: d["properties"]["data"]["sundata"][3].__setitem__("time", "10:16")),
            ("missing", lambda d, q: d["properties"]["data"]["sundata"].pop()),
        ]:
            changed_document = copy.deepcopy(document)
            changed_query = copy.deepcopy(query)
            change(changed_document, changed_query)
            with self.subTest(field=field), self.assertRaises(ValueError):
                capture.parse_usno(changed_document, changed_query)

    def test_failed_refresh_preserves_accepted_archive(self):
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory) / "civil-horizon"
            shutil.copytree(capture.DATA, data)
            before = {path.relative_to(data): path.read_bytes() for path in data.rglob("*") if path.is_file()}
            payloads = {
                "horizons": (capture.DATA / "horizons.json").read_bytes().replace(b"Sun (10)", b"Sun (11)", 1),
                "usno": (capture.DATA / "usno.json").read_bytes(),
            }

            def open_url(url, timeout):
                name = "usno" if "usno" in url else "horizons"
                return io.BytesIO(payloads[name])

            with mock.patch.object(capture, "DATA", data), mock.patch.object(capture, "FIXTURE", data / "reference.json"), mock.patch.object(capture.urllib.request, "urlopen", open_url), self.assertRaises(ValueError):
                capture.refresh(publish=True)
            after = {path.relative_to(data): path.read_bytes() for path in data.rglob("*") if path.is_file()}
            self.assertEqual(before, after)

    def test_fixture_binds_every_source_and_query(self):
        fixture = capture.fixture()
        expected = {"horizons.json", "horizons.query.json", "usno.json", "usno.query.json"}
        self.assertEqual(expected, {Path(row["path"]).name for row in fixture["sources"]})
        for row in fixture["sources"]:
            path = capture.ROOT / row["path"]
            self.assertEqual(row["sha256"], hashlib.sha256(path.read_bytes()).hexdigest())


if __name__ == "__main__":
    unittest.main()
