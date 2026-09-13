import argparse
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import agent
from bench import run_full_156


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.dataset = self.root/'dataset'
        self.dataset.mkdir()
        for name in ('a', 'b'):
            for suffix in ('_prompt.txt', '_ref.sv', '_test.sv'):
                (self.dataset/(name+suffix)).write_text('module TopModule; endmodule')
        self.args = argparse.Namespace(dataset=str(self.dataset), output_dir=str(self.root/'out'),
            limit=None, offset=0, samples=1, repairs=1, seed=7, skip_eda=True, skip_synthesis=True, resume=False)
        self.model = mock.patch.object(agent, 'call_model', return_value='module TopModule; endmodule').start()
        self.addCleanup(mock.patch.stopall)

    def test_complete_resume_makes_no_model_calls_and_preserves_metrics(self):
        first = agent.benchmark(self.args)
        self.assertEqual(first['total_model_calls'], 4)
        self.assertIsNone(first['pass_at_1'])
        self.args.resume = True
        self.model.reset_mock()
        second = agent.benchmark(self.args)
        self.model.assert_not_called()
        self.assertEqual(first, second)

    def test_interruption_resumes_only_unfinished_problem_and_keeps_partial_files(self):
        original = agent.run_problem
        def interrupted(args):
            if Path(args.problem).name.startswith('b_'):
                partial = Path(args.output_dir)/'partial.txt'
                agent.write_text(partial, 'preserve this')
                raise RuntimeError('simulated disconnect')
            return original(args)
        with mock.patch.object(agent, 'run_problem', side_effect=interrupted):
            with self.assertRaisesRegex(RuntimeError, 'disconnect'):
                agent.benchmark(self.args)
        self.assertFalse((self.root/'out/.benchmark.lock').exists())
        self.args.resume = True
        self.model.reset_mock()
        result = agent.benchmark(self.args)
        self.assertEqual(self.model.call_count, 2)
        self.assertTrue(result['complete'])
        self.assertEqual((self.root/'out/b/partial.txt').read_text(), 'preserve this')
        child = json.loads((self.root/'out/b/restart_1/result.json').read_text())
        self.assertEqual(child['samples'][0]['seed'], 108)

    def test_checkpoint_survives_crash_before_summary_update(self):
        original = agent.write_json
        def fail_summary(path, value):
            if path.name == 'benchmark.json' and value['problems'] == 1:
                raise OSError('disk interruption')
            return original(path, value)
        with mock.patch.object(agent, 'write_json', side_effect=fail_summary):
            with self.assertRaisesRegex(OSError, 'disk interruption'):
                agent.benchmark(self.args)
        self.args.resume = True
        self.model.reset_mock()
        result = agent.benchmark(self.args)
        self.assertEqual(result['problems'], 2)
        self.assertEqual(self.model.call_count, 2)

    def test_changed_config_or_dataset_rejected_before_inference(self):
        agent.benchmark(self.args)
        self.args.resume = True
        self.args.seed += 1
        self.model.reset_mock()
        with self.assertRaisesRegex(RuntimeError, 'mismatch'):
            agent.benchmark(self.args)
        self.args.seed -= 1
        (self.dataset/'b_test.sv').write_text('changed testbench')
        with self.assertRaisesRegex(RuntimeError, 'mismatch'):
            agent.benchmark(self.args)
        self.model.assert_not_called()

    def test_modified_candidate_rejected(self):
        agent.benchmark(self.args)
        (self.root/'out/a/best.sv').write_text('changed')
        self.args.resume = True
        self.model.reset_mock()
        with self.assertRaisesRegex(RuntimeError, 'artifact missing or changed'):
            agent.benchmark(self.args)
        self.model.assert_not_called()

    def test_existing_output_requires_explicit_resume(self):
        agent.benchmark(self.args)
        summary = (self.root/'out/benchmark.json').read_bytes()
        with self.assertRaisesRegex(RuntimeError, 'not empty'):
            agent.benchmark(self.args)
        self.assertEqual((self.root/'out/benchmark.json').read_bytes(), summary)

    def test_lock_does_not_delete_other_writers_lock(self):
        lock = self.root/'out/.benchmark.lock'
        agent.write_text(lock, 'other process')
        with self.assertRaisesRegex(RuntimeError, 'locked'):
            agent.benchmark(self.args)
        self.assertEqual(lock.read_text(), 'other process')
        self.model.assert_not_called()

    def test_experiment_never_persists_api_key_or_endpoint_credentials(self):
        with mock.patch.dict(os.environ, {'LLM_API_KEY': 'secret-test-api-key',
                                         'LLM_BASE_URL': 'https://user:secret-password@example.test/v1'}):
            agent.benchmark(self.args)
        saved = (self.root/'out/experiment.json').read_text()
        self.assertNotIn('secret-test-api-key', saved)
        self.assertNotIn('secret-password', saved)

    def test_legacy_launcher_retries_into_fresh_directories(self):
        directories = []
        def run(command, **kwargs):
            output = Path(command[command.index('--output-dir') + 1])
            self.assertFalse(output.exists())
            output.mkdir(parents=True)
            directories.append(output)
            if len(directories) == 1:
                (output/'partial.txt').write_text('keep')
                return argparse.Namespace(returncode=1)
            agent.write_json(output/'benchmark.json', {'records': [dict(
                baseline_pass=True, pass_at_1=True, repair_succeeded=False, elapsed_s=1)]})
            return argparse.Namespace(returncode=0)
        with mock.patch.object(run_full_156.subprocess, 'run', side_effect=run), mock.patch.object(run_full_156.time, 'sleep'):
            result = run_full_156.run_one(0, 'p', self.root/'legacy', {})
        self.assertTrue(result['pass_at_1'])
        self.assertEqual(result['attempts'], 2)
        self.assertNotEqual(*directories)
        self.assertEqual((directories[0]/'partial.txt').read_text(), 'keep')


if __name__ == '__main__':
    unittest.main()
