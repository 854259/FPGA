"""Full156 same-budget development regression; zero requests require a bound mechanical route."""
import hashlib,json,math
from pathlib import Path
import re

ARMS = ['C', 'P']
COEFFICIENTS = {0: 0., 1: .2, 2: .7, 3: 1.}
TARGET_NUMBERS = (50, 57, 101, 102, 113, 125)
EMIT_GUARD_NUMBERS = (90, 103, 122)
FALLBACK_GUARD_NUMBERS = (45, 54, 71, 115)
ABSTENTION_NUMBERS = (83,)


def resolve_task_ids(upstream_tasks):
    assert len(upstream_tasks) == len(set(upstream_tasks)) == 156
    by_number = {}
    for task in upstream_tasks:
        m = re.fullmatch(r'Prob(\d{3})_[A-Za-z0-9_]+', task)
        assert m and int(m[1]) not in by_number, 'Invalid or duplicate original task number'
        by_number[int(m[1])] = task
    assert set(by_number) == set(range(1, 157))
    wanted = TARGET_NUMBERS+EMIT_GUARD_NUMBERS+FALLBACK_GUARD_NUMBERS+ABSTENTION_NUMBERS
    assert len(set(wanted)) == 14
    return {n: by_number[n] for n in wanted}


ROOT=Path(__file__).resolve().parent
_original=json.loads((ROOT/'upstream/RUN_SPEC.json').read_bytes())
TASKS=_original['task_ids']
assert len(TASKS)==len(set(TASKS))==156 and TASKS==sorted(TASKS)
REFERENCE=json.loads((ROOT/'FULL_BASELINE_REFERENCE.json').read_bytes())
assert REFERENCE['source_audit_sha256']==hashlib.sha256((ROOT/'FULL_BASELINE_SOURCE_AUDIT.json').read_bytes()).hexdigest()=='3be06a7939895221aa194dfd5ff6814fe1ac84dcdee5ff2215b1b347bea05652'
assert set(REFERENCE['levels'])==set(TASKS) and all(type(v) is int and v in COEFFICIENTS for v in REFERENCE['levels'].values())
GUARDS=[t for t in TASKS if REFERENCE['levels'][t]==3]
TARGETS=[t for t in TASKS if t not in GUARDS]
assert len(GUARDS)==113 and abs(sum(COEFFICIENTS[v] for v in REFERENCE['levels'].values())/156-0.7743589743589744)<1e-12
ADMISSION=json.loads((ROOT/'PRODUCTION_ADMISSION.json').read_bytes())
assert ADMISSION['task_count']==156 and set(ADMISSION['tasks'])==set(TASKS)
assert all(type(r['emitted']) is bool for r in ADMISSION['tasks'].values())
EMIT_TASKS=[t for t in TASKS if ADMISSION['tasks'][t]['emitted']]
ABSTENTIONS=[t for t in TASKS if t not in EMIT_TASKS]
EMIT_GUARDS=[t for t in GUARDS if t in EMIT_TASKS]
FALLBACK_GUARDS=[t for t in GUARDS if t not in EMIT_TASKS]


def order(tasks):
    assert tasks == TASKS and len(set(tasks)) == 156
    return [(task, arm) for index, task in enumerate(tasks)
            for arm in (ARMS if index % 2 == 0 else ARMS[::-1])]


