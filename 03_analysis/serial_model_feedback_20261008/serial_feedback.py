"""Prompt-derived serial testbench/feedback only; this module never emits a DUT.

Finite binary traces are diagnostics, not exhaustive protocol correctness.
Runtime/EDA execution is AMD-only, through the existing paired oracle.
"""
import hashlib
import re
from pathlib import Path

from reserved_keywords import KEYWORDS

HEADER = re.compile(r'\AI would like you to implement a module named TopModule with the following\s+interface\. All input and output ports are one bit unless otherwise\s+specified\.\s*', re.S)
PORT = re.compile(r'-\s+(input|output)\s+([A-Za-z_][A-Za-z_0-9]*)\s*(?:\((\d+) bits\))?')
LABEL = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,80}')


def body_template(width, data=False, data_name='out_byte', done_name='done', word='byte'):
    """Complete finite prose grammar copied from the prior parser, not its emitter."""
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


def parse(prompt):
    """Abstain unless the entire prompt gives this exact, unambiguous contract."""
    if not isinstance(prompt, str):
        return None
    try:
        prompt_sha = hashlib.sha256(prompt.encode('utf-8')).hexdigest()
    except UnicodeEncodeError:
        return None
    text = prompt.replace('\r\n', '\n').replace('\r', '\n')
    header = HEADER.match(text)
    if header is None:
        return None
    lines = text[header.end():].splitlines()
    ports, body = [], None
    for index, line in enumerate(lines):
        if not line.strip():
            continue
        port = PORT.fullmatch(line.strip())
        if port is None:
            body = ' '.join('\n'.join(lines[index:]).split())
            break
        raw_width = port[3] or '1'
        if re.fullmatch(r'(?:[1-9]|1[0-6])', raw_width) is None:
            return None
        ports.append(dict(direction=port[1], name=port[2], width=int(raw_width)))
    if not ports or body is None or len({p['name'] for p in ports}) != len(ports):
        return None
    if any(p['name'] in KEYWORDS for p in ports):
        return None
    inputs = [p for p in ports if p['direction'] == 'input']
    outputs = [p for p in ports if p['direction'] == 'output']
    if len(inputs) != 3 or any(p['width'] != 1 for p in inputs):
        return None
    clocks = [p for p in inputs if p['name'] in ('clk', 'clock')]
    resets = [p for p in inputs if p['name'] in ('reset', 'rst')]
    if len(clocks) != 1 or len(resets) != 1:
        return None
    serial = [p for p in inputs if p not in clocks + resets]
    scalar = [p for p in outputs if p['width'] == 1]
    data = [p for p in outputs if p['width'] > 1]
    if len(serial) != 1 or len(scalar) != 1 or len(data) > 1 or len(outputs) != 1 + len(data):
        return None
    done = scalar[0]['name']
    matches = []
    for n in ([data[0]['width']] if data else range(2, 17)):
        for word in ('byte', 'word'):
            if word == 'byte' and n != 8:
                continue
            template = body_template(n, bool(data), data[0]['name'] if data else '', done, word)
            if body in (template, template.replace('Include a active-high', 'Include an active-high')):
                matches.append((n, word))
    if len(matches) != 1:
        return None
    contract = dict(ports=ports, clock=clocks[0]['name'], reset=resets[0]['name'],
                    serial_input=serial[0]['name'], done_output=done,
                    data_output=data[0]['name'] if data else None,
                    payload_bits=matches[0][0], all_prompt_consumed=True,
                    start_bit=0, stop_bit=1, idle_bit=1, lsb_first=True,
                    reset_kind='active_high_synchronous', clock_edge='positive',
                    invalid_stop='discard_frame_wait_high_then_rearm',
                    observation='after_positive_edge_and_nonblocking_updates',
                    done='one_cycle_pulse_after_sampling_the_expected_valid_stop',
                    data_care='when_done_only' if data else None)
    rows = trace(contract)
    return dict(prompt_sha256=prompt_sha, contract=contract, rows=rows, checks=len(rows))


