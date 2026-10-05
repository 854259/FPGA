"""AMD-only A/P/B routing and durable at-most-once reservations.

This is execution plumbing, not an admission decision or a quality evaluator.
Unfinished reservations deliberately block automatic recovery: a process crash
cannot prove whether the model received a request. Never retry that row here.
"""
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import time

import official_baseline_arm_20261005 as official


PARENT = Path('/workspace/team/runs/fpga_owner/phase_full156_20261005_v1')
PARENT_SPEC = '3fb1531c14b011f80ff58de559e326a4904d3fbdbcf3cdce7d6c955285860ba1'
MAX_CALLS = {'A': 2, 'P': 2, 'B': 1}


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def save(path, value):
    """Write and fsync before launching, including the containing directory."""
    path = Path(path)
    with path.with_suffix(path.suffix+'.pending').open('w') as handle:
        json.dump(value, handle, sort_keys=True, indent=2)
        handle.write('\n'); handle.flush(); os.fsync(handle.fileno())
    path.with_suffix(path.suffix+'.pending').replace(path)
    fd = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def prepare_sources(out):
    """Copy pinned U8, changing only input/ledger routing in an owned copy."""
    out = Path(out).resolve()
    assert not out.exists() and official.sha(PARENT/'RUN_SPEC.json') == PARENT_SPEC
    spec = json.loads((PARENT/'RUN_SPEC.json').read_text())
    out.mkdir(parents=True)
    for name, expected in spec['source_hashes'].items():
        source = PARENT/name
        assert official.sha(source) == expected, name
        target = out/name; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    changes = [
        ("source = args.kit/'bench/tasks_veval'/args.task", "source = Path(os.environ['PAIRED_TASK_DIR']).resolve()"),
        ("ledger=Path('/workspace/team/activity/fpga_owner')", "ledger=ROOT/'activity'"),
        ("event_id='functional-fresh:'+spec['identity']+':'+args.task+':'+args.arm+':'+str(index)",
         "event_id='paired-fresh:'+spec['identity']+':'+str(out.relative_to(ROOT))+':'+str(index)"),
    ]
    worker = (out/'worker.py').read_text()
    for before, after in changes:
        assert worker.count(before) == 1, before
        worker = worker.replace(before, after)
    reversed_worker = worker
    for before, after in changes:
        reversed_worker = reversed_worker.replace(after, before)
    assert hashlib.sha256(reversed_worker.encode()).hexdigest() == spec['source_hashes']['worker.py']
    (out/'worker.py').write_text(worker)
    spec.update(identity=out.name, cloud_root=str(out), parent_spec_sha256=PARENT_SPEC,
                paired_route_only=True)
    spec['source_hashes']['worker.py'] = official.sha(out/'worker.py')
    save(out/'RUN_SPEC.json', spec)
    # Runtime, skill and functional feedback source bytes must remain unchanged.
    for name, expected in spec['source_hashes'].items():
        assert official.sha(out/name) == expected
    return {'root': str(out), 'parent_spec_sha256': PARENT_SPEC,
            'worker_route_changes': changes, 'files': {
                **{str(out/k): v for k, v in spec['source_hashes'].items()},
                str(out/'RUN_SPEC.json'): official.sha(out/'RUN_SPEC.json'),
                **{str(Path(spec['dependencies_cloud'])/k): v for k, v in spec['dependency_hashes'].items()}}}


