"""Complete vector edge-pulse prose; emits test/observed facts, never DUT answers."""
import hashlib,re
from reserved_keywords import KEYWORDS


def parse(prompt):
    identity=hashlib.sha256(prompt.encode()).hexdigest()
    def reject(reason):return dict(status='abstain',reason=reason,prompt_sha256=identity)
    if not re.search(r'\bdetect\b.*\bedge|\bpositive edge detection\b',prompt,re.I|re.S):return dict(status='skip',reason='no_edge_pulse_description',prompt_sha256=identity)
    declarations=re.findall(r'^\s*-\s*(input|output)\s+(.+?)\s*$',prompt,re.M)
    if len(declarations)!=3:return reject('incomplete_three_port_interface')
    ports=[]
    for direction,body in declarations:
        m=re.fullmatch(r'([A-Za-z][A-Za-z0-9_]{0,31})(?:\s*\(\s*(\d+)\s+bits\s*\))?',body)
        if not m or m[1] in KEYWORDS:return reject('unsupported_or_reserved_port')
        ports.append((direction,m[1],int(m[2]) if m[2] else 1,m[2] is not None))
    clocks=[p for p in ports if p[0]=='input' and not p[3] and p[1] in ['clk','clock']]
    data=[p for p in ports if p[0]=='input' and p[3]];output=[p for p in ports if p[0]=='output' and p[3]]
    if len(clocks)!=1 or len(data)!=1 or len(output)!=1 or len({p[1] for p in ports})!=3:return reject('ambiguous_roles')
    _,clk,_,_=clocks[0];_,signal,w,_=data[0];_,out,ow,_=output[0]
    if not 1<=w<=64 or ow!=w:return reject('exact_vector_widths_disagree')
    prose=re.sub(r'^\s*-\s*(?:input|output)\s+.+?\s*$','',prompt,flags=re.M);prose=' '.join(prose.split())
    intro='I would like you to implement a module named TopModule with the following interface. All input and output ports are one bit unless otherwise specified.'
    if prose.lower().startswith(intro.lower()):prose=prose[len(intro):].strip()
    any_edge=(r'Implement a module that for each bit in an (?P<w>\d+)-bit input vector, detect when the input signal changes from one clock cycle to the next \(detect any edge\)\. '
              r'The output bit of (?P<out>[A-Za-z][A-Za-z0-9_]{0,31}) should be set to 1 the cycle after the input bit has 0 to 1 or 1 to 0 transition occurs\. '
              r'Assume all sequential logic is triggered on the positive edge of the clock\.')
    rising=(r'The module should examine each bit in an (?P<w>\d+)-bit vector and detect when the input signal changes from 0 in one clock cycle to 1 the next '
            r'\(similar to positive edge detection\)\. The output bit should be set the cycle after a 0 to 1 transition occurs\.')
    m=re.fullmatch(any_edge,prose,re.I);kind='any';clock_edge='positive'
    if not m:m=re.fullmatch(rising,prose,re.I);kind='rising';clock_edge='unspecified_cycle'
    if not m:return reject('unsupported_complete_edge_prose')
    if int(m['w'])!=w:return reject('body_interface_width_disagree')
    if kind=='any' and m['out']!=out:return reject('case_sensitive_output_role_disagree')
    mask=2**w-1;alt=sum(1<<i for i in range(0,w,2))
    values=[0,0,0,mask,mask,0,alt,mask^alt,0]+[1<<i for i in range(w)]+[mask^(1<<i) for i in range(w)]+[mask,0,0]
    observations=[]
    def pulse(old,new):return old^new if kind=='any' else (mask^old)&new
    for i,v in enumerate(values):
        if i>=2:observations.append(dict(step=i,phase='stable',previous_input=values[i-1],older_input=values[i-2],input=v,expected=pulse(values[i-2],values[i-1])))
        if i>=1:
            for phase in (['positive','cycle'] if clock_edge=='positive' else ['cycle']):
                observations.append(dict(step=i,phase=phase,previous_input=values[i-1],older_input=values[i-2] if i>=2 else None,input=v,expected=pulse(values[i-1],v)))
    return dict(status='supported',prompt_sha256=identity,roles=dict(clock=clk,input=signal,output=out),width=w,kind=kind,clock_edge=clock_edge,
                steps=values,observations=observations,checks=len(observations),scope='Complete bounded edge-pulse prose; sampled transitions/holding, no reset or initial state invented')


def render_tb(c,task):
    assert c['status']=='supported' and re.fullmatch('[A-Za-z][A-Za-z0-9_]{0,40}',task)
    w=c['width'];r=c['roles'];clk,signal,out=[r[k] for k in ['clock','input','output']]
    lines=['`timescale 1ns/1ps','module R2Probe;',f'reg {clk}; reg [{w-1}:0] {signal}; wire [{w-1}:0] {out};',
           f'TopModule _edgecheck_dut(.{clk}({clk}),.{signal}({signal}),.{out}({out}));',
           'integer _edgecheck_checks=0,_edgecheck_mismatches=0;','initial begin',f'{clk}=0; {signal}=0; #1;']
    def check(i,phase):
        rows=[o for o in c['observations'] if o['step']==i and o['phase']==phase]
        if not rows:return
        assert len(rows)==1;e=rows[0]['expected']
        lines.extend(['_edgecheck_checks=_edgecheck_checks+1;',f"if({out} !== {w}'d{e}) begin",
                      f'if(_edgecheck_mismatches==0) $display("EDGE_FIRST step={i} phase={phase} expected={e:x} observed=%h",{out});',
                      '_edgecheck_mismatches=_edgecheck_mismatches+1; end'])
    for i,v in enumerate(c['steps']):
        lines.extend([f"{signal}={w}'d{v}; #1;"]);check(i,'stable')
        lines.append(f'{clk}=1; #1;');check(i,'positive')
        lines.append(f'{clk}=0; #1;');check(i,'cycle')
    lines.extend([f'$display("R2_PROBE_RESULT task={task} checks=%0d mismatches=%0d",_edgecheck_checks,_edgecheck_mismatches);',
                  f'if(_edgecheck_checks!={c["checks"]}) $fatal(1,"CHECK_COUNT_INVALID"); $finish; end',
                  'initial begin #10000; $fatal(1,"WATCHDOG_EXPIRED"); end','endmodule',''])
    return '\n'.join(lines)


def counterexample(log,c):
    matches=re.findall(r'^EDGE_FIRST step=(\d+) phase=(stable|positive|cycle) expected=([0-9a-f]+) observed=([0-9a-fxz]+)\s*$',log,re.M)
    if len(matches)!=1:raise ValueError('Missing or ambiguous edge counterexample')
    i,phase,e,observed=matches[0];rows=[r for r in c['observations'] if r['step']==int(i) and r['phase']==phase]
    if len(rows)!=1 or rows[0]['expected']!=int(e,16):raise ValueError('Counterexample contradicts contract')
    if len(observed)>(c['width']+3)//4:raise ValueError('Observed value outside declared width')
    if not re.search('[xz]',observed) and (int(observed,16)==int(e,16) or int(observed,16)>=2**c['width']):raise ValueError('No actual mismatch or invalid observed width')
    return dict(**rows[0],output=c['roles']['output'],observed_hex=observed)
