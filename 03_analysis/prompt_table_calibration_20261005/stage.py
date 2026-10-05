"""UNFROZEN 25-control/75-command research calibration; guard admission required."""
import argparse
import ctypes
import importlib.util
import json
import os
import shutil
import sys
import time
from pathlib import Path

import controls as c

ROOT = Path(__file__).resolve().parent


def file_sha(path):
    return c.sha(Path(path).read_bytes())


def environment_sha():
    return c.sha(json.dumps(dict(os.environ), sort_keys=True, separators=(',', ':')).encode())


def validate_environment(spec):
    # Direct reuse of phase pilot validate_environment checks, with frozen hashes.
    tools = Path(spec['vivado_bin']).resolve()
    stub = Path(spec['udev_stub']).resolve()
    c.require(Path(os.environ.get('VIVADO_BIN', '')).resolve() == tools, 'VIVADO_BIN not pinned')
    c.require(str(stub) in os.environ.get('LD_LIBRARY_PATH', '').split(os.pathsep) and stub.is_dir(), 'scoped udev stub missing')
    checked = {}
    for name in ('xvlog', 'xelab', 'xsim', 'vivado'):
        found = shutil.which(name)
        c.require(found and Path(found).resolve() == (tools / name).resolve() and os.access(found, os.X_OK), 'wrong/non-executable tool: ' + name)
        checked[name] = {'path': str(Path(found).resolve()), 'sha256': file_sha(found)}
    c.require(checked == spec['compiler_tools'], 'compiler entry bytes changed')
    actual_stub = {p.relative_to(stub).as_posix(): file_sha(p) for p in stub.rglob('*') if p.is_file()}
    c.require(actual_stub == spec['udev_files'] and actual_stub, 'compiler stub bytes changed')
    compiler_env = {key: os.environ.get(key) for key in ('PATH', 'VIVADO_BIN', 'LD_LIBRARY_PATH')}
    c.require(compiler_env == spec['compiler_env'], 'compiler environment changed')
    return {'verified': True, 'tools': checked, 'udev_files': actual_stub, 'compiler_env': compiler_env,
            'complete_inherited_environment_sha256': environment_sha(), 'model_calls': 0, 'eda_calls': 0}


def frozen(root, kit):
    root, kit = Path(root), Path(kit)
    c.require((root / 'RUN_SPEC.json').is_file(), 'RUN_SPEC absent: no native invocation permitted')
    spec = c.read(root / 'RUN_SPEC.json')
    c.require(all(type(spec[key]) is int for key in ('model_requests_max', 'controls_max', 'commands_per_tool')), 'integer budget types required')
    c.require(spec['schema'] == 'prompt_table_generated_calibration_frozen_v1'
              and spec['cloud_root'] == str(root) and spec['kit'] == str(kit)
              and spec['model_requests_max'] == 0 and spec['controls_max'] == 25
              and spec['commands_per_tool'] == 25, 'fixed frozen identity/budget required')
    private, prepared = c.validate_assets(root)
    bindings = c.read(root / 'raw_evidence/DEPENDENCY_BINDINGS.json')
    c.require(spec['dependencies_cloud'] == bindings['dependencies_cloud']
              and spec['dependency_hashes'] == bindings['dependency_hashes']
              and spec['compiler_tools'] == bindings['environment']['tools']
              and spec['vivado_bin'] == bindings['environment']['vivado_bin']
              and spec['udev_stub'] == bindings['environment']['udev_stub']
              and spec['protected'] == bindings['protected'], 'reviewed dependency/compiler/protected binding')
    c.require(set(spec['source_hashes']) == set(c.source_paths(private)), 'exact frozen source inventory required')
    for name, digest in spec['source_hashes'].items():
        c.require(file_sha(c.contained(root, name)) == digest, 'frozen source bytes changed: ' + name)
    for name, digest in spec['dependency_hashes'].items():
        c.require(file_sha(c.contained(spec['dependencies_cloud'], name)) == digest, 'frozen dependency changed')
    return spec, prepared


