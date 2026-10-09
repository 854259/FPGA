"""Read a completed model-only queue and apply the unmodified official summary.

AMD only. No generation, judging, retries, selection or edits to the frozen run.
The output is private evidence; publish only reviewed aggregates.
"""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys

SCORE_SHA = '2b382a41fa2d357d021c09d41b65bdfcd598149f038f4c9b571ef48d74816768'
WEIGHTS = {0: 0., 1: .2, 2: .7, 3: 1.}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def summarize(rows, tasks, official):
    tasks = sorted(tasks)
    assert tasks and len(set(tasks)) == len(tasks)
    expected = {(t, a, s) for t in tasks for a in ('A', 'P', 'B') for s in range(5)}
    indexed = {}
    for row in rows:
        key = row['task'], row['arm'], row['sample']
        assert type(row['sample']) is int and key in expected and key not in indexed
        v = row['verdict']
        assert v['task_id'] == row['task'] and not v.get('tool_error')
        assert type(v['level']) is int and v['level'] in WEIGHTS
        assert v['coefficient'] == WEIGHTS[v['level']]
        assert type(row['calls']) is int and 1 <= row['calls'] <= (1 if row['arm'] == 'B' else 2)
        for field in ('solve_s', 'judge_s', 'row_s'):
            assert type(row[field]) in (float, int) and math.isfinite(row[field]) and row[field] >= 0
        indexed[key] = row
    assert set(indexed) == expected, 'Complete five-sample A/P/B grid required; no prefix or best-sample selection'
    arms = {}
    means = {}
    for arm in ('A', 'P', 'B'):
        grouped = {t: [indexed[t, arm, s]['verdict'] for s in range(5)] for t in tasks}
        means[arm] = {t: math.fsum(v['coefficient'] for v in g) / 5 for t, g in grouped.items()}
        selected = [indexed[t, arm, s] for t in tasks for s in range(5)]
        arms[arm] = dict(official_summary=official.summarize(grouped),
                        coefficient_mean_unrounded=math.fsum(means[arm].values()) / len(tasks),
                        all_five_L3_tasks=sum(all(v['level'] == 3 for v in g) for g in grouped.values()),
                        model_requests=sum(r['calls'] for r in selected),
                        observed_solve_s=math.fsum(r['solve_s'] for r in selected),
                        observed_judge_s=math.fsum(r['judge_s'] for r in selected),
                        observed_row_s=math.fsum(r['row_s'] for r in selected))
    baseline = arms['B']['coefficient_mean_unrounded']
    for arm in ('A', 'P'):
        arms[arm]['same_run_official_baseline_gain'] = (
            arms[arm]['coefficient_mean_unrounded'] / baseline if baseline else None)
    differences = {t: means['P'][t] - means['A'][t] for t in tasks}
    delta = math.fsum(differences.values()) / len(tasks)
    radius = math.sqrt(2 * math.log(40) / len(tasks))
    return dict(complete=True, samples_per_task=5, named_tasks=len(tasks), generation_rows=len(rows),
                arms=arms, paired_task_mean_deltas=differences, P_minus_A_mean=delta,
                exploratory_task_pair_95_hoeffding=[max(-1., delta-radius), min(1., delta+radius)],
                interval_assumptions='Independent task pairs; unverified family dependence, not a generalization guarantee',
                independent_unseen_tasks=0, effective_independent_families=None,
                official_total_score=None, gain_points=None, cost_points=None, engineering_points=None,
                formal_adoption=False, full_batch_complete=False,
                limitations=['Official summarize() supplies pass@1 and diagnostic pass@5 without changing its code.',
                             'This frozen queue stops on tool/environment failures; it does not convert them to L0 or retry.',
                             'Local observed solve/judge/row sums are separate; none is the final contest measured wall clock.',
                             'Unknown official gain multiplier, reference time and engineering assessment are not filled in.',
                             'Calls, individual regressions and historical task retention are diagnostics, never selection vetoes.'])


def expected_worker_arm(root, selected_arm):
    assert selected_arm in ('A', 'P')
    spec = json.loads((Path(root) / 'RUN_SPEC.json').read_bytes())
    if spec.get('schema') == 'unsupported_clocked_semantic_review_model_comparison_v1':
        assert spec['model_generated_rtl_only'] is True
        assert spec['inherited_worker_arms'] == dict(A='P', P='P')
        assert spec['parent_complete_table_spec_sha256'] == 'b499f6c16fa91868ca7ba60a168929204f02d5b0e164f5ade776a65983aa5c5d'
        return 'P'
    return 'C' if selected_arm == 'A' else 'P'


