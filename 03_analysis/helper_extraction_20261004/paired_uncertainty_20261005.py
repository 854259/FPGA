"""AMD-only postflight supplement. Does not select, stop, retry or promote a run."""
import argparse
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import statistics
import sys
import zipfile

SPEC_SHA = '43ba0bb8da29e2ec9dd5cef5b3ae81173e5796973466c18f7f1ee34fff13bbb7'
STABILITY_SPEC_SHA = '589ee0f566d708924370ad5b051ff23fce41df4891853e3ce8abf153104a4f15'
STABILITY_AUDITOR_SHA = '4004a32ef28d5b32513ebc5cd762fa959ead197a7005176c36602da0dd92f612'
WEIGHTS = {0:0., 1:.2, 2:.7, 3:1.}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    return json.loads(path.read_text())


def cdf(k, n, p):
    return math.fsum(math.comb(n,j) * p**j * (1-p)**(n-j) for j in range(k+1))


def invert_cdf(k, n, target):
    lo, hi = 0., 1.
    for _ in range(80):
        mid = (lo+hi)/2
        if cdf(k,n,mid) > target: lo = mid
        else: hi = mid
    return (lo+hi)/2


def binomial_interval(k, n, tail):
    if not isinstance(k,int) or not isinstance(n,int) or not 0<=k<=n or n<1:
        raise ValueError('Invalid binomial counts')
    if not 0<tail<.5: raise ValueError('Invalid tail probability')
    return [0. if k==0 else invert_cdf(k-1,n,1-tail),
            1. if k==n else invert_cdf(k,n,tail)]


def binary_pairs(a, c):
    if not a or len(a)!=len(c) or any(type(v) is not bool for v in a+c):
        raise ValueError('Expected equal nonempty boolean paired samples')
    n=len(a); repairs=sum(not x and y for x,y in zip(a,c))
    harms=sum(x and not y for x,y in zip(a,c)); discordant=repairs+harms
    # Each rate has a 97.5% two-sided Clopper-Pearson interval. The union bound
    # yields >=95% simultaneous coverage, hence a conservative difference interval.
    fix_ci=binomial_interval(repairs,n,.0125); harm_ci=binomial_interval(harms,n,.0125)
    p=min(1.,2*sum(math.comb(discordant,j) for j in range(min(repairs,harms)+1))/2**discordant)
    return dict(paired_tasks=n,A_pass=sum(a),C_pass=sum(c),repairs=repairs,harms=harms,
        unchanged=n-discordant,net_delta=(repairs-harms)/n,
        exploratory_net_95_interval=[fix_ci[0]-harm_ci[1],fix_ci[1]-harm_ci[0]],
        repair_rate_97_5_interval=fix_ci,harm_rate_97_5_interval=harm_ci,
        exact_mcnemar_p=p,discordant_tasks=discordant,
        inferential_assumptions='Independent identically distributed task pairs; unverified for these development tasks',
        zero_discordance_is_not_equivalence=True)


def validate_rows(rows,tasks):
    if len(tasks)!=156 or len(set(tasks))!=156 or tasks!=sorted(tasks):
        raise ValueError('Expected frozen full156 denominator')
    expected=[(t,a) for i,t in enumerate(tasks) for a in (['A','C'] if i%2==0 else ['C','A'])]
    if [(r['task'],r['arm']) for r in rows]!=expected:
        raise ValueError('Missing, duplicate or reordered task/arm rows')
    for r in rows:
        v=r['verdict'];level=v['level']
        if type(level) is not int or level not in WEIGHTS or v['coefficient']!=WEIGHTS[level]:
            raise ValueError('Invalid official grade')
        if v['task_id']!=r['task'] or v['tool_error']:
            raise ValueError('Unresolved scoring validity problem')
        if type(v['stages']['simulate']) is not bool:
            raise ValueError('Unknown simulation result')
        for seconds in [r['solve_elapsed_s'],v['elapsed_s']]:
            if type(seconds) not in (int,float) or not math.isfinite(seconds) or seconds<0:
                raise ValueError('Invalid recorded duration')
    return {t:{r['arm']:r for r in rows if r['task']==t} for t in tasks}


