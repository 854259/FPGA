"""Full task denominator and conservative promotion gate, pinned official scorer."""
def order(tasks):
    assert len(tasks)==len(set(tasks)) and tasks==sorted(tasks)
    return [(task,arm) for i,task in enumerate(tasks) for arm in (['A','C'] if i%2==0 else ['C','A'])]


def aggregate(rows,tasks,scorer):
    assert [(r['task'],r['arm']) for r in rows]==order(tasks)
    pairs={t:{r['arm']:r for r in rows if r['task']==t} for t in tasks}
    for row in rows:
        v=row['verdict'];assert not v['tool_error'] and v['task_id']==row['task']
        assert type(v['level']) is int and v['level'] in [0,1,2,3]
        assert v['coefficient']=={0:0.,1:.2,2:.7,3:1.}[v['level']]
        assert 1<=row['actual_model_requests']<=2
        assert row['received_model_responses']<=row['actual_model_requests']
    official={a:scorer.summarize({t:[p[a]['verdict']] for t,p in pairs.items()}) for a in ['A','C']}
    assert all(s['tasks']==s['scored_tasks']==len(tasks) and s['tool_errors']==0 and s['samples_per_task']==1 for s in official.values())
    means={a:sum(p[a]['verdict']['coefficient'] for p in pairs.values())/len(tasks) for a in ['A','C']}
    regressions=[t for t,p in pairs.items() if p['C']['verdict']['coefficient']<p['A']['verdict']['coefficient']]
    repairs=[t for t,p in pairs.items() if p['A']['verdict']['level']<3 and p['C']['verdict']['level']==3]
    unconfirmed=sum(r['actual_model_requests']-r['received_model_responses'] for r in rows)
    deadlines=[dict(task=r['task'],arm=r['arm']) for r in rows if r['solve_deadline_reached']]
    requests={a:sum(r['actual_model_requests'] for r in rows if r['arm']==a) for a in ['A','C']}
    seconds={a:sum(r['solve_elapsed_s'] for r in rows if r['arm']==a) for a in ['A','C']}
    # Quality completion and execution completion remain distinct.
    eligible=not unconfirmed and not deadlines and not regressions and (
        means['C']>means['A'] or (means['C']==means['A'] and requests['C']<requests['A']))
    return dict(official_scores=official,coefficients=means,repairs=repairs,regressions=regressions,
                unconfirmed_attempts=unconfirmed,solve_deadlines=deadlines,requests_by_arm=requests,
                solve_seconds_by_arm=seconds,candidate_qualified_for_independent_validation=eligible)
