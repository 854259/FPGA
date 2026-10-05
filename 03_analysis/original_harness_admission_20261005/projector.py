"""Project exact completed original-harness calibration onto public input digests.

Read-only source/archive audit; no archived code, model, EDA, network or FIFO
execution. Pure row derivation alone never establishes evidence validity.
"""
from pathlib import Path, PurePosixPath
import argparse
import hashlib
import json
import stat
import sys
import types
import zipfile

ROOT = Path(__file__).resolve().parent
ANALYSIS = ROOT.parent
SOURCE = ANALYSIS / 'natural_harness_calibration_20261005'
ADAPTER_SOURCE = ANALYSIS / 'natural_input_adapter_20261005' / 'adapter.py'
SPEC_SHA = 'b423bb37761744a33bc5fe91d3ae0d847dc06d29862afe2ab090059c97154a68'
ARCHIVE_SHA = 'b2cee6bfd50e1b12cfd78246c767880b1f11ddd09324d3ca717cc322fe9f9acf'
AUDITOR_SHA = 'e3992c2791b53dea5ec4b3391e7792c9c2dd7c5f4c71f220f81740bc4379359d'
RESULT_SHA = 'a1620cbe38e93c4599955fa352044d39d08b97f35460d973d1cc115ce6415056'
ADAPTER_SHA = '9b41ef3adfd345ff037ee4dcd3ef918d991c3bc5e52562ed8bc309355e0a39f9'
DATASET_SHA = 'cbcd81295561ebb16e4d857e096f4d9908d042c33aff3b58abf236e868411857'
IDS = ['cvdp_copilot_reverse_bits_0001', 'cvdp_copilot_binary_to_gray_0001',
       'cvdp_copilot_gray_to_binary_0001']
EXPECTED_LABELS = {name: ['positive', 'constant_zero', 'constant_one', 'identity',
                         *(['valid_zero'] if name == IDS[2] else []), 'failure_propagation'] for name in IDS}
EXPECTED_TRIALS = dict(zip(IDS, [1, 3, 5]))
EXPECTED_RECORD_SHA = dict(zip(IDS, [
    '91ab190b6b004b4669baa4df3ef53ee799105f64c89622ff4e860d5c15222420',
    'e111d3ae4206ca9ef9a4284540d92d714cddf1cf716a718315a0b7e1545152a7',
    'c16a5640e7f8601aadf52ab0a7a6e33e4408e48d3f7a97fda90edacaf00a1043']))
EXPECTED_MODEL = dict(pid=2013333, starttime='823869819', exe='llama-server',
                      command_sha256='2ef1233963df0e5cc660fc2bed2baa2fca4e30b84d450e79bc9f77381cbd24e1')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate JSON field')
        value[key] = item
    return value


def decoded(data):
    return json.loads(data, object_pairs_hook=unique)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def no_links(path):
    path = Path(path).absolute()
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        require(not current.is_symlink() and not (hasattr(current, 'is_junction') and current.is_junction()),
                'projection path contains a link/junction')
    return path


def pin_bytes(data, expected, label):
    require(sha(data) == expected, label + ' exact historical bytes differ')
    return data


def read_pinned(path, expected):
    path = no_links(path)
    return pin_bytes(path.read_bytes(), expected, path.name)


def portable(name):
    require(isinstance(name, str) and name and '\\' not in name and ':' not in name,
            'invalid archive relative path')
    path = PurePosixPath(name)
    require(not path.is_absolute() and '..' not in path.parts and path.as_posix() == name,
            'noncanonical archive relative path')
    return name


def trusted_module(path, expected, label):
    """Execute only a verified live pure auditor/adapter, never archived code."""
    path = no_links(path)
    source = read_pinned(path, expected)
    module = types.ModuleType(label)
    module.__file__ = str(path)
    exec(compile(source, str(path), 'exec'), module.__dict__)
    return module


