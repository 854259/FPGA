"""AMD-only prompt applicability; reuse old table abstentions, never score RTL."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import socket
import subprocess
import sys
import urllib.request
from unittest.mock import patch


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_bound(item):
    assert sha(item['path']) == item['sha256']
    return json.loads(Path(item['path']).read_bytes())


def forbidden(*args, **kwargs):
    raise RuntimeError('Prompt intake cannot start processes or network requests')


if __name__ == '__main__':
    assert sys.platform == 'linux' and sys.dont_write_bytecode
    root = Path(__file__).resolve().parent
    plan_path = root / 'PLAN.json'
    plan_sha = sha(plan_path)
    plan = json.loads(plan_path.read_bytes())
    assert sha(__file__) == plan['intake_sha256']
    assert plan['model_max'] == plan['eda_max'] == plan['fifo_max'] == 0
    historical = read_bound(plan['historical_plan'])
    prior_plan = read_bound(plan['prior_table_plan'])
    prior = read_bound(plan['prior_table_result'])
    manifest = read_bound(plan['qualified_manifest'])
    qualification = read_bound(plan['qualified_result'])
    receipt = read_bound(plan['qualified_receipt'])
    assert qualification['passed'] and receipt['passed'] and receipt['protected_held']
    assert receipt['result_sha256'] == plan['qualified_result']['sha256']
    assert prior_plan['historical_plan_sha256'] == plan['historical_plan']['sha256']
    assert prior_plan['parser_sources']['table_feedback.py'] == manifest['table_feedback.py']
    assert prior['complete'] and prior['tasks'] == 29 and prior['applicable'] == 0
    previous = {row['task']: row for row in prior['rows']}
    assert len(previous) == len(prior['rows']) == 29
    tasks = [row for row in historical['rows'] if row['sample'] == 0 and row['arm'] == 'A']
    assert len(tasks) == len({row['task'] for row in tasks}) == 29
    assert {row['task'] for row in tasks} == set(previous)
    source = Path(plan['source_root'])
    for name, digest in plan['parser_sources'].items():
        assert manifest[name] == digest == sha(source / name) == sha(root / name)
    with (root / 'INTENT.json').open('x') as stream:
        json.dump(dict(plan_sha256=plan_sha, model_max=0, eda_max=0, fifo_max=0), stream)
    rows = []
    with patch.object(socket, 'socket', forbidden), patch.object(subprocess, 'Popen', forbidden), \
            patch.object(subprocess, 'run', forbidden), patch.object(urllib.request, 'urlopen', forbidden):
        import edge_dispatch
        import semantic_review
        for task in tasks:
            directory = Path(task['task_dir'])
            hashes = task['input_hashes']
            old = previous[task['task']]
            assert old['eligible'] is False and old['input_sha256'] == hashes
            assert 'prompt.txt' in hashes and set(hashes) <= {'prompt.txt', 'interface.txt'}
            assert (directory / 'interface.txt').exists() == ('interface.txt' in hashes)
            assert all(sha(directory / name) == digest for name, digest in hashes.items())
            prompt = (directory / 'prompt.txt').read_text(encoding='utf-8')
            interface = (directory / 'interface.txt').read_text(encoding='utf-8') if 'interface.txt' in hashes else ''
            combined = prompt + ('\n\nInterface:\n' + interface if interface.strip() else '')
            combined_sha = hashlib.sha256(combined.encode()).hexdigest()
            assert combined_sha == old['runtime_prompt_sha256']
            contract = edge_dispatch.parse(combined)
            hint = semantic_review.hint(prompt, interface, contract['status'], True, 0)
            rows.append(dict(task=task['task'], input_sha256=hashes,
                             runtime_prompt_sha256=combined_sha, original_table_abstention_reused=True,
                             original_contract_status=contract['status'], hint=hint,
                             potentially_eligible=hint['status'] == 'review_requested'))
            assert all(sha(directory / name) == digest for name, digest in hashes.items())
    assert sha(plan_path) == plan_sha and sha(__file__) == plan['intake_sha256']
    for key in ('historical_plan', 'prior_table_plan', 'prior_table_result',
                'qualified_manifest', 'qualified_result', 'qualified_receipt'):
        assert sha(plan[key]['path']) == plan[key]['sha256']
    assert all(sha(root / name) == sha(source / name) == digest
               for name, digest in plan['parser_sources'].items())
    result = dict(complete=True, tasks=29, potentially_eligible=sum(r['potentially_eligible'] for r in rows),
                  reasons=dict(Counter(r['hint']['reason'] for r in rows)),
                  contract_statuses=dict(Counter(r['original_contract_status'] for r in rows)), rows=rows,
                  plan_sha256=plan_sha, source_sha256=plan['intake_sha256'], model_calls=0, eda_calls=0,
                  fifo_calls=0, previous_table_intake_reexecuted=False, scoring_inputs_read=False,
                  compile_pass_assumed_for_applicability=True, actual_compile_or_feedback_trigger_verified=False,
                  selection='All 29 existing finite-domain development prompts; no outputs used for selection',
                  scope='Potential prompt applicability only; not accuracy, native qualification or official scoring',
                  remaining_specification_blocked_tasks=15, independent_unseen_tasks=0,
                  real_model_benefit_and_wall_time_pending=True, full_goal_complete=False)
    with (root / 'RESULT.json').open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'rows'}))
