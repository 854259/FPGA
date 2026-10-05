"""Fixed prompt-derived research controls, never model inputs or official TB."""
import hashlib
import json
import re
from pathlib import Path

from contract import parse_prompt
from render import render_tb, parse_observations

TASKS = ('Prob050_kmap1', 'Prob057_kmap2', 'Prob113_2012_q1g', 'Prob122_kmap4', 'Prob125_kmap3')
KINDS = ('positive', 'constant0', 'constant1', 'single_cell', 'sentinel')
ORDER = tuple(task + '_' + kind for task in TASKS for kind in KINDS)
TOOLS = ('xvlog', 'xelab', 'xsim')
SENTINEL = 'OWN_TABLE_SENTINEL'
PARSER_SHA = '46d53aee94b55034c1677873551c651b9a496e4331374c291d7f750a6043d206'
RENDER_SHA = '2893c870e5cd5cba4b88de3cbca3f1f447cbc74836669f0f78e940dd34d9d817'
PUBLIC = ('contract.py', 'render.py', 'controls.py', 'stage.py', 'audit.py', 'prepare.py',
          'test_calibration.py', 'README.md', 'guard_wrapper.py', 'collect_evidence.py', 'INPUT_MANIFEST.json')
ENV_ERROR = re.compile(r'(license checkout failed|failed to check out.{0,40}license|no valid license|'
                       r'flexnet licensing error|segmentation fault|cannot open shared object file|no space left on device)', re.I)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read(path):
    return json.loads(Path(path).read_bytes())


def save(path, value):
    path = Path(path)
    pending = path.with_name(path.name + '.pending')
    pending.write_bytes((json.dumps(value, indent=2) + '\n').encode())
    pending.replace(path)


def contained(root, name):
    require(isinstance(name, str) and '\\' not in name and not Path(name).is_absolute()
            and '..' not in Path(name).parts, 'unsafe evidence path')
    root = Path(root).resolve()
    path = root / name
    require(path.resolve().is_relative_to(root) and not path.is_symlink(), 'evidence escapes owned root')
    return path


def generate(prompt, case_label):
    """Five controls from all prompt care cells, with no task-selector semantics."""
    admitted = parse_prompt(prompt)
    require(admitted['admitted'] and admitted['contract']['kind'] == 'karnaugh_map', 'explicit complete Kmap required')
    contract = admitted['contract']
    care = [(i, row) for i, row in enumerate(contract['rows']) if row['care']]
    require({r['expected'] for _, r in care} == {0, 1}, 'both care values required for fixed constant negatives')
    require(re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,40}', case_label), 'invalid label')
    ports = ['input ' + ('' if p['width'] == 1 else f"[{p['width']-1}:0] ") + p['name']
             for p in contract['input_ports']]
    output = contract['output_port']['name']
    bits = contract['input_bit_order']
    controls = []
    for kind in KINDS:
        label = case_label + '_' + kind
        if kind in ('constant0', 'constant1'):
            value = int(kind[-1])
            rtl = 'module TopModule(' + ','.join(ports + ['output ' + output]) + ');\n'
            rtl += f"assign {output}=1'b{value};\nendmodule\n"
            expected = sum(row['expected'] != value for _, row in care)
        else:
            rtl = 'module TopModule(' + ','.join(ports + ['output reg ' + output]) + ');\n'
            rtl += 'always @* begin\ncase ({' + ','.join(bits) + '})\n'
            for index, row in care:
                label_bits = ''.join(str(row['input_bits'][bit]) for bit in bits)
                value = row['expected'] ^ int(kind == 'single_cell' and index == care[0][0])
                rtl += f"{len(bits)}'b{label_bits}: {output}=1'b{value};\n"
            rtl += f"default: {output}=1'b0;\nendcase\nend\nendmodule\n"
            expected = 1 if kind == 'single_cell' else 0
        tb = render_tb(prompt, label)
        if kind == 'sentinel':
            require(tb.count('$finish;\nend') == 1, 'sentinel insertion must be unique')
            tb = tb.replace('$finish;\nend', f'$display("{SENTINEL} task={label}");\n'
                            f'$fatal(1,"{SENTINEL}");\n$finish;\nend')
        controls.append({'label': label, 'kind': kind, 'checks': len(care),
                         'expected_mismatches': expected, 'single_flip_row': care[0][0] if kind == 'single_cell' else None,
                         'expected_xsim_outcome': 'positive_nonzero_sentinel' if kind == 'sentinel' else 'zero',
                         'prompt_sha256': admitted['prompt_sha256'], 'rtl': rtl, 'tb': tb,
                         'generated_research_test': True, 'original_harness': False})
    return controls


