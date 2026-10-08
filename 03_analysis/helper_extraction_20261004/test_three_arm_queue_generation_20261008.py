"""One new queue integration control, reusing FAKE solve receipts; no solver/EDA."""
import copy
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


if __name__ == '__main__':
    main(Path(sys.argv[1]).resolve())
