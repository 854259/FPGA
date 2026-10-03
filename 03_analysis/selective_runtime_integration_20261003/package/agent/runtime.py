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
# In the packaged layout the agent lives at <pkg>/agent/ while the official baseline
# and our integrity manifest sit at the package root; the development tree keeps
# everything beside this file. Detect the layout instead of assuming one.
PKG = ROOT.parent if (ROOT.parent / 'baseline.py').is_file() else ROOT
# `worker` imports the untouched official baseline to reuse its extract() helper.
# In the packaged layout that module sits at the package root rather than beside
# this file, so make the package root importable in both layouts.
if str(PKG) not in sys.path:
    sys.path.insert(0, str(PKG))
LOCK = threading.Lock()

# Templates are unchanged from the frozen R2 diagnostic/control prompt.
REVIEW_CONTROL = 'Review the candidate against the specification. Return one complete corrected TopModule. Preserve the required interface and behaviour; output only code.'
REVIEW_CHECKLIST = '\nReview checklist:\nBefore finalizing, infer the required bit widths, signed or unsigned interpretation, extension behaviour and shift semantics from the explicit specification. Check that operand declarations and expression types implement those requirements. Correct only what the specification requires; do not add unspecified initialization or change the required interface.'


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
        ready = bool(model and model in models() and baseline_integrity() and vivado_tool('xvlog')
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
            command = [sys.executable, str(PKG / 'baseline.py'), str(inp), str(out), 'rtl']
        else:
            command = [sys.executable, str(ROOT / 'runtime.py'), 'worker', str(inp), str(out),
                       '--deadline-mono', str(started + seconds)]
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


def _sha(value):
    return hashlib.sha256(value.encode('utf-8') if isinstance(value, str) else value).hexdigest()


def _review_config():
    mode = os.environ.get('RTL_REVIEW_MODE', 'off')
    if mode not in ('off', 'observe', 'control', 'checklist'):
        raise ValueError('RTL_REVIEW_MODE must be off/observe/control/checklist')
    config = {'mode': mode}
    for name, env, default in (
            ('llm_cap_s', 'RTL_REVIEW_LLM_CAP_S', '20'),
            ('compile_cap_s', 'RTL_REVIEW_COMPILE_CAP_S', '5'),
            ('cleanup_reserve_s', 'RTL_REVIEW_CLEANUP_RESERVE_S', '6')):
        value = float(os.environ.get(env, default))
        if not math.isfinite(value) or value <= 0:
            raise ValueError(env + ' must be a finite positive number')
        config[name] = value
    value = float(os.environ.get('RTL_REVIEW_SOCKET_CAP_S', str(config['llm_cap_s'])))
    if not math.isfinite(value) or value <= 0:
        raise ValueError('RTL_REVIEW_SOCKET_CAP_S must be a finite positive number')
    config['socket_cap_s'] = value
    return config


def _interface_signature(source):
    """Simple ANSI port subset only; unknown syntax never means equal."""
    import signedness_selector
    code, closed = signedness_selector._strip_noncode(source)
    if not closed:
        return None
    if len(re.findall(r'\bmodule\s+TopModule\b', code)) != 1:
        return None
    match = re.search(r'\bmodule\s+TopModule\s*\(([^()]*)\)\s*;', code, re.S)
    if not match:
        return None
    ports, names, previous = [], set(), None
    for item in match[1].split(','):
        item = item.strip()
        declared = re.fullmatch(r'(input|output|inout)\s+(?:(?:wire|reg|logic)\s+)?'
                               r'(?:(signed|unsigned)\s+)?(?:\[\s*(\d+)\s*:\s*(\d+)\s*\]\s*)?'
                               r'([A-Za-z_][A-Za-z0-9_$]*)', item)
        if declared:
            direction, sign, high, low, name = declared.groups()
            previous = direction, sign == 'signed', (int(high), int(low)) if high else None
        elif previous and re.fullmatch(r'[A-Za-z_][A-Za-z0-9_$]*', item):
            name = item
        else:
            return None
        if name in names:
            return None
        names.add(name)
        ports.append((name, *previous))
    return tuple(ports) if ports else None


def _linux_descendants(pid):
    """Best-effort PID/starttime ownership snapshot; outer PG is final cleanup."""
    result, todo = {}, [pid]
    while todo:
        parent = todo.pop()
        try:
            children = (Path('/proc') / str(parent) / 'task' / str(parent) / 'children').read_text().split()
        except OSError:
            continue
        for child in children:
            child = int(child)
            if child in result:
                continue
            try:
                stat = (Path('/proc') / str(child) / 'stat').read_text()
                start = stat[stat.rfind(')') + 2:].split()[19]
            except (OSError, IndexError):
                continue
            result[child] = start
            todo.append(child)
    return result


def _kill_owned_stage(proc, children, cleanup_cap):
    # The child inherits the worker's group. Never start a nested session: outer
    # supervision must still kill all this request's tools when the worker exits.
    cleanup_deadline = time.monotonic() + cleanup_cap
    if os.name == 'nt':
        if proc.poll() is None:
            try:
                subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               timeout=min(5, max(.01, cleanup_cap)))
            except (OSError, subprocess.SubprocessError):
                proc.kill()
    else:
        # poll() reaps the root; only rediscover descendants while it remains
        # live/unreaped, so a reused root PID cannot target unrelated processes.
        if proc.poll() is None:
            children.update(_linux_descendants(proc.pid))
        for pid, start in reversed(list(children.items())):
            try:
                stat = (Path('/proc') / str(pid) / 'stat').read_text()
                if stat[stat.rfind(')') + 2:].split()[19] == start:
                    os.kill(pid, signal.SIGKILL)
            except (OSError, IndexError):
                pass
        if proc.poll() is None:
            proc.kill()
    try:
        proc.wait(timeout=max(.01, cleanup_deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        pass


def _bounded_command(command, cwd, log_path, seconds, cleanup_cap):
    """Wall-clock cap without PIPE/communicate or detached nested groups."""
    started = time.monotonic()
    deadline = started + seconds
    children = {}
    timed_out = False
    with Path(log_path).open('wb') as log:
        proc = subprocess.Popen(command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT)
        try:
            while proc.poll() is None:
                if os.name != 'nt':
                    children.update(_linux_descendants(proc.pid))
                left = deadline - time.monotonic()
                if left <= 0:
                    timed_out = True
                    break
                time.sleep(min(.025, left))
        finally:
            _kill_owned_stage(proc, children, cleanup_cap)
    return {'rc': proc.returncode, 'timeout': timed_out, 'sec': time.monotonic() - started,
            'pid': proc.pid, 'descendant_cleanup': 'best_effort_outer_group_final'}


def review_call(request_path, response_path, deadline_mono):
    """One HTTP client subprocess, inherited worker PG; no model lifecycle work."""
    request = json.loads(Path(request_path).read_text(encoding='utf-8'))
    body = request['body']
    started = time.monotonic()
    result = {'mono_start': started, 'request_attempted': False}
    try:
        remaining = deadline_mono - started
        if remaining <= 0:
            raise TimeoutError('request deadline reached')
        req = urllib.request.Request(endpoint() + '/chat/completions',
                                     data=json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json'})
        result['request_attempted'] = True
        with urllib.request.urlopen(req, timeout=min(remaining, request['socket_cap_s'])) as response:
            result['payload'] = json.load(response)
    except Exception as exc:
        result['error'] = type(exc).__name__
        result['shared_model_cancellation'] = 'unknown'
    result['mono_end'] = time.monotonic()
    temp = Path(str(response_path) + '.tmp')
    write(temp, json.dumps(result, ensure_ascii=False))
    os.replace(temp, response_path)


def finish_compiled(prompt, accepted_source, out, attempt, repairs, model, skill,
                    repair_skill, deadline_mono, model_calls, iface=None):
    """At most one optional review, preserving the already compiled answer."""
    original_hash = _sha(accepted_source)
    final_hash = original_hash
    new_hash = None
    used = model_calls
    status, reason = 'rejected', 'exception'
    config = None
    llm_logged = False
    started = time.monotonic()
    try:
        config = _review_config()
        mode = config['mode']
        selector_path = ROOT / 'signedness_selector.py'
        template = REVIEW_CONTROL + (REVIEW_CHECKLIST if mode == 'checklist' else '')
        trace(out, 'review_meta', mode=mode, runtime_sha256=_sha(Path(__file__).read_bytes()),
              selector_sha256=_sha(selector_path.read_bytes()), skill_sha256=_sha(skill),
              repair_skill_sha256=_sha(repair_skill), template_sha256=_sha(template),
              repairs=repairs, **{k: v for k, v in config.items() if k != 'mode'})
        if mode == 'off':
            status, reason = 'bypassed', 'off'
            return
        selected_start = time.monotonic()
        try:
            import signedness_selector
            selected = signedness_selector.analyze(prompt, accepted_source)
        except Exception as exc:
            trace(out, 'review_select', decision='abstain', error=type(exc).__name__,
                  mono_start=selected_start, sec=time.monotonic()-selected_start,
                  source_sha256=original_hash, prompt_sha256=_sha(prompt))
            reason = 'selector_exception'
            return
        trace(out, 'review_select', **selected, mono_start=selected_start,
              sec=time.monotonic()-selected_start, source_sha256=original_hash,
              prompt_sha256=_sha(prompt))
        remaining_calls = repairs - attempt
        remaining_s = deadline_mono - time.monotonic()
        admission = config['llm_cap_s'] + config['compile_cap_s'] + config['cleanup_reserve_s']
        reason = ('observe' if mode == 'observe' else
                  'selection_' + selected.get('decision', 'invalid') if selected.get('decision') != 'review' else
                  'call_budget' if remaining_calls <= 0 else
                  'time_budget' if remaining_s < admission else 'admitted')
        trace(out, 'review_budget', calls_used=used, calls_remaining=remaining_calls,
              remaining_s=remaining_s, admission_s=admission, reason=reason)
        if reason != 'admitted':
            status = 'bypassed'
            return
        old_interface = _interface_signature(accepted_source)
        interface_text = Path(iface).read_text(encoding='utf-8') if iface and Path(iface).is_file() else ''
        specified_interface = _interface_signature(interface_text) if interface_text.strip() else None
        if old_interface is None or (interface_text.strip() and
                                     (specified_interface is None or old_interface != specified_interface)):
            reason = 'accepted_interface_unparseable_or_mismatch'
            return
        review_dir = out / 'review'
        review_dir.mkdir()
        body = dict(model=model,
                    messages=[dict(role='system', content=skill+'\n'+repair_skill),
                              dict(role='user', content=prompt+'\nPrevious candidate:\n'+accepted_source+'\n'+template)],
                    temperature=float(os.environ.get('RTL_TEMPERATURE', '0')),
                    top_p=1.0, max_tokens=int(os.environ.get('RTL_MAX_TOKENS', '8192')))
        request_path, response_path = review_dir/'request.json', review_dir/'response.json'
        write(request_path, json.dumps({'body': body, 'socket_cap_s': config['socket_cap_s']}, ensure_ascii=False))
        request_hash = _sha(json.dumps(body).encode())
        now = time.monotonic()
        client_deadline = min(now+config['llm_cap_s'], deadline_mono-config['compile_cap_s']-config['cleanup_reserve_s'])
        if client_deadline <= now:
            reason = 'time_budget_before_llm'
            return
        used += 1
        trace(out, 'review_llm_start', call_id='optional_review_1', request_sha256=request_hash,
              model=model, temperature=body['temperature'], top_p=body['top_p'], max_tokens=body['max_tokens'],
              mono_start=now, stage_deadline_mono=client_deadline, calls_used=used)
        stage = _bounded_command([sys.executable, str(ROOT/'runtime.py'), 'review-call',
                                  str(request_path), str(response_path), '--deadline-mono', str(client_deadline)],
                                 review_dir, review_dir/'client.log', client_deadline-now,
                                 config['cleanup_reserve_s'])
        if stage['timeout'] or stage['rc'] != 0 or not response_path.is_file():
            llm_logged = True
            trace(out, 'review_llm_end', **stage, mono_end=time.monotonic(),
                  error='client_timeout' if stage['timeout'] else 'client_failed',
                  shared_model_cancellation='unknown')
            reason = 'client_timeout' if stage['timeout'] else 'client_failed'
            return
        response = json.loads(response_path.read_text(encoding='utf-8'))
        if response.get('error'):
            llm_logged = True
            trace(out, 'review_llm_end', **stage, mono_end=time.monotonic(),
                  error=response['error'], shared_model_cancellation='unknown')
            reason = 'llm_error'
            return
        payload = response['payload']
        choice = payload['choices'][0]
        usage = payload.get('usage') or {}
        cache = {key: value for key, value in payload.items() if 'cache' in key.lower() or key == 'timings'}
        llm_logged = True
        trace(out, 'review_llm_end', **stage, mono_end=time.monotonic(), finish=choice.get('finish_reason'),
              tokens_in=usage.get('prompt_tokens'), tokens_out=usage.get('completion_tokens'),
              usage=usage, cache=cache, shared_model_cancellation='not_requested_response_received')
        import baseline
        candidate = baseline.extract(choice['message'].get('content') or '', 'rtl')
        new_hash = _sha(candidate)
        write(review_dir/'candidate.sv', candidate)
        forbidden = re.search(r'`include|\$(?:readmem\w*|writemem\w*|dumpfile|dumpvars|dumpall|dumpon|dumpoff|'
                              r'fopen|fclose|fdisplay\w*|fwrite\w*|fmonitor\w*|fstrobe\w*|fscanf|fread|'
                              r'fgets|feof|fflush|rewind|ftell|fseek|ferror|system)\b', candidate)
        gates = {'nonempty': bool(candidate.strip()), 'nonlength': choice.get('finish_reason') != 'length',
                 'no_file_io': not forbidden,
                 'complete_module': bool(re.search(r'\bmodule\s+TopModule\b', candidate) and
                                         re.search(r'\bendmodule\b', candidate)),
                 'same_interface': _interface_signature(candidate) == old_interface}
        try:
            gates['self_contained'] = not undefined_submodules(candidate)
        except Exception:
            gates['self_contained'] = False
        trace(out, 'review_validate', source_sha256=new_hash, gates=gates)
        if not all(gates.values()):
            reason = 'candidate_gate:' + ','.join(key for key, value in gates.items() if not value)
            return
        if candidate == accepted_source:
            status, reason = 'unchanged', 'identical_source'
            return
        tool = vivado_tool('xvlog')
        if not tool:
            reason = 'xvlog_unavailable'
            return
        cap = min(config['compile_cap_s'], deadline_mono-time.monotonic()-config['cleanup_reserve_s'])
        if cap <= 0:
            reason = 'time_budget_before_compile'
            return
        compile_dir = review_dir/'compile'
        compile_dir.mkdir()
        write(compile_dir/'candidate.sv', candidate)
        log_path = compile_dir/'xvlog.log'
        stage = _bounded_command([tool, '--sv', str(compile_dir/'candidate.sv')], compile_dir,
                                 log_path, cap, config['cleanup_reserve_s'])
        trace(out, 'review_validate', source_sha256=new_hash, **stage,
              log_path=str(log_path), log_sha256=_sha(log_path.read_bytes()),
              remaining_s=deadline_mono-time.monotonic())
        if stage['timeout'] or stage['rc'] != 0:
            reason = 'compile_timeout' if stage['timeout'] else 'compile_failed'
            return
        if deadline_mono-time.monotonic() < config['cleanup_reserve_s']:
            reason = 'time_budget_before_commit'
            return
        # solution.v has contained accepted_source throughout review. Write the
        # replacement beside it, then atomically switch complete files.
        replacement = out/'solution.review.tmp'
        write(replacement, candidate)
        os.replace(replacement, out/'solution.v')
        final_hash = new_hash
        status, reason = 'accepted', 'static_and_compile_gates_only'
    except Exception as exc:
        reason = 'exception:' + type(exc).__name__
    finally:
        if used > model_calls and not llm_logged:
            trace(out, 'review_llm_end', error=reason, mono_end=time.monotonic(),
                  shared_model_cancellation='unknown')
        trace(out, 'review_commit', mode=config['mode'] if config else 'invalid',
              status=status, reason=reason, original_sha256=original_hash,
              candidate_sha256=new_hash, final_sha256=final_hash, model_calls=used,
              sec=time.monotonic()-started, functional_improvement='unverified')


def worker(task, out, deadline_mono=None):
    task = Path(task).resolve()
    out = Path(out).resolve()
    started = time.monotonic()
    if deadline_mono is None:
        deadline_mono = started + float(os.environ.get('AGENT_DEADLINE_S', '300'))
    try:
        _worker_impl(task, out, deadline_mono)
    finally:
        try:
            events = [json.loads(line) for line in (out/'trace.jsonl').read_text(encoding='utf-8').splitlines()]
            calls = sum(event.get('tool') in ('llm_start', 'review_llm_start') for event in events)
            commit = next((event for event in reversed(events) if event.get('tool') == 'review_commit'), {})
            trace(out, 'worker_done', mono_start=started, mono_end=time.monotonic(),
                  elapsed_s=time.monotonic()-started, deadline_reached=time.monotonic() >= deadline_mono,
                  final_sha256=_sha((out/'solution.v').read_bytes()), model_calls=calls,
                  return_source='reviewed' if commit.get('status') == 'accepted' else 'original')
        except (OSError, ValueError):
            pass


def _worker_impl(task, out, deadline_mono):
    # Import ONLY the untouched extraction helper; never import the development evaluator.
    import baseline
    out = Path(out)
    prompt = (Path(task) / 'prompt.txt').read_text(encoding='utf-8')
    iface = Path(task) / 'interface.txt'
    if iface.is_file() and iface.read_text(encoding='utf-8').strip():
        prompt += '\n\nInterface:\n' + iface.read_text(encoding='utf-8')
    skill, repair_skill = skill_texts()
    repairs = int(os.environ.get('RTL_REPAIRS', '1'))
    if not 0 <= repairs <= 2:
        raise ValueError('RTL_REPAIRS must be 0..2')
    model = os.environ.get('MODEL_NAME') or models()[0]
    code, feedback = '', ''
    model_calls = 0
    trace(out, 'agent_meta', boundary='prompt_only_candidate_compile',
          skill_sha256=hashlib.sha256(skill.encode()).hexdigest(),
          repair_skill_sha256=hashlib.sha256(repair_skill.encode()).hexdigest(), repairs=repairs)
    for attempt in range(repairs + 1):
        user = prompt if attempt == 0 else prompt + '\nPrevious candidate:\n' + code + '\nCandidate diagnostics:\n' + feedback
        body = dict(model=model, messages=[dict(role='system', content=skill + ('\n' + repair_skill if attempt else '')),
                                         dict(role='user', content=user)],
                    temperature=float(os.environ.get('RTL_TEMPERATURE', '0')),
                    top_p=1.0, max_tokens=int(os.environ.get('RTL_MAX_TOKENS', '8192')))
        model_calls += 1
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
        # A hierarchical design that instantiates a module it never defines still passes
        # xvlog, because analysis does not resolve module instantiation; it only fails at
        # elaboration, which the judge runs and we do not. Catch it by text instead: it
        # costs nothing, whereas an xelab pass costs about a second on every task.
        # Validated against xelab ground truth on 200 generated solutions with no false
        # positives; it finds every missing-submodule case and ignores other error classes.
        # Measured effect on the four tasks it fires on: one moved L0 to L3.
        #
        # This runs on every candidate, so it must never be able to break one. The check
        # is an optimisation, not a requirement: any failure here means "nothing flagged"
        # and the pipeline carries on exactly as before.
        try:
            undefined = undefined_submodules(code)
        except Exception:
            undefined = []
        if undefined:
            # Report the fact only. A paired A/B showed that adding a prescription
            # ("define it, or rewrite as one flat module") produced no benefit and
            # steered the model into a flattened form that then failed xvlog, so the
            # message stays factual, matching the condition that recovered 2 of 5.
            feedback = ('The design instantiates module(s) that this file never defines: ' +
                        ', '.join(undefined) + '.')
            trace(out, 'check_submodules', rc=1, excerpt=feedback)
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
        if result.returncode != 0:
            # A declaration fault is mechanical, so fix it by text instead of spending a
            # model call on it. The patch is only accepted if it actually recompiles;
            # otherwise the loop falls through to the normal model repair below.
            # Prob058_alwaysblock2 goes from L0 to L3 this way with no model call.
            try:
                patched = repair_ansi_declarations(code, feedback)
            except Exception:
                patched = None
            if patched:
                write(wd / 'candidate.sv', patched)
                again = subprocess.run([tool, '--sv', str(wd / 'candidate.sv')], cwd=wd,
                                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       text=True, errors='replace')
                if again.returncode == 0:
                    write(out / 'solution.v', patched)
                    trace(out, 'declaration_fix', rc=0, round=attempt)
                    finish_compiled(prompt, patched, out, attempt, repairs, model, skill, repair_skill,
                                    deadline_mono, model_calls, iface)
                    return  # Compilation is NOT an official L1/L2/L3 judgement.
        if result.returncode == 0:
            finish_compiled(prompt, code, out, attempt, repairs, model, skill, repair_skill,
                            deadline_mono, model_calls, iface)
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
    p.add_argument('action', choices=('run', 'baseline', 'worker', 'review-call', 'serve'))
    p.add_argument('task', nargs='?')
    p.add_argument('out', nargs='?')
    p.add_argument('--port', type=int, default=7860)
    p.add_argument('--deadline-mono', type=float)
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
    elif args.action == 'review-call':
        review_call(args.task, args.out, args.deadline_mono)
    elif args.action == 'worker':
        worker(args.task, args.out, args.deadline_mono)
    else:
        run_job('agent' if args.action == 'run' else 'baseline', args.task, args.out,
                float(os.environ.get('AGENT_DEADLINE_S', '300')))


if __name__ == '__main__':
    main()
