"""Bounded, preregistered synthetic budget experiment; never edits live settings.

Only prompt.txt and the frozen agent system prompt enter model requests. Private
vectors/reference RTL validate this experiment's simulator, never guide repair.
This is first-generation engineering evidence, not a VerilogEval score or an
independent competition holdout. No retries, prompt search, or auto-deployment.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import re
import shutil
import signal
import subprocess
import time
import urllib.request


PROFILES = [
    dict(name='control', max_tokens=8192, thinking_token_budget=None),
    dict(name='t4096_m8192', max_tokens=8192, thinking_token_budget=4096),
    dict(name='t6144_m10240', max_tokens=10240, thinking_token_budget=6144),
    dict(name='t8192_m12288', max_tokens=12288, thinking_token_budget=8192),
]
INTERFACE = ('module TopModule(input wire clk, rst, en, input wire [31:0] x, y, '
             'output reg [31:0] z, output reg valid);')
TIMING = ('Use this exact interface: ' + INTERFACE + '\nOn each rising clock edge, '
          'synchronous active-high rst has priority and clears z, valid, and any '
          'history. Otherwise set valid to en. If en=0 hold z and history; if en=1 '
          'register the specified result computed from current inputs and old history. '
          'Ignore unspecified input bits. Produce synthesizable SystemVerilog.\n')
SPECS = [
    ('gf_product', 'selection', 'Treat x[7:0] and y[7:0] as polynomials over GF(2). '
     'Multiply them and reduce modulo t^8+t^4+t^3+t^2+1 (hex 11d). '
     'Put the eight coefficients in z[7:0], with z[31:8]=0.'),
    ('rounded_fixed', 'selection', 'Interpret x[15:0] as a signed two-complement '
     'integer a. Round a/8 to the nearest integer, with exact halves rounded to '
     'the even integer. Clamp the rounded value to [-512,511]. z is its signed '
     '32-bit two-complement representation. y is unused.'),
    ('median_five', 'selection', 'Five unsigned six-bit integers occupy '
     'x[5:0], x[11:6], x[17:12], x[23:18], x[29:24]. Sort them conceptually in '
     'nondecreasing order and output the third value, zero-extended to z. '
     'Duplicate values count separately. y is unused.'),
    ('history_filter', 'selection', 'Each enabled edge accepts signed input '
     'a=x[7:0]. Let h1 and h2 be the two most recent accepted signed inputs, '
     'initially zero after reset. Output the exact signed result '
     '3*a+5*h1-2*h2 sign-extended to 32 bits, then update h2=h1 and h1=a. '
     'Disabled edges do not enter the history. y is unused.'),
    ('associative_lookup', 'validation', 'Four eight-bit keys occupy '
     'x[7:0], x[15:8], x[23:16], x[31:24]. Their validity bits are y[8], '
     'y[9], y[10], y[11]; query key is y[7:0]. Find the lowest numbered valid '
     'matching entry. If one exists set z[8]=1 and z[1:0] to its index; '
     'otherwise z=0. All other z bits are zero.'),
    ('prime_inverse', 'validation', 'Let a be unsigned x[7:0]. For 1<=a<=250, '
     'output the unique integer b in [1,250] for which (a*b) modulo 251 equals '
     'one. For a=0 or a>=251 output zero. z is zero-extended; y is unused. '
     'The same one-edge register timing applies; no busy port or extra cycles.'),
    ('complex_product', 'validation', 'x[7:0] and x[15:8] are respectively '
     'signed eight-bit real and imaginary parts of A; y[7:0] and y[15:8] '
     'likewise form B. Multiply the two complex numbers. Put the low 16 bits '
     'of the signed real result in z[15:0], and low 16 bits of the signed '
     'imaginary result in z[31:16].'),
    ('matrix_transpose', 'validation', 'x[15:0] encodes a four-by-four bit '
     'matrix in row-major order: element (row,column) is bit 4*row+column. '
     'Output its transpose in z[15:0] using the same encoding, with z[31:16]=0. '
     'y is unused.'),
]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def save(path, data):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(path)


def signed(n, bits=8):
    n &= (1 << bits) - 1
    return n - (1 << bits) if n & (1 << (bits-1)) else n


def expected(kind, x, y, history):
    if kind == 'gf_product':
        p = 0
        for i in range(8):
            if (y >> i) & 1:
                p ^= (x & 255) << i
        for i in range(14, 7, -1):
            if (p >> i) & 1:
                p ^= 0x11d << (i-8)
        value = p
    elif kind == 'rounded_fixed':
        q, rem = divmod(signed(x, 16), 8)
        value = max(-512, min(511, q + (rem > 4 or (rem == 4 and q % 2))))
    elif kind == 'median_five':
        value = sorted((x >> (6*i)) & 63 for i in range(5))[2]
    elif kind == 'history_filter':
        value = 3*signed(x) + 5*history[0] - 2*history[1]
        history[:] = [signed(x), history[0]]
    elif kind == 'associative_lookup':
        hits = [i for i in range(4) if ((y >> (8+i)) & 1) and ((x >> (8*i)) & 255) == (y & 255)]
        value = 256 + hits[0] if hits else 0
    elif kind == 'prime_inverse':
        a = x & 255
        value = pow(a, -1, 251) if 1 <= a <= 250 else 0
    elif kind == 'complex_product':
        ar, ai, br, bi = signed(x), signed(x >> 8), signed(y), signed(y >> 8)
        value = ((ar*br-ai*bi) & 65535) | (((ar*bi+ai*br) & 65535) << 16)
    elif kind == 'matrix_transpose':
        value = sum(((x >> (4*r+c)) & 1) << (4*c+r) for r in range(4) for c in range(4))
    else:
        raise ValueError(kind)
    return value & 0xffffffff


def reference(kind):
    bodies = {
        'gf_product': "p=0; for(i=0;i<8;i=i+1) if(y[i]) p=p^({8'b0,x[7:0]}<<i); for(i=14;i>=8;i=i-1) if(p[i]) p=p^(16'h11d<<(i-8)); z<={24'b0,p[7:0]};",
        'rounded_fixed': 'a=$signed(x[15:0]); q=a>>>3; r=a-8*q; if(r>4 || (r==4 && (q&1))) q=q+1; if(q>511) q=511; if(q < -512) q=-512; z<=q;',
        'median_five': 'for(i=0;i<5;i=i+1) s[i]=(x>>(6*i))&63; for(i=0;i<5;i=i+1) for(j=i+1;j<5;j=j+1) if(s[j]<s[i]) begin a=s[i]; s[i]=s[j]; s[j]=a; end z<=s[2];',
        'history_filter': 'a=$signed(x[7:0]); z<=3*a+5*h1-2*h2; h2<=h1; h1<=a;',
        'associative_lookup': "a=0; for(i=3;i>=0;i=i-1) if(y[8+i] && (((x>>(8*i))&255)==(y&255))) a=256+i; z<=a;",
        'prime_inverse': 'a=x&255; q=0; for(i=1;i<=250;i=i+1) if(a>0 && a<251 && ((a*i)%251)==1) q=i; z<=q;',
        'complex_product': 'a=$signed(x[7:0]); b=$signed(x[15:8]); c=$signed(y[7:0]); d=$signed(y[15:8]); q=a*c-b*d; r=a*d+b*c; z<={r[15:0],q[15:0]};',
        'matrix_transpose': 'a=0; for(i=0;i<4;i=i+1) for(j=0;j<4;j=j+1) a=a|(((x>>(4*i+j))&1)<<(4*j+i)); z<=a;',
    }
    return (INTERFACE + '\ninteger a,b,c,d,q,r,i,j,h1,h2,s[0:4]; reg [15:0] p;\n'
            'always @(posedge clk) begin if(rst) begin z<=0;valid<=0;h1<=0;h2<=0;end '
            'else begin valid<=en; if(en) begin ' + bodies[kind] + ' end end end\nendmodule\n')


def make_vectors(kind, seed):
    rng = random.Random(seed)
    h, out = [0, 0], 0
    rows = []
    for i in range(640):
        x, y = rng.getrandbits(32), rng.getrandbits(32)
        if i < 256:
            x = (x & ~255) | i
        if kind == 'rounded_fixed' and i < 64:
            x = [-32768, -4100, -4096, -4092, -12, -4, 0, 4, 12, 4084, 4092, 4096, 32767][i % 13] & 65535
        if kind == 'associative_lookup' and i % 2 == 0:
            y = (y & ~255) | ((x >> (8*(i % 4))) & 255)
        rst, en = int(i in (0, 1, 33, 257, 511)), int(i % 7 != 0)
        if rst:
            h[:], out, valid = [0, 0], 0, 0
        else:
            valid = en
            if en:
                out = expected(kind, x, y, h)
        rows.append([rst, en, x, y, out, valid])
    return rows


def testbench(rows):
    checks = []
    for i, (rst, en, x, y, out, valid) in enumerate(rows):
        checks.append(f"rst={rst};en={en};x=32'h{x:08x};y=32'h{y:08x};#5;clk=1;#1;"
                      f"if(z!==32'h{out:08x} || valid!==1'b{valid}) begin "
                      f'$display("CALIBRATION_FAIL cycle={i}");$fatal(1);end #4;clk=0;')
    return ('`timescale 1ns/1ps\nmodule tb;reg clk=0,rst=0,en=0;reg[31:0]x=0,y=0;wire[31:0]z;wire valid;'
            'TopModule dut(.*);initial begin\n' + '\n'.join(checks) +
            '\n$display("CALIBRATION_PASS");$finish;end endmodule\n')


def prepare(out, skill, dataset=None):
    out.mkdir(parents=True, exist_ok=False)
    (out/'system.txt').write_bytes(skill.read_bytes())
    manifest = dict(schema=1, profiles=PROFILES, seed=20260927, cases=[],
                    scope='Synthetic first-generation engineering calibration; no formal L-level or holdout claim',
                    selection='Max functional passes, then fewest blanks, then lowest total model seconds; a quality tie needs >=10% measured time reduction to replace control; fixed grid, no refinement',
                    validation='Selected profile versus control once on four reserved specifications; no reselection after validation',
                    deadline_s=300, temperature=0, repairs=0, concurrency=1, max_requests=25,
                    reason='Coarse 4096/6144/8192 thinking caps with 4096 answer allowance; control reproduces uncapped 8192 request',
                    prepared_at=time.time(), hashes={}, near_duplicate_check=[])
    for i, (name, split, spec) in enumerate(SPECS):
        case = out/'cases'/name
        case.mkdir(parents=True)
        (case/'prompt.txt').write_text(TIMING+spec+'\n', encoding='utf-8')
        save(case/'vectors.json', make_vectors(name, 20260927+i))
        (case/'reference.sv').write_text(reference(name), encoding='utf-8')
        manifest['cases'].append(dict(name=name, split=split))
    # Offline text comparison is a warning screen, not proof of semantic novelty.
    if dataset:
        def grams(s):
            words = re.findall(r'[a-z0-9]+', s.lower())
            return {tuple(words[i:i+5]) for i in range(len(words)-4)}
        old = [(p.parent.name, grams(p.read_text(encoding='utf-8'))) for p in dataset.glob('*/prompt.txt')]
        if len(old) != 156:
            raise ValueError('Expected 156 existing prompts for the offline duplication screen')
        for name, _, spec in SPECS:
            g = grams(spec)
            tid, overlap = max(((tid, len(g & other)/max(1, len(g))) for tid, other in old), key=lambda x:x[1])
            manifest['near_duplicate_check'].append(dict(case=name, closest_id=tid, fivegram_overlap=overlap))
            if overlap > .30:
                raise ValueError('Duplicate warning: manual independent-spec review required')
    for p in sorted(out.rglob('*')):
        if p.is_file():
            manifest['hashes'][p.relative_to(out).as_posix()] = sha(p.read_bytes())
    save(out/'plan.json', manifest)
    return manifest


def verify_plan(out):
    plan = json.loads((out/'plan.json').read_text(encoding='utf-8'))
    if plan['profiles'] != PROFILES:
        raise ValueError('Frozen profile grid changed')
    for name, digest in plan['hashes'].items():
        if sha((out/name).read_bytes()) != digest:
            raise ValueError('Frozen input changed: '+name)
    return plan


def predecessor_ready(predecessor):
    meta = json.loads((predecessor/'experiment.json').read_text())
    return (meta.get('complete') is True and (predecessor/'graded_summary.json').is_file()
            and len(list((predecessor/'results').glob('*.json'))) == 312)


def request_body(system, prompt, profile, model):
    body = dict(model=model, messages=[dict(role='system', content=system),
                                      dict(role='user', content=prompt)],
                temperature=0.0, top_p=1.0, max_tokens=profile['max_tokens'])
    if profile['thinking_token_budget'] is not None:
        body['thinking_token_budget'] = profile['thinking_token_budget']
    return body


def extract(content):
    # Same extraction semantics as the fixed baseline, without importing it.
    fence = re.search(r'```(?:systemverilog|verilog|sv|cpp|c\+\+|c)?\s*(.*?)```', content, re.S)
    text = fence.group(1) if fence else content
    match = re.search(r'(module\s+TopModule\b.*?endmodule)', text, re.S)
    return (match.group(0) if match else text).strip()+'\n'


def generate(endpoint, body, timeout=300):
    began = time.monotonic()
    req = urllib.request.Request(endpoint+'/chat/completions', json.dumps(body).encode(),
                                 {'Content-Type':'application/json'})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = json.load(response)
    choice = data['choices'][0]
    message, usage = choice['message'], data.get('usage') or {}
    content = message.get('content') or ''
    reasoning = message.get('reasoning') or message.get('reasoning_content') or ''
    details = usage.get('completion_tokens_details') or {}
    result = dict(model_seconds=time.monotonic()-began, finish=choice.get('finish_reason'),
                  content_chars=len(content), reasoning_chars=len(reasoning),
                  prompt_tokens=usage.get('prompt_tokens'), completion_tokens=usage.get('completion_tokens'),
                  reasoning_tokens=details.get('reasoning_tokens'), response_id=data.get('id'),
                  blank=not content.strip())
    return extract(content), result


def run_tool(args, cwd, timeout, log):
    with log.open('w', encoding='utf-8') as stream:
        proc = subprocess.Popen(args, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
        try:
            return proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)
            proc.wait()
            return 124


def simulate(code, rows, directory, vivado_bin):
    directory.mkdir(parents=True, exist_ok=False)
    candidate = directory/'candidate.sv'
    candidate.write_text(code, encoding='utf-8')
    (directory/'tb.sv').write_text(testbench(rows), encoding='utf-8')
    if re.search(r'`include|\$(?:readmem\w*|fopen|system)\b', code):
        return dict(functional_pass=False, error='disallowed_source_file_access')
    commands = [('compile',[str(vivado_bin/'xvlog'),'--sv','candidate.sv','tb.sv']),
                ('elaborate',[str(vivado_bin/'xelab'),'tb','-s','trial']),
                ('simulate',[str(vivado_bin/'xsim'),'trial','-runall'])]
    outcome = dict(functional_pass=False)
    try:
        for stage, command in commands:
            log = directory/(stage+'.log')
            rc = run_tool(command, directory, 90, log)
            outcome[stage+'_rc'] = rc
            if rc:
                break
        else:
            outcome['functional_pass'] = 'CALIBRATION_PASS' in (directory/'simulate.log').read_text(errors='replace')
    finally:
        # This directory was created exclusively by this call. Keep source/logs;
        # remove only known simulator products owned by this call.
        for name in ('xsim.dir', '.Xil'):
            p = directory/name
            if p.is_dir():
                shutil.rmtree(p)
        for pattern in ('*.jou', '*.pb', '*.wdb'):
            for p in directory.glob(pattern):
                p.unlink()
    return outcome


def choose(records):
    stats = []
    for profile in PROFILES:
        rows = [r for r in records if r['profile']==profile['name']]
        if len(rows) != 4:
            raise ValueError('Selection requires four results for every profile')
        stats.append(dict(profile=profile['name'], passes=sum(r['functional_pass'] for r in rows),
                          blanks=sum(r['blank'] for r in rows), seconds=sum(r['model_seconds'] for r in rows)))
    winner = max(stats, key=lambda r:(r['passes'], -r['blanks'], -r['seconds']))
    control = stats[0]
    if (winner['passes'], winner['blanks']) == (control['passes'], control['blanks']) and winner['seconds'] > .9*control['seconds']:
        winner = control
    return winner['profile'], stats


def execute(out, predecessor, endpoint, model, vivado_bin, max_wait):
    plan = verify_plan(out)
    began_wait = time.monotonic()
    def status(phase, **fields):
        save(out/'status.json', dict(phase=phase, updated_at=time.time(), **fields))
    status('waiting_for_frozen_full156')
    while not predecessor_ready(predecessor):
        if time.monotonic()-began_wait > max_wait:
            raise TimeoutError('Predecessor did not finish within the bounded wait')
        time.sleep(30)
    # Never queue a calibration call behind another evaluation or user workload.
    with urllib.request.urlopen(endpoint.removesuffix('/v1')+'/metrics', timeout=10) as response:
        metrics = response.read().decode()
    busy = [float(line.rsplit(' ',1)[1]) for line in metrics.splitlines()
            if re.match(r'vllm:num_requests_(?:running|waiting)\{', line)]
    if not busy or any(busy):
        raise RuntimeError('Model service is not confirmed idle; no calibration requests sent')
    verify_plan(out)
    status('checking_private_testbenches')
    for case in plan['cases']:
        d = out/'cases'/case['name']
        result = simulate((d/'reference.sv').read_text(), json.loads((d/'vectors.json').read_text()),
                          out/'checks'/case['name'], vivado_bin)
        save(out/'checks'/case['name']/'result.json', result)
        if not result['functional_pass']:
            raise RuntimeError('Private simulator self-check failed: '+case['name'])
    # A wrong constant output must fail, so a permissive bench cannot pass unnoticed.
    d = out/'cases'/'gf_product'
    bad = INTERFACE+' always @(posedge clk) begin z<=0;valid<=0;end endmodule'
    negative = simulate(bad, json.loads((d/'vectors.json').read_text()), out/'checks'/'negative', vivado_bin)
    save(out/'checks'/'negative'/'result.json', negative)
    if negative['functional_pass'] or negative.get('compile_rc') != 0 or negative.get('elaborate_rc') != 0:
        raise RuntimeError('Negative control did not exercise a functional rejection')
    status('verifying_thinking_cap')
    probe_profile = dict(max_tokens=512, thinking_token_budget=32)
    probe_body = request_body('Follow the instruction.',
        'Work out 12345 multiplied by 6789, and output only the decimal result.', probe_profile, model)
    probe_code, probe = generate(endpoint, probe_body)
    save(out/'cap_probe.json', probe)
    if probe['reasoning_tokens'] is None or not (30 <= probe['reasoning_tokens'] <= 48) or probe['blank']:
        raise RuntimeError('Thinking-cap activation not demonstrated; bounded experiment stopped')
    records = []
    system = (out/'system.txt').read_text(encoding='utf-8')
    began = time.monotonic()
    def trial(case, profile, phase):
        if time.monotonic()-began > 10800:
            raise TimeoutError('Experiment exceeded three-hour active budget')
        verify_plan(out)
        name = case['name']
        status(phase, case=name, profile=profile['name'], completed=len(records))
        directory = out/'trials'/phase/name/profile['name']
        d = out/'cases'/name
        body = request_body(system, (d/'prompt.txt').read_text(encoding='utf-8'), profile, model)
        code, result = generate(endpoint, body, plan['deadline_s'])
        if result['prompt_tokens'] is None or result['prompt_tokens']+profile['max_tokens'] > 16384:
            raise RuntimeError('Context accounting could not be verified')
        cap = profile['thinking_token_budget']
        if cap is not None and (result['reasoning_tokens'] is None or result['reasoning_tokens'] > cap+16):
            raise RuntimeError('Thinking cap not honored; stop without changing settings')
        result.update(case=name, profile=profile['name'], phase=phase,
                      candidate_sha256=sha(code.encode()),
                      request_sha256=sha(json.dumps(body,sort_keys=True).encode()))
        result.update(simulate(code, json.loads((d/'vectors.json').read_text()), directory, vivado_bin))
        save(directory/'result.json', result)
        records.append(result)
        save(out/'results.json', records)
        return result
    selection = [c for c in plan['cases'] if c['split']=='selection']
    for i, case in enumerate(selection):
        # Balanced fixed rotation reduces order effects without changing randomness.
        for profile in PROFILES[i:]+PROFILES[:i]:
            trial(case, profile, 'selection')
    winner, stats = choose(records)
    save(out/'selection.json', dict(selected=winner, statistics=stats, frozen_before_validation=True))
    contenders = [PROFILES[0]] + [p for p in PROFILES if p['name']==winner and winner!='control']
    for i, case in enumerate(c for c in plan['cases'] if c['split']=='validation'):
        for profile in (contenders if i%2==0 else list(reversed(contenders))):
            trial(case, profile, 'validation')
    rows = [r for r in records if r['phase']=='validation']
    totals = {p['name']:dict(passes=sum(r['functional_pass'] for r in rows if r['profile']==p['name']),
                            blanks=sum(r['blank'] for r in rows if r['profile']==p['name']),
                            seconds=sum(r['model_seconds'] for r in rows if r['profile']==p['name'])) for p in contenders}
    accepted = totals[winner]['passes'] >= totals['control']['passes'] and totals[winner]['blanks'] <= totals['control']['blanks']
    report = dict(selected_on_calibration=winner, validation=totals,
                  recommendation=winner if accepted else 'retain_control_validation_regressed',
                  validation_gate_passed=accepted, model_calls=1+len(records),
                  limits='Eight synthetic specifications, one generation each; no repairs/synthesis/PPA/full-agent or unseen competition accuracy claim; no configuration deployed',
                  complete=True, finished_at=time.time(), plan_sha256=sha((out/'plan.json').read_bytes()))
    save(out/'report.json', report)
    status('complete', report='report.json', completed=len(records), configuration_deployed=False)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action', choices=('prepare','run'))
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--skill', type=Path)
    ap.add_argument('--dataset', type=Path)
    ap.add_argument('--after-run', type=Path)
    ap.add_argument('--endpoint', default='http://127.0.0.1:8000/v1')
    ap.add_argument('--model', default='rtl-qwen27b')
    ap.add_argument('--vivado-bin', type=Path)
    ap.add_argument('--max-wait', type=int, default=14400)
    args = ap.parse_args()
    out = args.out.resolve()
    if args.action=='prepare':
        if not args.skill:
            ap.error('--skill required for prepare')
        plan = prepare(out, args.skill, args.dataset)
        print(json.dumps(dict(prepared=True, cases=len(plan['cases']), plan_sha256=sha((out/'plan.json').read_bytes()))))
    else:
        if os.name=='nt' or not args.after_run or not args.vivado_bin:
            ap.error('run requires Linux, --after-run and --vivado-bin')
        # Exclusive run marker prevents accidental duplicate calls; no implicit resume.
        marker = out/'started.json'
        with marker.open('x', encoding='utf-8') as f:
            json.dump(dict(pid=os.getpid(), started_at=time.time()), f)
        try:
            execute(out, args.after_run, args.endpoint, args.model, args.vivado_bin, args.max_wait)
        except Exception as exc:
            save(out/'status.json', dict(phase='stopped_error', error=type(exc).__name__, message=str(exc), updated_at=time.time()))
            raise


if __name__=='__main__':
    main()
