import copy
from fractions import Fraction as F
import importlib.util
import json
from pathlib import Path
import unittest

SPEC = importlib.util.spec_from_file_location('center_qualification', Path(__file__).with_name('qualify-pluto-center.py'))
q = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(q)
RESOURCE_SPEC = importlib.util.spec_from_file_location('model_resource', Path(__file__).with_name('model_resource.py'))
resource = importlib.util.module_from_spec(RESOURCE_SPEC)
RESOURCE_SPEC.loader.exec_module(resource)


def generated_payload(path):
    return resource.payload(path.read_text(), q.g.binary.RESOURCE_DIRECTORY)


class PlutoCenterQualificationTests(unittest.TestCase):
    def test_exact_restriction_and_derivative(self):
        coefficients = [2., -3., 0.25, 0.125, -0.5]
        polynomial = q.restricted(coefficients, -4., 16., 0., 3.)
        for u in [F(-1), F(-1,2), F(0), F(1,2), F(1)]:
            t = F(3,2) + u * F(3,2)
            x = (t + 4) / 8 - 1
            chebyshev = [F(1), x]
            for _ in range(2,len(coefficients)):
                chebyshev.append(2*x*chebyshev[-1]-chebyshev[-2])
            self.assertEqual(sum(F(c)*v for c,v in zip(coefficients,chebyshev)), sum(c*u**i for i,c in enumerate(polynomial)))
            derivative = sum(i*c*u**(i-1) for i,c in enumerate(polynomial) if i)
            position_bound, rate_bound = q.polynomial_bounds([polynomial, [F(0)], [F(0)]],3.)
            self.assertLessEqual(abs(float(sum(c*u**i for i,c in enumerate(polynomial)))),position_bound)
            self.assertLessEqual(abs(float(derivative*F(2,3))),rate_bound)

    def test_record_coverage_does_not_extrapolate(self):
        table = [(2451545.,3.,((1.,),(2.,),(3.,)))]
        for t in [0.,3.]: self.assertEqual(q.record(table,t),table[0])
        for t in [-1.,4.]:
            with self.assertRaises(ValueError): q.record(table,t)

    def test_full_payload_corruption_and_shape_are_rejected(self):
        evidence = json.loads(q.g.KERNEL_MANIFEST.read_bytes())
        record = evidence['tables']['barycenter']
        source = (q.g.OUTPUT/record['output']).read_text()
        raw = generated_payload(q.g.OUTPUT/record['output'])
        q.g.render_kernel_table('barycenter',record,raw)
        with self.assertRaises(ValueError): q.g.render_kernel_table('barycenter',record,raw[:-8])
        changed = bytearray(raw); changed[0] ^= 1
        with self.assertRaises(ValueError): q.g.render_kernel_table('barycenter',record,changed)
        changed = copy.deepcopy(record); changed['degreeCount'] += 1
        with self.assertRaises(ValueError): q.g.render_kernel_table('barycenter',changed,raw)

    def test_every_legacy_coefficient_is_preserved_in_expanded_tables(self):
        manifest = json.loads(q.g.MANIFEST.read_bytes())
        sources = q.g.read_sources(manifest)
        evidence = json.loads(q.g.KERNEL_MANIFEST.read_bytes())
        for path, table in q.g.TABLES.items():
            start, days, count, degrees, values = q.g.chebyshev_table(sources[path], table.prefix, table.array)
            expanded = evidence['tables'][table.property]
            self.assertEqual((days, degrees), (expanded['recordDays'], expanded['degreeCount']))
            offset = (start - expanded['startTDB']) / days
            self.assertEqual(offset, int(offset))
            raw = generated_payload(q.g.OUTPUT/table.swift_file)
            first = int(offset) * 3 * degrees * 8
            expected = q.g.struct.pack(f'<{len(values)}d', *values)
            self.assertEqual(raw[first:first+len(expected)], expected)

    def test_geometric_reference_semantics_and_frozen_selection(self):
        raw = q.ARCHIVE.read_bytes()
        rows = q.p.references(raw,999,'plu060_merged')
        self.assertEqual([x[0] for x in rows],[t+2451545 for t in q.HORIZONS_TDB])
        for old,new in [('Sun (10)','Earth (399)'),('plu060_merged','DE441'),('JDTDB','JDTT'),('ICRF','ECLIPTIC')]:
            self.assertIn(old.encode(),raw)
            with self.assertRaises(ValueError): q.p.references(raw.replace(old.encode(),new.encode()),999,'plu060_merged')
        self.assertEqual(q.query()['TIME_TYPE'],"'TDB'")


if __name__ == '__main__':
    unittest.main()
