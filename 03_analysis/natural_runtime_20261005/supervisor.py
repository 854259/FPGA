"""DRAFT: one guarded Linux solve, inherited-pipe admission, owned PID cleanup.

Import has no process, network, model, or EDA effects.  This module never signals
process groups.  Its admission proves an actual child of the active own stage;
it does not grant model access, certify a sandbox, or cancel a server-side job.
"""
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import select
import signal
import stat
import subprocess
import sys
import threading
import time
import uuid

TOTAL_SECONDS = 300.0
CLEANUP_SECONDS = 24.0
RECEIPT_SECONDS = 4.0
PIPE_ENV = 'OWN_NATURAL_SUPERVISOR_FD'
_CHILD_GRANTS = {}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode('utf-8')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('duplicate JSON field')
        value[key] = item
    return value


def read_json(path):
    data = Path(path).read_bytes()
    return json.loads(data, object_pairs_hook=unique), digest(data)


def no_links(path):
    path = Path(path).absolute()
    current = Path(path.anchor)
    for part in path.parts[1:]:
        current /= part
        if current.is_symlink() or (hasattr(current, 'is_junction') and current.is_junction()):
            raise PermissionError('supervisor path contains a link or junction')
    return path


def owned_evidence(root, path):
    if not Path(root).is_absolute() or not Path(path).is_absolute():
        raise PermissionError('supervisor root/evidence paths must be explicitly absolute')
    root, path = no_links(root), no_links(path)
    if not path.is_relative_to(root / 'raw_evidence'):
        raise PermissionError('solve supervision evidence must remain in own raw_evidence')
    return path


