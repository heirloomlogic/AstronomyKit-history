from fractions import Fraction as Q
import unittest
from unittest.mock import patch
from pathlib import Path
import base64
import hashlib
import struct
import re
import selected_earth_bounds as bounds


class SelectedEarthBoundsTests(unittest.TestCase):
    def test_squared_norm_coefficients_preserve_cancellation(self):
        # (1 + T2)^2 + (2 T1)^2 has a known exact expansion.
        self.assertEqual(bounds.squared_norm([[Q(1), Q(0), Q(1)], [Q(0), Q(2)]]),
                         [Q(7, 2), Q(0), Q(4), Q(0), Q(1, 2)])

    def test_domain_must_be_entirely_full_weight(self):
        with self.assertRaisesRegex(ValueError, 'full-weight'):
            bounds.check_domain(Q('-36524.50001'), Q('36889.5'))

    def test_changed_admission_or_weight_branch_invalidates_proof(self):
        original = Path.read_text
        cases = [('SolarAltitudeObservation.swift', 'guard coverage.contains(lowerTT), coverage.contains(upperTT)'),
                 ('EngineMoonEphemeris.swift', 'if tt >= fullWeightStart && tt <= fullWeightEnd { return (1, 0) }')]
        for filename, expression in cases:
            with self.subTest(filename=filename):
                def changed(path, *args, **kwargs):
                    text = original(path, *args, **kwargs)
                    return text.replace(expression, 'changed') if path.name == filename else text
                with patch.object(Path, 'read_text', changed):
                    with self.assertRaises(ValueError):
                        bounds.check_domain()

    def test_selected_coefficients_drive_majorants(self):
        baseline = bounds.record_bounds([[Q(10), Q(1)], [Q(0)], [Q(0)]], Q(4))
        altered = bounds.record_bounds([[Q(10), Q(2)], [Q(0)], [Q(0)]], Q(4))
        self.assertGreater(altered['speed'], baseline['speed'])
        self.assertGreater(altered['radiusUpper'], baseline['radiusUpper'])
        self.assertLess(altered['radiusLower'], baseline['radiusLower'])

    def test_each_actual_selected_component_drives_the_bounds(self):
        original = Path.read_text
        for source in bounds.PATHS:
            with self.subTest(source=source):
                baseline = bounds.table(source, Q(0), Q(1))
                source_text = (bounds.ROOT/source).read_text()
                mapped = 'Engine.TableResource(' in source_text
                changed_resource = None
                resource_path = None
                if mapped:
                    resource_name = re.search(r'Engine\.TableResource\(name: "([^"]+)"', source_text)[1]
                    resource_path = bounds.ROOT/'Sources/AstronomyKit/Resources/ModelTables'/f'{resource_name}.bin'
                    changed_resource = bytearray(resource_path.read_bytes())
                    size = int(re.search(r'coefficientCount: ([0-9]+)', source_text)[1])
                    offset = int(baseline['firstRecord'])*3*size*8
                    struct.pack_into('<d', changed_resource, offset, 10**12)
                def changed(path, *args, **kwargs):
                    text = original(path, *args, **kwargs)
                    if str(path) != str(bounds.ROOT/source):
                        return text
                    if mapped:
                        digest = hashlib.sha256(changed_resource).hexdigest()
                        return re.sub(r'sha256: "[0-9a-f]{64}"', f'sha256: "{digest}"', text)
                    parts = text.split('"""')
                    payload = bytearray(base64.b64decode(''.join(parts[1].split())))
                    size = int(re.search(r'coefficientCount: ([0-9]+)', text)[1])
                    offset = int(baseline['firstRecord'])*3*size*8
                    struct.pack_into('<d', payload, offset, 10**12)
                    parts[1] = base64.b64encode(payload).decode()
                    return '"""'.join(parts)
                original_bytes = Path.read_bytes
                def changed_bytes(path, *args, **kwargs):
                    return bytes(changed_resource) if mapped and path == resource_path else original_bytes(path, *args, **kwargs)
                with patch.object(Path, 'read_text', changed), patch.object(Path, 'read_bytes', changed_bytes):
                    mutated = bounds.table(source, Q(0), Q(1))
                self.assertGreater(mutated['radiusUpper'], baseline['radiusUpper'])

    def test_convergence_rejects_selected_radius_outside_delay_interval(self):
        import certify_light_time
        with patch.object(bounds, 'derive', return_value={
                'radiusMaximumAU': Q(3), 'radiusMinimumAU': Q(1)}):
            with self.assertRaisesRegex(ValueError, 'delay interval'):
                certify_light_time.constants()

    def test_velocity_jump_uses_both_sides(self):
        left = [[Q(1), Q(2)], [Q(0)], [Q(0)]]
        right = [[Q(3), Q(4)], [Q(0)], [Q(0)]]
        position, velocity = bounds.join_bounds(left, right, Q(4))
        self.assertEqual(position, Q(4))
        self.assertEqual(velocity, Q(1))


if __name__ == '__main__':
    unittest.main()
