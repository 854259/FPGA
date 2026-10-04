"""Bounded arithmetic-shifter prose -> sampled cycle checks, never DUT answers."""
import hashlib
import re
import json
from pathlib import Path

# Digital keyword spellings from the pinned source recorded beside this file.
# Spellings are case-sensitive; upper-case ordinary identifiers remain valid.
SV_KEYWORDS = frozenset(json.loads(Path(__file__).with_name('SV_KEYWORDS_V12_0.json').read_text())['keywords'])


def parse(prompt):
    identity=hashlib.sha256(prompt.encode('utf-8')).hexdigest()
    def reject(reason):return dict(status='abstain',reason=reason,prompt_sha256=identity)
    if not re.search(r'\barithmetic shift register\b',prompt,re.I):
        return dict(status='skip',reason='no_arithmetic_shift_register',prompt_sha256=identity)
    declarations=re.findall(r'^\s*-\s*(input|output)\s+(.+?)\s*$',prompt,re.M)
    if len(declarations)!=6:return reject('incomplete_single_shifter_interface')
    ports={}
    for direction,declaration in declarations:
        m=re.fullmatch(r'([A-Za-z][A-Za-z0-9_]{0,31})(?:\s*\(\s*(\d+)\s+bits\s*\))?',declaration)
        if not m:return reject('unsupported_port_declaration')
        name=m.group(1);width=int(m.group(2) or 1)
        if name in ports or name in SV_KEYWORDS:
            return reject('ambiguous_or_reserved_port')
        ports[name]=(direction,width)
    prose=re.sub(r'^\s*-\s*(?:input|output)\s+.+?\s*$','',prompt,flags=re.M)
    prose=' '.join(prose.split())
    intro='I would like you to implement a module named TopModule with the following interface. All input and output ports are one bit unless otherwise specified.'
    if prose.lower().startswith(intro.lower()):prose=prose[len(intro):].strip()
    word=r'[A-Za-z][A-Za-z0-9_]{0,31}'
    grammar=(r'The module should implement a (?P<width>\d+)-bit arithmetic shift register, with synchronous load\. '
        r'The shifter can shift both left and right, and by 1 or 8 bit positions, selected by "(?P<amount>'+word+r')\." '
        r'Assume the right (?:shift|shit) is an arithmetic right shift\. Signals are defined as below: '
        r'\(1\) (?P<load>'+word+r'): Loads shift register with (?P<data>'+word+r')\[(?P<high>\d+):0\] instead of shifting\. Active high\. '
        r'\(2\) (?P<enable>'+word+r'): Chooses whether to shift\. Active high\. '
        r'\(3\) (?P<amount_again>'+word+r'): Chooses which direction and how much to shift\. '
        r"\(a\) 2'b00: shift left by 1 bit\. \(b\) 2'b01: shift left by 8 bits\. "
        r"\(c\) 2'b10: shift right by 1 bit\. \(d\) 2'b11: shift right by 8 bits\. "
        r'\(4\) (?P<output>'+word+r'): The contents of the shifter\.')
    m=re.fullmatch(grammar,prose,re.I)
    if not m:return reject('unsupported_complete_shifter_prose')
    g=m.groupdict();width=int(g['width'])
    if g['amount_again'] != g['amount']:return reject('case_ambiguous_amount_role')
    if not 8<=width<=64 or int(g['high'])!=width-1:return reject('unsupported_exact_width')
    roles={k:g[k] for k in ['load','enable','amount','data','output']}
    if len(set(roles.values()))!=5:return reject('ambiguous_signal_roles')
    required={roles['load']:('input',1),roles['enable']:('input',1),roles['amount']:('input',2),roles['data']:('input',width),roles['output']:('output',width)}
    remaining=set(ports)-set(required)
    if len(remaining)!=1:return reject('ambiguous_clock')
    clock=next(iter(remaining))
    if clock not in {'clk','clock'} or ports[clock]!=('input',1) or any(ports.get(n)!=v for n,v in required.items()):return reject('interface_role_width_disagree')
    roles['clock']=clock
    mask=(1<<width)-1;seeds=sorted({0,1,1<<(width-1),mask,(1<<(width-1))|1,int('10'*(width//2)+'1'*(width%2),2),int('01'*(width//2)+'0'*(width%2),2)})
    steps=[];observations=[];state=None
    for amount in range(4):
        for seed in seeds:
            drives=[(1,0,seed),(0,0,seed^mask),(0,1,seed^mask),(0,1,seed),(1,1,seed^mask),(0,0,seed)]
            for load,enable,data in drives:
                inputs={roles['load']:load,roles['enable']:enable,roles['amount']:amount,roles['data']:data}
                step=len(steps);previous=state
                if state is not None:observations.append(dict(step=step,phase='stable',expected=state,inputs=inputs,previous=state))
                if load:state=data
                elif enable:
                    count=1 if amount%2==0 else 8
                    if amount<2:state=(state<<count)&mask
                    else:
                        signed=state-(1<<width) if state&(1<<(width-1)) else state
                        state=(signed>>count)&mask
                steps.append(dict(inputs=inputs,expected=state,previous=previous))
                observations.append(dict(step=step,phase='cycle',expected=state,inputs=inputs,previous=previous))
    return dict(status='supported',prompt_sha256=identity,width=width,roles=roles,steps=steps,observations=observations,checks=len(observations),
        scope='Sampled boundary states and load/enable/hold/sign paths, not exhaustive state proof; stable-clock checks and full-cycle endpoints; unspecified edge polarity is not asserted')


def render_tb(contract,task):
    assert contract['status']=='supported' and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,40}',task)
    r=contract['roles'];w=contract['width']
    lines=['`timescale 1ns/1ps','module R2Probe;',
        f'reg {r["clock"]}=0,{r["load"]}=0,{r["enable"]}=0; reg [1:0] {r["amount"]}=0;',
        f'reg [{w-1}:0] {r["data"]}=0; wire [{w-1}:0] {r["output"]};',
        'TopModule _shiftcheck_dut('+','.join('.'+n+'('+n+')' for n in r.values())+');',
        'integer _shiftcheck_checks=0,_shiftcheck_mismatches=0;','initial begin']
    def check(step,phase,expected):
        return ['_shiftcheck_checks=_shiftcheck_checks+1;',f"if({r['output']} !== {w}'h{expected:x}) begin",
            f'if(_shiftcheck_mismatches==0) $display("SHIFT_FIRST step={step} phase={phase} expected={expected:x} observed=%h",{r["output"]});',
            '_shiftcheck_mismatches=_shiftcheck_mismatches+1; end']
    for i,step in enumerate(contract['steps']):
        for name,value in step['inputs'].items():
            bits=w if name==r['data'] else 2 if name==r['amount'] else 1
            lines.append(f"{name}={bits}'h{value:x};")
        lines.append('#1;')
        if step['previous'] is not None:lines.extend(check(i,'stable',step['previous']))
        lines.extend([r['clock']+'=1; #1;',r['clock']+'=0; #1;'])
        lines.extend(check(i,'cycle',step['expected']))
    lines.extend([f'$display("R2_PROBE_RESULT task={task} checks=%0d mismatches=%0d",_shiftcheck_checks,_shiftcheck_mismatches);',
        f'if(_shiftcheck_checks!={contract["checks"]}) $fatal(1,"CHECK_COUNT_INVALID"); $finish; end',
        'initial begin #2000; $fatal(1,"WATCHDOG_EXPIRED"); end','endmodule',''])
    return '\n'.join(lines)


def counterexample(log,contract):
    points=re.findall(r'^SHIFT_FIRST step=(\d+) phase=(stable|cycle) expected=([0-9a-f]+) observed=([0-9a-fxz]+)\s*$',log,re.M|re.I)
    if len(points)!=1:raise ValueError('Missing or ambiguous shifter counterexample')
    step,phase,expected,observed=points[0];step=int(step);phase=phase.lower();observed=observed.lower()
    rows=[r for r in contract['observations'] if r['step']==step and r['phase']==phase]
    if len(rows)!=1 or int(expected,16)!=rows[0]['expected']:raise ValueError('Counterexample contradicts contract')
    if len(observed)>(contract['width']+3)//4:raise ValueError('Observed value too wide')
    if not re.search('[xz]',observed) and (int(observed,16)>=2**contract['width'] or int(observed,16)==rows[0]['expected']):raise ValueError('Invalid mismatch')
    return dict(step=step,phase=phase,inputs=rows[0]['inputs'],previous=rows[0]['previous'],output=contract['roles']['output'],expected=rows[0]['expected'],observed_hex=observed)
