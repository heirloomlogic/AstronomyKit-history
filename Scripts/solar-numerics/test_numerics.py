from fractions import Fraction
from pathlib import Path
import tempfile
import unittest

import numerics


class ExactArithmeticTests(unittest.TestCase):
    def test_selected_earth_trajectory_dependencies_are_bound(self):
        self.assertTrue(set(numerics.SELECTED_EARTH_BINDINGS).issubset(numerics.BINDINGS))
        for path in numerics.SELECTED_EARTH_BINDINGS:
            with self.subTest(path=path), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                target = root / path
                target.parent.mkdir(parents=True)
                target.write_bytes((numerics.ROOT / path).read_bytes())
                binding = numerics.source_hashes(numerics.ROOT, [path])
                numerics.check_hashes(root, binding)
                target.write_bytes(target.read_bytes() + b"\n")
                with self.assertRaisesRegex(ValueError, path):
                    numerics.check_hashes(root, binding)

    def test_sqrt_encloses_exact_rational(self):
        for value in [Fraction(0), Fraction(2), Fraction(1, 3), Fraction(1, 2**1100)]:
            lo, hi = numerics.sqrt_interval(value)
            self.assertLessEqual(lo * lo, value)
            self.assertGreaterEqual(hi * hi, value)

    def test_outward_float_including_subnormal(self):
        for value in [Fraction(1, 10), Fraction(2**53 + 1), Fraction(1, 2**1100)]:
            self.assertGreaterEqual(Fraction(numerics.upward(value)), value)
            self.assertLessEqual(Fraction(numerics.downward(value)), value)

    def test_chebyshev_endpoints_and_derivative_bound(self):
        coefficients = [Fraction(2), Fraction(-3), Fraction(5)]
        self.assertEqual(numerics.chebyshev(coefficients, Fraction(1)), 4)
        self.assertEqual(numerics.chebyshev(coefficients, Fraction(-1)), 10)
        self.assertEqual(numerics.derivative_bound(coefficients, Fraction(8)), Fraction(23, 4))

    def test_actual_source_and_data_changes_invalidate_binding(self):
        paths = [numerics.ENGINE + "Orientation/EngineEarthRotation.swift", numerics.ENGINE + "Foundation/EngineMappedResource.swift", numerics.EARTH, numerics.EARTH_RESOURCE]
        for path in paths:
            with self.subTest(path=path), tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                target = root / path
                target.parent.mkdir(parents=True)
                target.write_bytes((numerics.ROOT / path).read_bytes())
                binding = numerics.source_hashes(numerics.ROOT, [path])
                numerics.check_hashes(root, binding)
                if path == numerics.EARTH_RESOURCE:
                    data = bytearray(target.read_bytes())
                    data[0] ^= 1
                    target.write_bytes(data)
                    with self.assertRaisesRegex(ValueError, path):
                        numerics.check_hashes(root, binding)
                    continue
                if path == numerics.EARTH:
                    text = target.read_text().replace("degree: 12", "degree: 13", 1)
                elif path.endswith("EngineEarthRotation.swift"):
                    text = target.read_text().replace("0.002_737_811_911_354_48", "0.002_737_811_911_354_49", 1)
                else:
                    text = target.read_text()+"\n"
                self.assertNotEqual(text, target.read_text(), "Mutation must change the actual source")
                target.write_text(text)
                with self.assertRaisesRegex(ValueError, path):
                    numerics.check_hashes(root, binding)


if __name__ == "__main__":
    unittest.main()
