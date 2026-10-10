"""Check model RTL against complete prompt tables; never synthesize a DUT."""
import re
import hashlib
import json
from pathlib import Path

import contract as table_contract
from reserved_keywords import KEYWORDS


def parse(prompt):
    parsed = table_contract.parse_prompt(prompt)
    if not parsed['admitted']:
        return None
    table = parsed['contract']
    ports = table['input_ports'] + [table['output_port']]
    if any(p['name'] in KEYWORDS or p['name'].lower() in table_contract.CONTROL_NAMES for p in ports):
        return None
    if table['kind'] == 'complete_scalar_waveform' and not re.search(
            r'The module should implement a combinational circuit\. Read the simulation\s+'
            r'waveforms to determine what the circuit does, then implement it\.', prompt):
        return None
    if not table['care_assignment_count']:
        return None
    return dict(prompt_sha256=parsed['prompt_sha256'], table=table,
                checks=2 * table['care_assignment_count'])


def render_tb(parsed, task):
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,80}', task):
        raise ValueError('unsafe probe label')
    table = parsed['table']
    ports = table['input_ports']
    # Local signal names are independent of user port names, avoiding collisions.
    lines = ['`timescale 1ns/1ps', 'module R2Probe;']
    for i, port in enumerate(ports):
        lines.append(f"reg [{port['width']-1}:0] _tf_i{i};")
    lines += ['wire _tf_o;', 'integer _tf_checks=0, _tf_bad=0;']
    connections = [f".{p['name']}(_tf_i{i})" for i, p in enumerate(ports)]
    connections.append(f".{table['output_port']['name']}(_tf_o)")
    lines += ['TopModule _tf_dut(' + ','.join(connections) + ');', 'initial begin']
    rows = table['rows']
    for index in list(range(len(rows))) + list(reversed(range(len(rows)))):
        row = rows[index]
        for i, port in enumerate(ports):
            lines.append(f"_tf_i{i}={port['width']}'d{row['inputs'][port['name']]};")
        lines.append('#1;')
        if row['care']:
            expected = row['expected']
            lines += ['_tf_checks=_tf_checks+1;', f"if(_tf_o !== 1'b{expected}) begin",
                      f'if(_tf_bad==0) $display("TABLE_FIRST row={index} expected={expected} observed=%b",_tf_o);',
                      '_tf_bad=_tf_bad+1; end']
    lines += [f'$display("R2_PROBE_RESULT task={task} checks=%0d mismatches=%0d",_tf_checks,_tf_bad);',
              f'if(_tf_checks!={parsed["checks"]}) $fatal(1,"CHECK_COUNT_INVALID");',
              '$finish; end', 'initial begin #1000; $fatal(1,"WATCHDOG_EXPIRED"); end', 'endmodule', '']
    return '\n'.join(lines)


def counterexample(log, parsed):
    found = re.findall(r'^TABLE_FIRST row=(\d+) expected=([01]) observed=([01xz])\s*$', log, re.M)
    if len(found) != 1:
        raise ValueError('missing or ambiguous table counterexample')
    index, expected, observed = found[0]
    rows = parsed['table']['rows']
    if int(index) >= len(rows):
        raise ValueError('counterexample row out of range')
    row = rows[int(index)]
    if not row['care'] or row['expected'] != int(expected) or expected == observed:
        raise ValueError('counterexample contradicts the prompt contract')
    return dict(inputs=row['inputs'], output=parsed['table']['output_port']['name'],
                expected=int(expected), observed=observed)


def check(prompt, code, out, attempt, probe, task):
    """None means abstain; empty text means this finite check passed."""
    save = lambda p, v: p.write_text(json.dumps(v, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    parsed = parse(prompt)
    if parsed is None or re.search(r'\$[A-Za-z_]|`include', code):
        return None
    folder = Path(out) / ('table_check_' + str(attempt))
    inputs = folder / 'inputs' / task
    inputs.mkdir(parents=True, exist_ok=False)
    source, tb = folder / 'input.sv', inputs / 'tb.sv'
    source.write_text(code, encoding='utf-8', newline='\n')
    tb.write_text(render_tb(parsed, task), encoding='utf-8', newline='\n')
    save(folder / 'contract.json', parsed)
    source_sha, tb_sha = sha(source), sha(tb)
    result = probe(dict(task=task, checks=parsed['checks'],
                                tb=str(tb.resolve())), source, folder / 'probe')
    if sha(source) != source_sha or sha(tb) != tb_sha:
        raise RuntimeError('table check inputs changed')
    if result.get('inputs_unchanged') is not True or result.get('checks') != parsed['checks']:
        raise RuntimeError('unconfirmed table check; no fabricated feedback')
    if result['status'] == 'pass' and result['mismatches'] == 0:
        return ''
    if result['status'] != 'fail' or result['failure_kind'] != 'semantic_mismatch' or not 0 < result['mismatches'] <= parsed['checks']:
        raise RuntimeError('table tool/protocol failure; no fabricated feedback')
    point = counterexample((folder / 'probe/xsim.log').read_text(encoding='utf-8', errors='replace'), parsed)
    save(folder / 'counterexample.json', point)
    values = ', '.join(f'{name}={value}' for name, value in point['inputs'].items())
    feedback = (f"A check derived only from the complete combinational table in the prompt found: "
                f"inputs {values}; expected {point['output']}={point['expected']}, "
                f"observed {point['output']}={point['observed']}.")
    (folder / 'feedback.txt').write_text(feedback, encoding='utf-8', newline='\n')
    return feedback