def trace(contract):
    """Stimulus and expected observations derived only from the parsed protocol."""
    n = contract['payload_bits']
    stimulus = []

    def add(reset, bit):
        stimulus.append((reset, bit))

    def frame(value, stop=1):
        add(0, 0)
        for index in range(n):
            add(0, (value >> index) & 1)
        add(0, stop)

    add(1, 1)
    add(1, 0)
    add(0, 1)
    add(0, 1)
    # Distinct non-palindromic values expose direction/position errors.
    mask = (1 << n) - 1
    for value in (0, mask, 1, 1 << (n - 1), sum(1 << i for i in range(0, n, 2))):
        frame(value)  # No idle gap: valid stop can be followed by next start.
    add(0, 1)
    frame(1, stop=0)
    # A late high re-arms; it must not report the already-invalid frame.
    for _ in range(n + 2):
        add(0, 0)
    add(0, 1)
    frame(mask ^ 1)
    # Reset interrupts reception, error recovery and a just-completed frame.
    add(0, 0)
    for _ in range(max(1, n // 2)):
        add(0, 1)
    add(1, 0)
    add(0, 1)
    frame(1)
    add(1, 1)
    frame(mask, stop=0)
    add(1, 0)
    frame(1 << (n - 1))
    add(0, 1)
    add(0, 1)

    # This is a TB specification model; no Verilog DUT is constructed.
    state, index, payload, last_reset = 'idle', 0, 0, 0
    rows = []
    for cycle, (reset, bit) in enumerate(stimulus):
        done, data = 0, None
        if reset:
            state, index, payload, last_reset = 'idle', 0, 0, cycle
        elif state == 'idle':
            if bit == 0:
                state, index, payload = 'data', 0, 0
        elif state == 'data':
            payload |= bit << index
            index += 1
            if index == n:
                state = 'stop'
        elif state == 'stop':
            if bit == 1:
                done, state = 1, 'idle'
                data = payload if contract['data_output'] else None
            else:
                state = 'recover'
        elif bit == 1:
            state = 'idle'
        rows.append(dict(cycle=cycle, reset=reset, serial_input=bit, expected_done=done,
                         expected_data=data, last_reset=last_reset))
    return rows


def render_tb(parsed, task):
    if not isinstance(task, str) or LABEL.fullmatch(task) is None:
        raise ValueError('unsafe probe label')
    c = parsed['contract']
    n = c['payload_bits']
    lines = ['`timescale 1ns/1ps', 'module R2Probe;',
             'reg _sf_clk=0, _sf_reset=1, _sf_bit=1;', 'wire _sf_done;',
             f'wire [{n-1}:0] _sf_data;', 'integer _sf_checks=0, _sf_bad=0;']
    connections = [f'.{c[role]}({signal})' for role, signal in
                   (('clock', '_sf_clk'), ('reset', '_sf_reset'),
                    ('serial_input', '_sf_bit'), ('done_output', '_sf_done'))]
    if c['data_output']:
        connections.append(f'.{c["data_output"]}(_sf_data)')
    else:
        lines.append(f'assign _sf_data={n}\'d0;')
    lines += ['TopModule _sf_dut(' + ','.join(connections) + ');', 'initial begin']
    for row in parsed['rows']:
        cycle = row['cycle']
        bad = f"(_sf_done !== 1'b{row['expected_done']})"
        if row['expected_data'] is not None:
            bad += f" || (_sf_data !== {n}'d{row['expected_data']})"
        lines += [f"_sf_clk=0; _sf_reset=1'b{row['reset']}; _sf_bit=1'b{row['serial_input']};",
                  '#5; _sf_clk=1; #1;',
                  f'$display("SERIAL_STEP cycle={cycle} reset=%b input=%b done=%b data=%b",_sf_reset,_sf_bit,_sf_done,_sf_data);',
                  '_sf_checks=_sf_checks+1;', f'if ({bad}) begin',
                  f'if(_sf_bad==0) $display("SERIAL_FIRST cycle={cycle}");',
                  '_sf_bad=_sf_bad+1; end', '#4;']
    lines += [f'$display("R2_PROBE_RESULT task={task} checks=%0d mismatches=%0d",_sf_checks,_sf_bad);',
              f'if(_sf_checks!={parsed["checks"]}) $fatal(1,"CHECK_COUNT_INVALID");',
              '$finish; end', f'initial begin #{10 * parsed["checks"] + 100}; $fatal(1,"WATCHDOG_EXPIRED"); end',
              'endmodule', '']
    return '\n'.join(lines)


def measured_trace(log, parsed, mismatches):
    """Validate actual logged stimulus and observations; return the first mismatch."""
    found = re.findall(r'^SERIAL_STEP cycle=(\d+) reset=([01]) input=([01]) done=([01xz]) data=([01xz]+)\s*$', log, re.M)
    if len(found) != parsed['checks']:
        raise RuntimeError('missing/ambiguous serial observations')
    observations, failures = [], []
    n = parsed['contract']['payload_bits']
    for row, values in zip(parsed['rows'], found):
        cycle, reset, bit, done, data = values
        if (int(cycle), int(reset), int(bit)) != (row['cycle'], row['reset'], row['serial_input']) or len(data) != n:
            raise RuntimeError('serial observations contradict the executed trace')
        observation = dict(cycle=int(cycle), reset=int(reset), serial_input=int(bit), done=done, data=data)
        observations.append(observation)
        bad = done != str(row['expected_done'])
        if row['expected_data'] is not None:
            bad |= data != format(row['expected_data'], f'0{n}b')
        if bad:
            failures.append(row['cycle'])
    first = re.findall(r'^SERIAL_FIRST cycle=(\d+)\s*$', log, re.M)
    if len(failures) != mismatches or first != ([str(failures[0])] if failures else []):
        raise RuntimeError('serial mismatch count/first observation unconfirmed')
    if not failures:
        return None
    row = parsed['rows'][failures[0]]
    c = parsed['contract']
    return dict(cycle=row['cycle'], reset_port=c['reset'], input_port=c['serial_input'],
                done_port=c['done_output'], data_port=c['data_output'], payload_bits=n,
                expected_done=row['expected_done'], expected_data=row['expected_data'],
                observed_done=observations[row['cycle']]['done'],
                observed_data=observations[row['cycle']]['data'],
                actual_trace_since_reset=observations[row['last_reset']:row['cycle'] + 1])


def feedback_text(point):
    samples = ', '.join(f"{x['cycle']}:({x['reset']},{x['serial_input']})"
                        for x in point['actual_trace_since_reset'])
    text = (f"A simulation check derived only from the complete serial protocol in the prompt found a mismatch. "
            f"At successive positive clock edges, actual cycle:({point['reset_port']},{point['input_port']}) "
            f"samples from the most recent reset were [{samples}]. "
            f"After edge {point['cycle']} and nonblocking updates, expected {point['done_port']}="
            f"{point['expected_done']}, observed {point['observed_done']}.")
    if point['expected_data'] is not None:
        expected = format(point['expected_data'], f"0{point['payload_bits']}b")
        text += f" Expected {point['data_port']}=0b{expected}, observed 0b{point['observed_data']}."
    return text


def check(prompt, code, out, attempt, paired, task, root):
    """None: abstain; empty: finite check passed; text: measured repair feedback."""
    parsed = parse(prompt)
    if parsed is None or not isinstance(code, str) or re.search(r'\$[A-Za-z_]|`(?:include|define)|\bR2Probe\b', code):
        return None
    if not isinstance(task, str) or LABEL.fullmatch(task) is None:
        raise ValueError('unsafe probe label')
    if type(attempt) is not int or attempt not in (0, 1):
        raise ValueError('serial feedback must use the existing initial/one-repair attempts')
    folder = Path(out) / ('serial_check_' + str(attempt))
    inputs = folder / 'inputs' / task
    inputs.mkdir(parents=True, exist_ok=False)
    source, tb = folder / 'input.sv', inputs / 'tb.sv'
    source.write_text(code, encoding='utf-8', newline='\n')
    tb.write_text(render_tb(parsed, task), encoding='utf-8', newline='\n')
    paired.save(folder / 'contract.json', parsed)
    source_sha, tb_sha = paired.sha(source), paired.sha(tb)
    result = paired.oracle(dict(task=task, checks=parsed['checks'], tb=str(tb.relative_to(root))),
                           source, folder / 'probe')
    if paired.sha(source) != source_sha or paired.sha(tb) != tb_sha:
        raise RuntimeError('serial check inputs changed')
    if result.get('inputs_unchanged') is not True or result.get('checks') != parsed['checks']:
        raise RuntimeError('unconfirmed serial check; no fabricated feedback')
    mismatches = result.get('mismatches')
    if type(mismatches) is not int or not 0 <= mismatches <= parsed['checks']:
        raise RuntimeError('unconfirmed serial mismatch count')
    if not ((result.get('status') == 'pass' and mismatches == 0) or
            (result.get('status') == 'fail' and result.get('failure_kind') == 'semantic_mismatch' and mismatches > 0)):
        raise RuntimeError('serial tool/protocol failure; no fabricated feedback')
    point = measured_trace((folder / 'probe/xsim.log').read_text(encoding='utf-8', errors='replace'),
                           parsed, mismatches)
    if point is None:
        return ''
    paired.save(folder / 'counterexample.json', point)
    text = feedback_text(point)
    (folder / 'feedback.txt').write_text(text, encoding='utf-8', newline='\n')
    return text


def run_worker(base, args, paired):
    if args.arm == 'C':
        return base.run_worker(args, paired)
    if args.arm != 'P':
        raise ValueError('serial feedback comparison requires C or P')
    original = base.functional_feedback

    def feedback(prompt, code, out, attempt, tools, task, candidate=False):
        result = check(prompt, code, out, attempt, tools, task, base.ROOT)
        if result is not None:
            return result
        return original(prompt, code, out, attempt, tools, task, candidate=candidate)

    base.functional_feedback = feedback
    try:
        return base.run_worker(args, paired)
    finally:
        base.functional_feedback = original
