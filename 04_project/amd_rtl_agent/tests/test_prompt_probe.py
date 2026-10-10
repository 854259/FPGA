"""CPU-only qualification of the extracted prompt checker; no model or EDA."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / 'submission/agent/prompt_probe.py'
SPEC = importlib.util.spec_from_file_location('portable_prompt_probe', SOURCE)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


class PromptProbeTests(unittest.TestCase):
    def setUp(self):
        self.scratch = tempfile.TemporaryDirectory(prefix='prompt-probe-cpu-')
        self.addCleanup(self.scratch.cleanup)
        self.root = Path(self.scratch.name)
        self.solution = self.root / 'model_candidate.sv'
        self.testbench = self.root / 'prompt_derived_tb.sv'
        self.solution.write_text('module TopModule; endmodule\n')
        self.testbench.write_text('module R2Probe; endmodule\n')
        self.calls = []

    def run_case(self, name, summary, *, checks=2, task='Request', failure=None,
                 mutate=False, stage_error=None):
        out = self.root / name

        def stage(label, argv, directory):
            self.calls.append((label, list(argv), directory))
            if stage_error:
                raise stage_error
            text = summary if label == 'xsim' else ''
            result = dict(launch_error=None, timeout=False, returncode=0)
            if failure and label == failure[0]:
                result.update(failure[1])
                text += failure[2]
            if mutate and label == 'xsim':
                self.testbench.write_text('changed during checker\n')
            log = directory / (label + '.log')
            log.write_text(text)
            return dict(name=label, argv=list(argv), log=str(log), **result)

        result = probe.probe_candidate(task, self.solution, self.testbench, out,
                                       checks, stage)
        self.assertEqual(result, json.loads((out / 'result.json').read_text()))
        return result

    def test_pass_then_different_request_count_has_no_global_task_state(self):
        first = self.run_case('first', 'R2_PROBE_RESULT task=Request checks=2 mismatches=0\n')
        second = self.run_case('second', 'R2_PROBE_RESULT task=Another checks=3 mismatches=0\n',
                               task='Another', checks=3)
        self.assertEqual((first['status'], second['status']), ('pass', 'pass'))
        self.assertEqual((first['checks'], second['checks']), (2, 3))
        self.assertTrue(first['inputs_unchanged'] and second['inputs_unchanged'])
        self.assertEqual([c[0] for c in self.calls], ['xvlog', 'xelab', 'xsim'] * 2)
        self.assertEqual(self.calls[0][1], ['xvlog', '-sv', '--nolog', 'dut.sv', 'tb.sv'])
        self.assertEqual(self.calls[1][1], ['xelab', 'R2Probe', '-s', 'r2_probe', '--nolog',
                                          '-timescale', '1ns/1ps'])
        self.assertEqual(self.calls[2][1], ['xsim', 'r2_probe', '-runall', '-nolog'])
        self.assertEqual((self.root / 'first/dut.sv').read_bytes(), self.solution.read_bytes())
        self.assertEqual((self.root / 'first/tb.sv').read_bytes(), self.testbench.read_bytes())
        self.assertEqual(first['runner_sha256'], probe.sha256(SOURCE))

    def test_completed_counterexample_remains_semantic_failure(self):
        result = self.run_case('negative', 'R2_PROBE_RESULT task=Request checks=2 mismatches=1\n')
        self.assertEqual((result['status'], result['failure_kind'], result['mismatches']),
                         ('fail', 'semantic_mismatch', 1))

    def test_malformed_summary_is_environment_failure(self):
        summaries = ['', 'R2_PROBE_RESULT task=Other checks=2 mismatches=0\n',
                     'R2_PROBE_RESULT task=Request checks=3 mismatches=0\n',
                     'R2_PROBE_RESULT task=Request checks=2 mismatches=3\n',
                     'R2_PROBE_RESULT task=Request checks=2 mismatches=0\n' * 2]
        for i, summary in enumerate(summaries):
            with self.subTest(i=i):
                result = self.run_case('protocol-' + str(i), summary)
                self.assertEqual((result['status'], result['failure_kind']),
                                 ('environment_error', 'probe_protocol_error'))

    def test_launch_timeout_license_and_stage_exit_are_not_semantic_failures(self):
        cases = [('launch', {'launch_error': 'missing executable'}, '', 'environment_error'),
                 ('timeout', {'timeout': True}, '', 'environment_error'),
                 ('license', {}, 'license checkout failed', 'environment_error'),
                 ('compile', {'returncode': 1}, '', 'fail')]
        for name, values, log, status in cases:
            with self.subTest(name=name):
                self.calls.clear()
                result = self.run_case(name, '', failure=('xvlog', values, log))
                self.assertEqual(result['status'], status)
                self.assertNotEqual(result['failure_kind'], 'semantic_mismatch')
                self.assertEqual(len(self.calls), 1)
        result = self.run_case('simulation', '', failure=('xsim', {'returncode': 1}, ''))
        self.assertEqual((result['status'], result['failure_kind']),
                         ('environment_error', 'xsim_failed'))

    def test_mutated_generated_input_overrides_completed_summary(self):
        result = self.run_case('mutated', 'R2_PROBE_RESULT task=Request checks=2 mismatches=0\n',
                               mutate=True)
        self.assertEqual((result['status'], result['failure_kind'], result['inputs_unchanged']),
                         ('environment_error', 'input_changed_during_probe', False))

    def test_invalid_boundary_and_deadline_exception_cannot_produce_success(self):
        for label, count in [('../task', 2), ('Request', 0), ('Request', True)]:
            with self.subTest(label=label, count=count), self.assertRaises(ValueError):
                probe.probe_candidate(label, self.solution, self.testbench,
                                      self.root / 'invalid', count, lambda *args: None)
        self.assertFalse((self.root / 'invalid').exists())
        with self.assertRaisesRegex(RuntimeError, 'owned deadline exhausted'):
            self.run_case('deadline', '', stage_error=RuntimeError('owned deadline exhausted'))
        self.assertFalse((self.root / 'deadline/result.json').exists())


if __name__ == '__main__':
    unittest.main()
