"""AMD-only RTLLM finite-domain reporting contract. No generation or EDA.

This validates historical fixture identity and a reporting function using synthetic
rows. It does not run candidate scoring or authorize a complete model experiment.
"""
import argparse
import copy
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import time
import zipfile

ARCHIVE_SHA = '13d60f0d05e64f2342a70563480e315447cb275bf6ddb339b183bc4d06e22d51'
MANIFEST_SHA = 'eae6c4cc03ea4d5b32318b49bb26bbb127e1b62cf12db8f35c8c84691b1428fa'
COVERAGE_SHA = '53d9da2c4a0fb136288feae68537c39c5fed7168053ddb98c10fce21f9ca916c'
PUBLIC_SHA = '3bedb60d2b65ad6c2b042a292a82358e9019c755fcaf54d010e41a854d7e33aa'
PAIRED_SHA = '78e9b3e144f2bd43ebab371e15ac3946017686db890a8e45891db7a386841e1c'
ARMS = ('A', 'C', 'B')


def digest(b):
    return hashlib.sha256(b).hexdigest()


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def make_contract(coverage, public, manifest, original):
    tasks = coverage['tasks']
    require(len(tasks) == len({t['task'] for t in tasks}) == 44, 'inventory denominator')
    require(coverage['score_aggregation_permitted'] is False, 'historical gate changed')
    finite = {t['task'] for t in tasks if t['status'] == 'finite_default_domain_evidence'}
    blocked = {t['task'] for t in tasks if t['status'] == 'specification_blocked'}
    require(len(finite) == 29 and len(blocked) == 15 and not finite & blocked, 'partition')
    require(blocked == {t['task'] for t in manifest['blocked']}, 'blocked identity')
    require(original['complete'] and original['execution_valid'] and
            original['frozen_inputs_unchanged'] and original['error'] is None, 'original validity')
    new = {t['task']: t for t in public['rows']}
    reused = {t['task']: t for t in public['reused']}
    require(len(new) == 20 and len(reused) == 9 and not new.keys() & reused.keys(), 'control partition')
    require(set(new) | set(reused) == finite, 'finite evidence identity')
    require(finite == {r['task'] for r in original['new_controls']+original['reused_controls']},
            'original control identity')
    ledger = []
    for t in tasks:
        name = t['task']
        require(t['prior_exposure'] == 'historical_public_development_not_unseen' and
                t['universal_contract_certified'] is False, 'exposure or scope')
        files = {rel: manifest['files'][name+'/'+rel] for rel in
                 ('prompt.txt', 'ref.sv', 'reference/solution.sv', 'task.json', 'tb.sv')}
        if name in new:
            row = new[name]
            require(row['passed'] is True, 'positive/negative control failed')
            pos, neg = row['arms']['positive'], row['arms']['negative']
            require(pos['valid'] and neg['valid'] and pos['errors'] == 0 and neg['errors'] > 0,
                    'invalid finite controls')
            require(pos['tb_sha256'] == neg['tb_sha256'] == files['tb.sv'] and
                    pos['source_sha256'] == files['reference/solution.sv'], 'control file identity')
        elif name in reused:
            require(all(files[k] == v for k, v in reused[name]['files'].items()), 'reused identity')
        ledger.append(dict(task=name, status=t['status'], scope=t.get('current_verified_scope'),
                           remaining=t['minimum_remaining_check'], prior_exposure=t['prior_exposure'],
                           input_sha256=files['prompt.txt'], judge_sha256=files['tb.sv'],
                           all_files_sha256=files))
    return dict(schema='rtllm_finite_reporting_v1', original_inventory=44, finite_tasks=29,
                specification_blocked=15, independent_tasks=0, samples_per_task=5, arms=list(ARMS),
                expected_finite_rows=435, ledger=ledger, model_launch_authorized=False,
                full44_contract_certified=False, full_batch_complete=False,
                limits=['Finite functional-domain report only; no official L0-L3 or contest score.',
                        'All44 ledger retained;15 unscored specification blocks are not model failures.',
                        'Five generations per task do not create five independent tasks.',
                        'Historical score_aggregation_permitted remains false; no admission override.',
                        'Solver input may use prompt only; judge and reference files remain isolated.',
                        'No independent generalization, family independence or promotion established.'])


