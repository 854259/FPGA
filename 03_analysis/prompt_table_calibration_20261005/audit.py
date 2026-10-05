"""Read-only complete75-command archive audit; no model/compiler execution."""
import argparse
import json
import re
import zipfile
from pathlib import Path, PurePosixPath

import controls as c


def check_evidence(raw, names, spec_sha):
    """Validate raw(name)->bytes, never trust only summary.rows or totals."""
    def read(name):
        return json.loads(raw(name))

    spec = read('run/RUN_SPEC.json')
    c.require(c.sha(raw('run/RUN_SPEC.json')) == spec_sha
              and spec['schema'] == 'prompt_table_generated_calibration_frozen_v1', 'spec binding')
    c.require(all(type(spec[key]) is int for key in ('controls_max', 'commands_per_tool', 'model_requests_max')), 'integer budget types')
    c.require(spec['controls_max'] == spec['commands_per_tool'] == 25 and spec['model_requests_max'] == 0, 'fixed25/75/0model budget')
    private = read('run/raw_evidence/CONTROLS.json')
    bindings = read('run/raw_evidence/DEPENDENCY_BINDINGS.json')
    c.require(spec['dependencies_cloud'] == bindings['dependencies_cloud']
              and spec['dependency_hashes'] == bindings['dependency_hashes']
              and spec['compiler_tools'] == bindings['environment']['tools']
              and spec['vivado_bin'] == bindings['environment']['vivado_bin']
              and spec['udev_stub'] == bindings['environment']['udev_stub']
              and spec['protected'] == bindings['protected'], 'reviewed dependency/compiler/protected binding')
    c.require(private['original_harness'] is False and private['generated_research_test'] is True
              and private['model_calls'] == 0 and len(private['controls']) == 25, 'research provenance')
    c.require(set(spec['source_hashes']) == set(c.source_paths(private)), 'exact frozen source inventory')
    for name, digest in spec['source_hashes'].items():
        c.require(c.sha(raw('run/' + name)) == digest, 'frozen source bytes: ' + name)
    c.require(spec['source_hashes']['contract.py'] == c.PARSER_SHA
              and spec['source_hashes']['render.py'] == c.RENDER_SHA, 'original sealed parser/renderer binding')
    for name in ('audit.py', 'controls.py', 'contract.py', 'render.py'):
        c.require(c.sha((Path(__file__).parent / name).read_bytes()) == spec['source_hashes'][name], 'live auditor/helper bytes differ from freeze')
    for name, digest in spec['dependency_hashes'].items():
        c.require(c.sha(raw('dependencies/' + name)) == digest, 'owned command dependency bytes')
    preparation = read('run/PREPARATION_RECEIPT.json')
    c.require(c.sha(raw('run/PREPARATION_RECEIPT.json')) == spec['preparation_receipt_sha256']
              and preparation['source_hashes'] == spec['source_hashes']
              and preparation['actual_native_commands'] == 0 and preparation['prepared_controls'] == 25
              and preparation['RUN_SPEC_frozen'] is False, 'unfrozen preparation provenance')
    guard, resource = read('guard/status.json'), read('guard/resource_check.json')
    c.require(all(guard.get(k) is True for k in ('complete', 'passed', 'model_unchanged', 'protected_files_unchanged', 'own_slot_released'))
              and type(guard['stage_rc']) is int and guard['stage_rc'] == 0
              and guard['owned_cleanup']['verified'] is True and not guard['owned_cleanup']['remaining'], 'guard/model/protected/cleanup/release')
    c.require(resource['resource_idle'] is True and resource['model_identity'] == spec['model_identity']
              and resource['model_pid'] == spec['model_identity']['pid']
              and resource['model_starttime'] == spec['model_identity']['starttime']
              and resource['protected'] == spec['protected'], 'protected model/resource binding')
    for key in ('slot_owner', 'slot_lock_path', 'llm_base_url', 'model_name'):
        c.require(resource[key] == spec[key], 'FIFO/endpoint resource binding')
    inputs = read('run/INPUT_MANIFEST.json')
    c.require(resource['protected']['tasks'] == inputs['input_sha256']
              and resource['protected']['official'] == inputs['official_sha256'], 'protected input/official manifest')
    env = read('run/results/ENVIRONMENT_PREFLIGHT.json')
    c.require(env['verified'] is True and env['tools'] == spec['compiler_tools']
              and env['compiler_env'] == spec['compiler_env'] and env['udev_files'] == spec['udev_files']
              and env['model_calls'] == env['eda_calls'] == 0
              and re.fullmatch('[0-9a-f]{64}', env['complete_inherited_environment_sha256']), 'compiler environment binding')
    summary = read('run/results/summary.json')
    c.require(summary['schema'] == 'prompt_table_generated_calibration_measurement_v1'
              and summary['complete'] is True and summary['passed'] is True and summary['evidence_complete'] is True
              and summary['error'] is None and summary['spec_sha256'] == spec_sha
              and summary['model_calls'] == 0 and summary['original_harness'] is False
              and summary['generated_research_test'] is True and summary['score_gain_measured'] is False
              and summary['adoption'] is False, 'complete research measurement only')
    for key in ('attempted_native_commands', 'actual_native_commands'):
        c.require(type(summary[key]) is int and summary[key] == 75, 'all75 native totals required')
    c.require(type(summary['unconfirmed_native_attempts']) is int and summary['unconfirmed_native_attempts'] == 0 and not summary['inventory_errors']
              and summary['actual_by_tool'] == summary['attempted_commands_by_tool'] == {tool: 25 for tool in c.TOOLS}, 'confirmed/global accounting')
    c.require(all(type(value) is int for field in ('actual_by_tool', 'attempted_commands_by_tool') for value in summary[field].values()), 'integer native totals')
    expected_calls = {f'run/results/{label}/native_calls/{i:02d}_{tool}.json'
                      for label in c.ORDER for i, tool in enumerate(c.TOOLS)}
    actual_calls = set()
    for name in names:
        if not name.startswith('run/results/'):
            continue
        value = read(name) if name.endswith('.json') else None
        native_shaped = isinstance(value, dict) and (value.get('schema') == 'owned_table_native_command_v1'
                         or {'argv', 'source_input_sha256', 'tool'}.issubset(value))
        if '/native_calls/' in name or native_shaped:
            c.require(name in expected_calls and not name.endswith('.pending'), 'unknown/extra/pending native receipt')
            actual_calls.add(name)
    c.require(actual_calls == expected_calls and len(actual_calls) == 75, 'global actual75 receipt classes')
    c.require([(row['index'], row['label']) for row in summary['rows']] == list(enumerate(c.ORDER)), 'all fixed25 rows/order')
    prepared, measured = [], []
    for task in c.TASKS:
        path = 'raw_evidence/inputs/' + task + '/prompt.txt'
        prompt = raw('run/' + path)
        c.require(c.sha(prompt) == private['prompt_sha256'][task], 'original prompt byte binding')
        for item in c.generate(prompt.decode(), task):
            index = len(prepared)
            meta = {k: v for k, v in item.items() if k not in ('rtl', 'tb')}
            meta.update(task=task, index=index, prompt_path=path,
                        rtl_path='raw_evidence/controls/' + item['label'] + '/candidate.sv',
                        tb_path='raw_evidence/controls/' + item['label'] + '/tb.sv',
                        rtl_sha256=c.sha(item['rtl'].encode()), tb_sha256=c.sha(item['tb'].encode()))
            c.require(meta == private['controls'][index], 'fixed control sources/expectations')
            c.require(all(type(private['controls'][index][key]) is int for key in ('index', 'checks', 'expected_mismatches')), 'control metadata integer types')
            c.require(private['controls'][index]['single_flip_row'] is None or type(private['controls'][index]['single_flip_row']) is int, 'single flip row integer type')
            prepared.append(meta)
            base = 'run/results/' + meta['label'] + '/'
            hashes = {'candidate.sv': meta['rtl_sha256'], 'tb.sv': meta['tb_sha256']}
            for name, content in (('candidate.sv', item['rtl']), ('tb.sv', item['tb'])):
                c.require(raw(base + name) == content.encode(), 'actual materialized source bytes')
                private_path = meta['rtl_path' if name == 'candidate.sv' else 'tb_path']
                c.require(raw('run/' + private_path) == content.encode(), 'private generated source bytes')
            c.require(read(base + 'SOURCE_MANIFEST.json') == hashes, 'actual source manifest')
            row = read(base + 'ROW.json')
            c.require(row == summary['rows'][index], 'row/summary binding')
            c.require(all(type(row[key]) is int for key in ('index', 'checks', 'mismatches')), 'actual row integer types')
            prior_finish = 0
            calls = []
            for sequence, (tool, argv, cwd) in enumerate(c.commands(meta, spec)):
                name = base + f'native_calls/{sequence:02d}_{tool}.json'
                receipt = read(name)
                command = receipt['command']
                c.require(receipt['schema'] == 'owned_table_native_command_v1' and receipt['label'] == meta['label']
                          and receipt['tool'] == tool and type(receipt['sequence']) is int and receipt['sequence'] == sequence
                          and receipt['argv'] == argv and receipt['cwd'] == cwd and receipt['source_input_sha256'] == hashes
                          and receipt['compiler_entry_sha256'] == spec['compiler_tools'][tool]['sha256']
                          and receipt['environment_sha256'] == env['complete_inherited_environment_sha256']
                          and receipt['resource_check_sha256'] == c.sha(raw('guard/resource_check.json'))
                          and receipt['spec_sha256'] == spec_sha and receipt['attempted'] is True
                          and receipt['confirmed'] is True and receipt['finalized'] is True and receipt['inputs_unchanged'] is True,
                          'actual native argv/source/compiler/environment/resource/spec binding')
                c.require(type(receipt['started_ns']) is int and type(receipt['finished_ns']) is int
                          and prior_finish <= receipt['started_ns'] <= receipt['finished_ns'], 'actual command ordering')
                prior_finish = receipt['finished_ns']
                log = raw(base + tool + '.log')
                c.require(command['log'] == cwd + '/' + tool + '.log' and c.sha(log) == command['log_sha256']
                          and type(command['log_bytes']) is int and len(log) == command['log_bytes'] and command['timeout'] is False
                          and command['launch_error'] is None and not command['remaining_live_group']
                          and type(command['returncode']) is int and 0 <= command['returncode'] <= 255,
                          'true returncode/full log/timeout/cleanup binding')
                if tool in ('xvlog', 'xelab'):
                    c.require(command['returncode'] == 0 and not c.ENV_ERROR.search(log.decode()), 'compile/elaboration failure cannot count as semantic negative')
                calls.append(name.removeprefix('run/results/'))
            parsed = c.classify(prompt.decode(), item, raw(base + 'xsim.log').decode(), command['returncode'])
            c.require(parsed == read(base + 'PARSED.json') and c.sha(raw(base + 'PARSED.json')) == row['parsed_sha256']
                      and row['commands'] == calls and row['error'] is None and row['evidence_complete'] is True
                      and row['control_matched'] is parsed['control_matched'] and row['checks'] == item['checks']
                      and row['mismatches'] == parsed['parsed']['mismatches'] and row['original_harness'] is False
                      and row['generated_research_test'] is True, 'full care/unknown/rc classification binding')
            measured.append({'label': item['label'], 'kind': item['kind'], 'checks': row['checks'],
                             'mismatches': row['mismatches'], 'true_xsim_returncode': parsed['true_xsim_returncode'],
                             'control_matched': parsed['control_matched'], 'false_acceptance': parsed['false_acceptance']})
    qualified = all(row['control_matched'] for row in measured)
    c.require(summary['qualified_for_generated_control_discrimination'] is qualified, 'measurement/discrimination distinction')
    return {'schema': 'prompt_table_generated_calibration_audit_v1', 'evidence_valid': True,
            'actual_native_commands': 75, 'actual_xvlog': 25, 'actual_xelab': 25, 'actual_xsim': 25,
            'actual_model_calls': 0, 'research_controls': 25, 'rows': measured,
            'qualified_for_generated_control_discrimination': qualified,
            'original_harness': False, 'generated_research_test': True,
            'score_gain_measured': False, 'independent_model_qualification': False, 'adoption': False}


