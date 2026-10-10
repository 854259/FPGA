"""Owned Linux process group: absolute work end and one cleanup interval."""
import ctypes
import hashlib
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import threading
import time


class DeadlineBeforeLaunch(RuntimeError):
    pass


def _stat(pid):
    try:
        fields = (Path('/proc')/str(pid)/'stat').read_text().rsplit(')', 1)[1].split()
    except FileNotFoundError:
        return None
    return dict(pid=pid, starttime=int(fields[19]), pgid=int(fields[2]), sid=int(fields[3]))


def _group(pgid, birth):
    leader = _stat(pgid)
    if leader is not None and leader['starttime'] != birth:
        raise RuntimeError('Owned leader identity changed; refuse group signal')
    result = []
    for path in Path('/proc').glob('[0-9]*'):
        try:
            identity = _stat(int(path.name))
            if identity is not None and identity['pgid'] == pgid:
                assert identity['starttime'] >= birth
                result.append(identity)
        except (FileNotFoundError, ProcessLookupError):
            continue
    return result


def owned_command(argv, cwd, log, seconds, *, deadline, cleanup_deadline=None):
    """Match the original receipt keys; do not refresh work or cleanup budgets.

    Popen itself is synchronous. Recompute the remaining wait after it returns;
    this is not evidence that a blocked Popen can be interrupted at the deadline.
    The caller must be a subreaper so same-group adopted children can be reaped.
    """
    assert sys.platform == 'linux' and threading.current_thread() is threading.main_thread()
    flag = ctypes.c_int()
    assert ctypes.CDLL(None, use_errno=True).prctl(37, ctypes.byref(flag), 0, 0, 0) == 0 and flag.value == 1
    assert isinstance(argv, list) and argv and all(isinstance(x, str) for x in argv)
    for value in (seconds, deadline):
        assert type(value) in (int, float) and math.isfinite(value)
    assert 0 < seconds <= 310 and deadline >= 0
    if cleanup_deadline is not None:
        assert type(cleanup_deadline) in (int, float) and math.isfinite(cleanup_deadline)
        assert cleanup_deadline >= deadline
    started = time.monotonic()
    end = min(deadline, started + seconds)
    if end <= started:
        raise DeadlineBeforeLaunch('Absolute solve deadline exhausted before launch')
    proc, birth, pending_error = None, None, None
    result = dict(timeout=False, launch_error=None, returncode=None, group_signals=[])
    alive, reaped, cleanup_end = [], False, None

    def cancelled(signum, frame):
        raise InterruptedError('Owned stage cancelled by signal '+str(signum))

    previous = {sig: signal.signal(sig, cancelled) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        with Path(log).open('xb') as stream:
            try:
                # File creation is also part of the work budget.
                if time.monotonic() >= end:
                    raise DeadlineBeforeLaunch('Absolute solve deadline exhausted before Popen')
                proc = subprocess.Popen(argv, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT,
                                        stdin=subprocess.DEVNULL, start_new_session=True)
                identity = _stat(proc.pid)
                assert identity and identity['pgid'] == identity['sid'] == proc.pid
                birth = identity['starttime']
                remaining = end-time.monotonic()
                if remaining <= 0:
                    result['timeout'] = True
                else:
                    try:
                        proc.wait(timeout=remaining)
                    except subprocess.TimeoutExpired:
                        result['timeout'] = True
            except InterruptedError as error:
                pending_error = error
            except OSError as error:
                result['launch_error'] = str(error)
            except BaseException as error:
                pending_error = error
            finally:
                # Cancellation must not skip same-group reap or restart its
                # clock. A guard can still kill the entire owning stage.
                for sig in previous:
                    signal.signal(sig, signal.SIG_IGN)
                cleanup_end = min(time.monotonic()+10, end+10)
                if cleanup_deadline is not None:
                    cleanup_end = min(cleanup_end, cleanup_deadline)
                if proc is not None:
                    if birth is None:
                        identity = _stat(proc.pid)
                        assert identity and identity['pgid'] == identity['sid'] == proc.pid
                        birth = identity['starttime']
                    alive = _group(proc.pid, birth)
                    if alive:
                        try:
                            os.killpg(proc.pid, signal.SIGKILL)
                            result['group_signals'].append('SIGKILL')
                        except ProcessLookupError:
                            pass
                    try:
                        proc.wait(timeout=max(0, cleanup_end-time.monotonic()))
                        reaped = True
                        result['returncode'] = proc.returncode
                    except subprocess.TimeoutExpired:
                        pass
                    while True:
                        try:
                            while os.waitpid(-proc.pid, os.WNOHANG)[0]:
                                pass
                        except ChildProcessError:
                            pass
                        alive = _group(proc.pid, birth)
                        if not alive or time.monotonic() >= cleanup_end:
                            break
                        time.sleep(min(.025, max(0, cleanup_end-time.monotonic())))
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    if alive or (proc is not None and not reaped):
        raise RuntimeError('Owned process cleanup incomplete at its single deadline')
    if pending_error is not None:
        raise pending_error
    log = Path(log)
    return dict(result, elapsed_s=time.monotonic()-started, remaining_live_group=[],
                log=str(log), log_sha256=hashlib.sha256(log.read_bytes()).hexdigest(), log_bytes=log.stat().st_size,
                work_deadline_monotonic=end, parent_deadline_monotonic=deadline,
                cleanup_deadline_monotonic=cleanup_end, cleanup_budget_s=10,
                leader_starttime=birth, leader_reaped=reaped if proc is not None else None)
