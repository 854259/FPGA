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
from http.server import BaseHTTPRequestHandler, HTTPServer

ROOT = Path(__file__).resolve().parent
# In the packaged layout the agent lives at <pkg>/agent/ while the official baseline
# and our integrity manifest sit at the package root; the development tree keeps
# everything beside this file. Detect the layout instead of assuming one.
PKG = ROOT.parent if (ROOT.parent / 'baseline.py').is_file() else ROOT
# `worker` imports the untouched official baseline to reuse its extract() helper.
# In the packaged layout that module sits at the package root rather than beside
# this file, so make the package root importable in both layouts.
if str(PKG) not in sys.path:
    sys.path.insert(0, str(PKG))
BLOCKED = None  # Infrastructure failures require inspection before another request.


def skill_texts():
    """Locate the skill pack in either the development or the packaged layout.

    The submission package keeps the agent at <pkg>/agent/ and skills at
    <pkg>/skill/<name>/SKILL.md, while the development tree keeps them flat
    beside this file. Both layouts are resolved so the packaged tree can be
    tested without editing paths.
    """
    pairs = (
        (ROOT / 'skill/rtl-generation/SKILL.md', ROOT / 'skill/rtl-feedback-repair/SKILL.md'),
        (ROOT.parent / 'skill/rtl-generation/SKILL.md', ROOT.parent / 'skill/rtl-feedback-repair/SKILL.md'),
        (ROOT / 'skill/RTL_SKILL.md', ROOT / 'skill/RTL_REPAIR_SKILL.md'),
        (ROOT.parent / 'skill/RTL_SKILL.md', ROOT.parent / 'skill/RTL_REPAIR_SKILL.md'),
    )
    for generation, repair in pairs:
        if generation.is_file() and repair.is_file():
            return generation.read_text(encoding='utf-8'), repair.read_text(encoding='utf-8')
    raise FileNotFoundError('skill pack not found relative to ' + str(ROOT))


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
    lock = json.loads((PKG / 'upstream.json').read_text(encoding='utf-8'))
    return all(hashlib.sha256((PKG / name).read_bytes()).hexdigest() == digest
               for name, digest in lock['files'].items())


def models():
    with urllib.request.urlopen(endpoint() + '/models', timeout=2) as r:
        return [v['id'] for v in json.load(r)['data']]


def _drm_amd_cards():
    """Render node -> bytes of VRAM in use, for AMD cards only."""
    cards = {}
    for node in sorted(Path('/sys/class/drm').glob('renderD*')):
        device = node / 'device'
        try:
            if (device / 'vendor').read_text().strip() != '0x1002':
                continue
            cards[node.name] = int((device / 'mem_info_vram_used').read_text().strip())
        except (OSError, ValueError):
            continue
    return cards


def _model_server_render_node():
    """The render node held open by whatever process serves the model endpoint."""
    try:
        port = urlparse(endpoint()).port or 80
    except (ValueError, TypeError):
        return None
    inode = None
    try:
        for line in Path('/proc/net/tcp').read_text().splitlines()[1:]:
            fields = line.split()
            if len(fields) > 9 and fields[3] == '0A' and int(fields[1].split(':')[1], 16) == port:
                inode = fields[9]
                break
    except (OSError, IndexError, ValueError):
        return None
    if not inode:
        return None
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            fds = list((proc / 'fd').iterdir())
        except OSError:
            continue
        for entry in fds:
            try:
                if os.readlink(entry) != 'socket:[' + inode + ']':
                    continue
            except OSError:
                continue
            for other in fds:
                try:
                    target = os.readlink(other)
                except OSError:
                    continue
                if 'renderD' in target:
                    return Path(target).name
    return None


def vram_gb():
    """VRAM the model server holds, in GB, or None when that cannot be established.

    This host carries eight AMD GPUs and other tenants occupy several of them, so
    summing every card reports about 67 GB against our own 19 GB and would fail a
    32 GB readiness check for a reason that has nothing to do with us. The counter is
    therefore attributed to the card the model server actually holds open, by way of
    the render node its listening socket's process owns.

    When that attribution fails there is deliberately no fallback to "the busiest
    card": on a shared host the busiest card is very likely somebody else's, and
    reporting their number as ours would be worse than reporting nothing. Unknown is
    reported as None, and the readiness check treats an unmeasurable value as an
    instrumentation gap rather than as a breach of the limit.
    """
    cards = _drm_amd_cards()
    if not cards:
        return None
    node = _model_server_render_node()
    if node and node in cards:
        return round(cards[node] / 1024 ** 3, 3)
    return None