def summarize(pairs,tasks):
    levels={a:[pairs[t][a]['verdict']['level'] for t in tasks] for a in ['A','C']}
    sims={a:[pairs[t][a]['verdict']['stages']['simulate'] for t in tasks] for a in ['A','C']}
    differences=[WEIGHTS[c]-WEIGHTS[a] for a,c in zip(levels['A'],levels['C'])]
    quality_delta=sum(differences)/len(tasks)
    # Each paired coefficient difference lies in [-1,1]; a distribution-free,
    # conservative bound under independent task-pair sampling, not a family certificate.
    radius=math.sqrt(2*math.log(40)/len(tasks))
    solve={a:sum(pairs[t][a]['solve_elapsed_s'] for t in tasks) for a in ['A','C']}
    judge={a:sum(pairs[t][a]['verdict']['elapsed_s'] for t in tasks) for a in ['A','C']}
    cost_differences=[pairs[t]['C']['solve_elapsed_s']-pairs[t]['A']['solve_elapsed_s'] for t in tasks]
    return dict(tasks=len(tasks),L3=binary_pairs([v==3 for v in levels['A']],[v==3 for v in levels['C']]),
        simulation_pass=binary_pairs(sims['A'],sims['C']),
        official_quality_mean={a:sum(WEIGHTS[v] for v in levels[a])/len(tasks) for a in ['A','C']},
        official_quality_delta=quality_delta,
        exploratory_weighted_95_hoeffding=[max(-1.,quality_delta-radius),min(1.,quality_delta+radius)],
        weighted_interval_assumptions='Independent task pairs in [-1,1]; unverified, conservative, not a generalization certificate',
        weighted_improvements=sum(v>0 for v in differences),weighted_regressions=sum(v<0 for v in differences),
        solve_seconds=solve,judge_seconds=judge,
        solve_seconds_delta=solve['C']-solve['A'],
        paired_solve_delta_median_s=statistics.median(cost_differences),
        confirmed_responses={a:sum(pairs[t][a]['received_model_responses'] for t in tasks) for a in ['A','C']},
        attempted_requests={a:sum(pairs[t][a]['actual_model_requests'] for t in tasks) for a in ['A','C']},
        paired_task_differences=[dict(task=t,quality_delta=differences[i],solve_delta_s=cost_differences[i])
                                 for i,t in enumerate(tasks)])


