"""Bounded complete combinational FSM prose/table; checks, never DUT answers."""
import hashlib
import itertools
import re
from reserved_keywords import KEYWORDS

IDENT = r'[A-Za-z][A-Za-z0-9_]{0,31}'
INTRO = 'I would like you to implement a module named TopModule with the following interface. All input and output ports are one bit unless otherwise specified.'

def parse(prompt):
    identity = hashlib.sha256(prompt.encode()).hexdigest()
    def no(reason): return dict(status='abstain', reason=reason, prompt_sha256=identity)
    if 'state machine' not in prompt or 'one-hot' not in prompt:
        return dict(status='skip', reason='no_onehot_fsm', prompt_sha256=identity)
    ports = []
    for direction, body in re.findall(r'^\s*-\s*(input|output)\s+(.+?)\s*$', prompt, re.M):
        m = re.fullmatch(r'('+IDENT+r')(?:\s*\(\s*(\d+)\s+bits\s*\))?', body)
        if not m or m[1] in KEYWORDS: return no('invalid_or_reserved_port')
        ports.append(dict(direction=direction, name=m[1], width=int(m[2]) if m[2] else 1, vector=m[2] is not None))
    if not ports or len({p['name'] for p in ports}) != len(ports): return no('duplicate_or_empty_interface')
    state = [p for p in ports if p['direction']=='input' and p['vector']]
    inputs = [p['name'] for p in ports if p['direction']=='input' and not p['vector']]
    output_ports = [p for p in ports if p['direction']=='output']
    if len(state)!=1 or not 2<=state[0]['width']<=12 or not 1<=len(inputs)<=3: return no('bounded_roles_or_width')
    n=state[0]['width']; state_name=state[0]['name']
    prose=re.sub(r'^\s*-\s*(?:input|output)\s+.+?\s*$','',prompt,flags=re.M)
    prose=' '.join(prose.split())
    if not prose.startswith(INTRO+' '): return no('complete_intro_missing')
    prose=prose[len(INTRO):].strip()
    transitions=[]; labels=[]; moore=[]; output_maps=[]
    vector_outputs=[p for p in output_ports if p['vector']]
    if vector_outputs:
        if len(vector_outputs)!=1 or vector_outputs[0]['width']!=n or len(inputs)!=1: return no('full_vector_roles')
        moore=[p['name'] for p in output_ports if not p['vector']]
        if not 1<=len(moore)<=4: return no('bounded_moore_outputs')
        next_name=vector_outputs[0]['name']
        prefix=f'Given the follow state machine with 1 input and {len(moore)} outputs (the outputs are given as "({", ".join(moore)})"):'
        if not prose.startswith(prefix+' '): return no('complete_full_prefix')
        tail=prose[len(prefix):].strip()
        label_match=re.match(r'([A-Za-z]{1,8})0 ',tail)
        if not label_match:return no('explicit_indexed_state_labels')
        label_prefix=label_match[1];labels=[label_prefix+str(i) for i in range(n)]
        suffix=(f'Suppose this state machine uses one-hot encoding, where {state_name}[0] through {state_name}[{n-1}] correspond to the states {labels[0]} though {labels[-1]}, respectively. '
                f'The outputs are zero unless otherwise specified. The {next_name}[0] through {next_name}[{n-1}] correspond to the transition to next states {labels[0]} though {labels[-1]}. '
                f'For example, The {next_name}[1] is set to 1 when the next state is {labels[1]} , otherwise, it is set to 0. '
                f'Here, the input {state_name}[{n-1}:0] can be a combinational of multiple states, and the TopModule is expected to response. For example: '
                f'When the {state_name}[{n-1}:0] = {n}\'b'+format((1<<2)|(1<<4),f'0{n}b')+f', {state_name}[4] == 1, and {state_name}[2] == 1, the states includes {label_prefix}4, and {label_prefix}2 states. '
                f'The module should implement the state transition logic and output logic portions of the state machine (but not the state flip-flops). '
                f'You are given the current state in {state_name}[{n-1}:0] and must implement {next_name}[{n-1}:0] and the '+('two outputs.' if len(moore)==2 else f'{len(moore)} outputs.'))
        # This exact complete form explicitly admits simultaneous active states.
        if n<5 or not tail.endswith(suffix):return no('complete_multistate_suffix')
        table=tail[:-len(suffix)].strip();row_pattern=re.compile(r'('+IDENT+r') \(([01](?:, [01])*)\) --([01])--> ('+IDENT+r')(?: |$)')
        pos=0;seen={};state_outputs={}
        while pos<len(table):
            m=row_pattern.match(table,pos)
            if not m:return no('unconsumed_full_table')
            a,outputs,v,b=m.groups();values=[int(x) for x in outputs.split(', ')]
            if a not in labels or b not in labels or len(values)!=len(moore):return no('unknown_state_or_output_width')
            if (a,v) in seen:return no('duplicate_transition')
            seen[a,v]=b
            if a in state_outputs and state_outputs[a]!=values:return no('inconsistent_moore_row')
            state_outputs[a]=values;transitions.append(dict(source=labels.index(a),target=labels.index(b),condition={inputs[0]:int(v)}));pos=m.end()
        if set(seen)!={(a,str(v)) for a in labels for v in [0,1]}:return no('incomplete_total_transition_table')
        state_outputs=[state_outputs[a] for a in labels]
        output_maps=[dict(name=p['name'],width=p['width'],kind='next_vector' if p['vector'] else 'moore',index=None if p['vector'] else moore.index(p['name'])) for p in output_ports]
        family='full_vector_multistate';domain=list(range(1<<n))
    else:
        if any(p['vector'] for p in output_ports):return no('partial_scalar_outputs_required')
        pattern=(r'The module should implement the following Moore state machine with (?P<ni>\d+) input \((?P<inputs>'+IDENT+r'(?:, '+IDENT+r')*)\) and (?P<no>\d+) outputs \((?P<moore>'+IDENT+r'(?:, '+IDENT+r')*)\)\. '
                 r'Unless otherwise stated in the diagram below, assume outputs are 0 and inputs are don\'t cares\. '
                 r'state \(output\) --input--> next state -+ (?P<table>.*?) '
                 r'At reset, the state machine starts in state "(?P<reset>'+IDENT+r')"\. Derive next-state logic equations and output logic equations by inspection assuming the following one-hot encoding is used: '
                 r'\((?P<labels>'+IDENT+r'(?:, '+IDENT+r')*)\) = \((?P<encoding>[^()]+)\) '
                 r'Derive state transition and output logic equations by inspection assuming a one-hot encoding\. '
                 r'Implement only the state transition logic and output logic \(the combinational logic portion\) for this state machine\. Write code that generates the following signals: (?P<signals>.+)')
        m=re.fullmatch(pattern,prose)
        if not m:return no('complete_partial_prose')
        if int(m['ni'])!=len(inputs) or m['inputs'].split(', ')!=inputs:return no('case_sensitive_input_roles')
        moore=m['moore'].split(', ');labels=m['labels'].split(', ')
        if int(m['no'])!=len(moore) or len(set(moore))!=len(moore) or any(x not in [p['name'] for p in output_ports] for x in moore):return no('unknown_or_duplicate_output_roles')
        if len(labels)!=n or len(set(labels))!=n or m['reset'] not in labels:return no('explicit_encoding_state_roles')
        codes=[s.strip() for s in m['encoding'].split(',')]
        if '...' in codes:
            if n<4 or len(codes)!=5 or codes[3]!='...':return no('unsupported_encoding_ellipsis')
            wanted=[1,2,4,1<<(n-1)];codes=codes[:3]+codes[4:]
        else:wanted=[1<<i for i in range(n)]
        parsed=[re.fullmatch(r'(\d+)\'b([01]+)',s) for s in codes]
        if len(parsed)!=len(wanted) or any(not q or int(q[1])!=n or len(q[2])!=n or int(q[2],2)!=v for q,v in zip(parsed,wanted)):return no('onehot_encoding_not_exact')
        sig_pattern=re.compile(r'- ('+IDENT+r') -- (?:Assert when next-state is ('+IDENT+r') state|(output logic))(?: |$)')
        pos=0;maps={}
        while pos<len(m['signals']):
            q=sig_pattern.match(m['signals'],pos)
            if not q:return no('unconsumed_output_description')
            name,target,_=q.groups()
            if name in maps or name not in [p['name'] for p in output_ports]:return no('duplicate_or_unknown_output_mapping')
            if target:
                if name in moore or target not in labels:return no('ambiguous_next_output_mapping')
                maps[name]=dict(name=name,width=1,kind='next_bit',index=labels.index(target))
            else:
                if name not in moore:return no('unspecified_moore_output')
                maps[name]=dict(name=name,width=1,kind='moore',index=moore.index(name))
            pos=q.end()
        if set(maps)!={p['name'] for p in output_ports}:return no('incomplete_output_mapping')
        output_maps=[maps[p['name']] for p in output_ports]
        row_pattern=re.compile(r'('+IDENT+r') \(([^()]*)\) --(\(always go to next cycle\)|'+IDENT+r'=[01])--> ('+IDENT+r')(?: |$)')
        pos=0;state_outputs={}
        while pos<len(m['table']):
            q=row_pattern.match(m['table'],pos)
            if not q:return no('unconsumed_partial_table')
            a,output_text,condition,b=q.groups()
            if a not in labels or b not in labels:return no('unknown_transition_state')
            values=[0]*len(moore);seen=set()
            for term in (output_text.split(', ') if output_text else []):
                out=re.fullmatch(r'('+IDENT+r')=1',term)
                if not out or out[1] not in moore or out[1] in seen:return no('unsupported_moore_assignment')
                seen.add(out[1]);values[moore.index(out[1])]=1
            if a in state_outputs and state_outputs[a]!=values:return no('inconsistent_moore_row')
            state_outputs[a]=values
            cond={}
            if condition!='(always go to next cycle)':
                name,v=condition.split('=')
                if name not in inputs:return no('unknown_case_sensitive_condition_input')
                cond={name:int(v)}
            transitions.append(dict(source=labels.index(a),target=labels.index(b),condition=cond));pos=q.end()
        if set(state_outputs)!=set(labels):return no('missing_state')
        state_outputs=[state_outputs[a] for a in labels]
        family='partial_scalar_onehot';domain=[1<<i for i in range(n)]
    for source in range(n):
        for values in itertools.product([0,1],repeat=len(inputs)):
            bits=dict(zip(inputs,values))
            if sum(t['source']==source and all(bits[k]==v for k,v in t['condition'].items()) for t in transitions)!=1:return no('overlapping_or_incomplete_conditions')
    c=dict(status='supported',prompt_sha256=identity,family=family,ports=ports,state_name=state_name,width=n,
           input_names=inputs,states=labels,transitions=transitions,moore_names=moore,state_outputs=state_outputs,output_maps=output_maps,
           scope='Complete combinational FSM table; explicit multistate union only in vector form, one-hot domain only otherwise; no flip-flops or reset invented')
    observations=[]
    for state_value in domain:
        for values in itertools.product([0,1],repeat=len(inputs)):
            bits=dict(zip(inputs,values));targets=set();outs=[0]*len(moore)
            for index in range(n):
                if not state_value>>index&1:continue
                for t in transitions:
                    if t['source']==index and all(bits[k]==v for k,v in t['condition'].items()):targets.add(t['target'])
                outs=[a|b for a,b in zip(outs,state_outputs[index])]
            nv=sum(1<<i for i in targets);expected=0
            for spec in output_maps:
                value=nv if spec['kind']=='next_vector' else (nv>>spec['index']&1 if spec['kind']=='next_bit' else outs[spec['index']])
                expected=expected<<spec['width']|value
            observations.append(dict(case=len(observations),state=state_value,inputs=bits,expected=expected))
    c.update(observations=observations,checks=len(observations),output_width=sum(p['width'] for p in output_maps))
    return c

