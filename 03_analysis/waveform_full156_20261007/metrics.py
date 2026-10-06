"""Frozen six-task development screen; original judge and cost gates."""
import hashlib,json
import math
import re
from pathlib import Path
ARMS = ['C', 'P']
COEFFICIENTS = {0:0., 1:.2, 2:.7, 3:1.}
ROOT=Path(__file__).resolve().parent
original=json.loads((ROOT/'upstream/RUN_SPEC.json').read_bytes())
TASKS=original['task_ids']
assert len(TASKS)==len(set(TASKS))==156 and TASKS==sorted(TASKS)
assert all(re.fullmatch(r'Prob\d{3}_[A-Za-z0-9_]+',t) for t in TASKS)
reference=json.loads((ROOT/'FULL_BASELINE_REFERENCE.json').read_bytes())
assert reference['source_audit_sha256']==hashlib.sha256((ROOT/'FULL_BASELINE_SOURCE_AUDIT.json').read_bytes()).hexdigest()=='3be06a7939895221aa194dfd5ff6814fe1ac84dcdee5ff2215b1b347bea05652'
assert set(reference['levels'])==set(TASKS) and all(type(v) is int and v in COEFFICIENTS for v in reference['levels'].values())
GUARDS=[t for t in TASKS if reference['levels'][t]==3]
TARGETS=[t for t in TASKS if t not in GUARDS]
HISTORICALLY_CORRECT=list(GUARDS)
assert len(GUARDS)==113 and abs(sum(COEFFICIENTS[v] for v in reference['levels'].values())/156-0.7743589743589744)<1e-12
ADMISSION=json.loads((ROOT/'PRODUCTION_ADMISSION.json').read_bytes())['full156_prompt_only']
assert set(ADMISSION)==set(TASKS)
assert all(type(v['advice']) is bool and v['status'] in ('supported','skip','abstain') and v['advice']==(v['status']=='supported') for v in ADMISSION.values())
ADVICE_TASKS=[t for t in TASKS if ADMISSION[t]['advice']]
ABSTENTIONS=[]

def order(tasks):
    assert tasks == TASKS and len(set(tasks)) == 156
    return [(t,a) for i,t in enumerate(tasks) for a in (ARMS if i%2 == 0 else ARMS[::-1])]

def aggregate(rows, tasks, scorer):
    assert [(r['task'],r['arm']) for r in rows] == order(tasks)
    pairs = {t:{r['arm']:r for r in rows if r['task']==t} for t in tasks}
    for r in rows:
        v=r['verdict']; n=r['actual_model_requests']; received=r['received_model_responses']
        assert v['task_id']==r['task'] and not v['tool_error'] and type(v['level']) is int and v['level'] in COEFFICIENTS
        assert v['coefficient']==COEFFICIENTS[v['level']]
        assert type(n) is type(received) is int and 1 <= n <= 2 and 0 <= received <= n
        assert type(r['solve_deadline_reached']) is bool
        assert type(r['solve_elapsed_s']) in (int,float) and math.isfinite(r['solve_elapsed_s']) and 0 <= r['solve_elapsed_s'] <= 300
        assert r['generation_route']=='model' and r['stage_generation_binding_verified'] is True
        assert r['waveform_request_binding_verified'] is True and re.fullmatch('[0-9a-f]{64}', r['request_proof_sha256'])
        assert type(r['first_request_advice_changed']) is bool
        assert r['first_request_advice_changed'] == (r['arm']=='P' and r['task'] in ADVICE_TASKS)
    official={a:scorer.summarize({t:[p[a]['verdict']] for t,p in pairs.items()}) for a in ARMS}
    assert all(s['tasks']==s['scored_tasks']==156 and s['tool_errors']==0 and s['samples_per_task']==1 for s in official.values())
    means={a:sum(p[a]['verdict']['coefficient'] for p in pairs.values())/156 for a in ARMS}
    requests={a:sum(r['actual_model_requests'] for r in rows if r['arm']==a) for a in ARMS}
    seconds={a:sum(r['solve_elapsed_s'] for r in rows if r['arm']==a) for a in ARMS}
    regressions=[t for t,p in pairs.items() if p['P']['verdict']['level'] < p['C']['verdict']['level']]
    improvements=[t for t,p in pairs.items() if p['P']['verdict']['level'] > p['C']['verdict']['level']]
    repairs=[t for t in TASKS if pairs[t]['C']['verdict']['level']<3 and pairs[t]['P']['verdict']['level']==3]
    deadlines=[dict(task=r['task'],arm=r['arm']) for r in rows if r['solve_deadline_reached']]
    unconfirmed={a:sum(r['actual_model_requests']-r['received_model_responses'] for r in rows if r['arm']==a) for a in ARMS}
    original113_regressions=[t for t in GUARDS if pairs[t]['P']['verdict']['level']!=3]
    guard_pass=not original113_regressions
    same_cost=all(p['P']['actual_model_requests'] <= p['C']['actual_model_requests'] for p in pairs.values() if p['C']['verdict']['level']==p['P']['verdict']['level'])
    correct_cost=all(pairs[t]['P']['actual_model_requests'] <= pairs[t]['C']['actual_model_requests'] for t in HISTORICALLY_CORRECT)
    eligible=bool(repairs and means['P']>means['C'] and not regressions and guard_pass and same_cost and correct_cost and not deadlines and not sum(unconfirmed.values()) and requests['P']<=requests['C'])
    fully_correct={a:official[a]['level_counts'].get('L3',0) for a in ARMS}
    return dict(original113_regressions=original113_regressions,fully_correct_by_arm=fully_correct,goal_score_thresholds_met=eligible and means['P']>=.80 and fully_correct['P']>=120,official_scores=official, coefficients=means, requests_by_arm=requests,
        solve_seconds_by_arm=seconds, improvements=improvements, improved_target_tasks=repairs, repairs=repairs,
        regressions=regressions, solve_deadlines=deadlines, unconfirmed_by_arm=unconfirmed,
        unconfirmed_attempts=sum(unconfirmed.values()), guard_pass=guard_pass,
        unchanged_task_request_cost=same_cost, historically_correct_request_cost=correct_cost,
        screening_eligible=eligible, generation_provenance_audit_pending=True, full_score_measured=False,
        independent_validation_qualified=False, five_sample_qualified=False)

def decision(result, provenance, rows):
    expected=order(TASKS)
    assert [(r['task'],r['arm']) for r in rows]==expected
    assert len(provenance)==312 and {(p['task'],p['arm']) for p in provenance}==set(expected)
    by_pair={(p['task'],p['arm']):p for p in provenance}
    flags=['generation_route_bound','input_bytes_bound','source_hashes_bound','solution_bytes_bound','native_execution_bound','original_model_replay_bound','waveform_request_factor_bound']
    bound=all(by_pair[r['task'],r['arm']].get('generation_route')=='model' and all(by_pair[r['task'],r['arm']].get(k) is True for k in flags) for r in rows)
    return dict(qualified_for_goal=bool(result['goal_score_thresholds_met'] and bound),full156_evidence_valid=bound,full_score_measured=bound,generation_provenance_audit_pending=not bound,qualified_for_new_full_regression=False,
        audited_generation_provenance_bound=bound, adoption=False, independent_validation_qualified=False,
        five_sample_qualified=False, prior_phase_full_qualification_unchanged=True,
        qualification_scope='All156 same-budget development C/P with original113 and paired preservation; no independent/five/adoption.')
