"""Synthetic metadata/provenance gates only. No model or native tools execute."""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import metrics
import pilot
import synthesis

ROOT = Path(__file__).resolve().parent
s = importlib.util.spec_from_file_location('table_pinned_official_score', ROOT/'upstream/raw_evidence/test_fixtures/score.py')
score = importlib.util.module_from_spec(s)
s.loader.exec_module(score)


def material():
    rows, provenance = [], []
    for task, arm in metrics.order(metrics.TASKS):
        emitted = arm == 'P' and task in metrics.EMIT_TASKS
        route = 'mechanical_table' if emitted else 'model'
        level = 1 if task in metrics.ABSTENTIONS or (task in metrics.TARGETS and arm == 'C') else 3
        rows.append(dict(task=task, arm=arm, generation_route=route,
                         verdict=dict(task_id=task, level=level, coefficient=metrics.COEFFICIENTS[level],
                                      tool_error=None, elapsed_s=1.),
                         actual_model_requests=0 if emitted else 1,
                         received_model_responses=0 if emitted else 1,
                         solve_deadline_reached=False, solve_elapsed_s=10.,
                         solution_sha256='solution', emitted_solution_sha256='solution' if emitted else None,
                         route_receipt_sha256='route', synthesis_receipt_sha256='recipe' if arm == 'P' else None,
                         producer_contract_sha256='contract' if emitted else None,
                         stage_generation_binding_verified=True))
        provenance.append(dict(task=task, arm=arm, generation_route=route,
                               generation_route_bound=True, input_bytes_bound=True,
                               source_hashes_bound=True, solution_bytes_bound=True,
                               native_execution_bound=True, original_model_replay_bound=True,
                               synthesis_abstention_bound=True, mechanical_recipe_bound=True,
                               empty_model_artifacts_bound=True))
    return rows, provenance


def decide(rows, p):
    return metrics.decision(metrics.aggregate(rows, metrics.TASKS, score), p, rows)


def fake_mechanical(folder):
    """Fully synthetic retained artifacts; a normal rc=1 is not a tool failure."""
    source, worker = folder/'source', folder/'worker'
    source.mkdir()
    (worker/'prompt_only').mkdir(parents=True)
    prompt = ("I would like you to implement a module named TopModule with the following\n"
              "interface. All input and output ports are one bit unless otherwise\nspecified.\n\n"
              " - input p\n - input r\n - output answer\n\n"
              "The module should implement a combinational circuit. Read the simulation\n"
              "waveforms to determine what the circuit does, then implement it.\n\n"
              "time p r answer\n0ns 0 0 0\n5ns 0 1 1\n10ns 1 0 1\n15ns 1 1 0\n")
    raw = prompt.encode('utf-8')
    recipe = synthesis.synthesize(prompt)
    assert recipe['emitted']
    (source/'prompt.txt').write_bytes(raw)
    (worker/'prompt_only/prompt.txt').write_bytes(raw)
    emission = worker/'emission'
    emission.mkdir()
    rtl = recipe['rtl'].encode('utf-8')
    (worker/'solution.v').write_bytes(rtl)
    (emission/'emitted.sv').write_bytes(rtl)
    (emission/'contract.json').write_text(json.dumps(synthesis.contract.parse_prompt(prompt)['contract']))
    (worker/'synthesis_receipt.json').write_text(json.dumps(recipe))
    (worker/'trace.jsonl').write_text('{"tool":"table_generation"}\n')
    (worker/'requests.json').write_text('[]')
    (worker/'worker_result.json').write_text(json.dumps(dict(
        complete=True, generation_route='mechanical_table', arm='P', requests=0,
        actual_model_requests=0, received_model_responses=0, solution_sha256=recipe['rtl_sha256'])))
    route = dict(schema='table_synthesis_generation_route_v1', route='mechanical_table', outer_arm='P',
                 prompt_sha256=hashlib.sha256(raw).hexdigest(), interface_sha256=hashlib.sha256(b'').hexdigest(),
                 interface_present=False, baseline_worker_sha256=pilot.sha(ROOT/'baseline_worker.py'),
                 synthesis_source_sha256=pilot.sha(ROOT/'synthesis.py'),
                 generated_solution_sha256=recipe['rtl_sha256'])
    (worker/'generation_route.json').write_text(json.dumps(route))
    native = worker/'native_receipts/0'
    native.mkdir(parents=True)
    candidate = worker/'work/mechanical_compile-0/candidate.sv'
    candidate.parent.mkdir(parents=True)
    candidate.write_bytes(rtl)
    for name in ('source_before.sv', 'source_after.sv'):
        (native/name).write_bytes(rtl)
    log = native/'owned_compile.log'
    log.write_bytes(b'FAKE ordinary compiler failure for pure metadata control\n')
    spec = dict(compiler_tools=dict(xvlog=dict(path='FAKE-xvlog')))
    command = dict(timeout=False, launch_error=None, remaining_live_group=[],
                   returncode=1, argv=['FAKE-xvlog', '--sv', str(candidate)],
                   source_sha256=recipe['rtl_sha256'], source_before_sha256=recipe['rtl_sha256'],
                   source_after_sha256=recipe['rtl_sha256'], log_sha256=pilot.sha(log),
                   log_bytes=log.stat().st_size)
    (native/'command.json').write_text(json.dumps(command))
    return worker, source, spec


