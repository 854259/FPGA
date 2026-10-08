"""One new queue integration control, reusing FAKE solve receipts; no solver/EDA."""
import copy
import fcntl
import json
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

import official_baseline_arm_20261005 as official
import three_arm_queue_20261005 as queue


def main(root):
    sources = json.loads((root/'SOURCES.json').read_text())
    folder = root/'case_A_table'
    task = root/'queue_input'; task.mkdir()
    (task/'prompt.txt').write_bytes((folder/'prompt_only/prompt.txt').read_bytes())
    queue.save(task/'task.json', dict(task_id='FAKE_NEW_QUEUE_CONTROL'))
    inputs = {'prompt.txt': official.sha(task/'prompt.txt')}
    files = {p.name: official.sha(p) for p in task.iterdir()}
    tasks = [dict(dataset='synthetic', task='FAKE_NEW_QUEUE_CONTROL', family='synthetic_table',
                  use='development', task_dir=str(task), hashes=inputs,
                  evaluator_dir=str(task), evaluator_hashes=files)]
    plan = queue.build_plan(tasks, 1, sources, root/'official_baseline_arm_20261005.py',
                            '/workspace/team/tasks/autodl-rtl-kit/project', 5, 2010)
    queue.validate(plan)
    argv = {r['arm']: queue.launch_args(plan, r, folder, root/'FAKE_RESOURCE.json') for r in plan['rows']}
    assert str(root/'official_baseline_arm_20261005.py') in argv['B']
    assert '--source-root' not in argv['B'] and 'worker' not in argv['B']
    for label in ('A', 'P'):
        assert argv[label][argv[label].index('--source-root')+1] == sources['generation_arms'][label]['root']
        assert argv[label][argv[label].index('--arm')+1] == label
    bad = copy.deepcopy(plan)
    bad['sources']['generation_arms']['A'] = bad['sources']['generation_arms']['P']
    try:
        queue.validate(bad)
    except AssertionError:
        pass
    else:
        raise AssertionError('Swapped archived source accepted')
    calls = []
    result_sha = official.sha(folder/'solve/worker_result.json')
    solution_sha = official.sha(folder/'solve/solution.v')

    def fake_command(command, cwd, log, seconds):
        calls.append(command)
        Path(log).write_text('FAKE_QUEUE_TRANSPORT_NO_SOLVER_NO_JUDGE\n')
        if len(calls) == 2:
            assert '--generation-source' in command
            assert command[command.index('--generation-source')+1] == sources['generation_arms']['A']['root']
            judge = folder/'judge'; judge.mkdir()
            queue.save(judge/'verdict.json', dict(level=3, coefficient=1, fixture='FAKE_NOT_SCORE'))
            queue.save(judge/'BOUND_VERDICT.json', dict(arm='A', solution_sha256=solution_sha,
                solve_result_sha256=result_sha, task_files=files,
                verdict_sha256=official.sha(judge/'verdict.json'), client_request_attempts=0,
                verdict=dict(level=3, coefficient=1, fixture='FAKE_NOT_SCORE')))
        return dict(timeout=False, launch_error=None, returncode=0, remaining_live_group=[],
                    elapsed_s=0, fixture='FAKE_NOT_PROCESS_EVIDENCE')

    fake = SimpleNamespace(check_resource=lambda *args: None, owned_command=fake_command)
    row = next(r for r in plan['rows'] if r['arm'] == 'A')
    with patch.object(official, 'resource_module', return_value=fake), \
         patch('urllib.request.urlopen', side_effect=AssertionError('No HTTP permitted')):
        receipt = queue.execute_row(plan, argv['A'], row, folder, root/'FAKE_RESOURCE.json')
    assert receipt['complete'] and receipt['actual_calls'] == receipt['unconfirmed_calls'] == 0, receipt
    assert len(calls) == 2 and official.sha(folder/'solve/worker_result.json') == result_sha
    assert row['reserved_calls'] == 2 and plan['required_reserved_calls'] == plan['max_calls'] == 5
    queue.save(root/'QUEUE_CONTROL_RESULT.json', dict(passed=True,
        checks=['three_distinct_entries', 'B_original_entry', 'swapped_source_rejected',
                'zero_call_reaches_bound_judge', 'raw_result_preserved', 'maximum_reservation_unchanged'],
        fixture='FAKE_NO_SOLVER_NO_JUDGE', new_model_requests=0, new_eda_commands=0))


