"""The existing owned-command supervisor, without host evaluation orchestration.

Projected from source SHA-256
680d8790d5031b4dd938af2790acf1296f710a81aedb7c0572110019e8abb54f.
Both functions retain their original AST. Linux callers must enable subreaping
and invoke owned_command in their owned main thread, as before.
"""
import hashlib
import math
import os
from pathlib import Path
import signal
import subprocess
import time

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def owned_command(argv, cwd, log, seconds, *, deadline=None, cleanup_seconds=10., cleanup_deadline=None):
    """Charge launch/wait to one monotonic deadline; clean only the owned group.

    Callers with an earlier parent start must pass its absolute deadline. Cleanup
    shares one reserve (at most 10 seconds), never a fresh reserve per operation.
    A delayed OS/Popen call cannot be preempted here: late returns fail closed.
    Linux callers must enable child-subreaping before invoking this function.
    """
    started = time.monotonic()
    for name, value in (("seconds", seconds), ("cleanup_seconds", cleanup_seconds),
                        ("deadline", deadline), ("cleanup_deadline", cleanup_deadline)):
        if name in ("deadline", "cleanup_deadline") and value is None:
            continue
        try:
            valid = not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
        except OverflowError:
            valid = False
        if not valid or (name not in ("deadline", "cleanup_deadline") and value <= 0):
            raise ValueError(name + " must be a finite " + ("number" if name == "deadline" else "positive number"))
    if cleanup_seconds > 10:
        raise ValueError("cleanup_seconds cannot exceed the 10 second total reserve")
    deadline = min(started + seconds, deadline) if deadline is not None else started + seconds
    cleanup_limit = cleanup_deadline
    if cleanup_limit is not None and cleanup_limit < deadline:
        raise ValueError("cleanup_deadline precedes the work deadline")
    proc = None
    leader_birth = None
    alive = []
    phase = "run"
    cancel_signal = None
    cleanup_started = None
    cleanup_deadline = None
    result = {"timeout": False, "launch_error": None, "returncode": None, "group_signals": []}

    def identity(pid):
        try:
            fields = (Path("/proc") / str(pid) / "stat").read_text().rsplit(")", 1)[1].split()
        except FileNotFoundError:
            return None
        return (int(fields[19]), int(fields[2]), int(fields[3]))

    def owned_members():
        # The leader remains waitable until after the only group signal. Its
        # PID therefore cannot be recycled while authorizing that signal.
        if leader_birth is None or identity(proc.pid) != (leader_birth, proc.pid, proc.pid):
            raise RuntimeError("owned leader identity changed; refuse group signal")
        members = []
        for directory in Path("/proc").glob("[0-9]*"):
            current = identity(int(directory.name))
            if current is not None and current[1] == proc.pid:
                if current[0] < leader_birth or current[2] != proc.pid:
                    raise RuntimeError("unknown process group ownership; refuse group signal")
                members.append(int(directory.name))
        return members

    def cancelled(signum, frame):
        nonlocal cancel_signal
        cancel_signal = signum
        # Defer Python's exception until Popen hands us ownership, and keep a
        # second cancellation from interrupting bounded cleanup. No child mask.
        if phase in ("launch", "cleanup"):
            return
        raise InterruptedError("owned stage cancelled by signal " + str(signum))

    previous = {sig: signal.signal(sig, cancelled) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        with Path(log).open("xb") as stream:
            try:
                if time.monotonic() >= deadline:
                    result["timeout"] = True
                else:
                    phase = "launch"
                    try:
                        proc = subprocess.Popen(argv, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT,
                                                stdin=subprocess.DEVNULL, start_new_session=True)
                        leader = identity(proc.pid)
                        if leader is None or leader[1:] != (proc.pid, proc.pid):
                            raise RuntimeError("owned launch identity unavailable")
                        leader_birth = leader[0]
                    finally:
                        phase = "run"
                    if cancel_signal is not None:
                        raise InterruptedError("owned stage cancelled by signal " + str(cancel_signal))
                    # Observe exit without reaping; retain the birth-bound
                    # leader until group authorization and cleanup below.
                    while os.waitid(os.P_PID, proc.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT) is None:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise subprocess.TimeoutExpired(argv, seconds)
                        time.sleep(min(.025, remaining))
                    result["timeout"] = time.monotonic() >= deadline
            except subprocess.TimeoutExpired:
                result["timeout"] = True
            except InterruptedError:
                raise
            except OSError as exc:
                result["launch_error"] = str(exc)
            finally:
                phase = "cleanup"
                cleanup_started = time.monotonic()
                cleanup_deadline = min(cleanup_started, deadline) + cleanup_seconds
                if cleanup_limit is not None:
                    cleanup_deadline = min(cleanup_deadline, cleanup_limit)
                if proc is not None:
                    owned_members()
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                        result["group_signals"].append("SIGKILL")
                    except ProcessLookupError:
                        pass
                    try:
                        proc.wait(timeout=max(0., cleanup_deadline - time.monotonic()))
                    except subprocess.TimeoutExpired:
                        pass
                    while True:
                        # Reap the leader through Popen first, then only adopted
                        # children in this exact owned PG, within the SAME end.
                        if proc.poll() is not None:
                            try:
                                while os.waitpid(-proc.pid, os.WNOHANG)[0]:
                                    pass
                            except ChildProcessError:
                                pass
                        alive = []
                        for directory in Path("/proc").glob("[0-9]*"):
                            try:
                                fields = (directory / "stat").read_text().rsplit(")", 1)[1].split()
                                if int(fields[2]) == proc.pid:
                                    alive.append(int(directory.name))
                            except (OSError, IndexError, ValueError):
                                continue
                        if not alive and proc.returncode is not None:
                            break
                        remaining = cleanup_deadline - time.monotonic()
                        if remaining <= 0:
                            raise RuntimeError("owned process cleanup deadline exceeded: " + str(alive))
                        time.sleep(min(.025, remaining))
                    result["returncode"] = proc.returncode
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)
    if cancel_signal is not None:
        raise InterruptedError("owned stage cancelled by signal " + str(cancel_signal))
    return {**result, "elapsed_s": time.monotonic() - started, "remaining_live_group": alive,
            "started_monotonic": started, "deadline_monotonic": deadline,
            "cleanup_started_monotonic": cleanup_started, "cleanup_deadline_monotonic": cleanup_deadline,
            "cleanup_limit_monotonic": cleanup_limit, "leader_starttime": leader_birth,
            "log": str(log), "log_sha256": sha(log), "log_bytes": Path(log).stat().st_size}
