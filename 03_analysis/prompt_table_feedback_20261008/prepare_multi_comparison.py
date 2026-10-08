"""AMD-only paired feedback freeze and conditional start after native133.

A is the archived single-counterexample model policy, P the multi-point policy,
B the unchanged official baseline. All nine original intake tasks enter, five
samples each. No source, input or selection decision depends on new scores.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(name, value):
    with (ROOT / name).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2)
        stream.write('\n')


def routing_controls(spec):
    import worker
    base = worker.baseline_worker
    old = SimpleNamespace(check=lambda *a: 'single')
    calls = []

    def fake_worker(args, paired):
        calls.append(args.arm)
        return base.functional_feedback('synthetic', 'model_fixture', ROOT, 0,
                                        paired, 'synthetic', candidate=True)

    fallback = lambda *a, **k: 'fallback'
    with patch.object(base, 'run_worker', fake_worker), \
            patch.object(base, 'functional_feedback', fallback), \
            patch.object(base, 'load', return_value=old), \
            patch.object(worker.table_feedback, 'check', return_value='multiple'):
        assert worker.run_selected(SimpleNamespace(arm='C'), None, spec) == 'single'
        assert base.functional_feedback is fallback
        assert worker.run_selected(SimpleNamespace(arm='P'), None, spec) == 'multiple'
        assert base.functional_feedback is fallback
        old.check = lambda *a: None
        assert worker.run_selected(SimpleNamespace(arm='C'), None, spec) == 'fallback'
        with patch.object(old, 'check', side_effect=RuntimeError('synthetic stop')):
            try:
                worker.run_selected(SimpleNamespace(arm='C'), None, spec)
            except RuntimeError as exc:
                assert str(exc) == 'synthetic stop'
            else:
                raise AssertionError('feedback error was swallowed')
        assert base.functional_feedback is fallback
        assert worker.run_selected(SimpleNamespace(arm='C'), None, {}) == 'fallback'
    assert calls == ['C', 'P', 'C', 'C', 'C']
    return dict(passed=True, cases=['A_single', 'P_multiple', 'A_abstention_fallback',
                'exception_restores_callback', 'historical_C_unchanged'],
                real_model_calls=0, eda_calls=0, old_controls_rerun=0)


def prepare(config):
    import three_arm_queue_20261005 as queue
    spec = json.loads((ROOT / 'RUN_SPEC.json').read_text())
    parent = Path(config['parent_root'])
    assert sha(parent / 'PLAN.json') == config['parent_plan_sha256']
    prior = json.loads((parent / 'PLAN.json').read_text())
    parent_spec = json.loads((parent / 'RUN_SPEC.json').read_text())
    assert sha(parent / 'RUN_SPEC.json') == config['parent_spec_sha256']
    for name, digest in spec['source_hashes'].items():
        assert sha(ROOT / name) == digest, name
    assert spec['control_feedback_sha256'] == parent_spec['source_hashes']['table_feedback.py']
    assert sha(ROOT / 'control_feedback.py') == spec['control_feedback_sha256']
    for name, digest in parent_spec['source_hashes'].items():
        assert sha(parent / name) == digest, name
        if name not in ('worker.py', 'table_feedback.py'):
            assert spec['source_hashes'][name] == digest
    assert config['model_max'] == 225 and config['samples'] == 5
    assert (config['wall_s'], config['guard_s'], config['slot_minutes']) == (43200, 43600, 740)
    save('PREPARE_INTENT.json', dict(config_sha256=sha(ROOT / 'PREPARATION_PLAN.json'),
         model_max=0, eda_max=0))
    controls = routing_controls(spec)
    tasks = {}
    for row in prior['rows']:
        if row['task'] in tasks:
            continue
        target = ROOT / 'inputs' / row['task']
        target.mkdir(parents=True, exist_ok=False)
        for name, digest in row['input_hashes'].items():
            source = Path(row['task_dir']) / name
            assert sha(source) == digest
            shutil.copyfile(source, target / name)
        tasks[row['task']] = dict(dataset=row['dataset'], task=row['task'],
            family=row['family'], use='development', task_dir=str(target),
            hashes=row['input_hashes'], evaluator_dir=row['evaluator_dir'],
            evaluator_hashes=row['evaluator_hashes'])
    assert len(tasks) == 9 and prior['unique_tasks'] == 9 and prior['samples'] == 5
    files = {str(ROOT / name): digest for name, digest in spec['source_hashes'].items()}
    for name in ('RUN_SPEC.json', 'PREPARATION_PLAN.json', 'prepare_multi_comparison.py'):
        files[str(ROOT / name)] = sha(ROOT / name)
    plan = queue.build_plan(list(tasks.values()), 5,
        dict(root=str(ROOT), model_feedback=True, files=files),
        ROOT / 'official_baseline_arm_20261005.py', prior['kit'], 225, 43200)
    plan.update(execution_authorized=True, model_generated_rtl_only=True,
        independent_unseen=0, full156=False, formal_adoption=False,
        selection_policy=config['selection'], prerequisite=config['prerequisite'],
        arm_meanings=dict(A='archived single-point table feedback',
                         P='multi-point table feedback', B='original official baseline'),
        data_selection='All nine original prompt-only intake tasks; all are seen development. No score selection.')
    queue.validate(plan)
    assert len(plan['rows']) == 135 and plan['required_reserved_calls'] == 225
    for arm in ('A', 'P', 'B'):
        row = next(r for r in plan['rows'] if r['arm'] == arm)
        argv = queue.launch_args(plan, row, ROOT / 'route_only', ROOT / 'unused_resource')
        if arm == 'B':
            assert argv[2] == str(ROOT / 'official_baseline_arm_20261005.py') and '--arm' not in argv
        else:
            assert argv[argv.index('--arm') + 1] == ('C' if arm == 'A' else 'P')
    save('ROUTING_RESULT.json', controls)
    save('PLAN.json', plan)
    print(json.dumps(dict(prepared=True, plan_sha256=sha(ROOT / 'PLAN.json'),
         rows=135, model_max=225, model_calls=0, eda_calls=0, native_prerequisite_pending=True)))


def prerequisite(required):
    root = Path(required['root'])
    assert sha(root / 'PLAN.json') == required['plan_sha256']
    assert sha(root / 'SOURCE_MANIFEST.json') == required['manifest_sha256']
    for name, digest in json.loads((root / 'SOURCE_MANIFEST.json').read_text()).items():
        assert sha(root / name) == digest
    ticket = json.loads((Path('/workspace/team/task_fifo/tickets') /
                         ('%08d.json' % required['ticket'])).read_text())
    assert ticket['cwd'] == str(root) and ticket['state'] == 'completed'
    native = json.loads((root / 'NATIVE_RESULT.json').read_text())
    assert native['complete'] and native['passed'] and native['error'] is None
    assert native['model_calls'] == 0 and native['eda_calls'] == 3
    assert len(native['native_commands']) == 3
    for rec in native['native_commands']:
        assert rec['normal_completion'] and rec['returncode'] == 0
        assert rec['exec_confirmed'] and rec['leader_reaped'] and not rec['remaining_group']
    external = json.loads((root / 'external/EXTERNAL_PROCESS_RECEIPT.json').read_text())
    guard = json.loads((root / 'guard/status.json').read_text())
    assert external['passed'] and guard['complete'] and guard['passed']
    assert guard['owned_cleanup']['verified'] and guard['own_slot_released']
    return {name: sha(root / name) for name in ('NATIVE_RESULT.json',
            'external/EXTERNAL_PROCESS_RECEIPT.json', 'guard/status.json')}


if __name__ == '__main__':
    assert sys.platform == 'linux' and sys.dont_write_bytecode
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('prepare', 'run'))
    parser.add_argument('--plan-sha256')
    parser.add_argument('--resource-check', type=Path)
    args = parser.parse_args()
    config = json.loads((ROOT / 'PREPARATION_PLAN.json').read_text())
    assert sha(__file__) == config['prepare_sha256']
    if args.mode == 'prepare':
        prepare(config)
    else:
        assert args.resource_check is not None and sha(ROOT / 'PLAN.json') == args.plan_sha256
        import three_arm_queue_20261005 as queue
        plan = json.loads((ROOT / 'PLAN.json').read_text())
        queue.validate(plan)
        save('CONDITIONAL_START_INTENT.json', dict(plan_sha256=args.plan_sha256))
        evidence = prerequisite(plan['prerequisite'])
        save('PREREQUISITE_PASSED.json', dict(files=evidence, model_calls_before_check=0))
        print(json.dumps(queue.run_plan(ROOT / 'PLAN.json', args.plan_sha256,
                                       ROOT / 'queue', args.resource_check)))
