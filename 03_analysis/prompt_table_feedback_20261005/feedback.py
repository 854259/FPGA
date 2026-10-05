"""Prompt-only complete-care Kmap runner; no model or official TB/reference.

The caller supplies the admitted worker's guarded owned-command callback, fixed
absolute tools and original absolute solve deadline. This is not stage admission.
"""
from pathlib import Path
import hashlib
import json
import math
import re
import time
import uuid

import contract
import render

SEALED = {'contract.py': '46d53aee94b55034c1677873551c651b9a496e4331374c291d7f750a6043d206',
          'render.py': '2893c870e5cd5cba4b88de3cbca3f1f447cbc74836669f0f78e940dd34d9d817'}
ERROR = re.compile(r'^\s*(?:ERROR|FATAL)(?:_ERROR)?(?:\s|:|$)', re.M | re.I)
ENV_ERROR = re.compile(r'license checkout failed|failed to check out.{0,40}license|'
                       r'no valid license|flexnet licensing error|segmentation fault|'
                       r'cannot open shared object file|no space left on device', re.I)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def no_links(path):
    path = Path(path)
    if not path.is_absolute() or '..' in path.parts:
        raise ValueError('explicit absolute owned paths required')
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink() or (hasattr(current, 'is_junction') and current.is_junction()):
            raise ValueError('path contains a symlink/junction')
    return path


