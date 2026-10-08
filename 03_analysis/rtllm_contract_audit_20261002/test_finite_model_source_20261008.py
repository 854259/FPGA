"""AMD-only new model-source plumbing checks; retained FAKE replies, no EDA/LLM."""
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


def main(root):
    assert sys.platform == 'linux' and sys.dont_write_bytecode
    arm = queue.official
    source = Path('/workspace/team/runs/fpga_teammate/prompt_table_feedback_comparison9x5_20261008_v1')
    assert arm.sha(source/'RUN_SPEC.json') == '317e40d723e7c0956a11143fc914b1841e036fe871a0ffba415f0939c90399da'
    old = Path('/workspace/team/runs/fpga_teammate/rtllm_finite_integration_U17_20261005_v1/results')
    historical = json.loads((old/'NON_DISPATCHABLE_PLAN.json').read_text())
    contract_path = Path(historical['finite_judge']['contract'])
    contract = json.loads(contract_path.read_text())
    sources = json.loads((source/'PLAN.json').read_text())['sources']
    tasks = [dict(dataset=r['dataset'], task=r['task'], family=r['family'], use=r['use'],
                  task_dir=r['task_dir'], hashes=r['input_hashes'])
             for r in historical['rows'] if r['sample'] == 0 and r['arm'] == 'A']
    plan = queue.build_plan(tasks, 5, sources, root/'official_baseline_arm_20261005.py',
                            historical['kit'], 725, 435*670)
    plan.update(model_launch_authorized=False, execution_authorized=False)
    finite.bind_plan(plan, contract_path, Path(historical['rows'][0]['evaluator_dir']).parent,
                    historical['finite_judge']['toolbin'],
                    {r['task']: r['minimum_observations'] for r in historical['rows']})
    queue.validate(plan)
    model_source = dict(root=str(source), spec_sha256=arm.sha(source/'RUN_SPEC.json'))
    identities = {a: queue.digest(dict(source=model_source, arm=a)) for a in ('A', 'P')}
    identities['B'] = arm.sha(root/'official_baseline_arm_20261005.py')
    bound_contract = report.bind_phase_p(contract, identities, model_source=model_source)
    queue.save(root/'NON_DISPATCHABLE_PLAN.json', plan)
    queue.save(root/'BOUND_REPORT_CONTRACT.json', bound_contract)
    checks = ['29_domains_bound_without_dispatch']
    rejected = []

    def reject(name, fn):
        try:
            fn()
        except (AssertionError, ValueError, KeyError):
            rejected.append(name)
        else:
            raise AssertionError('Accepted '+name)

    originals = Path('/workspace/team/runs/fpga_teammate/prompt_table_feedback_controls_20261008_v1/results/flow')
    outputs = dict(A=originals/'control_unchanged', P=originals/'candidate_repair',
                   B=old/'sources/finite_queue/row_000002/solve')
    observed = {}
    for label, retained in outputs.items():
        folder = root/('case_'+label)
        # v1 reached the A transport successfully, then used the wrong JSON
        # serialization in the test's report hash. Reuse that FAKE transport.
        reused = root.parent/'rtllm_model_source_routes_20261008_v1/case_A'
        reuse = label == 'A' and root.name.endswith('_v2')
        if reuse:
            shutil.copytree(reused, folder)
        else:
            folder.mkdir()
            shutil.copytree(retained, folder/'solve')
            shutil.copytree(retained/'prompt_only', folder/'fixture')
            queue.save(folder/'fixture/task.json', dict(task_id='FAKE_'+label))
        task = folder/'fixture'
        ledger = dict(task=task.name, input_sha256=arm.sha(task/'prompt.txt'), judge_sha256='0'*64,
                      all_files_sha256={p.name: arm.sha(p) for p in task.iterdir()},
                      scope='FAKE_WRAPPER_ONLY', remaining='not native or scoring evidence')
        args = SimpleNamespace(solve=folder/'solve', task=task, arm=label, model_source=source if label != 'B' else None,
            kit=Path(plan['kit']), resource_check=root/'FAKE_RESOURCE.json', out=folder/'judge',
            contract=contract_path, toolbin=Path(plan['finite_judge']['toolbin']), minimum_samples=1)
        resource = SimpleNamespace(check_resource=lambda *a: None)
        with patch.object(arm, 'MODEL', 'SIMULATED_NO_MODEL'), \
             patch.object(arm, 'resource_module', return_value=resource), \
             patch.object(finite, 'task_contract', return_value=ledger), \
             patch.object(finite, 'simulate', return_value=dict(passed=True, fixture='FAKE_NO_EDA')):
            if not reuse:
                finite.main(args)
        bound = json.loads((args.out/'BOUND_VERDICT.json').read_text())
        assert bound['model_source'] == (model_source if label != 'B' else None)
        assert bound['client_request_attempts'] == (2 if label == 'P' else 1)
        observed[label] = bound
        one = [dict(dataset='rtllm_finite_development', task=ledger['task'], family='FAKE', use='development',
                    task_dir=str(task), hashes={'prompt.txt': ledger['input_sha256']},
                    evaluator_dir=str(task), evaluator_hashes=ledger['all_files_sha256'])]
        test_plan = queue.build_plan(one, 1, sources, root/'official_baseline_arm_20261005.py', plan['kit'], 5, 2010)
        test_plan['finite_judge'] = copy.deepcopy(plan['finite_judge'])
        for row in test_plan['rows']:
            row['minimum_observations'] = 1
        run = dict(run_id='FAKE_REPORT_FORMAT_ONLY', observation_kind='real_model',
                   model_config_sha256='0'*64, arm_sources=identities)
        test_plan.update(reporting_run=run, reporting_implementation_sha256=arm.sha(report.__file__),
                        reporting_contract_sha256=report.digest((json.dumps(bound_contract, indent=2, ensure_ascii=False)+'\n').encode()))
        row = next(r for r in test_plan['rows'] if r['arm'] == label)
        argv = queue.launch_args(test_plan, row, folder, args.resource_check)
        queue.save(folder/'STARTED.json', dict(row=row, plan_sha256=queue.digest(test_plan)))
        commands = []

        def fake_command(command, cwd, log, seconds):
            commands.append(command)
            Path(log).write_text('FAKE_TRANSPORT_REUSES_RETAINED_OUTPUT\n')
            if len(commands) == 2:
                assert command[2] == str(Path(finite.__file__).resolve())
                assert ('--model-source' in command) == (label != 'B')
                if label != 'B':
                    assert command[command.index('--model-source')+1] == str(source)
                assert '--generation-source' not in command
            return dict(timeout=False, launch_error=None, returncode=0, remaining_live_group=[], elapsed_s=0)

        resource.owned_command = fake_command
        with patch.object(arm, 'resource_module', return_value=resource), \
             patch.object(arm, 'MODEL', 'SIMULATED_NO_MODEL'), patch.object(queue, 'validate'):
            if reuse:
                receipt = json.loads((reused/'TERMINAL.json').read_text())
                queue.save(root/'REUSED_A_ORIGINAL_TERMINAL.json', receipt)
                receipt['files'] = {n: arm.sha(folder/n) for n in receipt['files']}
                receipt['relocated_fake_transport'] = True
            else:
                receipt = queue.execute_row(test_plan, argv, row, folder, args.resource_check)
        assert receipt['complete'], receipt
        queue.save(folder/'TERMINAL.json', receipt)
        normalized = report.normalize_queue_row(folder, row, test_plan, bound_contract, run)
        assert normalized['model_binding'] == bound['model_binding']
        receipt.update(synthetic=True, real_model_calls=0)
        queue.save(folder/'TERMINAL.json', receipt)
        reject(label+'_synthetic_not_score', lambda: report.normalize_queue_row(folder, row, test_plan, bound_contract, run))
    checks.append('three_retained_arms_finite_queue_and_reporting')
    rows = []
    for task in contract['ledger']:
        if task['status'] != 'finite_default_domain_evidence':
            continue
        for label in ('A', 'P', 'B'):
            bound = observed[label]
            for sample in range(5):
                rows.append(dict(task=task['task'], arm=label, sample=sample, passed=True, status='completed',
                    input_sha256=task['input_sha256'], judge_sha256=task['judge_sha256'], run_id=run['run_id'],
                    model_config_sha256=run['model_config_sha256'], arm_source_sha256=identities[label],
                    call_attempts=bound['client_request_attempts'], call_confirmed=bound['confirmed_model_responses'],
                    solve_s=0, judge_s=0, model_source=bound['model_source'], model_binding=bound['model_binding'],
                    solution_sha256=bound['solution_sha256']))
    summary = report.summarize(rows, bound_contract, run)
    assert summary['scored_tasks'] == 29 and summary['generation_rows'] == 435
    assert summary['official_contest_score'] is None and summary['blocked_unscored_tasks'] == 15
    for name, change in [('missing_model', lambda r: r.pop('model_binding')),
                         ('different_source', lambda r: r.update(model_source=dict(root=str(root), spec_sha256='f'*64))),
                         ('different_solution', lambda r: r.update(solution_sha256='f'*64)),
                         ('zero_calls', lambda r: r.update(call_attempts=0, call_confirmed=0))]:
        bad = copy.deepcopy(rows); change(bad[0])
        reject(name, lambda: report.summarize(bad, bound_contract, run))
    checks.append('five_sample_model_report_preserves_finite_scope')
    queue.save(root/'CONTROL_RESULT.json', dict(passed=True, checks=checks, rejected=rejected,
        fixture='RETAINED_FAKE_OUTPUTS_AND_SYNTHETIC_REPORT_ONLY', real_model_calls=0, eda_commands=0,
        solver_executions=0, old_native_controls_rerun=0, retained_solve_cases=3, fake_native_judges=3,
        full_scoring_admission=False, full_batch=False))


if __name__ == '__main__':
    main(Path(sys.argv[1]).resolve())