def verify_archive(archive, local_spec):
    """Supplement frozen auditor with strict manifest/guard/global receipt binding."""
    read_pinned(archive, ARCHIVE_SHA)
    with zipfile.ZipFile(archive) as z:
        names = z.namelist()
        require(len(names) == len(set(names)), 'duplicate archive name')
        for item in z.infolist():
            portable(item.filename)
            require(not item.is_dir() and stat.S_IFMT(item.external_attr >> 16) != stat.S_IFLNK,
                    'directory/symlink entry is not an evidence file')
        manifest = decoded(z.read('ARCHIVE_MANIFEST.json'))
        require(manifest['schema'] == 'natural_harness_calibration_archive_v1', 'foreign archive schema')
        require(manifest['run_spec_sha256'] == SPEC_SHA and len(manifest['files']) == 613,
                'manifest source/count differs')
        require(set(names) == set(manifest['files']) | {'ARCHIVE_MANIFEST.json'}, 'manifest set differs')
        for name, expected in manifest['files'].items():
            portable(name)
            pin_bytes(z.read(name), expected, name)
        raw_spec = pin_bytes(z.read('run/RUN_SPEC.json'), SPEC_SHA, 'archived RUN_SPEC')
        require(raw_spec == local_spec, 'archived and live frozen specification differ')
        spec = decoded(raw_spec)
        require(spec['schema'] == 'natural_harness_calibration_frozen_v1'
                and spec['record_ids'] == IDS and spec['controls'] == 16
                and spec['model_requests_max'] == 0 and spec['compiles_max'] == spec['simulations_max'] == 50,
                'historical original-control scope differs')
        require(manifest['collector_sha256'] == spec['source_hashes']['collect.py'], 'collector binding differs')
        require(manifest['model_calls'] == manifest['eda_calls'] == 0, 'collector executed actual IO')
        for name, expected in spec['source_hashes'].items():
            portable(name)
            pin_bytes(z.read('run/' + name), expected, name)
        for name, expected in spec['dependency_hashes'].items():
            pin_bytes(z.read('dependencies/' + portable(name)), expected, name)
        guard = decoded(z.read('run/guard/status.json'))
        resource = decoded(z.read('run/guard/resource_check.json'))
        inputs = decoded(z.read('run/INPUT_MANIFEST.json'))
        for key in ['complete', 'passed', 'model_unchanged', 'protected_files_unchanged', 'own_slot_released']:
            require(guard.get(key) is True, 'historical guard ' + key + ' not verified')
        require(type(guard['stage_rc']) is int and guard['stage_rc'] == 0 and guard.get('error') is None,
                'historical guard exit/error differs')
        require(guard['model_managed'] is False and guard['instance_managed'] is False,
                'guard managed shared model/instance')
        require(guard['owned_cleanup']['verified'] is True and guard['owned_cleanup']['remaining'] == [],
                'historical owned cleanup incomplete')
        require(resource['model_identity'] == EXPECTED_MODEL and resource['model_pid'] == EXPECTED_MODEL['pid']
                and resource['model_starttime'] == EXPECTED_MODEL['starttime'], 'historical model identity differs')
        require(resource['slot_owner'] == 'codex_natural_harness_calibration_20261005_v1'
                and resource['slot_lock_path'] == '/workspace/team/SLOT.lock', 'historical slot differs')
        require(guard['model_idle_after']['processing_slots'] == 0
                and guard['model_idle_after']['model_pid_owns_port'] is True, 'historical model postflight differs')
        require(len(inputs['input_sha256']) == 936 and len(inputs['official_sha256']) == 35
                and resource['protected']['tasks'] == inputs['input_sha256']
                and resource['protected']['official'] == inputs['official_sha256'], 'protected inventories differ')
        private = decoded(z.read('run/raw_evidence/CONTROLS.json'))
        data = pin_bytes(z.read('run/raw_evidence/ORIGINAL_DATASET.jsonl'), DATASET_SHA, 'original dataset')
        records = [decoded(line) for line in data.decode('utf-8').splitlines()]
        require(len(records) == 302 and len({row['id'] for row in records}) == 302, 'dataset count/unique IDs differ')
        records = {row['id']: row for row in records if row['id'] in IDS}
        summary = decoded(z.read('run/results/summary.json'))
        require(summary['complete'] is True and summary['passed'] is True and summary['error'] is None
                and summary['source_unchanged'] is True and summary['dependencies_unchanged'] is True,
                'historical summary source/evidence incomplete')
        require(summary['run_spec_sha256'] == SPEC_SHA and summary['model_calls'] == 0
                and summary['actual_compile'] == summary['actual_sim'] == 50
                and summary['independent_model_tasks'] == 0 and summary['adoption'] is False
                and summary['eligible_for_independent_models'] is False, 'historical measurement scope differs')
        expected_folders = {'run/results/' + case['record_id'] + '/' + control['label'] + '/native_receipts/'
                            for case in private['cases'] for control in case['controls']}
        native = [name for name in names if '/native_receipts/' in name and name.endswith('.json')]
        require(len(native) == 100, 'global native receipt count differs')
        counts = dict(iverilog=0, vvp=0)
        for name in native:
            require(name.rsplit('/', 1)[0] + '/' in expected_folders, 'misplaced native receipt')
            row = decoded(z.read(name))
            require(row.get('name') in counts and type(row.get('returncode')) is int and row['returncode'] >= 0,
                    'unknown/unconfirmed native receipt')
            counts[row['name']] += 1
        require(counts == dict(iverilog=50, vvp=50), 'native compiler/simulator counts differ')
        return dict(spec=spec, private=private, records=records,
                    manifest_sha256=sha(z.read('ARCHIVE_MANIFEST.json')),
                    guard_sha256=sha(z.read('run/guard/status.json')),
                    resource_sha256=sha(z.read('run/guard/resource_check.json')),
                    global_native_receipts=len(native), native_counts=counts)


