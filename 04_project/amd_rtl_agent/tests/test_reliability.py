import argparse
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent


class ReliabilityTests(unittest.TestCase):
    def test_feedback_retains_root_error_and_final_mismatch_count(self):
        log = "ERROR: root syntax error [E:/very/long/path/candidate.sv:17]\n"
        log += "\n".join(f"ERROR: cascading diagnostic {i}" for i in range(300))
        log += "\nMismatches: 12 in 300 samples"
        feedback = agent.compact_feedback(log)
        self.assertLessEqual(len(feedback), 4096)
        self.assertTrue(feedback.startswith('ERROR: root syntax error [line 17]'))
        self.assertTrue(feedback.endswith('Mismatches: 12 in 300 samples'))

    def test_repair_selects_lower_simulation_error_rate(self):
        codes = ['module TopModule; wire a; endmodule', 'module TopModule; wire b; endmodule']
        results = [dict(passed=False, highest_stage='simulation', functional_checked=True,
                        feedback=f'Mismatches: {n} in 100 samples') for n in (80, 10)]
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(agent, 'call_model', side_effect=codes), mock.patch.object(agent, 'evaluate_candidate', side_effect=results):
            root = Path(tmp)
            result = agent.generate_agent_sample('p', root/'out.sv', root/'eval', 1, 'tb', 'ref', 1, False, False)
            self.assertEqual(result['selected_attempt'], 2)
            self.assertFalse(result['passed'])
            self.assertEqual((root/'out.sv').read_text().strip(), codes[1])

    def test_mismatch_ranking_normalizes_sample_count_and_preserves_stage(self):
        def result(stage, feedback):
            return dict(passed=False, highest_stage=stage, feedback=feedback)
        self.assertGreater(agent.quality(result('simulation', 'Mismatches: 20 in 100 samples')),
                           agent.quality(result('simulation', 'Mismatches: 5 in 10 samples')))
        self.assertGreater(agent.quality(result('synthesis', '')),
                           agent.quality(result('simulation', 'Mismatches: 0 in 100 samples')))
        agent.quality(result('simulation', 'Mismatches: 1 in 0 samples'))

    def test_repair_feedback_explains_observed_declaration_error(self):
        feedback = agent.repair_feedback('module TopModule; endmodule',
                                        'procedural assignment to a non-register q is not permitted')
        self.assertIn('reg', feedback)
        self.assertIn('logic', feedback)

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
            result = {'baseline_pass': False, 'pass_at_1': True, 'pass_at_5': None, 'elapsed_s': 2,
                      'samples': [{'selected_attempt': 1, 'attempt_history': [{'passed': True}]}]}
            with mock.patch.object(agent, 'run_problem', side_effect=[result, RuntimeError('service lost')]):
                with self.assertRaisesRegex(RuntimeError, 'service lost'):
                    agent.benchmark(args)
            summary = json.loads((root/'out/benchmark.json').read_text())
            self.assertFalse(summary['complete'])
            self.assertEqual(summary['problems'], 1)
            self.assertEqual(summary['improved_problems'], 1)
            self.assertEqual(summary['repaired_problems'], 0)
            self.assertEqual(summary['regressed_problems'], 0)
            self.assertIsNone(summary['pass_at_5'])

    def test_benchmark_counts_actual_repairs_independently_of_baseline(self):
        for passed, selected, initial, expected in [(True, 2, False, 1), (False, 1, False, 0),
                                                    (None, 2, False, None)]:
            with self.subTest(passed=passed), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                for suffix in ('_prompt.txt', '_ref.sv', '_test.sv'):
                    (root/('a'+suffix)).write_text('p')
                args = argparse.Namespace(dataset=tmp, limit=None, output_dir=str(root/'out'),
                    samples=1, repairs=1, seed=1, skip_eda=False, skip_synthesis=True)
                result = {'baseline_pass': True, 'pass_at_1': passed, 'pass_at_5': None, 'elapsed_s': 2,
                          'samples': [{'selected_attempt': selected, 'attempt_history': [{'passed': initial}]}]}
                with mock.patch.object(agent, 'run_problem', return_value=result):
                    summary = agent.benchmark(args)
                self.assertTrue(summary['complete'])
                self.assertEqual(summary['repaired_problems'], expected)
                self.assertEqual(summary['improved_problems'], 0)

    def test_nonpositive_benchmark_limit_rejected_before_inference(self):
        for limit in (0, -1):
            with self.subTest(limit=limit), mock.patch.object(agent, 'run_problem') as run:
                with self.assertRaisesRegex(ValueError, 'limit must be positive'):
                    agent.benchmark(argparse.Namespace(limit=limit))
                run.assert_not_called()

    def test_benchmark_offset_selects_next_ten_and_preserves_seeds(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for index in range(1, 21):
                for suffix in ('_prompt.txt', '_ref.sv', '_test.sv'):
                    (root / (f'Prob{index:03d}' + suffix)).write_text('p')
            args = argparse.Namespace(dataset=tmp, offset=10, limit=10, output_dir=str(root/'out'),
                samples=1, repairs=1, seed=1, skip_eda=False, skip_synthesis=False)
            result = {'baseline_pass': True, 'pass_at_1': True, 'pass_at_5': None, 'elapsed_s': 1,
                      'samples': [{'selected_attempt': 1, 'attempt_history': [{'passed': True}]}]}
            with mock.patch.object(agent, 'run_problem', return_value=result) as run:
                summary = agent.benchmark(args)
            self.assertEqual([Path(call.args[0].problem).name for call in run.call_args_list],
                             [f'Prob{i:03d}_prompt.txt' for i in range(11, 21)])
            self.assertEqual([call.args[0].seed for call in run.call_args_list], list(range(1001, 2001, 100)))
            self.assertTrue(summary['complete'])
            self.assertEqual(summary['problems'], 10)
            self.assertEqual(summary['offset'], 10)

    def test_negative_benchmark_offset_rejected(self):
        with self.assertRaisesRegex(ValueError, 'offset must be non-negative'):
            agent.benchmark(argparse.Namespace(limit=10, offset=-1))

    def test_model_rejects_malformed_response_without_retry(self):
        payloads = [None, [], {}, {'choices': []}]
        payloads += [{'choices': [{'message': {'content': value}}]} for value in (None, '', '  ', [], 12)]
        for payload in payloads:
            with self.subTest(payload=payload), mock.patch.dict(os.environ, {'LLM_MOCK_FILE': ''}), mock.patch.object(agent.urllib.request, 'urlopen') as request:
                request.return_value.__enter__.return_value.read.return_value = json.dumps(payload).encode()
                with self.assertRaisesRegex(RuntimeError, 'model request failed'):
                    agent.call_model([{'role': 'user', 'content': 'p'}], 1)
                self.assertEqual(request.call_count, 1)

    def test_model_accepts_valid_response(self):
        with mock.patch.dict(os.environ, {'LLM_MOCK_FILE': ''}), mock.patch.object(agent.urllib.request, 'urlopen') as request:
            request.return_value.__enter__.return_value.read.return_value = json.dumps(
                {'choices': [{'message': {'content': 'module TopModule; endmodule'}}]}).encode()
            self.assertEqual(agent.call_model([{'role': 'user', 'content': 'p'}], 1), 'module TopModule; endmodule')


if __name__ == '__main__':
    unittest.main()
