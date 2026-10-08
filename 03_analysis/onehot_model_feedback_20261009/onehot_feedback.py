"""Prompt-only one-hot checker draft. Emits a testbench and measured diagnostics only."""
import json
from pathlib import Path
import re

import graph_contract

LABEL = re.compile(r'[A-Za-z_][A-Za-z_0-9]*')
LIMIT = 8


def parse(prompt):
    if not isinstance(prompt, str) or prompt.count('\n\nInterface:\n') > 1:
        return None
    body, _, interface = prompt.partition('\n\nInterface:\n')
    try:
        return graph_contract.parse(body, interface)
    except graph_contract.Abstain:
        return None


def expected(c, state, pin):
    n = len(c['labels'])
    if type(state) is not int or not 0 <= state < (1 << n) or type(pin) is not int or pin not in (0, 1):
        raise ValueError('invalid measured input')
    nxt, outputs = 0, [0] * len(c['outputs'])
    for src, value, dst in c['transitions']:
        if value == pin and (state >> src) & 1:
            nxt |= 1 << dst
    for src, mask in enumerate(c['output_masks']):
        if (state >> src) & 1:
            outputs = [a | b for a, b in zip(outputs, mask)]
    return format(nxt, '0' + str(n) + 'b') + ''.join(map(str, outputs))


def render_tb(c, task):
    if not isinstance(task, str) or LABEL.fullmatch(task) is None:
        raise ValueError('unsafe probe label')
    n, k = len(c['labels']), len(c['outputs'])
    declarations = [f'module R2Probe; reg _oh_pin; reg [{n-1}:0] _oh_state;',
        f'wire [{n-1}:0] _oh_next; wire [{k-1}:0] _oh_out;',
        f'reg [{n-1}:0] _oh_expected_next; reg [{k-1}:0] _oh_expected_out;',
        'integer _oh_mask,_oh_value,_oh_checks=0,_oh_bad=0;']
    ports = [f'.{c["input"]}(_oh_pin)', f'.{c["state"]}(_oh_state)',
             f'.{c["next_state"]}(_oh_next)']
    ports += [f'.{name}(_oh_out[{k-1-i}])' for i, name in enumerate(c['outputs'])]
    lines = declarations + [c['module'] + ' _oh_dut(' + ','.join(ports) + ');',
        'initial begin', f'for(_oh_mask=0;_oh_mask<{1<<n};_oh_mask=_oh_mask+1) begin',
        'for(_oh_value=0;_oh_value<2;_oh_value=_oh_value+1) begin',
        "_oh_state=_oh_mask;_oh_pin=_oh_value;_oh_expected_next=0;_oh_expected_out=0;"]
    for src, value, dst in c['transitions']:
        lines += [f'if(_oh_state[{src}] && _oh_pin==1\'b{value}) _oh_expected_next[{dst}]=1\'b1;']
    for src, mask in enumerate(c['output_masks']):
        bits = ''.join(map(str, mask))
        lines += [f'if(_oh_state[{src}]) _oh_expected_out=_oh_expected_out | {k}\'b{bits};']
    lines += ['#1;_oh_checks=_oh_checks+1;',
        'if({_oh_next,_oh_out} !== {_oh_expected_next,_oh_expected_out}) begin',
        f'if(_oh_bad<{LIMIT}) $display("ONEHOT_FIRST input=%b state=%b observed=%b",_oh_pin,_oh_state,{{_oh_next,_oh_out}});',
        '_oh_bad=_oh_bad+1;end', 'end end',
        f'$display("R2_PROBE_RESULT task={task} checks=%0d mismatches=%0d",_oh_checks,_oh_bad);',
        '$finish;end endmodule']
    return '\n'.join(lines) + '\n'


def measured_points(text, c, task, mismatches):
    """Reject malformed summaries or fabricated/misordered measured inputs."""
    n, k = len(c['labels']), len(c['outputs'])
    checks = 2 * (1 << n)
    if type(mismatches) is not int or not 0 <= mismatches <= checks:
        raise ValueError('invalid mismatch count')
    summaries = re.findall(r'^R2_PROBE_RESULT task=(\S+) checks=(\d+) mismatches=(\d+)\s*$', text, re.M)
    if len(summaries) != 1 or summaries[0] != (task, str(checks), str(mismatches)):
        raise ValueError('unconfirmed completion summary')
    lines = [line for line in text.splitlines() if line.startswith('ONEHOT_FIRST')]
    if len(lines) != min(mismatches, LIMIT):
        raise ValueError('incomplete measured counterexamples')
    points, previous = [], -1
    for line in lines:
        match = re.fullmatch(r'ONEHOT_FIRST input=([01]) state=([01]{' + str(n) +
            r'}) observed=([01xzXZ]{' + str(n+k) + r'})', line)
        if match is None:
            raise ValueError('malformed counterexample')
        pin, state, observed = int(match[1]), int(match[2], 2), match[3].lower()
        index = 2 * state + pin
        want = expected(c, state, pin)
        if index <= previous or observed == want:
            raise ValueError('counterexample is repeated, unordered or not a mismatch')
        previous = index
        points.append(dict(input=match[1], state=match[2], expected=want, observed=observed))
    return points