def validate_audit(audit):
    require(audit.get('schema') == 'natural_harness_calibration_readonly_audit_v1'
            and audit.get('evidence_valid') is True, 'original completed readonly audit missing')
    for field, expected in [('spec_sha256', SPEC_SHA), ('archive_sha256', ARCHIVE_SHA), ('auditor_sha256', AUDITOR_SHA)]:
        require(audit.get(field) == expected, 'audit ' + field + ' differs')
    for key, expected in [('manifest_files', 613), ('native_compile_commands', 50), ('native_simulation_commands', 50),
                          ('model_calls', 0), ('audit_model_calls', 0), ('audit_eda_calls', 0), ('independent_model_tasks', 0)]:
        require(type(audit.get(key)) is int and audit[key] == expected, 'audit count/scope differs: ' + key)
    require(audit.get('eligible_for_independent_models') is False and audit.get('adoption') is False,
            'original calibration is not independent model/production admission')


def derive_rows(records, private, audit, adapter):
    """Pure semantic projection. Caller must separately prove archive/source audit."""
    validate_audit(audit)
    require(private.get('schema') == 'natural_original_harness_private_controls_v1'
            and [row['record_id'] for row in private['cases']] == IDS, 'control record order/version differs')
    require(set(records) == set(IDS), 'original record set differs')
    expected_order = [(name, label) for name in IDS for label in EXPECTED_LABELS[name]]
    require([(row['record_id'], row['label']) for row in audit['controls']] == expected_order,
            'missing/extra/duplicate/reordered audited controls')
    require(audit['false_acceptances'] == [row for row in audit['controls'] if row['false_acceptance'] is True],
            'false acceptance list was removed or changed')
    require(set(audit['original_harness_calibration']) == set(IDS), 'audit qualification record set differs')
    rows, excluded = {}, []
    for case in private['cases']:
        name = case['record_id']; original = records[name]
        require(case['record_sha256'] == EXPECTED_RECORD_SHA[name], 'private record version binding differs')
        # This is the historical canonical record encoding used by the frozen
        # old auditor, including original ID/categories/private harness version.
        require(sha(json.dumps(original, sort_keys=True).encode()) == case['record_sha256'],
                'record/input/output/private test version differs')
        require({path: sha(text.encode()) for path, text in original['harness']['files'].items()} == case['harness_sha256'],
                'original test/runner/full harness version differs')
        require([row['label'] for row in case['controls']] == EXPECTED_LABELS[name]
                and case['expected_pytest_tests'] == EXPECTED_TRIALS[name], 'private control schedule differs')
        require(case['controls'][0]['intent'] == 'correct' and case['controls'][-1]['intent'] == 'sentinel'
                and all(row['intent'] == 'wrong' for row in case['controls'][1:-1]), 'control intent changed')
        view = adapter.task_view(original)
        binding = adapter.binding(original, view)
        require(binding['prompt_sha256'] == case['prompt_sha256']
                and binding['output_paths'] == [case['rtl_path']], 'public prompt/output version differs')
        selected = [row for row in audit['controls'] if row['record_id'] == name]
        for actual, control in zip(selected, case['controls']):
            require(all(type(actual.get(key)) is bool for key in ['passed', 'failed', 'original_harness', 'false_acceptance']),
                    'boolean control outcome/provenance types differ')
            require(actual['passed'] != actual['failed'] and type(actual['native_trials']) is int
                    and actual['native_trials'] == EXPECTED_TRIALS[name], 'actual complete control trials differ')
            require(actual['original_harness'] is (control['intent'] != 'sentinel'),
                    'research/sentinel harness cannot become original')
            require(actual['false_acceptance'] is (control['intent'] == 'wrong' and actual['passed']),
                    'wrong-control false acceptance was hidden')
        false_acceptances = [row for row in selected if row['false_acceptance']]
        correct = selected[0]['passed']
        sentinel = selected[-1]['failed']
        qualified = correct and sentinel and not false_acceptances and all(row['failed'] for row in selected[1:-1])
        require(type(audit['original_harness_calibration'].get(name)) is bool
                and audit['original_harness_calibration'][name] is qualified, 'qualification contradicts actual controls')
        key = binding['user_content_sha256']
        require(key not in rows, 'public task projection collision; do not merge record qualifications')
        row = dict(qualified=qualified, original_harness=True,
                   prompt_sha256=binding['prompt_sha256'], input_context_sha256=binding['input_context_sha256'],
                   output_paths=binding['output_paths'], false_acceptances=false_acceptances,
                   unconfirmed_native_attempts=0, wrong_controls_checked=len(selected[1:-1]),
                   correct_control_passed=correct, failure_propagation_confirmed=sentinel,
                   failure_propagation_control_original_harness=False,
                   failure_propagation_scope='original test with evaluation-only forced AssertionError appended; not an unchanged original harness',
                   record_id=name, record_sha256=case['record_sha256'],
                   original_harness_sha256=case['harness_sha256'], test_sha256=case['harness_sha256'][case['test_path']],
                   native_trials_per_control=EXPECTED_TRIALS[name],
                   observed_controls=[dict(label=x['label'], passed=x['passed'], failed=x['failed'],
                                           native_trials=x['native_trials'], original_harness=x['original_harness'],
                                           false_acceptance=x['false_acceptance']) for x in selected],
                   public_input_only=True, hidden_harness_forwarded=False, answers_forwarded=False,
                   qualification_scope='finite original-harness discrimination on this exact original public task version')
        rows[key] = row
        if not qualified:
            excluded.append(dict(user_content_sha256=key, record_id=name, record_sha256=case['record_sha256'],
                                 test_sha256=row['test_sha256'], false_acceptances=false_acceptances,
                                 reason='original valid_zero control passed every original parameter trial; keep this exact original version excluded'))
    return dict(public_inputs=rows, exclusions=excluded, pure_projection_only=True,
                evidence_valid=False, real_execution_admitted=False)


