"""Seven fixed development pairs; serial framing extends the complete common parent."""
import json, math, re
from pathlib import Path

TASKS=['Prob045_edgedetect2','Prob057_kmap2','Prob127_lemmings1','Prob137_fsm_serial','Prob143_fsm_onehot','Prob146_fsm_serialdata','Prob151_review2015_fsm']
HISTORICAL=['Prob045_edgedetect2','Prob127_lemmings1','Prob143_fsm_onehot','Prob151_review2015_fsm']
TARGETS=['Prob137_fsm_serial','Prob146_fsm_serialdata']
COEFFICIENTS={0:0.,1:.2,2:.7,3:1.}
PARENT_ROUTES=('mechanical_table','mechanical_onehot','mechanical_timer')
MECHANICAL=PARENT_ROUTES+('mechanical_serial_framing',)


def order(tasks):
    assert tasks==TASKS and len(tasks)==len(set(tasks))==7
    return [(t,a) for i,t in enumerate(tasks) for a in (['C','P'] if i%2==0 else ['P','C'])]


def aggregate(rows,tasks,historically_correct,scorer):
    assert [(r['task'],r['arm']) for r in rows]==order(tasks)
    assert historically_correct==HISTORICAL
    plan=json.loads((Path(__file__).resolve().parent/'COMPARISON_INPUT_PLAN.json').read_bytes())
    assert plan['schema']=='table_history_cp8_score7_input_plan_v1' and plan['task_count']==7
    assert set(plan['tasks'])==set(tasks)
    pairs={t:{r['arm']:r for r in rows if r['task']==t} for t in tasks}
    for r in rows:
        v=r['verdict'];n=r['actual_model_requests'];received=r['received_model_responses'];route=r['generation_route']
        expected=plan['tasks'][r['task']][r['arm']]
        assert set(expected)=={'route','selected_provider'}
        assert route==expected['route'] and r['selected_provider']==expected['selected_provider']
        assert v['task_id']==r['task'] and not v['tool_error'] and type(v['level']) is int and v['level'] in COEFFICIENTS
        assert v['coefficient']==COEFFICIENTS[v['level']]
        assert type(n) is type(received) is int and 0<=received<=n
        assert type(r['solve_deadline_reached']) is bool and type(r['solve_elapsed_s']) in (int,float)
        assert math.isfinite(r['solve_elapsed_s']) and r['solve_elapsed_s']>=0
        assert r['stage_generation_binding_verified'] is True
        assert r['module_source_objects_bound'] is True and r['common_mechanical_strategy_bound'] is True
        assert r['parent_recipe_bound'] is True
        assert r['parent_route']==plan['tasks'][r['task']]['C']['route']
        assert r['parent_preserved_bound'] is (r['parent_route'] in PARENT_ROUTES)
        assert r['parent_abstention_bound'] is (r['parent_route']=='model')
        for field in ('route_receipt_sha256','synthesis_receipt_sha256','solution_sha256'):
            assert re.fullmatch('[0-9a-f]{64}',r[field])
        if route in MECHANICAL:
            assert r['selected_provider']==route.removeprefix('mechanical_') and n==received==0
            assert re.fullmatch('[0-9a-f]{64}',r['producer_contract_sha256'])
            assert r['emitted_solution_sha256']==r['solution_sha256']
            if route in PARENT_ROUTES:
                assert route==r['parent_route'] and r['parent_output_sha256']==r['solution_sha256']
            else:
                assert r['arm']=='P' and r['parent_route']=='model' and r['parent_output_sha256'] is None
        else:
            assert route=='model' and r['selected_provider'] is None and 1<=n<=2
            assert r['parent_route']=='model'
            assert r['parent_output_sha256'] is r['producer_contract_sha256'] is r['emitted_solution_sha256'] is None
    for task,p in pairs.items():
        assert p['C']['generation_route'] in PARENT_ROUTES+('model',)
        if p['C']['generation_route'] in PARENT_ROUTES:
            for key in ('generation_route','selected_provider','solution_sha256','producer_contract_sha256','parent_output_sha256'):
                assert p['C'][key]==p['P'][key],('Common parent output changed',task,key)
        elif task in TARGETS:
            assert p['P']['generation_route']=='mechanical_serial_framing'
        else:
            assert p['P']['generation_route']=='model'
    official={a:scorer.summarize({t:[p[a]['verdict']] for t,p in pairs.items()}) for a in ['C','P']}
    assert all(s['tasks']==s['scored_tasks']==7 and s['tool_errors']==0 and s['samples_per_task']==1 for s in official.values())
    means={a:sum(p[a]['verdict']['coefficient'] for p in pairs.values())/7 for a in ['C','P']}
    counts={a:sum(p[a]['verdict']['level']==3 for p in pairs.values()) for a in ['C','P']}
    requests={a:sum(p[a]['actual_model_requests'] for p in pairs.values()) for a in ['C','P']}
    assert sum(requests.values())<=28
    regressions=[t for t,p in pairs.items() if p['P']['verdict']['level']<p['C']['verdict']['level']]
    repairs=[t for t,p in pairs.items() if p['C']['verdict']['level']<3 and p['P']['verdict']['level']==3]
    same_cost=all(p['P']['actual_model_requests']<=p['C']['actual_model_requests'] for p in pairs.values() if p['P']['verdict']['level']==p['C']['verdict']['level'])
    historic_cost=all(pairs[t]['P']['actual_model_requests']<=pairs[t]['C']['actual_model_requests'] for t in historically_correct)
    every_cost=all(p['P']['actual_model_requests']<=p['C']['actual_model_requests'] for p in pairs.values())
    historic_local=all(pairs[t]['P']['verdict']['level']==3 for t in historically_correct)
    unconfirmed=sum(r['actual_model_requests']-r['received_model_responses'] for r in rows)
    timely=all(not r['solve_deadline_reached'] and r['solve_elapsed_s']<=300 for r in rows)
    passed=bool(counts['P']==7 and not regressions and same_cost and historic_cost and every_cost and historic_local and requests['P']<=requests['C'] and not unconfirmed and timely)
    net=counts['P']-counts['C'];target_gains=[t for t in TARGETS if t in repairs]
    return dict(official_scores=official,coefficients=means,fully_correct_by_arm=counts,requests_by_arm=requests,
        strict_new_L3_net=net,repairs=repairs,regressions=regressions,unchanged_task_request_cost=same_cost,
        historically_correct_request_cost=historic_cost,all_task_request_cost=every_cost,
        local_historical_subset_pass=historic_local,unconfirmed_attempts=unconfirmed,all_workers_within_original300_and_no_deadline=timely,
        all_seven_P_L3=counts['P']==7,diagnostic_passed=passed,improved_target_tasks=target_gains,
        diagnostic_promising=bool(passed and net>0 and target_gains and means['P']>means['C']),
        historical113_protection_complete=False,known_uncovered_history=['Prob145_circuit8'],
        screening_eligible=False,qualified_for_new_full_regression=False,
        qualified_for_full156=False,full156_evidence_valid=False,goal_score_thresholds_met=False,qualified_for_goal=False,goal_achieved=False,adoption=False,
        limits='Seven fixed development pairs only; all seven P L3, positive net gain and paired/history/every-task/total cost preservation. History145 is uncovered. No full156, unseen, goal or adoption qualification.')
