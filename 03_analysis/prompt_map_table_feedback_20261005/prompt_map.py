"""Narrow ASCII map contracts; abstain unless the whole prose grammar is known.

Isolated research copy of parser SHA63cbdeaa; never writes a DUT or a repair.
"""
import hashlib
import re


def parse(prompt):
    identity=hashlib.sha256(prompt.encode('utf-8')).hexdigest()
    def reject(reason):return dict(status='abstain',reason=reason,prompt_sha256=identity)
    markers=list(re.finditer(r'(?i)\bKarnaugh\s+map\b',prompt))
    if not markers:return dict(status='skip',reason='no_explicit_map',prompt_sha256=identity)
    if len(markers)!=1:return reject('multiple_maps')
    normalized=' '.join(prompt.split())
    if not re.search(r'(?i)\bmodule should implement (?:the circuit described by )?the Karnaugh map below\b',normalized):
        return reject('unsupported_map_relationship')
    if re.search(r'(?i)\b(?:clock|registered|register|latency|posedge|negedge|sequential|reset|enable|invert|inverted|complement|negate)\b|active[- ]low',prompt):
        return reject('additional_timing_or_output_semantics')
    declarations=re.findall(r'^\s*-\s*(input|output)\s+(.+?)\s*$',prompt,re.M)
    if not declarations:return reject('no_scalar_bullet_interface')
    inputs=[];outputs=[]
    for direction,name in declarations:
        pattern=r'[A-Za-z]' if direction=='input' else r'[A-Za-z][A-Za-z0-9_]{0,31}'
        if not re.fullmatch(pattern,name):return reject('unsupported_scalar_port_declaration')
        (inputs if direction=='input' else outputs).append(name)
    # Common public output 'out' is supported without allowing an arbitrary
    # fragment of RTL/prose to become generated testbench source.
    if not outputs:
        return reject('no_output')
    if len(outputs)!=1 or len(set(inputs+outputs))!=len(inputs)+1:return reject('ambiguous_interface')
    if not 2<=len(inputs)<=4:return reject('unsupported_input_count')
    lines=prompt[markers[0].end():].splitlines()
    first=next((i for i,line in enumerate(lines) if re.match(r'^\s*[01]+\s*\|',line)),None)
    if first is None or first<2:return reject('no_complete_table')
    # A complete table cannot override an extra requirement in the prose. Match
    # the entire supported preamble instead of adding more blacklist words.
    all_lines=prompt.splitlines()
    table_start=next(i for i,line in enumerate(all_lines) if re.match(r'^\s*[01]+\s*\|',line))
    preamble='\n'.join(all_lines[:table_start-2])
    preamble=re.sub(r'^\s*-\s*(?:input|output)\s+[A-Za-z][A-Za-z0-9_]{0,31}\s*$', '', preamble, flags=re.M)
    preamble=' '.join(preamble.split())
    introduction=re.escape('I would like you to implement a module named TopModule with the following interface. All input and output ports are one bit unless otherwise specified.')
    relationship=r'The module should implement (?:the circuit described by )?the Karnaugh map below\.'
    legend=r"(?: d is don['’]t[- ]care, which means you may choose (?:the output|to output whatever value is convenient)\.)?"
    if not re.fullmatch('(?:'+introduction+' )?'+relationship+legend,preamble,re.I):
        return reject('unsupported_complete_preamble')
    header=lines[first-1].split();column_names=lines[first-2].split()
    if len(column_names)!=1 or len(header)<3:return reject('ambiguous_axes')
    columns=column_names[0];rows=header[0];labels=header[1:]
    if not re.fullmatch(r'[A-Za-z]{1,2}',columns) or not re.fullmatch(r'[A-Za-z]{1,2}',rows):return reject('unsupported_axes')
    if len(set(columns+rows))!=len(inputs) or set(columns+rows)!=set(inputs):return reject('axes_do_not_match_ports')
    if len(labels)!=2**len(columns) or set(labels)!={format(i,f'0{len(columns)}b') for i in range(2**len(columns))}:return reject('incomplete_or_duplicate_columns')
    if not all(len(label)==len(columns) for label in labels):return reject('column_width')
    allow_dc=bool(re.search(r"(?i)\bd\s+is\s+don['’]t[- ]care\b",prompt))
    cases=[];seen=set();end=first
    while end<len(lines) and '|' in lines[end]:
        fields=[x.strip() for x in lines[end].split('|')]
        if len(fields)!=len(labels)+2 or fields[-1]:return reject('malformed_row')
        label=fields[0];values=fields[1:-1]
        if not re.fullmatch('[01]{'+str(len(rows))+'}',label) or label in seen:return reject('invalid_or_duplicate_rows')
        seen.add(label)
        for column,value in zip(labels,values):
            if value not in ('0','1') and not (value=='d' and allow_dc):return reject('unknown_cell_or_undeclared_dontcare')
            bits=dict(zip(rows+columns,map(int,label+column)))
            cases.append(dict(inputs={name:bits[name] for name in inputs},expected=None if value=='d' else int(value)))
        end+=1
    if seen!={format(i,f'0{len(rows)}b') for i in range(2**len(rows))}:return reject('incomplete_rows')
    if any(line.strip() for line in lines[end:]):return reject('extra_table_or_semantic_content')
    if len(cases)!=2**len(inputs):return reject('incomplete_input_domain')
    if {case['expected'] for case in cases if case['expected'] is not None}!={0,1}:return reject('constant_or_unconstrained_map_not_admitted')
    cases.sort(key=lambda case:tuple(case['inputs'][n] for n in inputs))
    return dict(status='supported',prompt_sha256=identity,inputs=inputs,output=outputs[0],
        checks=sum(c['expected'] is not None for c in cases),cases=cases,
        scope='Complete explicitly labelled ASCII map, scalar 2-4 inputs; two-state combinational care cells only')


