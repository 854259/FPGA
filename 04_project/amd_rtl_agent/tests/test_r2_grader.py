"""R2 end-to-end grading gates using real pinned scoring and fake EDA calls."""
import argparse
from contextlib import ExitStack
import importlib.util
from pathlib import Path
import shutil
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
PILOT = ROOT.parents[1] / '03_analysis/r2_signedness_20261003'
spec = importlib.util.spec_from_file_location('r2_grader_under_test', PILOT / 'grade_pilot.py')
grader = importlib.util.module_from_spec(spec)
spec.loader.exec_module(grader)


class R2GraderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.kit, self.run = self.base / 'kit', self.base / 'run'
        self.run.mkdir()
        for name in grader.PACKAGE_SHA:
            target = self.kit / 'submission' / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / 'submission' / name, target)
        shutil.copytree(ROOT / 'official_reference', self.kit / 'official_reference',
                        ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copytree(PILOT / 'input', self.run / 'inputs')
        self.probes = self.base / 'probes' / 'probe_runner.py'
        shutil.copytree(PILOT / 'probes', self.probes.parent, ignore=shutil.ignore_patterns('__pycache__'))
        self.harness = self.base / 'signedness_repair_pilot.py'
        self.harness.write_text('# frozen generation fixture\n')
        self.slot = self.base / 'slot'
        self.slot.write_text('r2_test\nunchanged\n')
        self.validation = self.base / 'controls' / 'controls_validation.json'
        self.validation.parent.mkdir()
        controls = {}
        for task in grader.TASKS:
            controls[task] = dict(valid=True)
            for role in ('positive', 'negative'):
                controls[task][role] = self.make_probe(task, self.probes.parent / task / (role + '.sv'),
                    self.validation.parent / task / role, 'pass' if role == 'positive' else 'fail')
            official_task = self.kit / 'bench/tasks_veval' / task
            official_task.mkdir(parents=True)
            grader.write_json(official_task / 'task.json', dict(task_id=task))
            # Actual kit task prompts also omit the outer blank lines.
            text = (self.run / 'inputs' / task / 'prompt.txt').read_text(encoding='utf-8').strip('\n')
            (official_task / 'prompt.txt').write_text(text, encoding='utf-8', newline='\n')
        assets = {'probe_runner.py': grader.digest(self.probes)}
        assets.update({task + '/' + name: grader.digest(self.probes.parent / task / name)
                       for task in grader.TASKS for name in ('tb.sv', 'positive.sv', 'negative.sv')})
        grader.write_json(self.validation, dict(schema_version=1, complete=True, valid=True,
                                               assets_unchanged=True, tasks=controls, probe_files=assets))
        auxiliary = {str(self.probes.parent / rel): sha for rel, sha in assets.items()}
        auxiliary[str(Path(grader.__file__).resolve())] = grader.digest(grader.__file__)
        rows, generated = [], []
        for sequence, (task, pair, arm) in enumerate(grader.ORDER):
            name = f'{sequence:02d}_{task}_pair{pair}_{arm}'
            sample = self.run / name
            sample.mkdir()
            grader.write_json(sample / 'request.json', dict(model=grader.MODEL, temperature=0,
                top_p=1, max_tokens=8192, messages=[]))
            row = dict(sequence=sequence, task_id=task, pair=pair, arm=arm, directory=name,
                       request_sha256=grader.digest(sample / 'request.json'))
            reply = 'module TopModule; endmodule'
            (sample / 'reply.txt').write_text(reply, encoding='utf-8')
            (sample / 'solution.v').write_text(reply + '\n', encoding='utf-8', newline='\n')
            (sample / 'client.log').write_text('mock client log\n')
            grader.write_json(sample / 'response.json', dict(model=grader.MODEL, usage={'completion_tokens': 9},
                choices=[dict(message=dict(content=reply), finish_reason='stop')]))
            record = dict(row, wall_seconds=1.0, error=None, empty=False, finish_reason='stop',
                usage={'completion_tokens': 9}, solution_sha256=grader.digest(sample / 'solution.v'))
            grader.write_json(sample / 'generation.json', record)
            rows.append(row)
            generated.append(record)
        self.plan = dict(schema='r2-signedness-pilot-v1', task_ids=list(grader.TASKS),
            planned_calls=12, repetitions=2, model=grader.MODEL, package=str(self.kit / 'submission'),
            package_sha256=grader.PACKAGE_SHA, harness_path=str(self.harness),
            harness_sha256=grader.digest(self.harness), input_sha256=grader.files_under(self.run / 'inputs'),
            per_call_wall_limit_s=300, max_output_tokens_per_call=8192, temperature=0, records=rows,
            probe_validation=dict(path=str(self.validation), sha256=grader.digest(self.validation)),
            auxiliary_sha256=auxiliary)
        grader.write_json(self.run / 'plan.json', self.plan)
        grader.write_json(self.run / 'generation.json', dict(complete=True, status='generated_ungraded',
            served_model_before=grader.MODEL, calls_attempted=12, records=generated,
            plan_sha256=grader.digest(self.run / 'plan.json')))
        self.args = argparse.Namespace(run=self.run, kit=self.kit, evaluator=ROOT / 'official_eval.py',
            probes=self.probes, slot_file=self.slot, slot_owner='r2_test')
        self.tools = {}
        for name in ('xvlog', 'xelab', 'xsim'):
            path = self.base / name
            path.write_text('fake binary identity only\n')
            self.tools[name] = str(path)
        self.events, self.level_overrides, self.probe_overrides = [], {}, {}
        self.tool_error_at = self.missing_log_at = self.change_slot_at = None

    def make_probe(self, task, solution, destination, status):
        destination.mkdir(parents=True, exist_ok=False)
        stages = []
        for name in ('xvlog', 'xelab', 'xsim'):
            log = destination / (name + '.log')
            log.write_text('mock successful stage\n')
            stages.append(dict(name=name, log=str(log), log_sha256=grader.digest(log),
                log_bytes=log.stat().st_size, returncode=0, timeout=False, launch_error=None))
        result = dict(schema_version=1, task=task, outdir=str(destination), status=status,
            failure_kind=None if status == 'pass' else 'semantic_mismatch', checks=10,
            mismatches=0 if status == 'pass' else 1, inputs_unchanged=True, stages=stages,
            solution_sha256=grader.digest(solution), tb_sha256=grader.digest(self.probes.parent / task / 'tb.sv'),
            runner_sha256=grader.digest(self.probes))
        grader.write_json(destination / 'result.json', result)
        return result

    def fake_judge(self, task, solution, destination, verdict_path, deadline):
        index = len(self.events)
        self.events.append(('official', solution.parent.name))
        task_id = task.name
        level = 1 if task_id == grader.TARGET and 'control' in solution.parent.name else 3
        level = self.level_overrides.get(solution.parent.name, level)
        if not solution.read_text().strip():
            level = 0
        verdict = dict(task_id=task_id, level=level, coefficient={0: 0, 1: .2, 2: .7, 3: 1}[level],
            tool_error='license missing' if index == self.tool_error_at else None,
            judge_evidence_complete=True, judge_rc=0, elapsed_s=.1)
        evidence = destination / 'judge_work_logs'
        evidence.mkdir()
        log = evidence / 'adapter_verdict.json'
        grader.write_json(log, verdict)
        grader.write_json(destination / 'judge_receipt.json', dict(judge_rc=0, errors=[],
            evidence={log.name: dict(sha256=grader.digest(log), bytes=log.stat().st_size)}))
        grader.write_json(verdict_path, verdict)
        if index == self.missing_log_at:
            log.unlink()
        if index == self.change_slot_at:
            self.slot.write_text('other_owner\n')
        return verdict

    def fake_probe(self, task, solution, destination):
        solution = Path(solution)
        self.events.append(('probe', solution.parent.name))
        status = self.probe_overrides.get(solution.parent.name, 'pass')
        return self.make_probe(task, solution, destination, status)

    def grade(self):
        real_load_module = grader.load_module

        def load(name, path):
            if name == 'r2_frozen_probes':
                return types.SimpleNamespace(probe_candidate=self.fake_probe)
            return real_load_module(name, path)

        with ExitStack() as stack:
            stack.enter_context(patch.object(grader, 'load_evaluator', return_value=types.SimpleNamespace(judge_sample=self.fake_judge)))
            stack.enter_context(patch.object(grader, 'load_module', side_effect=load))
            stack.enter_context(patch.object(grader.shutil, 'which', side_effect=lambda n: self.tools[n]))
            stack.enter_context(patch('builtins.print'))
            result = grader.grade(self.args)
        destination = sorted(self.run.glob('grading_*'))[-1]
        return result, grader.read_json(destination / 'summary.json'), destination

    def test_complete_twelve_judged_before_probes_and_positive_requires_all_gates(self):
        result, report, destination = self.grade()
        self.assertEqual(result, 0, report)
        self.assertEqual([e[0] for e in self.events], ['official'] * 12 + ['probe'] * 12)
        self.assertEqual(report['decision'], 'single_target_positive_signal_expand_not_deploy')
        self.assertEqual(report['tasks'][grader.TARGET]['diagnostic']['coefficient_mean'], 1)
        self.assertEqual(report['tasks'][grader.TARGET]['control']['coefficient_mean'], .2)
        self.assertEqual(report['valid_samples'], 12)
        self.assertEqual(grader.read_json(destination / 'before.json'), grader.read_json(destination / 'after.json'))

    def test_guard_regression_blocks_promotion(self):
        self.level_overrides[self.plan['records'][4]['directory']] = 1
        result, report, _ = self.grade()
        self.assertEqual(result, 0, report)
        self.assertFalse(report['gates']['all_diagnostic_guards_L3'])
        self.assertEqual(report['decision'], 'no_promotion_archive_this_implementation')

    def test_target_probe_failure_blocks_promotion_even_when_official_score_improves(self):
        self.probe_overrides[self.plan['records'][0]['directory']] = 'fail'
        result, report, _ = self.grade()
        self.assertEqual(result, 0, report)
        self.assertTrue(report['gates']['target_mean_improved'])
        self.assertFalse(report['gates']['both_target_probes_pass'])
        self.assertEqual(report['decision'], 'evidence_conflict_review')

    def test_control_arm_L3_probe_conflict_blocks_promotion_without_changing_original_gates(self):
        row = self.plan['records'][5]  # Correct guard, control arm.
        self.assertEqual(row['arm'], 'control')
        self.probe_overrides[row['directory']] = 'fail'
        result, report, _ = self.grade()
        self.assertEqual(result, 0, report)
        self.assertTrue(all(report['gates'].values()))
        self.assertEqual(report['decision'], 'evidence_conflict_review')
        self.assertEqual(report['evidence_conflicts'], [dict(task_id=row['task_id'],
            pair=row['pair'], arm=row['arm'], probe_failure_kind='semantic_mismatch')])

    def test_official_tie_is_not_promotion(self):
        for row in self.plan['records']:
            if row['task_id'] == grader.TARGET:
                self.level_overrides[row['directory']] = 3
        result, report, _ = self.grade()
        self.assertEqual(result, 0, report)
        self.assertFalse(report['gates']['target_mean_improved'])
        self.assertEqual(report['decision'], 'no_promotion_archive_this_implementation')

    def test_empty_answer_remains_in_official_denominator(self):
        generation = grader.read_json(self.run / 'generation.json')
        row = generation['records'][0]
        sample = self.run / row['directory']
        for name in ('reply.txt', 'solution.v'):
            (sample / name).write_bytes(b'')
        response = grader.read_json(sample / 'response.json')
        response['choices'][0]['message']['content'] = ''
        grader.write_json(sample / 'response.json', response)
        row.update(empty=True, solution_sha256=grader.digest(sample / 'solution.v'))
        grader.write_json(sample / 'generation.json', row)
        grader.write_json(self.run / 'generation.json', generation)
        result, report, _ = self.grade()
        self.assertEqual(result, 0, report)
        arm = report['tasks'][grader.TARGET]['diagnostic']
        self.assertEqual(arm['levels'], [0, 3])
        self.assertEqual(arm['coefficient_mean'], .5)
        self.assertEqual(arm['scored_samples'], 2)
        self.assertEqual(arm['empty_answers'], 1)

    def test_incomplete_generation_stops_before_judging(self):
        path = self.run / 'generation.json'
        value = grader.read_json(path)
        value['complete'] = False
        grader.write_json(path, value)
        result, report, _ = self.grade()
        self.assertEqual(result, 1)
        self.assertEqual(report['decision'], 'not_determinable')
        self.assertEqual(self.events, [])

    def test_duplicate_sample_cannot_replace_a_missing_pair(self):
        path = self.run / 'plan.json'
        value = grader.read_json(path)
        value['records'][3] = value['records'][0]
        grader.write_json(path, value)
        generation = grader.read_json(self.run / 'generation.json')
        generation['plan_sha256'] = grader.digest(path)
        grader.write_json(self.run / 'generation.json', generation)
        result, report, _ = self.grade()
        self.assertEqual(result, 1)
        self.assertEqual(self.events, [])
        self.assertIn('paired task/order', report['errors'][0])

    def test_probe_environment_error_prevents_conclusion(self):
        self.probe_overrides[self.plan['records'][0]['directory']] = 'environment_error'
        result, report, _ = self.grade()
        self.assertEqual(result, 1)
        self.assertEqual(len(self.events), 13)
        self.assertEqual(report['decision'], 'not_determinable')
        self.assertNotIn('tasks', report)

    def test_official_environment_error_does_not_shrink_denominator(self):
        self.tool_error_at = 1
        result, report, _ = self.grade()
        self.assertEqual(result, 1)
        self.assertEqual(len(self.events), 2)
        self.assertEqual(report['valid_samples'], 1)
        self.assertNotIn('tasks', report)

    def test_missing_judge_log_invalidates_whole_pilot(self):
        self.missing_log_at = 0
        result, report, _ = self.grade()
        self.assertEqual(result, 1)
        self.assertEqual(report['valid_samples'], 0)
        self.assertEqual(len(self.events), 1)

    def test_changed_slot_stops_without_touching_new_owner(self):
        self.change_slot_at = 0
        result, report, _ = self.grade()
        self.assertEqual(result, 1)
        self.assertEqual(len(self.events), 1)
        self.assertEqual(self.slot.read_text(), 'other_owner\n')

    def test_changed_probe_source_or_validation_logs_stops_before_judging(self):
        path = self.validation.parent / grader.TARGET / 'negative/xsim.log'
        path.write_text('changed after validation\n')
        result, report, _ = self.grade()
        self.assertEqual(result, 1)
        self.assertEqual(self.events, [])
        self.assertIn('probe tool evidence', report['errors'][0])

    def test_changed_prompt_content_is_rejected_but_line_endings_are_accepted(self):
        path = self.kit / 'bench/tasks_veval' / grader.TARGET / 'prompt.txt'
        path.write_text(path.read_text(encoding='utf-8') + 'additional constraint', encoding='utf-8')
        result, report, _ = self.grade()
        self.assertEqual(result, 1)
        self.assertEqual(self.events, [])
        self.assertIn('prompt text differs', report['errors'][0])


if __name__ == '__main__':
    unittest.main()
