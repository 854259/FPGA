"""Bounded prompt-only complete-table admission; no file, model or EDA access.

Only fully consumed English table templates are accepted. No task IDs, reference
answers, testbenches, candidate RTL, inferred reset values or row-order defaults
enter this function. An abstention is the ordinary result for unsupported text.
"""
import hashlib
import itertools
import re

SCHEMA = 'prompt_only_complete_table_contract_v1'
HEADER = re.compile(
    r'\AI would like you to implement a module named TopModule with the following\s+'
    r'interface\. All input and output ports are one bit unless otherwise\s+specified\.\s*'
)
PORT = re.compile(r'-\s*(input|output)\s+([A-Za-z_][A-Za-z_0-9]*)(?:\s+\(([1-9][0-9]*) bits\))?')
ATOM = re.compile(r'[A-Za-z_][A-Za-z_0-9]*\[[0-9]+\]|[A-Za-z_]')
KMAP = re.compile(
    r'\AThe module should implement (?:the circuit described by the Karnaugh map|'
    r'the function (?P<function>[A-Za-z_][A-Za-z_0-9]*) shown in the Karnaugh map|'
    r'the Karnaugh map)\s+below\.\s*'
    r"(?P<dontcare>d is don't-care,\s+which means you may choose to output whatever\s+value is convenient\.\s*)?"
)
WAVEFORM = re.compile(
    r'\A(?:The module can be described by the following simulation waveform:|'
    r'The module should implement a combinational circuit\. Read the simulation\s+'
    r'waveforms to determine what the circuit does, then implement it\.)\s*'
)
CONTROL_NAMES = {'clk', 'clock', 'reset', 'areset', 'rst', 'resetn', 'rst_n', 'aresetn'}


class Abstain(ValueError):
    pass


def _require(condition, reason):
    if not condition:
        raise Abstain(reason)


def _port_bits(port):
    name, width = port['name'], port['width']
    return [name] if width == 1 else [f'{name}[{i}]' for i in range(width - 1, -1, -1)]


def _atoms(text):
    compact = re.sub(r'\s+', '', text)
    atoms = ATOM.findall(compact)
    _require(atoms and ''.join(atoms) == compact, 'malformed_axis')
    _require(len(atoms) == len(set(atoms)), 'duplicate_axis_bit')
    return atoms


def _labels(n):
    return {''.join(bits) for bits in itertools.product('01', repeat=n)}


def _rows(ports, output, bit_order, cells):
    rows = []
    for label in sorted(cells):
        expected, source = cells[label]
        bits = dict(zip(bit_order, map(int, label), strict=True))
        values = {}
        for port in ports:
            values[port['name']] = int(''.join(str(bits[b]) for b in _port_bits(port)), 2)
        rows.append({'inputs': values, 'input_bits': bits, 'expected': expected,
                     'care': expected is not None, 'source': source})
    return {'input_ports': ports, 'output_port': output, 'input_bit_order': bit_order,
            'complete_assignment_count': len(rows),
            'care_assignment_count': sum(r['care'] for r in rows), 'rows': rows}


def _parse_kmap(body, inputs, output, bit_order):
    match = KMAP.match(body)
    _require(match is not None, 'unsupported_kmap_statement')
    _require(match['function'] in (None, output['name']), 'function_output_binding')
    lines = [line.strip() for line in body[match.end():].splitlines() if line.strip()]
    _require(len(lines) >= 3, 'incomplete_kmap')
    columns = _atoms(lines[0])
    header = lines[1].split()
    _require(len(header) >= 3, 'malformed_kmap_header')
    row_bits = _atoms(header[0])
    labels = header[1:]
    _require(len(labels) == 2 ** len(columns) and set(labels) == _labels(len(columns)),
             'incomplete_or_duplicate_column_labels')
    axes = columns + row_bits
    _require(len(axes) == len(set(axes)), 'overlapping_axes')
    _require(set(axes) == set(bit_order), 'axis_not_exact_declared_inputs')
    _require(len(lines[2:]) == 2 ** len(row_bits), 'incomplete_kmap_rows')
    row_labels, cells = [], {}
    for line in lines[2:]:
        pieces = [item.strip() for item in line.split('|')]
        _require(len(pieces) == len(labels) + 2 and pieces[-1] == '', 'malformed_kmap_row')
        row_label = pieces[0]
        _require(row_label in _labels(len(row_bits)) and row_label not in row_labels,
                 'invalid_or_duplicate_row_label')
        row_labels.append(row_label)
        for column_label, value in zip(labels, pieces[1:-1], strict=True):
            _require(value in {'0', '1', 'd'}, 'invalid_kmap_cell')
            _require(value != 'd' or match['dontcare'] is not None, 'undeclared_dontcare')
            assignment = dict(zip(row_bits, row_label, strict=True))
            assignment.update(zip(columns, column_label, strict=True))
            key = ''.join(assignment[b] for b in bit_order)
            cells[key] = (None if value == 'd' else int(value),
                          {'row_label': row_label, 'column_label': column_label})
    _require(set(row_labels) == _labels(len(row_bits)), 'incomplete_kmap_row_labels')
    _require(set(cells) == _labels(len(bit_order)), 'incomplete_input_assignments')
    result = _rows(inputs, output, bit_order, cells)
    result.update({'kind': 'karnaugh_map', 'semantics': 'explicit_complete_cared_truth_table',
                   'column_bit_order': columns, 'row_bit_order': row_bits,
                   'column_labels_as_written': labels, 'row_labels_as_written': row_labels,
                   'dontcare_declared': match['dontcare'] is not None})
    return result