def stability_summary(rows, tasks):
    """Complete P-only development repetitions, clustered by named task.

    These are descriptive results and a conditional task-IID interval. Five
    generations never become five independent tasks or a paired treatment gain.
    """
    if len(tasks) != 156 or tasks != sorted(set(tasks)):
        raise ValueError('Expected frozen 156 named tasks')
    expected = [(t, 'P', repeat) for repeat in range(1, 6) for t in tasks]
    if [(r['task'], r['arm'], r['repeat']) for r in rows] != expected:
        raise ValueError('Full 780-row ordered result required; no interim selection')
    for r in rows:
        v = r['verdict']; level = v['level']
        if type(r['repeat']) is not int or type(level) is not int or level not in WEIGHTS:
            raise ValueError('Invalid repeat or grade')
        if v['task_id'] != r['task'] or v['tool_error'] or v['coefficient'] != WEIGHTS[level]:
            raise ValueError('Unresolved grade identity or environment failure')
        if type(v['stages']['simulate']) is not bool or type(r['solve_deadline_reached']) is not bool:
            raise ValueError('Unknown simulation or deadline status')
        calls, responses = r['actual_model_requests'], r['received_model_responses']
        if type(calls) is not int or type(responses) is not int or not 0 <= responses <= calls <= 2 or calls < 1:
            raise ValueError('Invalid request counts')
        for seconds in [r['solve_elapsed_s'], v['elapsed_s']]:
            if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
                raise ValueError('Invalid recorded duration')
    grouped = {t: [r for r in rows if r['task'] == t] for t in tasks}
    per_task = [dict(task=t, levels=[r['verdict']['level'] for r in group],
                     quality_mean=math.fsum(r['verdict']['coefficient'] for r in group)/5,
                     L3_count=sum(r['verdict']['level'] == 3 for r in group),
                     simulation_pass_count=sum(r['verdict']['stages']['simulate'] for r in group))
                for t, group in grouped.items()]
    per_repeat = []
    for repeat in range(1, 6):
        group = [r for r in rows if r['repeat'] == repeat]
        per_repeat.append(dict(repeat=repeat, tasks=156,
            quality_mean=math.fsum(r['verdict']['coefficient'] for r in group)/156,
            L3_count=sum(r['verdict']['level'] == 3 for r in group),
            solve_s=math.fsum(r['solve_elapsed_s'] for r in group),
            recorded_judge_s=math.fsum(r['verdict']['elapsed_s'] for r in group),
            calls=sum(r['actual_model_requests'] for r in group)))
    mean = math.fsum(r['quality_mean'] for r in per_task)/156
    # Hoeffding applies to 156 bounded task means, not 780 correlated draws.
    # Cross-task family independence is unverified; this is not a formal CI
    # for unseen competition tasks or a confidence interval for a P-A gain.
    radius = math.sqrt(math.log(40)/(2*156))
    deadlines = sum(r['solve_deadline_reached'] for r in rows)
    unconfirmed = sum(r['actual_model_requests']-r['received_model_responses'] for r in rows)
    return dict(named_development_tasks=156, generation_rows=780, repetitions=5,
        independent_unseen_tasks=0, effective_independent_families=None,
        weighted_quality_mean=mean, per_repeat=per_repeat, per_task=per_task,
        exploratory_task_mean_95_hoeffding=[max(0., mean-radius), min(1., mean+radius)],
        interval_assumptions='156 independent task means in [0,1]; task/family independence unverified; no generalization guarantee',
        tasks_with_level_variation=sum(len(set(r['levels'])) > 1 for r in per_task),
        tasks_with_L3_variation=sum(0 < r['L3_count'] < 5 for r in per_task),
        all_five_L3_tasks=sum(r['L3_count'] == 5 for r in per_task),
        solve_seconds=math.fsum(r['solve_elapsed_s'] for r in rows),
        recorded_judge_seconds=math.fsum(r['verdict']['elapsed_s'] for r in rows),
        attempted_requests=sum(r['actual_model_requests'] for r in rows),
        confirmed_responses=sum(r['received_model_responses'] for r in rows),
        solve_deadlines=deadlines, unconfirmed_attempts=unconfirmed,
        complete_stability_evidence_valid=deadlines == 0 and unconfirmed == 0,
        paired_gain=None, repairs=None, harms=None, official_baseline_gain=None,
        full_batch_complete=False, promotion_permitted=False)


