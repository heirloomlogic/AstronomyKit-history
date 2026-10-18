#!/usr/bin/env python3
"""Regression tests for the direct DE421 convention replay."""

import copy
import importlib.util
import json
import math
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("de421_replay", HERE / "de421_replay.py")
REPLAY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(REPLAY)


class DE421ReplayTests(unittest.TestCase):
    def setUp(self):
        self.receipts = REPLAY.load_json(REPLAY.RECEIPTS)
        self.manifest = REPLAY.verify_receipts(self.receipts)

    def test_committed_matrix_is_reproducible(self):
        actual = REPLAY.build_results(self.receipts, self.manifest)
        expected = REPLAY.load_json(REPLAY.RESULTS)
        self.assertEqual(actual, expected)

    def test_kernel_identity_and_all_ranges_are_bound(self):
        source = self.receipts["de421Kernel"]
        self.assertEqual(source["bytes"], 16_790_528)
        self.assertEqual(source["sha256"], "08b20db2ae22488650641c5a9033e5bfda4b1c4b440cfeaf20f621cfa18ecdb3")
        reader = REPLAY.StoredRangeReader(self.manifest)
        with self.assertRaisesRegex(REPLAY.EvidenceError, "lacks required byte range"):
            reader.read(1, 1)

    def test_duplicate_and_invalid_range_inventory_is_rejected(self):
        duplicate = copy.deepcopy(self.receipts)
        manifest_path = REPLAY.source_path(duplicate["de421Kernel"]["manifestPath"], "manifest")
        manifest = REPLAY.load_json(manifest_path)
        manifest["ranges"].append(copy.deepcopy(manifest["ranges"][0]))
        with tempfile.TemporaryDirectory(dir=REPLAY.SOURCES) as directory:
            path = Path(directory) / "manifest.json"
            path.write_text(json.dumps(manifest))
            duplicate["de421Kernel"]["manifestPath"] = str(path.relative_to(REPLAY.ROOT))
            duplicate["de421Kernel"]["manifestSHA256"] = REPLAY.sha256(path)
            with self.assertRaisesRegex(REPLAY.EvidenceError, "duplicate intervals"):
                REPLAY.verify_receipts(duplicate)

    def test_source_path_escape_is_rejected(self):
        receipts = copy.deepcopy(self.receipts)
        receipts["documents"]["svs"]["path"] = "Package.swift"
        with self.assertRaisesRegex(REPLAY.EvidenceError, "outside the issue source archive"):
            REPLAY.verify_receipts(receipts)

    def test_source_digest_and_semantics_are_rejected(self):
        receipts = copy.deepcopy(self.receipts)
        receipts["documents"]["shadow"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(REPLAY.EvidenceError, "shadow SHA-256 changed"):
            REPLAY.verify_receipts(receipts)
        receipts = copy.deepcopy(self.receipts)
        receipts["documents"]["lola"]["requiredText"].append("invented limb algorithm")
        with self.assertRaisesRegex(REPLAY.EvidenceError, "required source text"):
            REPLAY.verify_receipts(receipts)

    def test_horizons_target_and_query_binding_are_rejected(self):
        receipts = copy.deepcopy(self.receipts)
        receipts["horizons"]["de441MoonGeometric"]["command"] = "'10'"
        with self.assertRaisesRegex(REPLAY.EvidenceError, "Horizons target changed"):
            REPLAY.build_results(receipts, self.manifest)
        receipts = copy.deepcopy(self.receipts)
        receipts["horizons"]["de441MoonGeometric"]["sha256"] = receipts["horizons"]["de441SunGeometric"]["sha256"]
        with self.assertRaisesRegex(REPLAY.EvidenceError, "SHA-256 changed"):
            REPLAY.verify_receipts(receipts)

    def test_matrix_inventory_and_unresolved_outcome_are_literal(self):
        result = REPLAY.build_results(self.receipts, self.manifest)
        identities = [(row["epoch"], row["shadow"]) for row in result["matrix"]]
        self.assertEqual(len(identities), 20)
        self.assertEqual(len(set(identities)), 20)
        self.assertFalse(result["outcome"]["exactSVSConventionReproduced"])
        self.assertFalse(result["outcome"]["productionDefectEstablished"])
        self.assertFalse(any(REPLAY.PRINT_INTERVAL[0] <= row["obscuration"] <= REPLAY.PRINT_INTERVAL[1] for row in result["matrix"]))

    def test_nonfinite_and_degenerate_vectors_are_rejected(self):
        with self.assertRaisesRegex(REPLAY.EvidenceError, "degenerate"):
            REPLAY.overlap((0.0, 0.0, 0.0), (1.0, 0.0, 0.0), "fiveMillenniumDanjon")
        with self.assertRaisesRegex(REPLAY.EvidenceError, "degenerate"):
            REPLAY.overlap((math.nan, 0.0, 0.0), (1.0, 0.0, 0.0), "fiveMillenniumDanjon")

    def test_circle_overlap_boundary_controls(self):
        self.assertEqual(REPLAY.circle_overlap_fraction(1, 1, 2), 0)
        self.assertEqual(REPLAY.circle_overlap_fraction(1, 2, 0), 1)
        self.assertEqual(REPLAY.circle_overlap_fraction(2, 1, 0), 0.25)


if __name__ == "__main__":
    unittest.main()
