"""Strict prompt-only zero-model serial-frame emitter; experimental, not adopted.

Inputs are complete prompt/interface strings only. This component handles an
explicit start0, binary LSB-first payload and stop1 protocol. It does not handle
parity, asynchronous reset, shortened framing or added obligations. Construction
and pure checks do not prove native/official correctness.
"""
import hashlib
import json
import re
from reserved_keywords import KEYWORDS

SCHEMA = 'serial_framing_prompt_only_draft_v1'
HEADER = re.compile(r'\AI would like you to implement a module named TopModule with the following\s+interface\. All input and output ports are one bit unless otherwise\s+specified\.\s*', re.S)
PORT = re.compile(r'-\s+(input|output)\s+([A-Za-z_][A-Za-z_0-9]*)\s*(?:\((\d+) bits\))?')

def digest(b):
    return hashlib.sha256(b).hexdigest()

def normalized(text):
    return ' '.join(text.split())

def body_template(width, data=False, data_name='out_byte', done_name='done', word='byte'):
    """Finite protocol grammar; roles/counts are parameters, never task identity."""
    prefix = ('In many (older) serial communications protocols, each data '+word+
              ' is sent along with a start bit and a stop bit, to help the receiver delimit '+word+'s '
              'from the stream of bits. One common scheme is to use one start bit (0), '+str(width)+
              ' data bits, and 1 stop bit (1). The line is also at logic 1 when nothing '
              'is being transmitted (idle).')
    if data:
        middle = (' Design a finite state machine that will identify when '+word+'s have been correctly received '
                  'when given a stream of bits. It needs to identify the start bit, wait for all '+str(width)+
                  ' data bits, then verify that the stop bit was correct. The module will also output the '
                  'correctly-received data '+word+'. `'+data_name+'` needs to be valid when `'+done_name+
                  '` is 1, and is don\'t-care otherwise.')
    else:
        middle = (' Implement a finite state machine that will identify when '+word+'s have been correctly '
                  'received when given a stream of bits. It needs to identify the start bit, wait for all '+str(width)+
                  ' data bits, then verify that the stop bit was correct.')
    suffix = (' If the stop bit does not appear when expected, the FSM must wait until it finds a stop bit '
              'before attempting to receive the next '+word+'. Include a active-high synchronous reset. '
              'Note that the serial protocol sends the least significant bit first.')
    if data:
        suffix += ' It should assert '+done_name+' each time it finds a stop bit.'
    return prefix+middle+suffix+' Assume all sequential logic is triggered on the positive edge of the clock.'

class Abstain(ValueError):
    pass

def require(condition, reason):
    if not condition:
        raise Abstain(reason)

def split_prompt(prompt):
    text=prompt.replace('\r\n','\n').replace('\r','\n')
    header=HEADER.match(text)
    require(header is not None,'missing_exact_interface_header')
    lines=text[header.end():].splitlines();ports=[]
    for index,line in enumerate(lines):
        if not line.strip():
            continue
        port=PORT.fullmatch(line.strip())
        if port is None:
            require(bool(ports),'missing_ports')
            return ports,normalized('\n'.join(lines[index:]))
        raw_width=port[3] or '1'
        require(re.fullmatch(r'(?:[1-9]|1[0-6])',raw_width) is not None,'port_width_must_be_ascii_1_to_16')
        ports.append(dict(direction=port[1],name=port[2],width=int(raw_width)))
    raise Abstain('missing_protocol_body')

