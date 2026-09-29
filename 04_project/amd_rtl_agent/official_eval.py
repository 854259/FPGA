"""External-only evaluation driver using the pinned official judge and scorer.

Reference and testbench are never passed to the submission process. This module
is deliberately outside the submission directory and must not be shipped with it.
"""
from __future__ import annotations
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import http.client
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import zipfile
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
OFFICIAL = ROOT / 'official_reference'


def verify_http_protocol(path, expected_sha256):
    """Read-only admission check; a hash is not proof that environment gates passed."""
    path = Path(path).resolve()
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError('protocol hash mismatch')
    plan = json.loads(raw)
    for name, digest in plan['files_sha256'].items():
        # Frozen manifests prepared on Windows must also verify on Linux.
        relative = name.replace('\\', '/')
        parts = relative.split('/')
        if not relative or any(p in ('', '.', '..') or ':' in p for p in parts):
            raise ValueError('unsafe manifest path')
        item = path.parent.joinpath(*parts).resolve()
        if not item.is_relative_to(path.parent) or hashlib.sha256(item.read_bytes()).hexdigest() != digest:
            raise ValueError('input hash mismatch: ' + name)
    if plan.get('launch_ready') is not True or not plan.get('gates') or any(
            gate.get('status') != 'passed' for gate in plan['gates']):
        raise ValueError('protocol launch blocked: environment admission incomplete')
    return plan


def http_exchange(endpoint, route, payload, out, deadline_at, token=''):
    """One local request, absolute wall deadline, raw evidence, no redirect/retry.

    This is evaluator-side transport, not a model endpoint or an admission bypass.
    A transport timeout does not establish that remote work stopped: the batch
    supervisor must verify backend idle before allowing any subsequent solve.
    """
    parsed = urlsplit(endpoint)
    if (parsed.scheme != 'http' or parsed.hostname not in ('127.0.0.1', '::1') or
            parsed.username or parsed.password or parsed.path not in ('', '/') or
            parsed.query or parsed.fragment):
        raise ValueError('numeric loopback HTTP origin required')
    if route not in ('/v1/health', '/v1/solve', '/metrics'):
        raise ValueError('unsupported evaluator route')
    remaining = deadline_at - time.monotonic()
    if not math.isfinite(remaining) or remaining <= 0:
        raise TimeoutError('wall deadline reached before request')
    body = None if payload is None else json.dumps(payload, ensure_ascii=False).encode('utf-8')
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)  # A previous attempt, even partial, must never be replayed.
    started = time.monotonic()
    record = dict(started_at=time.time(), route=route, request_attempted=False,
                  response_complete=False, status=None, error=None,
                  body_sha256=hashlib.sha256(body).hexdigest() if body is not None else None)
    if route == '/v1/solve' and isinstance(payload, dict):
        record.update(task_id=payload.get('task_id'), nonce=payload.get('nonce'), mode=payload.get('mode'),
                      model_requests_reserved=2 if payload.get('mode') == 'agent' else 1,
                      model_executions=None)
    (out/'started.json').write_text(json.dumps(record, indent=2)+'\n', encoding='utf-8')
    conn = http.client.HTTPConnection(parsed.hostname, parsed.port or 80, timeout=remaining)
    timer, response = None, None
    expired = threading.Event()
    try:
        with (out/'response.bin').open('xb') as evidence:
            conn.connect()  # Numeric address: no proxy, DNS, redirect or implicit retry.
            sock = conn.sock

            def expire():
                expired.set()
                try:
                    sock.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass

            remaining = deadline_at - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('wall deadline reached while connecting')
            timer = threading.Timer(remaining, expire)
            timer.daemon = True
            timer.start()
            headers = {'Content-Type': 'application/json'}
            if token:
                headers['Authorization'] = 'Bearer ' + token
            record['request_attempted'] = True
            with (out/'started.json').open('w', encoding='utf-8') as started_file:
                started_file.write(json.dumps(record, indent=2)+'\n')
                started_file.flush()
                os.fsync(started_file.fileno())
            if expired.is_set():
                raise TimeoutError('wall deadline reached before send')
            conn.request('GET' if body is None else 'POST', route, body=body, headers=headers)
            response = conn.getresponse()
            record['status'] = response.status
            expected_length = response.length
            received = 0
            while True:
                chunk = response.read1(min(65536, 16 * 1024 * 1024 + 1 - received))
                if chunk:
                    evidence.write(chunk)
                    evidence.flush()
                    received += len(chunk)
                if expired.is_set() or time.monotonic() >= deadline_at:
                    raise TimeoutError('absolute HTTP wall deadline')
                if received > 16 * 1024 * 1024:
                    raise ValueError('HTTP response evidence limit exceeded')
                if not chunk:
                    break
            if expected_length is not None and received != expected_length:
                raise ValueError('incomplete HTTP body')
            if response.status != 200:
                raise ValueError('HTTP status ' + str(response.status))
            record['response_complete'] = True
    except BaseException as exc:
        # Avoid exception strings: they can embed URLs, credentials or payloads.
        record['error'] = 'wall_timeout' if expired.is_set() or isinstance(exc, TimeoutError) else type(exc).__name__
        raise
    finally:
        if timer:
            timer.cancel()
            timer.join()
        if response:
            response.close()
        conn.close()
        record['elapsed_s'] = time.monotonic() - started
        (out/'transport.json').write_text(json.dumps(record, indent=2)+'\n', encoding='utf-8')
    return (out/'response.bin').read_bytes(), record


