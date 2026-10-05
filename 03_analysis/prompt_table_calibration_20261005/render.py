"""Prompt-only explicit Kmap TB rendering and complete-observation feedback.

These are pure functions, not a simulator runner. Native execution receipts and
zero-error xvlog/xelab/xsim completion remain the caller's responsibility.
"""
import hashlib
import json
import re

from contract import parse_prompt

SCHEMA = 'explicit_kmap_full_care_native_observations_v1'
CASE = re.compile(r'[A-Za-z][A-Za-z0-9_]{0,63}')
SUMMARY = re.compile(r'R2_PROBE_RESULT task=(\S+) checks=([0-9]+) mismatches=([0-9]+)')
BINDING = re.compile(r'TABLE_BINDING task=(\S+) prompt_sha256=([0-9a-f]{64}) contract_sha256=([0-9a-f]{64})')
CARE = re.compile(r'TABLE_CARE task=(\S+) row=([0-9]+) inputs=(\S+) expected=([01]) observed=([01xXzZ])')


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _admit(prompt, case_id):
    _require(isinstance(case_id, str) and CASE.fullmatch(case_id), 'invalid_case_label')
    receipt = parse_prompt(prompt)
    _require(receipt['admitted'] and receipt['all_prompt_consumed'],
             'prompt_not_admitted:' + str(receipt['reason']))
    contract = receipt['contract']
    _require(contract['kind'] == 'karnaugh_map'
             and contract['semantics'] == 'explicit_complete_cared_truth_table',
             'explicit_kmap_only')
    _require(contract['care_assignment_count'] > 0, 'no_cared_obligations')
    payload = json.dumps(contract, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()
    contract_sha = _sha(payload)
    rows = [(i, row) for i, row in enumerate(contract['rows']) if row['care']]
    _require(len(rows) == contract['care_assignment_count'], 'invalid_derived_care_count')
    return receipt['prompt_sha256'], contract_sha, contract, rows


def _expressions(contract):
    expressions = {}
    for i, port in enumerate(contract['input_ports']):
        name, width = port['name'], port['width']
        if width == 1:
            expressions[name] = f'_pt_i{i}'
        else:
            expressions.update({f'{name}[{bit}]': f'_pt_i{i}[{bit}]' for bit in range(width)})
    return expressions


def render_tb(prompt, case_id):
    """Render R2Probe with every explicit care cell; no DUT/reference is emitted."""
    prompt_sha, contract_sha, contract, rows = _admit(prompt, case_id)
    expressions = _expressions(contract)
    lines = ['`timescale 1ns/1ps', 'module R2Probe;']
    for i, port in enumerate(contract['input_ports']):
        width = '' if port['width'] == 1 else f"[{port['width'] - 1}:0] "
        lines.append(f'reg {width}_pt_i{i};')
    lines.append('wire _pt_o;')
    connections = [f".{p['name']}(_pt_i{i})" for i, p in enumerate(contract['input_ports'])]
    connections.append(f".{contract['output_port']['name']}(_pt_o)")
    lines += ['TopModule _pt_dut(' + ','.join(connections) + ');',
              'integer _pt_checks=0, _pt_mismatches=0;', 'initial begin',
              '$display("TABLE_BINDING task=' + case_id + ' prompt_sha256=' + prompt_sha
              + ' contract_sha256=' + contract_sha + '");']
    bit_order = contract['input_bit_order']
    for row_index, row in rows:
        for bit in bit_order:
            lines.append(expressions[bit] + "=1'b" + str(row['input_bits'][bit]) + ';')
        lines += ['#1;', '_pt_checks=_pt_checks+1;',
                  "if (_pt_o !== 1'b" + str(row['expected']) + ') _pt_mismatches=_pt_mismatches+1;']
        inputs_format = ','.join(bit + '=%b' for bit in bit_order)
        args = ','.join(expressions[bit] for bit in bit_order) + ',_pt_o'
        lines.append('$display("TABLE_CARE task=' + case_id + ' row=' + str(row_index)
                     + ' inputs=' + inputs_format + ' expected=' + str(row['expected'])
                     + ' observed=%b",' + args + ');')
    lines += ['if (_pt_checks!=' + str(len(rows)) + ') $fatal(1,"CHECK_COUNT_INVALID");',
              '$display("R2_PROBE_RESULT task=' + case_id
              + ' checks=%0d mismatches=%0d",_pt_checks,_pt_mismatches);',
              '$finish;', 'end', 'initial begin #1000; $fatal(1,"WATCHDOG_EXPIRED"); end',
              'endmodule', '']
    return '\n'.join(lines)


def parse_observations(prompt, case_id, log):
    """Validate all actual rows plus source binding and completed R2 summary.

    ValueError means invalid/unknown evidence and must never become repair
    feedback or a semantic pass/fail. This function does not run any tool.
    """
    prompt_sha, contract_sha, contract, care_rows = _admit(prompt, case_id)
    _require(isinstance(log, str), 'log_must_be_string')
    _require(len(log) <= 1048576 and '\x00' not in log, 'invalid_or_oversized_log')
    normalized = log.replace('\r\n', '\n')
    _require('\r' not in normalized, 'invalid_log_line_endings')
    protocol = []
    for line in normalized.splitlines():
        line = line.strip()
        if line.startswith(('TABLE_', 'R2_PROBE_')):
            protocol.append(line)
    _require(len(protocol) == len(care_rows) + 2, 'missing_or_duplicate_protocol_rows')
    binding = BINDING.fullmatch(protocol[0])
    _require(binding is not None and binding.groups() == (case_id, prompt_sha, contract_sha),
             'source_binding_mismatch')
    summary = SUMMARY.fullmatch(protocol[-1])
    _require(summary is not None and summary[1] == case_id, 'missing_or_unbound_completed_summary')
    _require(int(summary[2]) == len(care_rows), 'summary_check_count_mismatch')
    observations = []
    for line, (row_index, row) in zip(protocol[1:-1], care_rows, strict=True):
        match = CARE.fullmatch(line)
        _require(match is not None and match[1] == case_id, 'malformed_or_unbound_care_row')
        _require(int(match[2]) == row_index, 'duplicate_missing_or_out_of_order_care_row')
        pairs = match[3].split(',')
        _require(len(pairs) == len(contract['input_bit_order']), 'input_bit_count_mismatch')
        actual_bits = {}
        for pair, bit in zip(pairs, contract['input_bit_order'], strict=True):
            _require(pair in (bit + '=0', bit + '=1'), 'input_bit_name_order_or_value_mismatch')
            actual_bits[bit] = int(pair[-1])
        _require(actual_bits == row['input_bits'], 'input_assignment_not_bound_to_care_row')
        _require(int(match[4]) == row['expected'], 'expected_value_not_bound_to_prompt')
        _require(match[5] in ('0', '1'), 'unknown_output_not_semantic_feedback')
        observed = int(match[5])
        observations.append({'row': row_index, 'inputs': row['inputs'], 'input_bits': actual_bits,
                             'expected': row['expected'], 'observed': observed,
                             'mismatch': observed != row['expected'], 'source': row['source']})
    mismatches = sum(row['mismatch'] for row in observations)
    _require(int(summary[3]) == mismatches, 'summary_mismatch_count_disagrees_with_rows')
    return {'schema': SCHEMA, 'status': 'fail' if mismatches else 'pass',
            'evidence_complete': True, 'case_id': case_id, 'prompt_sha256': prompt_sha,
            'contract_sha256': contract_sha, 'tb_sha256': _sha(render_tb(prompt, case_id).encode()),
            'log_sha256': _sha(log.encode()), 'checks': len(care_rows), 'mismatches': mismatches,
            'output': contract['output_port']['name'], 'input_bit_order': contract['input_bit_order'],
            'observations': observations, 'semantics': 'explicit_prompt_care_observations',
            'actual_native_execution_confirmed_by_this_pure_function': False}


def make_feedback(prompt, case_id, log, mode='first'):
    """Return first/full feedback from the same fully verified raw log; pass=None."""
    _require(mode in ('first', 'full'), 'unsupported_feedback_mode')
    receipt = parse_observations(prompt, case_id, log)
    if not receipt['mismatches']:
        return None
    lines = [f"Native prompt-derived Kmap observations: checks={receipt['checks']}, mismatches={receipt['mismatches']}.",
             "Only explicit cared cells impose output requirements; don't-care cells are unconstrained."]
    if mode == 'first':
        rows = [next(row for row in receipt['observations'] if row['mismatch'])]
        lines.append('First mismatching cared cell:')
    else:
        rows = receipt['observations']
        lines.append('Complete cared table, including passing observations:')
    for row in rows:
        inputs = ','.join(bit + '=' + str(row['input_bits'][bit]) for bit in receipt['input_bit_order'])
        lines.append('inputs=' + inputs + '; output=' + receipt['output'] + '; expected='
                     + str(row['expected']) + '; observed=' + str(row['observed']) + '; '
                     + ('MISMATCH' if row['mismatch'] else 'PASS'))
    lines.append('Repair the logic against the original prompt; these observations do not change its requirements.')
    return '\n'.join(lines)