def stability_selfcheck():
    import copy
    tasks = [f'Task{i:03}' for i in range(156)]
    rows = [dict(task=t, arm='P', repeat=repeat, solve_deadline_reached=False,
                 actual_model_requests=1, received_model_responses=1, solve_elapsed_s=2.,
                 verdict=dict(task_id=t, level=3, coefficient=1., tool_error=False,
                              elapsed_s=3., stages={'simulate': True}))
            for repeat in range(1, 6) for t in tasks]
    all_good = stability_summary(rows, tasks)
    assert all_good['weighted_quality_mean'] == 1 and all_good['all_five_L3_tasks'] == 156
    assert all_good['generation_rows'] == 780 and all_good['effective_independent_families'] is None
    assert all_good['solve_seconds'] == 1560 and all_good['recorded_judge_seconds'] == 2340
    assert abs(all_good['exploratory_task_mean_95_hoeffding'][0]-(1-math.sqrt(math.log(40)/312))) < 1e-12
    changed = copy.deepcopy(rows); changed[0]['verdict'].update(level=0, coefficient=0., stages={'simulate': False})
    one = stability_summary(changed, tasks)
    assert abs(one['weighted_quality_mean']-(1-1/780)) < 1e-12
    assert one['tasks_with_level_variation'] == one['tasks_with_L3_variation'] == 1
    assert one['all_five_L3_tasks'] == 155 and one['per_task'][0]['quality_mean'] == .8
    uncertain = copy.deepcopy(rows); uncertain[0].update(solve_deadline_reached=True, received_model_responses=0)
    invalid = stability_summary(uncertain, tasks)
    assert not invalid['complete_stability_evidence_valid'] and invalid['unconfirmed_attempts'] == 1
    assert invalid['repairs'] is None and invalid['harms'] is None and invalid['paired_gain'] is None
    bad = [('missing', rows[:-1]), ('duplicate', rows[:-1]+[rows[0]]), ('reordered', list(reversed(rows)))]
    for label, path, value in [('arm', ['arm'], 'A'), ('repeat_type', ['repeat'], True),
            ('nan_time', ['solve_elapsed_s'], float('nan')), ('negative_time', ['verdict','elapsed_s'], -1),
            ('tool_error', ['verdict','tool_error'], True), ('grade', ['verdict','coefficient'], .7),
            ('extra_call', ['actual_model_requests'], 3), ('response_count', ['received_model_responses'], 2)]:
        altered = copy.deepcopy(rows); target = altered[0]
        for key in path[:-1]: target = target[key]
        target[path[-1]] = value; bad.append((label, altered))
    for label, altered in bad:
        try: stability_summary(altered, tasks)
        except ValueError: pass
        else: raise AssertionError('Invalid evidence accepted: '+label)
    return dict(complete=True, passed=True, synthetic_only=True, model_calls=0, eda_calls=0,
                checks=['complete_grid', 'task_cluster_denominator', 'known_costs', 'single_sample_change',
                        'deadline_and_unconfirmed_retained']+[label for label, unused in bad])


def run_stability(a):
    if sha(a.spec) != STABILITY_SPEC_SHA:
        raise ValueError('Unfrozen stability protocol')
    spec, summary, audit, guard = map(read, [a.spec, a.summary, a.audit, a.guard])
    if not summary['complete'] or not summary['passed'] or summary['spec_sha256'] != STABILITY_SPEC_SHA:
        raise ValueError('Stability result incomplete; never summarize a selected prefix')
    if not audit['evidence_valid'] or not audit['stability780_evidence_valid'] or audit['historical_fixture_only']:
        raise ValueError('Original terminal provenance audit required')
    if audit['auditor_sha256'] != STABILITY_AUDITOR_SHA or audit['spec_sha256'] != STABILITY_SPEC_SHA:
        raise ValueError('Original auditor identity mismatch')
    repair = audit.get('report_schema_repair')
    if repair is not None and repair != dict(
            kind='remove_duplicate_actual_model_requests_keyword_only',
            original_source_sha256=STABILITY_AUDITOR_SHA,
            executed_source_sha256='3eb3ae5454d1080635b02bad9eec050c774efeb63cb3d28b38e2b6331eb6ef89',
            regression_original_reproduced=True, regression_corrected_passed=True, source_drift_rejected=True):
        raise ValueError('Unknown audit report correction')
    archive_sha = sha(a.archive)
    if audit['archive_sha256'] != archive_sha:
        raise ValueError('Audit archive identity mismatch')
    with zipfile.ZipFile(a.archive) as z:
        if len(z.namelist()) != len(set(z.namelist())):
            raise ValueError('Duplicate archive members')
        for path, member in [(a.spec, 'run/RUN_SPEC.json'), (a.summary, 'run/results/summary.json'),
                             (a.guard, 'guard/status.json')]:
            if path.read_bytes() != z.read(member):
                raise ValueError('Input not bound to terminal archive: '+member)
    if not all(guard[k] for k in ['complete','passed','model_unchanged','protected_files_unchanged','own_slot_released']):
        raise ValueError('Terminal guard incomplete')
    if not guard['owned_cleanup']['verified'] or guard['owned_cleanup']['remaining']:
        raise ValueError('Owned cleanup incomplete')
    primary = stability_summary(summary['rows'], spec['task_ids'])
    if not math.isclose(primary['weighted_quality_mean'], audit['coefficients']['P'], abs_tol=1e-12):
        raise ValueError('Audited mean mismatch')
    if primary['attempted_requests'] != audit['actual_model_requests'] or primary['unconfirmed_attempts'] != audit['unconfirmed_attempts']:
        raise ValueError('Audited call count mismatch')
    first_pairs = audit['first_pairs']
    if [r['task'] for r in first_pairs] != spec['task_ids']:
        raise ValueError('Audited repetition identity mismatch')
    primary['tasks_with_five_identical_first_replies'] = sum(
        r['all_five_first_content_identical'] for r in first_pairs)
    for seconds in [summary['elapsed_s'], guard['elapsed_s']]:
        if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds < 0:
            raise ValueError('Invalid terminal wall time')
    return dict(complete=True, analysis_only=True, analysis_source_sha256=sha(Path(__file__)),
        audit_report_schema_repair=repair,
        inputs={k:sha(getattr(a,k)) for k in ['spec','summary','audit','guard']},
        archived_evidence_sha256=archive_sha, primary=primary,
        reported_stage_wall_seconds=summary['elapsed_s'], guard_wall_seconds=guard['elapsed_s'],
        full_delivery_end_to_end_seconds=None, five_development_repetitions=True,
        formal_five_sample_qualified=False, full_competition_score_computed=False,
        full_batch_complete=False, promotion_decision_changed=False, new_model_calls=0, new_eda_calls=0,
        limits=['Single P arm: repairs, harms and paired gain are unknown, not zero.',
                'Known development tasks; family independence and unseen generalization remain unverified.',
                'Solver plus recorded judge time excludes preparation, queueing, archive and transfer overhead.',
                'No resampling, stopping-rule change or automatic promotion.'])