def build_plan(tasks, samples, sources, official_entry, kit, call_budget, wall_seconds):
    assert samples > 0 and tasks and call_budget > 0 and wall_seconds > 0
    seen = set(); rows = []
    for task_index, task in enumerate(sorted(tasks, key=lambda x: (x['dataset'], x['task']))):
        key = (task['dataset'], task['task'])
        assert key not in seen, 'Duplicate task'
        seen.add(key)
        assert task['use'] in ['development', 'validation'] and task['family']
        assert task['hashes'].get('prompt.txt') and set(task['hashes']) <= {'prompt.txt', 'interface.txt'}
        for sample in range(samples):
            offset = (task_index+sample) % 3
            order = ['A', 'P', 'B'][offset:]+['A', 'P', 'B'][:offset]
            for arm in order:
                row = dict(dataset=task['dataset'], task=task['task'], family=task['family'],
                           use=task['use'], task_dir=task['task_dir'], input_hashes=task['hashes'],
                           sample=sample, arm=arm, reserved_calls=MAX_CALLS[arm])
                row['key'] = digest([row[k] for k in ['dataset', 'task', 'sample', 'arm']])
                if 'evaluator_dir' in task:
                    row.update(evaluator_dir=task['evaluator_dir'], evaluator_hashes=task['evaluator_hashes'])
                rows.append(row)
    return dict(schema='three_arm_queue_v1', rows=rows, samples=samples, sources=sources,
                official_entry=str(Path(official_entry).resolve()), kit=str(Path(kit).resolve()),
                entry_sha256=official.sha(official_entry), scheduler_sha256=official.sha(__file__),
                official_files=official.OFFICIAL, model=official.MODEL,
                max_calls=call_budget, required_reserved_calls=sum(x['reserved_calls'] for x in rows),
                execution_files={str(Path(official_entry).with_name(name).resolve()): official.sha(Path(official_entry).with_name(name))
                                 for name in ['official_baseline_arm_20261005.py','official_baseline_observed_20261005.py','official_baseline_scoring_20261005.py']},
                resource_module_sha256=official.PAIRED_SHA,
                wall_seconds=wall_seconds, solve_deadline_s=300,
                solve_supervisor_s=310, judge_supervisor_s=360, row_reservation_s=670,
                unique_tasks=len(seen), known_families=len({(x['dataset'], x['family']) for x in tasks}),
                # Family labels alone do not establish statistical independence.
                independent_tasks_verified=None, comprehensive_admitted=False,
                full_batch=False, retries=0)


def validate(plan):
    assert plan['scheduler_sha256'] == official.sha(__file__)
    assert plan['entry_sha256'] == official.sha(plan['official_entry'])
    assert plan['model'] == official.MODEL and plan['retries'] == 0
    assert plan['official_files'] == official.OFFICIAL
    assert plan['solve_deadline_s'] == 300
    assert (plan['solve_supervisor_s'],plan['judge_supervisor_s'],plan['row_reservation_s']) == (310,360,670)
    assert plan['resource_module_sha256'] == official.PAIRED_SHA == official.sha(official.PAIRED)
    expected_execution = {str(Path(plan['official_entry']).with_name(name).resolve()) for name in
                          ['official_baseline_arm_20261005.py','official_baseline_observed_20261005.py','official_baseline_scoring_20261005.py']}
    assert set(plan['execution_files']) == expected_execution
    for path, expected in plan['execution_files'].items():
        assert official.sha(path) == expected, 'Execution dependency drift: '+path
    for path, expected in plan['sources']['files'].items():
        assert official.sha(path) == expected, path
    for name, expected in official.OFFICIAL.items():
        assert official.sha(Path(plan['kit'])/'submission'/name) == expected
    keys = set(); groups = {}
    for row in plan['rows']:
        assert row['arm'] in MAX_CALLS and row['reserved_calls'] == MAX_CALLS[row['arm']]
        assert row['key'] == digest([row[k] for k in ['dataset', 'task', 'sample', 'arm']])
        assert row['key'] not in keys, 'Duplicate row'
        keys.add(row['key'])
        group = groups.setdefault((row['dataset'], row['task']), [])
        group.append(row)
        for name, expected in row['input_hashes'].items():
            assert name in ['prompt.txt', 'interface.txt']
            assert official.sha(Path(row['task_dir'])/name) == expected
        if 'evaluator_dir' in row:
            evaluator = Path(row['evaluator_dir']).resolve()
            assert {'task.json','prompt.txt'} <= set(row['evaluator_hashes'])
            assert {p.name:official.sha(p) for p in evaluator.iterdir() if p.is_file()} == row['evaluator_hashes']
            assert {n:row['evaluator_hashes'][n] for n in row['input_hashes']} == row['input_hashes']
    for group in groups.values():
        assert {(x['sample'], x['arm']) for x in group} == {
            (sample, arm) for sample in range(plan['samples']) for arm in MAX_CALLS}, 'Incomplete paired matrix'
        assert len({digest({k: x[k] for k in ['family', 'use', 'task_dir', 'input_hashes']}) for x in group}) == 1
    assert len(groups) == plan['unique_tasks']
    assert plan['required_reserved_calls'] == sum(x['reserved_calls'] for x in plan['rows'])