def bind_phase_p(contract, arm_sources):
    """Create a new source-bound contract; never relabel historical C results.

    The caller audits these execution identities before binding. This only
    binds report semantics and does not authenticate model runs or admit them.
    """
    original = json.dumps(contract, indent=2, ensure_ascii=False)+'\n'
    require(digest(original.encode()) ==
            '7e381b00f7968dcb217cfab41a2c28faf0d8271706f1729024a0aa9e07dfa14f',
            'original U2 contract identity')
    require(set(arm_sources) == {'A', 'P', 'B'}, 'explicit A/P/B identities')
    require(all(isinstance(v, str) and len(v) == 64 and
                all(c in '0123456789abcdef' for c in v) for v in arm_sources.values()),
            'source identity hash')
    require(len(set(arm_sources.values())) == 3, 'arm execution identities must differ')
    bound = copy.deepcopy(contract)
    bound.update(schema='rtllm_finite_reporting_phaseP_v2', arms=['A', 'P', 'B'],
                 parent_contract_sha256=digest(original.encode()),
                 arm_sources=copy.deepcopy(arm_sources), candidate_arm='P')
    return bound


def normalize_queue_row(folder, row, plan, contract, run):
    """Normalize a verified terminal receipt, including sealed recovery.

    The caller must bind run/source/model identities in the plan before freeze.
    Request and solution eligibility is checked by the isolated judge; the
    original row manifest then binds its result. Synthetic execution stays
    explicitly synthetic and is never accepted as a model observation here.
    """
    import three_arm_queue_20261005 as queue
    folder = Path(folder)
    require(plan['reporting_run'] == run, 'unfrozen reporting run')
    require(run['observation_kind'] == 'real_model', 'non-model run cannot become model scores')
    serialized = (json.dumps(contract, indent=2, ensure_ascii=False)+'\n').encode()
    require(plan['reporting_contract_sha256'] == digest(serialized), 'report contract drift')
    require(contract['arm_sources'] == run['arm_sources'], 'run source drift')
    require(row in plan['rows'], 'row outside plan')
    receipt = queue.verify_terminal(folder, row, queue.digest(plan))
    require(receipt.get('synthetic') is not True and receipt.get('real_model_calls') != 0,
            'synthetic observations cannot become model scores')
    require(type(receipt.get('finite_pass')) is bool, 'not a finite-domain receipt')
    name = 'judge/BOUND_VERDICT.json'
    require(name in receipt['files'], 'unbound judge result')
    if (folder/name).is_file():
        raw = (folder/name).read_bytes()
    else:
        with zipfile.ZipFile(folder/'EVIDENCE.zip') as archive:
            raw = archive.read(name)
    require(digest(raw) == receipt['files'][name], 'judge receipt drift')
    bound = json.loads(raw)
    finite = plan['finite_judge']
    require(bound['schema'] == 'rtllm_finite_verdict_v1' and
            bound['arm'] == row['arm'] and bound['task'] == row['task'], 'judge identity')
    require(bound['contract_sha256'] == finite['contract_sha256'] and
            bound['evaluator_sha256'] == finite['entry_sha256'], 'judge source drift')
    require(bound['task_files'] == row['evaluator_hashes'] and
            bound['input_sha256'] == row['input_hashes']['prompt.txt'], 'judge inputs')
    require(bound['client_request_attempts'] == bound['confirmed_model_responses'] ==
            receipt['actual_calls'] and receipt['unconfirmed_calls'] == 0, 'unconfirmed responses')
    require(bound['verdict']['passed'] == receipt['finite_pass'], 'outcome drift')
    return dict(task=row['task'], arm=row['arm'], sample=row['sample'],
        passed=receipt['finite_pass'], status='completed', input_sha256=bound['input_sha256'],
        judge_sha256=bound['judge_sha256'], run_id=run['run_id'],
        model_config_sha256=run['model_config_sha256'], arm_source_sha256=run['arm_sources'][row['arm']],
        call_attempts=receipt['actual_calls'], call_confirmed=bound['confirmed_model_responses'],
        solve_s=receipt['solve_elapsed_s'], judge_s=receipt['judge_elapsed_s'])