def durable_json(path, value, new=False):
    """Replace only our own receipt; fsync is part of elapsed-time accounting."""
    path = no_links(path)
    data = canonical(value) + b'\n'
    if new:
        with path.open('xb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
    else:
        temporary = path.with_name(path.name + '.tmp-' + uuid.uuid4().hex)
        with temporary.open('xb') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        no_links(path)
        os.replace(temporary, path)
    if sys.platform == 'linux':
        fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    return digest(data)


def parse_stat(pid, text):
    fields = text.rsplit(')', 1)[1].split()
    if len(fields) < 20:
        raise ValueError('truncated /proc stat')
    return dict(pid=int(pid), starttime=fields[19], state=fields[0],
                ppid=int(fields[1]), pgid=int(fields[2]), sid=int(fields[3]))


def process_record(pid):
    try:
        return parse_stat(pid, (Path('/proc') / str(pid) / 'stat').read_text())
    except (FileNotFoundError, ProcessLookupError):
        return None


def same_identity(actual, expected, live=True):
    return (isinstance(actual, dict) and isinstance(expected, dict)
            and all(actual.get(key) == expected.get(key)
                    for key in ['pid', 'starttime', 'pgid', 'sid'])
            and (not live or actual.get('state') not in {'Z', 'X'}))


def descendants(parent):
    found, todo = {}, [parent]
    while todo:
        current = todo.pop()
        try:
            threads = list((Path('/proc') / str(current) / 'task').iterdir())
        except (FileNotFoundError, ProcessLookupError):
            continue
        for thread in threads:
            try:
                children = (thread / 'children').read_text().split()
            except (FileNotFoundError, ProcessLookupError):
                continue
            for pid in map(int, children):
                row = process_record(pid)
                if row and pid not in found:
                    found[pid] = row
                    todo.append(pid)
    return found


def deadlines(started, seconds=TOTAL_SECONDS):
    if (isinstance(started, bool) or not isinstance(started, (int, float))
            or not math.isfinite(started) or seconds != TOTAL_SECONDS):
        raise PermissionError('real solves have one fixed total 300-second budget')
    return dict(started_monotonic=started,
                work_deadline_monotonic=started + seconds - CLEANUP_SECONDS - RECEIPT_SECONDS,
                cleanup_deadline_monotonic=started + seconds - RECEIPT_SECONDS,
                total_deadline_monotonic=started + seconds,
                total_timeout_s=seconds, cleanup_reserve_s=CLEANUP_SECONDS,
                receipt_reserve_s=RECEIPT_SECONDS)


def solve_start(started_monotonic, entered_monotonic):
    """Include the parent's actual input/gate preparation in the existing budget."""
    value = entered_monotonic if started_monotonic is None else started_monotonic
    bounds = deadlines(value)
    if value > entered_monotonic:
        raise PermissionError('parent solve start is in the future; cannot reopen the budget')
    if entered_monotonic >= bounds['work_deadline_monotonic']:
        raise TimeoutError('parent preparation already exhausted the cleanup-reserved solve budget')
    return value


def _linux_requirements():
    if sys.platform != 'linux':
        raise PermissionError('actual supervision is Linux-only; Windows plans do not admit execution')
    if not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
        raise PermissionError('safe PID-pinned signalling is unavailable; do not launch')
    if threading.active_count() != 1 or len(list(Path('/proc/self/task').iterdir())) != 1:
        raise PermissionError('solve supervisor must own a single-threaded stage with no other children')


def _proc_command(pid):
    return (Path('/proc') / str(pid) / 'cmdline').read_bytes()


def wrapper_binding(root, spec, stage):
    """Bind the live stage's actual parent to this frozen own guard script."""
    source = no_links(root / 'guard_wrapper.py')
    if digest(source.read_bytes()) != spec.get('source_hashes', {}).get('guard_wrapper.py'):
        raise PermissionError('actual wrapper source is not frozen in own runtime root')
    wrapper = process_record(stage['ppid'])
    if not wrapper or wrapper['state'] in {'Z', 'X'}:
        raise PermissionError('actual guard parent is not live')
    command = _proc_command(wrapper['pid'])
    argv = [item.decode('utf-8', errors='strict') for item in command.split(b'\0') if item]
    if argv.count(str(source)) != 1 or argv.count('--guard-out') != 1:
        raise PermissionError('actual stage parent command does not run own frozen wrapper')
    index = argv.index('--guard-out')
    if index + 1 == len(argv) or argv[index + 1] != str(root / 'guard'):
        raise PermissionError('actual guard parent command binds a different evidence namespace')
    if not same_identity(process_record(wrapper['pid']), wrapper):
        raise PermissionError('guard parent identity changed while reading command')
    source_sha = digest(source.read_bytes())
    if source_sha != spec['source_hashes']['guard_wrapper.py']:
        raise PermissionError('guard source changed while binding actual parent')
    return dict(identity={key: wrapper[key] for key in ['pid', 'starttime', 'ppid', 'pgid', 'sid']},
                command_sha256=digest(command), source_sha256=source_sha)


def guard_snapshot(root, stage_pid, deadline):
    """Read the actual active guard; bounded wait covers Popen/status publication.

    The caller still needs runtime's complete qualification and resource gates.
    Missing or transiently incomplete status is waited for; contradictory status
    is rejected.  No caller-provided Boolean or state-only token grants access.
    """
    root = no_links(root)
    spec, spec_sha = read_json(root / 'RUN_SPEC.json')
    cloud_root = spec.get('cloud_root')
    if (spec.get('schema') != 'natural_runtime_frozen_v1' or not isinstance(cloud_root, str)
            or not Path(cloud_root).is_absolute() or Path(cloud_root).absolute() != root):
        raise PermissionError('supervisor requires this exact own frozen runtime root')
    if spec.get('execution_authorized_by_root') is not True or spec.get('solve_timeout_s') != TOTAL_SECONDS:
        raise PermissionError('root execution authorization/fixed solve budget missing')
    own_hash = spec.get('source_hashes', {}).get('supervisor.py')
    if own_hash != digest(Path(__file__).read_bytes()) or Path(__file__).absolute() != root / 'supervisor.py':
        raise PermissionError('live supervisor is not the frozen source in this own root')
    for name in ['guard/status.json', 'guard/resource_check.json']:
        no_links(root / name)
    wait_until = min(deadline, time.monotonic() + 5.0)
    while True:
        try:
            status, status_sha = read_json(root / 'guard/status.json')
        except (FileNotFoundError, json.JSONDecodeError):
            status = None
        else:
            if not isinstance(status, dict) or status.get('complete') is not False or status.get('error') is not None:
                raise PermissionError('contradictory actual guard status; no pending-stage admission')
            published = status.get('stage_pid')
            if published is None:
                if status.get('passed') is not False or status.get('phase') != 'resource_guard':
                    raise PermissionError('missing stage PID is not an explicit pending resource-guard shape')
            elif isinstance(published, bool) or not isinstance(published, int) or published != stage_pid:
                raise PermissionError('caller/parent is not the actual active own guard stage')
            else:
                break
        if time.monotonic() >= wait_until:
            raise TimeoutError('active guard handshake was not published within solve budget')
        time.sleep(min(.025, max(0, wait_until - time.monotonic())))
    stage = process_record(stage_pid)
    if stage is None or stage['state'] in {'Z', 'X'}:
        raise PermissionError('actual admitted stage is not live')
    resource, resource_sha = read_json(root / 'guard/resource_check.json')
    if resource.get('slot_owner') != spec.get('slot_owner') or resource.get('model_identity') != spec.get('model_identity'):
        raise PermissionError('actual slot/model resource identity differs')
    if resource.get('slot_lock_path') != spec.get('slot_lock_path'):
        raise PermissionError('actual slot path is not the frozen slot path')
    lock = no_links(resource['slot_lock_path'])
    lock_data = lock.read_bytes()
    if digest(lock_data) != resource.get('slot_lock_sha256') or lock_data.decode('utf-8').splitlines()[0] != spec['slot_owner']:
        raise PermissionError('actual cooperative lock changed or is not owned')
    if time.monotonic() >= deadline:
        raise TimeoutError('supervisor admission consumed the cleanup-reserved solve budget')
    # State is instantaneous scheduling information, not process identity.  The
    # child observes its parent sleeping while the parent originally observed R.
    stage_binding = {key: stage[key] for key in ['pid', 'starttime', 'ppid', 'pgid', 'sid']}
    wrapper = wrapper_binding(root, spec, stage)
    if time.monotonic() >= deadline:
        raise TimeoutError('actual wrapper binding exhausted solve work deadline')
    return dict(root=str(root), spec_sha256=spec_sha, resource_sha256=resource_sha,
                status_sha256=status_sha, stage=stage_binding, model_pid=resource['model_identity']['pid'],
                slot_lock_sha256=digest(lock_data), wrapper=wrapper), spec


def validate_child_token(token, snapshot, child, parent):
    if token.get('schema') != 'owned_natural_solve_pipe_v1' or token.get('guard') != snapshot:
        raise PermissionError('inherited child handshake does not bind the actual guard bytes')
    if not same_identity(child, token.get('child')) or not same_identity(parent, token.get('parent')):
        raise PermissionError('actual parent/child process identity differs from supervisor handshake')
    if child['ppid'] != parent['pid'] or child['pgid'] != child['pid'] or child['sid'] != child['pid']:
        raise PermissionError('child is not the direct independently grouped supervised process')
    if parent['pid'] != snapshot['stage']['pid'] or not same_identity(parent, snapshot['stage']):
        raise PermissionError('supervisor parent is not the active own guarded main stage')
    planned = deadlines(token['started_monotonic'])
    if any(token.get(key) != value for key, value in planned.items()):
        raise PermissionError('inherited fixed absolute deadlines were altered')
    if not isinstance(token.get('nonce'), str) or len(token['nonce']) != 32:
        raise PermissionError('missing own one-shot handshake nonce')
    return planned


def _pipe_read(fd, deadline):
    if not stat.S_ISFIFO(os.fstat(fd).st_mode):
        raise PermissionError('child admission needs the inherited pipe, not a file or Boolean')
    data, count = bytearray(), None
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('inherited child guard handshake exceeded budget')
        if not select.select([fd], [], [], min(.1, remaining))[0]:
            continue
        block = os.read(fd, 65536)
        if not block:
            if count is None or len(data) != 4 + count:
                raise PermissionError('truncated inherited handshake pipe')
            return json.loads(bytes(data[4:]), object_pairs_hook=unique)
        data.extend(block)
        if len(data) >= 4 and count is None:
            count = int.from_bytes(data[:4], 'big')
            if not 0 < count <= 32768:
                raise PermissionError('inherited handshake is not bounded')
        if count is not None and len(data) > 4 + count:
            raise PermissionError('extra bytes in inherited handshake pipe')


def child_admission(root):
    """Child entry must call this before make_real_clients/HTTP/EDA admission."""
    _linux_requirements()
    raw_fd = os.environ.pop(PIPE_ENV, None)
    if not isinstance(raw_fd, str) or not raw_fd.isdigit():
        raise PermissionError('no actual inherited supervisor handshake')
    fd = int(raw_fd)
    try:
        token = _pipe_read(fd, time.monotonic() + 5.0)
    finally:
        os.close(fd)
    current, parent = process_record(os.getpid()), process_record(os.getppid())
    snapshot, _ = guard_snapshot(root, parent['pid'], token['work_deadline_monotonic'])
    validate_child_token(token, snapshot, current, parent)
    token_path = owned_evidence(root, token['authorization_path'])
    on_disk, _ = read_json(token_path)
    if canonical(on_disk) != canonical(token):
        raise PermissionError('durable parent authorization and inherited pipe differ')
    if time.monotonic() >= token['work_deadline_monotonic']:
        raise TimeoutError('child reached admission after cleanup-reserved deadline')
    grant = dict(token=token, admission_monotonic=time.monotonic(),
                 actual_parent=parent, actual_child=current,
                 real_io_admitted=False, server_job_cancellation_confirmed=False)
    _CHILD_GRANTS[id(grant)] = canonical(grant)
    return grant


def verify_child_admission(grant, root):
    if _CHILD_GRANTS.get(id(grant)) != canonical(grant):
        raise PermissionError('child grant did not come from a validated inherited handshake')
    token = grant['token']
    current, parent = process_record(os.getpid()), process_record(os.getppid())
    snapshot, _ = guard_snapshot(root, parent['pid'], token['work_deadline_monotonic'])
    validate_child_token(token, snapshot, current, parent)
    if time.monotonic() >= token['work_deadline_monotonic']:
        raise TimeoutError('no child IO may start after cleanup-reserved solve deadline')
    return dict(stage=parent, child=current, **deadlines(token['started_monotonic']),
                handshake_sha256=digest(canonical(token)), real_io_admitted=False,
                server_job_cancellation_confirmed=False)


def _pin(row):
    before = process_record(row['pid'])
    if not same_identity(before, row, live=False):
        return None
    try:
        fd = os.pidfd_open(row['pid'], 0)
    except ProcessLookupError:
        return None
    if not same_identity(process_record(row['pid']), row, live=False):
        os.close(fd)
        return None
    return fd


def _observe(tracked, stage_pid, protected):
    seen = descendants(stage_pid)
    for pid, row in seen.items():
        if pid in protected:
            raise PermissionError('protected process appeared in own descendant tree; do not signal')
        existing = tracked.get(pid)
        if existing and not same_identity(row, existing['record'], live=False):
            raise PermissionError('observed PID identity was reused; do not signal replacement')
        if not existing:
            fd = _pin(row)
            if fd is not None:
                tracked[pid] = dict(record=row, pidfd=fd,
                                   ownership='observed_descendant_of_exclusive_subreaper_stage')
    return seen


def _signal(tracked, sig, protected, events):
    for pid, item in list(tracked.items()):
        if pid in protected:
            raise PermissionError('refuse signal to protected PID')
        row = process_record(pid)
        if not same_identity(row, item['record']) or row['state'] == 'Z':
            continue
        try:
            signal.pidfd_send_signal(item['pidfd'], sig, None, 0)
            events.append(dict(pid=pid, starttime=row['starttime'], pgid=row['pgid'],
                               signal=int(sig), ownership=item['ownership']))
        except ProcessLookupError:
            pass


def cleanup_owned(proc, tracked, stage_pid, protected, deadline):
    """Capture adopted descendants, pin identity, TERM then KILL, then reap ours."""
    events, reap_events = [], []
    _observe(tracked, stage_pid, protected)
    _signal(tracked, signal.SIGTERM, protected, events)
    term_until = min(deadline, time.monotonic() + 2.0)
    while True:
        proc.poll()
        _observe(tracked, stage_pid, protected)
        if time.monotonic() >= term_until:
            _signal(tracked, signal.SIGKILL, protected, events)
        remaining = []
        for pid, item in tracked.items():
            row = process_record(pid)
            if not same_identity(row, item['record'], live=False):
                continue
            if row['state'] == 'Z' and row['ppid'] == stage_pid:
                try:
                    actual_pid, status = os.waitpid(pid, os.WNOHANG)
                    if actual_pid:
                        reap_events.append(dict(pid=pid, starttime=row['starttime'], status=status))
                        continue
                except ChildProcessError:
                    pass
            remaining.append(row)
        freshly_observed = _observe(tracked, stage_pid, protected)
        if not remaining and not freshly_observed:
            return dict(verified=True, remaining=[], recorded=[item['record'] for item in tracked.values()],
                        signal_events=events, reap_events=reap_events,
                        method='exclusive_owned_subreaper_tree_with_pidfd_identity_pinning',
                        process_groups_signalled=False)
        if time.monotonic() >= deadline:
            return dict(verified=False, remaining=remaining, recorded=[item['record'] for item in tracked.values()],
                        signal_events=events, reap_events=reap_events,
                        method='exclusive_owned_subreaper_tree_with_pidfd_identity_pinning',
                        process_groups_signalled=False)
        time.sleep(min(.025, max(0, deadline - time.monotonic())))


def _pipe_write(fd, payload, deadline):
    data = len(payload).to_bytes(4, 'big') + payload
    os.set_blocking(fd, False)
    offset = 0
    while offset < len(data):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('parent handshake write exhausted whole solve budget')
        if not select.select([], [fd], [], min(.1, remaining))[1]:
            continue
        try:
            offset += os.write(fd, data[offset:])
        except BlockingIOError:
            continue


def run_supervised(argv, evidence_dir, guard_root, timeout_s=TOTAL_SECONDS, started_monotonic=None):
    """Main guarded stage supervises exactly one child solve; no retry.

    RUN_SPEC.supervisor must bind child_entry (relative frozen .py source),
    python_executable, and python_sha256. The child calls child_admission before
    runtime IO. Closing/killing a client never establishes model cancellation.
    """
    entered = time.monotonic()
    started = solve_start(started_monotonic, entered)
    bounds = deadlines(started, timeout_s)
    _linux_requirements()
    root = no_links(guard_root)
    evidence_dir = owned_evidence(root, evidence_dir)
    evidence_dir.mkdir(parents=True, exist_ok=False)
    receipt_path = evidence_dir / 'SUPERVISOR_RECEIPT.json'
    receipt = dict(schema='owned_natural_solve_supervisor_v1', complete=False, passed=False,
                   real_model_calls=None, real_eda_calls=None, runtime_receipts_required=True,
                   launch_attempted=False, launch_confirmed=False, child_returncode=None,
                   server_job_cancellation_confirmed=False, model_managed=False,
                   instance_managed=False, process_groups_signalled=False, error=None, **bounds)
    receipt.update(supervisor_entered_monotonic=entered,
                   parent_preparation_elapsed_s=entered - started)
    durable_json(receipt_path, receipt, new=True)
    proc, tracked, pipe, old_subreaper = None, {}, [], None
    protected, original_handlers = {os.getpid(), os.getppid()}, {}
    cleanup_result = dict(verified=True, remaining=[], recorded=[], signal_events=[], reap_events=[],
                          process_groups_signalled=False, method='no_child_launched')
    try:
        snapshot, spec = guard_snapshot(root, os.getpid(), bounds['work_deadline_monotonic'])
        protected.add(snapshot['model_pid'])
        config = spec['supervisor']
        entry = Path(config['child_entry'])
        if entry.is_absolute() or '..' in entry.parts or entry.suffix != '.py' or entry.as_posix() not in spec['source_hashes']:
            raise PermissionError('child entry is not a relative frozen own source')
        child_path, python_path = no_links(root / entry), no_links(config['python_executable'])
        if digest(child_path.read_bytes()) != spec['source_hashes'][entry.as_posix()] or digest(python_path.read_bytes()) != config['python_sha256']:
            raise PermissionError('child/interpreter bytes differ before supervision')
        if not isinstance(argv, list) or len(argv) < 2 or argv[:2] != [str(python_path), str(child_path)] or any(not isinstance(x, str) or '\0' in x for x in argv):
            raise PermissionError('supervised command does not use frozen own Python child entry')
        if descendants(os.getpid()):
            raise PermissionError('stage already has children; do not adopt or terminate unrelated work')
        libc = ctypes.CDLL(None, use_errno=True)
        previous = ctypes.c_int()
        if libc.prctl(37, ctypes.byref(previous), 0, 0, 0) != 0 or libc.prctl(36, 1, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), 'owned descendant subreaper unavailable')
        old_subreaper = previous.value
        def interrupted(signum, frame):
            raise InterruptedError('own solve supervisor received signal ' + str(signum))
        for sig in [signal.SIGTERM, signal.SIGINT]:
            original_handlers[sig] = signal.signal(sig, interrupted)
        read_fd, write_fd = os.pipe()
        pipe = [read_fd, write_fd]
        env = dict(os.environ, **{PIPE_ENV: str(read_fd)})
        receipt.update(launch_attempted=True, argv=argv, guard=snapshot,
                       launch_attempted_monotonic=time.monotonic())
        durable_json(receipt_path, receipt)
        if time.monotonic() >= bounds['work_deadline_monotonic']:
            raise TimeoutError('admission/attempt evidence consumed cleanup-reserved solve time')
        with (evidence_dir / 'child.log').open('xb') as log:
            proc = subprocess.Popen(argv, cwd=root, env=env, stdin=subprocess.DEVNULL,
                                    stdout=log, stderr=subprocess.STDOUT,
                                    start_new_session=True, pass_fds=(read_fd,))
            os.close(read_fd); pipe.remove(read_fd)
            child = process_record(proc.pid)
            if child is None or child['ppid'] != os.getpid() or child['pgid'] != child['pid'] or child['sid'] != child['pid']:
                raise PermissionError('launched child identity/session could not be confirmed')
            fd = _pin(child)
            if fd is None:
                raise PermissionError('launched child could not be pinned to its actual identity')
            tracked[proc.pid] = dict(record=child, pidfd=fd, ownership='actual_Popen_child_new_session')
            token_path = evidence_dir / 'CHILD_AUTHORIZATION.json'
            token = dict(schema='owned_natural_solve_pipe_v1', guard=snapshot,
                         parent=snapshot['stage'], child=child, nonce=uuid.uuid4().hex,
                         authorization_path=str(token_path), **bounds)
            token_file_sha = durable_json(token_path, token, new=True)
            receipt.update(launch_confirmed=True, child=child,
                           child_handshake_sha256=digest(canonical(token)),
                           child_authorization_file_sha256=token_file_sha)
            durable_json(receipt_path, receipt)
            _pipe_write(write_fd, canonical(token), bounds['work_deadline_monotonic'])
            os.close(write_fd); pipe.remove(write_fd)
            while proc.poll() is None:
                _observe(tracked, os.getpid(), protected)
                current_guard, _ = guard_snapshot(root, os.getpid(), bounds['work_deadline_monotonic'])
                if current_guard != snapshot:
                    raise PermissionError('actual guard/process/slot bytes changed during solve')
                if time.monotonic() >= bounds['work_deadline_monotonic']:
                    raise TimeoutError('whole solve reached cleanup-reserved external deadline')
                time.sleep(min(.05, max(0, bounds['work_deadline_monotonic'] - time.monotonic())))
            receipt['child_returncode'] = proc.returncode
    except BaseException as exc:
        receipt['error'] = type(exc).__name__ + ': ' + str(exc)
    finally:
        try:
            for fd in pipe:
                try:
                    os.close(fd)
                except OSError:
                    pass
            for sig in original_handlers:
                signal.signal(sig, signal.SIG_IGN)
            try:
                if proc is not None:
                    cleanup_result = cleanup_owned(proc, tracked, os.getpid(), protected,
                                                   bounds['cleanup_deadline_monotonic'])
                    receipt['child_returncode'] = proc.poll()
            except BaseException as exc:
                cleanup_result = dict(verified=False, remaining=None, cleanup_unconfirmed=True,
                                      error=type(exc).__name__ + ': ' + str(exc),
                                      process_groups_signalled=False)
            for item in tracked.values():
                try:
                    os.close(item['pidfd'])
                except OSError as exc:
                    cleanup_result.update(verified=False, close_error=str(exc))
            if old_subreaper is not None and cleanup_result['verified']:
                if ctypes.CDLL(None, use_errno=True).prctl(36, old_subreaper, 0, 0, 0) != 0:
                    cleanup_result['verified'] = False
                    cleanup_result['restore_subreaper_failed'] = True
            receipt.update(owned_cleanup=cleanup_result, complete=True,
                           elapsed_s=time.monotonic() - started,
                           within_total_deadline=time.monotonic() < bounds['total_deadline_monotonic'])
            child_log = evidence_dir / 'child.log'
            if child_log.is_file():
                try:
                    log_data = child_log.read_bytes()
                    receipt['child_log'] = dict(path='child.log', sha256=digest(log_data), bytes=len(log_data))
                except OSError as exc:
                    receipt['error'] = 'child log sealing unconfirmed: ' + str(exc)
            receipt['passed'] = (receipt['error'] is None and receipt['launch_confirmed']
                                 and receipt['child_returncode'] == 0 and cleanup_result['verified']
                                 and receipt['within_total_deadline'])
            durable_json(receipt_path, receipt)
            finalized = time.monotonic()
            receipt['receipt_commit_elapsed_s'] = finalized - started
            if finalized >= bounds['total_deadline_monotonic']:
                receipt.update(passed=False, within_total_deadline=False,
                               error=receipt['error'] or 'TimeoutError: final receipt exceeded absolute solve deadline')
            durable_json(receipt_path, receipt)
            if time.monotonic() >= bounds['total_deadline_monotonic'] and receipt['within_total_deadline']:
                receipt.update(passed=False, within_total_deadline=False,
                               error='TimeoutError: final receipt sealing exceeded absolute solve deadline')
                durable_json(receipt_path, receipt)
        finally:
            for sig, handler in original_handlers.items():
                signal.signal(sig, handler)
    return receipt
