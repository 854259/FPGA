"""Two-input diagnostic with original grade/cost rules; never grants full156 admission."""
import math,re
COEFFICIENTS={0:0.,1:.2,2:.7,3:1.}

def order(tasks):
    assert len(tasks)==len(set(tasks))==2 and tasks==sorted(tasks)
    return [(t,a) for i,t in enumerate(tasks) for a in (['C','P'] if i%2==0 else ['P','C'])]

def aggregate(rows,tasks,historically_correct,scorer):
    assert [(r['task'],r['arm']) for r in rows]==order(tasks)
    assert set(historically_correct)<=set(tasks)
    pairs={t:{r['arm']:r for r in rows if r['task']==t} for t in tasks}
    for r in rows:
        v=r['verdict'];n=r['actual_model_requests'];received=r['received_model_responses']
        assert v['task_id']==r['task'] and not v['tool_error'] and type(v['level']) is int and v['level'] in COEFFICIENTS
        assert v['coefficient']==COEFFICIENTS[v['level']]
        assert type(n) is type(received) is int and 1<=n<=2 and 0<=received<=n
        assert type(r['solve_deadline_reached']) is bool and type(r['solve_elapsed_s']) in (int,float)
        assert math.isfinite(r['solve_elapsed_s']) and r['solve_elapsed_s']>=0
        assert r['generation_route']=='model' and r['stage_generation_binding_verified'] is True
        assert r['semantic_factor_binding_verified'] is True and re.fullmatch('[0-9a-f]{64}',r['request_proof_sha256'])
        assert r['first_system_changed'] is False and r['first_user_changed']==(r['arm']=='P')
        assert r['repair_wires_unchanged'] is True and r['declaration_enabled'] is False
        assert re.fullmatch('[0-9a-f]{64}',r['first_original_wire_sha256']) and re.fullmatch('[0-9a-f]{64}',r['first_forwarded_wire_sha256'])
        assert (r['first_original_wire_sha256']!=r['first_forwarded_wire_sha256'])==(r['arm']=='P')
    assert all(p['C']['first_original_wire_sha256']==p['P']['first_original_wire_sha256'] for p in pairs.values())
    official={a:scorer.summarize({t:[p[a]['verdict']] for t,p in pairs.items()}) for a in ['C','P']}
    assert all(s['tasks']==s['scored_tasks']==2 and s['tool_errors']==0 and s['samples_per_task']==1 for s in official.values())
    means={a:sum(p[a]['verdict']['coefficient'] for p in pairs.values())/2 for a in ['C','P']}
    counts={a:sum(p[a]['verdict']['level']==3 for p in pairs.values()) for a in ['C','P']}
    requests={a:sum(p[a]['actual_model_requests'] for p in pairs.values()) for a in ['C','P']}
    regressions=[t for t,p in pairs.items() if p['P']['verdict']['level']<p['C']['verdict']['level']]
    repairs=[t for t,p in pairs.items() if p['C']['verdict']['level']<3 and p['P']['verdict']['level']==3]
    same_cost=all(p['P']['actual_model_requests']<=p['C']['actual_model_requests'] for p in pairs.values() if p['P']['verdict']['level']==p['C']['verdict']['level'])
    historic_cost=all(pairs[t]['P']['actual_model_requests']<=pairs[t]['C']['actual_model_requests'] for t in historically_correct)
    historic_local=all(pairs[t]['P']['verdict']['level']==3 for t in historically_correct)
    unconfirmed=sum(r['actual_model_requests']-r['received_model_responses'] for r in rows)
    timely=all(not r['solve_deadline_reached'] and r['solve_elapsed_s']<=300 for r in rows)
    net=counts['P']-counts['C']
    promising=bool(net>=1 and repairs and means['P']>means['C'] and not regressions and same_cost and historic_cost and historic_local and requests['P']<=requests['C'] and not unconfirmed and timely)
    return dict(official_scores=official,coefficients=means,fully_correct_by_arm=counts,requests_by_arm=requests,strict_new_L3_net=net,repairs=repairs,regressions=regressions,unchanged_task_request_cost=same_cost,historically_correct_request_cost=historic_cost,all_task_request_cost=all(p['P']['actual_model_requests']<=p['C']['actual_model_requests'] for p in pairs.values()),local_historical_subset_pass=historic_local,unconfirmed_attempts=unconfirmed,all_workers_within_original300_and_no_deadline=timely,diagnostic_promising=promising,historical113_protection_complete=False,screening_eligible=False,qualified_for_new_full_regression=False,full156_evidence_valid=False,goal_achieved=False,adoption=False,limits='Two eligible inputs only. A promising audited diagnostic still requires historical protection, paired/cost gates and a separately admitted complete regression; no cross-run score addition.')
