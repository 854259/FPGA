"""Selected frozen model/repair loop; transport and probes are owned by candidate_worker."""
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from urllib.parse import urlparse
ROOT = Path(__file__).resolve().parent
PKG = ROOT.parent
if str(PKG) not in sys.path:
    sys.path.insert(0, str(PKG))

def skill_texts():
    """Locate the skill pack in either the development or the packaged layout.

    The submission package keeps the agent at <pkg>/agent/ and skills at
    <pkg>/skill/<name>/SKILL.md, while the development tree keeps them flat
    beside this file. Both layouts are resolved so the packaged tree can be
    tested without editing paths.
    """
    pairs = ((ROOT / 'skill/rtl-generation/SKILL.md', ROOT / 'skill/rtl-feedback-repair/SKILL.md'), (ROOT.parent / 'skill/rtl-generation/SKILL.md', ROOT.parent / 'skill/rtl-feedback-repair/SKILL.md'), (ROOT / 'skill/RTL_SKILL.md', ROOT / 'skill/RTL_REPAIR_SKILL.md'), (ROOT.parent / 'skill/RTL_SKILL.md', ROOT.parent / 'skill/RTL_REPAIR_SKILL.md'))
    for generation, repair in pairs:
        if generation.is_file() and repair.is_file():
            return (generation.read_text(encoding='utf-8'), repair.read_text(encoding='utf-8'))
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

def models():
    with urllib.request.urlopen(endpoint() + '/models', timeout=2) as r:
        return [v['id'] for v in json.load(r)['data']]

def vivado_tool(name):
    base = os.environ.get('VIVADO_BIN')
    if not base and os.environ.get('XILINX_VIVADO'):
        base = str(Path(os.environ['XILINX_VIVADO']) / 'bin')
    suffix = '.bat' if os.name == 'nt' else ''
    path = str(Path(base) / (name + suffix)) if base else shutil.which(name + suffix)
    return path if path and Path(path).is_file() else None

_SUBMODULE_KEYWORDS = frozenset('\nmodule endmodule input output inout wire reg logic assign always always_comb always_ff\nalways_latch initial begin end if else case endcase casez casex for while repeat forever\nfunction endfunction task endtask generate endgenerate genvar parameter localparam defparam\nposedge negedge integer real time signed unsigned default return break continue typedef\nstruct enum packed unpacked static automatic specify endspecify primitive table endtable\nsupply0 supply1 tri triand trior wand wor byte shortint int longint bit string void assert\nassume cover property endproperty sequence endsequence interface endinterface package\nendpackage import export class endclass new this super extends virtual pure\n'.split())

_SUBMODULE_PRIMITIVES = frozenset('\nand nand or nor xor xnor not buf bufif0 bufif1 notif0 notif1 nmos pmos cmos rnmos rpmos\nrcmos tran tranif0 tranif1 rtran rtranif0 rtranif1 pullup pulldown\n'.split())

_RE_MODULE_DECL = re.compile('^\\s*module\\s+([A-Za-z_]\\w*)', re.M)

_RE_INSTANTIATION = re.compile('^[ \\t]*([A-Za-z_]\\w*)\\s*(?:#\\s*\\([^;]*?\\)\\s*)?([A-Za-z_]\\w*)\\s*(?:\\[[^\\]]*\\]\\s*)?\\(([^;]*?)\\)\\s*;', re.M | re.S)

_RE_NAMED_PORT = re.compile('\\.\\s*[A-Za-z_]\\w*\\s*\\(')

def undefined_submodules(code):
    """Module names instantiated with a named port map but never defined here.

    Returns names in first-seen order. Empty list means nothing was flagged.
    """
    text = re.sub('/\\*.*?\\*/', ' ', code, flags=re.S)
    text = re.sub('//[^\\n]*', ' ', text)
    text = re.sub('"(?:[^"\\\\]|\\\\.)*"', '""', text)
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

_RE_NONREG = re.compile('VRFC 10-1280\\]\\s*procedural assignment to a non-register\\s+(\\w+)')