def classify(prompt, control, log, returncode):
    require(type(returncode) is int and 0 <= returncode <= 255, 'unknown/native-signal returncode')
    require(not ENV_ERROR.search(log), 'compiler environment error')
    parsed = parse_observations(prompt, control['label'], log)
    markers = [(i, line) for i, line in enumerate(log.splitlines()) if line.startswith(SENTINEL)]
    summary_lines = [i for i, line in enumerate(log.splitlines()) if line.startswith('R2_PROBE_RESULT ')]
    if control['kind'] == 'sentinel':
        marker_bound = (len(markers) == 1 and markers[0][1] == SENTINEL + ' task=' + control['label']
                        and len(summary_lines) == 1 and markers[0][0] > summary_lines[0])
        require(marker_bound, 'unknown/missing/out-of-order sentinel marker')
        matched = returncode > 0 and marker_bound and parsed['mismatches'] == 0
    else:
        marker_bound = not markers
        require(marker_bound, 'unexpected sentinel marker')
        matched = returncode == 0 and marker_bound and parsed['mismatches'] == control['expected_mismatches']
        if control['kind'] != 'positive':
            matched = matched and parsed['mismatches'] > 0
    return {'evidence_complete': True, 'control_matched': bool(matched),
            'false_acceptance': control['kind'] in ('constant0', 'constant1', 'single_cell') and parsed['mismatches'] == 0,
            'sentinel_failure_propagated': control['kind'] == 'sentinel' and matched,
            'true_xsim_returncode': returncode, 'parsed': parsed,
            'actual_research_tb_sha256': sha(control['tb'].encode()),
            'base_renderer_tb_sha256': parsed['tb_sha256'], 'sentinel_markers': len(markers),
            'generated_research_test': True, 'original_harness': False}


def validate_assets(root):
    root = Path(root)
    require(sha((root / 'contract.py').read_bytes()) == PARSER_SHA
            and sha((root / 'render.py').read_bytes()) == RENDER_SHA, 'sealed parser/render changed')
    private = read(root / 'raw_evidence/CONTROLS.json')
    require(private['model_calls'] == 0 and private['original_harness'] is False
            and private['generated_research_test'] is True, 'private research provenance')
    prepared = []
    for task in TASKS:
        prompt_path = 'raw_evidence/inputs/' + task + '/prompt.txt'
        prompt = contained(root, prompt_path).read_bytes()
        require(sha(prompt) == private['prompt_sha256'][task], 'prompt byte binding')
        for item in generate(prompt.decode(), task):
            item['task'] = task
            item['index'] = len(prepared)
            item['prompt_path'] = prompt_path
            item['rtl_path'] = 'raw_evidence/controls/' + item['label'] + '/candidate.sv'
            item['tb_path'] = 'raw_evidence/controls/' + item['label'] + '/tb.sv'
            for key, content in (('rtl_path', item['rtl']), ('tb_path', item['tb'])):
                require(contained(root, item[key]).read_bytes() == content.encode(), 'generated private source binding')
            meta = {k: v for k, v in item.items() if k not in ('rtl', 'tb')}
            meta.update(rtl_sha256=sha(item['rtl'].encode()), tb_sha256=sha(item['tb'].encode()))
            require(private['controls'][item['index']] == meta, 'fixed control metadata binding')
            require(all(type(private['controls'][item['index']][key]) is int for key in ('index', 'checks', 'expected_mismatches')), 'control metadata integer types')
            require(private['controls'][item['index']]['single_flip_row'] is None or type(private['controls'][item['index']]['single_flip_row']) is int, 'single flip row integer type')
            prepared.append((meta, prompt, item))
    require(len(private['controls']) == len(prepared) == 25
            and tuple(meta['label'] for meta, _, _ in prepared) == ORDER, 'all fixed 25 controls required')
    return private, prepared


def source_paths(private):
    names = set(PUBLIC) | {'raw_evidence/CONTROLS.json', 'raw_evidence/DEPENDENCY_BINDINGS.json'}
    for item in private['controls']:
        names.update(item[key] for key in ('prompt_path', 'rtl_path', 'tb_path'))
    return sorted(names)


def commands(control, spec):
    folder = spec['cloud_root'] + '/results/' + control['label']
    argv = (
        ['xvlog', '-sv', '--nolog', 'candidate.sv', 'tb.sv'],
        ['xelab', 'R2Probe', '-s', 'table_probe', '--nolog', '-timescale', '1ns/1ps'],
        ['xsim', 'table_probe', '-runall', '-nolog'],
    )
    return [(tool, [spec['vivado_bin'] + '/' + tool, *args[1:]], folder)
            for tool, args in zip(TOOLS, argv, strict=True)]
