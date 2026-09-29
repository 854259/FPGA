"""Official RTL transport and prompt-only worker; no evaluator imports or inputs."""
from __future__ import annotations

import argparse
import hashlib
from functools import lru_cache
import hmac
import http.client
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
import urllib.request
from urllib.parse import urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = Path(__file__).resolve().parent
LOCK = threading.Lock()


def write(path, text):
    path = Path(path)
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(text, encoding='utf-8', newline='\n')
    temp.replace(path)


def trace(out, tool, **fields):
    with (out / 'trace.jsonl').open('a', encoding='utf-8') as f:
        f.write(json.dumps(dict(ts=time.time(), tool=tool, **fields), ensure_ascii=False) + '\n')
        f.flush()


def endpoint():
    base = os.environ.get('LLM_BASE_URL', 'http://127.0.0.1:8000/v1').rstrip('/')
    parsed = urlparse(base)
    if parsed.scheme not in ('http', 'https') or parsed.username or parsed.password:
        raise ValueError('LLM_BASE_URL must be an HTTP service URL without credentials')
    # Project policy: both development and submission use server-local weights.
    if parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
        raise ValueError('all profiles require a server-local loopback model service')
    return base


def baseline_integrity():
    lock = json.loads((ROOT / 'upstream.json').read_text(encoding='utf-8'))
    return all(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
               for name, digest in lock['files'].items())


def models():
    with urllib.request.urlopen(endpoint() + '/models', timeout=2) as r:
        return [v['id'] for v in json.load(r)['data']]


def vram_gb():
    # sysfs may expose the entire host; count only the container's assigned card.
    cards = list(Path('/dev/dri').glob('card[0-9]*'))
    if len(cards) != 1:
        return None
    try:
        counter = Path('/sys/class/drm') / cards[0].name / 'device/mem_info_vram_used'
        return int(counter.read_text().strip()) / 1024**3
    except (OSError, ValueError):
        return None


