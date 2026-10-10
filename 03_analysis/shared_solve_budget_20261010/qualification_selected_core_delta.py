"""AMD-only changes to the selected peer core, never replay old CPU suites.

Hard cleanup clamp, non-reaped leader ownership, injected identity refusal,
cancellation during the new birth-capture window, and the changed consumer ABI.
Resource admission/clock age/faults are synthetic; CPU children are real.
"""
import ctypes, hashlib, json, os, signal, subprocess, sys, time, types
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve()
OUT = Path(sys.argv[2]).resolve()
assert sys.platform == 'linux' and sys.dont_write_bytecode
assert ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0
OUT.mkdir(exist_ok=False)
sys.path.insert(0, str(ROOT))
import deadline_supervisor as owned
import shared_budget as budget

def deny_network(event, arguments):
    if event in ('socket.connect', 'socket.bind'):
        raise AssertionError('CPU delta qualification cannot access the network')
sys.addaudithook(deny_network)
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
manifest = json.loads((ROOT/'SOURCE_MANIFEST.json').read_bytes())
assert all(sha(ROOT/n) == h for n, h in manifest.items())
real_popen, real_killpg = subprocess.Popen, os.killpg
real_waitid, real_read_text = os.waitid, Path.read_text
records = []
children = []

def identity(pid):
    try:
        f = real_read_text(Path('/proc')/str(pid)/'stat').rsplit(')', 1)[1].split()
    except FileNotFoundError:
        return None
    return dict(pid=pid, birth=int(f[19]), pgid=int(f[2]), sid=int(f[3]))

