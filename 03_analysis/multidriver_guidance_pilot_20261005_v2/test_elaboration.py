"""Pure fake-native diagnostic/receipt controls; zero actual EDA or model IO."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import elaboration_feedback as e

CODE = 'module TopModule(input a, output b); assign b=a; endmodule\n'
ERR = "ERROR: [VRFC 10-2063] Module <helper> not found while processing module instance <u> [candidate.sv:1]"


class Controls(unittest.TestCase):
    def setUp(self):
        raw = ROOT / 'raw_evidence'; raw.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix='pure_elab_controls_', dir=raw)
        self.assertTrue(Path(self.temporary.name).resolve().is_relative_to(raw.resolve()))
        self.addCleanup(self.temporary.cleanup)
        self.out = Path(self.temporary.name)
        self.compile = self.out / 'work' / 'compile-0'; self.compile.mkdir(parents=True)
        self.source = self.compile / 'candidate.sv'; self.source.write_bytes(CODE.encode())
        self.tool = self.out / 'fake_tool' / 'xelab'; self.tool.parent.mkdir(); self.tool.write_bytes(b'FAKE TOOL NEVER EXECUTED\n')
        self.calls = []

    def runner(self, text='', rc=0, mutate=None):
        def native(argv, cwd, log, seconds):
            self.calls.append(dict(argv=copy.deepcopy(argv), cwd=str(cwd), log=str(log), seconds=seconds))
            raw = text.encode('utf-8')
            log.write_bytes(raw)
            result = dict(returncode=rc, timeout=False, launch_error=None, remaining_live_group=[],
                          log=str(log), log_sha256=e.sha(raw), log_bytes=len(raw),
                          elapsed_s=.001, group_signals=[], io_kind='FAKE')
            if mutate: mutate(result, argv, log)
            return result
        return native

    def invoke(self, native=None, code=CODE, attempt=0, seconds=60, tool=None):
        return e.check(code, self.compile, self.out, attempt,
                       self.runner() if native is None else native,
                       self.tool if tool is None else tool, timeout_s=seconds)

    def receipt(self, attempt=0):
        return json.loads((self.out / ('elaboration_check_' + str(attempt)) / 'RESULTS.json').read_bytes())

    def assert_error_receipt(self):
        row = self.receipt()
        self.assertEqual(row['outcome'], 'measurement_error')
        self.assertFalse(row['measurement_valid']); self.assertTrue(row['complete'])
        self.assertEqual(row['feedback'], '')
        self.assertTrue(row['candidate_only'])
        return row

    def test_success_returns_empty_preserves_original_code_and_full_receipt(self):
        self.assertEqual(self.invoke(self.runner('INFO: Static elaboration completed.\nWARNING: a harmless message\n')), '')
        row = self.receipt()
        self.assertEqual(row['outcome'], 'pass'); self.assertTrue(row['measurement_valid'])
        self.assertEqual(row['source_before_sha256'], e.sha(CODE.encode()))
        self.assertEqual(row['source_after_sha256'], e.sha(CODE.encode()))
        self.assertTrue(row['source_unchanged']); self.assertTrue(row['executable_unchanged'])
        self.assertEqual(row['actualcheck_path'], str(self.out / 'elaboration_check_0'))
        self.assertEqual(row['native_command']['returncode'], 0)
        self.assertFalse(row['hidden_testbench_used']); self.assertFalse(row['reference_used'])
        self.assertEqual(row['model_calls'], 0)

    def test_exact_established_native_argv_and_candidate_top_only(self):
        self.invoke()
        row = self.receipt()
        self.assertEqual(row['argv'], [str(self.tool), 'TopModule', '-s', row['snapshot'], '--nolog', '-timescale', '1ns/1ps'])
        self.assertEqual(row['cwd'], str(self.compile))
        self.assertEqual(self.calls[0]['argv'], row['argv'])
        self.assertEqual(self.calls[0]['seconds'], 60)
        self.assertTrue(row['snapshot'].startswith('own_candidate_elab_0_'))
        self.assertNotIn('R2Probe', row['argv'])

    def test_confirmed_nonzero_returns_actual_error_facts_only(self):
        full = 'INFO: starting\n' + ERR + '\nWARNING: irrelevant\nFATAL: actual static error\n'
        text = self.invoke(self.runner(full, rc=1))
        self.assertEqual(text, ERR + '\nFATAL: actual static error')
        row = self.receipt()
        self.assertEqual(row['outcome'], 'fail'); self.assertTrue(row['measurement_valid'])
        self.assertEqual(row['log_sha256'], e.sha(full.encode()))
        self.assertEqual(row['log_bytes'], len(full.encode()))
        self.assertEqual(row['native_command']['returncode'], 1)

    def test_diagnostic_dedup_order_and_2048_bound(self):
        self.assertEqual(e.diagnostic_text(ERR + '\n' + ERR + '\nFATAL_ERROR: second\n'), ERR + '\nFATAL_ERROR: second')
        full = 'ERROR: ' + 'a' * 3000
        self.assertEqual(e.diagnostic_text(full), full[:2048])
        self.assertEqual(e.diagnostic_text('INFO: quoted ERROR from a message\nWARNING: ERROR is a signal name\n'), '')

    def test_warning_only_nonzero_is_measurement_error_without_invented_feedback(self):
        with self.assertRaises(RuntimeError): self.invoke(self.runner('WARNING: no confirmed error\n', rc=1))
        self.assert_error_receipt()

    def test_timeout_never_becomes_semantic_feedback(self):
        def mutate(result, argv, log): result['timeout'] = True
        with self.assertRaises(RuntimeError): self.invoke(self.runner(ERR, rc=1, mutate=mutate))
        row = self.assert_error_receipt(); self.assertTrue(row['timeout'])

    def test_launch_failure_preserves_error_and_does_not_repair(self):
        def mutate(result, argv, log): result['launch_error'] = 'executable could not start'
        with self.assertRaises(RuntimeError): self.invoke(self.runner(ERR, rc=1, mutate=mutate))
        row = self.assert_error_receipt(); self.assertEqual(row['launch_error'], 'executable could not start')

    def test_remaining_owned_processes_are_measurement_failure(self):
        def mutate(result, argv, log): result['remaining_live_group'] = [123]
        with self.assertRaises(RuntimeError): self.invoke(self.runner(ERR, rc=1, mutate=mutate))
        row = self.assert_error_receipt(); self.assertEqual(row['remaining_live_group'], [123])

    def test_native_raised_exception_preserves_partial_log_and_source(self):
        def native(argv, cwd, log, seconds):
            log.write_bytes(b'PARTIAL OWN FAKE LOG\n')
            raise RuntimeError('own fake cleanup exception')
        with self.assertRaises(RuntimeError): self.invoke(native)
        row = self.assert_error_receipt()
        self.assertEqual(row['actual_log_sha256'], e.sha(b'PARTIAL OWN FAKE LOG\n'))
        self.assertTrue(row['source_unchanged'])

    def test_source_mutation_withdraws_feedback(self):
        def mutate(result, argv, log): self.source.write_bytes(b'module TopModule;endmodule\n')
        with self.assertRaises(RuntimeError): self.invoke(self.runner(ERR, rc=1, mutate=mutate))
        row = self.assert_error_receipt(); self.assertFalse(row['source_unchanged'])
        self.assertNotEqual(row['source_after_sha256'], row['source_before_sha256'])

    def test_tool_mutation_withdraws_feedback(self):
        def mutate(result, argv, log): self.tool.write_bytes(b'CHANGED FAKE TOOL\n')
        with self.assertRaises(RuntimeError): self.invoke(self.runner(ERR, rc=1, mutate=mutate))
        row = self.assert_error_receipt(); self.assertFalse(row['executable_unchanged'])

    def test_current_source_mismatch_rejected_before_native_effect(self):
        self.source.write_bytes(b'module Another;endmodule\n')
        with self.assertRaises(ValueError): self.invoke()
        self.assertEqual(self.calls, [])

    def test_wrong_or_unconfirmed_return_code_rejected(self):
        for rc in [None, True, -9]:
            with self.subTest(rc=rc):
                if (self.out / 'elaboration_check_0').exists():
                    # Use the next fresh own fixture rather than overwriting a receipt.
                    self.temporary.cleanup(); self.setUp()
                with self.assertRaises(RuntimeError): self.invoke(self.runner(ERR, rc=rc))
                self.assert_error_receipt()

    def test_changed_full_log_receipt_rejected(self):
        for key, value in [('log', 'outside.log'), ('log_sha256', '0'*64), ('log_bytes', True), ('log_bytes', 0)]:
            with self.subTest(key=key, value=value):
                if (self.out / 'elaboration_check_0').exists():
                    self.temporary.cleanup(); self.setUp()
                def mutate(result, argv, log): result[key] = value
                with self.assertRaises(RuntimeError): self.invoke(self.runner(ERR, rc=1, mutate=mutate))
                self.assert_error_receipt()

    def test_actual_log_missing_is_measurement_failure(self):
        def native(argv, cwd, log, seconds):
            return dict(returncode=0, timeout=False, launch_error=None, remaining_live_group=[],
                        log=str(log), log_sha256=e.sha(b''), log_bytes=0)
        with self.assertRaises(RuntimeError): self.invoke(native)
        self.assert_error_receipt()

    def test_mutated_argv_cannot_be_claimed_original_command(self):
        def mutate(result, argv, log): argv[1] = 'HiddenTestbench'
        with self.assertRaises(RuntimeError): self.invoke(self.runner(ERR, rc=1, mutate=mutate))
        row = self.assert_error_receipt(); self.assertEqual(row['native_argv_after'][1], 'HiddenTestbench')

    def test_no_attempt_replay_or_existing_receipt_overwrite(self):
        self.invoke()
        before = (self.out / 'elaboration_check_0' / 'RESULTS.json').read_bytes()
        with self.assertRaises(FileExistsError): self.invoke()
        self.assertEqual((self.out / 'elaboration_check_0' / 'RESULTS.json').read_bytes(), before)
        self.assertEqual(len(self.calls), 1)

    def test_second_round_gets_independent_snapshot(self):
        self.invoke(); first = self.receipt()['snapshot']
        self.invoke(attempt=1); second = self.receipt(1)['snapshot']
        self.assertNotEqual(first, second)
        self.assertTrue(second.startswith('own_candidate_elab_1_'))

    def test_invalid_attempt_budget_tool_or_foreign_compile_path_rejected(self):
        for attempt in [True, -1, 2]:
            with self.assertRaises(ValueError): self.invoke(attempt=attempt)
        for seconds in [True, 0, -1, 61, float('nan'), float('inf')]:
            with self.assertRaises(ValueError): self.invoke(seconds=seconds)
        with self.assertRaises(ValueError): e.check(CODE, self.compile, self.out, 0, self.runner(), 'xelab')
        outside = self.out / 'another_output'; outside.mkdir()
        with self.assertRaises(ValueError): e.check(CODE, self.compile, outside, 0, self.runner(), self.tool)
        self.assertEqual(self.calls, [])


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    print(json.dumps(dict(schema='candidate_elaboration_pure_controls_v1', tests_run=result.testsRun,
                          failures=len(result.failures), errors=len(result.errors), skipped=len(result.skipped),
                          helper_sha256=e.sha((ROOT / 'elaboration_feedback.py').read_bytes()),
                          test_sha256=e.sha(Path(__file__).read_bytes()), actual_model_calls=0,
                          actual_eda_calls=0, actual_cloud_or_fifo_calls=0, fake_native_only=True), indent=2))
    raise SystemExit(0 if result.wasSuccessful() else 1)
