"""Official RTL transport and prompt-only worker; no evaluator imports or inputs."""
from __future__ import annotations

import argparse
import hashlib
from functools import lru_cache
import hmac
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
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
    Path(path).write_text(text, encoding='utf-8', newline='\n')


def trace(out, tool, **fields):
    with (out / 'trace.jsonl').open('a', encoding='utf-8') as f:
        f.write(json.dumps(dict(ts=time.time(), tool=tool, **fields), ensure_ascii=False) + '\n')
        f.flush()


def endpoint():
    base = os.environ.get('LLM_BASE_URL', 'http://127.0.0.1:8000/v1').rstrip('/')
    parsed = urlparse(base)
    if parsed.scheme not in ('http', 'https') or parsed.username or parsed.password:
        raise ValueError('LLM_BASE_URL must be an HTTP service URL without credentials')
    if os.environ.get('RTL_PROFILE', 'submission') != 'development':
        if parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
            raise ValueError('submission profile requires a loopback model service')
    return base


def baseline_integrity():
    lock = json.loads((ROOT / 'upstream.json').read_text(encoding='utf-8'))
    return all(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
               for name, digest in lock['files'].items())


def models():
    with urllib.request.urlopen(endpoint() + '/models', timeout=2) as r:
        return [v['id'] for v in json.load(r)['data']]


def vram_gb():
    # Linux amdgpu counters are bytes, unlike rocm-smi's percentage output.
    counters = list(Path('/sys/class/drm').glob('card[0-9]*/device/mem_info_vram_used'))
    if not counters:
        return None
    try:
        return round(sum(int(p.read_text().strip()) for p in counters) / 1024**3, 3)
    except (OSError, ValueError):
        return None


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
        match = re.search(r'Vivado\s+v?(\d{4}\.\d+)', result.stdout)
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
        ready = ready and used is not None and used <= 32
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
        env = dict(os.environ, PYTHONUTF8='1', TRACK='rtl')
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
    if not 0 <= repairs <= 2:
        raise ValueError('RTL_REPAIRS must be 0..2')
    model = os.environ.get('MODEL_NAME') or models()[0]
    code, feedback = '', ''
    trace(out, 'agent_meta', boundary='prompt_only_candidate_compile',
          skill_sha256=hashlib.sha256(skill.encode()).hexdigest(),
          repair_skill_sha256=hashlib.sha256(repair_skill.encode()).hexdigest(), repairs=repairs)
    for attempt in range(repairs + 1):
        user = prompt if attempt == 0 else prompt + '\nPrevious candidate:\n' + code + '\nCandidate diagnostics:\n' + feedback
        body = dict(model=model, messages=[dict(role='system', content=skill + ('\n' + repair_skill if attempt else '')),
                                         dict(role='user', content=user)],
                    temperature=float(os.environ.get('RTL_TEMPERATURE', '0')),
                    top_p=1.0, max_tokens=int(os.environ.get('RTL_MAX_TOKENS', '8192')))
        trace(out, 'llm_start', round=attempt)
        try:
            req = urllib.request.Request(endpoint() + '/chat/completions',
                                         data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=300) as r:
                payload = json.load(r)
            choice = payload['choices'][0]
            usage = payload.get('usage') or {}
            reply = choice['message'].get('content') or ''
            trace(out, 'llm', round=attempt, tokens_in=usage.get('prompt_tokens'),
                  tokens_out=usage.get('completion_tokens'), finish=choice.get('finish_reason'))
            code = baseline.extract(reply, 'rtl')
        except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
            trace(out, 'llm', round=attempt, error=type(exc).__name__)
            return
        write(out / 'solution.v', code)
        # Includes/file IO are unnecessary for a self-contained TopModule and could cross the input boundary.
        if re.search(r'`include|\$(?:readmem\w*|fopen|system)\b', code):
            feedback = 'Return a self-contained module without file access or include directives.'
            trace(out, 'check_source', rc=1, excerpt=feedback)
            continue
        if not re.search(r'\bmodule\s+TopModule\b', code) or 'endmodule' not in code:
            feedback = 'Return a complete TopModule ending in endmodule.'
            if choice.get('finish_reason') == 'length':
                feedback += ' Output reached the token limit; shorten the implementation.'
            trace(out, 'check_source', rc=1, excerpt=feedback)
            continue
        tool = vivado_tool('xvlog')
        if not tool:
            trace(out, 'lint', rc=None, error='xvlog unavailable; candidate unverified')
            return
        wd = Path.cwd() / ('compile-' + str(attempt))
        wd.mkdir()
        write(wd / 'candidate.sv', code)
        trace(out, 'lint_start', round=attempt)
        result = subprocess.run([tool, '--sv', str(wd / 'candidate.sv')], cwd=wd,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                text=True, errors='replace')
        lines = [s for s in result.stdout.splitlines() if re.search('ERROR|WARNING|FATAL', s)]
        feedback = '\n'.join(lines)[:2048] or result.stdout[-2048:]
        trace(out, 'lint', rc=result.returncode, excerpt=feedback, round=attempt)
        if result.returncode == 0:
            return  # Compilation is NOT an official L1/L2/L3 judgement.


def solve(data):
    started = time.monotonic()
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
    if not LOCK.acquire(timeout=max(0, deadline - .1)):
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
            self.send_json(200, solve(data))
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