def runner_controls(root):
    """New driver only: real reservations/seals, FAKE row results, no solver/EDA."""
    prior = Path('/workspace/team/runs/fpga_teammate/three_arm_generation_routes_20261008_v1')
    sources = json.loads((prior/'SOURCES.json').read_text())
    sources['root'] = str(root)
    entry = root/'three_arm_generation_20261008.py'
    sources['files'][str(entry)] = official.sha(entry)
    task = root/'runner_input'; task.mkdir()
    (task/'prompt.txt').write_text('FAKE driver control; no RTL evaluation.\n')
    tasks = [dict(dataset='synthetic', task='FAKE_RUNNER', family='driver_control',
                  use='development', task_dir=str(task),
                  hashes={'prompt.txt': official.sha(task/'prompt.txt')})]
    base = queue.build_plan(tasks, 1, sources, root/'official_baseline_arm_20261005.py',
                            '/workspace/team/tasks/autodl-rtl-kit/project', 5, 10000)
    base['execution_authorized'] = True
    base['synthetic_control'] = True
    calls, checks = [], []
    mode = {'value': 'success'}

    def fake_row(plan, argv, row, folder, resource_check):
        calls.append((str(folder), row['arm']))
        (folder/'FAKE_RESULT.txt').write_text('FAKE_NO_SOLVER_NO_JUDGE\n')
        if mode['value'] == 'crash':
            raise RuntimeError('FAKE_CRASH_AFTER_DURABLE_RESERVATION')
        return dict(complete=mode['value'] != 'unconfirmed',
            actual_calls=1 if row['arm'] == 'B' else 0,
            unconfirmed_calls=int(mode['value'] == 'unconfirmed'),
            fixture='FAKE_NOT_SCORE', files={
                'FAKE_RESULT.txt': official.sha(folder/'FAKE_RESULT.txt')})

    def freeze(name, **changes):
        plan = copy.deepcopy(base); plan.update(changes)
        path = root/(name+'.json'); queue.save(path, plan)
        return path, official.sha(path), root/name

    def run(frozen):
        return queue.run_plan(*frozen, root/'FAKE_RESOURCE.json')

    def rejected(frozen, message):
        before = len(calls)
        try:
            run(frozen)
        except (AssertionError, RuntimeError, BlockingIOError) as error:
            assert message in str(error), (message, str(error))
        else:
            raise AssertionError('Invalid queue accepted: '+message)
        assert len(calls) == before

    fake = SimpleNamespace(check_resource=lambda *args, **kwargs: None)
    with patch.object(official, 'resource_module', return_value=fake), \
         patch.object(queue, 'execute_row', side_effect=fake_row), \
         patch('urllib.request.urlopen', side_effect=AssertionError('No HTTP permitted')):
        done = freeze('complete')
        assert run(done) == dict(complete=True, rows=3, reserved_calls=5, full_batch=False)
        assert [arm for _, arm in calls] == ['A', 'P', 'B']
        count = len(calls); assert run(done)['complete'] and len(calls) == count
        assert len(list(done[2].glob('row_*/SEALED.json'))) == 3
        checks.append('complete_three_arms_and_repeat_without_dispatch')

        draft = freeze('draft', execution_authorized=False)
        rejected(draft, 'Preparation plan cannot dispatch'); assert not draft[2].exists()
        changed = freeze('changed')
        rejected((changed[0], '0'*64, changed[2]), 'Frozen plan changed')
        assert not changed[2].exists()
        checks.append('draft_and_wrong_plan_hash_rejected_before_output')

        locked = freeze('locked'); locked[2].mkdir()
        with (locked[2]/'runner.lock').open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            rejected(locked, 'Resource temporarily unavailable')
        assert not (locked[2]/'QUEUE.json').exists()
        checks.append('second_driver_cannot_enter')

        for state, message in [('crash', 'Unfinished reservation'),
                               ('unconfirmed', 'Unconfirmed/failed row')]:
            frozen = freeze(state); mode['value'] = state; before = len(calls)
            try:
                run(frozen)
            except (AssertionError, RuntimeError):
                pass
            else:
                raise AssertionError('Failed row did not stop')
            assert len(calls) == before+1
            assert len(list(frozen[2].glob('row_*'))) == 1
            start_sha = official.sha(frozen[2]/'row_000000/STARTED.json')
            mode['value'] = 'success'; rejected(frozen, message)
            assert official.sha(frozen[2]/'row_000000/STARTED.json') == start_sha
            checks.append(state+'_stops_next_row_and_never_retries')

        capped = freeze('capped', max_calls=2); before = len(calls)
        try:
            run(capped)
        except AssertionError as error:
            assert 'Call reservation budget exhausted' in str(error)
        else:
            raise AssertionError('Zero actual calls incorrectly refunded maximum reservation')
        assert len(calls) == before+1
        rejected(capped, 'Call reservation budget exhausted')
        checks.append('zero_calls_do_not_refund_frozen_reservation')
        timed = freeze('timed', wall_seconds=669)
        rejected(timed, 'Wall budget cannot cover next solve and judge')
        assert not list(timed[2].glob('row_*'))
        checks.append('whole_row_time_reserved_before_dispatch')
    result = dict(passed=True, checks=checks, fake_row_executions=len(calls),
        model_calls=0, eda_commands=0, fifo_submissions=0,
        scope='Remote driver only; real queue reservations and ZIP seals; all row results FAKE',
        full_batch=False)
    queue.save(root/'RUNNER_CONTROL_RESULT.json', result)
    print(json.dumps(result))


if __name__ == '__main__':
    root = Path(sys.argv[1]).resolve()
    if sys.argv[2:] == ['--runner-controls']:
        runner_controls(root)
    else:
        assert not sys.argv[2:]
        main(root)
