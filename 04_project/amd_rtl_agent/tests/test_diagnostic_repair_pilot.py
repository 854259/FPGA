"""No model/EDA calls: freeze integrity, six-call limit and incomplete-run gates."""
import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('repair_pilot', ROOT / 'bench/diagnostic_repair_pilot.py')
pilot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pilot)
INPUT = ROOT.parents[1] / '03_analysis/diagnostic_repair_pilot_20261003/input'


class PilotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name) / 'run'
        with patch('builtins.print'):
            pilot.freeze(argparse.Namespace(inputs=str(INPUT), package=str(ROOT / 'submission'),
                                            out=str(self.out), endpoint='http://127.0.0.1:8000/v1'))
        self.slot = Path(self.tmp.name) / 'slot'
        self.slot.write_text('pilot_test\nstart\n40\npurpose\n123\n')
        self.args = argparse.Namespace(out=str(self.out), slot_file=str(self.slot), slot_owner='pilot_test')
        self.baseline = types.SimpleNamespace(served_model=lambda: pilot.MODEL)

    def fake_call(self, command, **kwargs):
        sample = self.out / command[-1]
        # Keep an empty first candidate as a scored result, not a missing sample.
        code = '' if sample.name.startswith('00') else 'module TopModule; endmodule\n'
        (sample / 'solution.v').write_text(code)
        pilot.write_json(sample / 'response.json', dict(model=pilot.MODEL, usage={},
                         choices=[dict(message=dict(content=code), finish_reason='stop')]))
        return subprocess.CompletedProcess(command, 0)

    def test_freeze_has_exact_pairs_and_only_diagnostics_differ(self):
        plan = pilot.read_json(self.out / 'plan.json')
        self.assertEqual([(r['pair'], r['arm']) for r in plan['records']], pilot.ORDER)
        bodies = [pilot.read_json(self.out / r['directory'] / 'request.json') for r in plan['records']]
        diag = (self.out / 'inputs/diagnostics.txt').read_text().rstrip('\n')
        normalized = []
        for body in bodies:
            text = body['messages'][1]['content']
            self.assertNotIn('[/workspace/', text)
            self.assertNotIn('scored_samples', text)
            body['messages'][1]['content'] = text.replace(diag, 'No diagnostic text is provided.')
            normalized.append(body)
        self.assertTrue(all(body == normalized[0] for body in normalized))

    def test_six_calls_complete_and_empty_answer_is_preserved(self):
        with patch.object(pilot, 'baseline_module', return_value=self.baseline), \
             patch.object(pilot.subprocess, 'run', side_effect=self.fake_call) as calls, \
             patch('builtins.print'):
            self.assertEqual(pilot.run(self.args), 0)
        report = pilot.read_json(self.out / 'generation.json')
        self.assertTrue(report['complete'])
        self.assertEqual(calls.call_count, 6)
        self.assertEqual(report['calls_attempted'], 6)
        self.assertTrue(report['records'][0]['empty'])
        self.assertFalse(report['grading_performed'])

    def test_client_timeout_stops_without_retry_or_complete_flag(self):
        with patch.object(pilot, 'baseline_module', return_value=self.baseline), \
             patch.object(pilot.subprocess, 'run', side_effect=subprocess.TimeoutExpired('client', 300)) as calls, \
             patch('builtins.print'):
            self.assertEqual(pilot.run(self.args), 1)
        report = pilot.read_json(self.out / 'generation.json')
        self.assertFalse(report['complete'])
        self.assertEqual(calls.call_count, 1)
        self.assertEqual(report['records'][0]['error'], 'model_client_wall_deadline')

    def test_changed_request_is_rejected_before_any_model_call(self):
        request = self.out / pilot.read_json(self.out / 'plan.json')['records'][0]['directory'] / 'request.json'
        request.write_text('{}')
        with patch.object(pilot.subprocess, 'run') as calls:
            with self.assertRaisesRegex(ValueError, 'frozen request changed'):
                pilot.run(self.args)
        calls.assert_not_called()

    def test_slot_owner_change_stops_remaining_calls(self):
        def change_slot(command, **kwargs):
            result = self.fake_call(command, **kwargs)
            self.slot.write_text('someone_else\n')
            return result
        with patch.object(pilot, 'baseline_module', return_value=self.baseline), \
             patch.object(pilot.subprocess, 'run', side_effect=change_slot) as calls, \
             patch('builtins.print'):
            self.assertEqual(pilot.run(self.args), 1)
        self.assertEqual(calls.call_count, 1)
        self.assertFalse(pilot.read_json(self.out / 'generation.json')['complete'])
        self.assertEqual(self.slot.read_text(), 'someone_else\n')

    def test_existing_run_is_not_resumed(self):
        (self.out / '.started').write_text('old')
        with patch.object(pilot.subprocess, 'run') as calls:
            with self.assertRaises(FileExistsError):
                pilot.run(self.args)
        calls.assert_not_called()


if __name__ == '__main__':
    unittest.main()
