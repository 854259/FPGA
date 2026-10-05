"""Fixed eight-task denominator; one exact model-repair chain permits only full."""
ARMS=['C','P']
TARGETS=['Prob134_2014_q3c']
COUNTEREXAMPLES=['Prob082_lfsr32','Prob144_ece241_2013_q4']
GUARDS=['Prob045_edgedetect2','Prob054_edgedetect','Prob058_alwaysblock2','Prob071_always_casez','Prob112_always_case2']
COEFFICIENTS={0:0.,1:.2,2:.7,3:1.}


def order(tasks):
    assert tasks==sorted(TARGETS+COUNTEREXAMPLES+GUARDS)
    return [(task,arm) for i,task in enumerate(tasks) for arm in (ARMS if i%2==0 else ARMS[::-1])]


def aggregate(rows,tasks,scorer):
    assert [(r['task'],r['arm']) for r in rows]==order(tasks)
    pairs={t:{r['arm']:r for r in rows if r['task']==t} for t in tasks}
    for row in rows:
        v=row['verdict'];assert v['task_id']==row['task'] and not v['tool_error']
        assert type(v['level']) is int and v['level'] in COEFFICIENTS and v['coefficient']==COEFFICIENTS[v['level']]
        assert type(row['actual_model_requests']) is int and 1<=row['actual_model_requests']<=2
        assert type(row['received_model_responses']) is int and 0<=row['received_model_responses']<=row['actual_model_requests']
        assert type(row['solve_deadline_reached']) is bool
    official={a:scorer.summarize({t:[p[a]['verdict']] for t,p in pairs.items()}) for a in ARMS}
    assert all(s['tasks']==s['scored_tasks']==8 and s['tool_errors']==0 and s['samples_per_task']==1 for s in official.values())
    means={a:sum(p[a]['verdict']['coefficient'] for p in pairs.values())/8 for a in ARMS}
    requests={a:sum(r['actual_model_requests'] for r in rows if r['arm']==a) for a in ARMS}
    seconds={a:sum(r['solve_elapsed_s'] for r in rows if r['arm']==a) for a in ARMS}
    deadlines=[dict(task=r['task'],arm=r['arm']) for r in rows if r['solve_deadline_reached']]
    unknown={a:sum(r['actual_model_requests']-r['received_model_responses'] for r in rows if r['arm']==a) for a in ARMS}
    regressions=[t for t,p in pairs.items() if p['P']['verdict']['coefficient']<p['C']['verdict']['coefficient']]
    improvements=[t for t,p in pairs.items() if p['P']['verdict']['coefficient']>p['C']['verdict']['coefficient']]
    repairs=[t for t,p in pairs.items() if p['C']['verdict']['level']<3 and p['P']['verdict']['level']==3]
    guards=all(pairs[t][a]['verdict']['level']==3 for t in GUARDS for a in ARMS)
    same_cost=all(pairs[t]['P']['actual_model_requests']==pairs[t]['C']['actual_model_requests'] for t in GUARDS)
    eligible=not regressions and guards and same_cost and not deadlines and not sum(unknown.values()) and requests['P']<=requests['C']+2 and means['P']>means['C']
    return dict(official_scores=official,coefficients=means,requests_by_arm=requests,solve_seconds_by_arm=seconds,
        repairs=repairs,improvements=improvements,regressions=regressions,solve_deadlines=deadlines,
        unconfirmed_by_arm=unknown,unconfirmed_attempts=sum(unknown.values()),guard_pass=guards,
        unchanged_task_request_cost=same_cost,screening_eligible=eligible)


def decision(aggregate,provenance,rows):
    tasks=sorted(TARGETS+COUNTEREXAMPLES+GUARDS)
    assert [(r['task'],r['arm']) for r in rows]==order(tasks)
    assert len(provenance)==16 and {(p['task'],p['arm']) for p in provenance}==set(order(tasks))
    pairs={t:{r['arm']:r for r in rows if r['task']==t} for t in tasks}
    prov={t:{p['arm']:p for p in provenance if p['task']==t} for t in tasks}
    matched=[];chains=[]
    for task in TARGETS+COUNTEREXAMPLES:
        c,p=prov[task]['C'],prov[task]['P'];cc=c['native_compile_repair'];pc=p['native_compile_repair']
        same_first=c['first_reply_sha256'] is not None and c['first_reply_sha256']==p['first_reply_sha256']
        improved=pairs[task]['P']['verdict']['coefficient']>pairs[task]['C']['verdict']['coefficient']
        exact=bool(same_first and c['original_repair_feedback_bound'] and p['original_repair_feedback_bound'] and cc and pc
            and cc['repair_request_index']==pc['repair_request_index']==1
            and cc['initial_code_sha256']==pc['initial_code_sha256']
            and cc['initial_native_fact_sha256']==pc['initial_native_fact_sha256']
            and type(cc['initial_returncode']) is int and type(pc['initial_returncode']) is int
            and cc['initial_returncode']>0 and pc['initial_returncode']>0
            and not cc['priority_invoked'] and pc['priority_invoked'] and pc['policy_effect_feedback_changed']
            and cc['normalized_feedback_sha256']!=pc['normalized_feedback_sha256']
            and cc['feedback_bound'] and pc['feedback_bound']
            and cc['complete'] and pc['complete']
            and type(pc['repaired_compile_returncode']) is int and pc['repaired_compile_returncode']==0 and pc['repaired_compile_direct']
            and pairs[task]['C']['actual_model_requests']==pairs[task]['P']['actual_model_requests']==2 and improved)
        if exact and task in TARGETS:matched.append(task)
        chains.append(dict(task=task,role='direct_target' if task in TARGETS else 'counterexample',
            first_content_identical=same_first,coefficient_improved=improved,
            candidate_l3=pairs[task]['P']['verdict']['level']==3,
            control_compile_repair=cc,candidate_compile_repair=pc,exact_native_model_repair_chain=exact))
    return dict(matched_native_repair_tasks=matched,target_repair_chains=chains,
        qualified_for_new_full_regression=bool(aggregate['screening_eligible'] and matched),
        qualification_scope='New full156 experiment only; one direct case is not cross-task/independent/five/adoption.',
        adoption=False,independent_validation_qualified=False,five_sample_qualified=False,
        direct_motivation_cases=1,current_failure_denominator=43)
