"""Extract adjacent given-row values; completeness of between-row events is unknown.
No inferred RTL, reference answer, task identity, service, file or candidate input.
These observations constrain the model; they do not identify a unique circuit.
"""
import hashlib
import re
from decimal import Decimal
from reserved_keywords import KEYWORDS

SCHEMA = 'prompt_only_waveform_sample_endpoints_v2'
IDENTIFIER = r'[A-Za-z_][A-Za-z_0-9]{0,63}'
INTRO = re.compile(
    r'\AI would like you to implement a module named (' + IDENTIFIER + r') with the following\s+'
    r'interface\. All input and output ports are one bit unless otherwise\s+specified\.\s*')
STATEMENT = re.compile(
    r'\AThe module should implement a sequential circuit\. Read the simulation\s+'
    r'waveforms to determine what the circuit does, then implement it\.\s*')

def parse(prompt):
    if not isinstance(prompt, str):
        return dict(schema=SCHEMA, status='abstain', reason='non_text_input')
    binding = hashlib.sha256(prompt.encode('utf-8')).hexdigest()
    def reject(reason, status='abstain'):
        return dict(schema=SCHEMA, status=status, reason=reason, prompt_sha256=binding)
    if 'simulation' not in prompt or 'waveform' not in prompt:
        return reject('no_sequential_waveform', 'skip')
    if not prompt.isascii() or len(prompt) > 65536 or any(ord(c) < 32 and c not in '\r\n\t' for c in prompt):
        return reject('unsupported_text')
    text = prompt.replace('\r\n', '\n')
    if '\r' in text:
        return reject('unsupported_newline')
    intro = INTRO.match(text)
    if not intro or intro[1] in KEYWORDS:
        return reject('unsupported_complete_intro')
    remaining = text[intro.end():]
    ports = []
    while True:
        match = re.match(r'\s*-\s*(input|output)\s+(' + IDENTIFIER + r')(?:\s*\(\s*(\d+)\s+bits\s*\))?\s*\n', remaining)
        if not match:
            break
        name, width = match[2], int(match[3]) if match[3] else 1
        if name in KEYWORDS or not 1 <= width <= 64:
            return reject('unsupported_port')
        ports.append(dict(direction=match[1], name=name, width=width))
        remaining = remaining[match.end():]
    if not 3 <= len(ports) <= 16 or len({p['name'] for p in ports}) != len(ports):
        return reject('incomplete_or_duplicate_ports')
    inputs = [p for p in ports if p['direction'] == 'input']
    outputs = [p for p in ports if p['direction'] == 'output']
    clocks = [p for p in inputs if p['width'] == 1 and p['name'].lower() in ('clk', 'clock')]
    if len(clocks) != 1 or not outputs or len(inputs) < 2:
        return reject('ambiguous_clock_or_interface')
    statement = STATEMENT.match(remaining.strip())
    if not statement:
        return reject('unsupported_complete_waveform_statement')
    body = remaining.strip()[statement.end():]
    lines = [line.split() for line in body.splitlines() if line.strip()]
    if not lines or lines[0][0] != 'time':
        return reject('missing_time_header')
    header = lines[0][1:]
    if len(header) != len(ports) or set(header) != {p['name'] for p in ports}:
        return reject('incomplete_or_duplicate_header')
    if not 4 <= len(lines[1:]) <= 4096:
        return reject('unsupported_row_count')
    widths = {p['name']: p['width'] for p in ports}
    rows = []
    previous_time = None
    for number, tokens in enumerate(lines[1:]):
        if len(tokens) != len(header) + 1 or not re.fullmatch(r'(?:0|[1-9]\d{0,11})(?:\.\d{1,6})?ns', tokens[0]):
            return reject('malformed_complete_row')
        time_value = Decimal(tokens[0][:-2])
        if previous_time is not None and time_value <= previous_time:
            return reject('non_increasing_time')
        values = dict(zip(header, tokens[1:]))
        if any(not re.fullmatch('[01xzXZ]{' + str(widths[name]) + '}', value) for name, value in values.items()):
            return reject('value_width_or_fourstate_mismatch')
        rows.append(dict(index=number, time=tokens[0], values={n: v.lower() for n, v in values.items()}))
        previous_time = time_value
    clock = clocks[0]['name']
    data_inputs = [p['name'] for p in inputs if p['name'] != clock]
    output_events = {p['name']: [] for p in outputs}
    uncertain_output_observations = {p['name']: [] for p in outputs}
    clock_endpoint_changes = []
    equal_clock_endpoint_input_changes = []
    known = lambda v: not any(c in v for c in 'xz')
    for before, after in zip(rows, rows[1:]):
        old, new = before['values'], after['values']
        ck0, ck1 = old[clock], new[clock]
        phase = 'equal_endpoints_' + ck1 if known(ck0) and known(ck1) and ck0 == ck1 else (
            'endpoints_0_to_1' if (ck0, ck1) == ('0', '1') else 'endpoints_1_to_0' if (ck0, ck1) == ('1', '0') else 'unknown_endpoints')
        changed_inputs = {n: dict(before=old[n], after=new[n]) for n in data_inputs if old[n] != new[n]}
        event = dict(row=after['index'], before_time=before['time'], time=after['time'], clock_relation=phase,
                     clock_before=ck0, clock_after=ck1, input_changes=changed_inputs)
        if phase in ('endpoints_0_to_1', 'endpoints_1_to_0'):
            clock_endpoint_changes.append(event)
        if phase.startswith('equal_endpoints_') and changed_inputs:
            equal_clock_endpoint_input_changes.append(dict(event, output_values={p['name']: new[p['name']] for p in outputs}))
        for output in outputs:
            name = output['name']
            if old[name] != new[name]:
                target = output_events if known(old[name]) and known(new[name]) else uncertain_output_observations
                target[name].append(dict(event, before=old[name], after=new[name]))
    if not clock_endpoint_changes:
        return reject('no_known_clock_endpoint_change')
    return dict(schema=SCHEMA, status='supported', prompt_sha256=binding, module=intro[1], ports=ports,
                clock=clock, row_count=len(rows), rows=rows, clock_endpoint_changes=clock_endpoint_changes,
                output_events=output_events, uncertain_output_observations=uncertain_output_observations,
                equal_clock_endpoint_input_changes=equal_clock_endpoint_input_changes, unique_circuit_inferred=False,
                reset_inferred=False, initialization_inferred=False,
                event_completeness_established=False, between_row_event_order_inferred=False)

