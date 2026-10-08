"""Fixed five-pair development screen; never grants full156 or goal qualification."""
import json, math, re
from pathlib import Path

TASKS=['Prob001_zero','Prob057_kmap2','Prob143_fsm_onehot','Prob145_circuit8','Prob151_review2015_fsm']
HISTORICAL=['Prob001_zero','Prob143_fsm_onehot','Prob145_circuit8','Prob151_review2015_fsm']
COEFFICIENTS={0:0.,1:.2,2:.7,3:1.}
MECHANICAL=('mechanical_table','mechanical_onehot','mechanical_timer')


def order(tasks):
    assert tasks==TASKS and len(tasks)==len(set(tasks))==5
    return [(t,a) for i,t in enumerate(tasks) for a in (['C','P'] if i%2==0 else ['P','C'])]


def aggregate(rows,tasks,historically_correct,scorer):
    assert [(r['task'],r['arm']) for r in rows]==order(tasks)
    assert historically_correct==HISTORICAL
    plan=json.loads((Path(__file__).resolve().parent/'COMPARISON_INPUT_PLAN.json').read_bytes())
    assert plan['schema']=='table_history_wave_score5_input_plan_v1' and plan['task_count']==5
    assert set(plan['tasks'])==set(tasks)
    pairs={t:{r['arm']:r for r in rows if r['task']==t} for t in tasks}
    for r in rows:
        v=r['verdict'];n=r['actual_model_requests'];received=r['received_model_responses'];route=r['generation_route']
        expected=plan['tasks'][r['task']][r['arm']]
        assert set(expected)=={'route','selected_provider','first_request_advice_changed'}
        assert type(expected['first_request_advice_changed']) is bool
        assert route==expected['route'] and r['selected_provider']==expected['selected_provider']
        assert v['task_id']==r['task'] and not v['tool_error'] and type(v['level']) is int and v['level'] in COEFFICIENTS
        assert v['coefficient']==COEFFICIENTS[v['level']]
        assert type(n) is type(received) is int and 0<=received<=n
        assert type(r['solve_deadline_reached']) is bool and type(r['solve_elapsed_s']) in (int,float)
        assert math.isfinite(r['solve_elapsed_s']) and r['solve_elapsed_s']>=0
        assert r['stage_generation_binding_verified'] is True
        assert r['module_source_objects_bound'] is True and r['common_mechanical_strategy_bound'] is True
        assert r['parent_recipe_bound'] is True and r['parent_route']==route
        assert r['wave_scope']=='model_first_user_only' and r['repair_wires_unchanged'] is True
        assert type(r['first_request_advice_changed']) is bool
        assert r['first_request_advice_changed']==expected['first_request_advice_changed']
        assert re.fullmatch('[0-9a-f]{64}',r['route_receipt_sha256'])
        assert re.fullmatch('[0-9a-f]{64}',r['synthesis_receipt_sha256'])
        if route in MECHANICAL:
            assert r['selected_provider']==route.removeprefix('mechanical_') and n==received==0
            assert r['parent_preserved_bound'] is True and r['parent_abstention_bound'] is False
            assert re.fullmatch('[0-9a-f]{64}',r['producer_contract_sha256'])
            assert r['parent_output_sha256']==r['emitted_solution_sha256']==r['solution_sha256']
            assert r['waveform_request_binding_verified'] is False and r['request_proof_sha256'] is None
            assert r['first_request_advice_changed'] is False
            assert r['first_original_wire_sha256'] is r['first_forwarded_wire_sha256'] is None
        else:
            assert route=='model' and r['selected_provider'] is None and 1<=n<=2
            assert r['parent_preserved_bound'] is False and r['parent_abstention_bound'] is True
            assert r['parent_output_sha256'] is r['producer_contract_sha256'] is r['emitted_solution_sha256'] is None
            assert r['waveform_request_binding_verified'] is True
            assert re.fullmatch('[0-9a-f]{64}',r['request_proof_sha256'])
            assert re.fullmatch('[0-9a-f]{64}',r['first_original_wire_sha256']) and re.fullmatch('[0-9a-f]{64}',r['first_forwarded_wire_sha256'])
            assert (r['first_original_wire_sha256']!=r['first_forwarded_wire_sha256'])==r['first_request_advice_changed']
    for task,p in pairs.items():
        assert p['C']['generation_route']==p['P']['generation_route']
        if p['C']['generation_route'] in MECHANICAL:
            for key in ('selected_provider','solution_sha256','producer_contract_sha256','parent_output_sha256'):
                assert p['C'][key]==p['P'][key],('Common mechanical output changed',task,key)
        else:
            assert p['C']['first_original_wire_sha256']==p['P']['first_original_wire_sha256']
    official={a:scorer.summarize({t:[p[a]['verdict']] for t,p in pairs.items()}) for a in ['C','P']}
    assert all(s['tasks']==s['scored_tasks']==5 and s['tool_errors']==0 and s['samples_per_task']==1 for s in official.values())
    means={a:sum(p[a]['verdict']['coefficient'] for p in pairs.values())/5 for a in ['C','P']}
    counts={a:sum(p[a]['verdict']['level']==3 for p in pairs.values()) for a in ['C','P']}
    requests={a:sum(p[a]['actual_model_requests'] for p in pairs.values()) for a in ['C','P']}
    assert sum(requests.values())<=20
    regressions=[t for t,p in pairs.items() if p['P']['verdict']['level']<p['C']['verdict']['level']]
    repairs=[t for t,p in pairs.items() if p['C']['verdict']['level']<3 and p['P']['verdict']['level']==3]
    same_cost=all(p['P']['actual_model_requests']<=p['C']['actual_model_requests'] for p in pairs.values() if p['P']['verdict']['level']==p['C']['verdict']['level'])
    historic_cost=all(pairs[t]['P']['actual_model_requests']<=pairs[t]['C']['actual_model_requests'] for t in historically_correct)
    historic_local=all(pairs[t]['P']['verdict']['level']==3 for t in historically_correct)
    unconfirmed=sum(r['actual_model_requests']-r['received_model_responses'] for r in rows)
    timely=all(not r['solve_deadline_reached'] and r['solve_elapsed_s']<=300 for r in rows)
    passed=bool(counts['P']==5 and not regressions and same_cost and historic_cost and historic_local and requests['P']<=requests['C'] and not unconfirmed and timely)
    net=counts['P']-counts['C'];wave_gain='Prob145_circuit8' in repairs
    return dict(official_scores=official,coefficients=means,fully_correct_by_arm=counts,requests_by_arm=requests,
        strict_new_L3_net=net,repairs=repairs,regressions=regressions,unchanged_task_request_cost=same_cost,
        historically_correct_request_cost=historic_cost,all_task_request_cost=all(p['P']['actual_model_requests']<=p['C']['actual_model_requests'] for p in pairs.values()),
        local_historical_subset_pass=historic_local,unconfirmed_attempts=unconfirmed,all_workers_within_original300_and_no_deadline=timely,
        all_five_P_L3=counts['P']==5,diagnostic_passed=passed,paired_wave_target_improved=wave_gain,
        diagnostic_promising=bool(passed and net>=1 and wave_gain and means['P']>means['C']),
        historical113_protection_complete=False,screening_eligible=False,qualified_for_new_full_regression=False,
        qualified_for_full156=False,full156_evidence_valid=False,goal_score_thresholds_met=False,qualified_for_goal=False,goal_achieved=False,adoption=False,
        limits='Five fixed development pairs only. All five P L3 and paired/history/cost preservation are required; an audited positive screen never grants full156, hidden-set, goal or adoption qualification.')