def selfcheck():
    # Analytic boundaries, exact small discordance probabilities, arm-reversal symmetry,
    # and hard rejection of incomplete evidence; no model, RTL or external statistics dependency.
    lo,hi=binomial_interval(0,1,.0125)
    assert lo==0. and abs(hi-.9875)<1e-12
    low,high=binomial_interval(1,1,.0125)
    assert abs(low-.0125)<1e-12 and high==1.
    z=binary_pairs([True]*156,[True]*156)
    assert z['exact_mcnemar_p']==1 and z['exploratory_net_95_interval'][0]<0<z['exploratory_net_95_interval'][1]
    assert abs(z['harm_rate_97_5_interval'][1]-(1-.0125**(1/156)))<1e-12
    p=binary_pairs([False]*6,[True]*6);q=binary_pairs([True]*6,[False]*6)
    assert p['exact_mcnemar_p']==q['exact_mcnemar_p']==.03125
    assert all(abs(x+y)<1e-12 for x,y in zip(p['exploratory_net_95_interval'],reversed(q['exploratory_net_95_interval'])))
    for k in range(1,12):
        lo,hi=binomial_interval(k,12,.0125)
        assert abs(cdf(k-1,12,lo)-.9875)<1e-12 and abs(cdf(k,12,hi)-.0125)<1e-12
    for a,c in [([],[]),([True],[True,False]),([1],[True])]:
        try:binary_pairs(a,c)
        except ValueError:pass
        else:raise AssertionError('Invalid binary evidence accepted')
    tasks=[f'Task{i:03}' for i in range(156)]
    try:validate_rows([],tasks)
    except ValueError:pass
    else:raise AssertionError('Incomplete denominator accepted')
    return dict(complete=True,passed=True,scope='Arithmetic and invalid-input controls only',
                model_calls=0,eda_calls=0,full156_analysis_executed=False)


