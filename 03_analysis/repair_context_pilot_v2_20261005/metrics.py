"""Known eight-task screening; raw control failures retain their grades/costs."""
ARMS=['C','D']
GUARDS=['Prob058_alwaysblock2','Prob071_always_casez','Prob112_always_case2',
        'Prob115_shift18','Prob124_rule110']


def order(tasks):
    assert tasks==sorted(tasks) and len(tasks)==len(set(tasks))
    return [(t,a) for i,t in enumerate(tasks) for a in (ARMS if i%2==0 else ARMS[::-1])]


def aggregate(rows,tasks,scorer):
    assert len(tasks)==8 and [(r['task'],r['arm']) for r in rows]==order(tasks)
    pairs={t:{r['arm']:r for r in rows if r['task']==t} for t in tasks}
    for r in rows:
        v=r['verdict'];assert v['task_id']==r['task'] and not v['tool_error']
        assert type(v['level']) is int and v['coefficient']=={0:0.,1:.2,2:.7,3:1.}[v['level']]
        assert 1<=r['actual_model_requests']<=2
        assert 0<=r['received_model_responses']<=r['actual_model_requests']
    official={a:scorer.summarize({t:[p[a]['verdict']] for t,p in pairs.items()}) for a in ARMS}
    assert all(s['tasks']==s['scored_tasks']==8 and s['tool_errors']==0 and s['samples_per_task']==1 for s in official.values())
    means={a:sum(p[a]['verdict']['coefficient'] for p in pairs.values())/8 for a in ARMS}
    requests={a:sum(r['actual_model_requests'] for r in rows if r['arm']==a) for a in ARMS}
    seconds={a:sum(r['solve_elapsed_s'] for r in rows if r['arm']==a) for a in ARMS}
    deadlines=[dict(task=r['task'],arm=r['arm']) for r in rows if r['solve_deadline_reached']]
    unconfirmed={a:sum(r['actual_model_requests']-r['received_model_responses'] for r in rows if r['arm']==a) for a in ARMS}
    regressions=[t for t,p in pairs.items() if p['D']['verdict']['coefficient']<p['C']['verdict']['coefficient']]
    repairs=[t for t,p in pairs.items() if p['C']['verdict']['level']<3 and p['D']['verdict']['level']==3]
    guard_pass=all(pairs[t][a]['verdict']['level']==3 for t in GUARDS for a in ARMS)
    eligible=(not regressions and guard_pass and not unconfirmed['D']
              and not any(d['arm']=='D' for d in deadlines)
              and requests['D']<=requests['C'] and means['D']>=means['C'])
    return dict(official_scores=official,coefficients=means,requests_by_arm=requests,
                solve_seconds_by_arm=seconds,repairs=repairs,regressions=regressions,
                solve_deadlines=deadlines,unconfirmed_by_arm=unconfirmed,
                unconfirmed_attempts=sum(unconfirmed.values()),guard_pass=guard_pass,
                screening_eligible=eligible)


def decision(aggregate,provenance,rows):
    pairs={t:{r['arm']:r for r in rows if r['task']==t} for t in {r['task'] for r in rows}}
    prov={t:{r['arm']:r for r in provenance if r['task']==t} for t in pairs}
    matched=[t for t,p in prov.items() if p['C']['first_reply_sha256'] is not None
             and p['C']['first_reply_sha256']==p['D']['first_reply_sha256']
             and any(r['changed'] for r in p['D']['context_receipts'])]
    matched=sorted(matched)
    gains=[t for t in matched if pairs[t]['D']['verdict']['coefficient']>pairs[t]['C']['verdict']['coefficient']]
    timing={a:sum(pairs[t][a]['solve_elapsed_s'] for t in matched) for a in ARMS}
    quality=(aggregate['coefficients']['D']>aggregate['coefficients']['C'] and bool(gains))
    lower_cost=(aggregate['coefficients']['D']==aggregate['coefficients']['C']
                and len(matched)>=2 and timing['D']<=0.9*timing['C'])
    qualified=aggregate['screening_eligible'] and len(matched)>=2 and (quality or lower_cost)
    return dict(matched_compression_tasks=matched,matched_coefficient_gain_tasks=gains,
                matched_solve_seconds=timing,qualified_for_new_full_regression=qualified,
                qualification_scope='New full156 experiment only, not independent/production adoption.',
                previous_full_gate_still_failed=True,adoption=False,
                independent_validation_qualified=False,five_sample_qualified=False)