def inventory(out):
    """Conservative whole-results accounting; pending/unknown receipts cannot pass."""
    out = Path(out)
    expected = {(label, tool): f'{label}/native_calls/{i:02d}_{tool}.json'
                for label in c.ORDER for i, tool in enumerate(c.TOOLS)}
    inverse = {name: key for key, name in expected.items()}
    grouped, errors = {}, []
    for path in out.rglob('*'):
        name = path.relative_to(out).as_posix()
        if path.is_symlink() and 'native_calls' in path.parts:
            errors.append('linked native evidence: ' + name)
            continue
        if path.is_dir() and 'native_calls' in path.parts and path.name != 'native_calls':
            errors.append('nested native evidence directory: ' + name)
            continue
        if not path.is_file():
            continue
        if not name.endswith(('.json', '.json.pending')) and 'native_calls/' not in name:
            continue
        raw = path.read_bytes()
        try:
            value = json.loads(raw)
        except (ValueError, UnicodeError):
            value = None
        shaped = isinstance(value, dict) and value.get('schema') == 'owned_table_native_command_v1'
        if 'native_calls/' not in name and not shaped:
            continue
        formal = name.removesuffix('.pending')
        if formal not in inverse:
            errors.append('unknown native receipt: ' + name)
            continue
        key = inverse[formal]
        grouped.setdefault(key, []).append((name, value))
    confirmed = []
    for key, rows in grouped.items():
        if len(rows) != 1 or rows[0][0].endswith('.pending'):
            errors.append('pending/duplicate native receipt: ' + repr(key))
            continue
        value = rows[0][1]
        if not isinstance(value, dict) or value.get('schema') != 'owned_table_native_command_v1' or value.get('label') != key[0] or value.get('tool') != key[1] or value.get('confirmed') is not True or value.get('finalized') is not True:
            errors.append('invalid native receipt: ' + repr(key))
            continue
        confirmed.append(key)
    return {'attempted_native_commands': len(grouped), 'actual_native_commands': len(confirmed),
            'unconfirmed_native_attempts': len(grouped) - len(confirmed),
            'actual_by_tool': {tool: sum(key[1] == tool for key in confirmed) for tool in c.TOOLS},
            'inventory_errors': errors}