def render_tb(contract,case_id):
    assert contract['status']=='supported'
    assert re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,40}',case_id)
    inputs=contract['inputs'];output=contract['output']
    declarations='reg '+','.join(inputs)+'; wire '+output+';'
    connections=','.join('.'+n+'('+n+')' for n in inputs+[output])
    lines=['`timescale 1ns/1ps','module R2Probe;',declarations,
        'TopModule _mapcheck_dut('+connections+');','integer _mapcheck_checks=0,_mapcheck_mismatches=0;','initial begin']
    for case in contract['cases']:
        lines.append(' '.join(n+"=1'b"+str(case['inputs'][n])+';' for n in inputs)+' #1;')
        if case['expected'] is None:continue
        assignments=','.join(n+'='+str(case['inputs'][n]) for n in inputs)
        expected=str(case['expected'])
        lines.append("_mapcheck_checks=_mapcheck_checks+1; if ("+output+" !== 1'b"+expected+") begin")
        lines.append('if(_mapcheck_mismatches==0) $display("MAP_FIRST inputs='+assignments+' expected='+expected+' observed=%b",'+output+');')
        lines.append('_mapcheck_mismatches=_mapcheck_mismatches+1;end')
    lines.extend(['$display("R2_PROBE_RESULT task='+case_id+' checks=%0d mismatches=%0d",_mapcheck_checks,_mapcheck_mismatches);',
        'if(_mapcheck_checks!='+str(contract['checks'])+') $fatal(1,"CHECK_COUNT_INVALID");$finish;end',
        'initial begin #1000;$fatal(1,"WATCHDOG_EXPIRED");end','endmodule',''])
    return '\n'.join(lines)


def counterexample(log,contract):
    """Validate a simulator's first-care-cell report before exposing feedback."""
    matches=re.findall(r'^MAP_FIRST inputs=([A-Za-z01=,]+) expected=([01]) observed=([01xz])\s*$',log,re.M)
    if len(matches)!=1:raise ValueError('Missing or ambiguous first counterexample')
    assignments,expected,observed=matches[0]
    pairs=assignments.split(',')
    if len(pairs)!=len(contract['inputs']):raise ValueError('Counterexample port count')
    bits={}
    for pair in pairs:
        if not re.fullmatch(r'[A-Za-z]=[01]',pair):raise ValueError('Invalid counterexample input')
        n,v=pair.split('=')
        if n in bits:raise ValueError('Duplicate counterexample port')
        bits[n]=int(v)
    if set(bits)!=set(contract['inputs']):raise ValueError('Counterexample interface mismatch')
    cases=[c for c in contract['cases'] if c['inputs']==bits]
    if len(cases)!=1 or cases[0]['expected']!=int(expected) or observed==expected:raise ValueError('Counterexample contradicts prompt contract')
    return dict(inputs=bits,output=contract['output'],expected=int(expected),observed=observed)