def feedback_text(c, mismatches, points):
    n = len(c['labels'])
    names = [c['next_state']] + c['outputs']
    return ('A simulation check derived only from the complete one-hot graph in the prompt found '
        f'{mismatches} mismatches among {2*(1<<n)} input combinations. '
        'All active state bits contribute simultaneously; zero and multiple active bits are allowed by the prompt. '
        f'Inputs below are ({c["input"]},{c["state"]}[{n-1}:0]); output order is '
        '(' + ','.join(names) + '), with next-state bits high to low. '
        'Measured counterexamples: ' + '; '.join(
            f'input=1\'b{p["input"]}, state={n}\'b{p["state"]}, '
            f'expected={len(p["expected"])}\'b{p["expected"]}, observed={len(p["observed"])}\'b{p["observed"]}'
            for p in points) + '. Fix the implementation while retaining the interface.')


def check(prompt, code, out, attempt, paired, task, root):
    c = parse(prompt)
    if c is None or not isinstance(code, str) or re.search(r'\$[A-Za-z_]|`(?:include|define)|\bR2Probe\b', code):
        return None
    if type(attempt) is not int or attempt not in (0, 1) or not isinstance(task, str) or LABEL.fullmatch(task) is None:
        raise ValueError('invalid retained one-repair probe identity')
    folder = Path(out) / ('onehot_check_' + str(attempt))
    inputs = folder / 'inputs' / task
    inputs.mkdir(parents=True, exist_ok=False)
    source, tb = folder / 'input.sv', inputs / 'tb.sv'
    source.write_text(code, encoding='utf-8', newline='\n')
    tb.write_text(render_tb(c, task), encoding='utf-8', newline='\n')
    paired.save(folder / 'contract.json', c)
    source_sha, tb_sha = paired.sha(source), paired.sha(tb)
    checks = 2 * (1 << len(c['labels']))
    result = paired.oracle(dict(task=task, checks=checks, tb=str(tb.relative_to(root))), source, folder / 'probe')
    if (paired.sha(source) != source_sha or paired.sha(tb) != tb_sha or
            result.get('inputs_unchanged') is not True or result.get('checks') != checks or
            result.get('solution_sha256') != source_sha or result.get('tb_sha256') != tb_sha):
        raise RuntimeError('one-hot measurement input binding unconfirmed')
    bad = result.get('mismatches')
    if type(bad) is not int or not 0 <= bad <= checks or not (
            (result.get('status') == 'pass' and bad == 0) or
            (result.get('status') == 'fail' and result.get('failure_kind') == 'semantic_mismatch' and bad > 0)):
        raise RuntimeError('one-hot native tool/protocol failure; no fabricated feedback')
    stages = result.get('stages')
    if not isinstance(stages, list) or [s.get('name') for s in stages] != ['xvlog', 'xelab', 'xsim']:
        raise RuntimeError('incomplete native receipts')
    for s in stages:
        log = folder / 'probe' / (s['name'] + '.log')
        if (s.get('returncode') != 0 or s.get('timeout') is not False or
                s.get('launch_error') is not None or s.get('remaining_live_group') != [] or
                Path(s.get('log', '')).resolve() != log.resolve() or
                s.get('log_sha256') != paired.sha(log) or s.get('log_bytes') != log.stat().st_size):
            raise RuntimeError('unconfirmed native log')
    log = folder / 'probe/xsim.log';log_sha = paired.sha(log)
    points = measured_points(log.read_text(encoding='utf-8', errors='replace'), c, task, bad)
    if paired.sha(log) != log_sha:
        raise RuntimeError('measurement log changed')
    paired.save(folder / 'measurement_binding.json', dict(source_sha256=source_sha, tb_sha256=tb_sha,
        log_sha256=log_sha, result_sha256=paired.sha(folder/'probe/result.json'), checks=checks, mismatches=bad))
    if bad == 0:
        return ''
    paired.save(folder / 'counterexamples.json', points)
    text = feedback_text(c, bad, points)
    (folder / 'feedback.txt').write_text(text, encoding='utf-8', newline='\n')
    return text
