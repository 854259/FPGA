"""Fixed15 development metadata and original-judge paired scoring; no production import."""
import hashlib,json,math,re
from pathlib import Path
ARMS=['C','P']
COEFFICIENTS={0:0.,1:.2,2:.7,3:1.}
ROOT=Path(__file__).resolve().parent
original=json.loads((ROOT/'upstream/RUN_SPEC.json').read_bytes())
ALL_TASKS=original['task_ids']
assert len(ALL_TASKS)==len(set(ALL_TASKS))==156 and ALL_TASKS==sorted(ALL_TASKS)
scope=json.loads((ROOT/'FIXED_SCOPE.json').read_bytes())
TASKS=scope['task_ids']
assert len(TASKS)==len(set(TASKS))==15 and TASKS==sorted(TASKS) and set(TASKS)<=set(ALL_TASKS)
assert [int(t[4:7]) for t in TASKS]==[45,54,78,118,127,129,139,142,143,145,151,152,153,154,155]
reference=json.loads((ROOT/'FULL_BASELINE_REFERENCE.json').read_bytes())
assert hashlib.sha256((ROOT/'FULL_BASELINE_REFERENCE.json').read_bytes()).hexdigest()=='8677fcf01f6589d7afee636cd328e7b296c5abef96da92adecd4929c007171ce'
assert reference['source_audit_sha256']==hashlib.sha256((ROOT/'FULL_BASELINE_SOURCE_AUDIT.json').read_bytes()).hexdigest()=='3be06a7939895221aa194dfd5ff6814fe1ac84dcdee5ff2215b1b347bea05652'
assert set(reference['levels'])==set(ALL_TASKS) and all(type(v) is int and v in COEFFICIENTS for v in reference['levels'].values())
assert sum(v==3 for v in reference['levels'].values())==113
GUARDS=[t for t in TASKS if reference['levels'][t]==3]
TARGETS=[t for t in TASKS if t not in GUARDS]
HISTORICALLY_CORRECT=list(GUARDS)
assert scope['guard_tasks']==GUARDS and scope['target_tasks']==TARGETS and len(GUARDS)==8 and len(TARGETS)==7
DECLARATION_FACTOR_TASKS=list(TASKS)
ABSTENTIONS=[]


def order(tasks):
    assert tasks==TASKS and len(set(tasks))==15
    return [(t,a) for i,t in enumerate(tasks) for a in (ARMS if i%2==0 else ARMS[::-1])]