def main(args):
    # Missing freeze is rejected before process/prctl/tool creation.
    spec, prepared = frozen(ROOT, args.kit.resolve())
    c.require(sys.platform == 'linux' and sys.version_info[:2] == (3, 12), 'pinned Linux Python3.12 required')
    c.require(ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0, 'owned-process subreaper required')
    c.require(args.resource_check.resolve() == (ROOT / 'guard/resource_check.json').resolve(), 'own guard admission only')
    loader = importlib.util.spec_from_file_location('table_owned_commands', Path(spec['dependencies_cloud']) / 'paired_checkpoint.py')
    paired = importlib.util.module_from_spec(loader)
    loader.loader.exec_module(paired)
    paired.REPO = ROOT
    environment = validate_environment(spec)
    env_sha = environment['complete_inherited_environment_sha256']
    inputs = c.read(ROOT / 'INPUT_MANIFEST.json')
    start = time.monotonic()

    def gate(first=False):
        frozen(ROOT, args.kit.resolve())
        c.require(environment_sha() == env_sha, 'inherited environment changed during stage')
        c.require(time.monotonic() - start < spec['stage_timeout_s'] - 60, 'stage budget exhausted; no retry')
        record = paired.check_resource(args.resource_check, args.kit.resolve(), first=first)
        c.require(record['model_identity'] == spec['model_identity'] and record['model_pid'] == spec['model_identity']['pid']
                  and record['model_starttime'] == spec['model_identity']['starttime'], 'protected model binding changed')
        c.require(record['protected'] == spec['protected'], 'protected package/task/official binding changed')
        c.require(record['protected']['tasks'] == inputs['input_sha256'] and record['protected']['official'] == inputs['official_sha256'], 'protected input metadata binding changed')
        for key in ('slot_owner', 'slot_lock_path', 'llm_base_url', 'model_name'):
            c.require(record[key] == spec[key], 'whole-task FIFO binding changed')
        return record

    gate(first=True)
    out = ROOT / 'results'
    out.mkdir(exist_ok=False)
    c.save(out / 'ENVIRONMENT_PREFLIGHT.json', environment)
    summary = {'schema': 'prompt_table_generated_calibration_measurement_v1',
               'spec_sha256': file_sha(ROOT / 'RUN_SPEC.json'), 'complete': False, 'passed': False,
               'evidence_complete': False, 'qualified_for_generated_control_discrimination': False,
               'error': None, 'rows': [], 'model_calls': 0, 'generated_research_test': True,
               'original_harness': False, 'score_gain_measured': False, 'adoption': False,
               'attempted_commands_by_tool': {tool: 0 for tool in c.TOOLS}}
    try:
        # All 25 controls are materialized before the first native call.
        for meta, prompt, item in prepared:
            folder = out / meta['label']
            folder.mkdir()
            (folder / 'native_calls').mkdir()
            (folder / 'candidate.sv').write_bytes(item['rtl'].encode())
            (folder / 'tb.sv').write_bytes(item['tb'].encode())
            c.save(folder / 'SOURCE_MANIFEST.json', {'candidate.sv': meta['rtl_sha256'], 'tb.sv': meta['tb_sha256']})
        c.save(out / 'summary.json', summary)
        for meta, prompt, item in prepared:
            folder = out / meta['label']
            row = {'index': meta['index'], 'label': meta['label'], 'kind': meta['kind'],
                   'generated_research_test': True, 'original_harness': False,
                   'commands': [], 'error': None, 'evidence_complete': False, 'control_matched': False}
            for number, (tool, argv, cwd) in enumerate(c.commands(meta, spec)):
                record = gate()
                c.require(str(folder) == cwd, 'fixed fresh cwd changed')
                sources = {'candidate.sv': file_sha(folder / 'candidate.sv'), 'tb.sv': file_sha(folder / 'tb.sv')}
                c.require(sources == {'candidate.sv': meta['rtl_sha256'], 'tb.sv': meta['tb_sha256']}, 'materialized source changed')
                path = folder / 'native_calls' / f'{number:02d}_{tool}.json'
                receipt = {'schema': 'owned_table_native_command_v1', 'label': meta['label'], 'tool': tool,
                           'sequence': number, 'argv': argv, 'cwd': cwd, 'source_input_sha256': sources,
                           'compiler_entry_sha256': spec['compiler_tools'][tool]['sha256'],
                           'environment_sha256': env_sha, 'resource_check_sha256': file_sha(args.resource_check),
                           'spec_sha256': summary['spec_sha256'], 'attempted': True, 'confirmed': False,
                           'finalized': False, 'started_ns': time.time_ns()}
                c.save(path.with_name(path.name + '.pending'), receipt)
                summary['attempted_commands_by_tool'][tool] += 1
                c.save(out / 'summary.json', summary)
                actual = paired.owned_command(argv, folder, folder / (tool + '.log'), spec['native_command_timeout_s'])
                unchanged = file_sha(folder / 'candidate.sv') == meta['rtl_sha256'] and file_sha(folder / 'tb.sv') == meta['tb_sha256']
                receipt.update(command=actual, finished_ns=time.time_ns(), confirmed=True, finalized=True, inputs_unchanged=unchanged)
                c.save(path, receipt)  # Preserve true rc/log even when validation below fails.
                c.require(not actual['timeout'] and actual['launch_error'] is None and not actual['remaining_live_group'], 'native launch/timeout/cleanup failure; no retry')
                c.require(type(actual['returncode']) is int, 'unknown true returncode')
                c.require(unchanged, 'source changed during native call')
                row['commands'].append(path.relative_to(out).as_posix())
                c.save(folder / 'ROW.json', row)
                if tool in ('xvlog', 'xelab'):
                    c.require(actual['returncode'] == 0 and not c.ENV_ERROR.search((folder / (tool + '.log')).read_text()), 'compile/elaboration error is not semantic discrimination')
            log = (folder / 'xsim.log').read_bytes().decode('utf-8')
            try:
                classified = c.classify(prompt.decode(), item, log, receipt['command']['returncode'])
                c.save(folder / 'PARSED.json', classified)
                row.update(evidence_complete=True, control_matched=classified['control_matched'],
                           checks=classified['parsed']['checks'], mismatches=classified['parsed']['mismatches'],
                           parsed_sha256=file_sha(folder / 'PARSED.json'))
            except ValueError as error:
                row['error'] = str(error)  # Preserve unknown/partial logs, never turn them into feedback.
            c.save(folder / 'ROW.json', row)
            summary['rows'].append(row)
            c.save(out / 'summary.json', summary)
        gate()
        c.require(validate_environment(spec) == environment, 'compiler environment changed after controls')
        summary.update(complete=True, evidence_complete=all(r['evidence_complete'] for r in summary['rows']),
                       qualified_for_generated_control_discrimination=all(r['control_matched'] for r in summary['rows']))
        summary['passed'] = summary['evidence_complete']  # Completeness and discrimination remain separate.
    except BaseException as error:
        summary['error'] = type(error).__name__ + ': ' + str(error)
    finally:
        try:
            counts = inventory(out)
            summary.update(counts)
            valid_counts = (counts['attempted_native_commands'] == counts['actual_native_commands'] == 75
                            and counts['unconfirmed_native_attempts'] == 0 and not counts['inventory_errors']
                            and counts['actual_by_tool'] == {tool: 25 for tool in c.TOOLS}
                            and summary['attempted_commands_by_tool'] == {tool: 25 for tool in c.TOOLS})
            if not valid_counts or len(summary['rows']) != 25 or summary['error'] is not None:
                summary.update(complete=False, passed=False, evidence_complete=False, qualified_for_generated_control_discrimination=False)
        except BaseException as error:
            summary.update(complete=False, passed=False, evidence_complete=False, qualified_for_generated_control_discrimination=False,
                           inventory_error=type(error).__name__ + ': ' + str(error))
        summary['elapsed_s'] = time.monotonic() - start
        c.save(out / 'summary.json', summary)
    return 0 if summary['passed'] else 1


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--kit', type=Path, required=True)
    p.add_argument('--resource-check', type=Path, required=True)
    raise SystemExit(main(p.parse_args()))