def _parse_waveform(body, inputs, output, bit_order):
    match = WAVEFORM.match(body)
    _require(match is not None, 'unsupported_waveform_statement')
    _require(all(p['width'] == 1 for p in inputs), 'waveform_vector_unsupported')
    _require(not any(p['name'].lower() in CONTROL_NAMES for p in inputs), 'waveform_sequential_control')
    lines = [line.strip() for line in body[match.end():].splitlines() if line.strip()]
    _require(len(lines) >= 2, 'incomplete_waveform')
    header = lines[0].split()
    expected_names = set(bit_order) | {output['name']}
    _require(header[0] == 'time' and len(header) == len(expected_names) + 1
             and len(set(header)) == len(header) and set(header[1:]) == expected_names,
             'waveform_header_binding')
    _require(len(lines) <= 513, 'waveform_too_many_rows')
    cells, unit, previous_time = {}, None, -1
    for line_number, line in enumerate(lines[1:], start=1):
        fields = line.split()
        _require(len(fields) == len(header), 'malformed_waveform_row')
        time = re.fullmatch(r'([0-9]+)(ns|ps)', fields[0])
        _require(time is not None, 'malformed_waveform_time')
        if unit is None:
            unit = time[2]
        _require(time[2] == unit and int(time[1]) > previous_time, 'waveform_time_order_or_units')
        previous_time = int(time[1])
        _require(all(v in {'0', '1'} for v in fields[1:]), 'waveform_nonbinary_value')
        assignment = dict(zip(header[1:], map(int, fields[1:]), strict=True))
        key = ''.join(str(assignment[b]) for b in bit_order)
        expected = assignment[output['name']]
        if key in cells:
            _require(cells[key][0] == expected, 'conflicting_waveform_observations')
            cells[key][1]['observation_lines'].append(line_number)
        else:
            cells[key] = (expected, {'observation_lines': [line_number]})
    _require(set(cells) == _labels(len(bit_order)), 'incomplete_waveform_input_coverage')
    result = _rows(inputs, output, bit_order, cells)
    result.update({'kind': 'complete_scalar_waveform',
                   'semantics': 'complete_consistent_prompt_observations_no_clock_specified',
                   'observation_count': len(lines) - 1, 'time_unit': unit,
                   'limits': ['Finite observations do not prove absence of unmentioned hidden state; admitted template has no sequential contract and all input combinations agree.']})
    return result


def parse_prompt(prompt):
    """Return admission/abstention; only a complete prompt string is accepted."""
    receipt = {'schema': SCHEMA, 'admitted': False, 'all_prompt_consumed': False,
               'model_calls': 0, 'eda_calls': 0, 'external_io_calls': 0}
    if not isinstance(prompt, str):
        return receipt | {'reason': 'prompt_must_be_string'}
    try:
        receipt['prompt_sha256'] = hashlib.sha256(prompt.encode('utf-8')).hexdigest()
    except UnicodeEncodeError:
        return receipt | {'reason': 'unsupported_prompt_encoding_or_size'}
    try:
        _require(len(prompt) <= 65536 and prompt.isascii(), 'unsupported_prompt_encoding_or_size')
        text = prompt.replace('\r\n', '\n')
        _require('\r' not in text and '\x00' not in text, 'unsupported_control_character')
        match = HEADER.match(text)
        _require(match is not None, 'unsupported_interface_preamble')
        lines = text[match.end():].splitlines()
        ports, index = [], 0
        for index, line in enumerate(lines):
            if not line.strip():
                continue
            port = PORT.fullmatch(line.strip())
            if port is None:
                break
            _require(port[3] is None or len(port[3]) == 1, 'input_width_out_of_scope')
            ports.append({'direction': port[1], 'name': port[2], 'width': int(port[3] or 1)})
        else:
            raise Abstain('missing_table_body')
        _require(ports and len({p['name'] for p in ports}) == len(ports), 'missing_or_duplicate_ports')
        inputs = [{k: p[k] for k in ('name', 'width')} for p in ports if p['direction'] == 'input']
        outputs = [{k: p[k] for k in ('name', 'width')} for p in ports if p['direction'] == 'output']
        _require(len(outputs) == 1 and outputs[0]['width'] == 1, 'requires_one_scalar_output')
        _require(1 <= sum(p['width'] for p in inputs) <= 4, 'input_width_out_of_scope')
        _require(all(p['name'] != 'time' for p in inputs + outputs), 'reserved_time_name')
        bit_order = [b for p in inputs for b in _port_bits(p)]
        body = '\n'.join(lines[index:]).strip()
        if KMAP.match(body):
            contract = _parse_kmap(body, inputs, outputs[0], bit_order)
        elif WAVEFORM.match(body):
            contract = _parse_waveform(body, inputs, outputs[0], bit_order)
        else:
            raise Abstain('unsupported_or_unconsumed_body')
        return receipt | {'admitted': True, 'all_prompt_consumed': True,
                          'reason': None, 'contract': contract}
    except Abstain as error:
        return receipt | {'reason': str(error)}