_RE_REDECL = re.compile("VRFC 10-9336\\]\\s*redeclaration of ANSI port\\s+'?(\\w+)'?")

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
    head = re.search('\\bmodule\\s+\\w+\\s*(?:#\\s*\\(.*?\\)\\s*)?\\((.*?)\\)\\s*;', code, re.S)
    if not head:
        return None
    ports, tail = (head.group(1), code[head.end(1):])
    changed = False
    for name in names:
        pattern = re.compile('(\\boutput\\b)(\\s+(?:wire\\s+|logic\\s+|reg\\s+)?)((?:\\[[^\\]]*\\]\\s*)?)(\\b' + re.escape(name) + '\\b)')

        def upgrade(match, _name=name):
            if 'reg' in match.group(2) or 'logic' in match.group(2):
                return match.group(0)
            return match.group(1) + ' reg ' + match.group(3) + match.group(4)
        upgraded = pattern.sub(upgrade, ports)
        if upgraded != ports:
            ports = upgraded
            changed = True
        stripped = re.sub('(?m)^[ \\t]*reg\\b[^;\\n]*\\b' + re.escape(name) + '\\b[^;\\n]*;[ \\t]*\\r?\\n', '', tail)
        if stripped != tail:
            tail = stripped
            changed = True
    if not changed:
        return None
    return code[:head.start(1)] + ports + tail

def worker(task, out):
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
    code, feedback = ('', '')
    trace(out, 'agent_meta', boundary='prompt_only_candidate_compile', skill_sha256=hashlib.sha256(skill.encode()).hexdigest(), repair_skill_sha256=hashlib.sha256(repair_skill.encode()).hexdigest(), repairs=repairs)
    for attempt in range(repairs + 1):
        user = prompt if attempt == 0 else prompt + '\nPrevious candidate:\n' + code + '\nCandidate diagnostics:\n' + feedback
        body = dict(model=model, messages=[dict(role='system', content=skill + ('\n' + repair_skill if attempt else '')), dict(role='user', content=user)], temperature=float(os.environ.get('RTL_TEMPERATURE', '0')), top_p=1.0, max_tokens=int(os.environ.get('RTL_MAX_TOKENS', '8192')))
        trace(out, 'llm_start', round=attempt)
        try:
            req = urllib.request.Request(endpoint() + '/chat/completions', data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=300) as r:
                payload = json.load(r)
            choice = payload['choices'][0]
            usage = payload.get('usage') or {}
            reply = choice['message'].get('content') or ''
            trace(out, 'llm', round=attempt, tokens_in=usage.get('prompt_tokens'), tokens_out=usage.get('completion_tokens'), finish=choice.get('finish_reason'))
            code = baseline.extract(reply, 'rtl')
        except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
            trace(out, 'llm', round=attempt, error=type(exc).__name__)
            return
        write(out / 'solution.v', code)
        if re.search('`include|\\$(?:readmem\\w*|fopen|system)\\b', code):
            feedback = 'Return a self-contained module without file access or include directives.'
            trace(out, 'check_source', rc=1, excerpt=feedback)
            continue
        if not re.search('\\bmodule\\s+TopModule\\b', code) or 'endmodule' not in code:
            feedback = 'Return a complete TopModule ending in endmodule.'
            if choice.get('finish_reason') == 'length':
                feedback += ' Output reached the token limit; shorten the implementation.'
            trace(out, 'check_source', rc=1, excerpt=feedback)
            continue
        try:
            undefined = undefined_submodules(code)
        except Exception:
            undefined = []
        if undefined:
            feedback = 'The design instantiates module(s) that this file never defines: ' + ', '.join(undefined) + '.'
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
        result = subprocess.run([tool, '--sv', str(wd / 'candidate.sv')], cwd=wd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace')
        lines = [s for s in result.stdout.splitlines() if re.search('ERROR|WARNING|FATAL', s)]
        feedback = '\n'.join(lines)[:2048] or result.stdout[-2048:]
        trace(out, 'lint', rc=result.returncode, excerpt=feedback, round=attempt)
        if result.returncode != 0:
            try:
                patched = repair_ansi_declarations(code, feedback)
            except Exception:
                patched = None
            if patched:
                write(wd / 'candidate.sv', patched)
                again = subprocess.run([tool, '--sv', str(wd / 'candidate.sv')], cwd=wd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors='replace')
                if again.returncode == 0:
                    write(out / 'solution.v', patched)
                    trace(out, 'declaration_fix', rc=0, round=attempt)
                    return
        if result.returncode == 0:
            feedback = map_feedback(prompt, code, out, attempt)
            if feedback:
                trace(out, 'map_feedback', round=attempt, excerpt=feedback, repair_available=attempt < repairs)
                continue
            return