def trace_call_accounting(events, mode):
    """Count trace-observed attempts, not guessed server executions or token usage."""
    if mode not in ('agent', 'baseline'):
        raise ValueError('invalid mode')
    rows = [json.loads(line) for line in events.splitlines() if line.strip()]
    if any(not isinstance(row, dict) for row in rows):
        raise ValueError('trace rows must be objects')
    starts = [row for row in rows if row.get('tool') == 'llm_start']
    ends = [row for row in rows if row.get('tool') == 'llm']
    cap = 2 if mode == 'agent' else 1
    indices = [row.get('round') for row in (starts if mode == 'agent' else ends)]
    if ((mode == 'baseline' and starts) or any(type(i) is not int for i in indices) or indices != list(range(len(indices))) or
            len(indices) > cap or len(ends) > len(indices)):
        raise ValueError('invalid or excessive model-call trace')
    end_indices = [row.get('round') for row in ends]
    if end_indices != list(range(len(end_indices))):
        raise ValueError('duplicate or unordered model completion')
    complete = bool(indices) and len(ends) == len(indices) and all(
        not row.get('error') and row.get('response_status', 'complete') == 'complete' and
        row.get('finish') in ('stop', 'length') and
        all(type(row.get(k)) is int and row[k] >= 0 for k in ('tokens_in', 'tokens_out'))
        for row in ends)
    return dict(reserved_upper_bound=cap, observed_attempts=len(indices) if indices else None,
                accounting_complete=complete, backend_executions=None,
                tokens_in=sum(r['tokens_in'] for r in ends) if complete else None,
                tokens_out=sum(r['tokens_out'] for r in ends) if complete else None,
                note='Empty/incomplete trace is unknown, never zero calls; server ledger still required.')


