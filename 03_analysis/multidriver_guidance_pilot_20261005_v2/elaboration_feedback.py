"""Candidate-only xelab feedback; no prompt/ID/testbench/reference rule.

Called only after normal xvlog success, before the existing functional checker.
The caller supplies its guarded paired.owned_command and fixed absolute tool.
"""
from pathlib import Path
import hashlib
import json
import math
import re
import time
import uuid

ERROR_LINE = re.compile(r'^\s*(?:ERROR|FATAL)(?:_ERROR)?(?:\s|:|$)')


def sha(data):
    return hashlib.sha256(data).hexdigest()


def diagnostic_text(text):
    """Only actual severity-marked facts from the complete native xelab log."""
    unique, seen = [], set()
    for line in text.splitlines():
        fact = line.strip()
        if ERROR_LINE.match(line) and fact not in seen:
            seen.add(fact); unique.append(fact)
    return '\n'.join(unique)[:2048]


def no_links(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('elaboration paths must be explicit absolute owned paths')
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink() or (hasattr(current, 'is_junction') and current.is_junction()):
            raise ValueError('elaboration path contains a symlink/junction')
    return path


def save(path, value):
    path = no_links(path)
    temporary = path.with_name(path.name + '.pending')
    with temporary.open('xb') as stream:
        stream.write((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode('utf-8'))
        stream.flush()
    temporary.replace(path)


def check(code, compile_dir, out, attempt, native_run, tool, timeout_s=60):
    """Return confirmed xelab ERROR/FATAL facts, or '' on native rc=0.

    Native runner signature: (argv, cwd, log, seconds) -> paired owned-command
    receipt. Supervision/receipt/source failures raise a measurement error and
    cannot become model diagnostics. No retry, source edit, xsim or TB occurs.
    """
    started = time.monotonic()
    if not isinstance(code, str) or not code or type(attempt) is not int or attempt not in (0, 1):
        raise ValueError('complete candidate code and original 0/1 repair round required')
    if type(timeout_s) not in (int, float) or not math.isfinite(timeout_s) or not 0 < timeout_s <= 60:
        raise ValueError('native timeout must be positive finite and at most 60 seconds')
    compile_dir, out = no_links(compile_dir), no_links(out)
    if not compile_dir.is_dir() or not out.is_dir() or not compile_dir.is_relative_to(out):
        raise ValueError('candidate compile directory must belong to this owned sample output')
    source = no_links(compile_dir / 'candidate.sv')
    expected = code.encode('utf-8')
    before = source.read_bytes()
    if before != expected:
        raise ValueError('current compiled candidate bytes differ from callback code')
    if not callable(native_run) or tool is None:
        raise ValueError('actual guarded native runner and xelab executable are required')
    tool = no_links(tool)
    if not tool.is_file() or tool.name.lower() not in ('xelab', 'xelab.bat'):
        raise ValueError('absolute actual xelab tool is unavailable')
    tool_before = sha(tool.read_bytes())
    folder = out / ('elaboration_check_' + str(attempt))
    folder.mkdir(exist_ok=False)
    snapshot = 'own_candidate_elab_' + str(attempt) + '_' + uuid.uuid4().hex
    if (compile_dir / 'xsim.dir' / snapshot).exists():
        raise ValueError('refuse an existing elaboration snapshot')
    # Exact established probe_runner.py options (frozen source 954a1bca...).
    # Only candidate TopModule is elaborated; no R2Probe/testbench/reference.
    argv = [str(tool), 'TopModule', '-s', snapshot, '--nolog', '-timescale', '1ns/1ps']
    log = folder / 'owned_elaboration.log'
    (folder / 'source_before.sv').write_bytes(before)
    receipt = dict(schema='candidate_elaboration_feedback_v1', actualcheck_path=str(folder),
                   attempt=attempt, snapshot=snapshot, top='TopModule', argv=argv, cwd=str(compile_dir),
                   code_sha256=sha(expected), source_path=str(source), source_before_sha256=sha(before),
                   source_after_sha256=None, source_unchanged=False,
                   executable_path=str(tool), executable_before_sha256=tool_before,
                   executable_after_sha256=None, executable_unchanged=False,
                   timeout_s=timeout_s, native_invocation_attempted=True, native_command=None,
                   returncode=None, timeout=None, launch_error=None, remaining_live_group=None,
                   log_path=str(log), log_sha256=None, log_bytes=None,
                   complete=False, measurement_valid=False, outcome='pending', feedback='',
                   model_calls=0, hidden_testbench_used=False, reference_used=False,
                   candidate_only=True, official_quality_judgement=False, error=None)
    save(folder / 'RESULTS.json', receipt)
    error = None
    try:
        invoked_argv = list(argv)
        command = native_run(invoked_argv, compile_dir, log, timeout_s)
        receipt['native_argv_after'] = invoked_argv
        if invoked_argv != argv:
            raise RuntimeError('injected native command changed actual elaboration argv')
        # Store the returned receipt exactly as data before deriving diagnostics.
        try:
            receipt['native_command'] = json.loads(json.dumps(command, allow_nan=False))
        except (TypeError, ValueError) as exc:
            receipt['native_command_unserializable'] = repr(command)
            raise RuntimeError('native command receipt is not complete JSON evidence') from exc
        if not isinstance(command, dict):
            raise RuntimeError('native command did not return an actual receipt')
        for key in ['returncode', 'timeout', 'launch_error', 'remaining_live_group']:
            if key not in command:
                raise RuntimeError('native command receipt field missing: ' + key)
            receipt[key] = command[key]
        if command['timeout'] is not False or command['launch_error'] is not None or command['remaining_live_group'] != []:
            raise RuntimeError('native xelab timeout/launch/owned-process cleanup failure')
        if type(command['returncode']) is not int or command['returncode'] < 0:
            raise RuntimeError('native xelab return code unconfirmed or externally terminated')
        raw = log.read_bytes()
        if (command.get('log') != str(log) or command.get('log_sha256') != sha(raw)
                or type(command.get('log_bytes')) is not int or command['log_bytes'] != len(raw)):
            raise RuntimeError('native complete xelab log receipt differs')
        receipt.update(log_sha256=sha(raw), log_bytes=len(raw))
        if command['returncode'] == 0:
            receipt.update(outcome='pass', feedback='')
        else:
            facts = diagnostic_text(raw.decode('utf-8', errors='replace'))
            if not facts:
                raise RuntimeError('nonzero xelab lacks confirmed ERROR/FATAL facts; no invented diagnostic')
            receipt.update(outcome='fail', feedback=facts)
    except BaseException as exc:
        error = exc
        receipt.update(outcome='measurement_error', feedback='', error=type(exc).__name__ + ': ' + str(exc))
    finally:
        try:
            after = source.read_bytes()
            (folder / 'source_after.sv').write_bytes(after)
            receipt.update(source_after_sha256=sha(after), source_unchanged=after == expected)
            receipt.update(executable_after_sha256=sha(tool.read_bytes()))
            receipt['executable_unchanged'] = receipt['executable_after_sha256'] == tool_before
            if not receipt['source_unchanged'] or not receipt['executable_unchanged']:
                raise RuntimeError('candidate/tool bytes changed during native elaboration')
        except BaseException as exc:
            error = exc
            receipt.update(outcome='measurement_error', feedback='', error=type(exc).__name__ + ': ' + str(exc))
        if log.is_file():
            try:
                raw = log.read_bytes()
                receipt.update(actual_log_sha256=sha(raw), actual_log_bytes=len(raw))
            except OSError as exc:
                error = exc
                receipt.update(outcome='measurement_error', feedback='', error=type(exc).__name__ + ': ' + str(exc))
        receipt.update(complete=True, elapsed_s=time.monotonic() - started,
                       measurement_valid=error is None)
        save(folder / 'RESULTS.json', receipt)
    if error is not None:
        raise RuntimeError('candidate elaboration measurement failed; see ' + str(folder / 'RESULTS.json')) from error
    return receipt['feedback']
