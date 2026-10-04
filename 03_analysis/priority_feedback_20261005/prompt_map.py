"""Complete textual LSB-priority contracts; emits checks, never DUT answers."""
import hashlib
import math
import re


def parse(prompt):
    identity=hashlib.sha256(prompt.encode('utf-8')).hexdigest()
    def reject(reason):return dict(status='abstain',reason=reason,prompt_sha256=identity)
    if not re.search(r'\bpriority encoder\b',prompt,re.I):
        return dict(status='skip',reason='no_explicit_priority_encoder',prompt_sha256=identity)
    declarations=re.findall(r'^\s*-\s*(input|output)\s+(.+?)\s*$',prompt,re.M)
    if len(declarations)!=2:return reject('incomplete_single_vector_interface')
    ports={}
    for direction,declaration in declarations:
        match=re.fullmatch(r'([A-Za-z][A-Za-z0-9_]{0,31})\s*\(\s*(\d+)\s+bits\s*\)',declaration)
        if not match or direction in ports:return reject('unsupported_port_declaration')
        name,width=match.group(1),int(match.group(2))
        if name.lower() in {'input','output','reg','wire','logic','module','endmodule','assign','always','begin','end','integer','case','default'}:
            return reject('reserved_port_name')
        ports[direction]=(name,width)
    if set(ports)!={'input','output'} or ports['input'][0]==ports['output'][0]:return reject('ambiguous_interface')
    signal,width=ports['input'];output,out_width=ports['output']
    if not 2<=width<=8 or out_width!=math.ceil(math.log2(width)):return reject('unsupported_exact_widths')
    prose=re.sub(r'^\s*-\s*(?:input|output)\s+.+?\s*$','',prompt,flags=re.M)
    prose=' '.join(prose.split())
    introduction='I would like you to implement a module named TopModule with the following interface. All input and output ports are one bit unless otherwise specified.'
    if prose.lower().startswith(introduction.lower()):prose=prose[len(introduction):].strip()
    example=(r"For example, (?:(?:the input )|(?:a(?:n)? (?P<description_width>\d+)-bit priority encoder given the input ))"
             r"(?P<example_width>\d+)'b(?P<bits>[01]+) (?:should |would )output (?P<position_width>\d+)'d(?P<position>\d+), "
             r"because bit\[(?P<explained_position>\d+)\] is first bit that is high\.")
    explicit=(r'The module should implement a priority encoder for an (?P<width>\d+)-bit input\. '
        r'Given an (?P<vector_width>\d+)-bit vector, the output should report the first \(least significant\) bit in the vector that is 1\. '
        r'Report zero if the input vector has no bits that are high\. '+example)
    illustrated=(r'The module should implement a priority encoder\. A priority encoder is a combinational circuit that, '
        r'when given an input bit vector, outputs the position of the first 1 bit in the vector\. '+example+
        r' Build a (?P<width>\d+)-bit priority encoder\. For this problem, if none of the input bits are high '
        r'\(i\.e\., input is zero\), output zero\. Note that a (?P<note_width>\d+)-bit number has (?P<combinations>\d+) possible combinations\.')
    match=re.fullmatch(explicit,prose,re.I)
    form='explicit_lsb'
    if not match:match=re.fullmatch(illustrated,prose,re.I);form='example_disambiguated_lsb'
    if not match:return reject('unsupported_complete_priority_prose')
    groups=match.groupdict()
    if int(groups['width'])!=width:return reject('interface_and_body_width_disagree')
    if groups.get('vector_width') and int(groups['vector_width'])!=width:return reject('vector_width_disagree')
    if groups.get('note_width') and (int(groups['note_width'])!=width or int(groups['combinations'])!=2**width):return reject('declared_domain_disagree')
    example_width=int(groups['example_width']);bits=groups['bits'];position=int(groups['position'])
    if not 2<=example_width<=64 or len(bits)!=example_width:return reject('unsupported_complete_example')
    if int(groups['position_width'])!=math.ceil(math.log2(example_width)):return reject('example_result_width_disagree')
    if groups.get('description_width') and int(groups['description_width'])!=example_width:return reject('example_description_disagree')
    value=int(bits,2)
    if not value or position!=int(groups['explained_position']):return reject('inconsistent_example')
    lowest=(value&-value).bit_length()-1;highest=value.bit_length()-1
    if position!=lowest:return reject('example_does_not_match_lsb_priority')
    if form=='example_disambiguated_lsb' and lowest==highest:return reject('single_hot_example_does_not_disambiguate_direction')
    if form=='explicit_lsb' and example_width!=width:return reject('example_not_same_declared_width')
    cases=[dict(inputs={signal:v},expected=0 if v==0 else (v&-v).bit_length()-1) for v in range(2**width)]
    return dict(status='supported',prompt_sha256=identity,input=signal,output=output,
        input_width=width,output_width=out_width,checks=len(cases),cases=cases,
        scope='Complete bounded LSB-priority prose; exhaustive two-state vector input, zero returns zero')


def render_tb(contract,task):
    assert contract['status']=='supported' and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,40}',task)
    signal,out=contract['input'],contract['output'];width=contract['input_width'];ow=contract['output_width']
    lines=['`timescale 1ns/1ps','module R2Probe;',
        f'reg [{width-1}:0] {signal}; wire [{ow-1}:0] {out};',
        f'TopModule _prioritycheck_dut(.{signal}({signal}),.{out}({out}));',
        'integer _prioritycheck_checks=0,_prioritycheck_mismatches=0;','initial begin']
    for case in contract['cases']:
        value=case['inputs'][signal];expected=case['expected']
        lines.extend([f"{signal}={width}'d{value}; #1; _prioritycheck_checks=_prioritycheck_checks+1;",
            f"if({out} !== {ow}'d{expected}) begin",
            f'if(_prioritycheck_mismatches==0) $display("PRIORITY_FIRST value={value} expected={expected} observed=%0d",{out});',
            '_prioritycheck_mismatches=_prioritycheck_mismatches+1; end'])
    lines.extend([f'$display("R2_PROBE_RESULT task={task} checks=%0d mismatches=%0d",_prioritycheck_checks,_prioritycheck_mismatches);',
        f'if(_prioritycheck_checks!={contract["checks"]}) $fatal(1,"CHECK_COUNT_INVALID"); $finish; end',
        'initial begin #1000; $fatal(1,"WATCHDOG_EXPIRED"); end','endmodule',''])
    return '\n'.join(lines)


def counterexample(log,contract):
    matches=re.findall(r'^PRIORITY_FIRST value=(\d+) expected=(\d+) observed=(\d+|[xz])\s*$',log,re.M)
    if len(matches)!=1:raise ValueError('Missing or ambiguous priority counterexample')
    value,expected,observed=matches[0];value=int(value);expected=int(expected)
    rows=[c for c in contract['cases'] if c['inputs']=={contract['input']:value}]
    if len(rows)!=1 or rows[0]['expected']!=expected or observed==str(expected):raise ValueError('Counterexample contradicts contract')
    if observed.isdigit() and int(observed)>=2**contract['output_width']:raise ValueError('Observed value outside declared width')
    return dict(inputs={contract['input']:value},output=contract['output'],expected=expected,observed=observed)
