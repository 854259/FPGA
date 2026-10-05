"""All156 complete C/P denominator; original deadline/regression/cost gates retained."""
import metrics as pilot_metrics
EDGES=pilot_metrics.EDGES
GUARDS=pilot_metrics.GUARDS
UNKNOWN=pilot_metrics.UNKNOWN
ARMS=['C','P']
def order(tasks):
    assert len(tasks)==156 and tasks==sorted(set(tasks))
    return [(t,a) for i,t in enumerate(tasks) for a in (ARMS if i%2==0 else ARMS[::-1])]
def aggregate(rows,tasks,scorer):
    assert [(r['task'],r['arm']) for r in rows]==order(tasks)
    pairs={t:{r['arm']:r for r in rows if r['task']==t} for t in tasks}
    for r in rows:
        v=r['verdict'];assert not v['tool_error'] and v['task_id']==r['task']
        assert type(v['level']) is int and v['coefficient']=={0:0.,1:.2,2:.7,3:1.}[v['level']]
        assert 1<=r['actual_model_requests']<=2 and 0<=r['received_model_responses']<=r['actual_model_requests']
    official={a:scorer.summarize({t:[p[a]['verdict']] for t,p in pairs.items()}) for a in ARMS}
    assert all(s['tasks']==s['scored_tasks']==156 and s['tool_errors']==0 and s['samples_per_task']==1 for s in official.values())
    means={a:sum(p[a]['verdict']['coefficient'] for p in pairs.values())/156 for a in ARMS}
    requests={a:sum(r['actual_model_requests'] for r in rows if r['arm']==a) for a in ARMS}
    seconds={a:sum(r['solve_elapsed_s'] for r in rows if r['arm']==a) for a in ARMS}
    regressions=[t for t,p in pairs.items() if p['P']['verdict']['coefficient']<p['C']['verdict']['coefficient']]
    repairs=[t for t,p in pairs.items() if p['C']['verdict']['level']<3 and p['P']['verdict']['level']==3]
    deadlines=[dict(task=r['task'],arm=r['arm']) for r in rows if r['solve_deadline_reached']]
    unconfirmed={a:sum(r['actual_model_requests']-r['received_model_responses'] for r in rows if r['arm']==a) for a in ARMS}
    eligible=not regressions and not deadlines and not sum(unconfirmed.values()) and requests['P']<=requests['C']+2 and (means['P']>means['C'] or means['P']==means['C'] and requests['P']<requests['C'])
    return dict(official_scores=official,coefficients=means,repairs=repairs,regressions=regressions,requests_by_arm=requests,solve_seconds_by_arm=seconds,solve_deadlines=deadlines,unconfirmed_by_arm=unconfirmed,unconfirmed_attempts=sum(unconfirmed.values()),screening_eligible=eligible,candidate_qualified_for_independent_validation=False)
def decision(aggregate,provenance,rows):
    assert len(rows)==len(provenance)==312
    pairs={t:{r['arm']:r for r in rows if r['task']==t} for t in {r['task'] for r in rows}}
    prov={t:{r['arm']:r for r in provenance if r['task']==t} for t in pairs}
    matched=[]
    for t in EDGES:
        c,p=prov[t]['C'],prov[t]['P'];checks=p['native_checks']
        if (c['first_reply_sha256'] is not None and c['first_reply_sha256']==p['first_reply_sha256'] and p['contract_family']=='edge' and p['original_repair_feedback_bound'] and c['contract_status']=='abstain' and not c['native_checks'] and len(checks)==2 and checks[0]['index']=='map_check_0' and checks[0]['status']=='fail' and checks[0]['mismatches']>0 and checks[1]['index']=='map_check_1' and checks[1]['status']=='pass' and checks[1]['mismatches']==0 and pairs[t]['P']['actual_model_requests']==2 and pairs[t]['C']['verdict']['level']<3 and pairs[t]['P']['verdict']['level']==3):matched.append(t)
    unchanged_first_regressions=[t for t,p in pairs.items() if prov[t]['C']['first_reply_sha256']==prov[t]['P']['first_reply_sha256'] and p['P']['verdict']['coefficient']<p['C']['verdict']['coefficient']]
    qualified=aggregate['screening_eligible'] and len(matched)==2 and not unchanged_first_regressions
    return dict(matched_native_repair_tasks=matched,unchanged_first_reply_regressions=unchanged_first_regressions,candidate_qualified_for_independent_validation=qualified,independent_validation_qualified=qualified,qualification_scope='Permits faithful independent model validation only; no five-sample/offline/target hardware/official baseline certificate or automatic deployment.',previous_full_gate_still_failed=True,adoption=False,five_sample_qualified=False)
