"""AMD-only total-48h amendment; resume only the unstarted suffix of FIFO132.

The original 36h process, plan, sources, receipts and failed exit stay intact.
A separately frozen authorization changes one budget expression in a loaded copy
of advance. The original FIFO adopts the new guarded continuation on ticket 132.
No completed row is regenerated, no call reservation is refunded, no model is
restarted, and no process is killed by this entry point.
"""
import argparse
import fcntl
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

ORIGINAL_ROOT = '/workspace/team/runs/fpga_teammate/prompt_table_feedback_full156x5_20261008_v1'
PLAN_SHA = 'c85226725bab88c08503cd9feda393378ef17c491fabebec4bea0abd930d954c'
QUEUE_SHA = '5371acf6c18ea9949d7943f4cc303126dfdeafe29ddf1657ee3738bbcc9cc3de'
FIFO_SHA = '4f1714fdd3ffd092a526e29860bdccf718249ced65e9dbb35947c0ecf8885f3f'
RECOVERY_SHA = '692305058c4499ffbe599ada3badb316f866e918da5a78df348e58ac146ca302'
WALL_ERROR = 'Wall budget cannot cover next solve and judge'
FIFO_ERROR = 'RuntimeError: Task failed or completion receipt is not verified; FIFO head retained'
TOTAL_SECONDS = 172800


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load_module(path, name):
    path = Path(path).resolve()
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read(path):
    return json.loads(Path(path).read_bytes())


def new_json(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())


def amended_advance(queue):
    """Derive exactly one explicit budget substitution from the bound old source."""
    source = Path(queue.__file__).read_text()
    if sha(queue.__file__) != QUEUE_SHA:
        raise RuntimeError('original queue source changed')
    body = source[source.index('def advance('):source.index('\ndef execute_row(')]
    old = "elapsed+plan['row_reservation_s'] <= plan['wall_seconds']"
    replacement = "elapsed+plan['row_reservation_s'] <= EXTENDED_TOTAL_SECONDS"
    if body.count(old) != 1 or 'EXTENDED_TOTAL_SECONDS' in body:
        raise RuntimeError('budget expression is not the reviewed original')
    amended = body.replace(old, replacement)
    assert amended.replace(replacement, old) == body
    scope = dict(vars(queue), EXTENDED_TOTAL_SECONDS=TOTAL_SECONDS)
    exec(compile(amended, str(Path(__file__)) + ':budget_amendment', 'exec'), scope)
    return scope['advance'], hashlib.sha256(amended.encode()).hexdigest()


def frozen(config):
    for name, expected in config['files'].items():
        if sha(name) != expected:
            raise RuntimeError('frozen file changed: ' + name)


def retired(records, recovery):
    for expected in records:
        current = recovery.proc_record(expected['pid'])
        if current and current['starttime'] == expected['starttime'] and current['state'] not in ('Z', 'X'):
            if current['command_sha256'] != expected['command_sha256']:
                raise RuntimeError('original process command changed')
            return False
    return True


def prefix_evidence(config, queue):
    root = Path(config['original_root'])
    plan = read(root/'PLAN.json')
    queue.validate(plan)
    header = read(root/'queue/QUEUE.json')
    digest = queue.digest(plan)
    if header != config['original_header'] or queue.digest(read(root/'queue/PLAN.json')) != digest:
        raise RuntimeError('original start time or queue plan changed')
    folders = sorted((root/'queue').glob('row_*'))
    if not 0 < len(folders) < len(plan['rows']):
        raise RuntimeError('continuation requires a nonempty incomplete prefix')
    if [p.name for p in folders] != ['row_%06d' % i for i in range(len(folders))]:
        raise RuntimeError('non-prefix results')
    bound = {}
    for folder, row in zip(folders, plan['rows']):
        queue.verify_terminal(folder, row, digest)
        for name in ('STARTED.json', 'TERMINAL.json', 'SEALED.json', 'EVIDENCE.zip'):
            bound[str(folder/name)] = sha(folder/name)
    return dict(completed_rows=len(folders), remaining_rows=len(plan['rows'])-len(folders),
                reserved_calls=sum(r['reserved_calls'] for r in plan['rows'][:len(folders)]),
                prefix_files=bound)