def launch_args(plan, row, folder, resource_check):
    """B has a separate original CLI entry; it can never fall through to P."""
    folder = Path(folder).resolve()
    prompt = folder/'prompt_only'
    argv = ['/usr/bin/python3', '-B']
    common = ['--kit', plan['kit'], '--resource-check', str(resource_check), '--out', str(folder/'solve')]
    if row['arm'] == 'B':
        return argv+[plan['official_entry']]+common+['--task', str(prompt)]
    return ['/usr/bin/env', 'PAIRED_TASK_DIR='+str(prompt), 'LLM_BASE_URL=http://127.0.0.1:8000/v1',
            'MODEL_NAME='+plan['model'], 'RTL_REPAIRS=1', 'RTL_TEMPERATURE=0', 'RTL_MAX_TOKENS=8192']+argv+[
        str(Path(plan['sources']['root'])/'worker.py')]+common+['--task', row['task'], '--arm', row['arm']]


def advance(plan, out, resource_check, execute):
    """execute receives the frozen argv; tests substitute a process probe.

    A real runner must enforce admission before calling this function. This
    module intentionally has no production CLI while real cancellation and the
    full data/resource/budget admission contract remain incomplete.
    """
    out = Path(out).resolve()
    assert out.is_relative_to(Path(plan['sources']['root']).resolve()), 'Native probes require owned source root'
    out.mkdir(parents=True, exist_ok=True)
    with (out/'queue.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        validate(plan)
        header = out/'QUEUE.json'
        if not header.exists():
            assert not any(out.glob('row_*')), 'Orphan row without manifest'
            save(header, dict(plan_sha256=digest(plan), started_unix=time.time()))
            save(out/'PLAN.json', plan)
        info = json.loads(header.read_text())
        assert info['plan_sha256'] == digest(plan) == digest(json.loads((out/'PLAN.json').read_text())), 'Plan drift'
        elapsed = time.time()-info['started_unix']
        assert elapsed >= 0, 'Clock moved backwards'
        allowed = {'row_'+str(i).zfill(6) for i in range(len(plan['rows']))}
        assert all(p.is_dir() and p.name in allowed for p in out.glob('row_*')), 'Unexpected result row'
        reserved = 0; next_row = None
        for index, row in enumerate(plan['rows']):
            folder = out/('row_'+str(index).zfill(6))
            if not folder.exists():
                assert not any(out.glob('row_*')) or all(
                    p.name < folder.name for p in out.glob('row_*')), 'Non-prefix results'
                next_row = (row, folder); break
            started = folder/'STARTED.json'; terminal = folder/'TERMINAL.json'
            assert started.is_file(), 'Incomplete reservation: inspect, never rerun'
            s = json.loads(started.read_text())
            assert s['row'] == row and s['plan_sha256'] == digest(plan)
            reserved += row['reserved_calls']
            assert terminal.is_file(), 'Unfinished reservation: inspect, never rerun'
            receipt = json.loads(terminal.read_text())
            assert receipt['complete'] and receipt['unconfirmed_calls'] == 0, 'Unconfirmed/failed row blocks continuation'
            assert isinstance(receipt['actual_calls'], int) and 0 <= receipt['actual_calls'] <= row['reserved_calls']
            assert receipt['files'], 'Empty terminal receipt'
            for name, expected in receipt['files'].items():
                path = (folder/name).resolve()
                assert path.is_relative_to(folder) and official.sha(path) == expected, 'Terminal evidence drift'
        if next_row is None:
            return dict(complete=True, rows=len(plan['rows']), reserved_calls=reserved, full_batch=False)
        row, folder = next_row
        assert elapsed+plan['row_reservation_s'] <= plan['wall_seconds'], 'Wall budget cannot cover next solve and judge'
        assert reserved+row['reserved_calls'] <= plan['max_calls'], 'Call reservation budget exhausted'
        folder.mkdir()
        argv = launch_args(plan, row, folder, resource_check)
        save(folder/'STARTED.json', dict(row=row, argv=argv, plan_sha256=digest(plan), started_unix=time.time()))
        prompt = folder/'prompt_only'; prompt.mkdir()
        for name, expected in row['input_hashes'].items():
            shutil.copyfile(Path(row['task_dir'])/name, prompt/name)
            assert official.sha(prompt/name) == expected
        receipt = execute(argv, row, folder)
        # Retain failures too. Never release reservations or silently retry.
        save(folder/'TERMINAL.json', receipt)
        validate(plan)
        assert {p.name: official.sha(p) for p in prompt.iterdir()} == row['input_hashes']
        return dict(complete=False, executed_key=row['key'], reserved_calls=reserved+row['reserved_calls'])


def execute_row(plan, argv, row, folder, resource_check):
    """Run the frozen solver, then an external judge; never retry or grade failures.

    Caller owns admission and the FIFO lease. No evaluator path is passed to the
    solver. Actual_calls is the legacy queue field for client attempts, not a
    claim of server receipt; the entire maximum reservation remains consumed.
    """
    import official_baseline_scoring_20261005 as scoring
    folder = Path(folder).resolve()
    assert argv == launch_args(plan,row,folder,resource_check)
    assert 'evaluator_dir' in row
    validate(plan)
    resource = official.resource_module()
    resource.check_resource(resource_check,Path(plan['kit']))
    started = time.monotonic()
    receipt = dict(complete=False,actual_calls=None,unconfirmed_calls=None,full_batch=False,
                   call_count_definition='durable client attempts; server receipt unknown',server_received_count=None)
    try:
        command = resource.owned_command(argv,folder,folder/'solve.log',plan['solve_supervisor_s'])
        save(folder/'SOLVE_COMMAND.json',command)
        assert not command['timeout'] and not command['launch_error'] and command['returncode'] == 0 and not command['remaining_live_group'], 'Solver supervision failure'
        solve = folder/'solve'; evaluator = Path(row['evaluator_dir'])
        original = scoring.eligible(solve,evaluator,row['arm'])
        assert original['input_sha256'] == row['input_hashes']
        receipt.update(actual_calls=original['client_request_attempts'],unconfirmed_calls=0)
        assert 1 <= receipt['actual_calls'] <= row['reserved_calls']
        save(folder/'SOLVE_BOUND.json',original)
        validate(plan)
        resource.check_resource(resource_check,Path(plan['kit']))
        judge_argv = ['/usr/bin/python3','-B',str(Path(scoring.__file__).resolve()),
            '--kit',plan['kit'],'--solve',str(solve),'--task',str(evaluator),'--arm',row['arm'],
            '--out',str(folder/'judge'),'--resource-check',str(resource_check)]
        command = resource.owned_command(judge_argv,folder,folder/'judge.log',plan['judge_supervisor_s'])
        save(folder/'JUDGE_COMMAND.json',command)
        assert not command['timeout'] and not command['launch_error'] and command['returncode'] == 0 and not command['remaining_live_group'], 'Judge supervision/environment failure'
        bound = json.loads((folder/'judge/BOUND_VERDICT.json').read_text())
        assert bound['arm'] == row['arm'] and bound['solution_sha256'] == original['solution_sha256']
        assert bound['solve_result_sha256'] == official.sha(solve/original['result_relative'])
        assert bound['task_files'] == row['evaluator_hashes']
        assert bound['verdict_sha256'] == official.sha(folder/'judge/verdict.json')
        assert bound['client_request_attempts'] == receipt['actual_calls']
        assert scoring.eligible(solve,evaluator,row['arm']) == original
        validate(plan)
        resource.check_resource(resource_check,Path(plan['kit']))
        receipt.update(complete=True,level=bound['verdict']['level'],coefficient=bound['verdict']['coefficient'],
                       solve_elapsed_s=json.loads((folder/'SOLVE_COMMAND.json').read_text())['elapsed_s'],
                       judge_elapsed_s=command['elapsed_s'])
    except Exception as error:
        receipt.update(error_type=type(error).__name__,error=str(error))
    receipt['end_to_end_s'] = time.monotonic()-started
    receipt['files'] = {str(p.relative_to(folder)):official.sha(p) for p in folder.rglob('*')
                        if p.is_file() and p.name != 'TERMINAL.json'}
    return receipt