def audit(root, expected_plan_sha, official_path):
    root = root.resolve()
    plan_path = root / 'PLAN.json'
    assert sha(plan_path) == expected_plan_sha
    plan = json.loads(plan_path.read_text())
    assert plan['samples'] == 5 and plan['model_generated_rtl_only'] is True
    assert plan['sources']['model_feedback'] is True and 'generation_arms' not in plan['sources']
    assert 'finite_judge' not in plan, 'RTLLM finite results must remain separate'
    assert sha(official_path) == SCORE_SHA
    queue_path = root / 'three_arm_queue_20261005.py'
    assert sha(queue_path) == plan['scheduler_sha256']
    sys.path.insert(0, str(root))
    queue = load('completed_comparison_queue', queue_path)
    official = load('unmodified_official_score', official_path)
    with (root/'queue/runner.lock').open('r') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        events_path = root/'queue/RUNNER_EVENTS.jsonl'
        events = [json.loads(line) for line in events_path.read_text().splitlines()]
        assert events[-1]['event'] == 'progress' and events[-1]['complete'] is True
        assert events[-1]['rows'] == len(plan['rows'])
        queue.validate(plan)
        plan_digest = queue.digest(plan)
        assert json.loads((root/'queue/PLAN.json').read_text()) == plan
        header = json.loads((root/'queue/QUEUE.json').read_text())
        assert header['plan_sha256'] == plan_digest
        assert {p.name for p in (root/'queue').glob('row_*')} == {
            'row_'+str(i).zfill(6) for i in range(len(plan['rows']))}
        rows, bound_files = [], {}
        for i, row in enumerate(plan['rows']):
            folder = root/'queue'/('row_'+str(i).zfill(6))
            receipt = queue.verify_terminal(folder, row, plan_digest)
            bound = json.loads((folder/'SOLVE_BOUND.json').read_text())
            judge = json.loads((folder/'judge/BOUND_VERDICT.json').read_text())
            verdict = json.loads((folder/'judge/verdict.json').read_text())
            assert judge['verdict'] == verdict and judge['verdict_sha256'] == sha(folder/'judge/verdict.json')
            assert judge['arm'] == row['arm']
            assert bound['arm'] == ('official_B' if row['arm'] == 'B' else row['arm'])
            assert judge['solution_sha256'] == bound['solution_sha256'] == sha(folder/'solve'/bound['solution_relative'])
            assert judge['solve_result_sha256'] == sha(folder/'solve'/bound['result_relative'])
            assert judge['task_files'] == row['evaluator_hashes'] and bound['input_sha256'] == row['input_hashes']
            assert receipt['level'] == verdict['level'] and receipt['coefficient'] == verdict['coefficient']
            assert receipt['actual_calls'] == bound['client_request_attempts'] == judge['client_request_attempts']
            assert not bound.get('generation_binding')
            if row['arm'] != 'B':
                model = bound['model_binding']
                assert model['model_generated_rtl_bound'] is True and model['outer_arm'] == row['arm']
                assert model['worker_arm'] == expected_worker_arm(root, row['arm'])
                if expected_worker_arm(root, row['arm']) == 'P' and row['arm'] == 'A':
                    assert model.get('inherited_complete_table_candidate') is True
                assert model['solution_sha256'] == bound['solution_sha256']
                assert model['actual_model_responses'] == receipt['actual_calls']
            else:
                assert bound['confirmed_model_responses'] == 1 and not bound.get('model_binding')
            rows.append(dict(task=row['task'], arm=row['arm'], sample=row['sample'], verdict=verdict,
                             calls=receipt['actual_calls'], solve_s=receipt['solve_elapsed_s'],
                             judge_s=receipt['judge_elapsed_s'], row_s=receipt['end_to_end_s']))
            bound_files[str(folder/'TERMINAL.json')] = sha(folder/'TERMINAL.json')
        result = summarize(rows, sorted({r['task'] for r in plan['rows']}), official)
        result.update(source_root=str(root), plan_sha256=expected_plan_sha,
                      official_score_sha256=SCORE_SHA, reader_sha256=sha(__file__),
                      terminal_receipts=bound_files, runner_events_sha256=sha(events_path),
                      queue_wall_s=events[-1]['at_unix']-header['started_unix'],
                      queue_wall_scope='Queue header through completion event, includes all arms and judging; excludes preparation, final guard exit and transfer.')
        return result


if __name__ == '__main__':
    assert sys.platform == 'linux' and sys.dont_write_bytecode, 'AMD-only execution'
    parser = argparse.ArgumentParser()
    for name in ('root', 'official-score', 'out'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--plan-sha256', required=True)
    args = parser.parse_args()
    assert not args.out.exists()
    result = audit(args.root, args.plan_sha256, args.official_score)
    with args.out.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False)
        stream.write('\n')
    print(json.dumps({k: v for k, v in result.items() if k in ('complete', 'named_tasks', 'generation_rows', 'P_minus_A_mean')}))

