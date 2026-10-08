"""AMD-only pure/three-flow qualification plus identical-inventory156 intake.

Reuses the frozen pure_flow_stage.stage once. The intake loop follows the
already-executed serial intake's task table, raw input hashes and exact runtime
prompt/interface assembly; it does not scan directories or select by outcomes.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import time
import traceback
import types
import urllib.request
from unittest.mock import patch

CORE_SHA = 'b5608f4d48e68a8c6f1fb40119226dd0685ade946abcdb29ef1e45fa7ae852ad'
CHECKER_SHA = 'e178d62a61bd279bb3dfcf4a17357a90e8a26b4537da83ba0f6e3714ae0a753a'
PURE_FLOW_SHA = '613acd289d49625730d107c744cde44ce1c2aec13474beb257dc6e49b3b6a0f5'
SERIAL_PLAN_SHA = '5ed73093dd455b738829e2b1f0b4c2df21ec76d2cc3397c1b64f4eb9c8eda0a7'
SERIAL_RESULT_SHA = '507d8b1af34dc0b132d1143a2bbdb60019bef49e7e261df967c1b3f25e18e97d'
SERIAL_INTAKE_SHA = '62f9bca6b1cf4205b0b5ba644188b904918c8c6f2523bafba639886edcab2957'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def forbidden(*args, **kwargs):
    raise RuntimeError('pure/flow/intake stage makes no real network or subprocess call')


def intake(root, out, original_serial_intake):
    """Only prompt/interface text and provenance metadata are read."""
    original_serial_intake = Path(original_serial_intake).resolve()
    prior_plan_path = original_serial_intake / 'PLAN.json'
    prior_result_path = original_serial_intake / 'RESULT.json'
    prior_intake_path = original_serial_intake / 'intake.py'
    for path, digest in ((prior_plan_path, SERIAL_PLAN_SHA), (prior_result_path, SERIAL_RESULT_SHA),
                         (prior_intake_path, SERIAL_INTAKE_SHA)):
        assert path.is_file() and not path.is_symlink() and sha(path) == digest
    plan, previous_result = read(prior_plan_path), read(prior_result_path)
    assert previous_result['complete'] is True and previous_result['tasks'] == 156
    assert previous_result['model_calls'] == previous_result['eda_calls'] == 0
    original = Path(plan['source_root'])
    assert sha(original / 'RUN_SPEC.json') == plan['spec_sha256']
    spec = read(original / 'RUN_SPEC.json')
    original_input_manifest = original / 'INPUT_MANIFEST.json'
    assert sha(original_input_manifest) == spec['source_hashes']['INPUT_MANIFEST.json']
    inventory = read(original_input_manifest)['input_sha256']
    tasks = spec['task_ids']
    assert len(tasks) == len(set(tasks)) == 156
    assert [row['task'] for row in previous_result['rows']] == tasks
    previous_rows = {row['task']: row for row in previous_result['rows']}
    import lemmings_feedback
    assert Path(lemmings_feedback.__file__).resolve() == root / 'lemmings_feedback.py'
    assert sha(lemmings_feedback.__file__) == CHECKER_SHA
    out.mkdir(parents=True, exist_ok=False)
    inputs_read, rows = {}, []
    # This assembly is deliberately the same as serial intake.py SHA62f9bca6.
    # No normalization, appended-interface stripping, glob or task-ID selection.
    for task in tasks:
        assert isinstance(task, str) and re.fullmatch(r'[A-Za-z0-9_]{1,128}', task)
        directory = Path(plan['kit']) / 'bench/tasks_veval' / task
        inputs = {}
        for name in ('prompt.txt', 'interface.txt'):
            path = directory / name
            key = task + '/' + name
            assert path.exists() == (key in inventory)
            if path.exists():
                assert path.is_file() and not path.is_symlink()
                inputs[name] = sha(path)
                assert inputs[name] == inventory[key]
                inputs_read[str(path)] = inputs[name]
        assert inputs == previous_rows[task]['input_sha256']
        prompt = (directory / 'prompt.txt').read_text(encoding='utf-8')
        interface = directory / 'interface.txt'
        if interface.is_file() and interface.read_text(encoding='utf-8').strip():
            prompt += '\n\nInterface:\n' + interface.read_text(encoding='utf-8')
        runtime_sha = hashlib.sha256(prompt.encode()).hexdigest()
        assert runtime_sha == previous_rows[task]['runtime_prompt_sha256']
        parsed = lemmings_feedback.parse(prompt)
        if parsed is not None:
            assert parsed['prompt_sha256'] == runtime_sha
            assert parsed['contract']['all_prompt_consumed'] is True
        rows.append(dict(task=task, input_sha256=inputs, eligible=parsed is not None,
                         checks=parsed['checks'] if parsed else 0,
                         runtime_prompt_sha256=runtime_sha,
                         contract=parsed['contract'] if parsed else None,
                         reason=None if parsed else 'outside_frozen_complete_prompt_grammar'))
    for path, digest in inputs_read.items():
        assert sha(path) == digest, path
    assert sha(prior_plan_path) == SERIAL_PLAN_SHA and sha(prior_result_path) == SERIAL_RESULT_SHA
    assert sha(prior_intake_path) == SERIAL_INTAKE_SHA
    assert sha(original / 'RUN_SPEC.json') == plan['spec_sha256']
    assert sha(original_input_manifest) == spec['source_hashes']['INPUT_MANIFEST.json']
    assert sha(lemmings_feedback.__file__) == CHECKER_SHA
    eligible = [row['task'] for row in rows if row['eligible']]
    result = dict(schema='lemmings_same_serial_inventory156_intake_v1', complete=True,
        tasks=156, applicable=len(eligible), eligible_tasks=eligible, rows=rows,
        original_serial_result_sha256=SERIAL_RESULT_SHA, original_serial_plan_sha256=SERIAL_PLAN_SHA,
        original_serial_intake_sha256=SERIAL_INTAKE_SHA,
        task_inventory_source_root=str(original), task_spec_sha256=plan['spec_sha256'],
        input_manifest_sha256=spec['source_hashes']['INPUT_MANIFEST.json'],
        exact_runtime_prompt_sha_equal_to_prior_serial_intake=True,
        parser_sha256=CHECKER_SHA, model_calls=0, eda_calls=0, score_inputs_read=False,
        sample_selection='All applicable complete prompt contracts; no outcome-based selection',
        use='development', independent_unseen_tasks=0, native_qualification_claimed=False,
        scoring_admitted=False)
    save(out / 'INTAKE_RESULT.json', result)
    return result


def stage(args):
    assert sys.platform == 'linux' and sys.dont_write_bytecode
    started = time.monotonic()
    root, out = args.root.resolve(), args.out.resolve()
    assert root == Path(__file__).resolve().parent
    assert out != root and out.is_relative_to(root) and not out.exists()
    out.mkdir(parents=True, exist_ok=False)
    manifest_path = root / 'SOURCE_MANIFEST.json'
    reports, failure, source_failure = {}, None, None

    def frozen():
        assert sha(manifest_path) == args.source_manifest_sha256
        sources = read(manifest_path)
        assert isinstance(sources, dict) and sources
        assert sources['pure_intake_stage.py'] == sha(__file__)
        assert sources['pure_flow_stage.py'] == PURE_FLOW_SHA
        assert sources['IMPLEMENTATION_MANIFEST.json'] == CORE_SHA
        assert sources['lemmings_feedback.py'] == CHECKER_SHA
        core = read(root / 'IMPLEMENTATION_MANIFEST.json')
        for name, record in core['files'].items():
            assert sources[name] == record['sha256']
        for name, digest in sources.items():
            path = root / name
            assert not Path(name).is_absolute() and '..' not in Path(name).parts
            assert path.resolve().is_relative_to(root) and not path.is_symlink()
            assert sha(path) == digest, name

    try:
        frozen()
        save(out / 'PURE_INTAKE_INTENT.json', dict(real_model_max=0, real_eda_max=0,
             source_manifest_sha256=args.source_manifest_sha256, implementation_manifest_sha256=CORE_SHA,
             original_pure_flow_stage_sha256=PURE_FLOW_SHA, original_pure_methods=7, original_flows=3,
             task_count=156, serial_intake_root=str(args.serial_intake_root.resolve()),
             serial_result_sha256=SERIAL_RESULT_SHA, serial_plan_sha256=SERIAL_PLAN_SHA,
             no_native_qualification=True, retries=0, caller_bounded_cap_seconds=40))
        sys.path.insert(0, str(root))
        with patch.object(urllib.request, 'urlopen', forbidden), patch.object(subprocess, 'run', forbidden), \
             patch.object(subprocess, 'Popen', forbidden):
            original_stage = load('lemmings_original_pure_flow_stage', root / 'pure_flow_stage.py')
            status = original_stage.stage(types.SimpleNamespace(root=root, out=out / 'pure_flow',
                                         source_manifest_sha256=args.source_manifest_sha256))
            pure_path = out / 'pure_flow/PURE_FLOW_RESULT.json'
            reports['pure_flow'] = read(pure_path)
            assert status == 0 and reports['pure_flow']['complete'] and reports['pure_flow']['passed']
            assert reports['pure_flow']['real_model_calls'] == reports['pure_flow']['real_eda_commands'] == 0
            assert reports['pure_flow']['implementation_manifest_sha256'] == CORE_SHA
            assert reports['pure_flow']['source_manifest_sha256'] == args.source_manifest_sha256
            frozen()
            reports['intake'] = intake(root, out / 'intake', args.serial_intake_root)
            frozen()
    except BaseException as error:
        failure = dict(type=type(error).__name__, message=str(error), traceback=traceback.format_exc())
    try:
        frozen()
    except BaseException as error:
        source_failure = dict(type=type(error).__name__, message=str(error))
    result = dict(schema='lemmings_pure_flow_intake_stage_v1', complete=True,
        passed=failure is None and source_failure is None, reports=reports, error=failure,
        source_error=source_failure, real_model_calls=0, real_eda_commands=0,
        source_manifest_sha256=args.source_manifest_sha256, implementation_manifest_sha256=CORE_SHA,
        eligible_tasks=reports.get('intake', {}).get('eligible_tasks'),
        intake_complete=reports.get('intake', {}).get('complete', False),
        native_qualified=False, scoring_admitted=False, accuracy_measured=False,
        elapsed_s=time.monotonic() - started)
    save(out / 'PURE_FLOW_INTAKE_RESULT.json', result)
    print(json.dumps(dict(passed=result['passed'], eligible_tasks=result['eligible_tasks'],
                          intake_complete=result['intake_complete'], error=failure)))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--source-manifest-sha256', required=True)
    parser.add_argument('--serial-intake-root', type=Path, required=True)
    raise SystemExit(stage(parser.parse_args()))