class MetricsControls(unittest.TestCase):
    def test_full_order_denominator_routes_and_no_adoption(self):
        rows, p = material()
        aggregate = metrics.aggregate(rows, metrics.TASKS, score)
        self.assertTrue(decide(rows, p)['qualified_for_new_full_regression'])
        self.assertEqual(aggregate['samples_by_generation_route'], dict(C=dict(model=14, mechanical_table=0), P=dict(model=5, mechanical_table=9)))
        self.assertEqual(aggregate['requests_by_arm'], dict(C=14, P=5))
        self.assertEqual(len(aggregate['improved_target_tasks']), 6)
        self.assertFalse(decide(rows, p)['adoption'])
        self.assertFalse(decide(rows, p)['independent_validation_qualified'])
        for changed in [rows[:-1], rows+[rows[0]], rows[::-1]]:
            with self.assertRaises(AssertionError):
                metrics.aggregate(changed, metrics.TASKS, score)

    def test_original_task_number_mapping_rejects_duplicate_or_absent_identity(self):
        tasks = list(metrics._original['task_ids'])
        self.assertEqual(len(metrics.resolve_task_ids(tasks)), 14)
        tasks[-1] = 'Prob050_unknown_duplicate'
        with self.assertRaises(AssertionError):
            metrics.resolve_task_ids(tasks)
        with self.assertRaises(AssertionError):
            metrics.resolve_task_ids(metrics._original['task_ids'][:-1])

    def test_zero_route_never_weakens_original_model_lower_bound(self):
        rows, p = material()
        for select, change in [
            (lambda r: r['arm'] == 'C', dict(actual_model_requests=0, received_model_responses=0)),
            (lambda r: r['generation_route'] == 'mechanical_table', dict(actual_model_requests=1, received_model_responses=1)),
            (lambda r: r['arm'] == 'C', dict(generation_route='mechanical_table', actual_model_requests=0, received_model_responses=0)),
            (lambda r: r['generation_route'] == 'mechanical_table', dict(generation_route='model', actual_model_requests=1, received_model_responses=1)),
        ]:
            changed = copy.deepcopy(rows)
            next(r for r in changed if select(r)).update(change)
            with self.assertRaises(AssertionError):
                metrics.aggregate(changed, metrics.TASKS, score)

    def test_three_distinct_target_l1_to_l3_gains_are_required(self):
        rows, p = material()
        for task in metrics.TARGETS[:4]:
            next(r for r in rows if r['task'] == task and r['arm'] == 'P')['verdict'].update(level=1, coefficient=.2)
        self.assertFalse(decide(rows, p)['qualified_for_new_full_regression'])
        rows, p = material()
        for task in metrics.TARGETS[:4]:
            next(r for r in rows if r['task'] == task and r['arm'] == 'C')['verdict'].update(level=0, coefficient=0.)
        self.assertFalse(decide(rows, p)['qualified_for_new_full_regression'])

    def test_all_seven_guards_and_per_guard_call_cost_must_hold(self):
        original, p = material()
        for task in metrics.GUARDS:
            changed = copy.deepcopy(original)
            next(r for r in changed if r['task'] == task and r['arm'] == 'P')['verdict'].update(level=1, coefficient=.2)
            self.assertFalse(decide(changed, p)['qualified_for_new_full_regression'])
        for task in metrics.FALLBACK_GUARDS:
            changed = copy.deepcopy(original)
            next(r for r in changed if r['task'] == task and r['arm'] == 'P').update(actual_model_requests=2, received_model_responses=2)
            self.assertFalse(decide(changed, p)['qualified_for_new_full_regression'])

    def test_regression_deadline_unconfirmed_and_tool_errors_do_not_disappear(self):
        original, p = material()
        for arm in metrics.ARMS:
            for change in [dict(solve_deadline_reached=True), dict(received_model_responses=0)]:
                changed = copy.deepcopy(original)
                next(r for r in changed if r['arm'] == arm and r['generation_route'] == 'model').update(change)
                self.assertFalse(decide(changed, p)['qualified_for_new_full_regression'])
        changed = copy.deepcopy(original)
        next(r for r in changed if r['task'] in metrics.ABSTENTIONS and r['arm'] == 'P')['verdict'].update(level=0, coefficient=0.)
        self.assertFalse(decide(changed, p)['qualified_for_new_full_regression'])
        changed[0]['verdict']['tool_error'] = 'environment'
        with self.assertRaises(AssertionError):
            metrics.aggregate(changed, metrics.TASKS, score)

    def test_stage_metadata_never_substitutes_for_route_specific_audit(self):
        rows, original = material()
        for route, field in [('model', 'original_model_replay_bound'), ('mechanical_table', 'mechanical_recipe_bound'),
                             ('mechanical_table', 'empty_model_artifacts_bound'), ('model', 'source_hashes_bound')]:
            changed = copy.deepcopy(original)
            next(p for p in changed if p['generation_route'] == route)[field] = False
            self.assertFalse(decide(rows, changed)['qualified_for_new_full_regression'])
        changed = copy.deepcopy(original)
        next(p for p in changed if p['arm'] == 'P' and p['generation_route'] == 'model')['synthesis_abstention_bound'] = False
        self.assertFalse(decide(rows, changed)['qualified_for_new_full_regression'])
        with self.assertRaises(AssertionError):
            metrics.decision(metrics.aggregate(rows, metrics.TASKS, score), original[:-1], rows)

    def test_recipe_recomputed_and_normal_compile_failure_is_not_discarded(self):
        with tempfile.TemporaryDirectory() as temp:
            worker, source, spec = fake_mechanical(Path(temp))
            result = pilot.generation_binding(worker, source, 'P', [], spec)
            self.assertTrue(result['stage_generation_binding_verified'])
            receipt = json.loads((worker/'synthesis_receipt.json').read_bytes())
            receipt['rtl'] += '\n'
            (worker/'synthesis_receipt.json').write_text(json.dumps(receipt))
            with self.assertRaises(AssertionError):
                pilot.generation_binding(worker, source, 'P', [], spec)
        rows, p = material()
        next(r for r in rows if r['generation_route'] == 'mechanical_table')['verdict'].update(level=0, coefficient=0.)
        self.assertFalse(decide(rows, p)['qualified_for_new_full_regression'])

    def test_machine_input_source_llm_artifacts_and_supervision_tampering_rejects(self):
        for mutation in ['prompt', 'source', 'llm', 'timeout', 'arm']:
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as temp:
                worker, source, spec = fake_mechanical(Path(temp))
                arm = 'P'
                if mutation == 'prompt':
                    (worker/'prompt_only/prompt.txt').write_bytes(b'changed')
                elif mutation == 'source':
                    (worker/'native_receipts/0/source_after.sv').write_bytes(b'changed')
                elif mutation == 'llm':
                    (worker/'trace.jsonl').write_text('{"tool":"llm_start"}\n')
                elif mutation == 'timeout':
                    command = json.loads((worker/'native_receipts/0/command.json').read_bytes())
                    command['timeout'] = True
                    (worker/'native_receipts/0/command.json').write_text(json.dumps(command))
                else:
                    arm = 'C'
                with self.assertRaises(AssertionError):
                    pilot.generation_binding(worker, source, arm, [], spec)

    def test_missing_freeze_fails_before_any_stage_can_launch(self):
        with tempfile.TemporaryDirectory() as temp, patch.object(pilot, 'ROOT', Path(temp)):
            with self.assertRaises(FileNotFoundError):
                pilot.frozen(Path(temp))


if __name__ == '__main__':
    unittest.main()
