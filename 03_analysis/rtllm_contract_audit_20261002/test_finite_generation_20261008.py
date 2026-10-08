"""New source/zero-call plumbing only; retained FAKE outputs, no solver or EDA."""
import copy
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace
from unittest.mock import patch

import finite_scoring_20261005 as finite
import reporting_contract_20261005 as report
import three_arm_queue_20261005 as queue

arm = queue.official
OLD = Path('/workspace/team/runs/fpga_teammate/three_arm_generation_routes_20261008_v1')
U17 = Path('/workspace/team/runs/fpga_teammate/rtllm_finite_integration_U17_20261005_v1')


def main(root):
    checks = []

    def reject(name, fn):
        try:
            fn()
        except (AssertionError, ValueError, KeyError):
            checks.append(name)
        else:
            raise AssertionError('Accepted '+name)

    sources = json.loads((OLD/'SOURCES.json').read_text())
    old_entry = str(OLD/'three_arm_generation_20261008.py')
    digest = sources['files'].pop(old_entry)
    assert arm.sha(root/'three_arm_generation_20261008.py') == digest
    sources['files'][str(root/'three_arm_generation_20261008.py')] = digest
    old_plan = json.loads((U17/'results/NON_DISPATCHABLE_PLAN.json').read_text())
    contract_path = Path(old_plan['finite_judge']['contract'])
    contract = json.loads(contract_path.read_text())
    tasks = [dict(dataset=r['dataset'], task=r['task'], family=r['family'], use=r['use'],
                  task_dir=r['task_dir'], hashes=r['input_hashes'])
             for r in old_plan['rows'] if r['sample'] == 0 and r['arm'] == 'A']
    plan = queue.build_plan(tasks, 5, sources, root/'official_baseline_arm_20261005.py',
                            old_plan['kit'], 725, 435*670)
    plan['model_launch_authorized'] = False
    dataset = Path(old_plan['rows'][0]['evaluator_dir']).parent
    floors = {r['task']: r['minimum_observations'] for r in old_plan['rows']}
    finite.bind_plan(plan, contract_path, dataset, old_plan['finite_judge']['toolbin'], floors)
    queue.validate(plan)
    identities = {a: s['spec_sha256'] for a, s in sources['generation_arms'].items()}
    identities['B'] = arm.sha(root/'official_baseline_arm_20261005.py')
    bound_contract = report.bind_phase_p(contract, identities, sources['generation_arms'])
    queue.save(root/'NON_DISPATCHABLE_PLAN.json', plan)
    queue.save(root/'BOUND_REPORT_CONTRACT.json', bound_contract)
    checks.append('29_frozen_domains_and_new_sources_bind_without_dispatch')
    fake_resource = SimpleNamespace(check_resource=lambda *a: None)
    cases = []
    for label, kind in [('A', 'table'), ('P', 'vector'), ('A', 'model'), ('P', 'model')]:
        folder = root/('case_'+label+'_'+kind); folder.mkdir()
        old = OLD/folder.name
        shutil.copytree(old/'solve', folder/'solve')
        shutil.copytree(old/'prompt_only', folder/'prompt_only')
        # Retained receipts are FAKE. Relocate their single candidate argv in
        # this new synthetic fixture; original receipts stay byte-for-byte intact.
        for path in (folder/'solve/native_receipts').glob('*/command.json'):
            command = json.loads(path.read_text())
            before = str(old/'solve/work/mechanical_compile-0/candidate.sv')
            after = str(folder/'solve/work/mechanical_compile-0/candidate.sv')
            assert command['argv'][-1] == before
            command['argv'][-1] = after
            command['fixture'] = 'RELOCATED_FAKE_RECEIPT_NOT_NATIVE_EVIDENCE'
            queue.save(path, command)
        task = folder/'fixture'; task.mkdir()
        (task/'prompt.txt').write_bytes((old/'prompt_only/prompt.txt').read_bytes())
        queue.save(task/'task.json', dict(task_id='FAKE_FINITE_'+label+'_'+kind))
        ledger = dict(task=task.name, input_sha256=arm.sha(task/'prompt.txt'), judge_sha256='0'*64,
                      all_files_sha256={p.name: arm.sha(p) for p in task.iterdir()},
                      scope='FAKE_NO_NATIVE', remaining='no score qualification')
        args = SimpleNamespace(solve=folder/'solve', task=task, arm=label,
            generation_source=Path(sources['generation_arms'][label]['root']),
            kit=Path(plan['kit']), resource_check=root/'FAKE_RESOURCE.json', out=folder/'judge',
            contract=contract_path, toolbin=Path(old_plan['finite_judge']['toolbin']), minimum_samples=1)
        original_sha = arm.sha(folder/'solve/worker_result.json')
        with patch.object(finite, 'task_contract', return_value=ledger), \
             patch.object(finite, 'simulate', return_value=dict(passed=True, fixture='FAKE_NO_EDA')), \
             patch.object(arm, 'resource_module', return_value=fake_resource):
            finite.main(args)
        bound = json.loads((args.out/'BOUND_VERDICT.json').read_text())
        assert bound['arm'] == label and bound['generation_binding']['worker_arm'] == 'P'
        assert bound['client_request_attempts'] == (0 if kind != 'model' else 2 if label == 'A' else 1)
        assert arm.sha(folder/'solve/worker_result.json') == original_sha
        cases.append((folder, args, ledger, bound))
    checks.append('four_retained_routes_through_finite_judge_binding')
    folder, args, ledger, bound = cases[0]
    one = [dict(dataset='rtllm_finite_development', task=ledger['task'], family='FAKE',
                use='development', task_dir=str(args.task), hashes={'prompt.txt':ledger['input_sha256']},
                evaluator_dir=str(args.task), evaluator_hashes=ledger['all_files_sha256'])]
    test_plan = queue.build_plan(one, 1, sources, root/'official_baseline_arm_20261005.py', plan['kit'], 5, 2010)
    test_plan['finite_judge'] = copy.deepcopy(plan['finite_judge'])
    for r in test_plan['rows']:
        r['minimum_observations'] = 1
    run = dict(run_id='FAKE_FORMAT_ONLY_NOT_A_SCORE', observation_kind='real_agent',
               model_config_sha256='0'*64, arm_sources=identities)
    test_plan.update(reporting_run=run, reporting_implementation_sha256=arm.sha(report.__file__),
                    reporting_contract_sha256=report.digest((json.dumps(bound_contract, indent=2, ensure_ascii=False)+'\n').encode()))
    row = next(r for r in test_plan['rows'] if r['arm'] == 'A')
    argv = queue.launch_args(test_plan, row, folder, args.resource_check)
    queue.save(folder/'STARTED.json', dict(row=row, plan_sha256=queue.digest(test_plan)))
    commands = []

    def fake_command(command, cwd, log, seconds):
        commands.append(command)
        Path(log).write_text('FAKE_TRANSPORT_REUSES_RETAINED_OUTPUT\n')
        if len(commands) == 2:
            assert command[command.index('--generation-source')+1] == str(args.generation_source)
            assert command[command.index('--minimum-samples')+1] == '1'
            assert command[2] == str(Path(finite.__file__).resolve())
        return dict(timeout=False, launch_error=None, returncode=0, remaining_live_group=[], elapsed_s=0)

    fake_resource.owned_command = fake_command
    with patch.object(arm, 'resource_module', return_value=fake_resource):
        receipt = queue.execute_row(test_plan, argv, row, folder, args.resource_check)
    assert receipt['complete'] and receipt['actual_calls'] == 0, receipt
    assert row['reserved_calls'] == 2 and test_plan['required_reserved_calls'] == 5
    # Format-only acceptance is exercised before the permanent synthetic marker.
    queue.save(folder/'TERMINAL.json', receipt)
    normalized = report.normalize_queue_row(folder, row, test_plan, bound_contract, run)
    assert normalized['call_attempts'] == 0 and normalized['generation_binding'] == bound['generation_binding']
    receipt.update(synthetic=True, real_model_calls=0)
    queue.save(folder/'TERMINAL.json', receipt)
    reject('synthetic_zero_receipt_rejected', lambda: report.normalize_queue_row(folder, row, test_plan, bound_contract, run))
    queue.seal_row(folder, row, queue.digest(test_plan))
    reject('sealed_synthetic_zero_rejected', lambda: report.normalize_queue_row(folder, row, test_plan, bound_contract, run))
    checks.append('finite_queue_source_argument_and_full_reservation')
    rows = [dict(task=t['task'], arm=a, sample=s, passed=True, status='completed',
        input_sha256=t['input_sha256'], judge_sha256=t['judge_sha256'], run_id=run['run_id'],
        model_config_sha256=run['model_config_sha256'], arm_source_sha256=identities[a],
        call_attempts=1, call_confirmed=1, solve_s=0, judge_s=0)
        for t in bound_contract['ledger'] if t['status']=='finite_default_domain_evidence'
        for a in ['A','P','B'] for s in range(5)]
    zero = rows[0]
    fixture_binding = copy.deepcopy(bound['generation_binding'])
    fixture_binding['input_sha256'] = {'prompt.txt': zero['input_sha256']}
    zero.update(call_attempts=0, call_confirmed=0, generation_binding=fixture_binding)
    summary = report.summarize(rows, bound_contract, run)
    assert summary['arms']['A']['calls'] == 144 and summary['generation_rows'] == 435
    checks.append('435_synthetic_rows_keep_29_domains_and_zero_call_accounting')
    for name, change in [
        ('missing_binding', lambda r: r.pop('generation_binding')),
        ('wrong_source', lambda r: r['generation_binding'].update(source_spec_sha256='f'*64)),
        ('model_route_zero', lambda r: r['generation_binding'].update(generation_route='model'))]:
        bad = copy.deepcopy(rows); change(bad[0])
        reject(name, lambda: report.summarize(bad, bound_contract, run))
    bad = copy.deepcopy(rows); next(r for r in bad if r['arm']=='B').update(call_attempts=0, call_confirmed=0)
    reject('baseline_zero_rejected', lambda: report.summarize(bad, bound_contract, run))
    legacy = report.bind_phase_p(contract, identities)
    reject('legacy_zero_rejected', lambda: report.summarize(rows, legacy, run))
    queue.save(root/'CONTROL_RESULT.json', dict(passed=True, checks=checks, fixture='ALL_FAKE_NO_SCORE',
        real_model_calls=0, eda_commands=0, solver_executions=0, old_native_controls_rerun=0,
        real_candidate_rows=0, reused_solve_cases=4, new_finite_wrapper_cases=4))


if __name__ == '__main__':
    main(Path(sys.argv[1]).resolve())
