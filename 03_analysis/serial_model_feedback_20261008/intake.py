"""Once-only AMD prompt/interface intake; no grading inputs or model access."""
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
    for name, digest in plan['sources'].items():
        assert sha(root / name) == digest, name
    original = Path(plan['source_root'])
    assert sha(original / 'RUN_SPEC.json') == plan['spec_sha256']
    spec = json.loads((original / 'RUN_SPEC.json').read_text())
    assert sha(original / 'INPUT_MANIFEST.json') == spec['source_hashes']['INPUT_MANIFEST.json']
    inventory = json.loads((original / 'INPUT_MANIFEST.json').read_text())['input_sha256']
    tasks = spec['task_ids']
    assert len(tasks) == len(set(tasks)) == 156
    with (root / 'INTENT.json').open('x') as stream:
        json.dump(dict(plan_sha256=sha(root / 'PLAN.json'), model_max=0, eda_max=0), stream)
    import serial_feedback
    rows = []
    for task in tasks:
        directory = Path(plan['kit']) / 'bench/tasks_veval' / task
        inputs = {}
        for name in ('prompt.txt', 'interface.txt'):
            path = directory / name
            key = task + '/' + name
            assert path.exists() == (key in inventory)
            if path.exists():
                inputs[name] = sha(path)
                assert inputs[name] == inventory[key]
        prompt = (directory / 'prompt.txt').read_text(encoding='utf-8')
        interface = directory / 'interface.txt'
        if interface.is_file() and interface.read_text(encoding='utf-8').strip():
            prompt += '\n\nInterface:\n' + interface.read_text(encoding='utf-8')
        parsed = serial_feedback.parse(prompt)
        rows.append(dict(task=task, input_sha256=inputs, eligible=parsed is not None,
                         checks=parsed['checks'] if parsed else 0,
                         runtime_prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest()))
    for name, digest in plan['sources'].items():
        assert sha(root / name) == digest
    result = dict(complete=True, tasks=156, applicable=sum(row['eligible'] for row in rows),
                  rows=rows, model_calls=0, eda_calls=0, score_inputs_read=False,
                  sample_selection='All applicable prompt contracts; no outcome-based selection',
                  use='development', independent_unseen_tasks=0, scoring_admitted=False)
    with (root / 'RESULT.json').open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'rows'}))