def vivado_tool(name):
    base = os.environ.get('VIVADO_BIN')
    if not base and os.environ.get('XILINX_VIVADO'):
        base = str(Path(os.environ['XILINX_VIVADO']) / 'bin')
    suffix = '.bat' if os.name == 'nt' else ''
    path = str(Path(base) / (name + suffix)) if base else shutil.which(name + suffix)
    return path if path and Path(path).is_file() else None


# Detection of instantiations whose module is never defined in the same source.
# The discriminator has to be a named port map: matching `Name inst (` alone also
# matches loop headers such as `for (i = 0; ...)`, which produced 69 false positives
# out of 156 on VerilogEval before this was tightened.
_SUBMODULE_KEYWORDS = frozenset("""
module endmodule input output inout wire reg logic assign always always_comb always_ff
always_latch initial begin end if else case endcase casez casex for while repeat forever
function endfunction task endtask generate endgenerate genvar parameter localparam defparam
posedge negedge integer real time signed unsigned default return break continue typedef
struct enum packed unpacked static automatic specify endspecify primitive table endtable
supply0 supply1 tri triand trior wand wor byte shortint int longint bit string void assert
assume cover property endproperty sequence endsequence interface endinterface package
endpackage import export class endclass new this super extends virtual pure
""".split())
_SUBMODULE_PRIMITIVES = frozenset("""
and nand or nor xor xnor not buf bufif0 bufif1 notif0 notif1 nmos pmos cmos rnmos rpmos
rcmos tran tranif0 tranif1 rtran rtranif0 rtranif1 pullup pulldown
""".split())
_RE_MODULE_DECL = re.compile(r'^\s*module\s+([A-Za-z_]\w*)', re.M)
_RE_INSTANTIATION = re.compile(
    r'^[ \t]*([A-Za-z_]\w*)\s*(?:#\s*\([^;]*?\)\s*)?([A-Za-z_]\w*)\s*'
    r'(?:\[[^\]]*\]\s*)?\(([^;]*?)\)\s*;', re.M | re.S)
_RE_NAMED_PORT = re.compile(r'\.\s*[A-Za-z_]\w*\s*\(')


def undefined_submodules(code):
    """Module names instantiated with a named port map but never defined here.

    Returns names in first-seen order. Empty list means nothing was flagged.
    """
    text = re.sub(r'/\*.*?\*/', ' ', code, flags=re.S)
    text = re.sub(r'//[^\n]*', ' ', text)
    text = re.sub(r'"(?:[^"\\]|\\.)*"', '""', text)
    defined = set(_RE_MODULE_DECL.findall(text))
    missing = []
    for module, _instance, ports in _RE_INSTANTIATION.findall(text):
        if module in defined or module in _SUBMODULE_KEYWORDS or module in _SUBMODULE_PRIMITIVES:
            continue
        if not _RE_NAMED_PORT.search(ports):
            continue
        if module not in missing:
            missing.append(module)
    return missing


_RE_NONREG = re.compile(
    r'VRFC 10-1280\]\s*procedural assignment to a non-register\s+(\w+)')
_RE_REDECL = re.compile(
    r"VRFC 10-9336\]\s*redeclaration of ANSI port\s+'?(\w+)'?")


def repair_ansi_declarations(code, feedback):
    """Fix a mechanical declaration fault in place, or return None.

    Two shapes, both reported by xvlog as a compile error:

      * an ANSI output assigned in a procedural block is an implicit wire, so the
        port has to become `output reg`;
      * the same signal then also declared `reg` inside the body is a redeclaration.

    Only signals named by the compiler are touched, and the caller recompiles before
    accepting anything, so a wrong guess costs one compile and not a wrong answer.
    Validated on Prob058_alwaysblock2, which this moves from L0 to L3 with no model
    call at all.
    """
    names = []
    for pattern in (_RE_NONREG, _RE_REDECL):
        for match in pattern.finditer(feedback or ''):
            if match.group(1) not in names:
                names.append(match.group(1))
    if not names:
        return None
    head = re.search(r'\bmodule\s+\w+\s*(?:#\s*\(.*?\)\s*)?\((.*?)\)\s*;', code, re.S)
    if not head:
        return None
    ports, tail = head.group(1), code[head.end(1):]
    changed = False
    for name in names:
        pattern = re.compile(
            r'(\boutput\b)(\s+(?:wire\s+|logic\s+|reg\s+)?)((?:\[[^\]]*\]\s*)?)'
            r'(\b' + re.escape(name) + r'\b)')

        def upgrade(match, _name=name):
            if 'reg' in match.group(2) or 'logic' in match.group(2):
                return match.group(0)
            return match.group(1) + ' reg ' + match.group(3) + match.group(4)

        # Compare text rather than counting substitutions: re.subn counts a match even
        # when the replacement is identical, which made an already-`reg` port look patched.
        upgraded = pattern.sub(upgrade, ports)
        if upgraded != ports:
            ports = upgraded
            changed = True
        tail, dropped = _drop_declared_name(tail, name)
        changed = changed or dropped
    if not changed:
        return None
    return code[:head.start(1)] + ports + tail


