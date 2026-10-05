"""DRAFT real natural IO. Every production entry is closed until bound own gates pass.

Importing this file performs no network or native execution. Pure protocol helpers
require injected byte sources, never implicitly open a socket or spawn a process.
"""
from pathlib import Path, PurePosixPath
import hashlib
import importlib.util
import json
import math
import re
import socket
import sys
import time
import uuid
import zipfile

ROOT = Path(__file__).resolve().parent
BASE_SPEC_SHA = '1073465430810c8bd5f569b27b12c81ee069367e9fdc427620cd2d6f9a6a0a22'
ADAPTER_SHA = '9b41ef3adfd345ff037ee4dcd3ef918d991c3bc5e52562ed8bc309355e0a39f9'
CONTRACT_SHA = '94bcb3b86b7bf1209c5a2348f9d3da5e9c74136e15f77cbdeeedc838ee5fa43d'
FULL_SPEC_SHA = '3fb1531c14b011f80ff58de559e326a4904d3fbdbcf3cdce7d6c955285860ba1'
FULL_AUDITOR_SHA = '681b46a55166caf319a03b48988d83cb923692c8a9424760d7ea7a5edfaea1ab'
FULL_SCOPE = 'Permits faithful independent model validation only; no five-sample/offline/target hardware/official baseline certificate or automatic deployment.'
NATIVE_SPEC_SHA = 'f4889422e53aa00848e567694d8df5e351c2d79713134ddd543ec638738a4bc3'
NATIVE_AUDITOR_SHA = '084cbce2b1d32234c429f4fe4a1cc50baa9a829347cb1146259298b99a3226b0'
HOST, PORT, ROUTE = '127.0.0.1', 8000, '/v1/chat/completions'
ENDPOINT = 'http://127.0.0.1:8000/v1/chat/completions'
RAW_HTTP_MAX = 16 * 1024 * 1024
NATIVE_CLEANUP_RESERVE = 24.0
_GRANTS = {}
_ACTIVE_IO = {}
_BOUND_ARCHIVES = set()
_STAGE_ADMISSIONS = set()
ESCAPE_CONTROLS = {'absolute_include', 'relative_include', 'file_read', 'network', 'shell', 'owned_cleanup'}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate JSON field')
        value[key] = item
    return value


def read_json(path):
    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique, parse_constant=reject_constant)


def reject_constant(value):
    raise ValueError('nonfinite JSON number is forbidden: ' + value)


