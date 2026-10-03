"""No EDA/model calls: exercise complete R1 grading flow and fail-closed gates."""
import argparse
from contextlib import ExitStack
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PILOT_DIR = ROOT.parents[1] / '03_analysis/diagnostic_repair_pilot_20261003'


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


pilot = module('generation_for_grader_tests', ROOT / 'bench/diagnostic_repair_pilot.py')
grader = module('independent_grader_tests', PILOT_DIR / 'grade_pilot.py')


class GraderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.kit = self.base / 'kit'
        self.run = self.base / 'run'
        shutil.copytree(ROOT / 'submission', self.kit / 'submission', ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copytree(ROOT / 'official_reference', self.kit / 'official_reference', ignore=shutil.ignore_patterns('__pycache__'))
        (self.kit / 'bench').mkdir()
        shutil.copyfile(ROOT / 'bench/diagnostic_repair_pilot.py', self.kit / 'bench/diagnostic_repair_pilot.py')
        task = self.kit / 'bench/tasks_veval' / grader.TASK
        task.mkdir(parents=True)
        pilot.write_json(task / 'task.json', {'task_id': grader.TASK})
        shutil.copyfile(PILOT_DIR / 'input/prompt.txt', task / 'prompt.txt')
        self.slot = self.base / 'slot'
        self.slot.write_text('grader_test\nunchanged receipt\n')
        with patch('builtins.print'):
            pilot.freeze(argparse.Namespace(inputs=PILOT_DIR / 'input', package=self.kit / 'submission',
                                            out=self.run, endpoint='http://127.0.0.1:8000/v1'))
            fake_baseline = types.SimpleNamespace(served_model=lambda: pilot.MODEL)
            with patch.object(pilot, 'baseline_module', return_value=fake_baseline), \
                 patch.object(pilot.subprocess, 'run', side_effect=self.generate):
                code = pilot.run(argparse.Namespace(out=self.run, slot_file=self.slot, slot_owner='grader_test'))
                self.assertEqual(code, 0)
        self.args = argparse.Namespace(run=self.run, kit=self.kit, evaluator=ROOT / 'official_eval.py',
                                       slot_owner='grader_test', slot_file=self.slot)
        self.tools = {}
        for name in ('xvlog', 'xelab'):
            path = self.base / name
            path.write_bytes(b'fake tool identity, never executed')
            self.tools[name] = str(path)
        self.events = []
        self.error_at = None
        self.drop_evidence_at = None
        self.change_slot_at = None

    def generate(self, command, **kwargs):
        sample = self.run / command[-1]
        # An empty candidate must stay in the denominator.
        code = '' if sample.name.startswith('00') else 'module TopModule; endmodule'
        (sample / 'reply.txt').write_text(code, encoding='utf-8')
        (sample / 'solution.v').write_text(code + '\n' if code else '', encoding='utf-8')
        pilot.write_json(sample / 'response.json', dict(model=pilot.MODEL, usage={'completion_tokens': 9},
                         choices=[dict(message=dict(content=code), finish_reason='stop')]))
        return subprocess.CompletedProcess(command, 0)

    def fake_judge(self, task, solution, dst, verdict_path, deadline):
        index = len([e for e in self.events if e[0] == 'official'])
        self.events.append(('official', solution.parent.name))
        empty = not solution.read_text().strip()
        level = 0 if empty or 'control' in solution.parent.name else 1
        verdict = dict(task_id=grader.TASK, level=level, coefficient={0: 0.0, 1: 0.2}[level],
                       elapsed_s=1.0, tool_error='license missing' if index == self.error_at else None,
                       judge_rc=0, judge_evidence_complete=True, suspected_silent_degradation=False)
        evidence = dst / 'judge_work_logs'
        evidence.mkdir()
        log = evidence / 'w_judge.log'
        log.write_text('mock complete evidence\n')
        receipt = dict(judge_rc=0, errors=[], evidence={log.name: {'bytes': log.stat().st_size, 'sha256': grader.digest(log)}})
        grader.write_json(dst / 'judge_receipt.json', receipt)
        grader.write_json(verdict_path, verdict)
        if index == self.drop_evidence_at:
            log.unlink()
        if index == self.change_slot_at:
            self.slot.write_text('someone_else\n')
        return verdict

    def evaluator(self, path, kit):
        actual = grader.load_module('real_adapter_for_pilot_test', path)
        actual.ROOT = kit
        actual.OFFICIAL = kit / 'official_reference'
        self.assertEqual(actual.verify_upstream(), grader.UPSTREAM_COMMIT)
        actual.judge_sample = self.fake_judge
        return actual

    def fake_tool(self, command, cwd, label):
        self.events.append((label, cwd.name))
        self.assertEqual(command[0], self.tools[label])
        # The compile/elaboration directory receives the candidate only.
        self.assertTrue((cwd / 'dut.sv').is_file())
        self.assertFalse((cwd / 'task.json').exists())
        self.assertFalse(any('tb' in p.name.lower() for p in cwd.iterdir()))
        result = dict(command=command, timeout=False, returncode=0, wall_seconds=0.1)
        grader.write_json(cwd / (label + '.execution.json'), result)
        return result

    def grade(self):
        with ExitStack() as stack:
            stack.enter_context(patch.object(grader, 'load_evaluator', side_effect=self.evaluator))
            stack.enter_context(patch.object(grader.shutil, 'which', side_effect=lambda name: self.tools[name]))
            stack.enter_context(patch.object(grader, 'run_tool', side_effect=self.fake_tool))
            stack.enter_context(patch('builtins.print'))
            result = grader.grade(self.args)
        output = sorted(self.run.glob('grading_*'))[-1]
        return result, grader.read_json(output / 'summary.json'), output

    def test_official_six_before_structure_and_empty_counts_in_mean(self):
        result, report, output = self.grade()
        self.assertEqual(result, 0, report)
        self.assertEqual([e[0] for e in self.events[:6]], ['official'] * 6)
        self.assertNotIn('official', [e[0] for e in self.events[6:]])
        self.assertEqual(report['valid_samples'], 6)
        self.assertEqual(report['arms']['diagnostic']['levels'], [0, 1, 1])
        self.assertEqual(report['arms']['diagnostic']['coefficient_mean'], 0.1333)
        self.assertEqual(report['arms']['diagnostic']['empty_answers'], 1)
        self.assertEqual(report['arms']['diagnostic']['elaboration_passed'], 2)
        self.assertEqual(report['decision'], 'no_promotion_archive_this_implementation')
        self.assertEqual(grader.read_json(output / 'before.json'), grader.read_json(output / 'after.json'))
        # Re-running is a distinct preserved grading, never an overwrite.
        first_summary = (output / 'summary.json').read_bytes()
        _, _, second = self.grade()
        self.assertNotEqual(second, output)
        self.assertEqual((output / 'summary.json').read_bytes(), first_summary)

    def test_incomplete_generation_runs_no_judge(self):
        path = self.run / 'generation.json'
        value = grader.read_json(path)
        value['complete'] = False
        grader.write_json(path, value)
        result, report, _ = self.grade()
        self.assertEqual(result, 1)
        self.assertFalse(report['complete'])
        self.assertEqual(self.events, [])

    def test_request_and_solution_tampering_stop_before_judgement(self):
        for file in ('request.json', 'solution.v'):
            with self.subTest(file=file):
                path = self.run / '00_pair0_diagnostic' / file
                original = path.read_bytes()
                path.write_bytes(original + b'changed')
                result, _, _ = self.grade()
                self.assertEqual(result, 1)
                self.assertEqual(self.events, [])
                path.write_bytes(original)

    def test_environment_failure_is_not_excluded_to_get_smaller_denominator(self):
        self.error_at = 1
        result, report, _ = self.grade()
        self.assertEqual(result, 1)
        self.assertEqual(len(self.events), 2)
        self.assertEqual(report['valid_samples'], 1)
        self.assertEqual(report['decision'], 'not_determinable')
        self.assertNotIn('arms', report)

    def test_missing_retained_judge_evidence_stops_batch(self):
        self.drop_evidence_at = 0
        result, report, _ = self.grade()
        self.assertEqual(result, 1)
        self.assertEqual(len(self.events), 1)
        self.assertEqual(report['valid_samples'], 0)

    def test_slot_change_stops_without_writing_or_releasing_lock(self):
        self.change_slot_at = 0
        result, report, _ = self.grade()
        self.assertEqual(result, 1)
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.slot.read_text(), 'someone_else\n')
        self.assertEqual(report['decision'], 'not_determinable')

    def test_promotion_requires_both_score_and_structure_conditions(self):
        score = grader.load_module('official_score_for_r1_decision_test', ROOT / 'official_reference/selftest/score.py')
        samples = []
        for pair in range(3):
            for arm in ('diagnostic', 'control'):
                samples.append(dict(pair=pair, arm=arm,
                                    verdict=dict(task_id=grader.TASK, level=1 if arm == 'diagnostic' else 0,
                                                 coefficient=0.2 if arm == 'diagnostic' else 0.0, tool_error=None),
                                    generation=dict(wall_seconds=1, empty=False),
                                    structure=dict(passed=arm == 'diagnostic')))
        report, _ = grader.summarize(score, samples)
        self.assertTrue(report['decision'].startswith('single_candidate_positive_signal'))
        for sample in samples:
            sample['verdict'].update(level=1, coefficient=0.2)
        report, _ = grader.summarize(score, samples)
        self.assertEqual(report['decision'], 'structure_improved_without_quality_score_advantage')
        samples[0]['verdict']['tool_error'] = 'environment failure'
        with self.assertRaisesRegex(ValueError, 'not all six'):
            grader.summarize(score, samples)


if __name__ == '__main__':
    unittest.main()