def save(path, value):
    path = no_links(path)
    pending = path.with_name(path.name + '.pending')
    with pending.open('xb') as stream:
        stream.write((json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode())
    pending.replace(path)


def implementation_hashes():
    root = no_links(Path(__file__).absolute().parent)
    if Path(contract.__file__).absolute() != root / 'contract.py' or Path(render.__file__).absolute() != root / 'render.py':
        raise ValueError('sealed local contract/render imports required')
    hashes = {name: sha(no_links(root / name).read_bytes())
              for name in ('contract.py', 'render.py', 'feedback.py')}
    if any(hashes[name] != digest for name, digest in SEALED.items()):
        raise ValueError('sealed contract/render bytes differ')
    return hashes


def check(prompt, code, out, attempt, native_run, tools, deadline_monotonic, timeout_s=60):
    """Return full confirmed care-table feedback, or '' on pass/abstention.

    Unsupported prompts abstain before any directory or native call. A native
    measurement error raises and never becomes semantic feedback. native_run
    must be (argv, cwd, log, seconds) -> the existing paired owned receipt. The
    deadline is the caller's existing solve deadline, not a fresh helper budget.
    """
    implementation_before = implementation_hashes()
    admitted = contract.parse_prompt(prompt)
    if not admitted['admitted'] or admitted['contract']['kind'] != 'karnaugh_map':
        return ''
    if not isinstance(code, str) or not code or type(attempt) is not int or attempt not in (0, 1):
        raise ValueError('current candidate and original 0/1 repair round required')
    if re.search(r'\$[A-Za-z_]|`include', code):
        raise ValueError('self-contained candidate without system tasks/includes required')
    if (type(deadline_monotonic) not in (int, float) or not math.isfinite(deadline_monotonic)
            or not 0 < deadline_monotonic - time.monotonic() <= 300):
        raise ValueError('original positive remaining solve budget at most 300 seconds required')
    if type(timeout_s) not in (int, float) or not math.isfinite(timeout_s) or not 0 < timeout_s <= 60:
        raise ValueError('positive finite native cap at most 60 seconds required')
    if not callable(native_run) or not isinstance(tools, dict) or set(tools) != {'xvlog', 'xelab', 'xsim'}:
        raise ValueError('guarded owned runner and three fixed tools required')
    tools = {name: no_links(value) for name, value in tools.items()}
    for name, path in tools.items():
        if not path.is_file() or path.name.lower() not in (name, name + '.bat'):
            raise ValueError('fixed tool unavailable: ' + name)
    tool_before = {name: sha(path.read_bytes()) for name, path in tools.items()}
    out = no_links(out)
    if not out.is_dir():
        raise ValueError('owned sample output directory required')
    case = 'candidate_' + str(attempt) + '_' + uuid.uuid4().hex
    tb = render.render_tb(prompt, case)  # Also rejects a Kmap with no cared obligations.
    folder = out / ('prompt_table_check_' + str(attempt))
    folder.mkdir(exist_ok=False)
    snapshot = 'table_probe_' + uuid.uuid4().hex
    expected = {'candidate.sv': code.encode(), 'tb.sv': tb.encode(), 'prompt.txt': prompt.encode()}
    for name, raw in expected.items():
        with (folder / name).open('xb') as stream:
            stream.write(raw)
    source_sha = {name: sha(raw) for name, raw in expected.items()}
    commands = (
        ('xvlog', [str(tools['xvlog']), '-sv', '--nolog', 'candidate.sv', 'tb.sv']),
        ('xelab', [str(tools['xelab']), 'R2Probe', '-s', snapshot, '--nolog', '-timescale', '1ns/1ps']),
        ('xsim', [str(tools['xsim']), snapshot, '-runall', '-nolog']),
    )
    started = time.monotonic()
    receipt = dict(schema='prompt_only_kmap_full_care_feedback_v1', actualcheck_path=str(folder),
                   attempt=attempt, case_id=case, snapshot=snapshot, admitted=admitted,
                   source_input_sha256=source_sha, implementation_before_sha256=implementation_before,
                   tool_before_sha256=tool_before, deadline_monotonic=deadline_monotonic,
                   native_timeout_cap_s=timeout_s, native_commands=[], parsed=None,
                   complete=False, measurement_valid=False, outcome='pending', feedback='', error=None,
                   model_calls=0, official_testbench_used=False, reference_used=False,
                   generated_prompt_testbench=True, official_quality_judgement=False)
    save(folder / 'RESULTS.json', receipt)
    error = None
    try:
        for name, argv in commands:
            if any(no_links(folder / source).read_bytes() != raw for source, raw in expected.items()):
                raise RuntimeError('candidate/prompt/TB bytes changed before native call')
            if implementation_hashes() != implementation_before or any(sha(no_links(path).read_bytes()) != tool_before[key] for key, path in tools.items()):
                raise RuntimeError('source/tool bytes changed before native call')
            remaining = deadline_monotonic - time.monotonic()
            if remaining <= 0:
                raise RuntimeError('original solve deadline exhausted; no new helper budget')
            seconds = min(timeout_s, remaining)
            log = no_links(folder / (name + '.log'))
            entry = dict(tool=name, argv=argv, cwd=str(folder), log=str(log),
                         source_input_sha256=source_sha, tool_sha256=tool_before[name],
                         remaining_budget_s=remaining, timeout_s=seconds, attempted=True,
                         confirmed=False, native_command=None)
            receipt['native_commands'].append(entry)
            save(folder / 'RESULTS.json', receipt)  # An interrupted callback leaves an attempted receipt.
            invoked = list(argv)
            actual = native_run(invoked, folder, log, seconds)
            entry['native_argv_after'] = invoked
            entry['native_command'] = json.loads(json.dumps(actual, allow_nan=False))
            save(folder / 'RESULTS.json', receipt)
            if invoked != argv or not isinstance(actual, dict):
                raise RuntimeError('native argv or receipt changed/unknown')
            for key in ('returncode', 'timeout', 'launch_error', 'remaining_live_group', 'log', 'log_sha256', 'log_bytes'):
                if key not in actual:
                    raise RuntimeError('native receipt missing ' + key)
            if (actual['timeout'] is not False or actual['launch_error'] is not None
                    or actual['remaining_live_group'] != [] or type(actual['returncode']) is not int
                    or actual['returncode'] != 0):
                raise RuntimeError('native nonzero/timeout/launch/cleanup is not care-table feedback')
            raw = no_links(log).read_bytes()
            if actual['log'] != str(log) or actual['log_sha256'] != sha(raw) or type(actual['log_bytes']) is not int or actual['log_bytes'] != len(raw):
                raise RuntimeError('actual complete native log is not bound to its receipt')
            text = raw.decode('utf-8')
            if ERROR.search(text) or ENV_ERROR.search(text):
                raise RuntimeError('native error log is not semantic observations')
            entry.update(confirmed=True, actual_log_sha256=sha(raw), actual_log_bytes=len(raw))
            save(folder / 'RESULTS.json', receipt)
        if deadline_monotonic - time.monotonic() <= 0:
            raise RuntimeError('original solve deadline exhausted before interpretation')
        log = no_links(folder / 'xsim.log').read_bytes().decode('utf-8')
        parsed = render.parse_observations(prompt, case, log)
        receipt.update(parsed=parsed, outcome=parsed['status'],
                       feedback=render.make_feedback(prompt, case, log, mode='full') or '')
    except BaseException as exc:
        error = exc
        receipt.update(outcome='measurement_error', feedback='', error=type(exc).__name__ + ': ' + str(exc))
    finally:
        try:
            receipt['source_after_sha256'] = {name: sha(no_links(folder / name).read_bytes()) for name in expected}
            receipt['tool_after_sha256'] = {name: sha(no_links(path).read_bytes()) for name, path in tools.items()}
            receipt['implementation_after_sha256'] = implementation_hashes()
            receipt['source_unchanged'] = receipt['source_after_sha256'] == source_sha
            receipt['tools_unchanged'] = receipt['tool_after_sha256'] == tool_before
            if (not receipt['source_unchanged'] or not receipt['tools_unchanged']
                    or receipt['implementation_after_sha256'] != implementation_before):
                raise RuntimeError('candidate/prompt/TB/tool/helper source changed during check')
            for entry in receipt['native_commands']:
                log = no_links(entry['log'])
                if log.is_file():
                    raw = log.read_bytes()
                    entry.update(final_log_sha256=sha(raw), final_log_bytes=len(raw))
                    if entry['confirmed'] and sha(raw) != entry['actual_log_sha256']:
                        raise RuntimeError('confirmed native log changed before finalization')
        except BaseException as exc:
            error = exc
            receipt.update(outcome='measurement_error', feedback='', error=type(exc).__name__ + ': ' + str(exc))
        receipt.update(complete=True, measurement_valid=error is None, elapsed_s=time.monotonic() - started)
        save(folder / 'RESULTS.json', receipt)
    if error is not None:
        raise RuntimeError('prompt-table measurement failed; see ' + str(folder / 'RESULTS.json')) from error
    return receipt['feedback']