def chat_stream(body, path, seconds, cancel_event=None):
    """One request, bounded by a wall deadline; keep received SSE evidence on failure.

    No retry and no extraction from reasoning. Partial content is diagnostic only.
    The socket watchdog also covers a peer that sends bytes indefinitely.
    """
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError('invalid request budget')
    url = urlparse(endpoint() + '/chat/completions')
    connection_type = http.client.HTTPSConnection if url.scheme == 'https' else http.client.HTTPConnection
    conn = connection_type(url.hostname, url.port, timeout=seconds)
    began = time.monotonic()
    deadline = began + seconds
    expired = threading.Event()
    watcher_stop = threading.Event()
    sock = None
    response = None
    result = dict(status='incomplete', content='', reasoning='', usage={}, token_ids=[],
                  prompt_token_ids=None, finish_reason=None, response_id=None,
                  first_event_s=None, elapsed_s=None, bytes_received=0)
    def watch():
        while time.monotonic() < deadline and not (cancel_event and cancel_event.is_set()):
            if watcher_stop.wait(min(.02, max(0, deadline - time.monotonic()))):
                return
        if time.monotonic() >= deadline:
            expired.set()
        active = sock or conn.sock
        if active is not None:
            try:
                active.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
    watcher = threading.Thread(target=watch, daemon=True)
    # Exclusive create makes accidental replays at the same call path fail before sending.
    with Path(path).open('xb') as evidence:
        watcher.start()
        try:
            request = dict(body, stream=True, stream_options={'include_usage': True})
            conn.connect()
            sock = conn.sock
            if expired.is_set() or (cancel_event and cancel_event.is_set()):
                raise TimeoutError('request deadline')
            conn.request('POST', url.path + ('?' + url.query if url.query else ''),
                         body=json.dumps(request).encode(), headers={'Content-Type': 'application/json'})
            response = conn.getresponse()
            result['http_status'] = response.status
            if response.status != 200:
                result['status'] = 'http_error'
                return result
            if 'text/event-stream' not in response.getheader('Content-Type', ''):
                raise ValueError('expected SSE response')
            pending, event_lines = b'', []
            done = False
            while not done:
                if expired.is_set() or time.monotonic() >= deadline or (cancel_event and cancel_event.is_set()):
                    raise TimeoutError('request deadline')
                chunk = response.read1(65536)
                if not chunk:
                    break
                result['bytes_received'] += len(chunk)
                # SSE includes an envelope per token plus prompt IDs. A 2 MiB cap
                # can reject a valid 8192-token response solely due to metadata.
                if result['bytes_received'] > 16 * 1024 * 1024:
                    raise ValueError('response evidence limit exceeded')
                evidence.write(chunk)
                evidence.flush()
                pending += chunk
                while b'\n' in pending and not done:
                    line, pending = pending.split(b'\n', 1)
                    line = line.rstrip(b'\r')
                    if line:
                        if line.startswith(b'data:'):
                            event_lines.append(line[5:].lstrip(b' '))
                        continue
                    if not event_lines:
                        continue
                    data = b'\n'.join(event_lines)
                    event_lines = []
                    if data == b'[DONE]':
                        done = True
                        break
                    event = json.loads(data.decode('utf-8'))
                    if not isinstance(event, dict):
                        raise ValueError('stream event must be an object')
                    if event.get('error'):
                        raise ValueError('server stream error')
                    if result['first_event_s'] is None:
                        result['first_event_s'] = time.monotonic() - began
                    result['response_id'] = event.get('id', result['response_id'])
                    if event.get('usage') is not None:
                        if not isinstance(event['usage'], dict):
                            raise ValueError('invalid usage')
                        result['usage'] = event['usage']
                    if event.get('prompt_token_ids') is not None:
                        ids = event['prompt_token_ids']
                        if not isinstance(ids, list) or any(type(x) is not int for x in ids):
                            raise ValueError('invalid prompt token IDs')
                        if result['prompt_token_ids'] not in (None, ids):
                            raise ValueError('inconsistent prompt token IDs')
                        result['prompt_token_ids'] = ids
                    for choice in event.get('choices', []):
                        if not isinstance(choice, dict):
                            raise ValueError('invalid choice')
                        if choice.get('index', 0) != 0:
                            raise ValueError('only one choice is supported')
                        delta = choice.get('delta') or {}
                        if not isinstance(delta, dict):
                            raise ValueError('invalid delta')
                        result['content'] += delta.get('content') or ''
                        result['reasoning'] += delta.get('reasoning') or delta.get('reasoning_content') or ''
                        ids = choice.get('token_ids')
                        if ids is not None:
                            if not isinstance(ids, list) or any(type(x) is not int for x in ids):
                                raise ValueError('invalid token IDs')
                            result['token_ids'].extend(ids)
                        if choice.get('finish_reason') is not None:
                            result['finish_reason'] = choice['finish_reason']
            if cancel_event and cancel_event.is_set():
                result['status'] = 'cancelled'
            elif expired.is_set() or time.monotonic() >= deadline:
                result['status'] = 'deadline'
            elif done and result['finish_reason'] is not None:
                result['status'] = 'complete'
        except (OSError, ValueError, TypeError, KeyError, http.client.HTTPException) as exc:
            result['status'] = ('cancelled' if cancel_event and cancel_event.is_set() else
                                'deadline' if expired.is_set() or time.monotonic() >= deadline else 'stream_error')
            result['error_type'] = type(exc).__name__
        finally:
            watcher_stop.set()
            if response is not None:
                response.close()
            conn.close()
            watcher.join(timeout=1)
            result['elapsed_s'] = time.monotonic() - began
    return result


def vivado_tool(name):
    base = os.environ.get('VIVADO_BIN')
    if not base and os.environ.get('XILINX_VIVADO'):
        base = str(Path(os.environ['XILINX_VIVADO']) / 'bin')
    suffix = '.bat' if os.name == 'nt' else ''
    path = str(Path(base) / (name + suffix)) if base else shutil.which(name + suffix)
    return path if path and Path(path).is_file() else None


@lru_cache(maxsize=4)
def vivado_version(tool):
    if not tool:
        return None
    try:
        with tempfile.TemporaryDirectory(prefix='rtl-version-') as td:
            result = subprocess.run([tool, '-version'], cwd=td, capture_output=True,
                                    text=True, errors='replace', timeout=5)
        match = re.search(r'Vivado\s+v?(\d{4}\.\d+)', result.stdout, re.IGNORECASE)
        return match[1] if result.returncode == 0 and match else None
    except (OSError, subprocess.SubprocessError):
        return None