def eligible(config, recovery, fifo, queue):
    """Read-only admission. An ordinary failure can never become a time extension."""
    item = read(Path(config['fifo_root'])/'tickets/00000132.json')
    original = config['original_ticket']
    if item == original:
        if retired(config['original_processes'], recovery):
            raise RuntimeError('original running ticket has no original process')
        return dict(outcome='waiting_original')
    if item.get('state') == 'completed':
        if any(item.get(k) != original[k] for k in ('ticket', 'command', 'cwd', 'completion_json')):
            raise RuntimeError('unexpected completed ticket')
        return dict(outcome='original_completed_untouched')
    if item != dict(original, state='held_for_inspection', error=FIFO_ERROR):
        raise RuntimeError('not the exact original failed ticket')
    if not retired(config['original_processes'], recovery):
        return dict(outcome='waiting_original_retirement')
    if time.time()+670 >= config['deadline_unix']:
        raise TimeoutError('total 48h budget cannot cover another row')
    frozen(config)
    root = Path(config['original_root'])
    events = [json.loads(line) for line in (root/'queue/RUNNER_EVENTS.jsonl').read_text().splitlines()]
    last = events[-1]
    if (last.get('event'), last.get('error_type'), last.get('error')) != ('stopped', 'AssertionError', WALL_ERROR):
        raise RuntimeError('original queue did not stop solely on wall budget')
    if last['at_unix'] < config['original_header']['started_unix']+129600-670:
        raise RuntimeError('wall stop occurred before original budget boundary')
    guard = read(root/'guard/status.json')
    if not (guard.get('complete') is True and guard.get('passed') is False
            and guard.get('stage_rc') == 1 and guard.get('owned_cleanup', {}).get('verified') is True
            and guard.get('model_unchanged') is True and guard.get('protected_files_unchanged') is True
            and guard.get('own_slot_released') is True and guard.get('model_idle_after')):
        raise RuntimeError('original guard retirement or protected state is not verified')
    if any(k in guard for k in ('error', 'postflight_error', 'wrapper_cleanup_error', 'slot_release_error')):
        raise RuntimeError('additional original guard failure')
    for expected in guard['owned_cleanup'].get('recorded', []):
        current = recovery.proc_record(expected['pid'])
        if current and current['starttime'] == expected['starttime'] and current['state'] not in ('Z', 'X'):
            raise RuntimeError('an original guarded descendant is still alive')
    if fifo.head(config['fifo_root'])['ticket'] != 132 or not fifo.probe(item):
        raise RuntimeError('original FIFO head or idle resources changed')
    for name in ('runner.lock', 'queue.lock'):
        with (root/'queue'/name).open('r+b') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    result = prefix_evidence(config, queue)
    result.update(outcome='eligible', failed_ticket=item,
                  original_guard_sha256=sha(root/'guard/status.json'),
                  original_events_sha256=sha(root/'queue/RUNNER_EVENTS.jsonl'))
    return result


def command_for(config, plan_path, plan_sha):
    out = plan_path.parent
    command = list(config['original_ticket']['command'])
    timeout = math.ceil(config['deadline_unix']-time.time())+400
    if timeout <= 1070:
        raise TimeoutError('insufficient total budget for continuation admission')
    for flag, value in (('--guard-out', str(out/'guard48')), ('--owner', config['owner48']),
                        ('--stage-timeout-s', str(timeout)),
                        ('--slot-minutes', str(math.ceil((timeout+120)/60)))):
        command[command.index(flag)+1] = value
    boundary = command.index('--')
    command[boundary+1:] = ['/usr/bin/python3', '-B', str(Path(__file__).resolve()), 'run',
        '--plan', str(plan_path), '--plan-sha256', plan_sha, '--resource-check', '{resource_check}']
    return command


