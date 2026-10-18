import copy
import contextlib
import io
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
import unittest
import measure_altitude as measure


class AltitudeMeasurementProvenanceTests(unittest.TestCase):
    def test_grid_covers_the_observed_model_and_its_joins(self):
        rows = measure.grid()
        self.assertEqual(len(rows), 1908)
        models = {row['model'] for row in rows}
        self.assertEqual(models, {'iersObserved', 'espenakMeeus', 'jplHorizons'})
        ids = {row['id'] for row in rows}
        for join in ['historical-observed', 'observed-predicted', 'table-extrapolated']:
            for offset in ['below', 'at', 'above']:
                self.assertTrue(any(f'observed-{join}-{offset}-observer-' in identifier for identifier in ids))

    def test_cli_recheck_rejects_altered_public_outcomes(self):
        pristine = json.loads(Path(__file__).with_name('evidence').joinpath('altitude-macos-arm64-debug.json').read_text())
        # Bind the mutation to current checker bytes so stale hashes cannot
        # masquerade as successful public-outcome validation.
        pristine['sourceSHA256'] = measure.source_hashes(measure.ROOT, measure.PATHS)
        supported = next(i for i,row in enumerate(pristine['rows']) if row['request']['id'] == 'coverage-1-espenakMeeus-observer-0')
        rejected = next(i for i,row in enumerate(pristine['rows']) if 'unsupported' in row)
        changes = ['missing-observation', 'false-rejection', 'both-outcomes', 'missing-rejection', 'wrong-rejection',
                   'false-observation', 'missing-field', 'extra-field', 'non-dictionary', 'consistent-zero-budget',
                   *['budget-'+key for key in ['altitude','civil','scale','light','era','total']]]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'altered-outcome.json'
            for change in changes:
                with self.subTest(change=change):
                    saved = copy.deepcopy(pristine)
                    row, other = saved['rows'][supported], saved['rows'][rejected]
                    if change == 'missing-observation': del row['observation']
                    elif change == 'false-rejection':
                        del row['observation']
                        row['unsupported'] = 'outsidePolynomialCoverage'
                    elif change == 'both-outcomes': row['unsupported'] = 'outsidePolynomialCoverage'
                    elif change == 'missing-rejection': del other['unsupported']
                    elif change == 'wrong-rejection': other['unsupported'] = 'civilDateAtSegmentStart'
                    elif change == 'false-observation':
                        del other['unsupported']
                        other['observation'] = {**row['observation'], 'altitude':other['values']['altitude']}
                    elif change == 'missing-field': del row['observation']['total']
                    elif change == 'extra-field': row['observation']['extra'] = '0'
                    elif change == 'non-dictionary': row['observation'] = None
                    elif change == 'consistent-zero-budget':
                        row['observation'].update(dict.fromkeys(['civil','scale','light','era','total'], '0'))
                    else:
                        key = change.removeprefix('budget-')
                        row['observation'][key] = '1' if row['observation'][key] == '0' else '0'
                    path.write_text(json.dumps(saved))
                    with patch('sys.argv', ['measure_altitude.py', '--recheck', '--output', str(path)]), patch.object(measure, 'native_export', return_value=(pristine['rows'], 0, '')) as replay, contextlib.redirect_stdout(io.StringIO()):
                        with self.assertRaisesRegex(ValueError, 'ublic outcome'):
                            measure.main()
                        replay.assert_called_once_with(measure.grid(), 'debug', 'recheck')

    def test_cli_fresh_export_failure_cannot_certify_the_saved_report(self):
        saved = json.loads(Path(__file__).with_name('evidence').joinpath('altitude-macos-arm64-debug.json').read_text())
        saved['sourceSHA256'] = measure.source_hashes(measure.ROOT, measure.PATHS)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'report.json'
            original = json.dumps(saved)
            path.write_text(original)
            with patch('sys.argv', ['measure_altitude.py', '--recheck', '--output', str(path)]), patch.object(measure, 'native_export', side_effect=RuntimeError('native replay failed')):
                with self.assertRaisesRegex(RuntimeError, 'native replay failed'):
                    measure.main()
            self.assertEqual(path.read_text(), original)

    def test_public_replay_does_not_require_cross_configuration_altitude_bits(self):
        saved = json.loads(Path(__file__).with_name('evidence').joinpath('altitude-macos-arm64-debug.json').read_text())
        row = next(row for row in saved['rows'] if 'observation' in row)
        fresh = copy.deepcopy(row)
        changed = format(int(row['values']['altitude'],16)+1, 'x')
        fresh['values']['altitude'] = fresh['observation']['altitude'] = changed
        measure.validate_public_outcomes([row], [row['request']], [fresh])
        fresh['request']['id'] = 'other'
        with self.assertRaisesRegex(ValueError, 'public outcome request coverage'):
            measure.validate_public_outcomes([row], [row['request']], [fresh])

    def test_comparison_requires_a_fresh_public_outcome(self):
        saved = json.loads(Path(__file__).with_name('evidence').joinpath('altitude-macos-arm64-debug.json').read_text())
        row = next(row for row in saved['rows'] if 'observation' in row)
        with self.assertRaisesRegex(ValueError, 'Fresh native public outcomes'):
            measure.comparisons([row], [row['request']])

    def test_recheck_rejects_paired_request_and_result_deletion(self):
        # Exercise the actual CLI before expensive reference evaluation. Matching
        # deletions must fail even if the stored summaries and hashes survive.
        saved = {'requests': measure.grid(), 'rows': [{'request': row} for row in measure.grid()]}
        del saved['requests'][0]
        del saved['rows'][0]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'omitted.json'
            path.write_text(json.dumps(saved))
            with patch('sys.argv', ['measure_altitude.py', '--recheck', '--output', str(path)]):
                with self.assertRaisesRegex(ValueError, 'canonical request grid'):
                    measure.main()

    def test_complete_request_grid_is_required(self):
        rows = measure.grid()
        self.assertEqual(len({r['id'] for r in rows}), len(rows))
        for change in ['delete', 'reorder', 'duplicate', 'observer']:
            changed = copy.deepcopy(rows)
            if change == 'delete':
                del changed[0]
            elif change == 'reorder':
                changed[0], changed[1] = changed[1], changed[0]
            elif change == 'duplicate':
                changed[0] = changed[1]
            else:
                changed[0]['observer'][0] = 33.0
            with self.assertRaisesRegex(ValueError, 'canonical request grid'):
                measure.validate_requests(changed)

    def test_wrong_result_association_is_rejected_before_evaluation(self):
        request = measure.grid()[0]
        record = {'request': {**request, 'model': 'other'}}
        with self.assertRaisesRegex(ValueError, 'wrong request'):
            measure.comparisons([record], [request])

    def test_missing_output_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Missing or duplicate'):
            measure.comparisons([], measure.grid()[:1])


if __name__ == '__main__':
    unittest.main()