def aggregate(rows, tasks, scorer):
    assert [(r['task'], r['arm']) for r in rows] == order(tasks)
    pairs = {task: {r['arm']: r for r in rows if r['task'] == task} for task in tasks}
    for row in rows:
        v = row['verdict']
        assert v['task_id'] == row['task'] and not v['tool_error']
        assert type(v['level']) is int and v['level'] in COEFFICIENTS
        assert v['coefficient'] == COEFFICIENTS[v['level']]
        count, received = row['actual_model_requests'], row['received_model_responses']
        assert type(count) is type(received) is int
        assert type(row['solve_deadline_reached']) is bool
        assert type(row['solve_elapsed_s']) in (int,float) and math.isfinite(row['solve_elapsed_s']) and 0 <= row['solve_elapsed_s'] <= 300
        assert row['stage_generation_binding_verified'] is True
        route = row['generation_route']
        if route == 'mechanical_onehot':
            assert row['arm'] == 'P' and row['task'] in EMIT_TASKS
            assert count == received == 0
            assert row['producer_contract_sha256'] and row['synthesis_receipt_sha256']
            assert row['emitted_solution_sha256'] == row['solution_sha256']
        else:
            assert route == 'model' and 1 <= count <= 2 and 0 <= received <= count
            assert row['arm'] == 'C' or row['task'] not in EMIT_TASKS
            assert row['producer_contract_sha256'] is None and row['emitted_solution_sha256'] is None
            assert row['arm'] == 'C' or row['synthesis_receipt_sha256']
        assert row['route_receipt_sha256']
    official = {arm: scorer.summarize({task: [pair[arm]['verdict']] for task, pair in pairs.items()})
                for arm in ARMS}
    assert all(s['tasks'] == s['scored_tasks'] == 156 and s['tool_errors'] == 0
               and s['samples_per_task'] == 1 for s in official.values())
    means = {arm: sum(pair[arm]['verdict']['coefficient'] for pair in pairs.values())/156 for arm in ARMS}
    requests = {arm: sum(r['actual_model_requests'] for r in rows if r['arm'] == arm) for arm in ARMS}
    seconds = {arm: sum(r['solve_elapsed_s'] for r in rows if r['arm'] == arm) for arm in ARMS}
    route_counts = {arm: {route: sum(r['arm'] == arm and r['generation_route'] == route for r in rows)
                         for route in ('model', 'mechanical_onehot')} for arm in ARMS}
    route_requests = {arm: {route: sum(r['actual_model_requests'] for r in rows
                                       if r['arm'] == arm and r['generation_route'] == route)
                           for route in ('model', 'mechanical_onehot')} for arm in ARMS}
    route_seconds = {arm: {route: sum(r['solve_elapsed_s'] for r in rows
                                      if r['arm'] == arm and r['generation_route'] == route)
                          for route in ('model', 'mechanical_onehot')} for arm in ARMS}
    regressions = [task for task, p in pairs.items() if p['P']['verdict']['coefficient'] < p['C']['verdict']['coefficient']]
    improvements = [task for task, p in pairs.items() if p['P']['verdict']['coefficient'] > p['C']['verdict']['coefficient']]
    full_gains = [task for task in TARGETS
                  if pairs[task]['C']['verdict']['level'] < 3 and pairs[task]['P']['verdict']['level'] == 3]
    deadlines = [dict(task=r['task'], arm=r['arm']) for r in rows if r['solve_deadline_reached']]
    unconfirmed = {arm: sum(r['actual_model_requests']-r['received_model_responses']
                           for r in rows if r['arm'] == arm) for arm in ARMS}
    original113_regressions=[t for t in GUARDS if pairs[t]['P']['verdict']['level']!=3]
    guard_pass = not original113_regressions
    guard_cost = all(pairs[task]['P']['actual_model_requests'] <= pairs[task]['C']['actual_model_requests'] for task in GUARDS) and all(p['P']['actual_model_requests'] <= p['C']['actual_model_requests'] for p in pairs.values() if p['P']['verdict']['coefficient']==p['C']['verdict']['coefficient'])
    eligible = (len(improvements) >= 1 and means['P'] > means['C'] and not regressions
                and guard_pass and guard_cost and not deadlines and not sum(unconfirmed.values())
                and requests['P'] <= requests['C'])
    return dict(original113_regressions=original113_regressions, fully_correct_by_arm={a:official[a]['level_counts'].get('L3',0) for a in ARMS},goal_score_thresholds_met=eligible and means['P']>=.8 and official['P']['level_counts'].get('L3',0)>=120,official_scores=official, coefficients=means, requests_by_arm=requests,
                solve_seconds_by_arm=seconds, samples_by_generation_route=route_counts,
                requests_by_generation_route=route_requests, solve_seconds_by_generation_route=route_seconds,
                improvements=improvements, improved_target_tasks=full_gains,
                repairs=full_gains, regressions=regressions, solve_deadlines=deadlines,
                unconfirmed_by_arm=unconfirmed, unconfirmed_attempts=sum(unconfirmed.values()),
                guard_pass=guard_pass, unchanged_task_request_cost=guard_cost,
                screening_eligible=eligible, generation_provenance_audit_pending=True,
                full_score_measured=False, independent_validation_qualified=False, five_sample_qualified=False)


def decision(aggregate_result, provenance, rows):
    expected = order(TASKS)
    assert [(r['task'], r['arm']) for r in rows] == expected
    assert len(provenance) == 312 and {(p['task'], p['arm']) for p in provenance} == set(expected)
    prov = {(p['task'], p['arm']): p for p in provenance}
    bound = True
    for row in rows:
        p = prov[row['task'], row['arm']]
        flags = ['generation_route_bound', 'input_bytes_bound', 'source_hashes_bound',
                 'solution_bytes_bound', 'native_execution_bound']
        if row['generation_route'] == 'model':
            flags.append('original_model_replay_bound')
            if row['arm'] == 'P':
                flags.append('synthesis_abstention_bound')
        else:
            flags += ['mechanical_recipe_bound', 'empty_model_artifacts_bound']
        bound = bound and p.get('generation_route') == row['generation_route'] and all(p.get(k) is True for k in flags)
    return dict(qualified_for_goal=aggregate_result['goal_score_thresholds_met'] and bound,full156_evidence_valid=bound,full_score_measured=bound,generation_provenance_audit_pending=not bound,qualified_for_new_full_regression=False,
                audited_generation_provenance_bound=bound,
                qualification_scope='All156 same-budget development C/P with original113 and paired preservation; no independent/five/adoption.',
                adoption=False, independent_validation_qualified=False, five_sample_qualified=False,
                prior_phase_full_qualification_unchanged=True)