def _drop_declared_name(text, name):
    """Remove one identifier from a `reg` declaration list, leaving its siblings alone.

    Deleting the whole line was wrong when several names share it: fixing `q` in
    `reg q, state;` also discarded the declaration of `state`. Only the named
    identifier goes, and the line disappears only when nothing is left on it.

    Returns (new_text, changed).
    """
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not re.match(r'reg\b', stripped) or not stripped.endswith(';'):
            continue
        body = stripped[len('reg'):-1]
        if not re.search(r'\b' + re.escape(name) + r'\b', body):
            continue
        parts = [part.strip() for part in body.split(',')]
        # A width on the first name applies to the rest of the list, so keep it.
        width = ''
        first = re.match(r'(\[[^\]]*\])\s*(.*)$', parts[0])
        if first:
            width, parts[0] = first.group(1), first.group(2)
        pattern = re.compile(r'^' + re.escape(name) + r'(?:\[[^\]]*\])?$')
        kept = [part for part in parts if not pattern.match(part)]
        if len(kept) == len(parts):
            continue
        if not kept:
            del lines[index]                       # nothing left: drop the whole line
        else:
            indent = line[:len(line) - len(line.lstrip())]
            prefix = (width + ' ') if width else ''
            lines[index] = '%sreg %s%s;\n' % (indent, prefix, ', '.join(kept))
        return ''.join(lines), True
    return text, False


@lru_cache(maxsize=4)
def vivado_version(tool):
    if not tool:
        return None
    try:
        with tempfile.TemporaryDirectory(prefix='rtl-version-') as td:
            result = subprocess.run([tool, '-version'], cwd=td, capture_output=True,
                                    text=True, errors='replace', timeout=30)
        # The banner lowercases it: `vivado v2026.1 (64-bit)`. Matching `Vivado`
        # case-sensitively never matched, which left the tool reported as absent and
        # held /v1/health at ready=false even though everything was working.
        match = re.search(r'vivado\s+v?(\d{4}\.\d+)', result.stdout, re.I)
        return match[1] if result.returncode == 0 and match else None
    except (OSError, subprocess.SubprocessError):
        return None


def health():
    model = os.environ.get('MODEL_NAME', '')
    ready = False
    try:
        ready = bool(BLOCKED is None and model and model in models() and baseline_integrity() and vivado_tool('xvlog')
                     and vivado_version(vivado_tool('vivado')) == '2026.1')
    except (OSError, ValueError, KeyError, TypeError):
        pass
    used = vram_gb()
    if os.environ.get('RTL_PROFILE', 'submission') != 'development' and used is not None:
        # Only a measured value can breach the limit. When attribution fails the
        # field is reported as null and readiness rests on the conditions above,
        # because failing to instrument our own VRAM is not the same as the agent
        # being unavailable, and answering ready=false for that would be a
        # self-inflicted refusal.
        ready = ready and used <= 32
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


