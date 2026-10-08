"""AMD-only applicability check of unchanged feedback on frozen RTLLM prompts."""
import hashlib
import json
from pathlib import Path
import sys


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


if __name__ == '__main__':
    assert sys.platform == 'linux' and sys.dont_write_bytecode
    root = Path(__file__).resolve().parent
    plan = json.loads((root / 'PLAN.json').read_text())
    assert sha(root / 'intake_rtllm.py') == plan['intake_sha256']
    assert plan['model_max'] == plan['eda_max'] == 0
    assert sha(plan['historical_plan']) == plan['historical_plan_sha256']
    historical = json.loads(Path(plan['historical_plan']).read_text())
    tasks = [r for r in historical['rows'] if r['sample'] == 0 and r['arm'] == 'A']
    assert len(tasks) == len({r['task'] for r in tasks}) == 29
    source = Path(plan['source_root'])
    assert sha(source / 'RUN_SPEC.json') == plan['source_spec_sha256']
    spec = json.loads((source / 'RUN_SPEC.json').read_text())
    for name, digest in plan['parser_sources'].items():
        assert spec['source_hashes'][name] == digest
        assert sha(source / name) == sha(root / name) == digest
    with (root / 'INTENT.json').open('x') as stream:
        json.dump(dict(plan_sha256=sha(root / 'PLAN.json'), model_max=0, eda_max=0), stream)
    import table_feedback
    rows = []
    for task in tasks:
        directory = Path(task['task_dir'])
        hashes = task['input_hashes']
        assert 'prompt.txt' in hashes and set(hashes) <= {'prompt.txt', 'interface.txt'}
        for name, digest in hashes.items():
            assert sha(directory / name) == digest
        assert (directory / 'interface.txt').exists() == ('interface.txt' in hashes)
        prompt = (directory / 'prompt.txt').read_text(encoding='utf-8')
        if 'interface.txt' in hashes:
            interface = (directory / 'interface.txt').read_text(encoding='utf-8')
            if interface.strip():
                prompt += '\n\nInterface:\n' + interface
        parsed = table_feedback.parse(prompt)
        rows.append(dict(task=task['task'], input_sha256=hashes,
                         runtime_prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),
                         eligible=parsed is not None, checks=parsed['checks'] if parsed else 0))
    assert sha(plan['historical_plan']) == plan['historical_plan_sha256']
    for name, digest in plan['parser_sources'].items():
        assert sha(source / name) == sha(root / name) == digest
    result = dict(complete=True, tasks=29, applicable=sum(r['eligible'] for r in rows),
                  rows=rows, model_calls=0, eda_calls=0, scoring_inputs_read=False,
                  selection='All 29 previously frozen finite-domain prompt inputs; no outcomes',
                  scope='RTLLM development applicability only; not accuracy or official scoring',
                  remaining_specification_blocked_tasks=15, independent_unseen_tasks=0)
    with (root / 'RESULT.json').open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'rows'}))
