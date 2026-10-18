#!/usr/bin/env python3
"""Negative controls for native lunar-eclipse evidence."""

import copy
import importlib.util
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("eclipse_evidence", ROOT / "Scripts/record-eclipse-event-evidence.py")
RECORD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RECORD)


class EclipseEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.captures = json.loads(RECORD.CAPTURES.read_bytes())

    def test_recorded_captures_validate(self):
        RECORD.evidence(self.captures, RECORD.source_hashes())

    def test_retained_rebind_rejects_changed_missing_or_different_measurements(self):
        previous = RECORD.evidence(self.captures, RECORD.source_hashes())
        self.assertEqual(RECORD.rebind(self.captures, previous), previous)
        for dependency in [
            "Sources/AstronomyKit/Engine/Foundation/EngineConstants.swift",
            "Tests/AstronomyKitTests/Engine/Planets/PlanetTestSupport.swift",
        ]:
            altered = copy.deepcopy(previous)
            altered["sourceSHA256"].pop(dependency)
            with self.subTest(dependency=dependency), self.assertRaisesRegex(ValueError, "result dependencies differ"):
                RECORD.rebind(self.captures, altered)
        changed = copy.deepcopy(previous)
        changed["sourceSHA256"]["Sources/AstronomyKit/Engine/Foundation/EngineConstants.swift"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "result dependencies differ"):
            RECORD.rebind(self.captures, changed)
        different = copy.deepcopy(self.captures)
        different["resources"]["coldSeconds"] += 1
        with self.assertRaisesRegex(ValueError, "changed scientific or measured payload"):
            RECORD.rebind(different, previous)

    def test_peak_outside_published_allowance_is_rejected(self):
        for configuration in ("debug", "release"):
            row = self.captures[configuration]["published"][0]
            row["nativePeakTT"] = RECORD.source_time_tt(row["sourceTime"]) + 121 / 86_400
            row["peakResidualSeconds"] = 121
        with self.assertRaisesRegex(ValueError, "peak criterion"):
            RECORD.evidence(self.captures, {})

    def test_published_peak_residual_is_derived_from_native_event_time(self):
        for configuration in ("debug", "release"):
            self.captures[configuration]["published"][0]["peakResidualSeconds"] = -500
        with self.assertRaisesRegex(ValueError, "peak residual relation"):
            RECORD.evidence(self.captures, {})

    def test_debug_release_disagreement_is_rejected(self):
        self.captures["debug"]["published"][0]["obscuration"] += 0.01
        with self.assertRaisesRegex(ValueError, "Debug and Release"):
            RECORD.evidence(self.captures, {})

    def test_debug_release_time_roundoff_uses_field_units(self):
        self.assertTrue(RECORD.near({"peakResidualSeconds": 1.0}, {"peakResidualSeconds": 1.000001}))
        self.assertTrue(RECORD.near({"peakResidualSeconds": 1.0}, {"peakResidualSeconds": 1.000015}))
        self.assertFalse(RECORD.near({"peakResidualSeconds": 1.0}, {"peakResidualSeconds": 1.00002}))
        self.assertTrue(RECORD.near({"semiDurationMinutes": 1.0}, {"semiDurationMinutes": 1.000000001}))
        self.assertTrue(RECORD.near({"nativePeakTT": 8_000.0}, {"nativePeakTT": 8_000.0 + 1.5e-10}))
        self.assertFalse(RECORD.near({"peakResidualSeconds": 1.0}, {"peakResidualSeconds": 1.0001}))
        self.assertFalse(RECORD.near({"semiDurationMinutes": 1.0}, {"semiDurationMinutes": 1.0000001}))
        self.assertFalse(RECORD.near({"nativePeakTT": 8_000.0}, {"nativePeakTT": 8_000.0 + 3e-10}))
        self.assertFalse(RECORD.near({"obscuration": 0.5}, {"obscuration": 0.50001}))
        self.assertTrue(RECORD.near({"kind": "total"}, {"kind": "total"}))
        self.assertFalse(RECORD.near({"kind": "total"}, {"kind": "partial"}))

    def test_obscuration_outside_print_interval_is_rejected(self):
        for configuration in ("debug", "release"):
            self.captures[configuration]["obscurations"][0]["obscuration"] = 0.99
        with self.assertRaisesRegex(ValueError, "print interval criterion"):
            RECORD.evidence(self.captures, {})

    def test_obscuration_event_time_must_match_the_published_event(self):
        for configuration in ("debug", "release"):
            self.captures[configuration]["obscurations"][0]["nativePeakTT"] = -1_000_000
        with self.assertRaisesRegex(ValueError, "obscuration event time"):
            RECORD.evidence(self.captures, {})

    def test_known_discrepancy_unexpected_pass_is_rejected(self):
        rows = self.captures["release"]["obscurations"]
        row = next(row for row in rows if row["sourceTimeSearchSeed"].startswith("2026-08-28"))
        row["obscuration"] = 0.963
        with self.assertRaisesRegex(ValueError, "#275 unexpectedly matches"):
            RECORD.validate_obscurations(rows)

    def test_known_discrepancy_cannot_hide_missing_or_invalid_rows(self):
        rows = self.captures["release"]["obscurations"]
        with self.assertRaisesRegex(ValueError, "row selection"):
            RECORD.validate_obscurations(rows[:-1])
        row = next(row for row in rows if row["sourceTimeSearchSeed"].startswith("2026-08-28"))
        row["obscuration"] = float("nan")
        with self.assertRaisesRegex(ValueError, "invalid lunar obscuration"):
            RECORD.validate_obscurations(rows)


if __name__ == "__main__":
    unittest.main()