def run_job(mode, task, out, seconds, *, parent_started=None):
    """CLI and serial HTTP share one main-thread budget, generation and cleanup."""
    import candidate_worker
    import shared_budget
    import deadline_supervisor
    import ctypes
    global BLOCKED
    if sys.platform != 'linux' or threading.current_thread() is not threading.main_thread():
        raise RuntimeError('The selected runtime must execute in the Linux main thread')
    if BLOCKED is not None:
        raise RuntimeError('Runtime retained for inspection after an infrastructure failure')
    if mode not in ('agent', 'baseline') or not math.isfinite(seconds) or seconds <= 0:
        raise ValueError('invalid mode or deadline')
    if deadline_supervisor.descendants(os.getpid()):
        BLOCKED = 'preexisting_children'
        raise RuntimeError('Request ownership unclear: process already has children')
    budget = shared_budget.SolveBudget(seconds, parent_started=parent_started)
    endpoint()
    if not baseline_integrity():
        raise RuntimeError('official baseline integrity check failed')
    out = Path(out).resolve()
    out.mkdir(parents=True, exist_ok=True)
    with (out / '.run.lock').open('x'):
        pass
    if (out / 'solution.v').exists() or (out / 'trace.jsonl').exists():
        raise ValueError('use a new output directory')
    write(out / 'solution.v', '')
    write(out / 'trace.jsonl', '')
    candidate_worker.save(out / 'SOLVE_CLOCK.json', dict(
        started_monotonic=budget.started, budget_s=budget.seconds,
        work_deadline_monotonic=budget.end, cleanup_deadline_monotonic=budget.end + 10))
    scratch = os.environ.get('EDA_TMP') or None
    if scratch:
        Path(scratch).mkdir(parents=True, exist_ok=True)
    started_baseline = False
    work = None
    cancelled_at = None
    def cancelled(signum, frame):
        nonlocal cancelled_at
        if cancelled_at is None:
            cancelled_at = time.monotonic()
        raise InterruptedError('Request cancelled by signal ' + str(signum))
    previous = {sig: signal.signal(sig, cancelled) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        work = Path(tempfile.mkdtemp(prefix="rtl-", dir=scratch))
        inp = work / 'task'
        inp.mkdir()
        write(inp / 'prompt.txt', (Path(task) / 'prompt.txt').read_text(encoding='utf-8'))
        iface = Path(task) / 'interface.txt'
        if iface.is_file():
            write(inp / 'interface.txt', iface.read_text(encoding='utf-8'))
        try:
            budget.remaining()
            if mode == 'agent':
                candidate_worker.run(inp, out, work / 'candidate', budget)
            else:
                if ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) != 0:
                    raise RuntimeError('Cannot enable baseline child subreaping')
                command = [sys.executable, '-B', str(PKG / 'baseline.py'), str(inp), str(out), 'rtl']
                started_baseline = True
                supervision = deadline_supervisor.owned_command(
                    command, work, out / 'worker.log', budget.remaining(),
                    deadline=budget.end, cleanup_deadline=budget.end + 10)
                candidate_worker.save(out / 'BASELINE_SUPERVISION.json', supervision)
                if supervision['launch_error'] or supervision['remaining_live_group']:
                    raise RuntimeError('Official baseline supervision failed')
                if supervision['timeout']:
                    raise shared_budget.BudgetExpired('Official baseline deadline reached')
                if supervision['returncode'] != 0:
                    raise RuntimeError('Official baseline exited unsuccessfully')
        except shared_budget.BudgetExpired:
            write(out / 'solution.v', '')
            trace(out, 'supervisor', event='deadline', mode=mode, actual_calls=None)
        except BaseException as error:
            cause = error
            while cause is not None:
                observed_cancel = getattr(cause, 'cancelled_at_monotonic', None)
                if observed_cancel is not None:
                    cancelled_at = min(cancelled_at or observed_cancel, observed_cancel)
                cause = cause.__cause__
            write(out / 'solution.v', '')
            trace(out, 'supervisor', event='failed', mode=mode, error=type(error).__name__)
            if isinstance(error, Exception) and not isinstance(error, InterruptedError):
                BLOCKED = type(error).__name__
                raise RuntimeError('Request infrastructure failed; retain for inspection') from error
            raise
        finally:
            # Native owned_command has already reaped its exact group. A
            # closed upstream HTTP connection still needs server-side idle.
            for sig in previous:
                signal.signal(sig, signal.SIG_IGN)
            cleanup_started = time.monotonic()
            cleanup_end = min(budget.end + 10, cleanup_started + 10,
                              (cancelled_at + 10) if cancelled_at is not None else float('inf'))
            try:
                cleanup = deadline_supervisor.cleanup_request_children(cleanup_end)
                candidate_worker.save(out / 'OWNED_CLEANUP.json', cleanup)
                trace(out, 'owned_cleanup', verified=cleanup['verified'],
                      observed_children=len(cleanup['recorded']))
            except BaseException as error:
                BLOCKED = type(error).__name__
                candidate_worker.save(out / 'OWNED_CLEANUP.json',
                    dict(verified=False, deadline_monotonic=cleanup_end,
                         error=type(error).__name__, recorded=getattr(error, 'recorded', None),
                         remaining=getattr(error, 'remaining', None)))
                trace(out, 'owned_cleanup', verified=False, error=type(error).__name__)
                raise
            req_path = out / 'requests.json'
            attempted = started_baseline or (req_path.is_file() and any(
                row.get('dispatch_started') for row in json.loads(req_path.read_bytes())))
            if attempted:
                recovery = shared_budget.SolveBudget(cleanup_end - budget.started,
                                                      parent_started=budget.started)
                observed = dict(complete=False, work_deadline_monotonic=budget.end,
                                cleanup_deadline_monotonic=recovery.end,
                                cancelled_at_monotonic=cancelled_at)
                try:
                    if budget.expired():
                        time.sleep(min(1.25, recovery.remaining()))
                    while True:
                        telemetry = candidate_worker.model_idle(
                            recovery, urllib.request.urlopen, allow_busy=True)
                        if telemetry['processing_slots'] == 0:
                            observed.update(complete=True, idle=telemetry,
                                            observed_monotonic=time.monotonic())
                            break
                        time.sleep(min(1.25, recovery.remaining()))
                except BaseException as error:
                    BLOCKED = type(error).__name__
                    observed['error'] = type(error).__name__
                    raise RuntimeError('Shared model recovery unverified; retain for inspection') from error
                finally:
                    candidate_worker.save(out / 'MODEL_RECOVERY.json', observed)
                    trace(out, 'model_recovery', complete=observed['complete'],
                          error=observed.get('error'))
    finally:
        try:
            if work is not None:
                if BLOCKED is None:
                    try:
                        shutil.rmtree(work)
                    except OSError as error:
                        BLOCKED = type(error).__name__
                        candidate_worker.save(out / 'SCRATCH_RETAINED.json',
                            dict(path=str(work), reason='cleanup_failed', error=type(error).__name__))
                        raise
                else:
                    candidate_worker.save(out / 'SCRATCH_RETAINED.json',
                        dict(path=str(work), reason='infrastructure_failure_requires_inspection'))
        finally:
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            if cancelled_at is not None:
                # Transport/recovery wrappers must not turn a process stop
                # into an ordinary HTTP failure followed by more requests.
                error = InterruptedError('Request process was cancelled')
                error.cancelled_at_monotonic = cancelled_at
                raise error
    return (out / 'solution.v').read_text(encoding='utf-8'), (out / 'trace.jsonl').read_text(encoding='utf-8')






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
    # Each accepted request gets a new private evidence directory. Caller IDs
    # are metadata only; no cache, resume, or task-derived filesystem paths.
    base = Path(os.environ.get('RTL_EVIDENCE_DIR') or
                (Path(os.environ.get('EDA_TMP') or tempfile.gettempdir()) / 'rtl-evidence'))
    base.mkdir(parents=True, exist_ok=True, mode=0o700)
    request_root = Path(tempfile.mkdtemp(prefix='request-', dir=base))
    task = request_root / 'in'
    task.mkdir()
    write(task / 'prompt.txt', data['prompt'])
    if data.get('interface'):
        write(task / 'interface.txt', data['interface'])
    write(request_root / 'request.json', json.dumps(data, ensure_ascii=False))
    budget = deadline - min(1, deadline * .1)
    solution, events = run_job(mode, task, request_root / 'out', budget, parent_started=started)
    result = dict(task_id=data['task_id'], solution=solution, trace=events,
                  elapsed_s=round(time.monotonic() - started, 3))
    write(request_root / 'response.json', json.dumps(result, ensure_ascii=False))
    return result



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
        except InterruptedError as exc:
            # HTTPServer catches Exception and otherwise keeps serving.
            # Exit only after run_job has finished bounded cleanup.
            raise SystemExit(1) from exc
        except (ValueError, UnicodeError) as exc:
            self.send_json(400, {'error': str(exc)})
        except (OSError, KeyError, RuntimeError, subprocess.SubprocessError):
            self.send_json(503, {'error': 'runtime unavailable'})


def main():
    p = argparse.ArgumentParser()
    p.add_argument('action', choices=('run', 'baseline', 'serve'))
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
        HTTPServer(('127.0.0.1', args.port), Handler).serve_forever()
    elif args.task is None or args.out is None:
        p.error('task_dir and out_dir required')
    else:
        run_job('agent' if args.action == 'run' else 'baseline', args.task, args.out,
                float(os.environ.get('AGENT_DEADLINE_S', '300')))


if __name__ == '__main__':
    main()
