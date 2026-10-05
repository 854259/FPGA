"""Static bytes/AST/ABI checks only; no simulator, model, subprocess or network calls."""
from pathlib import Path
import argparse
import ast
import hashlib
import json
import re
import sys

ROOT = Path(__file__).resolve().parent
DATASET_SHA = 'cbcd81295561ebb16e4d857e096f4d9908d042c33aff3b58abf236e868411857'
ORDER = ['positive', 'constant_zero', 'constant_one', 'swapped_edges', 'widened_pulse', 'reset_ignored', 'failure_propagation']


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return sha(json.dumps(value, sort_keys=True).encode())


def check():
    private = json.loads((ROOT / 'raw_evidence/CONTROLS.json').read_bytes())
    data = (ROOT / private['dataset']['local_copy']).read_bytes()
    assert sha(data) == DATASET_SHA == private['dataset']['sha256']
    lines = data.decode().splitlines()
    assert len(data) == private['dataset']['bytes'] and len(lines) == private['dataset']['records']
    assert len(private['cases']) == 1
    case = private['cases'][0]
    matches = [(line, json.loads(line)) for line in lines if json.loads(line)['id'] == case['record_id']]
    assert len(matches) == 1
    line, row = matches[0]
    assert canonical(row) == case['record_sha256']
    assert sha(line.encode()) == case['original_json_line_sha256']
    assert row['input']['context'] == {}
    assert row['output'] == {'response': '', 'context': {case['rtl_path']: ''}}
    for key, obj in [('input_sha256', row['input']), ('input_context_sha256', row['input']['context']),
                     ('output_sha256', row['output']), ('output_context_sha256', row['output']['context'])]:
        assert canonical(obj) == case[key], key
    assert sha(row['input']['prompt'].encode()) == case['prompt_sha256']
    original = row['harness']['files']
    assert {name: sha(text.encode()) for name, text in original.items()} == case['harness_sha256']
    assert sha(original[case['test_path']].encode()) == case['test_sha256']
    assert sha(original[case['runner_path']].encode()) == case['runner_sha256']
    parsed = []
    for path in sorted(ROOT.rglob('*.py')):
        if '__pycache__' in path.parts:
            continue
        source = path.read_bytes()
        ast.parse(source, filename=str(path))
        compile(source, str(path), 'exec')  # parsing only, never exec/import scripts
        parsed.append(path.relative_to(ROOT).as_posix())
    test_tree = ast.parse(original[case['test_path']])
    runner_tree = ast.parse(original[case['runner_path']])
    test_functions = [node for node in test_tree.body if isinstance(node, ast.AsyncFunctionDef)
                      and any(isinstance(d, ast.Call) and isinstance(d.func, ast.Attribute) and
                              isinstance(d.func.value, ast.Name) and d.func.value.id == 'cocotb' and d.func.attr == 'test'
                              for d in node.decorator_list)]
    runner_functions = [node for node in runner_tree.body if isinstance(node, ast.FunctionDef) and node.name.startswith('test_')]
    assert len(test_functions) == len(runner_functions) == case['expected_pytest_tests'] == 1
    test_body = test_functions[0]
    asserts = [node for node in ast.walk(test_body) if isinstance(node, ast.Assert)]
    observed_outputs = [node.test.left.value.attr for node in asserts
                        if isinstance(node.test, ast.Compare) and isinstance(node.test.left, ast.Attribute)
                        and isinstance(node.test.left.value, ast.Attribute)]
    assert len(asserts) == 4
    assert observed_outputs == ['o_positive_edge_detected', 'o_positive_edge_detected', 'o_negative_edge_detected', 'o_negative_edge_detected']
    # No assignment to reset inside the only decorated test; reset_dut is startup only.
    assert not any(isinstance(node, ast.Attribute) and node.attr == 'i_rstb' for node in ast.walk(test_body))
    ast.parse(original[case['test_path']] + private['sentinel_suffix'])
    expected_sentinel = '\n    raise AssertionError("OWN_NATURAL_FAILURE_PROPAGATION")\n'
    assert private['sentinel_suffix'] == expected_sentinel
    assert private['evaluation_only'] and not private['reference_answer_available']
    assert case['control_order'] == [control['label'] for control in case['controls']] == ORDER
    controls = {control['label']: control for control in case['controls']}
    for label, control in controls.items():
        rtl = control['rtl']
        assert sha(rtl.encode()) == control['rtl_sha256']
        assert re.findall(r'\bmodule\s+(\w+)\s*\(', rtl) == [case['top']]
        assert re.findall(r'\binput\s+wire\s+(\w+)', rtl) == case['public_ports']['inputs']
        assert re.findall(r'\boutput\s+reg\s+(\w+)', rtl) == case['public_ports']['outputs']
        assert len(re.findall(r'\bendmodule\b', rtl)) == 1
        assert not re.search(r'\$|\binitial\b|\binclude\b|\bforce\b|\bifdef\b', rtl)
        for port in case['public_ports']['inputs'] + case['public_ports']['outputs']:
            assert '`' + port + '`' in row['input']['prompt']
        assert control['original_harness'] == (label != 'failure_propagation')
        assert control['expected_for_admission'] == ('pass' if control['intent'] == 'correct' else 'fail')
    assert controls['positive']['rtl'] == controls['failure_propagation']['rtl']
    assert controls['reset_ignored']['rtl'].count('i_rstb') == 1  # input declaration only
    assert 'always @(posedge i_clk) begin' in controls['reset_ignored']['rtl']
    positive_normal = controls['positive']['rtl'].split('    end else begin\n')[1].split('    end\n')[0]
    reset_ignored_normal = controls['reset_ignored']['rtl'].split('always @(posedge i_clk) begin\n')[1].split('end\n')[0]
    assert positive_normal == reset_ignored_normal
    assert [control['intent'] for control in case['controls']] == ['correct'] + ['wrong'] * 5 + ['sentinel']
    count = len(case['controls']) * case['expected_pytest_tests']
    assert count == private['planned_controls'] == private['planned_pytest_cases'] == private['planned_compile_commands'] == private['planned_simulation_commands'] == 7
    # Mechanical journal copy verification; no native tool process is launched.
    assert sha((ROOT / 'tool_journal.py').read_bytes()) == 'ec07a0cb78495de1daee9611fb06e906ff319189fd239a91e41e52f58a67c465'
    return dict(schema='natural_edge_static_binding_check_v1', static_checks_passed=True,
                python_version=sys.version.split()[0], parsed_own_python_sources=parsed,
                original_python_sources_parsed=[case['test_path'], case['runner_path']],
                dataset_sha256=sha(data), dataset_records=len(lines), record_id=case['record_id'],
                record_sha256=case['record_sha256'], prompt_sha256=case['prompt_sha256'],
                original_test_sha256=case['test_sha256'], original_runner_sha256=case['runner_sha256'],
                original_harness_sha256=case['harness_sha256'], controls_sha256=sha((ROOT / 'raw_evidence/CONTROLS.json').read_bytes()),
                control_order=ORDER, controls=count, planned_native_trials=count,
                original_assertions=4, runtime_reset_assertions=0,
                model_calls=0, eda_calls=0, actual_native_trials=0,
                quality_verified=False, eligible_for_independent_models=False, adoption=False,
                limits=['Python AST/compile and textual RTL ABI checks only; no SystemVerilog compiler or semantic simulator was run.',
                        'Controls and original public prompt/harness have evaluation exposure; no reference answer exists in this source record.',
                        'No native outcome is reported; reset_ignored false acceptance remains a pending guarded observation.'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    result = check()
    if args.out:
        assert args.out.resolve().is_relative_to(ROOT)
        args.out.write_bytes((json.dumps(result, ensure_ascii=False, indent=2) + '\n').encode())
    print(json.dumps({key: result[key] for key in ['static_checks_passed', 'controls', 'planned_native_trials', 'model_calls', 'eda_calls', 'quality_verified']}))