def run(a):
    if sha(a.spec)!=SPEC_SHA: raise ValueError('Unfrozen protocol')
    spec,summary,audit,guard=map(read,[a.spec,a.summary,a.audit,a.guard])
    if not summary['complete'] or not summary['passed'] or summary['spec_sha256']!=SPEC_SHA:
        raise ValueError('Full result incomplete or invalid')
    if not audit['evidence_valid'] or not audit['full156_evidence_valid'] or audit['historical_fixture_only']:
        raise ValueError('Final full156 provenance audit required')
    archive_sha=sha(a.archive)
    if audit['spec_sha256']!=SPEC_SHA or audit['archive_sha256']!=archive_sha:
        raise ValueError('Archive audit identity mismatch')
    with zipfile.ZipFile(a.archive) as archived:
        for path,member in [(a.spec,'run/RUN_SPEC.json'),(a.summary,'run/results/summary.json'),
                            (a.guard,'guard/status.json')]:
            if path.read_bytes()!=archived.read(member):
                raise ValueError('Input bytes not bound to audited archive: '+member)
    if not all(guard[k] for k in ['complete','passed','model_unchanged','protected_files_unchanged','own_slot_released']):
        raise ValueError('Postflight guard incomplete')
    if not guard['owned_cleanup']['verified'] or guard['owned_cleanup']['remaining']:
        raise ValueError('Owned cleanup incomplete')
    tasks=spec['task_ids'];pairs=validate_rows(summary['rows'],tasks)
    first={r['task']:r['first_content_identical'] for r in audit['first_pairs']}
    if len(audit['first_pairs'])!=156 or set(first)!=set(tasks) or any(type(v) is not bool for v in first.values()):
        raise ValueError('Missing first-response provenance')
    primary=summarize(pairs,tasks)
    for arm in ['A','C']:
        if not math.isclose(primary['official_quality_mean'][arm],audit['coefficients'][arm],abs_tol=1e-12):
            raise ValueError('Audited score mismatch')
    if sum(primary['attempted_requests'].values())!=audit['actual_model_requests']:
        raise ValueError('Audited request count mismatch')
    same=[t for t in tasks if first[t]]
    return dict(complete=True,analysis_only=True,promotion_decision_changed=False,
        analysis_source_sha256=sha(Path(__file__)),
        inputs={k:sha(getattr(a,k)) for k in ['summary','audit','guard','spec']},
        archived_evidence_sha256=archive_sha,primary=primary,
        identical_first_response_descriptive=summarize(pairs,same) if same else None,
        subset_is_not_primary_or_randomized=True,named_development_tasks=156,
        independent_unseen_tasks=0,effective_independent_families=None,
        guard_wall_seconds=guard['elapsed_s'],reported_stage_wall_seconds=summary.get('elapsed_s'),
        full_delivery_end_to_end_seconds=None,
        inference_cost_includes_generation_compile_and_runtime_feedback=True,
        full_competition_score_computed=False,new_official_baseline=False,five_samples=False,
        formal32GB_verified=False,full_batch_complete=False,
        limits=['Exploratory task-IID uncertainty; family correlation is unknown.',
                'No universality, equivalence or zero-harm claim, including zero discordances.',
                'L3 and simulation pass are separate; weighted quality is not binary correctness.',
                'No resampling, stopping, runtime changes or automatic promotion.'])


if __name__=='__main__':
    p=argparse.ArgumentParser()
    modes=p.add_mutually_exclusive_group()
    modes.add_argument('--self-check',action='store_true')
    modes.add_argument('--stability-self-check',action='store_true')
    modes.add_argument('--stability',action='store_true')
    for n in ['spec','summary','audit','guard','archive','out']:p.add_argument('--'+n,type=Path)
    for n in ['resource-check','paired','kit']:p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args()
    assert sys.platform=='linux', 'All project execution stays on authorized AMD'
    if sha(a.paired)!='78e9b3e144f2bd43ebab371e15ac3946017686db890a8e45891db7a386841e1c':
        raise ValueError('Unfrozen resource-check implementation')
    resource_spec=importlib.util.spec_from_file_location('paired_resource',a.paired)
    resource_module=importlib.util.module_from_spec(resource_spec)
    resource_spec.loader.exec_module(resource_module)
    resource_module.check_resource(a.resource_check,a.kit,first=True)
    result=(stability_selfcheck() if a.stability_self_check else selfcheck() if a.self_check
            else run_stability(a) if a.stability else run(a))
    resource_module.check_resource(a.resource_check,a.kit)
    result['resource_check_sha256']=sha(a.resource_check)
    if not a.out or a.out.exists():raise ValueError('New output file required')
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