sentinel = real_popen(['/usr/bin/python3', '-B', '-c', 'import time;time.sleep(20)'],
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
sentinel_id = identity(sentinel.pid)

def safe():
    assert identity(sentinel.pid) == sentinel_id and sentinel.poll() is None

def tracked_launch(*args, **kwargs):
    p = real_popen(*args, **kwargs)
    children.append((p, identity(p.pid)))
    return p

def folder(name):
    p = OUT/name
    p.mkdir()
    return p

def record(name, **values):
    safe()
    records.append(dict(case=name, passed=True, **values))

owned.subprocess.Popen = tracked_launch
try:
    p = folder('peer_core_hard_cleanup_limit')
    start = time.monotonic()
    work, hard = start+.12, start+.28
    receipt = owned.owned_command(['/usr/bin/python3', '-B', '-c', 'import time;time.sleep(10)'],
        p, p/'log', 1., deadline=work, cleanup_deadline=hard)
    assert receipt['timeout'] and receipt['returncode'] < 0 and not receipt['remaining_live_group']
    assert receipt['cleanup_deadline_monotonic'] == hard == receipt['cleanup_limit_monotonic']
    assert receipt['cleanup_deadline_monotonic'] < receipt['deadline_monotonic']+10
    record('peer_core_hard_cleanup_limit', receipt=receipt, shortened_CPU_clock=True)

    p = folder('leader_waitable_until_group_signal')
    checks = []
    def checked_killpg(pgid, sig):
        child, birth = children[-1]
        assert pgid == child.pid != sentinel.pid and identity(pgid) == birth
        status = real_waitid(os.P_PID, pgid, os.WEXITED|os.WNOHANG|os.WNOWAIT)
        assert status is not None and child.returncode is None
        checks.append(dict(identity=birth, leader_waitable=True, popen_unreaped=True))
        return real_killpg(pgid, sig)
    os.killpg = checked_killpg
    try:
        code = 'import os,time;pid=os.fork();time.sleep(10) if pid==0 else None;os._exit(0)'
        receipt = owned.owned_command(['/usr/bin/python3', '-B', '-c', code], p, p/'log', 1.)
    finally:
        os.killpg = real_killpg
    assert checks and receipt['returncode'] == 0 and not receipt['remaining_live_group']
    record('leader_waitable_until_group_signal', receipt=receipt, ownership_checks=checks)

    p = folder('injected_birth_mismatch_refuses_signal')
    signal_attempts = []
    stat_reads = []
    def mismatched_stat(path, *args, **kwargs):
        text = real_read_text(path, *args, **kwargs)
        if children and path == Path('/proc')/str(children[-1][0].pid)/'stat':
            stat_reads.append(True)
            if len(stat_reads) >= 2:
                prefix, tail = text.rsplit(')', 1)
                fields = tail.split()
                fields[19] = str(int(fields[19])+1)
                return prefix+') '+' '.join(fields)
        return text
    def forbidden_signal(*args):
        signal_attempts.append(args)
        raise AssertionError('must not signal uncertain ownership')
    Path.read_text, os.killpg = mismatched_stat, forbidden_signal
    refused = False
    try:
        owned.owned_command(['/usr/bin/python3', '-B', '-c', 'pass'], p, p/'log', 1.)
    except RuntimeError as error:
        refused = 'identity changed' in str(error)
    finally:
        Path.read_text, os.killpg = real_read_text, real_killpg
    assert refused and len(stat_reads) >= 2 and not signal_attempts
    child, birth = children[-1]
    assert identity(child.pid) == birth
    child.wait(timeout=1)
    record('injected_birth_mismatch_refuses_signal', fault_is_synthetic=True,
           signal_attempts=signal_attempts, refused=True, external_fixture_reap=True)

    p = folder('cancel_during_new_birth_capture')
    handlers = {s: signal.getsignal(s) for s in (signal.SIGTERM, signal.SIGINT)}
    injected = []
    def cancel_on_capture(path, *args, **kwargs):
        text = real_read_text(path, *args, **kwargs)
        if children and path == Path('/proc')/str(children[-1][0].pid)/'stat' and not injected:
            injected.append(True)
            os.kill(os.getpid(), signal.SIGTERM)
        return text
    Path.read_text = cancel_on_capture
    cancelled = False
    try:
        owned.owned_command(['/usr/bin/python3', '-B', '-c', 'import time;time.sleep(10)'], p, p/'log', 1.)
    except InterruptedError:
        cancelled = True
    finally:
        Path.read_text = real_read_text
    child, birth = children[-1]
    assert cancelled and injected and child.returncode is not None and identity(child.pid) is None
    assert all(signal.getsignal(s) == h for s, h in handlers.items())
    record('cancel_during_new_birth_capture', cancelled_after_handover=True,
           child_reaped=True, handlers_restored=True)

    p = folder('selected_consumer_ABI')
    calls = []
    actual_owned = owned.owned_command
    def observed_owned(*args, **kwargs):
        receipt = actual_owned(*args, **kwargs)
        calls.append(dict(deadline=kwargs['deadline'], cleanup_limit=kwargs.get('cleanup_deadline'),
                          receipt=receipt))
        return receipt
    owned.owned_command = observed_owned
    def forbidden_legacy(*args, **kwargs):
        raise AssertionError('historical core must not be called')
    b = budget.SolveBudget(300, parent_started=time.monotonic()-299)
    receipt = b.owned_operation(forbidden_legacy)(['/usr/bin/python3', '-B', '-c', 'pass'], p, p/'budget.log', 300)
    assert receipt['returncode'] == 0 and calls[-1]['deadline'] == b.end
    import three_arm_queue_20261005 as queue
    old_validate, old_launch, old_resource = queue.validate, queue.launch_args, queue.official.resource_module
    try:
        queue.validate = lambda plan: None
        queue.launch_args = lambda *a: ['/usr/bin/python3', '-B', '-c', 'raise SystemExit(1)']
        queue.official.resource_module = lambda: types.SimpleNamespace(check_resource=lambda *a: None)
        plan = dict(kit=str(p/'synthetic_kit'), sources=dict(root=str(ROOT), model_feedback=True),
                    allow_shared_budget_failure=True, solve_supervisor_s=310, solve_deadline_s=300)
        result = queue.execute_row(plan, queue.launch_args(None), dict(arm='A', evaluator_dir=str(p/'unread')), p, None)
    finally:
        queue.validate, queue.launch_args, queue.official.resource_module = old_validate, old_launch, old_resource
        owned.owned_command = actual_owned
    clock = json.loads((p/'SOLVE_CLOCK.json').read_bytes())
    assert len(calls) == 2 and calls[-1]['deadline'] == calls[-1]['cleanup_limit'] == clock['started_monotonic']+310
    assert clock['owned_deadline_source_sha256'] == sha(ROOT/'deadline_supervisor.py')
    assert result['complete'] is False and result['error'] == 'Solver supervision failure'
    record('selected_consumer_ABI', calls=calls, clock=clock, queue_admission_synthetic=True,
           B_main_not_executed=True)
finally:
    owned.subprocess.Popen, os.killpg = real_popen, real_killpg
    os.waitid, Path.read_text = real_waitid, real_read_text
    for child, birth in children:
        current = identity(child.pid)
        if current is not None:
            assert current == birth
            if child.poll() is None:
                real_killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=2)
    safe()
    assert identity(sentinel.pid) == sentinel_id
    sentinel.kill()
    sentinel.wait(timeout=2)
assert identity(sentinel.pid) is None
assert all(sha(ROOT/n) == h for n, h in manifest.items())
report = dict(passed=True, controls=records, source_manifest=manifest, independent_sentinel_retired=True,
    old_8_or_9_suite_replayed=False, new_model_calls=0, new_EDA=0, new_FIFO=0,
    physical300=False, production_B_CLI=False, real_model_cancel_idle=False, full_production_chain=False)
(OUT/'QUALIFICATION_RESULT.json').write_text(json.dumps(report, indent=2)+'\n')
print(json.dumps(dict(passed=True, controls=len(records))))