def synthesize(prompt,interface=''):
    result=dict(schema=SCHEMA,emitted=False,reason=None,rtl='',actual_model_requests=0,actual_eda_calls=0,
                external_io_calls=0,native_qualified=False,formal_qualification=False)
    if not isinstance(prompt,str) or not isinstance(interface,str):
        return result|dict(reason='inputs_must_be_strings')
    try:
        result.update(prompt_sha256=digest(prompt.encode()),interface_sha256=digest(interface.encode()))
    except UnicodeEncodeError:
        return result|dict(reason='unsupported_encoding')
    if interface.strip():
        return result|dict(reason='separate_interface_unsupported')
    try:
        ports,body=split_prompt(prompt)
        require(len({p['name'] for p in ports})==len(ports),'duplicate_port')
        require(all(p['name'] not in KEYWORDS and 1<=p['width']<=16 for p in ports),'reserved_or_bad_width')
        inputs=[p for p in ports if p['direction']=='input'];outputs=[p for p in ports if p['direction']=='output']
        require(len(inputs)==3 and all(p['width']==1 for p in inputs),'requires_three_scalar_inputs')
        clocks=[p for p in inputs if p['name'] in ('clk','clock')]
        resets=[p for p in inputs if p['name'] in ('reset','rst')]
        require(len(clocks)==len(resets)==1,'unambiguous_clock_reset_roles_required')
        clock=clocks[0]['name'];reset=resets[0]['name'];bit=[p['name'] for p in inputs if p not in clocks+resets]
        require(len(bit)==1,'missing_serial_input')
        scalar=[p for p in outputs if p['width']==1];data=[p for p in outputs if p['width']>1]
        require(len(scalar)==1 and len(data)<=1 and len(outputs)==1+len(data),'output_roles_not_exact')
        done=scalar[0]['name'];width=data[0]['width'] if data else None
        matches=[]
        for n in ([width] if width is not None else range(2,17)):
            for word in ('byte','word'):
                if word=='byte' and n!=8:
                    continue
                template=body_template(n,bool(data),data[0]['name'] if data else '',done,word)
                if body==template or body==template.replace('Include a active-high','Include an active-high'):
                    matches.append((n,word))
        require(len(matches)==1,'protocol_not_fully_consumed_or_unsupported')
        n,word=matches[0];idx_width=(n-1).bit_length()
        contract=dict(family='start_stop_serial_framing',ports=ports,clock=clock,reset=reset,serial_input=bit[0],
                      done_output=done,data_output=data[0]['name'] if data else None,payload_bits=n,
                      start_bit=0,stop_bit=1,idle_bit=1,lsb_first=True,reset_kind='active_high_synchronous',
                      clock_edge='positive',invalid_stop='discard_frame_wait_high_then_rearm',
                      done='one_cycle_after_valid_stop_sample',data_care='when_done_only' if data else None,
                      all_prompt_consumed=True,word_label=word)
        decl=[]
        for p in ports:
            bus='' if p['width']==1 else '['+str(p['width']-1)+':0] '
            decl.append('    '+('input' if p['direction']=='input' else 'output reg')+' '+bus+p['name'])
        rtl='module TopModule (\n'+',\n'.join(decl)+'\n);\n'
        rtl+='    localparam _sf_IDLE=2\'d0, _sf_DATA=2\'d1, _sf_STOP=2\'d2, _sf_WAIT=2\'d3;\n'
        require(not any(p['name'].startswith('_sf_') for p in ports),'internal_name_collision')
        rtl+='    reg [1:0] _sf_state;\n    reg ['+str(idx_width-1)+':0] _sf_index;\n'
        if data:
            rtl+='    reg ['+str(n-1)+':0] _sf_buffer;\n'
        rtl+='    always @(posedge '+clock+') begin\n        if ('+reset+') begin\n'
        rtl+='            _sf_state <= _sf_IDLE; _sf_index <= 0; '+done+' <= 1\'b0;\n'
        if data:
            rtl+='            _sf_buffer <= 0; '+data[0]['name']+' <= 0;\n'
        rtl+='        end else begin\n            '+done+' <= 1\'b0;\n            case (_sf_state)\n'
        rtl+='                _sf_IDLE: if (!'+bit[0]+') begin _sf_state <= _sf_DATA; _sf_index <= 0; end\n'
        rtl+='                _sf_DATA: begin\n'
        if data:
            rtl+='                    _sf_buffer[_sf_index] <= '+bit[0]+';\n'
        rtl+='                    if (_sf_index == '+str(n-1)+') _sf_state <= _sf_STOP;\n'
        rtl+='                    else _sf_index <= _sf_index + 1\'b1;\n                end\n'
        rtl+='                _sf_STOP: begin\n                    if ('+bit[0]+') begin\n'
        rtl+='                        '+done+' <= 1\'b1; _sf_state <= _sf_IDLE;\n'
        if data:
            rtl+='                        '+data[0]['name']+' <= _sf_buffer;\n'
        rtl+='                    end else _sf_state <= _sf_WAIT;\n                end\n'
        rtl+='                _sf_WAIT: if ('+bit[0]+') _sf_state <= _sf_IDLE;\n'
        rtl+='                default: begin _sf_state <= _sf_IDLE; _sf_index <= 0; end\n'
        rtl+='            endcase\n        end\n    end\nendmodule\n'
        return result|dict(emitted=True,rtl=rtl,rtl_sha256=digest(rtl.encode()),contract=contract,
                           contract_sha256=digest(json.dumps(contract,sort_keys=True,separators=(',',':')).encode()),
                           all_prompt_consumed=True,limits=['Pure emission only; native positive/mutant protocol qualification and same-budget C/P screening still required.',
                           'No native binary, X/Z, arbitrary-parameter, hidden/generalization or score claim.'])
    except Abstain as error:
        return result|dict(reason=str(error))
