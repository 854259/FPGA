"""All780 fixed development samples; mean only, no best selection/qualification."""
from collections import Counter

def order(tasks):
    assert len(tasks)==156 and tasks==sorted(set(tasks))
    return [(task,'P',repeat) for repeat in range(1,6) for task in tasks]

def aggregate(rows,tasks,scorer):
    assert [(r['task'],r['arm'],r['repeat']) for r in rows]==order(tasks)
    coefficients={0:0.,1:.2,2:.7,3:1.}
    for r in rows:
        v=r['verdict'];assert v['task_id']==r['task'] and not v['tool_error']
        assert type(v['level']) is int and v['level'] in coefficients and v['coefficient']==coefficients[v['level']]
        assert type(r['actual_model_requests']) is int and 1<=r['actual_model_requests']<=2
        assert type(r['received_model_responses']) is int and 0<=r['received_model_responses']<=r['actual_model_requests']
        assert type(r['solve_deadline_reached']) is bool
    summaries=[]
    for repeat in range(1,6):
        current=[r for r in rows if r['repeat']==repeat]
        official=scorer.summarize({r['task']:[r['verdict']] for r in current})
        assert official['tasks']==official['scored_tasks']==156 and official['tool_errors']==0 and official['samples_per_task']==1
        summaries.append(dict(repeat=repeat,weighted_mean=sum(r['verdict']['coefficient'] for r in current)/156,
            levels={str(k):v for k,v in sorted(Counter(r['verdict']['level'] for r in current).items())},
            actual_model_requests=sum(r['actual_model_requests'] for r in current)))
    mean=sum(r['verdict']['coefficient'] for r in rows)/780
    deadlines=[dict(task=r['task'],repeat=r['repeat']) for r in rows if r['solve_deadline_reached']]
    unknown=sum(r['actual_model_requests']-r['received_model_responses'] for r in rows)
    return dict(coefficients={'P':mean},weighted_mean=mean,per_repeat=summaries,
        levels={str(k):v for k,v in sorted(Counter(r['verdict']['level'] for r in rows).items())},
        per_task=[dict(task=t,repeat_levels=[r['verdict']['level'] for r in rows if r['task']==t],
            weighted_mean=sum(r['verdict']['coefficient'] for r in rows if r['task']==t)/5) for t in tasks],
        actual_model_requests=sum(r['actual_model_requests'] for r in rows),
        solve_deadlines=deadlines,unconfirmed_attempts=unknown,repairs=[],regressions=[],screening_eligible=False,
        complete_five_development_repetitions=True,stability_measurement_valid=not deadlines and unknown==0)

def decision(aggregate,provenance,rows):
    assert len(provenance)==len(rows)==780
    assert {(p['task'],p['arm'],p['repeat']) for p in provenance}=={(r['task'],r['arm'],r['repeat']) for r in rows}
    return dict(adoption=False,independent_validation_qualified=False,five_sample_qualified=False,
        qualified_for_new_full_regression=False,formal_competition_five_qualified=False,
        scope='Five sequential fresh repetitions of156 known development tasks; approved phaseP stability measurement only.')
