"""DRAFT new natural integration factor, based on frozen FAKE worker 852f346d.

FAKE controls remain available; REAL callbacks require runtime-owned admission.
This does not faithfully migrate the old C/P/ANSI early-return policy.
"""
from pathlib import Path, PurePosixPath
import hashlib
import importlib.util
import json
import os
import re
import time

ROOT = Path(__file__).resolve().parent
RAW = ROOT / 'raw_evidence'
ADAPTER_SHA = '9b41ef3adfd345ff037ee4dcd3ef918d991c3bc5e52562ed8bc309355e0a39f9'
MAX_REQUESTS = 2
MAX_TOKENS = 8192
SOLVE_SECONDS = 300.0
HDL_EXTENSIONS = {'.v', '.sv', '.vh', '.svh'}
SOURCE_EXTENSIONS = {'.v', '.sv'}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')


def canonical_bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def load_adapter():
    path = ROOT / 'adapter.py'
    if digest(path.read_bytes()) != ADAPTER_SHA:
        raise ValueError('immutable adapter SHA mismatch')
    spec = importlib.util.spec_from_file_location('owned_natural_immutable_adapter', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


adapter = load_adapter()


def no_links(path):
    """Reject existing symlinks/junctions in every physical path component."""
    path = Path(path).absolute()
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink() or (hasattr(current, 'is_junction') and current.is_junction()):
            raise ValueError('symbolic link or junction is forbidden')
    return path


def owned_run_root(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('run directory must be an absolute owned path')
    no_links(RAW)
    no_links(path)
    if path == RAW or not path.resolve().is_relative_to(RAW.resolve()):
        raise ValueError('all task evidence must stay in owned ignored raw_evidence')
    return path


def portable_path(path):
    adapter.safe_path(path)
    if path == '.' or not PurePosixPath(path).parts:
        raise ValueError('public path must name a file')
    for part in PurePosixPath(path).parts:
        if part.endswith(('.', ' ')) or any(char in part for char in '<>"|?*'):
            raise ValueError('nonportable public path')
        stem = part.split('.', 1)[0].upper()
        if stem in {'CON', 'PRN', 'AUX', 'NUL'} or re.fullmatch(r'(?:COM|LPT)[1-9]', stem):
            raise ValueError('reserved public path')
    return path


def validate_file_set(view):
    """Exact output/context overlap is a partial design; all other aliases conflict."""
    names = list(dict.fromkeys([*view['context'], *view['output_paths']]))
    folded = {}
    for name in names:
        portable_path(name)
        key = name.casefold()
        if key in folded and folded[key] != name:
            raise ValueError('case alias conflict')
        folded[key] = name
    keys = set(folded)
    for key in keys:
        parts = PurePosixPath(key).parts
        if any('/'.join(parts[:end]) in keys for end in range(1, len(parts))):
            raise ValueError('file/directory conflict')


def save_json(path, value):
    path = Path(path)
    no_links(path)
    pending = path.with_name(path.name + '.pending')
    no_links(pending)
    with pending.open('xb') as stream:
        stream.write(json_bytes(value))
    pending.replace(path)
    return digest(path.read_bytes())


def write_text_new(path, content):
    path = Path(path)
    no_links(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    no_links(path)
    with path.open('xb') as stream:
        stream.write(content.encode('utf-8'))
    return digest(path.read_bytes())


def materialize_new(root, files):
    root = Path(root)
    no_links(root)
    root.mkdir(exist_ok=False)
    hashes = {}
    for name, text in files.items():
        portable_path(name)
        path = root.joinpath(*PurePosixPath(name).parts)
        if not path.absolute().is_relative_to(root.absolute()):
            raise ValueError('public file escapes its physical directory')
        hashes[name] = write_text_new(path, text)
    verify_files(root, files, hashes)
    return hashes


def verify_files(root, files, hashes):
    root = Path(root)
    no_links(root)
    for path in root.rglob('*'):
        no_links(path)
    actual = {path.relative_to(root).as_posix() for path in root.rglob('*') if path.is_file()}
    if actual != set(files):
        raise ValueError('physical public file set changed')
    for name, text in files.items():
        path = root.joinpath(*PurePosixPath(name).parts)
        if digest(path.read_bytes()) != hashes[name] or path.read_bytes() != text.encode('utf-8'):
            raise ValueError('physical public content changed')


def compile_package(root, files, hashes, targets, compiler):
    """Only public candidate/context HDL paths cross this injected compiler boundary."""
    hdl = {name: text for name, text in files.items() if PurePosixPath(name).suffix.lower() in HDL_EXTENSIONS}
    if any(PurePosixPath(name).suffix.lower() not in SOURCE_EXTENSIONS for name in targets):
        raise ValueError('prototype cannot compile a non-HDL output target; abstain')
    directives = [(name, match.group(1).strip()) for name, text in hdl.items()
                  for match in re.finditer(r'`include\b([^\n\r]*)', text)]
    if directives and getattr(compiler, 'include_isolation_verified', False) is not True:
        raise ValueError('include isolation is unverified; abstain without dropping dependencies')
    resolved = []
    for name, operand in directives:
        match = re.fullmatch(r'"([^"\n\r]+)"\s*(?://[^\n\r]*)?', operand)
        if not match:
            raise ValueError('include operand cannot be safely resolved by prototype; abstain')
        include = portable_path(match.group(1))
        dependency = (PurePosixPath(name).parent / include).as_posix()
        portable_path(dependency)
        if dependency not in hdl:
            raise ValueError('include dependency is not present as public HDL; abstain')
        resolved.append({'source': name, 'dependency': dependency})
    public_hdl = {name: dict(path=str(Path(root).joinpath(*PurePosixPath(name).parts)), sha256=hashes[name]) for name in hdl}
    package = dict(public_hdl=public_hdl, source_paths=[name for name in hdl if PurePosixPath(name).suffix.lower() in SOURCE_EXTENSIONS],
                   header_paths=[name for name in hdl if PurePosixPath(name).suffix.lower() not in SOURCE_EXTENSIONS],
                   output_paths=list(targets), resolved_includes=resolved, mode=getattr(compiler, 'io_kind', 'UNKNOWN'),
                   include_isolation=('REAL_BOUND_OS_AUDIT' if getattr(compiler, 'io_kind', None) == 'REAL' else 'FAKE_CAPABILITY_ONLY') if directives else 'NO_INCLUDE_DIRECTIVE_DETECTED')
    return package


def invoke_fake(callback, argument, timeout, folder, label):
    """Keep before/after snapshots even on callback exception; detect argument mutation."""
    folder = Path(folder)
    before = canonical_bytes(argument)
    before_file = label + '_input_before_callback.json'
    after_file = label + '_input_after_callback.json'
    before_hash = write_text_new(folder / before_file, before.decode('utf-8'))
    returned, callback_error = None, None
    try:
        returned = callback(argument, timeout)
    except Exception as exc:
        callback_error = exc
    try:
        after = canonical_bytes(argument)
        after_canonical_hash = digest(after)
    except Exception as exc:
        # An unserializable mutated object cannot have a faithful JSON snapshot.
        # Preserve its representation explicitly and reject, never label it equal.
        after = canonical_bytes(dict(unserializable_argument_repr=repr(argument), snapshot_error=type(exc).__name__ + ': ' + str(exc)))
        after_canonical_hash = None
    after_hash = write_text_new(folder / after_file, after.decode('utf-8'))
    info = dict(before_snapshot=before_file, after_snapshot=after_file,
                before_snapshot_sha256=before_hash, after_snapshot_sha256=after_hash,
                before_canonical_sha256=digest(before), after_canonical_sha256=after_canonical_hash,
                callback_input_mutated=after_canonical_hash != digest(before),
                callback_exception=None if callback_error is None else type(callback_error).__name__ + ': ' + str(callback_error),
                external_callback_fidelity_verified=False)
    save_json(folder / (label + '_callback_binding.json'), info)
    return returned, callback_error, info


def solve(record, arm, run_root, generation, repair, transport, compiler, clock=time.monotonic, real_grant=None, solve_started=None):
    """Two requests maximum; REAL requires fresh actual runtime gates before IO."""
    started = clock() if solve_started is None else solve_started
    if arm not in {'C', 'P'}:
        raise ValueError('prototype arm must be C or P')
    mode = getattr(transport, 'io_kind', None)
    if mode not in {'FAKE', 'REAL'} or getattr(compiler, 'io_kind', None) != mode:
        raise ValueError('callbacks must explicitly share FAKE or admitted REAL mode')
    if mode == 'REAL':
        import runtime
        runtime.revalidate(real_grant)
        if started != real_grant['started_monotonic'] or clock is not time.monotonic:
            raise PermissionError('REAL worker must inherit the actual supervisor clock and start')
    work_deadline = real_grant['work_deadline_monotonic'] if mode == 'REAL' else started + SOLVE_SECONDS
    root = owned_run_root(run_root)
    root.mkdir(parents=True, exist_ok=False)
    state = dict(schema='natural_runtime_integration_v1', mode=mode, arm=arm, status='preparing', complete=False,
                 adapter_sha256=ADAPTER_SHA, worker_sha256=digest(Path(__file__).read_bytes()),
                 request_limit=MAX_REQUESTS, max_tokens=MAX_TOKENS, temperature=0, top_p=1, solve_timeout_s=SOLVE_SECONDS,
                 transport_invocations=0, compiler_invocations=0, attempts=[], input_binding=None,
                 callback_input_mutation_detected=False, external_callback_fidelity_verified=False,
                 actual_model_calls=0, actual_eda_calls=0, actual_native_tests=0, quality_verified=False,
                 eligible_for_independent_models=False, adoption=False, arms_policy_integrated=False,
                 model_job_cancellation_confirmed=False, frozen_policy_equivalence=False,
                 work_deadline_monotonic=work_deadline, work_budget_s=work_deadline - started,
                 error=None, gaps=['ANSI early-return and original C/P policy are not faithfully migrated; this is a new integration factor.',
                                   'Real IO functions require unprovided actual qualification/native/isolation/guard evidence; no fresh model score is certified.',
                                   'HTTP timeout does not prove server-side model-job cancellation; hidden original runner/judge remains outside this solver.'])
    phase = 'input'

    def remaining():
        seconds = work_deadline - clock()
        if seconds <= 0:
            raise TimeoutError('whole solve deadline exhausted; no retry or resampling')
        return seconds

    def checkpoint():
        save_json(root / 'summary.json', state)

    try:
        remaining()
        view = adapter.task_view(record)
        validate_file_set(view)
        state['input_binding'] = adapter.binding(record, view)
        state['public_input_sha256'] = save_json(root / 'public_input.json', view)
        original_context_hashes = materialize_new(root / 'public_context', view['context'])
        state['original_context_sha256'] = original_context_hashes
        checkpoint()
        previous, diagnostics = None, None
        for number in range(1, MAX_REQUESTS + 1):
            phase = 'binding'
            remaining()
            if adapter.binding(record, view) != state['input_binding']:
                raise ValueError('original public input binding changed')
            verify_files(root / 'public_context', view['context'], original_context_hashes)
            if mode == 'REAL':
                runtime.revalidate(real_grant)
                if real_grant['binding'] != state['input_binding'] or real_grant['run_root'] != str(root):
                    raise PermissionError('real grant differs from this complete public input and owned solve path')
            messages = adapter.messages(view, generation, repair, previous, diagnostics)
            request = dict(messages=messages, max_tokens=MAX_TOKENS, temperature=0, top_p=1)
            attempt = dict(number=number, status='request_prepared', input_binding=state['input_binding'])
            state['attempts'].append(attempt)
            attempt_root = root / ('attempt_' + str(number))
            attempt_root.mkdir(exist_ok=False)
            attempt['request_sha256'] = save_json(attempt_root / 'request.json', request)
            attempt['request_messages_sha256'] = digest(json_bytes(messages))
            attempt['transport_timeout_s'] = remaining()
            state['transport_invocations'] += 1
            phase = 'transport'
            attempt['status'] = 'transport_invoked'
            checkpoint()
            response, callback_error, callback_binding = invoke_fake(transport, request, attempt['transport_timeout_s'], attempt_root, 'transport')
            attempt['transport_callback_binding'] = callback_binding
            if isinstance(response, dict) and isinstance(response.get('reply'), str):
                attempt['reply_sha256'] = write_text_new(attempt_root / 'reply.txt', response['reply'])
                attempt['reply_bytes'] = len(response['reply'].encode('utf-8'))
            attempt['transport_receipt_sha256'] = save_json(attempt_root / 'transport_return.json', response)
            attempt['status'] = 'reply_received'
            checkpoint()
            if callback_binding['callback_input_mutated']:
                state['status'] = attempt['status'] = 'callback_input_mutated'
                state['callback_input_mutation_detected'] = True
                state['error'] = 'transport callback mutated its input; pre-call request is not proof of the actual external request'
                break
            if callback_error is not None:
                raise callback_error
            if not isinstance(response, dict):
                raise ValueError('unconfirmed transport return type; no retry')
            remaining()
            if set(response) != {'confirmed', 'reply', 'finish_reason'} or type(response['confirmed']) is not bool:
                raise ValueError('unconfirmed transport schema; no retry')
            if response['finish_reason'] == 'timeout':
                state['status'] = 'transport_timeout'
                break
            if not response['confirmed'] or response['finish_reason'] != 'stop' or not isinstance(response['reply'], str):
                state['status'] = 'transport_unconfirmed'
                break
            phase = 'candidate'
            candidate = adapter.candidate_files(response['reply'], view)
            files = adapter.assembled_files(view, candidate)
            validate_file_set(dict(context=files, output_paths=view['output_paths']))
            hashes = materialize_new(attempt_root / 'files', files)
            attempt['all_public_files_sha256'] = hashes
            attempt['candidate_files_sha256'] = {name: hashes[name] for name in view['output_paths']}
            attempt['files_manifest_sha256'] = save_json(attempt_root / 'FILES.json', hashes)
            # Recheck original binding and all files before a compiler is invoked.
            phase = 'binding'
            if adapter.binding(record, view) != state['input_binding']:
                raise ValueError('original public input binding changed')
            verify_files(root / 'public_context', view['context'], original_context_hashes)
            verify_files(attempt_root / 'files', files, hashes)
            phase = 'compile_admission'
            package = compile_package(attempt_root / 'files', files, hashes, view['output_paths'], compiler)
            attempt['compiler_input_sha256'] = save_json(attempt_root / 'compiler_input.json', package)
            attempt['compiler_timeout_s'] = remaining()
            phase = 'compiler'
            state['compiler_invocations'] += 1
            attempt['status'] = 'compiler_invoked'
            checkpoint()
            compiled, callback_error, callback_binding = invoke_fake(compiler, package, attempt['compiler_timeout_s'], attempt_root, 'compiler')
            attempt['compiler_callback_binding'] = callback_binding
            attempt['compiler_receipt_sha256'] = save_json(attempt_root / 'compiler_return.json', compiled)
            attempt['status'] = 'compiler_returned'
            checkpoint()
            if callback_binding['callback_input_mutated']:
                state['status'] = attempt['status'] = 'callback_input_mutated'
                state['callback_input_mutation_detected'] = True
                state['error'] = 'compiler callback mutated its input; pre-call package is not proof of actual compiler input'
                break
            if callback_error is not None:
                raise callback_error
            if not isinstance(compiled, dict):
                raise ValueError('unconfirmed compiler return type; no retry')
            remaining()
            verify_files(root / 'public_context', view['context'], original_context_hashes)
            verify_files(attempt_root / 'files', files, hashes)
            if set(compiled) != {'outcome', 'diagnostics', 'input_sha256'} or not isinstance(compiled['diagnostics'], str):
                raise ValueError('unconfirmed compiler schema; no retry')
            if compiled['input_sha256'] != attempt['compiler_input_sha256']:
                raise ValueError('compiler diagnostics not bound to actual public inputs; no retry')
            outcome = compiled['outcome']
            attempt['compiler_outcome'] = outcome
            attempt['diagnostics_sha256'] = digest(compiled['diagnostics'].encode('utf-8'))
            write_text_new(attempt_root / 'diagnostics.txt', compiled['diagnostics'])
            if outcome in {'timeout', 'unconfirmed'}:
                state['status'] = 'compiler_' + outcome
                break
            if outcome == 'passed':
                state['status'] = 'fake_candidate_compile_pass' if mode == 'FAKE' else 'real_candidate_checks_pass'
                break
            if outcome != 'failed' or not compiled['diagnostics'].strip():
                raise ValueError('failed compiler result lacks confirmed diagnostics; no retry')
            if number == MAX_REQUESTS:
                state['status'] = 'fake_candidate_compile_fail' if mode == 'FAKE' else 'real_candidate_checks_fail'
                break
            previous, diagnostics = candidate, compiled['diagnostics']
            attempt['status'] = 'confirmed_failure_for_one_repair'
            checkpoint()
        else:
            raise RuntimeError('request budget logic fell through')
    except TimeoutError as exc:
        state['status'] = 'solve_timeout'
        state['error'] = str(exc)
    except Exception as exc:
        state['status'] = 'compile_abstained' if phase == 'compile_admission' else phase + '_error'
        state['error'] = type(exc).__name__ + ': ' + str(exc)
    finally:
        if mode == 'REAL':
            try:
                counts = runtime.io_accounting(real_grant)
                state.update(attempted_model_requests=counts['http_attempts'],
                             confirmed_model_responses=counts['http_confirmed'],
                             unconfirmed_model_attempts=counts['http_unconfirmed'],
                             attempted_native_commands=counts['native_attempts'],
                             confirmed_native_commands=counts['native_confirmed'],
                             unconfirmed_native_attempts=counts['native_unconfirmed'],
                             native_test_attempts=counts['native_test_attempts'],
                             actual_native_tests=counts['native_tests_confirmed'],
                             actual_model_calls=counts['http_invocations_started'],
                             actual_eda_calls=counts['native_invocations_started'],
                             accounting_complete=True,
                             actual_call_definition='Recorded conservative entry across the invocation boundary; confirmation reported separately.')
            except Exception as exc:
                state.update(status='io_accounting_error', error=type(exc).__name__ + ': ' + str(exc),
                             accounting_complete=False, attempted_model_requests=real_grant['http_attempts'],
                             attempted_native_commands=real_grant['native_attempts'])
        state['complete'] = True
        state['elapsed_s'] = max(0.0, clock() - started)
        if clock() >= work_deadline:
            state['terminal_status_before_timeout'] = state['status']
            state['status'] = 'solve_timeout'
            state['error'] = 'whole solve deadline exhausted during callback/verification/finalization; no retry or resampling'
        state['request_evidence_count'] = len(state['attempts'])
        checkpoint()
        final_elapsed = max(0.0, clock() - started)
        if final_elapsed > state['elapsed_s']:
            state['elapsed_s'] = final_elapsed
            if clock() >= work_deadline and state['status'] != 'solve_timeout':
                state['terminal_status_before_timeout'] = state['status']
                state['status'] = 'solve_timeout'
                state['error'] = 'whole solve deadline exhausted during final summary; no retry or resampling'
            checkpoint()
    return state