def solve_http(endpoint, request, out, batch_deadline_at):
    """Transport one admitted sample. Batch admission/supervision is caller-owned.

    Not wired to the CLI until the full resource/cancellation supervisor is ready.
    Only official request fields can cross the evaluator/submission boundary.
    """
    if set(request) != {'task_id', 'nonce', 'mode', 'prompt', 'interface', 'deadline_s'}:
        raise ValueError('exact official solve fields required')
    if any(not isinstance(request[k], str) for k in ('task_id', 'nonce', 'prompt', 'interface')):
        raise ValueError('solve text fields must be strings')
    seconds = request['deadline_s']
    if (request['mode'] not in ('agent', 'baseline') or type(seconds) not in (int, float)
            or not math.isfinite(seconds) or seconds <= 0):
        raise ValueError('invalid solve mode or deadline')
    # Do not shorten one sample's frozen budget to fit a nearly exhausted batch.
    if batch_deadline_at - time.monotonic() < seconds:
        raise TimeoutError('insufficient whole-batch time for unchanged solve budget')
    token = os.environ.get('FPGACHINA_TOKEN')
    if not token:
        raise ValueError('FPGACHINA_TOKEN required')
    out = Path(out)
    raw, transport = http_exchange(endpoint, '/v1/solve', request, out,
                                   min(batch_deadline_at, time.monotonic() + seconds), token)
    ledger = dict(mode=request['mode'], task_id=request['task_id'], nonce=request['nonce'],
                  reserved_upper_bound=2 if request['mode'] == 'agent' else 1,
                  observed_attempts=None, accounting_complete=False, backend_executions=None,
                  elapsed_s=transport['elapsed_s'], valid_response=False)
    try:
        value = json.loads(raw)
        if (not isinstance(value, dict) or value.get('task_id') != request['task_id'] or
                not isinstance(value.get('solution'), str) or not isinstance(value.get('trace'), str) or
                type(value.get('elapsed_s')) not in (int, float) or
                not math.isfinite(value['elapsed_s']) or value['elapsed_s'] < 0):
            raise ValueError('invalid solve response')
        (out/'solution.v').write_text(value['solution'], encoding='utf-8')
        (out/'trace.jsonl').write_text(value['trace'], encoding='utf-8')
        ledger.update(trace_call_accounting(value['trace'], request['mode']))
        ledger['valid_response'] = True
        return value, ledger
    finally:
        (out/'call-ledger.json').write_text(json.dumps(ledger, indent=2)+'\n', encoding='utf-8')


def backend_snapshot(raw, model):
    """Parse observed vLLM metrics exactly; missing/foreign/reset counters fail closed."""
    selected = {}
    names = ('num_requests_running', 'num_requests_waiting',
             'request_success_total', 'request_success_created')
    for line in raw.decode('utf-8').splitlines():
        match = re.fullmatch(r'vllm:(' + '|'.join(names) + r')\{(.*)\}\s+(\S+)', line)
        if not match:
            continue
        name, labels, number = match.groups()
        # These label values come from the fixed model service, not user prompts.
        pairs = re.findall(r'(\w+)="([^"\\]*)"', labels)
        values = dict(pairs)
        if (len(pairs) != len(values) or values.get('model_name') != model or
                values.get('engine') != '0'):
            raise ValueError('unexpected model/engine metrics')
        key = name + ':' + values.get('finished_reason', '')
        value = float(number)
        if key in selected or not math.isfinite(value) or value < 0:
            raise ValueError('invalid or duplicate model metrics')
        selected[key] = value
    if any(name + ':' not in selected for name in names[:2]):
        raise ValueError('backend idle metrics missing')
    counts = {k.split(':')[1]: v for k, v in selected.items() if k.startswith('request_success_total:')}
    created = {k.split(':')[1]: v for k, v in selected.items() if k.startswith('request_success_created:')}
    if not counts or counts.keys() != created.keys() or any(not n.is_integer() for n in counts.values()):
        raise ValueError('backend request ledger missing or invalid')
    return dict(running=selected['num_requests_running:'], waiting=selected['num_requests_waiting:'],
                counts=counts, created=created)


def backend_call_delta(before, after):
    if any(s[k] != 0 for s in (before, after) for k in ('running', 'waiting')):
        raise ValueError('backend not idle; no further solve permitted')
    if before['created'] != after['created'] or before['counts'].keys() != after['counts'].keys():
        raise ValueError('backend counters reset or service changed')
    delta = {k: after['counts'][k] - v for k, v in before['counts'].items()}
    if any(v < 0 or int(v) != v for v in delta.values()):
        raise ValueError('backend counters decreased or invalid')
    return {key: int(value) for key, value in delta.items()}


