"""AMD-only RTLLM A/P/B input/source binding; no inference or EDA.

This produces a non-runnable plan: the finite-domain judge is still unbound.
Legacy C reports remain separate and are never converted into P observations.
"""
import argparse
import copy
import json
from pathlib import Path
import sys
import time

import reporting_contract_20261005 as reporting
import three_arm_queue_20261005 as queue

official = queue.official
CONTRACT_SHA = '7e381b00f7968dcb217cfab41a2c28faf0d8271706f1729024a0aa9e07dfa14f'
QUEUE_SHA = 'de7d4df53461843503760047f03affa4ea682cc2aa9559e91c80db06d40f44e7'


def main(args):
    assert sys.platform == 'linux'
    assert official.sha(queue.__file__) == QUEUE_SHA
    assert official.sha(args.contract) == CONTRACT_SHA
    resource = official.resource_module()
    resource.check_resource(args.resource_check, args.kit, first=True)
    contract = json.loads(args.contract.read_text())
    assert contract['arms'] == ['A', 'C', 'B']
    out = args.out.resolve(); assert not out.exists(); out.mkdir(parents=True)
    start = time.monotonic()
    expected_files = {row['task']+'/'+name: value for row in contract['ledger']
                      for name, value in row['all_files_sha256'].items()}
    actual_files = {str(p.relative_to(args.dataset)): official.sha(p)
                    for p in args.dataset.rglob('*') if p.is_file()}
    assert len(actual_files) == 220 and actual_files == expected_files
    sources = queue.prepare_sources(out/'sources')
    queue.save(out/'SOURCE_COPY.json', sources)
    # Each identity includes the actual source manifest and the chosen arm.
    # A/P share source files but select different frozen worker branches.
    identities = {arm: dict(arm=arm, parent_spec_sha256=queue.PARENT_SPEC,
        source_files=sources['files'] if arm != 'B' else official.OFFICIAL,
        solver_entry_sha256=official.sha(Path(sources['root'])/'worker.py') if arm != 'B'
            else official.sha(official.__file__),
        observer_sha256=official.sha(Path(official.__file__).with_name('official_baseline_observed_20261005.py')),
        model=official.MODEL, temperature=0, top_p=1, max_tokens=8192,
        solve_deadline_s=300, max_requests=queue.MAX_CALLS[arm]) for arm in ('A','P','B')}
    hashes = {arm: queue.digest(identity) for arm, identity in identities.items()}
    bound = reporting.bind_phase_p(contract, hashes)
    queue.save(out/'ARM_EXECUTION_IDENTITIES.json', identities)
    queue.save(out/'REPORTING_CONTRACT_PHASE_P.json', bound)
    tasks = []
    for row in bound['ledger']:
        if row['status'] != 'finite_default_domain_evidence':
            continue
        folder = out/'prompt_only'/row['task']; folder.mkdir(parents=True)
        (folder/'prompt.txt').write_bytes((args.dataset/row['task']/'prompt.txt').read_bytes())
        tasks.append(dict(dataset='rtllm_finite_development', task=row['task'],
            family='rtllm_family_independence_unverified', use='development',
            task_dir=str(folder), hashes={'prompt.txt': row['input_sha256']}))
    plan = queue.build_plan(tasks, 5, sources, Path(official.__file__), args.kit, 725, 435*670)
    plan.update(execution_ready=False, finite_judge_bound=False, model_launch_authorized=False,
                capacity_only_not_approved_budget=True, reporting_contract_sha256=official.sha(out/'REPORTING_CONTRACT_PHASE_P.json'))
    queue.validate(plan)
    assert len(plan['rows']) == 435 and plan['unique_tasks'] == 29
    assert plan['required_reserved_calls'] == 725
    assert all('evaluator_dir' not in row for row in plan['rows'])
    assert all({p.name for p in Path(t['task_dir']).iterdir()} == {'prompt.txt'} for t in tasks)
    queue.save(out/'UNWIRED_EXECUTION_PLAN.json', plan)
    checks = ['all220_frozen_files', 'all29_prompt_only_inputs', '435_source_bound_rows']
    legacy = reporting.test_reporting(contract)
    current = reporting.test_reporting(bound)
    assert legacy['passed'] == current['passed'] == 18
    checks += ['legacy18_controls', 'phaseP18_controls']
    def reject(label, fn):
        try: fn()
        except (AssertionError, ValueError, FileNotFoundError): checks.append(label)
        else: raise AssertionError('Accepted '+label)
    folder = out/'must_not_dispatch'
    argv = queue.launch_args(plan, plan['rows'][0], folder, args.resource_check)
    reject('finite_judge_missing_blocks_actual_execution', lambda: queue.execute_row(
        plan, argv, plan['rows'][0], folder, args.resource_check))
    assert not folder.exists()
    reject('missing_P_identity', lambda: reporting.bind_phase_p(contract, {'A': hashes['A'], 'C': hashes['P'], 'B': hashes['B']}))
    reject('same_identity_for_A_and_P', lambda: reporting.bind_phase_p(contract, dict(hashes, P=hashes['A'])))
    changed = copy.deepcopy(contract); changed['ledger'][0]['input_sha256'] = 'f'*64
    reject('changed_historical_contract', lambda: reporting.bind_phase_p(changed, hashes))
    changed = copy.deepcopy(plan); changed['rows'][0]['input_hashes']['prompt.txt'] = 'f'*64
    reject('changed_solver_input_before_dispatch', lambda: queue.validate(changed))
    finite = [row for row in bound['ledger'] if row['status'] == 'finite_default_domain_evidence']
    run = dict(run_id='U16_synthetic', model_config_sha256='0'*64, arm_sources=hashes)
    rows = [dict(task=row['task'], arm=arm, sample=sample, passed=True, status='completed',
        input_sha256=row['input_sha256'], judge_sha256=row['judge_sha256'],
        run_id=run['run_id'], model_config_sha256=run['model_config_sha256'],
        arm_source_sha256=hashes[arm], call_attempts=1, call_confirmed=1, solve_s=1.0, judge_s=1.0)
        for row in finite for arm in ('A','P','B') for sample in range(5)]
    assert reporting.summarize(rows, bound, run)['comparison'] == ['A','P']
    bad = copy.deepcopy(rows)
    for row in bad:
        if row['arm'] == 'P': row['arm'] = 'C'
    reject('old_C_rows_are_not_P', lambda: reporting.summarize(bad, bound, run))
    bad_run = copy.deepcopy(run); bad_run['arm_sources']['P'] = 'f'*64
    bad = copy.deepcopy(rows)
    for row in bad:
        if row['arm'] == 'P': row['arm_source_sha256'] = 'f'*64
    reject('joint_row_and_run_source_drift', lambda: reporting.summarize(bad, bound, bad_run))
    resource.check_resource(args.resource_check, args.kit)
    assert official.sha(args.contract) == CONTRACT_SHA
    result = dict(schema='rtllm_phaseP_binding_U16', complete=True, real_model_calls=0, eda_calls=0,
        checked_source_sha256=official.sha(__file__), reporting_source_sha256=official.sha(reporting.__file__),
        original_contract_sha256=CONTRACT_SHA, source_parent_spec_sha256=queue.PARENT_SPEC,
        fixture_files=220, original_inventory=44, finite_tasks=29, blocked_unscored=15,
        bound_plan_rows=435, capacity_request_reservations=725, approved_model_budget=0,
        synthetic_checks=checks, legacy_reporting_controls=legacy['passed'], phaseP_reporting_controls=current['passed'],
        actual_candidate_outputs=0, actual_candidate_judgments=0, independent_tasks=0,
        execution_ready=False, finite_judge_bound=False, full_batch_complete=False, adoption=False,
        elapsed_s=time.monotonic()-start,
        next='Bind the isolated finite-domain native judge and actual receipt normalization before model execution; do not use official L0-L3 for RTLLM.')
    queue.save(out/'RESULTS.json', result)
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for key in ('kit','contract','dataset','out','resource-check'):
        parser.add_argument('--'+key, type=Path, required=True)
    main(parser.parse_args())
