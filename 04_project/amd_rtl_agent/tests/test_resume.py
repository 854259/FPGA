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

    def test_full_launcher_uses_protected_benchmark_and_preserves_machine_config(self):
        environment = {'LLM_BASE_URL': 'http://teammate.local/v1', 'LLM_MODEL': 'team-27b',
                       'LLM_API_KEY': 'test-only', 'VIVADO_BIN': 'E:/Vivado/2026.1/bin'}
        with mock.patch.dict(os.environ, environment, clear=True), \
             mock.patch.object(run_full_156, 'TOTAL', 2), mock.patch.object(agent, 'main', return_value=0) as run:
            self.assertEqual(run_full_156.main(['--dataset', str(self.dataset), '--output-dir', str(self.root/'full'), '--resume']), 0)
            self.assertEqual(os.environ['VIVADO_BIN'], environment['VIVADO_BIN'])
            self.assertEqual(os.environ['LLM_BASE_URL'], environment['LLM_BASE_URL'])
            self.assertEqual(os.environ['LLM_MODEL'], 'team-27b')
        self.assertEqual(run.call_args.args[0][0], 'benchmark')
        self.assertIn('--resume', run.call_args.args[0])

    def test_full_launcher_refuses_legacy_directory_without_changing_its_files(self):
        out = self.root/'legacy'
        agent.write_text(out/'progress.jsonl', '{"problem":"a"}\n')
        before = (out/'progress.jsonl').read_bytes()
        with mock.patch.dict(os.environ, {'LLM_API_KEY': 'test-only', 'LLM_MOCK_FILE': ''}), \
             mock.patch.object(run_full_156, 'TOTAL', 2):
            self.assertEqual(run_full_156.main(['--dataset', str(self.dataset), '--output-dir', str(out), '--resume']), 1)
        self.model.assert_not_called()
        self.assertEqual((out/'progress.jsonl').read_bytes(), before)

    def test_full_launcher_status_does_not_run_inference(self):
        agent.write_json(self.root/'status/benchmark.json', {'complete': False, 'problems': 1})
        with mock.patch.object(agent, 'main') as run:
            self.assertEqual(run_full_156.main(['--output-dir', str(self.root/'status'), '--status']), 0)
        run.assert_not_called()

    def test_checkpoint_protects_eda_evidence_as_well_as_candidate(self):
        original = agent.run_problem
        def with_reports(args):
            result = original(args)
            for name in ('01_xvlog.log', 'timing.rpt', 'post_synth.dcp', 'PASS'):
                agent.write_text(Path(args.output_dir)/name, 'original evidence')
            return result
        with mock.patch.object(agent, 'run_problem', side_effect=with_reports):
            agent.benchmark(self.args)
        self.args.resume = True
        self.model.reset_mock()
        for name in ('01_xvlog.log', 'timing.rpt', 'post_synth.dcp', 'PASS'):
            path = self.root/'out/a'/name
            path.write_text('changed')
            with self.assertRaisesRegex(RuntimeError, 'artifact missing or changed'):
                agent.benchmark(self.args)
            path.write_text('original evidence')
        self.model.assert_not_called()


if __name__ == '__main__':
    unittest.main()