def summarize(rows, contract, run):
    """Accept a complete normalized finite-domain result only; never select/retry rows.

    Caller must separately audit the actual model requests, process identity,
    generation configuration, arm sources and grading receipts. This function
    validates declared hashes; it cannot authenticate those declarations.
    """
    arms = tuple(contract['arms'])
    require(arms in (ARMS, ('A', 'P', 'B')), 'unsupported arm labels')
    if arms != ARMS:
        require(contract['schema'] == 'rtllm_finite_reporting_phaseP_v2' and
                contract['candidate_arm'] == 'P' and
                contract['arm_sources'] == run['arm_sources'], 'frozen phaseP source binding')
    candidate = arms[1]
    finite = {r['task']: r for r in contract['ledger'] if r['status'] == 'finite_default_domain_evidence'}
    expected = {(task, arm, sample) for task in finite for arm in arms for sample in range(5)}
    require(len(rows) == 435, 'missing or extra rows')
    require(isinstance(run['run_id'], str) and bool(run['run_id']), 'run id')
    for v in [run['model_config_sha256'], *run['arm_sources'].values()]:
        require(isinstance(v, str) and len(v) == 64 and all(c in '0123456789abcdef' for c in v), 'run hash')
    require(set(run['arm_sources']) == set(arms), 'arm identities')
    indexed = {}
    for row in rows:
        require(type(row['sample']) is int, 'sample type')
        key = (row['task'], row['arm'], row['sample'])
        require(key in expected and key not in indexed, 'duplicate, blocked or unknown row')
        task = finite[row['task']]
        require(row['status'] == 'completed' and type(row['passed']) is bool, 'non-complete or invalid outcome')
        for field, value in (('input_sha256', task['input_sha256']), ('judge_sha256', task['judge_sha256']),
                             ('run_id', run['run_id']), ('model_config_sha256', run['model_config_sha256']),
                             ('arm_source_sha256', run['arm_sources'][row['arm']])):
            require(row[field] == value, field+' mismatch')
        calls = row['call_attempts']
        require(type(calls) is int and 1 <= calls <= (1 if row['arm'] == 'B' else 2), 'call budget')
        require(type(row['call_confirmed']) is int and row['call_confirmed'] == calls, 'unconfirmed call')
        for field in ('solve_s', 'judge_s'):
            require(type(row[field]) in (int, float) and math.isfinite(row[field]) and row[field] >= 0,
                    'invalid elapsed time')
        indexed[key] = row
    require(set(indexed) == expected, 'incomplete grid')
    arm_reports = {}
    for arm in arms:
        grouped = [[indexed[t, arm, s] for s in range(5)] for t in sorted(finite)]
        arm_reports[arm] = dict(
            task_count=29, generation_count=145,
            finite_pass_at_1=sum(r['passed'] for g in grouped for r in g)/145,
            finite_pass_at_5_diagnostic=sum(any(r['passed'] for r in g) for g in grouped)/29,
            calls=sum(r['call_attempts'] for g in grouped for r in g),
            solve_s=sum(r['solve_s'] for g in grouped for r in g),
            judge_s=sum(r['judge_s'] for g in grouped for r in g))
    differences = []
    per_sample = []
    for sample in range(5):
        a = [indexed[t, 'A', sample]['passed'] for t in sorted(finite)]
        c = [indexed[t, candidate, sample]['passed'] for t in sorted(finite)]
        per_sample.append(dict(sample=sample, tasks=29, repairs=sum(not x and y for x,y in zip(a,c)),
                               harms=sum(x and not y for x,y in zip(a,c)),
                               unchanged=sum(x == y for x,y in zip(a,c))))
    for t in sorted(finite):
        differences.append(sum(int(indexed[t,candidate,s]['passed'])-int(indexed[t,'A',s]['passed']) for s in range(5))/5)
    task_results = [dict(task=t['task'], status=t['status'], scope=t['scope'], remaining=t['remaining'],
                         arms={a:sum(indexed[t['task'],a,s]['passed'] for s in range(5))/5 for a in arms}
                         if t['task'] in finite else None) for t in contract['ledger']]
    return dict(report_kind='finite_domain_development_only', original_inventory=44,
                scored_tasks=29, blocked_unscored_tasks=15, independent_tasks=0,
                task_families_independence_unknown=True, generation_rows=len(rows),
                arms=arm_reports, task_results=task_results, paired_by_generation=per_sample, paired_task_mean_deltas=differences,
                comparison=['A', candidate],
                net_task_mean_delta=sum(differences)/29,
                full44_accuracy=None, official_contest_score=None, uncertainty=None,
                promotion_permitted=False, full_batch_complete=False,
                limitation='No uncertainty or run-identity authentication here; caller must supply audited run receipts and task-cluster uncertainty. Component times exclude batch overhead.')


