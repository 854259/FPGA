"""Conservative prompt-derived clarification; no task IDs, RTL emission, I/O or evaluation inputs."""
import re

IDENT=r'[A-Za-z_][A-Za-z0-9_]*'

def parse(prompt):
    def reject(reason):return dict(status='unsupported',reason=reason)
    if not isinstance(prompt,str) or not 1<=len(prompt)<=12000:return reject('input_scope')
    text=re.sub(r'\s+',' ',prompt).strip();low=text.lower()
    if any(re.search(p,low) for p in (r'\bfibonacci\b',r'\basynchronous\b',r'\bactive[- ]low\b',r'\bnegative edge\b',r'\bnegedge\b',r'\bshift(?:s|ing)? left\b',r'\benable\b',r'\bdiagram\b')):return reject('additional_or_conflicting_behavior')
    modules=re.findall(r'implement a module named ('+IDENT+r')\b',text,re.I)
    if len(modules)!=1:return reject('module_interface')
    ports=[]
    for line in prompt.splitlines():
        if not line.lstrip().startswith('-'):continue
        m=re.fullmatch(r'\s*-\s*(input|output)\s+('+IDENT+r')(?:\s+\((\d+)\s+bits?\))?\s*',line,re.I)
        if not m:return reject('module_interface')
        ports.append((m[1].lower(),m[2],int(m[3]) if m[3] else 1))
    if len(ports)!=3 or len({p[1] for p in ports})!=3:return reject('module_interface')
    outs=[p for p in ports if p[0]=='output'];ins=[p for p in ports if p[0]=='input']
    if len(outs)!=1 or len(ins)!=2 or any(p[2]!=1 for p in ins):return reject('module_interface')
    clocks=[p[1] for p in ins if p[1].lower() in ('clk','clock')]
    resets=[p[1] for p in ins if p[1].lower() in ('reset','rst')]
    if len(clocks)!=1 or len(resets)!=1:return reject('clock_reset_binding')
    width_matches=re.findall(r'implement (?:a|an) (\d+)-bit (?:maximal-length |maximum-length )?Galois LFSR\b',text,re.I)
    if len(width_matches)!=1:return reject('width_definition')
    width=int(width_matches[0]);output=outs[0][1]
    if not 2<=width<=64 or outs[0][2]!=width:return reject('width_interface_mismatch')
    if not re.search(r'\bGalois LFSR\b',text,re.I) or not re.search(r'\bshifts right\b',text,re.I):return reject('right_shift_definition')
    lsb=r'LSB output bit\s*\(\s*'+re.escape(output)+r'\[0\]\s*\)'
    if not re.search(r'(?:a |the )?["\u201c]?tap["\u201d]?\s+is XORed with the '+lsb+r' to produce its next value',text,re.I):return reject('feedback_definition')
    if not re.search(r'bit positions without a tap shift right unchanged',text,re.I):return reject('untapped_definition')
    tap_matches=re.findall(r'with taps at bit positions ([\d,\s]+(?:and\s+\d+)?)\.',text,re.I)
    if len(tap_matches)!=1:return reject('tap_definition')
    tap_text=tap_matches[0];tokens=[x for x in re.split(r'\s*(?:,|\band\b)\s*',tap_text,flags=re.I) if x]
    if not tokens or any(not re.fullmatch(r'\d+',t) for t in tokens):return reject('tap_definition')
    taps=[int(t) for t in tokens]
    if len(taps)!=len(set(taps)) or any(not 1<=t<=width for t in taps) or width not in taps:return reject('tap_range_or_convention')
    if not re.search(r'active[- ]high synchronous|synchronous active[- ]high',text,re.I):return reject('reset_timing')
    if not re.search(r'all sequential logic is triggered on the positive edge of the clock',text,re.I):return reject('clock_timing')
    literal=r"(?:\d+'[hHbBdD][0-9a-fA-F_]+|\d+)"
    reset_targets=(r'the output '+re.escape(output),r'the LFSR output',r'the LFSR output '+re.escape(output))
    seeds=[]
    for target in reset_targets:seeds.extend(re.findall(r'\breset '+target+r' to ('+literal+r')\.',text,re.I))
    if len(seeds)!=1:return reject('reset_seed')
    value=seeds[0]
    if "'" in value:
        m=re.fullmatch(r"(\d+)'([hHbBdD])([0-9a-fA-F_]+)",value)
        if not m or int(m[1])!=width:return reject('seed_width')
        try:seed=int(m[3].replace('_',''),dict(h=16,b=2,d=10)[m[2].lower()])
        except ValueError:return reject('seed_literal')
    else:seed=int(value)
    if not 0<=seed<(1<<width) or seed==0:return reject('seed_range')
    return dict(status='supported',family='explicit_right_galois',module=modules[0],clock=clocks[0],reset=resets[0],output=output,width=width,taps=taps,seed=seed,tap_mask=sum(1<<(t-1) for t in taps),input_basis='explicit prompt/interface only')

def clarify(contract):
    if contract.get('status')!='supported':return ''
    width=contract['width'];out=contract['output'];tap_positions=', '.join(map(str,contract['taps']))
    return ('Prompt-derived transition clarification (no extra behavior): '
        f'Use the old {width}-bit {out} state for every next-state bit. Right shift means old bit i+1 moves to destination bit i, with zero entering the MSB. '
        f'The stated one-based tap positions are {tap_positions}; XOR the old LSB into each tapped destination after this right shift. '
        f'Equivalently next_state = (old_state >> 1) XOR (old_LSB ? tap_mask : 0), where tap_mask sets bit p-1 for each listed position p. '
        f'On the positive clock edge, active-high synchronous {contract["reset"]} has priority and loads {contract["seed"]}; otherwise use that next_state. '
        'This is Galois feedback, not an XOR reduction of the tapped source bits.')
