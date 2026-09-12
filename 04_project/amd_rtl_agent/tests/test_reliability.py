import argparse
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent


class ReliabilityTests(unittest.TestCase):
    def test_timeout_preserves_real_partial_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = agent.run_process(
                [sys.executable, '-c', 'import time; print("started", flush=True); time.sleep(10)'],
                Path(tmp), 1, Path(tmp) / 'timeout.log')
            self.assertTrue(result['timed_out'])
            self.assertEqual(result['returncode'], 124)
            self.assertIn('started', result['output'])
            self.assertIn('TIMEOUT', result['output'])

    def test_repair_keeps_better_earlier_candidate(self):
        codes = ['module TopModule; endmodule', 'broken']
        results = [
            {'passed': False, 'highest_stage': 'simulation', 'functional_checked': True, 'feedback': 'Mismatches: 1'},
            {'passed': False, 'highest_stage': 'format', 'functional_checked': False, 'feedback': 'bad syntax'},
        ]
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(agent, 'call_model', side_effect=codes), mock.patch.object(agent, 'evaluate_candidate', side_effect=results):
            root = Path(tmp)
            result = agent.generate_agent_sample('p', root/'out.sv', root/'eval', 1, 'tb', 'ref', 1, False, False)
            self.assertEqual(result['selected_attempt'], 1)
            self.assertEqual((root/'out.sv').read_text().strip(), codes[0])
            self.assertEqual((root/'eval/attempt_2/candidate.sv').read_text().strip(), 'broken')
            self.assertTrue((root/'eval/attempt_1/evaluation.json').exists())

    def test_smoke_and_single_sample_metrics(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(agent, 'call_model', return_value='module TopModule; endmodule'):
            root = Path(tmp)
            (root/'problem.txt').write_text('p')
            args = argparse.Namespace(problem=str(root/'problem.txt'), output_dir=str(root/'out'),
                seed=1, testbench=None, reference=None, samples=1, repairs=0, skip_eda=True, skip_synthesis=True)
            result = agent.run_problem(args)
            self.assertTrue(result['samples'][0]['passed'])
            self.assertIsNone(result['pass_at_1'])
            self.assertIsNone(result['pass_at_5'])
            self.assertIsNone(result['baseline_pass'])
            args.skip_eda = False
            args.testbench = 'tb'
            with mock.patch.object(agent, 'evaluate_candidate', return_value={
                'passed': True, 'highest_stage': 'simulation', 'functional_checked': True}):
                result = agent.run_problem(args)
            self.assertTrue(result['pass_at_1'])
            self.assertIsNone(result['pass_at_5'])
            args.samples = 5
            with mock.patch.object(agent, 'evaluate_candidate', return_value={
                'passed': True, 'highest_stage': 'simulation', 'functional_checked': True}):
                result = agent.run_problem(args)
                self.assertTrue(result['pass_at_5'])
                args.testbench = None
                result = agent.run_problem(args)
                self.assertIsNone(result['pass_at_1'])
                self.assertIsNone(result['pass_at_5'])

    def test_simulation_rejects_conflicting_markers_and_errors(self):
        for output, expected in [('Mismatches: 0', True), ('Mismatches: 0\nMismatches: 2', False),
                                 ('Mismatches: 0\nFATAL: stopped', False), ('done', False)]:
            with self.subTest(output=output), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                source = root/'input.sv'
                source.write_text('module TopModule; endmodule')
                process = {'returncode': 0, 'output': output}
                with mock.patch.object(agent, 'run_process', return_value=process):
                    result = agent.evaluate_candidate(source, root/'eval', testbench='tb', skip_synthesis=True)
                self.assertEqual(result['passed'], expected)

    def test_missing_dataset_files_fail_before_inference(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(agent, 'run_problem') as run:
            root = Path(tmp)
            (root/'p_prompt.txt').write_text('p')
            args = argparse.Namespace(dataset=tmp, limit=None, output_dir=str(root/'out'))
            with self.assertRaisesRegex(RuntimeError, 'incomplete dataset'):
                agent.benchmark(args)
            run.assert_not_called()

    def test_benchmark_saves_completed_work_before_later_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for prefix in ('a', 'b'):
                for suffix in ('_prompt.txt', '_ref.sv', '_test.sv'):
                    (root/(prefix+suffix)).write_text('p')
            args = argparse.Namespace(dataset=tmp, limit=None, output_dir=str(root/'out'),
                samples=1, repairs=1, seed=1, skip_eda=False, skip_synthesis=True)
            result = {'baseline_pass': False, 'pass_at_1': True, 'pass_at_5': None, 'elapsed_s': 2}
            with mock.patch.object(agent, 'run_problem', side_effect=[result, RuntimeError('service lost')]):
                with self.assertRaisesRegex(RuntimeError, 'service lost'):
                    agent.benchmark(args)
            summary = json.loads((root/'out/benchmark.json').read_text())
            self.assertFalse(summary['complete'])
            self.assertEqual(summary['problems'], 1)
            self.assertEqual(summary['repaired_problems'], 1)
            self.assertEqual(summary['regressed_problems'], 0)
            self.assertIsNone(summary['pass_at_5'])


if __name__ == '__main__':
    unittest.main()