def wait_backend_idle(endpoint, model, out, deadline_at):
    """Bounded GET-only check; never cancel, restart or retry model generation."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    index = 0
    while time.monotonic() < deadline_at:
        raw, _ = http_exchange(endpoint, '/metrics', None, out/str(index), deadline_at)
        state = backend_snapshot(raw, model)
        if state['running'] == 0 and state['waiting'] == 0:
            return state
        index += 1
        time.sleep(max(0, min(.1, deadline_at-time.monotonic())))
    raise TimeoutError('backend did not become idle; stop batch')


def judge_candidate(task, solution, out, result_path, seconds, batch_deadline_at):
    """Bound the unchanged Linux judge and kill its entire owned process group.

    The official wrapper's subprocess timeout kills only its direct child. EDA
    grandchildren can survive even when that wrapper exits normally with a tool
    error, so cleanup must also run after exit code zero. No verdict is invented
    if the outer wall deadline interrupts the official result writer.
    """
    if os.name != 'posix':
        raise ValueError('Linux judge process groups required')
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0:
        raise ValueError('finite positive judge deadline required')
    started = time.monotonic()
    until = min(started + seconds, batch_deadline_at)
    if not math.isfinite(until) or until <= started:
        raise TimeoutError('batch deadline before judge launch')
    out, result_path = Path(out), Path(result_path).resolve()
    if result_path.exists():
        raise FileExistsError('official judgement already exists; no replay')
    out.mkdir(parents=True, exist_ok=False)
    record = dict(started_at=time.time(), pid=None, returncode=None, error=None,
                  deadline_s=seconds, process_group_cleanup=False)
    proc = None
    old_handler = None
    try:
        with (out/'process.log').open('xb') as log:
            # This scratch contains only the external evaluator's data. Never
            # expose it to the submission container or model process.
            with tempfile.TemporaryDirectory(prefix='rtl-judge-', dir=os.environ.get('EDA_TMP')) as scratch:
                env = dict(os.environ, SELFTEST_TMP=scratch)
                if threading.current_thread() is threading.main_thread():
                    def interrupted(signum, frame):
                        raise SystemExit(128 + signum)
                    old_handler = signal.signal(signal.SIGTERM, interrupted)
                try:
                    proc = subprocess.Popen([sys.executable, str(OFFICIAL/'selftest/judge.py'),
                        '--task', str(Path(task).resolve()), '--solution', str(Path(solution).resolve()),
                        '--outdir', str(out.resolve()), '--timeout', str(seconds),
                        '--json', str(result_path)], cwd=scratch, env=env,
                        stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                    record['pid'] = proc.pid
                    remaining = until - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError('batch deadline during judge launch')
                    record['returncode'] = proc.wait(timeout=remaining)
                    if record['returncode']:
                        raise subprocess.CalledProcessError(record['returncode'], 'official judge')
                finally:
                    if proc is not None:
                        try:
                            os.killpg(proc.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        proc.wait(timeout=5)
                        record['process_group_cleanup'] = True
                    # Preserve diagnostic text before removing our own scratch.
                    # Large compiler caches and binaries are not evaluation inputs.
                    saved = out/'interrupted_logs'
                    if record['returncode'] is None:
                        for path in Path(scratch).rglob('*'):
                            if path.is_file() and path.suffix in ('.log', '.jou', '.json'):
                                target = saved/path.relative_to(scratch)
                                target.parent.mkdir(parents=True, exist_ok=True)
                                shutil.copyfile(path, target)
        if not result_path.is_file():
            raise ValueError('official judge returned no result')
        return json.loads(result_path.read_text(encoding='utf-8'))
    except BaseException as exc:
        record['error'] = type(exc).__name__
        raise
    finally:
        if old_handler is not None:
            signal.signal(signal.SIGTERM, old_handler)
        record['elapsed_s'] = time.monotonic() - started
        (out/'supervisor.json').write_text(json.dumps(record, indent=2)+'\n', encoding='utf-8')


def run_http_batch(plan_path, plan_sha256, candidate_archive, out, endpoint,
                   backend_endpoint, batch_started_at):
    """Sequential evaluator orchestration, not yet a live CLI entry point.

    The launcher must include setup time in batch_started_at. Continuous resource
    cancellation and deployment receipts remain admission requirements; the real
    frozen protocol is blocked. Fixed local services exercise this orchestration
    without generating model answers or altering the official judge/scorer.
    """
    plan_path = Path(plan_path).resolve()
    plan = verify_http_protocol(plan_path, plan_sha256)
    if verify_upstream() != plan['official_commit']:
        raise ValueError('official commit differs from frozen protocol')
    raw_archive = Path(candidate_archive).read_bytes()
    if hashlib.sha256(raw_archive).hexdigest() != plan['candidate_archive_sha256']:
        raise ValueError('candidate archive hash mismatch')
    allowed = {'runtime.py', 'baseline.py', 'run.sh', 'run_baseline.sh', 'LICENSE.official',
               'README.md', 'upstream.json', 'skill/RTL_SKILL.md', 'skill/RTL_REPAIR_SKILL.md'}
    with zipfile.ZipFile(candidate_archive) as archive:
        if len(archive.namelist()) != len(allowed) or set(archive.namelist()) != allowed:
            raise ValueError('candidate archive allowlist mismatch')
        for name in allowed:
            if archive.read(name) != (ROOT/'submission'/name).read_bytes():
                raise ValueError('candidate source differs from frozen archive')
    ids = sorted(plan['selection']['task_ids'])
    samples = plan['samples_per_task_per_mode']
    if (not ids or len(ids) != len(set(ids)) or any(not re.fullmatch(r'[A-Za-z0-9_-]+', tid) for tid in ids)
            or type(samples) is not int or not 1 <= samples <= 5 or plan['modes'] != ['agent', 'baseline']
            or plan['agent_repairs_max'] != 1 or plan['model_retries'] != 0):
        raise ValueError('unsupported frozen sampling protocol')
    for key, upper in [('solve_requests_max', 40), ('model_requests_max', 60)]:
        if type(plan[key]) is not int or not 0 < plan[key] <= upper:
            raise ValueError('invalid request cap')
    for key in ('solve_deadline_s', 'judge_timeout_s', 'batch_wall_limit_s'):
        if type(plan[key]) not in (int, float) or not math.isfinite(plan[key]) or plan[key] <= 0:
            raise ValueError('finite positive wall budgets required')
    if not math.isfinite(batch_started_at) or batch_started_at > time.monotonic():
        raise ValueError('invalid batch start clock')
    until = batch_started_at + plan['batch_wall_limit_s']
    if time.monotonic() >= until:
        raise TimeoutError('whole-batch deadline already expired')
    # Each task's judge directory stays on the evaluator side. Read only the
    # separately hashed prompt when constructing an HTTP request.
    manifest = {name.replace('\\', '/'): digest for name, digest in plan['files_sha256'].items()}
    for tid in ids:
        key = f'agent-input/{tid}/prompt.txt'
        if key not in manifest or f'judge-only/{tid}/task.json' not in manifest:
            raise ValueError('frozen task manifest incomplete')
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=False)
    (out/'results').mkdir()
    rows = [dict(task_id=tid, sample=sample, mode=mode, state='not_started', nonce=uuid.uuid4().hex,
                 model_calls=None, timed_out=None)
            for tid in ids for sample in range(samples) for mode in plan['modes']]
    status = dict(complete=False, protocol_sha256=plan_sha256, rows=rows, expected_solves=len(rows),
                  solves_started=0, model_calls_reserved=0, verified_backend_calls=0,
                  started_at=time.time(), stop_reason=None,
                  resource_observations=[],
                  resource_supervision='boundary checks only; continuous cancellation not accepted')

    def save():
        status['elapsed_s'] = time.monotonic() - batch_started_at
        pending = out/'batch.pending.json'
        with pending.open('w', encoding='utf-8') as handle:
            json.dump(status, handle, ensure_ascii=False, indent=2)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        pending.replace(out/'batch.json')

    save()
    runtime = module('batch_runtime', ROOT/'submission/runtime.py')
    model = plan['model']['served_name']
    consecutive_timeouts = 0
    current = None
    try:
        health_raw, _ = http_exchange(endpoint, '/v1/health', None, out/'health', min(until, time.monotonic()+10),
                                      os.environ.get('FPGACHINA_TOKEN', ''))
        health = json.loads(health_raw)
        if health.get('ready') is not True or health.get('track') != 'rtl' or health.get('model') != model:
            raise ValueError('submission health does not match frozen model/track')
        for index, current in enumerate(rows):
            cap = 2 if current['mode'] == 'agent' else 1
            if (status['solves_started'] >= plan['solve_requests_max'] or
                    status['model_calls_reserved'] + cap > plan['model_requests_max']):
                status['stop_reason'] = 'request_cap'
                break
            # Leave time for unshortened solve, external judge, idle confirmation
            # and cleanup. The original per-solve budgets are never increased.
            if until - time.monotonic() < plan['solve_deadline_s'] + plan['judge_timeout_s'] + 10:
                status['stop_reason'] = 'whole_batch_time'
                break
            used = runtime.vram_gb()
            status['resource_observations'].append(dict(sample=index, phase='before', gib=used))
            if used is None or not math.isfinite(used) or used < 0 or used * 1024**3 > 32_000_000_000:
                raise ValueError('resource admission failed')
            dst = out/'samples'/str(index)
            before = wait_backend_idle(backend_endpoint, model, dst/'before', min(until, time.monotonic()+10))
            tid = current['task_id']
            prompt_path = plan_path.parent/'agent-input'/tid/'prompt.txt'
            prompt = prompt_path.read_bytes()
            if hashlib.sha256(prompt).hexdigest() != manifest[f'agent-input/{tid}/prompt.txt']:
                raise ValueError('prompt changed after admission')
            # This reservation is durable BEFORE POST and is never refunded.
            status['solves_started'] += 1
            status['model_calls_reserved'] += cap
            current.update(state='started', reserved_upper_bound=cap)
            save()
            request = dict(task_id=tid, nonce=current['nonce'], mode=current['mode'],
                           prompt=prompt.decode('utf-8'), interface='', deadline_s=plan['solve_deadline_s'])
            try:
                response, ledger = solve_http(endpoint, request, dst/'solve', until)
            finally:
                # A broken POST always stops the batch; this GET only determines
                # whether the service still has outstanding generation work.
                after = wait_backend_idle(backend_endpoint, model, dst/'after', min(until, time.monotonic()+10))
                # Retain verified executions even when the response is malformed.
                delta = backend_call_delta(before, after)
                calls = sum(delta.values())
                current.update(model_calls=calls, backend_finished_reasons=delta)
                status['verified_backend_calls'] += calls
            used = runtime.vram_gb()
            status['resource_observations'].append(dict(sample=index, phase='after', gib=used))
            if used is None or not math.isfinite(used) or used < 0 or used * 1024**3 > 32_000_000_000:
                raise ValueError('resource limit after solve')
            events = [json.loads(line) for line in response['trace'].splitlines() if line.strip()]
            timed_out = any(e.get('event') == 'deadline' or e.get('response_status') == 'deadline' or
                            e.get('error') == 'deadline' or str(e.get('reason', '')).startswith('deadline')
                            for e in events)
            current['timed_out'] = timed_out
            if (calls > cap or (ledger['observed_attempts'] is not None and calls != ledger['observed_attempts']) or
                    (not ledger['accounting_complete'] and not timed_out)):
                raise ValueError('model call accounting incomplete or inconsistent')
            if any(e.get('tool') in ('lint', 'elaborate') and e.get('rc') is None and
                   e.get('error') != 'deadline' for e in events):
                raise ValueError('internal EDA unavailable')
            result = judge_candidate(plan_path.parent/'judge-only'/tid, dst/'solve/solution.v', dst/'judge',
                out/'results'/f"{current['mode']}.{tid}.s{current['sample']}.json",
                plan['judge_timeout_s'], until)
            if result.get('task_id') != tid or (not result.get('tool_error') and
                    (result.get('level') not in (0, 1, 2, 3) or
                     result.get('coefficient') != {0: 0., 1: .2, 2: .7, 3: 1.}[result['level']])):
                raise ValueError('invalid official judgement')
            current.update(state='graded', level=result.get('level'), tool_error=result.get('tool_error'))
            save()
            if result.get('tool_error'):
                status['stop_reason'] = 'official_tool_error'
                break
            consecutive_timeouts = consecutive_timeouts + 1 if timed_out else 0
            if consecutive_timeouts >= 2:
                status['stop_reason'] = 'two_consecutive_timeouts'
                break
        if time.monotonic() >= until:
            status['stop_reason'] = 'whole_batch_time'
        if all(row['state'] == 'graded' for row in rows) and status['stop_reason'] is None:
            report = summarize(out/'results', ids, plan['modes'], samples)
            (out/'graded_summary.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
            status['complete'] = True
    except BaseException as exc:
        status['stop_reason'] = type(exc).__name__
        if current is not None and current['state'] == 'started':
            current.update(state='failed', error_type=type(exc).__name__)
        if not isinstance(exc, Exception):
            raise
    finally:
        save()
    return status


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def verify_upstream():
    meta = json.loads((OFFICIAL / 'UPSTREAM.json').read_text(encoding='utf-8'))
    for name, digest in meta['files'].items():
        if hashlib.sha256((ROOT / name).read_bytes()).hexdigest() != digest:
            raise ValueError('official source changed: ' + name)
    return meta['commit']


def summarize(results, expected_tasks, modes, samples):
    """Validate batch completeness before handing official judgements to score.py."""
    if not expected_tasks or len(set(expected_tasks)) != len(expected_tasks):
        raise ValueError('expected tasks must be nonempty and unique')
    score = module('official_score', OFFICIAL / 'selftest/score.py')
    coefficients = {0: 0., 1: .2, 2: .7, 3: 1.}
    by_mode = {}
    expected_files = set()
    for mode in modes:
        by_task = {}
        for tid in expected_tasks:
            records = []
            for sample in range(samples):
                name = f'{mode}.{tid}.s{sample}.json'
                expected_files.add(name)
                item = json.loads((Path(results)/name).read_text(encoding='utf-8'))
                if item.get('task_id') != tid:
                    raise ValueError('task identity mismatch')
                if not item.get('tool_error') and (item.get('level') not in coefficients or
                        item.get('coefficient') != coefficients[item['level']]):
                    raise ValueError('official L0-L3 judgement required; legacy booleans are not scores')
                records.append(item)
            by_task[tid] = records
        by_mode[mode] = score.summarize(by_task)
    if {p.name for p in Path(results).glob('*.json')} != expected_files:
        raise ValueError('unexpected results: use a separate experiment directory')
    return {'scoring_source': 'pinned official selftest/score.py summarize()',
            'modes': by_mode, 'samples_requested': samples,
            'five_sample_protocol': samples == 5,
            'diagnostic_note': 'Upstream pass@5 field is best-of-available; only a five-sample run is pass@5 protocol.',
            'formal_total_score': None,
            'limits': 'Gain threshold, cost baseline, final time budget and engineering score are not established here.'}


def run_references(tasks, ids, samples, out, results, deadline, workers):
    """Parallelize only independent reference checks; never call a model here."""
    def check(path, tid, sample):
        dst = out/'reference'/tid/f's{sample}'
        dst.mkdir(parents=True)
        task_meta = json.loads(path.read_text(encoding='utf-8'))
        shutil.copyfile(path.parent/task_meta['reference'], dst/'solution.v')
        subprocess.run([sys.executable, str(OFFICIAL/'selftest/judge.py'),
                        '--task', str(path.parent), '--solution', str(dst/'solution.v'),
                        '--outdir', str(dst/'judge_logs'), '--timeout', str(deadline),
                        '--json', str(results/f'reference.{tid}.s{sample}.json')], check=True)
    with ThreadPoolExecutor(max_workers=workers) as pool:
        pending = [pool.submit(check, path, tid, sample)
                   for path, tid in zip(tasks, ids) for sample in range(samples)]
        try:
            for future in as_completed(pending):
                future.result()
        except BaseException:
            for future in pending:
                future.cancel()
            raise


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--tasks', type=Path, required=True)
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--samples', type=int, default=5)
    ap.add_argument('--reference', action='store_true', help='only validate evaluator fixtures; no model calls')
    ap.add_argument('--reference-workers', type=int, default=1,
                    help='1..4 independent reference checks; model runs remain sequential')
    ap.add_argument('--deadline', type=float, required=True, help='local trial budget, not an official announced limit')
    args = ap.parse_args()
    if os.name != 'posix':
        ap.error('Official judge targets Linux/WSL; do not report native Windows results as official validation')
    if args.samples not in range(1, 6) or args.deadline <= 0:
        ap.error('samples must be 1..5 and deadline positive')
    if args.reference_workers not in range(1, 5) or (not args.reference and args.reference_workers != 1):
        ap.error('reference-workers must be 1..4 and requires --reference when greater than 1')
    commit = verify_upstream()
    # Fail before any model call if tools are unavailable or not the required version.
    for name in ('xvlog', 'xelab', 'xsim', 'vivado'):
        if not shutil.which(name):
            ap.error(name + ' missing; source Vivado 2026.1 settings64.sh first')
    with tempfile.TemporaryDirectory(dir=os.environ.get('EDA_TMP')) as td:
        version = subprocess.check_output(['vivado', '-version'], cwd=td, timeout=30, text=True)
    if '2026.1' not in version:
        ap.error('Vivado 2026.1 required')
    tasks = sorted(args.tasks.resolve().glob('*/task.json'))
    if not tasks:
        ap.error('no task.json found')
    ids = [json.loads(p.read_text(encoding='utf-8'))['task_id'] for p in tasks]
    if len(set(ids)) != len(ids) or any(not isinstance(t, str) or not t or
            any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in t) for t in ids):
        ap.error('task IDs must be unique ASCII letters/digits/underscore/hyphen')
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=False)
    results = out/'results'
    results.mkdir()
    modes = ['reference'] if args.reference else ['agent', 'baseline']
    meta = dict(upstream_commit=commit, samples=args.samples, task_ids=ids, modes=modes,
                local_deadline_s=args.deadline, reference_workers=args.reference_workers,
                complete=False, started_at=time.time(),
                model=os.environ.get('MODEL_NAME'), vivado_version=version.strip(),
                input_sha256={str(p.relative_to(args.tasks.resolve())): hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in args.tasks.resolve().rglob('*') if p.is_file()},
                submission_sha256={str(p.relative_to(ROOT/'submission')): hashlib.sha256(p.read_bytes()).hexdigest()
                                   for p in (ROOT/'submission').rglob('*') if p.is_file() and '__pycache__' not in p.parts})
    def save():
        (out/'experiment.json').write_text(json.dumps(meta, indent=2)+'\n', encoding='utf-8')
    save()
    runtime = module('submission_runtime', ROOT/'submission/runtime.py')
    # No service calls for --reference. For actual runs require one explicitly named shared model.
    if not args.reference and (not os.environ.get('MODEL_NAME') or os.environ['MODEL_NAME'] not in runtime.models()):
        raise ValueError('MODEL_NAME must match the shared model service')
    if args.reference:
        run_references(tasks, ids, args.samples, out, results, args.deadline, args.reference_workers)
    for path, tid in ([] if args.reference else zip(tasks, ids)):
        for sample in range(args.samples):
            for mode in modes:
                dst = out/mode/tid/f's{sample}'
                runtime.run_job(mode, path.parent, dst, args.deadline)
                subprocess.run([sys.executable, str(OFFICIAL/'selftest/judge.py'),
                                '--task', str(path.parent), '--solution', str(dst/'solution.v'),
                                '--outdir', str(dst/'judge_logs'), '--timeout', str(args.deadline),
                                '--json', str(results/f'{mode}.{tid}.s{sample}.json')], check=True)
    report = summarize(results, ids, modes, args.samples)
    (out/'graded_summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    meta['complete'] = True
    meta['finished_at'] = time.time()
    save()


if __name__ == '__main__':
    main()