def bind_process(process, argv, recovery):
    until = time.monotonic()+3
    while True:
        record = recovery.proc_record(process.pid)
        if (record and record['state'] not in ('Z', 'X') and record['argv'] == argv
                and record['sid'] == process.pid and record['ppid'] == os.getpid()):
            return record
        if process.poll() is not None or time.monotonic() >= until:
            raise RuntimeError('launched PID identity is uncertain; inspect, never relaunch')
        time.sleep(.01)


def resume_once(config, plan_path, plan_sha, recovery, fifo, queue):
    out, root = plan_path.parent, Path(config['fifo_root'])
    intent = out/'RESUME_INTENT.json'
    if intent.exists():
        raise RuntimeError('continuation intent exists; no automatic retry')
    evidence = eligible(config, recovery, fifo, queue)
    if evidence['outcome'] != 'eligible':
        return evidence
    target = root/'tickets/00000132.json'
    command = command_for(config, plan_path, plan_sha)
    monitor_argv = ['/usr/bin/python3', '-B', config['fifo_source'], '--root', str(root), '_run', '--ticket', '132']
    with (root/'registry.lock').open('r+b') as lock:
        until = time.monotonic()+5
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= until:
                    raise TimeoutError('registry unavailable; no mutation')
                time.sleep(.05)
        raw = target.read_bytes()
        if json.loads(raw) != evidence['failed_ticket'] or fifo.head(root)['ticket'] != 132:
            raise RuntimeError('ticket/head changed during prefix verification')
        if not retired(config['original_processes'], recovery) or not fifo.probe(evidence['failed_ticket']):
            raise RuntimeError('resources changed during prefix verification')
        if recovery.matching_monitors(monitor_argv):
            raise RuntimeError('another ticket132 monitor exists')
        frozen(config)
        if (out/'guard48').exists() or (out/'EXECUTION_INTENT.json').exists():
            raise RuntimeError('continuation execution evidence already exists')
        new_json(intent, dict(plan_sha256=plan_sha, at_unix=time.time(),
            failed_ticket_utf8=raw.decode(), failed_ticket_sha256=hashlib.sha256(raw).hexdigest(),
            evidence=evidence, command=command, monitor_argv=monitor_argv,
            deadline_unix=config['deadline_unix'], total_seconds=TOTAL_SECONDS))
        guard_process = monitor_process = None
        try:
            with (out/'continuation_task.log').open('xb') as stream:
                guard_process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=stream,
                    stderr=subprocess.STDOUT, start_new_session=True, cwd=config['original_root'])
            guard = bind_process(guard_process, command[command.index('/usr/bin/flock'):], recovery)
            replacement = dict(config['original_ticket'])
            for key in ('started_at_utc', 'runner', 'child', 'task_fifo_sha256'):
                replacement.pop(key, None)
            replacement.update(state='queued', command=command, completion_json=str(out/'guard48/status.json'),
                slot_owner_prefix=config['owner48'], adopted_process={k:guard[k] for k in ('pid','starttime')},
                wall_extension=dict(intent=str(intent), original_plan_sha256=PLAN_SHA,
                                    total_seconds=TOTAL_SECONDS, deadline_unix=config['deadline_unix']))
            pending = target.with_name(target.name+'.wall48.pending')
            new_json(pending, replacement)
            os.replace(pending, target)
            with (out/'continuation_monitor.log').open('xb') as stream:
                monitor_process = subprocess.Popen(monitor_argv, stdin=subprocess.DEVNULL, stdout=stream,
                    stderr=subprocess.STDOUT, start_new_session=True)
            monitor = bind_process(monitor_process, monitor_argv, recovery)
            result = dict(outcome='suffix_continuation_adopted', ticket=132, guard=guard, monitor=monitor,
                          completed_prefix_rows=evidence['completed_rows'], remaining_rows=evidence['remaining_rows'],
                          deadline_unix=config['deadline_unix'], no_new_ticket=True, no_sample_repeated=True)
            new_json(out/'RESUME_RESULT.json', result)
            return result
        except BaseException as error:
            # Once Popen succeeds the task may be using the slot. Never roll its
            # ticket back, kill it, or launch another process on uncertain receipt.
            new_json(out/'RESUME_FAILURE.json', dict(error=type(error).__name__+': '+str(error),
                guard_pid=guard_process.pid if guard_process else None,
                monitor_pid=monitor_process.pid if monitor_process else None,
                task_may_continue=guard_process is not None, automatic_retry_allowed=False))
            raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['watch', 'run'])
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--plan-sha256', required=True)
    parser.add_argument('--resource-check', type=Path)
    args = parser.parse_args()
    path = args.plan.resolve()
    if sys.platform != 'linux' or not sys.dont_write_bytecode or sha(path) != args.plan_sha256:
        raise RuntimeError('AMD -B and exact extension plan required')
    config = read(path)
    if (config['schema'] != 'user_authorized_full132_total48h_v1'
            or config['original_root'] != ORIGINAL_ROOT or config['fifo_root'] != '/workspace/team/task_fifo'
            or config['original_ticket']['ticket'] != 132 or config['original_ticket']['state'] != 'running'
            or config['original_ticket']['adopted_process'] is not None
            or config['files'][str(Path(ORIGINAL_ROOT)/'PLAN.json')] != PLAN_SHA
            or config['files'][str(Path(ORIGINAL_ROOT)/'three_arm_queue_20261005.py')] != QUEUE_SHA
            or config['files'][str(Path(__file__).resolve())] != sha(__file__)
            or config['files'][config['fifo_source']] != FIFO_SHA
            or config['files'][config['recovery_source']] != RECOVERY_SHA
            or config['deadline_unix'] != config['original_header']['started_unix']+TOTAL_SECONDS
            or config['authorization'] != 'User explicitly requested total 48h on 2026-10-09'):
        raise RuntimeError('extension scope, authorization or fixed source mismatch')
    frozen(config)
    recovery = load_module(config['recovery_source'], 'wait_recovery_pr199')
    fifo = load_module(config['fifo_source'], 'original_fifo_48h_adoption')
    if args.action == 'watch':
        new_json(path.parent/'WATCH_INTENT.json', dict(plan_sha256=args.plan_sha256, pid=os.getpid(), at_unix=time.time()))
        try:
            while time.time()+670 < config['deadline_unix']:
                # Do not load project queue code or verify the live prefix while
                # the original monitor remains alive.
                if not retired(config['original_processes'], recovery):
                    time.sleep(30)
                    continue
                queue = load_module(Path(ORIGINAL_ROOT)/'three_arm_queue_20261005.py', 'original_queue_48h')
                result = resume_once(config, path, args.plan_sha256, recovery, fifo, queue)
                if result['outcome'].startswith('waiting_'):
                    time.sleep(30)
                    continue
                new_json(path.parent/'WATCH_RESULT.json', result)
                return
            raise TimeoutError('total extension window expired without admission')
        except BaseException as error:
            new_json(path.parent/'WATCH_FAILURE.json', dict(error=type(error).__name__+': '+str(error)))
            raise
    if args.resource_check is None:
        raise RuntimeError('fresh original guard resource check required')
    intent = read(path.parent/'RESUME_INTENT.json')
    if intent['plan_sha256'] != args.plan_sha256 or time.time()+670 >= config['deadline_unix']:
        raise RuntimeError('unbound or expired continuation')
    queue = load_module(Path(ORIGINAL_ROOT)/'three_arm_queue_20261005.py', 'original_queue_48h')
    for name, expected in intent['evidence']['prefix_files'].items():
        if sha(name) != expected:
            raise RuntimeError('completed prefix changed before continuation: '+name)
    advance, function_sha = amended_advance(queue)
    new_json(path.parent/'EXECUTION_INTENT.json', dict(plan_sha256=args.plan_sha256,
        original_queue_sha256=QUEUE_SHA, amended_advance_sha256=function_sha,
        total_seconds=TOTAL_SECONDS, original_header=config['original_header'],
        expected_prefix_rows=intent['evidence']['completed_rows'], at_unix=time.time()))
    queue.advance = advance
    queue.run_plan(Path(ORIGINAL_ROOT)/'PLAN.json', PLAN_SHA, Path(ORIGINAL_ROOT)/'queue', args.resource_check)


if __name__ == '__main__':
    main()
