"""Fixed known-task screen; quality changes require two actual native repair chains."""
ARMS = ['C', 'F']
FSMS = ['Prob143_fsm_onehot', 'Prob150_review2015_fsmonehot']
GUARDS = ['Prob058_alwaysblock2', 'Prob071_always_casez', 'Prob112_always_case2',
          'Prob115_shift18', 'Prob124_rule110']
UNKNOWN = 'Prob045_edgedetect2'


def order(tasks):
    assert tasks == sorted(tasks) and len(tasks) == len(set(tasks))
    assert tasks == sorted(FSMS+GUARDS+[UNKNOWN])
    return [(t, a) for i, t in enumerate(tasks) for a in (ARMS if i % 2 == 0 else ARMS[::-1])]


def aggregate(rows, tasks, scorer):
    assert len(tasks) == 8 and [(r['task'], r['arm']) for r in rows] == order(tasks)
    pairs = {t:{r['arm']:r for r in rows if r['task'] == t} for t in tasks}
    for r in rows:
        v = r['verdict']
        assert v['task_id'] == r['task'] and not v['tool_error']
        assert type(v['level']) is int and v['coefficient'] == {0:0., 1:.2, 2:.7, 3:1.}[v['level']]
        assert 1 <= r['actual_model_requests'] <= 2
        assert 0 <= r['received_model_responses'] <= r['actual_model_requests']
    official = {a:scorer.summarize({t:[p[a]['verdict']] for t, p in pairs.items()}) for a in ARMS}
    assert all(s['tasks'] == s['scored_tasks'] == 8 and s['tool_errors'] == 0 and s['samples_per_task'] == 1
               for s in official.values())
    means = {a:sum(p[a]['verdict']['coefficient'] for p in pairs.values())/8 for a in ARMS}
    requests = {a:sum(r['actual_model_requests'] for r in rows if r['arm'] == a) for a in ARMS}
    seconds = {a:sum(r['solve_elapsed_s'] for r in rows if r['arm'] == a) for a in ARMS}
    deadlines = [dict(task=r['task'], arm=r['arm']) for r in rows if r['solve_deadline_reached']]
    unconfirmed = {a:sum(r['actual_model_requests']-r['received_model_responses'] for r in rows if r['arm'] == a)
                   for a in ARMS}
    regressions = [t for t, p in pairs.items() if p['F']['verdict']['coefficient'] < p['C']['verdict']['coefficient']]
    repairs = [t for t, p in pairs.items() if p['C']['verdict']['level'] < 3 and p['F']['verdict']['level'] == 3]
    guards = all(pairs[t][a]['verdict']['level'] == 3 for t in GUARDS for a in ARMS)
    unknown = (pairs[UNKNOWN]['C']['verdict']['coefficient'] == pairs[UNKNOWN]['F']['verdict']['coefficient']
               and pairs[UNKNOWN]['C']['actual_model_requests'] == pairs[UNKNOWN]['F']['actual_model_requests'])
    unchanged_cost = all(pairs[t]['F']['actual_model_requests'] == pairs[t]['C']['actual_model_requests']
                         for t in GUARDS+[UNKNOWN])
    eligible = (not regressions and guards and unknown and unchanged_cost and not deadlines
                and not sum(unconfirmed.values()) and requests['F'] <= requests['C']+2 and means['F'] > means['C'])
    return dict(official_scores=official, coefficients=means, requests_by_arm=requests,
                solve_seconds_by_arm=seconds, repairs=repairs, regressions=regressions,
                solve_deadlines=deadlines, unconfirmed_by_arm=unconfirmed,
                unconfirmed_attempts=sum(unconfirmed.values()), guard_pass=guards,
                unknown_guard_pass=unknown, unchanged_task_request_cost=unchanged_cost,
                screening_eligible=eligible)


def decision(aggregate, provenance, rows):
    pairs = {t:{r['arm']:r for r in rows if r['task'] == t} for t in {r['task'] for r in rows}}
    prov = {t:{r['arm']:r for r in provenance if r['task'] == t} for t in pairs}
    matched = []
    for t in FSMS:
        c, e = prov[t]['C'], prov[t]['F']
        checks = e['native_checks']
        if (c['first_reply_sha256'] is not None and c['first_reply_sha256'] == e['first_reply_sha256']
                and e['contract_family'] in ('full_vector_multistate','partial_scalar_onehot') and e['original_repair_feedback_bound']
                and c['contract_status'] == 'abstain' and not c['native_checks']
                and len(checks) == 2 and checks[0]['index'] == 'map_check_0'
                and checks[0]['status'] == 'fail' and checks[0]['mismatches'] > 0
                and checks[1]['index'] == 'map_check_1' and checks[1]['status'] == 'pass'
                and checks[1]['mismatches'] == 0 and pairs[t]['F']['actual_model_requests'] == 2
                and pairs[t]['C']['verdict']['level'] < 3 and pairs[t]['F']['verdict']['level'] == 3):
            matched.append(t)
    return dict(matched_native_repair_tasks=matched,
                qualified_for_new_full_regression=aggregate['screening_eligible'] and len(matched) == 2,
                qualification_scope='New full156 experiment only; not independent/five/adoption.',
                previous_full_gate_still_failed=True, adoption=False,
                independent_validation_qualified=False, five_sample_qualified=False)