def render_tb(c,task):
    assert c['status']=='supported' and re.fullmatch(IDENT,task)
    declarations=[('reg' if p['direction']=='input' else 'wire')+(' ['+str(p['width']-1)+':0]' if p['vector'] else '')+' '+p['name']+';' for p in c['ports']]
    packed='{'+','.join(p['name'] for p in c['output_maps'])+'}'
    lines=['`timescale 1ns/1ps','module R2Probe;',*declarations,
           'TopModule _fsmcheck_dut('+','.join('.'+p['name']+'('+p['name']+')' for p in c['ports'])+');',
           'integer _fsmcheck_checks=0,_fsmcheck_mismatches=0;','initial begin']
    for o in c['observations']:
        input_bits=''.join(str(o['inputs'][k]) for k in c['input_names'])
        lines += [f'{c["state_name"]}={c["width"]}\'d{o["state"]};']+[f'{k}=1\'b{v};' for k,v in o['inputs'].items()]+['#1;',
          '_fsmcheck_checks=_fsmcheck_checks+1;',f'if({packed} !== {c["output_width"]}\'d{o["expected"]}) begin',
          f'if(_fsmcheck_mismatches==0) $display("FSM_FIRST case={o["case"]} state={o["state"]:x} inputs={input_bits} expected={o["expected"]:x} observed=%h",{packed});',
          '_fsmcheck_mismatches=_fsmcheck_mismatches+1; end']
    lines += [f'$display("R2_PROBE_RESULT task={task} checks=%0d mismatches=%0d",_fsmcheck_checks,_fsmcheck_mismatches);',
              f'if(_fsmcheck_checks!={c["checks"]}) $fatal(1,"CHECK_COUNT_INVALID"); $finish; end',
              'initial begin #20000; $fatal(1,"WATCHDOG_EXPIRED"); end','endmodule','']
    return '\n'.join(lines)

def counterexample(log,c):
    matches=re.findall(r'^FSM_FIRST case=(\d+) state=([0-9a-f]+) inputs=([01]+) expected=([0-9a-f]+) observed=([0-9a-fxz]+)\s*$',log,re.M)
    if len(matches)!=1:raise ValueError('Missing or ambiguous FSM point')
    index,state,inputs,expected,observed=matches[0]
    if int(index)>=len(c['observations']):raise ValueError('Invalid observation index')
    o=c['observations'][int(index)]
    if int(state,16)!=o['state'] or inputs!=''.join(str(o['inputs'][k]) for k in c['input_names']) or int(expected,16)!=o['expected']:raise ValueError('Point contradicts contract')
    if len(observed)>(c['output_width']+3)//4:raise ValueError('Observed outside declared width')
    if not re.search('[xz]',observed) and (int(observed,16)==o['expected'] or int(observed,16)>=1<<c['output_width']):raise ValueError('No mismatch or value overflow')
    return dict(**o,observed_hex=observed,output_maps=c['output_maps'])