def render_advice(contract):
    if contract.get('schema') != SCHEMA or contract.get('status') != 'supported':
        return ''
    lines = ['题面波形采样观察（仅描述相邻给定行的值，不是参考实现）：',
             '必须复现全部给定样本。表格格式和时间递增本身不保证列出了采样间全部事件；不能据端点相同推断期间没有时钟边沿，也不能据端点不同推断期间只有一次转移。',
             '相邻行之间多个信号值改变不能单独确定期间事件先后或采样新值/旧值。x/z不是复位或初始化要求，不擅自补初值。',
             '这些样本不能唯一确定电路或排除触发方式；结合完整题意检查组合、电平透明、边沿或明确要求的异步行为。']
    clock = contract['clock']
    for port in contract['ports']:
        if port['direction'] != 'output':
            continue
        name = port['name']
        events = contract['output_events'][name]
        same = [e for e in events if e['clock_relation'].startswith('equal_endpoints_')]
        up = sum(e['clock_relation'] == 'endpoints_0_to_1' for e in events)
        down = sum(e['clock_relation'] == 'endpoints_1_to_0' for e in events)
        lines.append(f"{name}：相邻给定行已知值改变{len(events)}对，其中{clock}两行值相同{len(same)}对、两行值0→1有{up}对、两行值1→0有{down}对；另有未知值参与的改变{len(contract['uncertain_output_observations'][name])}对。")
        for event in same[:4]:
            changes = ', '.join(f"{n}:端点{v['before']}→{v['after']}" for n, v in event['input_changes'].items()) or '其他输入两行值相同'
            lines.append(f"例：给定行{event['before_time']}与{event['time']}，{clock}两行均为{event['clock_after']}，{changes}，{name}:端点{event['before']}→{event['after']}；期间未给出的事件未知。")
    return '\n'.join(lines)