def aggregate(rows,tasks,scorer):
    assert [(r['task'],r['arm']) for r in rows]==order(tasks)
    pairs={t:{r['arm']:r for r in rows if r['task']==t} for t in tasks}
    for r in rows:
        v=r['verdict'];n=r['actual_model_requests'];received=r['received_model_responses']
        assert v['task_id']==r['task'] and not v['tool_error'] and type(v['level']) is int and v['level'] in COEFFICIENTS
        assert v['coefficient']==COEFFICIENTS[v['level']]
        assert type(n) is type(received) is int and 1<=n<=2 and 0<=received<=n
        assert type(r['solve_deadline_reached']) is bool
        assert type(r['solve_elapsed_s']) in (int,float) and math.isfinite(r['solve_elapsed_s']) and 0<=r['solve_elapsed_s']<=300
        assert r['generation_route']=='model' and r['stage_generation_binding_verified'] is True
        assert r['declaration_factor_binding_verified'] is True and re.fullmatch('[0-9a-f]{64}',r['request_proof_sha256'])
        assert type(r['first_system_changed']) is bool
        assert r['first_system_changed'] is False
        assert r['declaration_enabled']==(r['arm']=='P')
    official={a:scorer.summarize({t:[p[a]['verdict']] for t,p in pairs.items()}) for a in ARMS}
    assert all(s['tasks']==s['scored_tasks']==15 and s['tool_errors']==0 and s['samples_per_task']==1 for s in official.values())
    means={a:sum(p[a]['verdict']['coefficient'] for p in pairs.values())/15 for a in ARMS}
    requests={a:sum(r['actual_model_requests'] for r in rows if r['arm']==a) for a in ARMS}
    seconds={a:sum(r['solve_elapsed_s'] for r in rows if r['arm']==a) for a in ARMS}
    regressions=[t for t,p in pairs.items() if p['P']['verdict']['level']<p['C']['verdict']['level']]
    improvements=[t for t,p in pairs.items() if p['P']['verdict']['level']>p['C']['verdict']['level']]
    repairs=[t for t,p in pairs.items() if p['C']['verdict']['level']<3 and p['P']['verdict']['level']==3]
    lost_l3=[t for t,p in pairs.items() if p['C']['verdict']['level']==3 and p['P']['verdict']['level']<3]
    deadlines=[dict(task=r['task'],arm=r['arm']) for r in rows if r['solve_deadline_reached']]
    unconfirmed={a:sum(r['actual_model_requests']-r['received_model_responses'] for r in rows if r['arm']==a) for a in ARMS}
    original113_regressions=[t for t in GUARDS if pairs[t]['P']['verdict']['level']!=3]
    guard_pass=not original113_regressions
    same_cost=all(p['P']['actual_model_requests']<=p['C']['actual_model_requests'] for p in pairs.values() if p['C']['verdict']['level']==p['P']['verdict']['level'])
    correct_cost=all(pairs[t]['P']['actual_model_requests']<=pairs[t]['C']['actual_model_requests'] for t in HISTORICALLY_CORRECT)
    all_cost=all(p['P']['actual_model_requests']<=p['C']['actual_model_requests'] for p in pairs.values())
    fully_correct={a:official[a]['level_counts'].get('L3',0) for a in ARMS}
    strict_l3_net=fully_correct['P']-fully_correct['C']
    assert strict_l3_net==len(repairs)-len(lost_l3)
    eligible=bool(repairs and strict_l3_net>=1 and means['P']>means['C'] and not regressions and guard_pass and same_cost and correct_cost and not deadlines and not sum(unconfirmed.values()) and requests['P']<=requests['C'])
    return dict(original113_regressions=original113_regressions,fully_correct_by_arm=fully_correct,strict_new_L3_net=strict_l3_net,
        historical113_restore_to_L3=[t for t in repairs if t in GUARDS],historical113_outside_new_L3=[t for t in repairs if t in TARGETS],
        goal_score_thresholds_met=False,official_scores=official,coefficients=means,requests_by_arm=requests,
        solve_seconds_by_arm=seconds,improvements=improvements,improved_target_tasks=[t for t in repairs if t in TARGETS],repairs=repairs,
        regressions=regressions,solve_deadlines=deadlines,unconfirmed_by_arm=unconfirmed,unconfirmed_attempts=sum(unconfirmed.values()),guard_pass=guard_pass,
        unchanged_task_request_cost=same_cost,historically_correct_request_cost=correct_cost,all_task_request_cost=all_cost,
        screening_eligible=eligible,generation_provenance_audit_pending=True,full_score_measured=False,
        independent_validation_qualified=False,five_sample_qualified=False)

def decision(result,provenance,rows):
    expected=order(TASKS)
    assert [(r['task'],r['arm']) for r in rows]==expected
    assert len(provenance)==30 and {(p['task'],p['arm']) for p in provenance}==set(expected)
    by_pair={(p['task'],p['arm']):p for p in provenance}
    flags=['generation_route_bound','input_bytes_bound','source_hashes_bound','solution_bytes_bound','native_execution_bound','original_model_replay_bound','declaration_factor_bound']
    bound=all(by_pair[r['task'],r['arm']].get('generation_route')=='model' and all(by_pair[r['task'],r['arm']].get(k) is True for k in flags) for r in rows)
    return dict(qualified_for_goal=False,full156_evidence_valid=False,full_score_measured=False,generation_provenance_audit_pending=not bound,
        qualified_for_new_full_regression=bool(bound and result['screening_eligible']),audited_generation_provenance_bound=bound,
        adoption=False,independent_validation_qualified=False,five_sample_qualified=False,prior_phase_full_qualification_unchanged=True,
        qualification_scope='Fixed15/30 single-factor development screen; historical113 intersection8 and all paired grades/cost protected; fresh same-factor full156 required.')
