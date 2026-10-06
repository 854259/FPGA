"""Exact original106 owned tree cleanup functions; stdlib imports only."""
import os,signal,subprocess,time
from pathlib import Path

def process_record(pid):
    try:
        fields = (Path('/proc') / str(pid) / 'stat').read_text().rsplit(')', 1)[1].split()
        return dict(pid=pid, starttime=fields[19], state=fields[0],
                    ppid=int(fields[1]), pgid=int(fields[2]), sid=int(fields[3]))
    except (FileNotFoundError, ProcessLookupError):
        return None

def descendants(pid):
    found, todo = {}, [pid]
    while todo:
        parent = todo.pop()
        try:
            threads = list((Path('/proc') / str(parent) / 'task').iterdir())
        except (FileNotFoundError, ProcessLookupError):
            continue
        for thread in threads:
            try:
                children = (thread / 'children').read_text().split()
            except (FileNotFoundError, ProcessLookupError):
                continue
            for child in map(int, children):
                row = process_record(child)
                if row and child not in found:
                    found[child] = row
                    todo.append(child)
    return found

def cleanup(proc, tracked, model_pid):
    """TERM stage cooperatively, then reap/kill only verified owned descendants."""
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=6)
        except subprocess.TimeoutExpired:
            pass
    deadline = time.monotonic() + 10
    while True:
        # The wrapper is a subreaper: detached worker sessions become our
        # children when their own parent exits, including fast-parent orphans.
        tracked.update(descendants(os.getpid()))
        active = []
        for pid, recorded in list(tracked.items()):
            if pid in (os.getpid(), model_pid):
                raise RuntimeError('protected PID unexpectedly entered the owned tree')
            current = process_record(pid)
            if not current or current['starttime'] != recorded['starttime']:
                continue
            if current['state'] == 'Z':
                try:
                    os.waitpid(pid, os.WNOHANG)
                except ChildProcessError:
                    pass
            else:
                active.append(current)
                try:
                    os.kill(pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        if proc:
            proc.poll()
        # A dying parent can fork after the first snapshot. Refresh adopted
        # children after signals/reaping before declaring that the tree is gone.
        newly_observed = descendants(os.getpid())
        tracked.update(newly_observed)
        remaining = []
        for pid, recorded in tracked.items():
            current = process_record(pid)
            if current and current['starttime'] == recorded['starttime']:
                remaining.append(current)
        if (not remaining and not newly_observed) or time.monotonic() >= deadline:
            return dict(verified=not remaining and not newly_observed, remaining=remaining,
                        recorded=list(tracked.values()), method='owned_tree_all_threads_subreaper')
        time.sleep(.05)
