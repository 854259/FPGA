"""Pre-frozen known-task score screen; only verified causal gain permits a new full."""
ARMS = ['C', 'P']
TARGETS = ['Prob133_2014_q3fsm', 'Prob156_review2015_fancytimer']
GUARDS = ['Prob045_edgedetect2', 'Prob054_edgedetect', 'Prob058_alwaysblock2',
          'Prob071_always_casez', 'Prob112_always_case2', 'Prob115_shift18']
COEFFICIENTS = {0: 0., 1: .2, 2: .7, 3: 1.}


def order(tasks):
    assert tasks == sorted(tasks) and len(tasks) == len(set(tasks))
    assert tasks == sorted(TARGETS + GUARDS)
    return [(task, arm) for i, task in enumerate(tasks)
            for arm in (ARMS if i % 2 == 0 else ARMS[::-1])]


def aggregate(rows, tasks, scorer):
    assert len(tasks) == 8 and [(r['task'], r['arm']) for r in rows] == order(tasks)
    pairs = {t: {r['arm']: r for r in rows if r['task'] == t} for t in tasks}
    for row in rows:
        verdict = row['verdict']
        assert verdict['task_id'] == row['task'] and not verdict['tool_error']
        assert type(verdict['level']) is int and verdict['level'] in COEFFICIENTS
        assert verdict['coefficient'] == COEFFICIENTS[verdict['level']]
        assert type(row['actual_model_requests']) is int and 1 <= row['actual_model_requests'] <= 2
        assert type(row['received_model_responses']) is int
        assert 0 <= row['received_model_responses'] <= row['actual_model_requests']
        assert type(row['solve_deadline_reached']) is bool
    official = {arm: scorer.summarize({t: [p[arm]['verdict']] for t, p in pairs.items()}) for arm in ARMS}
    assert all(s['tasks'] == s['scored_tasks'] == 8 and s['tool_errors'] == 0
               and s['samples_per_task'] == 1 for s in official.values())
    means = {arm: sum(p[arm]['verdict']['coefficient'] for p in pairs.values()) / 8 for arm in ARMS}
    requests = {arm: sum(r['actual_model_requests'] for r in rows if r['arm'] == arm) for arm in ARMS}
    seconds = {arm: sum(r['solve_elapsed_s'] for r in rows if r['arm'] == arm) for arm in ARMS}
    deadlines = [dict(task=r['task'], arm=r['arm']) for r in rows if r['solve_deadline_reached']]
    unconfirmed = {arm: sum(r['actual_model_requests'] - r['received_model_responses']
                           for r in rows if r['arm'] == arm) for arm in ARMS}
    regressions = [t for t, p in pairs.items() if p['P']['verdict']['coefficient'] < p['C']['verdict']['coefficient']]
    improvements = [t for t, p in pairs.items() if p['P']['verdict']['coefficient'] > p['C']['verdict']['coefficient']]
    repairs = [t for t, p in pairs.items() if p['C']['verdict']['level'] < 3 and p['P']['verdict']['level'] == 3]
    guards = all(pairs[t][arm]['verdict']['level'] == 3 for t in GUARDS for arm in ARMS)
    unchanged_cost = all(pairs[t]['P']['actual_model_requests'] == pairs[t]['C']['actual_model_requests'] for t in GUARDS)
    eligible = (not regressions and guards and unchanged_cost and not deadlines and not sum(unconfirmed.values())
                and requests['P'] <= requests['C'] + 2 and means['P'] > means['C'])
    return dict(official_scores=official, coefficients=means, requests_by_arm=requests,
                solve_seconds_by_arm=seconds, repairs=repairs, improvements=improvements, regressions=regressions,
                solve_deadlines=deadlines, unconfirmed_by_arm=unconfirmed,
                unconfirmed_attempts=sum(unconfirmed.values()), guard_pass=guards,
                unchanged_task_request_cost=unchanged_cost, screening_eligible=eligible)