def file_sha(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def save(path, value):
    import worker
    return worker.save_json(path, value)


def new_bytes(path, data):
    import worker
    path = Path(path)
    worker.no_links(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    worker.no_links(path)
    with path.open('xb') as stream:
        stream.write(data)
    return sha(data)


def feedback_plan(prompt, arm):
    import native_reset_contract as contract
    parsed = contract.parse(prompt)
    return dict(arm=arm, contract=parsed,
                native_feedback_required=arm == 'P' and parsed['status'] == 'supported',
                path='generated_public_contract' if arm == 'P' and parsed['status'] == 'supported' else 'normal_candidate_compile',
                original_harness=False, frozen_policy_equivalence=False)


def sandbox_recipe(spec):
    return dict(mechanism='bubblewrap_prlimit_v1', unshare_all=True, network=False,
                candidate_mount='/inputs:readonly', output_mount='/outputs:owned',
                toolchain_files_sha256=sha(canonical(spec['toolchain']['files'])),
                runtime_libraries_sha256=sha(canonical(spec['runtime_libraries'])),
                bwrap_sha256=spec['real_tools']['bwrap']['sha256'],
                prlimit_sha256=spec['real_tools']['prlimit']['sha256'],
                native_as_bytes=spec['limits']['native_as_bytes'], native_fsize_bytes=spec['limits']['native_fsize_bytes'],
                cleanup_reserve_s=NATIVE_CLEANUP_RESERVE, no_host_root_mount=True)


def evaluate_documents(spec, full, original, isolation, native, binding, need_native):
    """Pure gate logic. Synthetic passing documents are never real admission."""
    if spec.get('schema') != 'natural_runtime_frozen_v1' or spec.get('integration_factor') != 'natural_runtime_v1':
        raise PermissionError('new integration factor must have its own frozen RUN_SPEC')
    if spec.get('base_worker_tools_spec_sha256') != BASE_SPEC_SHA or spec.get('execution_authorized_by_root') is not True:
        raise PermissionError('root execution authorization or base source binding missing')
    required = dict(max_requests=2, max_tokens=8192, temperature=0, top_p=1, solve_timeout_s=300, max_native_commands=6)
    if any(spec.get(key) != value for key, value in required.items()) or spec.get('endpoint') != ENDPOINT:
        raise PermissionError('fixed endpoint or solve/native budgets differ')
    if any(type(spec.get(key)) is not int for key in ('max_requests', 'max_tokens', 'max_native_commands')) or any(type(spec.get(key)) not in (int, float) for key in ('temperature', 'top_p', 'solve_timeout_s')):
        raise PermissionError('boolean values cannot substitute for fixed numeric budgets')
    if full.get('schema') != 'phase_full156_readonly_audit_v1' or full.get('spec_sha256') != FULL_SPEC_SHA or full.get('auditor_sha256') != FULL_AUDITOR_SHA or full.get('qualification_scope') != FULL_SCOPE:
        raise PermissionError('previous actual full156 audit identity/scope differs')
    if not all(full.get(key) is True for key in ['evidence_valid', 'full156_evidence_valid', 'screening_eligible',
                                               'candidate_qualified_for_independent_validation', 'independent_validation_qualified']):
        raise PermissionError('complete full156 quality qualification is missing')
    if full.get('historical_fixture_only') is not False or type(full.get('expected_samples')) is not int or full['expected_samples'] != 312:
        raise PermissionError('full156 result is fixture/partial')
    if type(full.get('actual_model_requests')) is not int or not 312 <= full['actual_model_requests'] <= 624 or type(full.get('unconfirmed_attempts')) is not int or full['unconfirmed_attempts'] != 0 or full.get('solve_deadlines') != [] or full.get('regressions') != [] or full.get('unchanged_first_reply_regressions') != [] or full.get('matched_native_repair_tasks') != ['Prob045_edgedetect2', 'Prob054_edgedetect']:
        raise PermissionError('full156 request/repair/deadline/regression gates fail')
    if original.get('schema') != 'natural_original_harness_admission_audit_v1' or original.get('evidence_valid') is not True:
        raise PermissionError('root-bound original-harness admission projection missing')
    row = original.get('public_inputs', {}).get(binding['user_content_sha256'])
    if not isinstance(row, dict) or row.get('qualified') is not True or row.get('original_harness') is not True:
        raise PermissionError('this exact public input has no original-harness calibration admission')
    if row.get('false_acceptances') != [] or type(row.get('unconfirmed_native_attempts')) is not int or row['unconfirmed_native_attempts'] != 0 or type(row.get('wrong_controls_checked')) is not int or row['wrong_controls_checked'] < 3 or row.get('correct_control_passed') is not True or row.get('failure_propagation_confirmed') is not True:
        raise PermissionError('original-harness controls failed or false acceptance retained; exclude')
    if row.get('prompt_sha256') != binding['prompt_sha256'] or row.get('input_context_sha256') != binding['input_context_sha256'] or row.get('output_paths') != binding['output_paths']:
        raise PermissionError('original-harness admission differs from complete public input')
    if isolation.get('schema') != 'natural_os_include_isolation_readonly_audit_v1' or isolation.get('evidence_valid') is not True:
        raise PermissionError('no actual OS/include isolation audit; abstain before model request')
    if isolation.get('historical_fixture_only') is not False or type(isolation.get('real_native_controls')) is not int or isolation['real_native_controls'] < 6 or type(isolation.get('unconfirmed_native_attempts')) is not int or isolation['unconfirmed_native_attempts'] != 0:
        raise PermissionError('OS/include isolation proof is synthetic/incomplete')
    if not all(isolation.get(key) is True for key in ['network_disabled', 'filesystem_escape_denied', 'include_escape_denied',
                                                     'shell_escape_denied', 'resource_limits_verified', 'owned_cleanup_verified']):
        raise PermissionError('OS/include/resource/own cleanup proof is incomplete')
    controls = isolation.get('escape_controls', {})
    if not ESCAPE_CONTROLS.issubset(controls) or any(controls[name] is not True for name in ESCAPE_CONTROLS):
        raise PermissionError('required actual escape controls missing')
    if isolation.get('sandbox_recipe_sha256') != sha(canonical(sandbox_recipe(spec))):
        raise PermissionError('isolation proof does not bind this precise sandbox/tool recipe')
    if need_native:
        if not isinstance(native, dict) or native.get('evidence_complete') is not True or native.get('qualified_for_generated_control_discrimination') is not True:
            raise PermissionError('supported native_reset feedback requires its actual generated-control calibration')
        required_native = dict(native_compile_commands=14, native_simulation_commands=14, global_native_receipts=28,
                               attempted_compile_commands=14, attempted_simulation_commands=14, unconfirmed_native_attempts=0)
        if native.get('spec_sha256') != NATIVE_SPEC_SHA or any(type(native.get(key)) is not int or native[key] != value for key, value in required_native.items()) or native.get('generated_research_test') is not True or native.get('original_harness') is not False:
            raise PermissionError('native_reset control counts/provenance fail')
        order = ['positive', 'reset_ignored', 'synchronous_reset', 'history_sync_only', 'clear_rising_only', 'clear_falling_only', 'constant_zero', 'constant_one', 'swapped_edges', 'two_cycle_pulse', 'one_cycle_late', 'negedge_sample', 'failure_propagation', 'positive_renamed']
        if [row.get('label') for row in native.get('controls', [])] != order or any(row.get('control_matched') is not True or row.get('false_acceptance') is not False for row in native['controls']):
            raise PermissionError('native_reset control false acceptance or missing outcome')
        if any(type(native.get(key)) is not int or native[key] != 0 for key in ('audit_model_calls', 'audit_eda_calls', 'model_calls', 'independent_quality_admitted')) or native.get('eligible_for_independent_models') is not False or native.get('adoption') is not False:
            raise PermissionError('native14 actual zero-model research scope differs')
    return dict(requirements_satisfied=True, real_execution_admitted=False,
                scope='pure document checks only; real file/archive/hash/guard/process/dependency checks remain mandatory')


def _own_path(path):
    import worker
    path = Path(path)
    worker.no_links(path)
    if not path.is_absolute() or not path.resolve().is_relative_to(ROOT / 'raw_evidence'):
        raise PermissionError('proof and execution evidence must stay in own ignored raw_evidence')
    return path


def _bound_report(entry):
    path, archive = _own_path(entry['path']), _own_path(entry['archive_path'])
    if file_sha(path) != entry['sha256'] or file_sha(archive) != entry['archive_sha256']:
        raise PermissionError('bound report/archive bytes differ')
    value = read_json(path)
    if value.get('archive_sha256') != entry['archive_sha256'] or value.get('spec_sha256') != entry['spec_sha256']:
        raise PermissionError('report does not bind its actual archived native/model run')
    kind = entry['kind']
    if kind == 'full156':
        required = dict(spec_sha256=FULL_SPEC_SHA, auditor_sha256=FULL_AUDITOR_SHA,
                        archive_schema='functional_fresh_archive_v1', run_schema='phase_full156_frozen_v1',
                        guard_prefix='guard/')
    elif kind == 'native14':
        required = dict(spec_sha256=NATIVE_SPEC_SHA, auditor_sha256=NATIVE_AUDITOR_SHA,
                        archive_schema='native_reset_generated_research_archive_v1',
                        run_schema='native_reset_generated_research_frozen_v1', guard_prefix='run/guard/')
    elif kind in {'original_harness_projection', 'isolation'}:
        # These future root-owned evidence types still require an actual source
        # archive and externally pinned auditor. A report-only fixture cannot admit.
        required = {key: entry[key] for key in ('spec_sha256', 'auditor_sha256', 'archive_schema', 'run_schema', 'guard_prefix')}
        if value.get('source_evidence') != {key: entry[key] for key in ('spec_sha256', 'archive_sha256', 'auditor_sha256')}:
            raise PermissionError('projection/isolation has no exact actual source evidence binding')
    else:
        raise PermissionError('unknown archived prerequisite type')
    if any(entry.get(key) != expected for key, expected in required.items()):
        raise PermissionError('prerequisite archive type/pinned identity differs')
    cache = (entry['archive_sha256'], tuple(sorted(required.items())))
    if cache not in _BOUND_ARCHIVES:
        with zipfile.ZipFile(archive) as source:
            names = source.namelist()
            if len(names) != len(set(names)):
                raise PermissionError('duplicate prerequisite archive member')
            for name in names:
                safe = PurePosixPath(name)
                if safe.is_absolute() or '..' in safe.parts or '\\' in name:
                    raise PermissionError('unsafe prerequisite archive member')
            manifest = json.loads(source.read('ARCHIVE_MANIFEST.json'), object_pairs_hook=unique, parse_constant=reject_constant)
            if manifest['schema'] != required['archive_schema'] or manifest['run_spec_sha256'] != required['spec_sha256'] or set(names) != set(manifest['files']) | {'ARCHIVE_MANIFEST.json'}:
                raise PermissionError('prerequisite archive manifest type/completeness differs')
            for name, digest in manifest['files'].items():
                if sha(source.read(name)) != digest:
                    raise PermissionError('prerequisite archive SHA differs')
            spec_bytes = source.read('run/RUN_SPEC.json')
            old_spec = json.loads(spec_bytes, object_pairs_hook=unique, parse_constant=reject_constant)
            if sha(spec_bytes) != required['spec_sha256'] or old_spec['schema'] != required['run_schema'] or sha(source.read('run/audit.py')) != required['auditor_sha256']:
                raise PermissionError('actual archived spec/auditor differs')
            for name, digest in old_spec['source_hashes'].items():
                if sha(source.read('run/' + name)) != digest:
                    raise PermissionError('actual archived source bytes differ')
            guard = json.loads(source.read(required['guard_prefix'] + 'status.json'))
            if not all(guard.get(key) is True for key in ('complete', 'passed', 'model_unchanged', 'protected_files_unchanged', 'own_slot_released')) or guard.get('stage_rc') != 0 or guard.get('owned_cleanup', {}).get('verified') is not True or guard['owned_cleanup'].get('remaining'):
                raise PermissionError('prerequisite actual guard/cleanup/release differs')
        _BOUND_ARCHIVES.add(cache)
    return value


def _tree_verify(directory, expected, expected_dirs=None):
    import worker
    directory = Path(directory)
    worker.no_links(directory)
    if not directory.is_absolute() or not directory.is_dir():
        raise PermissionError('fixed dependency directory missing')
    actual, dirs = {}, []
    for path in directory.rglob('*'):
        worker.no_links(path)
        if path.is_file():
            actual[path.relative_to(directory).as_posix()] = file_sha(path)
        elif path.is_dir():
            dirs.append(path.relative_to(directory).as_posix())
        else:
            raise PermissionError('native dependency has nonregular physical entry')
    if actual != expected:
        raise PermissionError('complete fixed dependency manifest differs')
    if expected_dirs is not None and sorted(dirs) != sorted(expected_dirs):
        raise PermissionError('complete physical dependency directory set differs')


def _paired(spec):
    import worker
    path = Path(spec['paired_dependency']['path'])
    worker.no_links(path)
    if str(path) != '/workspace/team/runs/fpga_owner/ross_diagnostic_repair_20261004_v1/paired_checkpoint.py' or spec['paired_dependency']['sha256'] != '78e9b3e144f2bd43ebab371e15ac3946017686db890a8e45891db7a386841e1c' or file_sha(path) != spec['paired_dependency']['sha256']:
        raise PermissionError('paired owned-command dependency differs')
    definition = importlib.util.spec_from_file_location('owned_runtime_paired_commands', path)
    module = importlib.util.module_from_spec(definition)
    definition.loader.exec_module(module)
    return module


def _physical_admission(binding, need_native, first, supervisor_grant=None, work_deadline=None):
    import worker
    import supervisor
    if sys.platform != 'linux':
        raise PermissionError('real IO requires the authorized guarded Linux stage')
    path = ROOT / 'RUN_SPEC.json'
    resource_path = ROOT / 'guard/resource_check.json'
    status_path = ROOT / 'guard/status.json'
    for item in [path, resource_path, status_path]:
        worker.no_links(item)
    spec = read_json(path)
    if Path(spec['cloud_root']).resolve() != ROOT or Path(spec['resource_check']).resolve() != resource_path:
        raise PermissionError('RUN_SPEC/resource do not belong to this exact own namespace')
    for required in ['adapter.py', 'worker.py', 'runtime.py', 'native_reset_contract.py',
                     'INPUT_MANIFEST.json', 'supervisor.py', 'solve_child.py', 'guard_wrapper.py']:
        if required not in spec['source_hashes']:
            raise PermissionError('required own source is not frozen')
    for name, expected in spec['source_hashes'].items():
        worker.portable_path(name)
        worker.no_links(ROOT / name)
        if file_sha(ROOT / name) != expected:
            raise PermissionError('own frozen source changed')
    if file_sha(ROOT / 'adapter.py') != ADAPTER_SHA or file_sha(ROOT / 'native_reset_contract.py') != CONTRACT_SHA:
        raise PermissionError('immutable adapter/contract binding changed')
    full = _bound_report(spec['qualification'])
    original = _bound_report(spec['original_harness_admission'])
    isolation = _bound_report(spec['isolation_admission'])
    native = _bound_report(spec['native_reset_admission']) if need_native else None
    evaluate_documents(spec, full, original, isolation, native, binding, need_native)
    if supervisor_grant is None:
        stage_pid = __import__('os').getpid()
    else:
        child = supervisor.verify_child_admission(supervisor_grant, ROOT)
        stage_pid = child['stage']['pid']
        work_deadline = child['work_deadline_monotonic']
    # The active guard must run the frozen own wrapper as its actual parent.
    # The child branch requires an inherited process-bound grant, never a flag.
    snapshot, _ = supervisor.guard_snapshot(ROOT, stage_pid, work_deadline if work_deadline is not None else time.monotonic() + 5)
    resource = read_json(resource_path)
    if resource.get('slot_owner') != spec['slot_owner'] or resource.get('model_name') != spec['model_name'] or resource.get('llm_base_url') != 'http://127.0.0.1:8000/v1':
        raise PermissionError('own slot/fixed model/loopback resource binding differs')
    if resource.get('model_pid') != spec['model_identity']['pid'] or resource.get('model_starttime') != spec['model_identity']['starttime']:
        raise PermissionError('shared model identity is not the frozen admitted identity')
    if set(spec['model_identity']) != {'pid', 'starttime', 'exe', 'command_sha256'} or resource.get('model_identity') != spec['model_identity']:
        raise PermissionError('complete shared model executable/command identity differs')
    if resource.get('slot_lock_path') != '/workspace/team/SLOT.lock' or spec.get('slot_lock_path') != resource['slot_lock_path']:
        raise PermissionError('actual resource lock is not the authorized shared slot')
    lock = Path(spec['slot_lock_path'])
    worker.no_links(lock)
    lock_bytes = lock.read_bytes()
    if sha(lock_bytes) != resource.get('slot_lock_sha256') or lock_bytes.decode('utf-8').splitlines()[0] != spec['slot_owner']:
        raise PermissionError('current owned lock bytes differ')
    inventory = read_json(ROOT / 'INPUT_MANIFEST.json')
    if len(inventory['input_sha256']) != 936 or len(inventory['official_sha256']) != 35 or resource['protected']['tasks'] != inventory['input_sha256'] or resource['protected']['official'] != inventory['official_sha256']:
        raise PermissionError('fixed protected task/official inventory differs')
    _tree_verify(spec['toolchain']['prefix'], spec['toolchain']['files'])
    if set(spec['real_tools']) != {'iverilog', 'vvp', 'bwrap', 'prlimit'}:
        raise PermissionError('real tool list differs')
    for name, entry in spec['real_tools'].items():
        worker.no_links(Path(entry['path']))
        if file_sha(entry['path']) != entry['sha256']:
            raise PermissionError('real tool bytes differ: ' + name)
    for name in ['iverilog', 'vvp']:
        expected = str(Path(spec['toolchain']['prefix']) / 'bin' / name)
        if spec['real_tools'][name]['path'] != expected:
            raise PermissionError('native compiler is outside the frozen mounted toolchain')
    runtime_root = _own_path(spec['sandbox_runtime_root'])
    if set(spec['runtime_libraries']) != {'/lib', '/lib64', '/usr/lib'}:
        raise PermissionError('only fixed runtime library guest mounts are admitted')
    for guest, entry in spec['runtime_libraries'].items():
        if Path(entry['path']).resolve() != (runtime_root / guest.lstrip('/')).resolve():
            raise PermissionError('runtime library mount is not inside the owned fixed library bundle')
        _tree_verify(entry['path'], entry['files'], entry['directories'])
    paired = _paired(spec)
    stage_key = sha(canonical({key: snapshot[key] for key in ['root', 'spec_sha256', 'resource_sha256', 'stage', 'slot_lock_sha256']}))
    # The guard produces the resource receipt once for the whole FIFO task.
    # Only its first parent admission applies the receipt-age requirement;
    # all subsequent parent and inherited-child calls retain every live check.
    require_fresh = supervisor_grant is None and stage_key not in _STAGE_ADMISSIONS
    paired.check_resource(resource_path, Path(spec['kit']), first=require_fresh)
    if require_fresh:
        _STAGE_ADMISSIONS.add(stage_key)
    return spec, paired


def admit_real(binding, run_root, need_native, supervisor_grant=None):
    import supervisor
    child = supervisor.verify_child_admission(supervisor_grant, ROOT)
    run_root = _own_path(run_root)
    spec, paired = _physical_admission(binding, need_native, first=False, supervisor_grant=supervisor_grant)
    grant = dict(binding=binding, run_root=str(run_root), need_native=bool(need_native),
                 spec_sha256=file_sha(ROOT / 'RUN_SPEC.json'), model_name=spec['model_name'],
                 started_monotonic=child['started_monotonic'], work_deadline_monotonic=child['work_deadline_monotonic'],
                 supervisor_handshake_sha256=child['handshake_sha256'],
                 http_attempts=0, native_attempts=0, model_job_cancellation_confirmed=False)
    _GRANTS[id(grant)] = dict(public=_grant_public(grant), http=0, native=0, supervisor_grant=supervisor_grant)
    return grant


def _grant_public(grant):
    return canonical({key: grant[key] for key in ['binding', 'run_root', 'need_native', 'spec_sha256', 'model_name',
                     'started_monotonic', 'work_deadline_monotonic', 'supervisor_handshake_sha256']})


def revalidate(grant):
    expected = _GRANTS.get(id(grant))
    if expected is None or _grant_public(grant) != expected['public']:
        raise PermissionError('no real own admission token; boolean capability cannot enable IO')
    if type(grant['http_attempts']) is not int or type(grant['native_attempts']) is not int or grant['http_attempts'] != expected['http'] or grant['native_attempts'] != expected['native']:
        raise PermissionError('real attempt accounting changed; cannot loosen frozen caps')
    if file_sha(ROOT / 'RUN_SPEC.json') != grant['spec_sha256']:
        raise PermissionError('RUN_SPEC changed since real admission')
    return _physical_admission(grant['binding'], grant['need_native'], first=False,
                               supervisor_grant=expected['supervisor_grant'])


def _begin_io(grant, kind, label):
    """Persist a conservative attempt before crossing an external IO boundary."""
    if kind not in {'http', 'native'}:
        raise ValueError('unknown IO kind')
    if id(grant) not in _GRANTS:
        raise PermissionError('durable attempts require a runtime-owned grant')
    field, cap = ('http_attempts', 2) if kind == 'http' else ('native_attempts', 6)
    number = grant[field] + 1
    if number > cap:
        raise PermissionError('frozen IO attempt cap exhausted')
    root = _own_path(grant['run_root'])
    folder = root / 'io_attempts'
    import worker
    worker.no_links(folder)
    folder.mkdir(exist_ok=True)
    path = folder / (kind + '_' + str(number) + '.json')
    if path.exists():
        raise PermissionError('IO attempt already exists; no retry or replay')
    receipt = dict(schema='natural_io_attempt_v1', mode='REAL', kind=kind, number=number,
                   label=label, spec_sha256=grant['spec_sha256'], attempted=True,
                   invocation_started=False, confirmed=False, evidence_complete=False,
                   finalized=False, error=None, server_job_cancellation_confirmed=False)
    save(path, receipt)
    grant[field] = number
    _GRANTS[id(grant)][kind] = number
    _ACTIVE_IO[str(path)] = dict(grant=grant, kind=kind)
    return path, receipt


def _finish_io(path, receipt, *, confirmed, evidence_complete, error=None):
    _ACTIVE_IO.pop(str(path), None)
    receipt.update(confirmed=bool(confirmed), evidence_complete=bool(evidence_complete),
                   finalized=True, error=error)
    try:
        save(path, receipt)
    except BaseException:
        receipt.update(confirmed=False, evidence_complete=False)
        raise


def io_accounting(grant):
    """Read durable attempts; missing final receipts remain explicitly unconfirmed."""
    folder = _own_path(grant['run_root']) / 'io_attempts'
    import worker
    worker.no_links(folder)
    rows = []
    if folder.exists():
        for path in sorted(folder.iterdir()):
            worker.no_links(path)
            if not path.is_file() or path.is_symlink():
                raise ValueError('unexpected IO accounting member')
            row = read_json(path)
            if row.get('schema') != 'natural_io_attempt_v1' or row.get('mode') != 'REAL' or row.get('kind') not in {'http', 'native'} or type(row.get('number')) is not int or path.name != row['kind'] + '_' + str(row['number']) + '.json' or row.get('spec_sha256') != grant['spec_sha256'] or row.get('attempted') is not True:
                raise ValueError('durable IO attempt binding differs')
            if row.get('label') not in ({'chat_completions'} if row['kind'] == 'http' else {'candidate_compile', 'feedback_compile', 'feedback_vvp'}):
                raise ValueError('unknown durable IO operation label')
            rows.append(row)
    result = {}
    for kind, field, cap in [('http', 'http_attempts', 2), ('native', 'native_attempts', 6)]:
        if type(grant[field]) is not int or not 0 <= grant[field] <= cap:
            raise ValueError('attempt counters must retain exact admitted integer caps')
        selected = [row for row in rows if row['kind'] == kind]
        if sorted(row['number'] for row in selected) != list(range(1, grant[field] + 1)) or len(selected) > cap:
            raise ValueError('durable IO attempts differ from admitted caps')
        confirmed = sum(row.get('confirmed') is True and row.get('evidence_complete') is True and row.get('finalized') is True and row.get('error') is None for row in selected)
        result[kind + '_attempts'] = len(selected)
        result[kind + '_confirmed'] = confirmed
        result[kind + '_unconfirmed'] = len(selected) - confirmed
        result[kind + '_invocations_started'] = sum(row.get('invocation_started') is True for row in selected)
    result['native_test_attempts'] = sum(row['kind'] == 'native' and row['label'] == 'feedback_vvp' for row in rows)
    result['native_tests_confirmed'] = sum(row['kind'] == 'native' and row['label'] == 'feedback_vvp' and row.get('confirmed') is True and row.get('evidence_complete') is True and row.get('finalized') is True and row.get('error') is None for row in rows)
    return result


def recover_io_accounting(run_root, spec_sha256):
    """Parent-only read of a stopped child's durable attempts, never an IO grant."""
    import worker
    folder = _own_path(run_root) / 'io_attempts'
    worker.no_links(folder)
    groups, residuals, errors = {}, [], []
    for path in sorted(folder.iterdir()) if folder.exists() else []:
        row, valid = None, False
        entry = dict(name=path.name, pending=path.name.endswith('.pending'), parse_valid=False)
        match = re.fullmatch(r'(http|native)_([1-9][0-9]*)\.json(\.pending)?', path.name)
        key = (match[1], int(match[2])) if match else None
        if key is not None:
            groups.setdefault(key, []).append(entry)
        try:
            worker.no_links(path)
            if not path.is_file(): raise ValueError('unexpected recovery directory/member')
            data = path.read_bytes()
            entry.update(sha256=sha(data), bytes=len(data))
            row = json.loads(data, object_pairs_hook=unique, parse_constant=reject_constant)
            if key is None or not isinstance(row, dict) or row.get('schema') != 'natural_io_attempt_v1' or row.get('mode') != 'REAL' or row.get('kind') != key[0] or type(row.get('number')) is not int or row['number'] != key[1] or row.get('spec_sha256') != spec_sha256 or row.get('attempted') is not True:
                raise ValueError('recovered attempt name/spec/schema binding differs')
            if row.get('label') not in ({'chat_completions'} if key[0] == 'http' else {'candidate_compile', 'feedback_compile', 'feedback_vvp'}):
                raise ValueError('recovered operation label differs')
            valid = True
            entry.update(parse_valid=True, row=row)
        except Exception as exc:
            entry['error'] = type(exc).__name__ + ': ' + str(exc)
            errors.append(path.name + ': ' + entry['error'])
        if entry['pending']:
            errors.append(path.name + ': interrupted atomic receipt update retained; confirmation withdrawn')
        residuals.append({key: value for key, value in entry.items() if key != 'row'})
    result = dict(evidence_complete=not errors, recovery_errors=errors, residual_files=residuals,
                  native_test_attempts=0, native_tests_confirmed=0, possibly_started_invocations=0)
    for kind, cap in [('http', 2), ('native', 6)]:
        keys = sorted(key for key in groups if key[0] == kind)
        if [key[1] for key in keys] != list(range(1, len(keys) + 1)) or len(keys) > cap:
            errors.append(kind + ': interrupted ledger sequence/cap differs')
            result['evidence_complete'] = False
        confirmed, entered = 0, 0
        for key in keys:
            members = groups[key]
            rows = [entry['row'] for entry in members if entry['parse_valid']]
            success = len(members) == 1 and not members[0]['pending'] and len(rows) == 1 and rows[0].get('confirmed') is True and rows[0].get('evidence_complete') is True and rows[0].get('finalized') is True and rows[0].get('error') is None
            confirmed += success
            entered += any(row.get('invocation_started') is True for row in rows)
            if not rows:
                result['possibly_started_invocations'] += 1
            if kind == 'native' and any(row['label'] == 'feedback_vvp' for row in rows):
                result['native_test_attempts'] += 1
                result['native_tests_confirmed'] += success
        result.update({kind + '_attempts': len(keys), kind + '_confirmed': confirmed,
                       kind + '_unconfirmed': len(keys) - confirmed, kind + '_invocations_started': entered})
    return result


def request_wire(request, model):
    if set(request) != {'messages', 'max_tokens', 'temperature', 'top_p'} or type(request['max_tokens']) is not int or any(type(request[key]) not in (int, float) for key in ('temperature', 'top_p')) or request['max_tokens'] != 8192 or request['temperature'] != 0 or request['top_p'] != 1:
        raise ValueError('fixed natural request protocol differs')
    if not isinstance(request['messages'], list) or len(request['messages']) != 2 or [row.get('role') for row in request['messages']] != ['system', 'user'] or any(set(row) != {'role', 'content'} or not isinstance(row['content'], str) for row in request['messages']):
        raise ValueError('complete adapted messages required')
    body = canonical(dict(model=model, **request, stream=False))
    head = ('POST ' + ROUTE + ' HTTP/1.1\r\nHost: ' + HOST + ':' + str(PORT) +
            '\r\nContent-Type: application/json\r\nContent-Length: ' + str(len(body)) +
            '\r\nConnection: close\r\n\r\n').encode('ascii')
    return head + body, body


def parse_http(raw, eof=False):
    """Pure strict incremental HTTP framing; raw bytes are never reconstructed."""
    if len(raw) > RAW_HTTP_MAX:
        raise ValueError('raw HTTP evidence exceeds bound')
    marker = raw.find(b'\r\n\r\n')
    if marker < 0:
        if eof:
            raise ValueError('truncated raw HTTP header')
        return None
    lines, body = raw[:marker].split(b'\r\n'), raw[marker + 4:]
    match = re.fullmatch(rb'HTTP/1\.[01] ([1-5][0-9]{2})(?: [^\r\n]*)?', lines[0])
    if not match:
        raise ValueError('invalid/unsupported raw HTTP status')
    headers = {}
    for line in lines[1:]:
        if b':' not in line or line[:1] in (b' ', b'\t'):
            raise ValueError('invalid/folded HTTP header')
        key, value = line.split(b':', 1)
        key = key.decode('ascii').lower()
        if not re.fullmatch(r'[!#$%&\'*+.^_`|~0-9a-z-]+', key):
            raise ValueError('invalid HTTP header name')
        headers.setdefault(key, []).append(value.strip().decode('latin1'))
    if 'content-length' in headers and 'transfer-encoding' in headers:
        raise ValueError('ambiguous HTTP framing')
    if 'transfer-encoding' in headers:
        if headers['transfer-encoding'] != ['chunked']:
            raise ValueError('unknown HTTP transfer encoding')
        offset, decoded = 0, bytearray()
        while True:
            end = body.find(b'\r\n', offset)
            if end < 0:
                if eof:
                    raise ValueError('truncated chunk size')
                return None
            token = body[offset:end]
            if not re.fullmatch(rb'[0-9A-Fa-f]+', token):
                raise ValueError('unsupported/malformed HTTP chunk size')
            size, offset = int(token, 16), end + 2
            if size == 0:
                if len(body) < offset + 2:
                    if eof:
                        raise ValueError('truncated chunk terminator')
                    return None
                if body[offset:] != b'\r\n':
                    raise ValueError('trailers/extra raw response are unsupported')
                body = bytes(decoded)
                break
            if len(body) < offset + size + 2:
                if eof:
                    raise ValueError('truncated HTTP chunk body')
                return None
            if body[offset + size:offset + size + 2] != b'\r\n':
                raise ValueError('invalid chunk separator')
            decoded.extend(body[offset:offset + size])
            offset += size + 2
    elif 'content-length' in headers:
        if len(headers['content-length']) != 1 or not re.fullmatch(r'[0-9]+', headers['content-length'][0]):
            raise ValueError('duplicate/invalid HTTP content-length')
        count = int(headers['content-length'][0])
        if len(body) < count:
            if eof:
                raise ValueError('truncated HTTP body')
            return None
        if len(body) != count:
            raise ValueError('extra bytes after fixed HTTP body')
    elif not eof:
        return None
    return dict(status=int(match[1]), headers=headers, body=body, raw_header=raw[:marker + 4])


def classify_chat(parsed, model):
    data = json.loads(parsed['body'].decode('utf-8'), object_pairs_hook=unique, parse_constant=reject_constant)
    reply, finish = None, 'unknown'
    choices = data.get('choices') if isinstance(data, dict) else None
    if isinstance(choices, list) and len(choices) == 1 and isinstance(choices[0], dict):
        message = choices[0].get('message')
        if isinstance(message, dict) and isinstance(message.get('content'), str):
            reply = message['content']
        finish = choices[0].get('finish_reason', 'unknown')
    confirmed = parsed['status'] == 200 and isinstance(data, dict) and data.get('model') == model and isinstance(choices, list) and len(choices) == 1 and isinstance(choices[0], dict) and type(choices[0].get('index')) is int and choices[0]['index'] == 0 and isinstance(choices[0].get('message'), dict) and choices[0]['message'].get('role') == 'assistant' and isinstance(reply, str) and finish == 'stop'
    return dict(confirmed=confirmed, reply=reply, finish_reason=finish if isinstance(finish, str) else 'unknown'), data


def http_exchange(request, model, timeout, directory, connect, clock=time.monotonic, *, mode='FAKE', attempt_path=None):
    """IO protocol helper: callers MUST inject connect; tests use in-memory sockets."""
    started = clock()
    if mode not in {'FAKE', 'REAL'} or (mode == 'FAKE' and getattr(connect, 'io_kind', None) != 'FAKE'):
        raise PermissionError('explicit FAKE byte source or runtime-owned REAL admission required')
    if mode == 'REAL' and (connect is not socket.create_connection or attempt_path is None):
        raise PermissionError('REAL transport requires a durable admitted attempt')
    if mode == 'REAL':
        active = _ACTIVE_IO.get(str(attempt_path))
        if active is None or active['kind'] != 'http':
            raise PermissionError('REAL helper is outside an active admitted HTTP attempt')
        revalidate(active['grant'])
    directory = _own_path(directory)
    directory.mkdir(exist_ok=False)
    evidence = dict(schema='natural_http_receipt_v1', mode=mode, endpoint=ENDPOINT,
                    attempted=True, invocation_started=False, request_sent=False,
                    response_observed=False, response_confirmed=False, evidence_complete=False, finalized=False,
                    server_job_cancellation_confirmed=False, error=None, close_error=None,
                    finalization_error=None, timeout_s=timeout, status=None)
    save(directory / 'HTTP_ATTEMPT.json', evidence)
    raw, sock = bytearray(), None
    result = dict(confirmed=False, reply=None, finish_reason='unknown')
    try:
        def remaining():
            seconds = timeout - (clock() - started)
            if seconds <= 0:
                raise TimeoutError('HTTP client deadline reached; server job cancellation remains unconfirmed')
            return seconds
        wire, body = request_wire(request, model)
        evidence['request_wire_sha256'] = new_bytes(directory / 'request.http', wire)
        evidence['request_body_sha256'] = new_bytes(directory / 'request.json', body)
        connect_timeout = remaining()
        evidence['invocation_started'] = True
        save(directory / 'HTTP_ATTEMPT.json', evidence)
        if attempt_path is not None:
            attempt = read_json(attempt_path)
            attempt['invocation_started'] = True
            save(attempt_path, attempt)
        sock = connect((HOST, PORT), timeout=connect_timeout)
        sock.settimeout(remaining())
        sock.sendall(wire)
        evidence['request_sent'] = True
        with (directory / 'response.http').open('xb') as stream:
            while True:
                sock.settimeout(remaining())
                block = sock.recv(65536)
                if block:
                    raw.extend(block)
                    stream.write(block)
                    stream.flush()
                parsed = parse_http(bytes(raw), eof=not block)
                if parsed is not None:
                    evidence['response_observed'] = True
                    new_bytes(directory / 'response_body.bin', parsed['body'])
                    new_bytes(directory / 'response_header.bin', parsed['raw_header'])
                    evidence['status'] = parsed['status']
                    candidate_result, decoded = classify_chat(parsed, model)
                    save(directory / 'decoded_http_body.json', decoded)
                    result = candidate_result
                    evidence['response_confirmed'] = result['confirmed']
                    break
                if not block:
                    raise ValueError('unconfirmed empty/incomplete HTTP reply')
    except (TimeoutError, socket.timeout) as exc:
        result = dict(confirmed=False, reply=None, finish_reason='timeout')
        evidence['error'] = type(exc).__name__ + ': ' + str(exc)
    except Exception as exc:
        result = dict(confirmed=False, reply=None, finish_reason='unknown')
        evidence['error'] = type(exc).__name__ + ': ' + str(exc)
    finally:
        if sock is not None:
            try:
                sock.close()
            except Exception as exc:
                evidence['close_error'] = type(exc).__name__ + ': ' + str(exc)
                evidence['error'] = evidence['error'] or evidence['close_error']
                result = dict(confirmed=False, reply=None, finish_reason='unknown')
        evidence['raw_response_sha256'] = sha(bytes(raw))
        evidence['raw_response_bytes'] = len(raw)
        evidence['elapsed_s'] = clock() - started
        if evidence['elapsed_s'] >= timeout and evidence['error'] is None:
            evidence['error'] = 'HTTP budget exhausted during evidence finalization'
            result = dict(confirmed=False, reply=None, finish_reason='timeout')
        evidence.update(finalized=True, response_confirmed=result['confirmed'], evidence_complete=evidence['error'] is None)
        try:
            save(directory / 'HTTP_RECEIPT.json', evidence)
            final_elapsed = clock() - started
            if final_elapsed >= timeout and result['confirmed']:
                result = dict(confirmed=False, reply=None, finish_reason='timeout')
                evidence.update(response_confirmed=False, evidence_complete=False,
                                error='HTTP budget exhausted while saving final receipt', elapsed_s=final_elapsed)
                save(directory / 'HTTP_RECEIPT.json', evidence)
        except BaseException as exc:
            result = dict(confirmed=False, reply=None, finish_reason='unknown')
            evidence.update(response_confirmed=False, evidence_complete=False, finalization_error=type(exc).__name__ + ': ' + str(exc))
            raise
    return result


def real_transport(grant, request, timeout):
    started = time.monotonic()
    revalidate(grant)  # always before any actual socket creation
    path, attempt = _begin_io(grant, 'http', 'chat_completions')
    directory = Path(grant['run_root']) / ('actual_http_' + str(grant['http_attempts']))
    confirmed, complete, error = False, False, None
    try:
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0:
            raise TimeoutError('real admission exhausted current solve budget before socket creation')
        result = http_exchange(request, grant['model_name'], remaining, directory, socket.create_connection,
                               mode='REAL', attempt_path=path)
        receipt = read_json(directory / 'HTTP_RECEIPT.json')
        attempt['invocation_started'] = receipt['invocation_started']
        attempt['request_sent'] = receipt['request_sent']
        confirmed, complete, error = result['confirmed'], receipt['evidence_complete'], receipt['error']
        return result
    except BaseException as exc:
        durable = read_json(path)
        attempt['invocation_started'] = durable.get('invocation_started') is True
        error = type(exc).__name__ + ': ' + str(exc)
        raise
    finally:
        _finish_io(path, attempt, confirmed=confirmed, evidence_complete=complete, error=error)


def sandbox_argv(spec, input_root, output_root, native_argv, seconds):
    """One explicit native process tree with readonly public inputs and no host root."""
    if seconds <= NATIVE_CLEANUP_RESERVE:
        raise TimeoutError('not enough whole-solve time for own native cleanup reserve')
    argv = [spec['real_tools']['prlimit']['path'], '--as=' + str(spec['limits']['native_as_bytes']),
            '--fsize=' + str(spec['limits']['native_fsize_bytes']), '--cpu=' + str(max(1, math.ceil(seconds - NATIVE_CLEANUP_RESERVE))), '--',
            spec['real_tools']['bwrap']['path'], '--unshare-all', '--die-with-parent', '--clearenv',
            '--tmpfs', '/', '--dir', '/usr', '--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',
            '--ro-bind', spec['toolchain']['prefix'], '/tools']
    for guest, entry in sorted(spec['runtime_libraries'].items()):
        argv.extend(['--ro-bind', entry['path'], guest])
    argv.extend(['--ro-bind', str(input_root), '/inputs', '--bind', str(output_root), '/outputs',
                 '--chdir', '/outputs', '--setenv', 'PATH', '/tools/bin', '--', *native_argv])
    return argv


def verify_public_package(package, binding):
    import worker
    required = {'public_hdl', 'source_paths', 'header_paths', 'output_paths', 'resolved_includes', 'mode', 'include_isolation'}
    if set(package) != required or package['output_paths'] != binding['output_paths']:
        raise ValueError('compiler public package/output binding differs')
    expected = {name for name in [*binding['input_context_sha256'], *binding['output_paths']]
                if PurePosixPath(name).suffix.lower() in worker.HDL_EXTENSIONS}
    if set(package['public_hdl']) != expected:
        raise ValueError('public HDL context/helper/target set differs; never drop dependencies')
    files = {}
    for name, entry in package['public_hdl'].items():
        worker.portable_path(name)
        if set(entry) != {'path', 'sha256'}:
            raise ValueError('unexpected compiler input fields')
        path = _own_path(entry['path'])
        data = path.read_bytes()
        if sha(data) != entry['sha256']:
            raise ValueError('public compiler physical input SHA differs')
        if name not in binding['output_paths'] and entry['sha256'] != binding['input_context_sha256'][name]:
            raise ValueError('public helper content was changed')
        files[name] = data
    if package['source_paths'] != [name for name in package['public_hdl'] if PurePosixPath(name).suffix.lower() in worker.SOURCE_EXTENSIONS] or package['header_paths'] != [name for name in package['public_hdl'] if PurePosixPath(name).suffix.lower() not in worker.SOURCE_EXTENSIONS]:
        raise ValueError('native sources/headers differ from all public HDL')
    if package['mode'] != 'REAL':
        raise PermissionError('physical real compiler requires actual admitted IO mode')
    resolved = []
    directories = {PurePosixPath(name).parent for name in files}
    for name, data in files.items():
        for match in re.finditer(r'`include\b([^\r\n]*)', data.decode('utf-8')):
            operand = re.fullmatch(r'"([^"\r\n]+)"\s*(?://[^\r\n]*)?', match[1].strip())
            if operand is None:
                raise ValueError('macro/unknown include resolution is unverified')
            include = worker.portable_path(operand[1])
            intended = (PurePosixPath(name).parent / include).as_posix()
            possible = {(directory / include).as_posix() for directory in directories} & set(files)
            if intended not in files or possible != {intended}:
                raise ValueError('missing/ambiguous same-name include; actual compiler search not qualified')
            resolved.append(dict(source=name, dependency=intended))
    marker = 'REAL_BOUND_OS_AUDIT' if resolved else 'NO_INCLUDE_DIRECTIVE_DETECTED'
    if package['resolved_includes'] != resolved or package['include_isolation'] != marker:
        raise ValueError('public include receipt/actual isolation marker differs')
    return files


def _native_run(grant, files, native_argv, timeout, label):
    started = time.monotonic()
    spec, paired = revalidate(grant)  # full real guard and isolation proof before EDA
    if label not in {'candidate_compile', 'feedback_compile', 'feedback_vvp'}:
        raise ValueError('unknown native operation label')
    attempt_path, attempt = _begin_io(grant, 'native', label)
    next_attempt = grant['native_attempts']
    directory = Path(grant['run_root']) / ('actual_native_' + str(next_attempt) + '_' + label)
    receipt = dict(schema='natural_native_receipt_v1', mode='REAL', label=label, attempted=True,
                   invocation_started=False, command_confirmed=False, evidence_complete=False, finalized=False,
                   error=None, argv=None, native_argv=native_argv, source_input_sha256={},
                   real_tool_sha256=spec['real_tools']['vvp' if label == 'feedback_vvp' else 'iverilog']['sha256'],
                   sandbox_recipe_sha256=sha(canonical(sandbox_recipe(spec))), compiled_blob=None,
                   server_job_cancellation_confirmed=False)
    confirmed, complete, error = False, False, None
    result = dict(outcome='unconfirmed', diagnostics='', receipt=receipt, directory=directory)
    try:
        directory.mkdir(exist_ok=False)
        inputs, outputs = directory / 'inputs', directory / 'outputs'
        inputs.mkdir(); outputs.mkdir()
        hashes = {}
        for name, data in files.items():
            import worker
            worker.portable_path(name)
            if not isinstance(data, bytes):
                raise ValueError('exact native public input bytes required')
            hashes[name] = new_bytes(inputs.joinpath(*PurePosixPath(name).parts), data)
        receipt['source_input_sha256'] = hashes
        remaining = timeout - (time.monotonic() - started)
        argv = sandbox_argv(spec, inputs, outputs, native_argv, remaining)
        receipt['argv'] = argv
        save(directory / 'NATIVE_INPUT.json', receipt)
        remaining = timeout - (time.monotonic() - started)
        if remaining <= NATIVE_CLEANUP_RESERVE:
            raise TimeoutError('native preparation exhausted cleanup-reserved whole solve budget')
        attempt['invocation_started'] = receipt['invocation_started'] = True
        save(attempt_path, attempt)
        save(directory / 'NATIVE_INPUT.json', receipt)
        command = paired.owned_command(argv, directory, directory / 'native.log', remaining - NATIVE_CLEANUP_RESERVE)
        receipt['command'] = command
        receipt['input_unchanged'] = all(file_sha(inputs.joinpath(*PurePosixPath(name).parts)) == value for name, value in hashes.items())
        blob = outputs / 'compiled.vvp'
        if blob.exists():
            data = blob.read_bytes()
            receipt['compiled_blob'] = dict(path='compiled.vvp', sha256=new_bytes(directory / 'compiled.vvp', data), bytes=len(data))
        raw_log = (directory / 'native.log').read_bytes()
        receipt['outer_log_sha256'], receipt['outer_log_bytes'] = sha(raw_log), len(raw_log)
        known = receipt['input_unchanged'] and command['timeout'] is False and command['launch_error'] is None and not command['remaining_live_group'] and type(command['returncode']) is int and command['returncode'] >= 0
        if not known:
            error = 'native command or cleanup unconfirmed; preserve evidence without retry'
        elif time.monotonic() - started >= timeout:
            error = 'native budget exhausted during evidence finalization'
        else:
            confirmed, complete = True, True
            result.update(outcome='passed' if command['returncode'] == 0 else 'failed',
                          diagnostics=raw_log.decode('utf-8', errors='replace'))
    except BaseException as exc:
        error = type(exc).__name__ + ': ' + str(exc)
        receipt['error'] = error
        raise
    finally:
        receipt.update(command_confirmed=confirmed, evidence_complete=complete, finalized=True, error=error,
                       elapsed_s=time.monotonic() - started)
        try:
            if directory.exists():
                save(directory / 'NATIVE_RECEIPT.json', receipt)
            if time.monotonic() - started >= timeout:
                confirmed, complete = False, False
                error = 'native budget exhausted while sealing evidence; confirmation withdrawn'
                result.update(outcome='unconfirmed', diagnostics='')
                receipt.update(command_confirmed=False, evidence_complete=False, error=error)
                save(directory / 'NATIVE_RECEIPT.json', receipt)
        except BaseException as exc:
            confirmed, complete = False, False
            error = 'native receipt finalization failed: ' + type(exc).__name__ + ': ' + str(exc)
            raise
        finally:
            _finish_io(attempt_path, attempt, confirmed=confirmed, evidence_complete=complete, error=error)
        if time.monotonic() - started >= timeout and confirmed:
            confirmed, complete = False, False
            error = 'native ledger sealing exhausted budget; confirmation withdrawn'
            result.update(outcome='unconfirmed', diagnostics='')
            receipt.update(command_confirmed=False, evidence_complete=False, error=error)
            save(directory / 'NATIVE_RECEIPT.json', receipt)
            _finish_io(attempt_path, attempt, confirmed=False, evidence_complete=False, error=error)
    return result


def compiler_argv(files, probe=None):
    sources = [name for name in files if PurePosixPath(name).suffix.lower() in {'.sv', '.v'}]
    dirs = sorted({str(PurePosixPath('/inputs') / PurePosixPath(name).parent) for name in files})
    argv = ['/tools/bin/iverilog', '-B', '/tools/lib/ivl', '-g2012', '-o', '/outputs/compiled.vvp']
    if probe:
        argv.extend(['-s', probe])  # only selects generated research TB; never renames DUT
    for directory in dirs:
        argv.extend(['-I', directory])
    return [*argv, *['/inputs/' + name for name in sources]]


def real_compiler(grant, package, timeout, plan):
    started = time.monotonic()
    revalidate(grant)
    input_sha = sha((json.dumps(package, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    files = verify_public_package(package, grant['binding'])
    built = _native_run(grant, files, compiler_argv(files), timeout - (time.monotonic() - started), 'candidate_compile')
    result = dict(outcome=built['outcome'], diagnostics=built['diagnostics'], input_sha256=input_sha)
    if built['outcome'] != 'passed':
        return result
    artifact = built['receipt']['compiled_blob']
    if artifact is None or not (built['directory'] / artifact['path']).read_bytes().startswith(b'#!'):
        return dict(outcome='unconfirmed', diagnostics='', input_sha256=input_sha)
    if not plan['native_feedback_required']:
        return dict(outcome='passed', diagnostics='', input_sha256=input_sha)
    import native_reset_contract as contract
    run_id = uuid.uuid4().hex
    tb = contract.render_tb(plan['contract'], run_id)
    probe = re.search(r'\bmodule\s+(\w+)\s*;', tb)[1]
    if any(re.search(r'\bmodule\s+' + re.escape(probe) + r'\b', data.decode('utf-8')) for data in files.values()):
        raise ValueError('generated probe name conflicts with public design; no repair diagnostic')
    tb_path = '_research/native_reset_' + run_id + '.sv'
    if tb_path in files:
        raise ValueError('generated research TB path conflicts with public input; never overwrite context')
    research_files = {**files, tb_path: tb.encode('utf-8')}
    remaining = timeout - (time.monotonic() - started)
    research = _native_run(grant, research_files, compiler_argv(research_files, probe), remaining, 'feedback_compile')
    if research['outcome'] != 'passed' or research['receipt']['compiled_blob'] is None:
        return dict(outcome='unconfirmed', diagnostics='', input_sha256=input_sha)
    blob = (research['directory'] / 'compiled.vvp').read_bytes()
    remaining = timeout - (time.monotonic() - started)
    simulated = _native_run(grant, {'compiled.vvp': blob}, ['/tools/bin/vvp', '/inputs/compiled.vvp'], remaining, 'feedback_vvp')
    if simulated['outcome'] == 'unconfirmed':
        return dict(outcome='unconfirmed', diagnostics='', input_sha256=input_sha)
    log = (simulated['directory'] / 'native.log').read_text(encoding='utf-8', errors='strict')
    parsed = contract.observations(log, plan['contract'], run_id)
    save(simulated['directory'] / 'PARSED.json', parsed)
    save(simulated['directory'] / 'RESEARCH_BINDING.json', dict(contract_sha256=CONTRACT_SHA, prompt_sha256=plan['contract']['prompt_sha256'],
         tb_sha256=sha(tb.encode()), run_id=run_id, generated_research_test=True, original_harness=False))
    rc = simulated['receipt']['command']['returncode']
    if parsed['mismatches'] == 0 and rc == 0:
        return dict(outcome='passed', diagnostics='', input_sha256=input_sha)
    if parsed['mismatches'] > 0 and rc == 1:
        feedback = contract.counterexample(log, plan['contract'], run_id)
        return dict(outcome='failed', diagnostics=json.dumps(dict(scope='actual generated public-contract native feedback; not hidden judge', **feedback), ensure_ascii=False), input_sha256=input_sha)
    return dict(outcome='unconfirmed', diagnostics='', input_sha256=input_sha)


def make_real_clients(binding, run_root, plan, supervisor_grant=None):
    grant = admit_real(binding, run_root, plan['native_feedback_required'], supervisor_grant=supervisor_grant)
    def transport(request, timeout):
        return real_transport(grant, request, timeout)
    def compiler(package, timeout):
        return real_compiler(grant, package, timeout, plan)
    transport.io_kind = compiler.io_kind = 'REAL'
    # This flag is derived only after actual bound OS/include gates, never caller input.
    compiler.include_isolation_verified = True
    transport.real_grant = compiler.real_grant = grant
    return transport, compiler, grant


def solve_real(record, arm, run_root, generation, repair, supervisor_grant=None):
    import supervisor
    child = supervisor.verify_child_admission(supervisor_grant, ROOT)
    import worker
    view = worker.adapter.task_view(record)
    binding = worker.adapter.binding(record, view)
    plan = feedback_plan(view['prompt'], arm)
    transport, compiler, grant = make_real_clients(binding, run_root, plan, supervisor_grant=supervisor_grant)
    return worker.solve(record, arm, run_root, generation, repair, transport, compiler,
                        real_grant=grant, solve_started=child['started_monotonic'])


def supervised_payload(record, arm, run_root, generation, repair):
    """Retain only complete public input and empty requested output placeholders."""
    import worker
    view = worker.adapter.task_view(record)
    worker.validate_file_set(view)
    worker.adapter.research_skill(generation, repair)
    if arm not in {'C', 'P'}:
        raise ValueError('new integration arm must be C or P')
    return dict(schema='natural_supervised_public_task_v1', arm=arm, run_root=str(_own_path(run_root)),
                record=dict(input=dict(prompt=view['prompt'], context=view['context']),
                            output=dict(response='', context={name: '' for name in view['output_paths']})),
                generation=generation, repair=repair)


def solve_supervised(record, arm, run_root, generation, repair, evidence_dir):
    """Actual main guarded stage entry; all preparation shares the 300s budget."""
    started = time.monotonic()
    import supervisor
    import worker
    payload = supervised_payload(record, arm, run_root, generation, repair)
    view = worker.adapter.task_view(payload['record'])
    binding = worker.adapter.binding(payload['record'], view)
    plan = feedback_plan(view['prompt'], arm)
    work_deadline = supervisor.deadlines(started)['work_deadline_monotonic']
    spec, _ = _physical_admission(binding, plan['native_feedback_required'], first=True, work_deadline=work_deadline)
    evidence = _own_path(evidence_dir)
    if evidence == Path(payload['run_root']) or evidence.is_relative_to(Path(payload['run_root'])) or Path(payload['run_root']).is_relative_to(evidence):
        raise ValueError('supervisor and worker evidence roots must be disjoint')
    # Parent preparation is distinct from the supervisor's exclusively new root.
    prepared = _own_path(evidence.with_name(evidence.name + '_prepared'))
    worker_root = Path(payload['run_root'])
    if prepared == worker_root or prepared.is_relative_to(worker_root) or worker_root.is_relative_to(prepared):
        raise ValueError('prepared task and worker evidence roots must be disjoint')
    prepared.mkdir(parents=True, exist_ok=False)
    payload_path = prepared / 'PUBLIC_TASK.json'
    payload_sha = save(payload_path, payload)
    config = spec['supervisor']
    if config['child_entry'] != 'solve_child.py':
        raise PermissionError('natural runtime has one fixed supervised child entry')
    argv = [config['python_executable'], str(ROOT / 'solve_child.py'), str(payload_path), payload_sha]
    receipt = supervisor.run_supervised(argv, evidence, ROOT, started_monotonic=started)
    recovered = None
    if receipt.get('owned_cleanup', {}).get('verified') is True:
        try:
            recovered = recover_io_accounting(payload['run_root'], file_sha(ROOT / 'RUN_SPEC.json'))
        except Exception as exc:
            recovered = dict(evidence_complete=False, recovery_errors=[type(exc).__name__ + ': ' + str(exc)],
                             preserved_attempts_path=str(Path(payload['run_root']) / 'io_attempts'))
        save(prepared / 'RECOVERED_IO_ACCOUNTING.json', dict(counts=recovered,
             child_completed=receipt.get('child_returncode') == 0, retry=False,
             real_execution_admitted=False, quality_verified=False, model_job_cancellation_confirmed=False))
    parent_receipt = dict(schema='natural_supervised_parent_receipt_v1', complete=True,
                          passed=receipt.get('passed') is True and isinstance(recovered, dict) and recovered.get('evidence_complete') is True and recovered.get('http_unconfirmed') == 0 and recovered.get('native_unconfirmed') == 0 and time.monotonic() < started + 300,
                          started_monotonic=started, elapsed_s=time.monotonic() - started,
                          recovered_io_counts=recovered, quality_verified=False, adoption=False,
                          model_job_cancellation_confirmed=False)
    save(prepared / 'PARENT_ENTRY_RECEIPT.json', parent_receipt)
    if time.monotonic() >= started + 300:
        parent_receipt.update(passed=False, elapsed_s=time.monotonic() - started,
                              error='parent recovered accounting/receipt exceeded absolute solve budget')
        save(prepared / 'PARENT_ENTRY_RECEIPT.json', parent_receipt)
    if parent_receipt['passed'] is not True:
        raise RuntimeError('owned solve supervision failed; stop enclosing stage and retain slot until outer guard confirms idle/cleanup')
    return receipt
