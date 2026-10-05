"""Fixed 14-task score screen for one sealed skill suffix; no samefirst gate."""
ARMS=['C','P']
TARGETS=['Prob089_ece241_2014_q5a','Prob111_fsm2s','Prob133_2014_q3fsm','Prob139_2013_q2bfsm','Prob146_fsm_serialdata','Prob149_ece241_2013_q4','Prob150_review2015_fsmonehot','Prob154_fsm_ps2data']
GUARDS=['Prob045_edgedetect2','Prob054_edgedetect','Prob058_alwaysblock2','Prob071_always_casez','Prob112_always_case2','Prob115_shift18']
COEFFICIENTS={0:0.,1:.2,2:.7,3:1.}
def order(tasks):
    assert tasks==sorted(TARGETS+GUARDS) and len(set(tasks))==14
    return [(task,arm) for index,task in enumerate(tasks) for arm in (ARMS if index%2==0 else ARMS[::-1])]
def aggregate(rows,tasks,scorer):
    assert [(row['task'],row['arm']) for row in rows]==order(tasks)
    pairs={task:{row['arm']:row for row in rows if row['task']==task} for task in tasks}
    for row in rows:
        v=row['verdict'];assert v['task_id']==row['task'] and not v['tool_error']
        assert type(v['level']) is int and v['level'] in COEFFICIENTS and v['coefficient']==COEFFICIENTS[v['level']]
        assert type(row['actual_model_requests']) is int and 1<=row['actual_model_requests']<=2
        assert type(row['received_model_responses']) is int and 0<=row['received_model_responses']<=row['actual_model_requests']
        assert type(row['solve_deadline_reached']) is bool
    official={arm:scorer.summarize({task:[pair[arm]['verdict']] for task,pair in pairs.items()}) for arm in ARMS}
    assert all(v['tasks']==v['scored_tasks']==14 and v['tool_errors']==0 and v['samples_per_task']==1 for v in official.values())
    means={arm:sum(pair[arm]['verdict']['coefficient'] for pair in pairs.values())/14 for arm in ARMS}
    requests={arm:sum(row['actual_model_requests'] for row in rows if row['arm']==arm) for arm in ARMS}
    seconds={arm:sum(row['solve_elapsed_s'] for row in rows if row['arm']==arm) for arm in ARMS}
    deadlines=[dict(task=row['task'],arm=row['arm']) for row in rows if row['solve_deadline_reached']]
    unconfirmed={arm:sum(row['actual_model_requests']-row['received_model_responses'] for row in rows if row['arm']==arm) for arm in ARMS}
    regressions=[task for task,pair in pairs.items() if pair['P']['verdict']['coefficient']<pair['C']['verdict']['coefficient']]
    improvements=[task for task,pair in pairs.items() if pair['P']['verdict']['coefficient']>pair['C']['verdict']['coefficient']]
    improved_targets=[task for task in TARGETS if task in improvements]
    guards=all(pairs[task][arm]['verdict']['level']==3 for task in GUARDS for arm in ARMS)
    guard_cost=all(pairs[task]['P']['actual_model_requests']<=pairs[task]['C']['actual_model_requests'] for task in GUARDS)
    eligible=(len(improved_targets)>=3 and not regressions and guards and guard_cost and not deadlines and not sum(unconfirmed.values()) and means['P']>means['C'] and requests['P']<=requests['C']+2)
    return dict(official_scores=official,coefficients=means,requests_by_arm=requests,solve_seconds_by_arm=seconds,
                repairs=[task for task in improvements if pairs[task]['C']['verdict']['level']<3 and pairs[task]['P']['verdict']['level']==3],
                improvements=improvements,improved_target_tasks=improved_targets,regressions=regressions,solve_deadlines=deadlines,
                unconfirmed_by_arm=unconfirmed,unconfirmed_attempts=sum(unconfirmed.values()),guard_pass=guards,
                unchanged_task_request_cost=guard_cost,screening_eligible=eligible)
def decision(aggregate,provenance,rows):
    expected=order(sorted(TARGETS+GUARDS))
    assert [(row['task'],row['arm']) for row in rows]==expected and len(provenance)==28
    assert {(row['task'],row['arm']) for row in provenance}==set(expected)
    bound=all(row['original_repair_feedback_bound'] is True and row['skill_messages_bound'] is True for row in provenance)
    return dict(qualified_for_new_full_regression=aggregate['screening_eligible'] and bound,
                qualification_scope='New full156 experiment only; not independent/five/adoption.',
                exact_skill_messages_bound=bound,first_reply_equality_required=False,
                adoption=False,independent_validation_qualified=False,five_sample_qualified=False,
                prior_phase_full_qualification_unchanged=True)
