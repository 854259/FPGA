"""Exercise the pinned judge adapter with a fake lower-level tool, without EDA."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


evaluation = load('eval_evidence_test', ROOT / 'official_eval.py')


class JudgeEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.task = self.root / 'task'
        self.task.mkdir()
        (self.task / 'task.json').write_text(json.dumps({
            'task_id': 'ProbTest', 'reference_module': 'ref.sv', 'testbench': 'tb.sv'}))
        self.dst = self.root / 'sample'
        self.dst.mkdir()
        self.solution = self.dst / 'solution.v'
        self.solution.write_text('module TopModule; endmodule\n')
        self.verdict = self.root / 'agent.ProbTest.s0.json'
        self.level = 3
        self.outer_rc = 0
        self.omit_tool_log = False
        self.tool_calls = 0

    def runner(self, cmd, **kwargs):
        """Run real judge.py logic; replace only its call to veval-judge.

        Importing the pinned file under the supplied environment proves the
        scratch variable and directory convention, rather than duplicating them
        in a fake adapter that could agree with a broken implementation.
        """
        if str(cmd[1]).endswith('judge.py'):
            with mock.patch.dict(os.environ, kwargs['env'], clear=True):
                judge = load('pinned_judge_evidence_test', ROOT / 'official_reference/selftest/judge.py')
                output = io.StringIO()
                with contextlib.redirect_stdout(output):
                    judge.main(cmd[2:])
            return subprocess.CompletedProcess(cmd, self.outer_rc, output.getvalue(), '')
        self.tool_calls += 1
        self.assertTrue(str(cmd[1]).endswith('veval-judge'))
        work = Path(cmd[cmd.index('--workdir') + 1])
        work.mkdir(parents=True, exist_ok=True)
        if not self.omit_tool_log:
            (work / 'judge.log').write_text('compiler and simulation stage output\n')
        stages = {'xvlog_dut': {'rc': 1 if self.level == 0 else 0}}
        if self.level >= 1:
            stages['xsim'] = {'rc': 0}
        if self.level >= 2:
            synth = work / 'synth'
            synth.mkdir()
            (synth / 'synth.log').write_text('raw synthesis output\n')
            stages['synth'] = {'rc': 0 if self.level == 3 else -15,
                               'status': 'OK' if self.level == 3 else 'SYNTH_FAIL'}
            if self.level == 3:
                (synth / 'synth.json').write_text('{"status":"OK"}')
        raw = {'level': self.level, 'verdict': 'L' + str(self.level), 'stages': stages}
        Path(cmd[cmd.index('--json') + 1]).write_text(json.dumps(raw))
        return subprocess.CompletedProcess(cmd, 0, '', '')

    def call(self):
        with mock.patch.object(evaluation.subprocess, 'run', side_effect=self.runner):
            return evaluation.judge_sample(self.task, self.solution, self.dst, self.verdict, 10)

    def receipt(self):
        return json.loads((self.dst / 'judge_receipt.json').read_text())

    def test_pinned_workdir_convention_and_all_stage_logs_are_preserved(self):
        result = self.call()
        self.assertEqual(result['level'], 3)
        self.assertEqual(result['coefficient'], 1)
        self.assertTrue(result['judge_evidence_complete'])
        self.assertIn('w_judge.log', result['judge_evidence'])
        self.assertIn('w_synth_synth.log', result['judge_evidence'])
        self.assertIn('w_synth_synth.json', result['judge_evidence'])
        self.assertEqual(result['judge_log_bytes'], sum(
            (self.dst / 'judge_work_logs' / name).stat().st_size
            for name in ('w_judge.log', 'w_synth_synth.log')))
        self.assertFalse(list(self.dst.glob('judge-scratch-*')))
        self.assertIsNone(self.receipt()['scratch_retained'])
        self.assertEqual(self.receipt()['errors'], [])
        # Outer --quiet log is empty; it must not mask the real stage logs.
        self.assertEqual((self.dst / 'judge_logs/ProbTest.judge.log').stat().st_size, 0)
        raw = json.loads((self.dst / 'judge_work_logs/adapter_verdict.json').read_text())
        self.assertNotIn('judge_evidence', raw)

    def test_compile_failure_preserves_compile_log_without_requiring_synth(self):
        self.level = 0
        result = self.call()
        self.assertEqual(result['level'], 0)
        self.assertIn('w_judge.log', result['judge_evidence'])
        self.assertNotIn('w_synth_synth.log', result['judge_evidence'])

    def test_simulation_failure_preserves_logs_and_official_l1(self):
        self.level = 1
        result = self.call()
        self.assertEqual(result['level'], 1)
        self.assertEqual(result['coefficient'], .2)
        self.assertFalse(result['suspected_silent_degradation'])

    def test_synthesis_failure_is_flagged_without_changing_official_l2(self):
        self.level = 2
        result = self.call()
        self.assertEqual(result['level'], 2)
        self.assertEqual(result['coefficient'], .7)
        self.assertTrue(result['suspected_silent_degradation'])
        raw = json.loads((self.dst / 'judge_work_logs/verdict.json').read_text())
        self.assertEqual(raw['stages']['synth']['rc'], -15)
        self.assertEqual(result['judge_rc'], 0)  # wrapper rc is distinct from stage rc

    def test_empty_answer_is_l0_with_no_tool_invocation_or_workdir(self):
        self.solution.write_text('  \n')
        result = self.call()
        self.assertEqual(result['level'], 0)
        self.assertEqual(result['coefficient'], 0)
        self.assertEqual(self.tool_calls, 0)
        self.assertEqual(result['judge_evidence'], [])
        self.assertEqual(result['judge_log_bytes'], 0)
        self.assertFalse(list(self.dst.glob('judge-scratch-*')))

    def test_nonzero_wrapper_rc_stops_even_with_valid_new_verdict(self):
        self.outer_rc = 1
        with self.assertRaises(RuntimeError):
            self.call()
        receipt = self.receipt()
        self.assertEqual(receipt['judge_rc'], 1)
        self.assertIn('judge did not exit successfully', receipt['errors'])
        self.assertEqual(json.loads((self.dst / 'judge_work_logs/adapter_verdict.json').read_text())['level'], 3)
        self.assertFalse(list(self.dst.glob('judge-scratch-*')))

    def test_missing_verdict_fails_and_cleans_only_owned_scratch(self):
        sentinel = self.root / 'judge_someone_else'
        sentinel.mkdir()
        (sentinel / 'keep.txt').write_text('unrelated work')
        with mock.patch.object(evaluation.subprocess, 'run', return_value=
                               subprocess.CompletedProcess(['judge'], 1, '', 'crash')):
            with self.assertRaises(RuntimeError):
                evaluation.judge_sample(self.task, self.solution, self.dst, self.verdict, 10)
        self.assertTrue((sentinel / 'keep.txt').is_file())
        self.assertFalse(list(self.dst.glob('judge-scratch-*')))
        self.assertTrue(self.receipt()['errors'])
        self.assertFalse(self.verdict.exists())

    def test_json_or_dut_bytes_do_not_substitute_for_missing_tool_log(self):
        self.omit_tool_log = True
        with self.assertRaises(RuntimeError):
            self.call()
        receipt = self.receipt()
        self.assertTrue(any('w_judge.log' in error for error in receipt['errors']))
        self.assertTrue(Path(receipt['scratch_retained']).is_dir())

    def test_copy_failure_retains_source_and_receipt_for_recovery(self):
        with mock.patch.object(evaluation.shutil, 'copyfile', side_effect=OSError('disk full')):
            with self.assertRaises(RuntimeError):
                self.call()
        receipt = self.receipt()
        self.assertTrue(any('disk full' in error for error in receipt['errors']))
        self.assertTrue(list(Path(receipt['scratch_retained']).glob('judge_*/w/judge.log')))

    def test_stale_verdict_is_never_reused_or_overwritten(self):
        self.verdict.write_text('old evidence')
        with mock.patch.object(evaluation.subprocess, 'run') as runner:
            with self.assertRaises(FileExistsError):
                evaluation.judge_sample(self.task, self.solution, self.dst, self.verdict, 10)
        runner.assert_not_called()
        self.assertEqual(self.verdict.read_text(), 'old evidence')

    def test_metadata_preserves_official_summary(self):
        self.call()
        score = evaluation.summarize(self.root, ['ProbTest'], ['agent'], 1)
        self.assertEqual(score['modes']['agent']['set_score'], 1)
        self.assertEqual(score['modes']['agent']['tool_errors'], 0)

    def test_invocation_exception_still_writes_failure_receipt_and_cleans(self):
        with mock.patch.object(evaluation.subprocess, 'run', side_effect=OSError('cannot launch')):
            with self.assertRaises(RuntimeError):
                evaluation.judge_sample(self.task, self.solution, self.dst, self.verdict, 10)
        self.assertTrue(any('cannot launch' in e for e in self.receipt()['errors']))
        self.assertFalse(list(self.dst.glob('judge-scratch-*')))

    def test_pinned_judge_timeout_retains_work_for_process_inspection(self):
        def runner(cmd, **kwargs):
            if str(cmd[1]).endswith('veval-judge'):
                raise subprocess.TimeoutExpired(cmd, 10)
            return self.runner(cmd, **kwargs)
        with mock.patch.object(evaluation.subprocess, 'run', side_effect=runner):
            with self.assertRaises(RuntimeError):
                evaluation.judge_sample(self.task, self.solution, self.dst, self.verdict, 10)
        receipt = self.receipt()
        self.assertTrue(any('inspect owned EDA' in e for e in receipt['errors']))
        self.assertTrue(Path(receipt['scratch_retained']).is_dir())


if __name__ == '__main__':
    unittest.main()