def health():
    model = os.environ.get('MODEL_NAME', '')
    ready = False
    try:
        ready = bool(model and model in models() and baseline_integrity() and vivado_tool('xvlog')
                     and vivado_version(vivado_tool('vivado')) == '2026.1')
    except (OSError, ValueError, KeyError, TypeError):
        pass
    used = vram_gb()
    if os.environ.get('RTL_PROFILE', 'submission') != 'development':
        # The counter helper reports GiB. Use a conservative 32 GB byte limit
        # instead of silently allowing 32 GiB (about 34.36 decimal GB).
        ready = ready and used is not None and used * 1024**3 <= 32_000_000_000
    return dict(ready=bool(ready), track='rtl', model=model, vram_gb=used)


def stop_tree(proc):
    if os.name == 'nt':
        if proc.poll() is None:
            subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    else:
        # The worker owns a session; kill descendants even if their parent exited.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def run_job(mode, task, out, seconds):
    """Copy only permitted input into fresh local scratch, supervise one process tree."""
    if mode not in ('agent', 'baseline') or not math.isfinite(seconds) or seconds <= 0:
        raise ValueError('invalid mode or deadline')
    endpoint()
    if not baseline_integrity():
        raise ValueError('official baseline integrity check failed')
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    # Atomic ownership, including when two CLI invocations target the same directory.
    with (out / '.run.lock').open('x'):
        pass
    if (out / 'solution.v').exists() or (out / 'trace.jsonl').exists():
        raise ValueError('use a new output directory')
    write(out / 'solution.v', '')
    write(out / 'trace.jsonl', '')
    started = time.monotonic()
    scratch = os.environ.get('EDA_TMP') or None
    if scratch:
        Path(scratch).mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='rtl-', dir=scratch) as td:
        work = Path(td)
        inp = work / 'task'
        inp.mkdir()
        # Deliberately never enumerate task_dir or read task.json, testbench or reference.
        write(inp / 'prompt.txt', (Path(task) / 'prompt.txt').read_text(encoding='utf-8'))
        iface = Path(task) / 'interface.txt'
        if iface.is_file():
            write(inp / 'interface.txt', iface.read_text(encoding='utf-8'))
        env = dict(os.environ, PYTHONUTF8='1', TRACK='rtl',
                   RTL_DEADLINE_MONOTONIC=str(started + max(0, seconds - min(.2, seconds * .1))))
        if mode == 'baseline':
            command = [sys.executable, str(ROOT / 'baseline.py'), str(inp), str(out), 'rtl']
        else:
            command = [sys.executable, str(ROOT / 'runtime.py'), 'worker', str(inp), str(out)]
        flags = {'start_new_session': True} if os.name != 'nt' else {}
        with (out / 'worker.log').open('w', encoding='utf-8') as log:
            proc = subprocess.Popen(command, cwd=work, env=env, stdout=log, stderr=log, **flags)
            previous = {}
            def cancelled(signum, frame):
                stop_tree(proc)
                raise SystemExit(128 + signum)
            if threading.current_thread() is threading.main_thread():
                for sig in (signal.SIGTERM, signal.SIGINT):
                    previous[sig] = signal.signal(sig, cancelled)
            try:
                proc.wait(timeout=max(.01, seconds - (time.monotonic() - started)))
            except subprocess.TimeoutExpired:
                stop_tree(proc)
                # Preserve existing official events; explicitly identify supervisor cancellation.
                trace(out, 'supervisor', event='deadline', mode=mode)
            finally:
                stop_tree(proc)
                for sig, handler in previous.items():
                    signal.signal(sig, handler)
    return (out / 'solution.v').read_text(encoding='utf-8'), (out / 'trace.jsonl').read_text(encoding='utf-8')


