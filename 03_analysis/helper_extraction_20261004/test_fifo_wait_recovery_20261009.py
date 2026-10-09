"""Run only on AMD; isolated synthetic FIFO, no model/EDA/production tickets."""
import copy
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

import fifo_wait_recovery_20261009 as recovery


def controls(root, original_fifo):
    root.mkdir(exist_ok=False)
    results = []
    fifo = root / 'task_fifo.py'
    fifo.write_bytes(original_fifo.read_bytes())
    assert recovery.sha(fifo) == recovery.FIFO_SHA

    def case(name):
        base = root / name
        (base / 'tickets').mkdir(parents=True)
        (base / 'registry.lock').touch()
        job = base / 'job'
        job.mkdir()
        frozen = job / 'frozen.txt'
        frozen.write_text('unchanged task input\n')
        queued = dict(schema='whole_task_fifo_v1', ticket=133, task_name='SYNTHETIC',
                      state='queued', accepted_at_utc='synthetic',
                      command=['MUST_NEVER_EXECUTE'], cwd=str(job),
                      completion_json=str(job / 'guard/status.json'),
                      slot_owner_prefix='SYNTHETIC', adopted_process=None)
        entry = dict(queued=queued,
                     monitor=dict(pid=999999991, starttime='1', command_sha256='old'),
                     monitor_argv=[sys.executable, '-B', str(fifo), '--root', str(base),
                                   '_run', '--ticket', '133'],
                     frozen_files={str(frozen): recovery.sha(frozen)},
                     must_be_absent=[str(base / 'task_00000133.log'), str(job / 'guard')])
        plan = dict(fifo_root=str(base), expires_unix=time.time() + 60,
                    sources={str(fifo): recovery.FIFO_SHA})
        held = dict(queued, state='held_for_inspection', error=recovery.WAIT_ERROR)
        target = base / 'tickets/00000133.json'
        recovery.write_new(target, held)
        return base, plan, entry, target, held

    base, plan, entry, target, held = case('real_monitor_waits_behind_held_head')
    # Use the unchanged FIFO controller against a synthetic predecessor. It
    # cannot become head, so its shared-resource probe and task command cannot run.
    predecessor = dict(held, ticket=132, task_name='SYNTHETIC_BLOCKED_HEAD')
    recovery.write_new(base / 'tickets/00000132.json', predecessor)
    before = target.read_bytes()
    with patch.object(recovery, 'matching_monitors', return_value=[]):
        result = recovery.recover(plan, entry, base)
    pid = result['monitor']['pid']
    try:
        time.sleep(.15)
        after = json.loads(target.read_bytes())
        assert after['state'] == 'queued'
        assert {k: after[k] for k in entry['queued']} == entry['queued']
        assert json.loads((base / 'tickets/00000132.json').read_bytes()) == predecessor
        assert not (base / 'task_00000133.log').exists()
        saved = json.loads((base / 'RECOVERY_133_INTENT.json').read_bytes())
        assert saved['failed_ticket_utf8'].encode() == before
        assert recovery.matching_monitors(entry['monitor_argv'])[0]['pid'] == pid
        try:
            recovery.recover(plan, entry, base)
        except RuntimeError as exc:
            assert 'intent already exists' in str(exc)
        else:
            raise AssertionError('duplicate recovery accepted')
    finally:
        record = recovery.proc_record(pid)
        assert record and record['starttime'] == result['monitor']['starttime']
        os.kill(pid, signal.SIGTERM)  # Only this newly created synthetic controller.
        waited, status = os.waitpid(pid, 0)
        assert waited == pid and recovery.proc_record(pid) is None
        recovery.write_new(base / 'OWNED_MONITOR_RETIREMENT.json',
                           dict(pid=pid, wait_status=status, retired=True))
    results.append(dict(case='real_monitor_waits_behind_held_head', passed=True,
                        original_fifo_source=True, controller_pid=pid, duplicate_refused=True))

    for name in ('wrong_error', 'started_field', 'task_log', 'guard_directory',
                 'frozen_drift', 'other_monitor', 'command_changed',
                 'queued_but_retired', 'expired_window'):
        base, plan, entry, target, held = case(name)
        if name == 'wrong_error':
            held['error'] = 'RuntimeError: task failed'
        elif name == 'started_field':
            held['started_at_utc'] = 'already ran'
        elif name == 'task_log':
            (base / 'task_00000133.log').write_text('started')
        elif name == 'guard_directory':
            (base / 'job/guard').mkdir()
            (base / 'job/guard/status.json').write_text('{}')
        elif name == 'frozen_drift':
            (base / 'job/frozen.txt').write_text('changed')
        elif name == 'command_changed':
            held['command'] = ['changed']
        elif name == 'queued_but_retired':
            held = copy.deepcopy(entry['queued'])
        elif name == 'expired_window':
            plan['expires_unix'] = time.time() - 1
        target.write_text(json.dumps(held))
        before = target.read_bytes()
        with patch.object(recovery, 'proc_record', return_value=None), \
                patch.object(recovery, 'matching_monitors', return_value=[{}] if name == 'other_monitor' else []), \
                patch.object(recovery.subprocess, 'Popen', side_effect=AssertionError('launch forbidden')) as launch:
            try:
                recovery.recover(plan, entry, base)
            except (RuntimeError, TimeoutError):
                pass
            else:
                raise AssertionError('negative accepted: ' + name)
            assert not launch.called
        assert target.read_bytes() == before
        assert not (base / 'RECOVERY_133_INTENT.json').exists()
        results.append(dict(case=name, refused=True, ticket_unchanged=True))

    for name, state in (('live_queued', 'queued'), ('live_held', 'held_for_inspection'),
                        ('original_running', 'running'), ('original_completed', 'completed')):
        base, plan, entry, target, held = case(name)
        if state != 'held_for_inspection':
            held = dict(entry['queued'], state=state)
        target.write_text(json.dumps(held))
        before = target.read_bytes()
        live = dict(entry['monitor'], state='S')
        with patch.object(recovery, 'proc_record', return_value=live), \
                patch.object(recovery.subprocess, 'Popen', side_effect=AssertionError('launch forbidden')) as launch:
            observed = recovery.recover(plan, entry, base)
            assert not launch.called
        assert target.read_bytes() == before
        results.append(dict(case=name, outcome=observed['outcome'], ticket_unchanged=True))

    for name in ('launch_fails', 'binding_unknown'):
        base, plan, entry, target, held = case(name)
        before = target.read_bytes()
        with patch.object(recovery, 'proc_record', return_value=None), \
                patch.object(recovery, 'matching_monitors', return_value=[]), \
                patch.object(recovery.subprocess, 'Popen',
                             side_effect=OSError('synthetic launch failure') if name == 'launch_fails' else None,
                             return_value=SimpleNamespace(pid=999999992)) as launch:
            try:
                recovery.recover(plan, entry, base)
            except (RuntimeError, OSError):
                pass
            else:
                raise AssertionError('expected launch/binding failure')
            assert launch.call_count == 1
            try:
                recovery.recover(plan, entry, base)
            except RuntimeError as exc:
                assert 'intent already exists' in str(exc)
            else:
                raise AssertionError('failed launch was retried')
            assert launch.call_count == 1
        failure = json.loads((base / 'RECOVERY_133_FAILURE.json').read_bytes())
        assert failure['automatic_retry_allowed'] is False
        assert failure['monitor_may_continue'] == (name == 'binding_unknown')
        assert (target.read_bytes() == before) == (name == 'launch_fails')
        results.append(dict(case=name, retained=True, duplicate_refused=True))
    return dict(passed=True, cases=results, model_calls=0, eda_commands=0,
                production_fifo_mutations=0, isolated_real_wait_monitors=1)


if __name__ == '__main__':
    if sys.platform != 'linux':
        raise SystemExit('AMD Linux only')
    root = Path(sys.argv[1]).resolve()
    result = controls(root, Path(sys.argv[2]).resolve())
    recovery.write_new(root.parent / 'RESULT.json', result)
    print(json.dumps(result))
