"""AMD-only, once-only recovery of expired, never-started FIFO waiting monitors.

Leaves the existing FIFO implementation, ticket ordering and task commands intact.
This dated entry point is restricted to the explicitly owned tickets 133 and 134.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

WAIT_ERROR = 'TimeoutError: FIFO wait lifetime expired; retained for inspection'
FIFO_SHA = '4f1714fdd3ffd092a526e29860bdccf718249ced65e9dbb35947c0ecf8885f3f'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_new(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def proc_record(pid):
    try:
        base = Path('/proc') / str(pid)
        fields = (base / 'stat').read_text().rsplit(')', 1)[1].split()
        command = (base / 'cmdline').read_bytes()
        return dict(pid=pid, starttime=fields[19], state=fields[0],
                    ppid=int(fields[1]), sid=int(fields[3]),
                    command_sha256=hashlib.sha256(command).hexdigest(),
                    argv=[x.decode(errors='surrogateescape') for x in command.split(b'\0') if x])
    except (FileNotFoundError, ProcessLookupError):
        return None


def matching_monitors(argv):
    found = []
    for path in Path('/proc').glob('[0-9]*'):
        item = proc_record(int(path.name))
        if item and item['state'] not in ('Z', 'X'):
            args = item['argv']
            # Also reject equivalent invocations with different Python flags.
            if argv[2] in args and '_run' in args:
                pairs = list(zip(args, args[1:]))
                if ('--root', argv[4]) in pairs and ('--ticket', argv[-1]) in pairs:
                    found.append(item)
    return found


def verify_files(files):
    for name, digest in files.items():
        if sha(name) != digest:
            raise RuntimeError('frozen file changed: ' + name)


def recover(plan, entry, out):
    """Hold the original registry lock through validation and monitor registration.

    A failed or ambiguous launch is retained for inspection and never retried.
    No task is resubmitted, no running monitor is signalled, and no head is skipped.
    """
    root, out = Path(plan['fifo_root']), Path(out)
    number = entry['queued']['ticket']
    target = root / 'tickets' / ('%08d.json' % number)
    intent = out / ('RECOVERY_%d_INTENT.json' % number)
    if intent.exists():
        raise RuntimeError('recovery intent already exists; inspect, never retry')
    with (root / 'registry.lock').open('r+b') as lock:
        until = time.monotonic() + 5
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= until:
                    raise TimeoutError('registry lock unavailable; no mutation')
                time.sleep(.05)
        raw = target.read_bytes()
        item = json.loads(raw)
        expected = entry['queued']
        # Every original immutable ticket field must remain present and identical.
        if any(item.get(k) != v for k, v in expected.items() if k != 'state'):
            raise RuntimeError('original ticket fields changed')
        if item['state'] in ('running', 'completed', 'cancelled_before_start'):
            return dict(outcome='original_advanced_untouched', state=item['state'])
        old = proc_record(entry['monitor']['pid'])
        old_live = (old and old['starttime'] == entry['monitor']['starttime']
                    and old['state'] not in ('Z', 'X'))
        if old_live and old['command_sha256'] != entry['monitor']['command_sha256']:
            raise RuntimeError('original live monitor command changed')
        if item == expected:
            if not old_live:
                raise RuntimeError('queued monitor disappeared without exact wait timeout')
            return dict(outcome='waiting_original')
        held = dict(expected, state='held_for_inspection', error=WAIT_ERROR)
        if item != held:
            raise RuntimeError('not an exact never-started waiting-timeout ticket')
        if old_live:
            return dict(outcome='waiting_original_retirement')
        if time.time() >= plan['expires_unix']:
            raise TimeoutError('recovery authorization window expired')
        for path in entry['must_be_absent']:
            if Path(path).exists():
                raise RuntimeError('possible task execution evidence: ' + path)
        verify_files(plan['sources'])
        verify_files(entry['frozen_files'])
        argv = entry['monitor_argv']
        if matching_monitors(argv):
            raise RuntimeError('another live waiting monitor exists')
        # Preserve the exact failed bytes before any mutation, then use an
        # exclusive intent shared by all invocations of this frozen recovery.
        write_new(intent, dict(ticket=number, observed_unix=time.time(),
                               failed_ticket_sha256=hashlib.sha256(raw).hexdigest(),
                               original_monitor=entry['monitor'], old_observation=old,
                               failed_ticket_utf8=raw.decode('utf-8'),
                               original_ticket=expected, monitor_argv=argv))
        replacement = dict(expected, wait_recovery=dict(intent=str(intent),
                           original_error=WAIT_ERROR, original_monitor=entry['monitor']))
        pending = target.with_name(target.name + '.wait-recovery.pending')
        write_new(pending, replacement)
        os.replace(pending, target)
        process = None
        try:
            with (out / ('monitor_%d.log' % number)).open('xb') as stream:
                process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=stream,
                                           stderr=subprocess.STDOUT, start_new_session=True)
            record = proc_record(process.pid)
            if (not record or record['state'] in ('Z', 'X')
                    or record['argv'] != argv or record['sid'] != process.pid
                    or record['ppid'] != os.getpid()):
                raise RuntimeError('new monitor identity not bound; inspect existing PID')
            receipt = dict(ticket=number, outcome='waiting_monitor_recovered',
                           monitor=record, observed_unix=time.time(),
                           task_command_unchanged=True, task_execution_not_repeated=True)
            write_new(out / ('RECOVERY_%d_RESULT.json' % number), receipt)
            return receipt
        except BaseException as exc:
            # After Popen succeeds the monitor may continue; never roll back its
            # ticket or launch a second monitor on uncertain registration.
            if process is None:
                pending = target.with_name(target.name + '.wait-recovery.pending')
                with pending.open('xb') as stream:
                    stream.write(raw)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(pending, target)
            write_new(out / ('RECOVERY_%d_FAILURE.json' % number),
                      dict(error=type(exc).__name__ + ': ' + str(exc),
                           monitor_pid=process.pid if process else None,
                           monitor_may_continue=process is not None,
                           automatic_retry_allowed=False))
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--plan-sha256', required=True)
    args = parser.parse_args()
    if sys.platform != 'linux' or sha(args.plan) != args.plan_sha256:
        raise RuntimeError('AMD Linux and exact frozen plan required')
    plan = json.loads(args.plan.read_bytes())
    out = args.plan.resolve().parent
    if (plan['schema'] != 'owned_fifo_wait_recovery_133_134_v1'
            or plan['fifo_root'] != '/workspace/team/task_fifo'
            or [x['queued']['ticket'] for x in plan['entries']] != [133, 134]
            or plan['sources'].get(str(Path(__file__).resolve())) != sha(__file__)
            or plan['sources'].get(plan['fifo_source']) != FIFO_SHA
            or not 0 < plan['expires_unix'] - time.time() < 86400):
        raise RuntimeError('recovery scope/source/window mismatch')
    for entry in plan['entries']:
        number = entry['queued']['ticket']
        expected_argv = ['/usr/bin/python3', '-B', plan['fifo_source'],
                         '--root', plan['fifo_root'], '_run', '--ticket', str(number)]
        if (entry['monitor_argv'] != expected_argv
                or entry['queued']['state'] != 'queued'
                or entry['queued']['adopted_process'] is not None
                or not entry['frozen_files']
                or not entry['queued']['cwd'].startswith('/workspace/team/runs/fpga_teammate/')
                or entry['must_be_absent'] != [
                    str(Path(plan['fifo_root']) / ('task_%08d.log' % number)),
                    str(Path(entry['queued']['completion_json']).parent)]):
            raise RuntimeError('never-started ticket binding mismatch')
    verify_files(plan['sources'])
    write_new(out / 'WATCH_INTENT.json', dict(plan_sha256=args.plan_sha256,
                                            started_unix=time.time(), pid=os.getpid()))
    pending = list(plan['entries'])
    outcomes = {}
    try:
        while pending and time.time() < plan['expires_unix']:
            for entry in list(pending):
                result = recover(plan, entry, out)
                if result['outcome'] not in ('waiting_original', 'waiting_original_retirement'):
                    outcomes[str(entry['queued']['ticket'])] = result
                    pending.remove(entry)
            if pending:
                time.sleep(min(30, max(0, plan['expires_unix'] - time.time())))
        if pending:
            raise TimeoutError('watch window ended; remaining tickets left untouched')
    except BaseException as exc:
        write_new(out / 'WATCH_FAILURE.json', dict(error=type(exc).__name__ + ': ' + str(exc),
                   outcomes=outcomes, pending=[e['queued']['ticket'] for e in pending]))
        raise
    write_new(out / 'WATCH_RESULT.json', dict(complete=True, outcomes=outcomes,
                                             ended_unix=time.time()))


if __name__ == '__main__':
    main()