def worker(task, out):
    # Import ONLY the untouched extraction helper; never import the development evaluator.
    import baseline
    out = Path(out)
    prompt = (Path(task) / 'prompt.txt').read_text(encoding='utf-8')
    iface = Path(task) / 'interface.txt'
    if iface.is_file() and iface.read_text(encoding='utf-8').strip():
        prompt += '\n\nInterface:\n' + iface.read_text(encoding='utf-8')
    skill = (ROOT / 'skill/RTL_SKILL.md').read_text(encoding='utf-8')
    repair_skill = (ROOT / 'skill/RTL_REPAIR_SKILL.md').read_text(encoding='utf-8')
    repairs = int(os.environ.get('RTL_REPAIRS', '1'))
    if not 0 <= repairs <= 1:
        raise ValueError('RTL_REPAIRS must be 0..1')
    deadline = float(os.environ.get('RTL_DEADLINE_MONOTONIC', str(time.monotonic() + 300)))
    model = os.environ.get('MODEL_NAME') or models()[0]
    code, feedback, best_code = '', '', ''
    write(out / 'solution.v', '')
    trace(out, 'agent_meta', boundary='prompt_only_candidate_compile',
          skill_sha256=hashlib.sha256(skill.encode()).hexdigest(),
          repair_skill_sha256=hashlib.sha256(repair_skill.encode()).hexdigest(), repairs=repairs)
    for attempt in range(repairs + 1):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            trace(out, 'agent_stop', reason='deadline', round=attempt)
            return
        user = prompt if attempt == 0 else prompt + '\nPrevious candidate:\n' + code + '\nCandidate diagnostics:\n' + feedback
        body = dict(model=model, messages=[dict(role='system', content=skill + ('\n' + repair_skill if attempt else '')),
                                         dict(role='user', content=user)],
                    temperature=float(os.environ.get('RTL_TEMPERATURE', '0')),
                    top_p=1.0, max_tokens=int(os.environ.get('RTL_MAX_TOKENS', '8192')))
        trace(out, 'llm_start', round=attempt)
        try:
            response = chat_stream(body, out / ('response-' + str(attempt) + '.sse'), remaining)
            usage = response['usage']
            reply = response['content']
            trace(out, 'llm', round=attempt, tokens_in=usage.get('prompt_tokens'),
                  tokens_out=usage.get('completion_tokens'), finish=response['finish_reason'],
                  response_status=response['status'], content_chars=len(reply),
                  reasoning_chars=len(response['reasoning']), elapsed_s=response['elapsed_s'])
            if response['status'] != 'complete':
                trace(out, 'agent_stop', reason='incomplete_response', preserved=bool(best_code))
                return  # A disconnected request must never become an implicit retry.
            code = baseline.extract(reply, 'rtl')
        except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
            trace(out, 'llm', round=attempt, error=type(exc).__name__)
            return
        # Includes/file IO are unnecessary for a self-contained TopModule and could cross the input boundary.
        if re.search(r'`include|\$(?:readmem\w*|fopen|system)\b', code):
            feedback = 'Return a self-contained module without file access or include directives.'
            trace(out, 'check_source', rc=1, excerpt=feedback)
            continue
        if not re.search(r'\bmodule\s+TopModule\b', code) or 'endmodule' not in code:
            feedback = 'Return a complete TopModule ending in endmodule.'
            if response['finish_reason'] == 'length':
                feedback += ' Output reached the token limit; shorten the implementation.'
            trace(out, 'check_source', rc=1, excerpt=feedback)
            continue
        if not best_code:
            best_code = code
            write(out / 'solution.v', best_code)
        tool = vivado_tool('xvlog')
        if not tool:
            trace(out, 'lint', rc=None, error='xvlog unavailable; candidate unverified')
            return
        wd = Path.cwd() / ('compile-' + str(attempt))
        wd.mkdir()
        write(wd / 'candidate.sv', code)
        trace(out, 'lint_start', round=attempt)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            trace(out, 'agent_stop', reason='deadline_before_lint', round=attempt)
            return
        try:
            result = subprocess.run([tool, '--sv', str(wd / 'candidate.sv')], cwd=wd,
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, errors='replace', timeout=remaining)
        except subprocess.TimeoutExpired:
            trace(out, 'lint', rc=None, error='deadline', round=attempt)
            return
        lines = [s for s in result.stdout.splitlines() if re.search('ERROR|WARNING|FATAL', s)]
        feedback = '\n'.join(lines)[:2048] or result.stdout[-2048:]
        trace(out, 'lint', rc=result.returncode, excerpt=feedback, round=attempt)
        if result.returncode == 0:
            best_code = code
            write(out / 'solution.v', best_code)
            return  # Compilation is NOT an official L1/L2/L3 judgement.