def audit(archive, spec_sha):
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        c.require(len(names) == len(set(names)), 'duplicate archive member')
        for name in names:
            path = PurePosixPath(name)
            c.require(not path.is_absolute() and '..' not in path.parts and '\\' not in name, 'unsafe archive path')
        manifest = json.loads(z.read('ARCHIVE_MANIFEST.json'))
        c.require(set(names) == set(manifest['files']) | {'ARCHIVE_MANIFEST.json'}, 'exact manifest member inventory')
        for name, digest in manifest['files'].items():
            c.require(c.sha(z.read(name)) == digest, 'archive member SHA')
        c.require(manifest['run_spec_sha256'] == spec_sha
                  and manifest['collector_model_calls'] == manifest['collector_eda_calls'] == 0, 'collector/spec binding')
        spec = json.loads(z.read('run/RUN_SPEC.json'))
        c.require(manifest['collector_sha256'] == spec['source_hashes']['collect_evidence.py'], 'reused collector source binding')
        result = check_evidence(z.read, names, spec_sha)
        result.update(archive_sha256=c.sha(Path(archive).read_bytes()), spec_sha256=spec_sha)
        return result


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--archive', required=True, type=Path)
    p.add_argument('--spec-sha256', required=True)
    args = p.parse_args()
    print(json.dumps(audit(args.archive, args.spec_sha256), indent=2))
