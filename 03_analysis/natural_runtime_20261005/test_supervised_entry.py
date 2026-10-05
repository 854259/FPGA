"""Invented supervisor/runtime fixtures. No real process or external IO admission."""
from pathlib import Path
import copy
import json
import tempfile
import unittest
from unittest import mock

import runtime
import solve_child
import supervisor
import worker
from test_worker import synthetic_record, G, REPAIR, reply


class SupervisedEntryChecks(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=runtime.ROOT / 'raw_evidence')
        self.root = Path(self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def payload(self):
        return runtime.supervised_payload(synthetic_record(), 'C', self.root / 'solve', G, REPAIR)

    def test_projection_strips_hidden_and_preserves_full_public_task(self):
        payload = self.payload()
        self.assertEqual(set(payload['record']), {'input', 'output'})
        self.assertEqual(payload['record']['input'], synthetic_record()['input'])
        self.assertEqual(payload['record']['output'], synthetic_record()['output'])
        self.assertNotIn('PRIVATE_', json.dumps(payload))

    def test_child_requires_exact_payload_digest_schema_and_public_projection(self):
        payload = self.payload()
        path = self.root / 'task.json'
        for mutation in ('none', 'digest', 'extra', 'hidden', 'answer'):
            with self.subTest(mutation=mutation):
                changed = copy.deepcopy(payload)
                if mutation == 'extra': changed['extra'] = True
                if mutation == 'hidden': changed['record']['harness'] = {'answer': 'PRIVATE'}
                if mutation == 'answer': changed['record']['output']['response'] = 'PRIVATE'
                digest = runtime.save(path, changed)
                if mutation == 'none':
                    self.assertEqual(solve_child.load_public_payload(path, digest), payload)
                else:
                    with self.assertRaises((ValueError, PermissionError)):
                        solve_child.load_public_payload(path, '0' * 64 if mutation == 'digest' else digest)

    def test_standalone_clients_and_solve_reject_before_network(self):
        with mock.patch('socket.create_connection') as socket_call, mock.patch('subprocess.Popen') as launch:
            for callback in (lambda: runtime.make_real_clients({}, self.root, {'native_feedback_required': False}),
                             lambda: runtime.solve_real(synthetic_record(), 'C', self.root, G, REPAIR)):
                with self.assertRaises(PermissionError): callback()
            socket_call.assert_not_called()
            launch.assert_not_called()

    def test_child_handshake_precedes_payload_read_and_real_solve(self):
        with (mock.patch.object(supervisor, 'child_admission', side_effect=PermissionError('invented missing pipe')),
             mock.patch.object(solve_child, 'load_public_payload') as load,
             mock.patch.object(runtime, 'solve_real') as solve):
            with self.assertRaises(PermissionError): solve_child.main(['unused', 'unused'])
            load.assert_not_called()
            solve.assert_not_called()

    def parent_fixture(self):
        spec = {'supervisor': {'python_executable': 'SYNTHETIC_NOT_EXECUTED', 'child_entry': 'solve_child.py'}}
        return mock.patch.object(runtime, '_physical_admission', return_value=(spec, None))

    def test_parent_preparation_and_grant_use_same_external_start(self):
        real_file_sha = runtime.file_sha
        with (self.parent_fixture(), mock.patch.object(runtime.time, 'monotonic', return_value=100.0),
             mock.patch.object(runtime, 'file_sha', side_effect=lambda p: 'a' * 64 if Path(p).name == 'RUN_SPEC.json' else real_file_sha(p)),
             mock.patch.object(supervisor, 'run_supervised', return_value={'synthetic_only': True, 'passed': True,
                              'owned_cleanup': {'verified': True}}) as launch):
            result = runtime.solve_supervised(synthetic_record(), 'C', self.root / 'solve', G, REPAIR, self.root / 'supervised')
            self.assertTrue(result['synthetic_only'])
            self.assertEqual(launch.call_args.kwargs, {'started_monotonic': 100.0})
            argv = launch.call_args.args[0]
            self.assertEqual(argv[:2], ['SYNTHETIC_NOT_EXECUTED', str(runtime.ROOT / 'solve_child.py')])
            self.assertEqual(solve_child.load_public_payload(*argv[2:]), self.payload())

    def test_overlapping_supervisor_prepared_and_worker_roots_reject(self):
        with self.parent_fixture(), mock.patch.object(supervisor, 'run_supervised') as launch:
            for worker_root, evidence in [(self.root / 'x', self.root / 'x'),
                                          (self.root / 'x/y', self.root / 'x'),
                                          (self.root / 'x_prepared', self.root / 'x')]:
                with self.subTest(worker=str(worker_root)):
                    with self.assertRaises(ValueError):
                        runtime.solve_supervised(synthetic_record(), 'C', worker_root, G, REPAIR, evidence)
            launch.assert_not_called()

    def test_worker_real_clock_cannot_be_replaced_or_restarted(self):
        transport, compiler = lambda *args: None, lambda *args: None
        transport.io_kind = compiler.io_kind = 'REAL'
        grant = {'started_monotonic': 1.0, 'work_deadline_monotonic': 273.0}
        with mock.patch.object(runtime, 'revalidate'):
            for started, clock in [(2.0, worker.time.monotonic), (1.0, lambda: 2.0)]:
                with self.assertRaises(PermissionError):
                    worker.solve(synthetic_record(), 'C', self.root / 'solve', G, REPAIR,
                                 transport, compiler, clock=clock, real_grant=grant, solve_started=started)

    def test_child_zero_exit_never_certifies_quality(self):
        with (mock.patch.object(supervisor, 'child_admission', return_value={'synthetic': True}),
             mock.patch.object(supervisor, 'verify_child_admission'),
             mock.patch.object(solve_child, 'load_public_payload', return_value=self.payload()),
             mock.patch.object(runtime, 'solve_real', return_value={'complete': True, 'accounting_complete': True,
                              'status': 'real_candidate_checks_fail', 'quality_verified': False}) as solve):
            self.assertEqual(solve_child.main(['unused', 'unused']), 0)
            self.assertEqual(solve.call_args.kwargs, {'supervisor_grant': {'synthetic': True}})

    def test_stopped_child_attempts_are_recovered_without_resampling(self):
        folder = self.root / 'solve/io_attempts'
        folder.mkdir(parents=True)
        runtime.save(folder / 'http_1.json', dict(schema='natural_io_attempt_v1', mode='REAL', kind='http',
                     number=1, spec_sha256='a' * 64, label='chat_completions', attempted=True,
                     invocation_started=True, finalized=False, confirmed=False, evidence_complete=False, error=None))
        counts = runtime.recover_io_accounting(self.root / 'solve', 'a' * 64)
        self.assertEqual((counts['http_attempts'], counts['http_unconfirmed'], counts['http_invocations_started']), (1, 1, 1))

    def test_failed_supervision_stops_enclosing_stage(self):
        with (self.parent_fixture(), mock.patch.object(supervisor, 'run_supervised',
                              return_value={'passed': False, 'owned_cleanup': {'verified': False}})):
            with self.assertRaises(RuntimeError):
                runtime.solve_supervised(synthetic_record(), 'C', self.root / 'solve', G, REPAIR, self.root / 'supervised')

    def test_recovery_error_is_sealed_and_cannot_pass_parent(self):
        with (self.parent_fixture(), mock.patch.object(runtime, 'file_sha', return_value='a' * 64),
              mock.patch.object(runtime, 'recover_io_accounting', side_effect=OSError('invented unreadable ledger')),
              mock.patch.object(supervisor, 'run_supervised', return_value={'passed': True, 'owned_cleanup': {'verified': True}})):
            with self.assertRaises(RuntimeError):
                runtime.solve_supervised(synthetic_record(), 'C', self.root / 'solve', G, REPAIR, self.root / 'supervised')
        receipt = runtime.read_json(self.root / 'supervised_prepared/PARENT_ENTRY_RECEIPT.json')
        self.assertFalse(receipt['passed'])
        self.assertFalse(receipt['recovered_io_counts']['evidence_complete'])
        self.assertIn('invented unreadable ledger', receipt['recovered_io_counts']['recovery_errors'][0])


if __name__ == '__main__':
    unittest.main()
