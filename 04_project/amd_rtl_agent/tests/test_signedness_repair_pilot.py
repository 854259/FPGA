"""R2 freeze/run behavior: no real model, EDA, server or slot operations."""
import argparse
import copy
import importlib.util
from pathlib import Path
import shutil
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'signedness_pilot', ROOT / 'bench/signedness_repair_pilot.py')
pilot = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pilot)
INPUT = ROOT.parents[1] / '03_analysis/r2_signedness_20261003/input'
PROBES = INPUT.parent / 'probes'


class SignednessPilotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.out = self.base / 'run'
        self.validation = self.base / 'validation.json'
        # Synthetic receipts bind actual source assets. These tests never claim
        # the controls have run: real control logs are separately graded on Linux.
        self.probes = self.base / 'probes'
        self.probes.mkdir()
        asset_names = ['probe_runner.py'] + [task + '/' + name for task in pilot.TASKS
                       for name in ('tb.sv', 'positive.sv', 'negative.sv')]
        for name in asset_names:
            target = self.probes / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(PROBES / name, target)
        identities = {name: pilot.digest(self.probes / name) for name in asset_names}
        validation = {'complete': True, 'valid': True, 'assets_unchanged': True,
                      'probe_files': identities, 'tasks': {}}
        counts = {'Prob115_shift18': 31, 'Prob042_vector4': 256,
                  'Prob055_conditional': 4096}
        for task in pilot.TASKS:
            row = {'valid': True}
            for mode in ('positive', 'negative'):
                row[mode] = {
                    'status': 'pass' if mode == 'positive' else 'fail',
                    'failure_kind': None if mode == 'positive' else 'semantic_mismatch',
                    'solution_sha256': identities[task + '/' + mode + '.sv'],
                    'tb_sha256': identities[task + '/tb.sv'],
                    'runner_sha256': identities['probe_runner.py'],
                    'checks': counts[task], 'mismatches': 0 if mode == 'positive' else 1,
                    'inputs_unchanged': True}
            validation['tasks'][task] = row
        pilot.write_json(self.validation, validation)
        self.auxiliary = self.base / 'probe.py'
        self.auxiliary.write_text('# inert test fixture\n', encoding='utf-8')
        self.freeze_args = argparse.Namespace(
            inputs=str(INPUT), package=str(ROOT / 'submission'),
            out=str(self.out), endpoint='http://127.0.0.1:8000/v1',
            probe_validation=str(self.validation), probe_runner=str(self.probes / 'probe_runner.py'),
            freeze_file=[str(self.auxiliary)] + [str(self.probes / n) for n in asset_names])
        with patch('builtins.print'):
            pilot.freeze(self.freeze_args)
        self.slot = self.base / 'slot'
        self.slot.write_text('r2_test\nstart\n60\npurpose\n123\n', encoding='utf-8')
        self.run_args = argparse.Namespace(out=str(self.out), slot_file=str(self.slot),
                                           slot_owner='r2_test')
        self.baseline = types.SimpleNamespace(served_model=lambda: pilot.MODEL)

    def fake_call(self, command, **kwargs):
        sample = self.out / command[-1]
        code = '' if sample.name.startswith('00') else 'module TopModule; endmodule\n'
        (sample / 'solution.v').write_text(code, encoding='utf-8')
        pilot.write_json(sample / 'response.json', {
            'model': pilot.MODEL, 'usage': {},
            'choices': [{'message': {'content': code}, 'finish_reason': 'stop'}]})
        return subprocess.CompletedProcess(command, 0)

    def test_twelve_frozen_requests_have_only_declared_treatment_difference(self):
        plan = pilot.read_json(self.out / 'plan.json')
        self.assertEqual(len(plan['records']), 12)
        expected_order = [(task, pair, arm) for task in pilot.TASKS
                          for pair, arm in [(0, 'diagnostic'), (0, 'control'),
                                            (1, 'control'), (1, 'diagnostic')]]
        self.assertEqual([(r['task_id'], r['pair'], r['arm'])
                          for r in plan['records']], expected_order)
        self.assertEqual(plan['per_call_wall_limit_s'], 300)
        by_task = {}
        for row in plan['records']:
            request = self.out / row['directory'] / 'request.json'
            self.assertEqual(pilot.digest(request), row['request_sha256'])
            body = pilot.read_json(request)
            self.assertEqual((body['temperature'], body['top_p'], body['max_tokens']),
                             (0.0, 1.0, 8192))
            self.assertEqual([m['role'] for m in body['messages']], ['system', 'user'])
            prompt = (INPUT / row['task_id'] / 'prompt.txt').read_text(encoding='utf-8')
            candidate = (INPUT / row['task_id'] / 'candidate.sv').read_text(encoding='utf-8')
            expected_user = (prompt + '\nPrevious candidate:\n' + candidate +
                             '\nReview the candidate against the specification. Return one complete corrected '
                             'TopModule. Preserve the required interface and behaviour; output only code.')
            suffix = '\nReview checklist:\n' + pilot.CHECKLIST
            self.assertEqual(body['messages'][1]['content'], expected_user +
                             (suffix if row['arm'] == 'diagnostic' else ''))
            # Exact user construction excludes hidden diagnostics/probe feedback.
            normalized = copy.deepcopy(body)
            normalized['messages'][1]['content'] = expected_user
            by_task.setdefault(row['task_id'], []).append(normalized)
        for requests in by_task.values():
            self.assertTrue(all(r == requests[0] for r in requests))

    def test_freeze_copies_exact_input_bytes_and_refuses_overwrite(self):
        for name in pilot.EXPECTED:
            self.assertEqual((INPUT / name).read_bytes(),
                             (self.out / 'inputs' / name).read_bytes())
        original_plan = (self.out / 'plan.json').read_bytes()
        with self.assertRaises(FileExistsError):
            pilot.freeze(self.freeze_args)
        self.assertEqual((self.out / 'plan.json').read_bytes(), original_plan)

    def test_changed_input_rejected_before_new_output_exists(self):
        modified = self.base / 'modified'
        shutil.copytree(INPUT, modified)
        (modified / 'Prob115_shift18/candidate.sv').write_text('tampered', encoding='utf-8')
        args = copy.copy(self.freeze_args)
        args.inputs, args.out = str(modified), str(self.base / 'rejected')
        with self.assertRaisesRegex(ValueError, 'hash mismatch'):
            pilot.freeze(args)
        self.assertFalse(Path(args.out).exists())

    def test_failed_or_missing_probe_validation_blocks_freeze(self):
        args = copy.copy(self.freeze_args)
        args.out = str(self.base / 'rejected')
        validation = pilot.read_json(self.validation)
        validation['valid'] = False
        pilot.write_json(self.validation, validation)
        with self.assertRaisesRegex(ValueError, 'probe controls'):
            pilot.freeze(args)
        self.validation.unlink()
        with self.assertRaises(FileNotFoundError):
            pilot.freeze(args)
        self.assertFalse(Path(args.out).exists())

    def test_control_receipt_with_wrong_source_hash_is_rejected(self):
        args = copy.copy(self.freeze_args)
        args.out = str(self.base / 'rejected')
        validation = pilot.read_json(self.validation)
        validation['tasks']['Prob115_shift18']['negative']['solution_sha256'] = '0' * 64
        pilot.write_json(self.validation, validation)
        with self.assertRaisesRegex(ValueError, 'control receipt'):
            pilot.freeze(args)
        self.assertFalse(Path(args.out).exists())

    def test_omitted_probe_asset_cannot_be_frozen(self):
        args = copy.copy(self.freeze_args)
        args.out, args.freeze_file = str(self.base / 'rejected'), args.freeze_file[:-1]
        with self.assertRaisesRegex(ValueError, 'freeze all validated probe assets'):
            pilot.freeze(args)
        self.assertFalse(Path(args.out).exists())

    def test_external_endpoint_is_rejected(self):
        args = copy.copy(self.freeze_args)
        args.out, args.endpoint = str(self.base / 'rejected'), 'https://example.com/v1'
        with self.assertRaisesRegex(ValueError, 'loopback'):
            pilot.freeze(args)
        self.assertFalse(Path(args.out).exists())

    def test_twelve_calls_preserve_empty_candidate_without_judging(self):
        with patch.object(pilot, 'baseline_module', return_value=self.baseline), \
             patch.object(pilot.subprocess, 'run', side_effect=self.fake_call) as calls, \
             patch('builtins.print'):
            self.assertEqual(pilot.run(self.run_args), 0)
        result = pilot.read_json(self.out / 'generation.json')
        self.assertTrue(result['complete'])
        self.assertEqual((calls.call_count, result['calls_attempted'], len(result['records'])),
                         (12, 12, 12))
        self.assertTrue(result['records'][0]['empty'])
        self.assertFalse(result['grading_performed'])
        self.assertTrue(all(c.kwargs['timeout'] == 300 for c in calls.call_args_list))

    def test_timeout_stops_without_retry_and_does_not_touch_slot(self):
        slot_before = self.slot.read_bytes()
        with patch.object(pilot, 'baseline_module', return_value=self.baseline), \
             patch.object(pilot.subprocess, 'run',
                          side_effect=subprocess.TimeoutExpired('client', 300)) as calls, \
             patch('builtins.print'):
            self.assertEqual(pilot.run(self.run_args), 1)
        result = pilot.read_json(self.out / 'generation.json')
        self.assertFalse(result['complete'])
        self.assertEqual(calls.call_count, 1)
        self.assertEqual(result['records'][0]['error'], 'model_client_wall_deadline')
        self.assertEqual(self.slot.read_bytes(), slot_before)

    def test_request_change_is_rejected_before_model_call(self):
        row = pilot.read_json(self.out / 'plan.json')['records'][0]
        (self.out / row['directory'] / 'request.json').write_text('{}', encoding='utf-8')
        with patch.object(pilot.subprocess, 'run') as calls:
            with self.assertRaisesRegex(ValueError, 'frozen request changed'):
                pilot.run(self.run_args)
        calls.assert_not_called()

    def test_probe_validation_change_is_rejected_before_model_call(self):
        validation = pilot.read_json(self.validation)
        validation['changed'] = True
        pilot.write_json(self.validation, validation)
        with patch.object(pilot.subprocess, 'run') as calls:
            with self.assertRaisesRegex(ValueError, 'probe validation changed'):
                pilot.run(self.run_args)
        calls.assert_not_called()

    def test_auxiliary_change_is_rejected_before_model_call(self):
        self.auxiliary.write_text('# changed after freeze\n', encoding='utf-8')
        with patch.object(pilot.subprocess, 'run') as calls:
            with self.assertRaisesRegex(ValueError, 'hash mismatch'):
                pilot.run(self.run_args)
        calls.assert_not_called()

    def test_slot_owner_change_stops_remaining_calls_without_releasing(self):
        def change_slot(command, **kwargs):
            result = self.fake_call(command, **kwargs)
            self.slot.write_text('someone_else\n', encoding='utf-8')
            return result
        with patch.object(pilot, 'baseline_module', return_value=self.baseline), \
             patch.object(pilot.subprocess, 'run', side_effect=change_slot) as calls, \
             patch('builtins.print'):
            self.assertEqual(pilot.run(self.run_args), 1)
        self.assertEqual(calls.call_count, 1)
        self.assertFalse(pilot.read_json(self.out / 'generation.json')['complete'])
        self.assertEqual(self.slot.read_text(encoding='utf-8'), 'someone_else\n')

    def test_started_run_cannot_be_resumed(self):
        (self.out / '.started').write_text('earlier attempt', encoding='utf-8')
        with patch.object(pilot.subprocess, 'run') as calls:
            with self.assertRaises(FileExistsError):
                pilot.run(self.run_args)
        calls.assert_not_called()


if __name__ == '__main__':
    unittest.main()