def build_projection(source_root=SOURCE, adapter_path=ADAPTER_SOURCE):
    require(sys.version_info[:2] == (3, 12), 'use Python 3.12 for the frozen historical auditor')
    source_root = no_links(source_root)
    archive = source_root / 'raw_evidence/terminal_v1.zip'
    local_spec = read_pinned(source_root / 'RUN_SPEC.json', SPEC_SHA)
    report_bytes = read_pinned(source_root / 'terminal_audit_v1/RESULTS.json', RESULT_SHA)
    bundle = verify_archive(archive, local_spec)
    for name, expected in bundle['spec']['source_hashes'].items():
        read_pinned(source_root / portable(name), expected)
    auditor = trusted_module(source_root / 'audit.py', AUDITOR_SHA, 'trusted_original_calibration_auditor')
    rebuilt = auditor.audit(archive, SPEC_SHA)
    require(canonical(rebuilt) == canonical(decoded(report_bytes)), 'reconstructed actual audit differs from saved source result')
    adapter = trusted_module(adapter_path, ADAPTER_SHA, 'trusted_immutable_public_adapter')
    pure = derive_rows(bundle['records'], bundle['private'], rebuilt, adapter)
    projection = dict(schema='natural_original_harness_admission_audit_v1', evidence_valid=True,
                      archive_sha256=ARCHIVE_SHA, spec_sha256=SPEC_SHA, auditor_sha256=AUDITOR_SHA,
                      source_evidence=dict(spec_sha256=SPEC_SHA, archive_sha256=ARCHIVE_SHA,
                                           auditor_sha256=AUDITOR_SHA, audit_report_sha256=RESULT_SHA,
                                           manifest_sha256=bundle['manifest_sha256'], guard_sha256=bundle['guard_sha256'],
                                           resource_sha256=bundle['resource_sha256'], adapter_sha256=ADAPTER_SHA,
                                           dataset_sha256=DATASET_SHA, source_files=10,
                                           manifest_files=613, global_native_receipts=bundle['global_native_receipts'],
                                           native_compile_commands=50, native_simulation_commands=50,
                                           actual_readonly_rebuild_matches_source=True),
                      public_inputs=pure['public_inputs'], exclusions=pure['exclusions'],
                      qualified_public_input_versions=sum(row['qualified'] for row in pure['public_inputs'].values()),
                      excluded_public_input_versions=len(pure['exclusions']),
                      actual_model_calls=0, actual_eda_calls=0, actual_cloud_or_fifo_calls=0,
                      independent_model_tasks=0, eligible_for_independent_models=False,
                      real_execution_admitted=False, official_vivado_quality_certified=False,
                      original_harness_required=True, research_modified_harness_admitted=False, adoption=False,
                      limits=rebuilt['limits'] + [
                          'This projection maps only three historical public task versions; two finite original-harness calibrations qualify and valid_zero false acceptance remains excluded.',
                          'Sentinel was an evaluation-only forced exception appended to the original test; its provenance is separately original_harness=false.',
                          'Unconfirmed native count zero derives from a successful completed frozen schedule with exactly 50+50 confirmed archived receipts, not a new durable-attempt instrumentation test.',
                          'Full156/net gain, actual OS/include isolation, real transport/supervision, model comparison and exposure review remain separate mandatory gates.'])
    receipt = dict(schema='original_harness_projection_readonly_receipt_v1',
                   projector_sha256=sha(Path(__file__).read_bytes()), adapter_sha256=ADAPTER_SHA,
                   source_evidence=projection['source_evidence'], qualified_inputs=projection['qualified_public_input_versions'],
                   excluded_inputs=projection['excluded_public_input_versions'],
                   actual_model_calls=0, actual_eda_calls=0, actual_cloud_or_fifo_calls=0,
                   archived_code_executed=False, verified_live_pure_auditor_reexecuted=True,
                   projection_sha256=sha((json.dumps(projection, ensure_ascii=False, indent=2) + '\n').encode()))
    return projection, receipt, rebuilt


def save_new(path, value):
    path = no_links(path)
    require(path.is_relative_to(ROOT), 'projector output must remain in its owned new directory')
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write((json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=ROOT / 'ADMISSION.json')
    args = parser.parse_args()
    projection, receipt, rebuilt = build_projection()
    save_new(ROOT / 'raw_evidence/REBUILT_AUDIT.json', rebuilt)
    save_new(args.out, projection)
    save_new(ROOT / 'PROJECTION_RECEIPT.json', receipt)
    print(json.dumps(dict(evidence_valid=projection['evidence_valid'],
                          qualified=projection['qualified_public_input_versions'],
                          excluded=projection['excluded_public_input_versions'],
                          projection_sha256=receipt['projection_sha256'], actual_model_calls=0, actual_eda_calls=0)))


if __name__ == '__main__':
    main()
