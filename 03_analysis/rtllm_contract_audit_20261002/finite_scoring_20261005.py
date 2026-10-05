"""Isolated AMD finite-domain judge; never import into the solving process.

The historical 44-task ledger admits only 29 finite domains. This judge reports
functional observations, never an official L0-L3 or contest score. It neither
generates answers nor changes fixtures. Caller freezes source/tool/contract
hashes and owns resource admission before using the CLI.

Awaiting combined AMD validation before any model dispatch. Observation floors
are taken from frozen historical controls, never candidate scores. References
remain in this isolated judge, including the nine legacy co-simulation fixtures.
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

import official_baseline_scoring_20261005 as scoring

arm = scoring.arm
CONTRACT_SHA = '7e381b00f7968dcb217cfab41a2c28faf0d8271706f1729024a0aa9e07dfa14f'


def bind_plan(plan, contract_path, dataset, toolbin, observation_floors):
    """Attach the finite judge to a new plan before freeze, never a running plan.

    Call/model/data/resource admission remains a separate caller obligation.
    This function does not authorize dispatch, inflate the 29 finite domains to
    44 valid tasks, or mutate historical reporting contracts.
    """
    assert not plan.get('finite_judge') and plan['full_batch'] is False
    assert plan['model_launch_authorized'] is False
    plan['finite_judge'] = dict(schema='rtllm_finite_judge_binding_v1',
        entry=str(Path(__file__).resolve()), entry_sha256=arm.sha(__file__),
        contract=str(Path(contract_path).resolve()), contract_sha256=CONTRACT_SHA,
        toolbin=str(Path(toolbin).resolve()),
        tools={name:arm.sha(Path(toolbin)/name) for name in ['xvlog','xelab','xsim']})
    tasks = {}
    for row in plan['rows']:
        assert row['dataset'] == 'rtllm_finite_development'
        task = Path(dataset)/row['task']
        if row['task'] not in tasks:
            tasks[row['task']] = task_contract(contract_path, task)
        ledger = tasks[row['task']]
        assert row['input_hashes'] == {'prompt.txt': ledger['input_sha256']}
        minimum = observation_floors[row['task']]
        assert type(minimum) is int and minimum > 0
        row.update(evaluator_dir=str(task.resolve()), evaluator_hashes=ledger['all_files_sha256'],
                   minimum_observations=minimum)
    assert len(tasks) == 29
    assert set(tasks) == set(observation_floors)
    plan.update(finite_judge_bound=True, execution_ready=False,
                integration_verified=False, model_launch_authorized=False)
    return plan


def task_contract(contract_path, task):
    assert arm.sha(contract_path) == CONTRACT_SHA, 'Historical contract drift'
    contract = json.loads(Path(contract_path).read_text())
    rows = [r for r in contract['ledger'] if r['task'] == Path(task).name]
    assert len(rows) == 1 and rows[0]['status'] == 'finite_default_domain_evidence', 'Task not admitted'
    row = rows[0]
    assert {str(p.relative_to(task)): arm.sha(p) for p in Path(task).rglob('*')
            if p.is_file()} == row['all_files_sha256'], 'Fixture drift'
    assert not any(p.is_symlink() for p in Path(task).rglob('*')), 'Fixture symlink'
    meta = json.loads((Path(task)/'task.json').read_text())
    assert meta['task_id'] == row['task'] and meta['top'] == 'TopModule'
    assert meta['tb_top'] == 'tb' and meta['testbench'] == 'tb.sv' and meta['extra_files'] == []
    return row


def completed_observations(text, tb_text, minimum_samples):
    # Require one terminal summary, not an arbitrary "pass" substring. A
    # missing, duplicate, fatal or zero-observation result is unscored.
    matches = re.findall(r'^Mismatches:\s*(\d+) in\s*(\d+) samples\s*$', text, re.M)
    assert len(matches) == 1, 'Missing or duplicate terminal summary'
    errors, samples = map(int, matches[0])
    # Some legacy fixtures count several signal mismatches per observation.
    assert type(minimum_samples) is int and minimum_samples > 0
    assert samples >= minimum_samples and errors >= 0, 'Insufficient observations'
    assert not re.search(r'WATCHDOG|^\s*ERROR:', text, re.M), 'Simulation environment/watchdog failure'
    fatal = re.findall(r'^\s*(?:Fatal:|FATAL:).*$', text, re.M)
    assert not fatal or (errors > 0 and all('RTLLM_FAIL' in line for line in fatal)), 'Unexpected fatal simulation'
    if 'RTLLM_PASS' in tb_text:
        assert ('RTLLM_PASS' in text) == (errors == 0), 'Legacy pass marker inconsistent'
        assert ('RTLLM_FAIL' in text) == (errors > 0), 'Legacy fail marker inconsistent'
    if 'ADMISSION_RESULT' in tb_text:
        extra = re.findall(r'^ADMISSION_RESULT errors=(\d+) samples=(\d+)\s*$', text, re.M)
        assert len(extra) == 1 and tuple(map(int, extra[0])) == (errors, samples), 'Inconsistent summaries'
    return dict(errors=errors, samples=samples, passed=errors == 0)


def candidate_compile_failure(stage, text):
    """Only explicit candidate diagnostics qualify; unknown tool errors stop.

    Compiling the candidate separately keeps TB/reference errors outside this
    classifier. Elaboration diagnostics are left unscored until calibrated.
    """
    errors = re.findall(r'^ERROR:.*$', text, re.M)
    return (stage == 'candidate_compile' and bool(errors) and
            all(re.match(r'ERROR: \[VRFC \d+-\d+\]', line) for line in errors) and
            any(re.search(r'\[(?:.*[/\\])?candidate\.sv:\d+\]', line) for line in errors))


def simulate(solution, task, out, resource, toolbin, minimum_samples):
    """Reuse frozen fixtures, including reference files only on the judge side.

    An unclassified compile/tool/runtime failure raises and remains unscored.
    This conservative behavior must be calibrated before a model batch; it must
    not turn missing evidence into a model failure or silently drop that row.
    """
    assert type(minimum_samples) is int and minimum_samples > 0
    out = Path(out); out.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(solution, out/'candidate.sv')
    shutil.copyfile(Path(task)/'tb.sv', out/'tb.sv')
    fixtures = ['tb.sv']
    if re.search(r'\bRefModule\b', (out/'tb.sv').read_text()):
        shutil.copyfile(Path(task)/'ref.sv', out/'ref.sv')
        fixtures.insert(0, 'ref.sv')
    stages = []
    commands = [('candidate_compile', 'xvlog', ['--sv', 'candidate.sv'], 30),
                ('fixture_compile', 'xvlog', ['--sv', *fixtures], 30),
                ('xelab', 'xelab', ['tb', '-s', 'finite', '--mt', 'off'], 45),
                ('xsim', 'xsim', ['finite', '--runall'], 60)]
    observations = None
    for name, tool, options, limit in commands:
        executable = Path(toolbin)/tool
        assert executable.is_file(), 'Missing native tool: '+tool
        receipt = resource.owned_command([str(executable), *options], out, out/(name+'.log'), limit)
        stages.append(dict(name=name, **receipt))
        arm.save(out/'execution.json', dict(stages=stages, complete=False))
        assert not receipt['timeout'] and not receipt['launch_error'] and not receipt['remaining_live_group'], 'Native supervision failure'
        text = (out/(name+'.log')).read_text(errors='replace')
        if receipt['returncode'] != 0:
            if receipt['returncode'] == 1 and candidate_compile_failure(name, text):
                observations = dict(errors=None, samples=0, passed=False, reason='candidate_compile_error')
                break
            if name == 'xsim':
                observations = completed_observations(text, (out/'tb.sv').read_text(), minimum_samples)
                assert observations['errors'] > 0 and 'RTLLM_FAIL' in text, 'Nonzero simulator exit without finite failure'
            else:
                raise RuntimeError('Unclassified native failure: '+name)
    if observations is None:
        observations = completed_observations((out/'xsim.log').read_text(errors='replace'),
                                               (out/'tb.sv').read_text(), minimum_samples)
    result = dict(complete=True, **observations, stages=stages,
                  solution_sha256=arm.sha(solution), judge_sha256=arm.sha(Path(task)/'tb.sv'),
                  native_elapsed_s=sum(r['elapsed_s'] for r in stages))
    arm.save(out/'execution.json', result)
    return result


def main(args):
    assert sys.platform == 'linux', 'AMD execution only'
    ledger = task_contract(args.contract, args.task)
    original = scoring.eligible(args.solve, args.task, args.arm)
    resource = arm.resource_module()
    resource.check_resource(args.resource_check, args.kit)
    assert not args.out.exists()
    args.out.mkdir(parents=True)
    verdict = simulate(args.solve/original['solution_relative'], args.task,
                       args.out/'native', resource, args.toolbin, args.minimum_samples)
    assert task_contract(args.contract, args.task) == ledger
    assert scoring.eligible(args.solve, args.task, args.arm) == original
    resource.check_resource(args.resource_check, args.kit)
    arm.save(args.out/'verdict.json', verdict)
    arm.save(args.out/'BOUND_VERDICT.json', dict(
        schema='rtllm_finite_verdict_v1', arm=args.arm, task=ledger['task'],
        solve_result_sha256=arm.sha(args.solve/original['result_relative']),
        solution_sha256=original['solution_sha256'], verdict_sha256=arm.sha(args.out/'verdict.json'),
        evaluator_sha256=arm.sha(__file__), contract_sha256=CONTRACT_SHA,
        input_sha256=ledger['input_sha256'], judge_sha256=ledger['judge_sha256'],
        minimum_observations=args.minimum_samples,
        task_files=ledger['all_files_sha256'], client_request_attempts=original['client_request_attempts'],
        confirmed_model_responses=original['client_request_attempts'], server_received_count=None,
        scope=ledger['scope'], remaining=ledger['remaining'], verdict=verdict,
        official_score=None, full_batch=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--arm', choices=['A', 'P', 'B'], required=True)
    parser.add_argument('--minimum-samples', type=int, required=True)
    for key in ['kit', 'solve', 'task', 'out', 'contract', 'toolbin', 'resource-check']:
        parser.add_argument('--'+key, type=Path, required=True)
    main(parser.parse_args())