def decision(aggregate, provenance, rows):
    tasks = sorted(TARGETS + GUARDS)
    assert [(r['task'], r['arm']) for r in rows] == order(tasks)
    assert len(provenance) == 16
    assert {(r['task'], r['arm']) for r in provenance} == set(order(tasks))
    pairs = {t: {r['arm']: r for r in rows if r['task'] == t} for t in tasks}
    prov = {t: {r['arm']: r for r in provenance if r['task'] == t} for t in tasks}
    matched, chains = [], []
    for task in TARGETS:
        control, candidate = prov[task]['C'], prov[task]['P']
        checks = candidate['elaboration_checks']
        control_checks = control['elaboration_checks']
        identical = control['first_reply_sha256'] is not None and control['first_reply_sha256'] == candidate['first_reply_sha256']
        improved = pairs[task]['P']['verdict']['coefficient'] > pairs[task]['C']['verdict']['coefficient']
        valid_chain = (identical and candidate['original_repair_feedback_bound']
                       and candidate['elaboration_repair_feedback_bound']
                       and control['original_repair_feedback_bound'] and control['elaboration_repair_feedback_bound']
                       and not control['guidance_applied'] and not control['guidance_repair_feedback_bound']
                       and candidate['guidance_applied'] and candidate['guidance_repair_feedback_bound']
                       and len(control_checks) == len(checks) == 2
                       and control_checks[0]['attempt'] == 0 and control_checks[0]['outcome'] == 'fail'
                       and type(control_checks[0]['returncode']) is int and control_checks[0]['returncode'] > 0
                       and control_checks[0]['code_sha256'] == checks[0]['code_sha256']
                       and control_checks[0]['fact_identity_sha256'] == checks[0]['fact_identity_sha256']
                       and control_checks[0]['raw_multidriver_3818'] and checks[0]['raw_multidriver_3818']
                       and not any(c['guidance_applied'] for c in control_checks)
                       and checks[0]['guidance_applied']
                       and all(c['measurement_valid'] and c['complete'] for c in control_checks)
                       and checks[0]['attempt'] == 0 and checks[0]['outcome'] == 'fail'
                       and type(checks[0]['returncode']) is int and checks[0]['returncode'] > 0
                       and checks[1]['attempt'] == 1 and checks[1]['outcome'] == 'pass'
                       and checks[1]['returncode'] == 0
                       and all(c['measurement_valid'] and c['complete'] for c in checks)
                       and pairs[task]['C']['actual_model_requests'] == pairs[task]['P']['actual_model_requests'] == 2 and improved)
        if valid_chain:
            matched.append(task)
        chains.append(dict(task=task, first_content_identical=identical,
                           control_level=pairs[task]['C']['verdict']['level'],
                           candidate_level=pairs[task]['P']['verdict']['level'],
                           coefficient_improved=improved, candidate_l3=pairs[task]['P']['verdict']['level'] == 3,
                           control_elaboration_checks=control_checks,elaboration_checks=checks, exact_elaboration_repair_chain=valid_chain))
    return dict(matched_native_repair_tasks=matched, target_repair_chains=chains,
                qualified_for_new_full_regression=aggregate['screening_eligible'] and len(matched) >= 1,
                qualification_scope='New full156 experiment only; not independent/five/adoption.',
                previous_full_gate_still_failed=True,
                previous_full_gate_reference=dict(identity='functional_full156_20261005_v1',
                    spec_sha256='43ba0bb8da29e2ec9dd5cef5b3ae81173e5796973466c18f7f1ee34fff13bbb7',
                    meaning='Historical functional full only; does not describe the newer phase full baseline gate.'),
                prior_elaboration_pilot_still_negative=True,
                prior_elaboration_spec_sha256='87cb93c00f386f3f16ece9f0ec9a7f49b18fd260faac9c75e83d4db9d31038bf',
                prior_elaboration_archive_sha256='87e3d657ae500d7657fb98c509b8a48f1dafa7953dc243fa081dfec43d82a078',
                adoption=False,
                independent_validation_qualified=False, five_sample_qualified=False)