def test_reporting(contract):
    arms = tuple(contract['arms'])
    run = dict(run_id='synthetic_report_guard_only', model_config_sha256='0'*64,
               arm_sources=contract.get('arm_sources', {a:str(i)*64 for i,a in enumerate(arms,1)}))
    rows = [dict(task=t['task'], arm=a, sample=s, passed=True, status='completed',
                 input_sha256=t['input_sha256'], judge_sha256=t['judge_sha256'],
                 run_id=run['run_id'], model_config_sha256=run['model_config_sha256'],
                 arm_source_sha256=run['arm_sources'][a], call_attempts=1, call_confirmed=1,
                 solve_s=1.0, judge_s=2.0)
            for t in contract['ledger'] if t['status']=='finite_default_domain_evidence'
            for a in arms for s in range(5)]
    result = summarize(rows,contract,run)
    require(result['arms']['A']['finite_pass_at_1'] == 1 and result['scored_tasks'] == 29 and
            result['blocked_unscored_tasks'] == 15 and result['independent_tasks'] == 0 and
            len(result['task_results']) == 44 and
            sum(t['arms'] is None for t in result['task_results']) == 15, 'positive report')
    # A complete five-repeat task remains one task: rescue it in C.
    first = rows[0]['task']
    positive = copy.deepcopy(rows)
    for r in positive:
        if r['task'] == first and r['arm'] == 'A': r['passed'] = False
    result = summarize(positive,contract,run)
    require(all(x['repairs']==1 and x['harms']==0 for x in result['paired_by_generation']) and
            abs(result['net_task_mean_delta']-1/29)<1e-12, 'task-level repeated rescue')
    checks = ['complete_grid', 'five_repeats_one_task']
    bad_cases = [('missing', rows[:-1]), ('duplicate', rows[:-1]+[rows[0]])]
    mutations = [('blocked','task',next(t['task'] for t in contract['ledger'] if t['status']=='specification_blocked')),
                 ('environment','status','environment_error'), ('unconfirmed','call_confirmed',0),
                 ('input_drift','input_sha256','f'*64), ('judge_drift','judge_sha256','f'*64),
                 ('model_drift','model_config_sha256','f'*64), ('source_drift','arm_source_sha256','f'*64),
                 ('mixed_runs','run_id','another'), ('numeric_pass','passed',1),
                 ('nan_time','solve_s',float('nan')), ('negative_time','judge_s',-1),
                 ('sample_type','sample',True), ('retry_budget','call_attempts',3)]
    for name, field, value in mutations:
        bad = copy.deepcopy(rows); bad[0][field]=value; bad_cases.append((name,bad))
    bad = copy.deepcopy(rows)
    next(r for r in bad if r['arm']=='B').update(call_attempts=2,call_confirmed=2)
    bad_cases.append(('baseline_retry',bad))
    for name,bad in bad_cases:
        try: summarize(bad,contract,run)
        except ValueError: checks.append(name)
        else: raise AssertionError('accepted '+name)
    return dict(passed=len(checks), checks=checks, synthetic_only=True,
                candidate_scores=0, candidate_quality_gain=None)


def main(a):
    require(sys.platform == 'linux', 'AMD execution only')
    for path,h in ((a.archive,ARCHIVE_SHA),(a.coverage,COVERAGE_SHA),(a.public,PUBLIC_SHA),(a.paired,PAIRED_SHA)):
        require(digest(path.read_bytes())==h,'input hash '+path.name)
    imp=importlib.util.spec_from_file_location('report_resource',a.paired)
    resource=importlib.util.module_from_spec(imp);imp.loader.exec_module(resource)
    resource.check_resource(a.resource_check,a.kit,first=True)
    tick=time.monotonic()
    coverage=json.loads(a.coverage.read_text());public=json.loads(a.public.read_text())
    with zipfile.ZipFile(a.archive) as z:
        require(len(z.namelist())==len(set(z.namelist())),'duplicate archive entries')
        raw=z.read('results/DATASET_MANIFEST.json')
        require(digest(raw)==MANIFEST_SHA,'manifest hash')
        manifest=json.loads(raw); original=json.loads(z.read('results/summary.json'))
        prefix='results/tasks_admission_v2/'
        names={n[len(prefix):] for n in z.namelist() if n.startswith(prefix) and not n.endswith('/')}
        require(names==set(manifest['files']) and len(names)==220,'dataset file inventory')
        for name,h in manifest['files'].items():
            require(digest(z.read(prefix+name))==h,'archived dataset drift')
            require(digest((a.dataset/name).read_bytes())==h,'live dataset drift')
        live={str(p.relative_to(a.dataset)) for p in a.dataset.rglob('*') if p.is_file()}
        require(live==names,'live extra or missing files')
        contract=make_contract(coverage,public,manifest,original)
    tests=test_reporting(contract)
    resource.check_resource(a.resource_check,a.kit)
    a.out.mkdir(exist_ok=False)
    (a.out/'REPORTING_CONTRACT.json').write_text(json.dumps(contract,indent=2,ensure_ascii=False)+'\n')
    report=dict(complete=True,analysis_only=True,source_commit=a.source_commit,
                source_sha256=digest(Path(__file__).read_bytes()), model_calls=0,eda_calls=0,
                archive_sha256=ARCHIVE_SHA,manifest_sha256=MANIFEST_SHA,coverage_sha256=COVERAGE_SHA,
                public_admission_sha256=PUBLIC_SHA,fixture_files_verified=220,inventory=44,
                finite_domain_tasks=29,specification_blocked=15,independent_tasks=0,
                reporting_checks=tests,historical_global_aggregation_gate_unchanged=True,
                actual_candidate_rows_aggregated=0,full_batch_complete=False,promotion_permitted=False,
                reporting_contract_sha256=digest((a.out/'REPORTING_CONTRACT.json').read_bytes()),
                elapsed_s=time.monotonic()-tick)
    (a.out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(report),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ('archive','dataset','coverage','public','paired','kit','resource-check','out'):
        p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--source-commit',required=True)
    main(p.parse_args())
