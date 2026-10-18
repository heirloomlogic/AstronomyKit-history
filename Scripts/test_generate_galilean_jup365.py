"""Controls for the Galilean jup365 representation generator."""

import copy
from decimal import Decimal, localcontext
import importlib.util
import json
import math
from pathlib import Path
import struct
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock


PATH = Path(__file__).with_name("generate-galilean-jup365.py")
SPEC = importlib.util.spec_from_file_location("galilean_jup365", PATH)
jup365 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(jup365)


class GalileanJUP365GeneratorTests(unittest.TestCase):
    def test_inventory_covers_every_galilean_moon_and_jupiter_center(self):
        self.assertEqual(set(jup365.SPECS), {"io", "europa", "ganymede", "callisto", "jupiter"})
        self.assertEqual([jup365.SPECS[name].target for name in jup365.MOONS], [501, 502, 503, 504])
        self.assertEqual(jup365.SPECS["jupiter"].target, 599)
        self.assertEqual(jup365.SOURCE_CENTER, 5)
        self.assertEqual(jup365.COVERAGE, (2_305_456.5, 2_524_602.5))

    def test_mixed_precision_payload_has_a_continuous_coefficient_bound(self):
        spec = jup365.CandidateSpec(target=501, source_coefficients=6, kept_coefficients=5, float32_coefficients=2)
        records = [
            (0.0, 2.0, ((10.25, 2.125, 0.75, -0.2, 0.04, 0.01), (20.5, -3.25, 0.5, 0.1, -0.03, 0.02), (-4.5, 1.5, -0.25, 0.05, 0.02, -0.01))),
            (2.0, 2.0, ((11.5, 2.5, 0.5, -0.1, 0.02, -0.02), (19.75, -3.0, 0.25, 0.2, -0.01, 0.03), (-5.0, 1.25, -0.5, 0.1, 0.01, 0.02))),
        ]
        data, scales, bounds = jup365.pack_records(records, spec)
        self.assertEqual(len(data), 2 * jup365.record_bytes(spec))
        for record, (_, days, axes) in enumerate(records):
            decoded = jup365.decode_record(data, spec, scales, record)
            for x in (-1.0, -0.375, 0.0, 0.625, 1.0):
                exact = jup365.evaluate_axes(axes, x, days)
                candidate = jup365.evaluate_axes(decoded, x, days)
                position_error = math.dist(exact[0], candidate[0])
                velocity_error = math.dist(exact[1], candidate[1])
                self.assertLessEqual(position_error, bounds["positionKm"])
                self.assertLessEqual(velocity_error, bounds["velocityKmPerTDBDay"])

    def test_coefficient_bound_rounds_outward_for_float32_tie(self):
        spec = jup365.CandidateSpec(target=501, source_coefficients=1, kept_coefficients=1, float32_coefficients=1)
        coefficient = 1.0 + 2.0 ** -24
        records = [(0.0, 1.0, (((coefficient,),) * 3))]
        _, _, bounds = jup365.pack_records(records, spec)
        with localcontext() as context:
            context.prec = 80
            exact = Decimal(3).sqrt() * (Decimal(2) ** -24)
        self.assertGreaterEqual(Decimal.from_float(bounds["positionKm"]), exact)

    def test_outward_helpers_enclose_positive_underflow(self):
        minimum = math.ulp(0.0)
        self.assertEqual(jup365.upper_multiply(minimum, 0.5), minimum)
        self.assertEqual(jup365.upper_divide(minimum, 2.0), minimum)

    def test_payload_validation_rejects_wrong_length_and_nonpositive_scale(self):
        spec = jup365.CandidateSpec(target=501, source_coefficients=4, kept_coefficients=4, float32_coefficients=2)
        scales = ((0.5, 0.25), (0.5, 0.25), (0.5, 0.25))
        good = b"".join(struct.pack("<ffhh", 1.0, 2.0, 3, -4) for _ in range(3))
        jup365.validate_payload(good, spec, scales, record_count=1)
        with self.assertRaises(ValueError):
            jup365.validate_payload(good[:-1], spec, scales, record_count=1)
        with self.assertRaises(ValueError):
            jup365.validate_payload(good, spec, ((0.0, 0.25), *scales[1:]), record_count=1)

    def test_table_selection_uses_half_open_domain_and_actual_records(self):
        spec = jup365.CandidateSpec(target=501, source_coefficients=3, kept_coefficients=3, float32_coefficients=3)
        records = [(0.0, 2.0, ((1.0, 2.0, 3.0), (4.0, 5.0, 6.0), (7.0, 8.0, 9.0)))]
        data, scales, _ = jup365.pack_records(records, spec)
        table = {"startJDTDB": 0.0, "exclusiveEndJDTDB": 2.0, "recordDays": 2.0, "recordCount": 1}
        self.assertIsNotNone(jup365.evaluate_table(data, spec, scales, table, 0.0))
        self.assertIsNotNone(jup365.evaluate_table(data, spec, scales, table, math.nextafter(2.0, -math.inf)))
        self.assertIsNone(jup365.evaluate_table(data, spec, scales, table, math.nextafter(0.0, -math.inf)))
        self.assertIsNone(jup365.evaluate_table(data, spec, scales, table, 2.0))
        self.assertIsNone(jup365.evaluate_table(data, spec, scales, table, math.nan))

    def test_table_selection_stops_at_source_endpoint_inside_padding_record(self):
        spec = jup365.CandidateSpec(target=501, source_coefficients=2, kept_coefficients=2, float32_coefficients=2)
        records = [
            (0.0, 2.0, ((1.0, 2.0), (3.0, 4.0), (5.0, 6.0))),
            (2.0, 2.0, ((7.0, 8.0), (9.0, 10.0), (11.0, 12.0))),
        ]
        data, scales, _ = jup365.pack_records(records, spec)
        table = {"startJDTDB": 0.0, "exclusiveEndJDTDB": 3.5, "recordDays": 2.0, "recordCount": 2}
        self.assertIsNotNone(jup365.evaluate_table(data, spec, scales, table, math.nextafter(3.5, -math.inf)))
        self.assertIsNone(jup365.evaluate_table(data, spec, scales, table, 3.5))

    def test_source_layout_uses_segment_endpoint_when_last_record_is_padding(self):
        spec = jup365.SPECS["io"]
        first = SimpleNamespace(target=501, center=5, frame=1, kind=2, start_seconds_tdb=(jup365.COVERAGE[0] - jup365.J2000) * 86_400, end_seconds_tdb=(jup365.SOURCE_SEAM - jup365.J2000) * 86_400)
        second = SimpleNamespace(target=501, center=5, frame=1, kind=2, start_seconds_tdb=(jup365.SOURCE_SEAM - jup365.J2000) * 86_400, end_seconds_tdb=(jup365.COVERAGE[1] - jup365.J2000) * 86_400)
        first_metadata = SimpleNamespace(start_jd_tdb=jup365.COVERAGE[0], record_days=1.125, record_count=128_896, record_words=50)
        second_metadata = SimpleNamespace(start_jd_tdb=jup365.SOURCE_SEAM, record_days=1.125, record_count=65_901, record_words=50)
        with mock.patch.object(jup365.spk, "read_segments", return_value=[second, first]), mock.patch.object(jup365.spk, "read_metadata", side_effect=lambda _reader, segment: first_metadata if segment is first else second_metadata):
            result = jup365.source_layout(object(), spec)
        self.assertEqual([segment for segment, _ in result], [first, second])
        self.assertGreater(second_metadata.start_jd_tdb + second_metadata.record_days * second_metadata.record_count, jup365.COVERAGE[1])

    def test_manifest_rejects_duplicate_direct_fixture_identities(self):
        manifest = json.loads(jup365.MANIFEST.read_bytes())
        manifest["generatorBindingsSHA256"] = jup365.binding_hashes()
        manifest["combinedJovicentricRepresentationBound"] = jup365.combined_bounds(manifest["components"])
        manifest["directFixtures"] = [copy.deepcopy(manifest["directFixtures"][0]) for _ in manifest["directFixtures"]]
        payloads = {name: jup365.payload_path(name).read_bytes() for name in jup365.SPECS}
        with self.assertRaisesRegex(ValueError, "fixture identity"):
            jup365.verify_manifest(manifest, payloads)

    def test_failed_capture_validation_leaves_accepted_artifacts_intact(self):
        manifest = json.loads(jup365.MANIFEST.read_bytes())
        manifest["generatorBindingsSHA256"] = jup365.binding_hashes()
        manifest["components"]["io"]["coefficientRepresentationBound"]["positionKm"] = 1.0
        manifest["combinedJovicentricRepresentationBound"] = jup365.combined_bounds(manifest["components"])
        payloads = {name: jup365.payload_path(name).read_bytes() for name in jup365.SPECS}
        comment = jup365.COMMENT.read_bytes()
        with tempfile.TemporaryDirectory() as directory:
            data = Path(directory)
            accepted = {f"{name}.bin": f"accepted-{name}".encode() for name in jup365.SPECS}
            accepted.update({"jup365.cmt": b"accepted-comment", "representation.json": b"accepted-manifest"})
            for name, contents in accepted.items():
                (data / name).write_bytes(contents)
            with mock.patch.object(jup365, "DATA", data), mock.patch.object(jup365, "COMMENT", data / "jup365.cmt"), mock.patch.object(jup365, "MANIFEST", data / "representation.json"):
                with self.assertRaisesRegex(ValueError, "qualification limit"):
                    jup365.publish(payloads, manifest, comment)
            self.assertEqual({path.name: path.read_bytes() for path in data.iterdir()}, accepted)


if __name__ == "__main__":
    unittest.main()