def solve(data, received_at=None):
    started = time.monotonic() if received_at is None else received_at
    if not isinstance(data, dict):
        raise ValueError('JSON object required')
    for key in ('task_id', 'prompt'):
        if not isinstance(data.get(key), str):
            raise ValueError(key + ' must be a string')
    for key in ('nonce', 'interface'):
        if key in data and not isinstance(data[key], str):
            raise ValueError(key + ' must be a string')
    mode = data.get('mode', 'agent')
    deadline = data.get('deadline_s', 360)
    if mode not in ('agent', 'baseline') or type(deadline) not in (int, float) or not math.isfinite(deadline) or deadline <= 0:
        raise ValueError('invalid mode or deadline')
    if not LOCK.acquire(timeout=max(0, deadline - (time.monotonic() - started) - .1)):
        return dict(task_id=data['task_id'], solution='', trace='', elapsed_s=time.monotonic()-started)
    try:
        if os.environ.get('EDA_TMP'):
            Path(os.environ['EDA_TMP']).mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='rtl-request-', dir=os.environ.get('EDA_TMP')) as td:
            task = Path(td) / 'in'
            task.mkdir()
            write(task / 'prompt.txt', data['prompt'])
            if data.get('interface'):
                write(task / 'interface.txt', data['interface'])
            budget = deadline - (time.monotonic() - started) - min(1, deadline * .1)
            solution, events = ('', '') if budget <= 0 else run_job(mode, task, Path(td)/'out', budget)
        return dict(task_id=data['task_id'], solution=solution, trace=events, elapsed_s=round(time.monotonic()-started, 3))
    finally:
        LOCK.release()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass  # Never log credentials or full request bodies.

    def send_json(self, status, value):
        raw = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def authorized(self):
        token = os.environ.get('FPGACHINA_TOKEN', '')
        if not token or not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token):
            self.send_json(401, {'error': 'unauthorized'})
            return False
        return True

    def do_GET(self):
        if not self.authorized():
            return
        self.send_json(200, health()) if self.path == '/v1/health' else self.send_json(404, {'error': 'not found'})

    def do_POST(self):
        received_at = time.monotonic()
        if not self.authorized():
            return
        if self.path != '/v1/solve':
            return self.send_json(404, {'error': 'not found'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 1024 * 1024:
                raise ValueError('invalid body size')
            self.connection.settimeout(10)
            data = json.loads(self.rfile.read(size))
            self.send_json(200, solve(data, received_at=received_at))
        except (ValueError, UnicodeError) as exc:
            self.send_json(400, {'error': str(exc)})
        except (OSError, KeyError, subprocess.SubprocessError):
            self.send_json(503, {'error': 'runtime unavailable'})


def main():
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=('run', 'baseline', 'worker', 'serve'))
    p.add_argument('task', nargs='?')
    p.add_argument('out', nargs='?')
    p.add_argument('--port', type=int, default=7860)
    args = p.parse_args()
    if args.action == 'serve':
        if not os.environ.get('FPGACHINA_TOKEN'):
            p.error('FPGACHINA_TOKEN required')
        endpoint()
        if os.environ.get('EDA_TMP'):
            Path(os.environ['EDA_TMP']).mkdir(parents=True, exist_ok=True)
        ThreadingHTTPServer(('127.0.0.1', args.port), Handler).serve_forever()
    elif args.task is None or args.out is None:
        p.error('task_dir and out_dir required')
    elif args.action == 'worker':
        worker(args.task, args.out)
    else:
        run_job('agent' if args.action == 'run' else 'baseline', args.task, args.out,
                float(os.environ.get('AGENT_DEADLINE_S', '300')))


if __name__ == '__main__':
    main()
