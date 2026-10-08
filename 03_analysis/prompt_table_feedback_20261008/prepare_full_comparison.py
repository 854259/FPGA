"""AMD-only full 156 x five A/P/B preparation; reuse unchanged qualified sources."""
import hashlib
import json
from pathlib import Path
import shutil
import sys


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


if __name__ == '__main__':
    assert sys.platform == 'linux' and sys.dont_write_bytecode
    root = Path(__file__).resolve().parent
    preparation = json.loads((root / 'PREPARATION_PLAN.json').read_text())
    assert sha(__file__) == preparation['prepare_sha256']
    assert not (root / 'PLAN.json').exists() and not (root / 'PREPARE_INTENT.json').exists()
    spec = json.loads((root / 'RUN_SPEC.json').read_text())
    for name, digest in spec['source_hashes'].items():
        assert sha(root / name) == digest, name
    parent = Path(preparation['parent_root'])
    parent_spec = json.loads((parent / 'RUN_SPEC.json').read_text())
    assert sha(parent / 'RUN_SPEC.json') == preparation['parent_spec_sha256']
    assert spec['source_hashes'] == parent_spec['source_hashes']
    for name, digest in parent_spec['source_hashes'].items():
        assert sha(parent / name) == digest, name
    result = Path(preparation['parent_terminal_result'])
    assert sha(result) == preparation['parent_terminal_sha256']
    result_data = json.loads(result.read_text())
    assert result_data['complete'] and result_data['generation_rows'] == 135
    intake = Path(preparation['intake'])
    assert sha(intake) == preparation['intake_sha256']
    inventory = json.loads(intake.read_text())
    assert inventory['complete'] and inventory['tasks'] == 156
    assert len(inventory['rows']) == len({v['task'] for v in inventory['rows']}) == 156
    assert preparation['model_max'] == 3900 and preparation['rows'] == 2340
    assert preparation['wall_s'] == 129600 and preparation['guard_s'] == 130000
    assert preparation['guard_s'] < preparation['slot_minutes'] * 60 - 60
    with (root / 'PREPARE_INTENT.json').open('x') as stream:
        json.dump(dict(preparation_sha256=sha(root / 'PREPARATION_PLAN.json'),
                       model_max=0, eda_max=0, old_controls_rerun=0), stream)
    sys.path.insert(0, str(root))
    import three_arm_queue_20261005 as queue
    kit = Path(preparation['kit'])
    tasks = []
    for row in inventory['rows']:
        source = kit / 'bench/tasks_veval' / row['task']
        target = root / 'inputs' / row['task']
        target.mkdir(parents=True, exist_ok=False)
        for name in ('prompt.txt', 'interface.txt'):
            assert (source / name).is_file() == (name in row['input_sha256'])
            if name in row['input_sha256']:
                assert sha(source / name) == row['input_sha256'][name]
                shutil.copyfile(source / name, target / name)
        tasks.append(dict(dataset='verilogeval_seen_development', task=row['task'],
                          family='unverified_family_dependence', use='development',
                          task_dir=str(target), hashes=row['input_sha256'],
                          evaluator_dir=str(source),
                          evaluator_hashes={p.name: sha(p) for p in source.iterdir() if p.is_file()}))
    sources = dict(root=str(root), model_feedback=True,
                   files={str(root / name): digest for name, digest in spec['source_hashes'].items()})
    for name in ('RUN_SPEC.json', 'PREPARATION_PLAN.json', 'prepare_full_comparison.py'):
        sources['files'][str(root / name)] = sha(root / name)
    plan = queue.build_plan(tasks, 5, sources, root / 'official_baseline_arm_20261005.py',
                            kit, preparation['model_max'], preparation['wall_s'])
    plan.update(execution_authorized=True, model_generated_rtl_only=True, independent_unseen=0,
                selection_policy=preparation['selection'],
                data_selection='All 156 original intake tasks, including all 147 parser abstentions; no outcome selection.',
                formal_adoption=False, full156=True,
                parent_terminal_sha256=preparation['parent_terminal_sha256'])
    queue.validate(plan)
    assert len(plan['rows']) == 2340 and plan['required_reserved_calls'] == 3900
    assert plan['unique_tasks'] == 156 and plan['samples'] == 5
    for arm in ('A', 'P', 'B'):
        row = next(v for v in plan['rows'] if v['arm'] == arm)
        argv = queue.launch_args(plan, row, root / 'route_only', root / 'unused_resource')
        if arm == 'B':
            assert argv[2] == str(root / 'official_baseline_arm_20261005.py') and '--arm' not in argv
        else:
            assert argv[argv.index('--arm') + 1] == ('C' if arm == 'A' else 'P')
            assert 'PAIRED_TASK_DIR=' + str(root / 'route_only/prompt_only') in argv
    with (root / 'PLAN.json').open('x') as stream:
        json.dump(plan, stream, indent=2)
        stream.write('\n')
    print(json.dumps(dict(prepared=True, rows=2340, tasks=156, samples=5,
                          plan_sha256=sha(root / 'PLAN.json'), model_max=3900,
                          model_calls=0, eda_calls=0, old_controls_rerun=0)))
