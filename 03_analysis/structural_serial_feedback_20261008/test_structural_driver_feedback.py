"""AMD-only independent handwritten controls; no model/EDA or source mutation."""
import hashlib
import json
from pathlib import Path
import sys
import traceback

import structural_driver_feedback as diagnostic

HERE = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


def check_case(case):
    path = HERE / case['file']
    assert sha(path) == case['sha256']
    code = path.read_text(encoding='utf-8')
    result = diagnostic.analyze(code)
    assert result['status'] == case['expected_status'], result
    assert [item['variable'] for item in result['diagnostics']] == case['expected_variables'], result
    assert result['compile_failure_proven'] is False and result['semantic_edits'] == 0
    assert result['source_sha256'] == hashlib.sha256(code.encode()).hexdigest()
    rendered = diagnostic.render_feedback(result)
    assert len(rendered) <= diagnostic.MAX_FEEDBACK_CHARS
    if case['expected_status'] == 'source_conflict_needs_review':
        assert result['complete_supported_syntax'] is True
        for item in result['diagnostics']:
            assert item['variable'] in rendered
            assert len({process['index'] for process in item['processes']}) >= 2
            assert any(process['clocked'] for process in item['processes'])
            for assignment in item['assignments']:
                offset = assignment['assignment']['offset']
                assert code[offset:offset + len(item['variable'])] == item['variable']
                assert assignment['assignment']['line'] == code.count('\n', 0, offset) + 1
                assert assignment['assignment']['column'] == offset - code.rfind('\n', 0, offset)
        if case['independent_locations']:
            expected, finding = case['independent_locations'], result['diagnostics'][0]
            assert [p['start']['line'] for p in finding['processes']] == expected['process_lines']
            assert [a['assignment']['line'] for a in finding['assignments']] == expected['assignment_lines']
            assert finding['declaration']['line'] == expected['declaration_line']
        if case['name'] == 'two_scalar_findings':
            # Rendering remains bounded even if many findings are presented;
            # the underlying JSON retains complete locations.
            expanded = dict(result, diagnostics=result['diagnostics'] * 100)
            assert len(diagnostic.render_feedback(expanded)) <= diagnostic.MAX_FEEDBACK_CHARS
    else:
        assert rendered == '' and not result['diagnostics']
        assert result['complete_supported_syntax'] == (case['expected_status'] == 'supported_no_conflict')
    assert sha(path) == case['sha256']
    return dict(name=case['name'], passed=True, synthetic=True, result=result,
                rendered_feedback=rendered, source_sha256=sha(path))


def run_controls(out):
    """Create a fresh output directory; write CONTROL_RESULT.json; raise on fail.

    Returned JSON is that same result. Every case outcome is retained. A failure
    is never retried and must not be interpreted as supported-no-conflict.
    """
    if sys.platform != 'linux' or not sys.dont_write_bytecode:
        raise RuntimeError('execute only on authorized AMD using Python -B')
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    manifest_path = HERE / 'CONTROL_CASES.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    assert manifest['static_cases'] == len(manifest['cases']) == 25
    records = []
    for case in manifest['cases']:
        try:
            record = check_case(case)
        except BaseException as error:
            record = dict(name=case['name'], passed=False, synthetic=True,
                          error=dict(type=type(error).__name__, message=str(error), traceback=traceback.format_exc()))
        records.append(record)
        save(out / (case['name'] + '.json'), record)
    resource_cases = [
        ('source_size_limit', '// ' + 'x' * (diagnostic.MAX_CHARS + 1), 'source_size_limit'),
        ('nesting_limit', 'module M(input c,input a,output reg q); always @(posedge c) ' +
         'begin ' * (diagnostic.MAX_DEPTH + 2) + 'q<=a; ' +
         'end ' * (diagnostic.MAX_DEPTH + 2) + 'endmodule', 'nesting_limit'),
        ('token_limit', 'module M(input c,input a,output reg q); always @(posedge c) begin ' +
         '; ' * (diagnostic.MAX_TOKENS + 1) + 'end endmodule', 'token_limit'),
    ]
    for name, code, reason in resource_cases:
        try:
            result = diagnostic.analyze(code)
            assert result['status'] == 'abstain' and result['reason'] == reason, result
            assert result['source_sha256'] == hashlib.sha256(code.encode('utf-8')).hexdigest()
            assert result['diagnostics'] == [] and diagnostic.render_feedback(result) == ''
            record = dict(name=name, passed=True, synthetic=True, result=result)
        except BaseException as error:
            record = dict(name=name, passed=False, synthetic=True,
                          error=dict(type=type(error).__name__, message=str(error), traceback=traceback.format_exc()))
        records.append(record)
        save(out / (name + '.json'), record)
    summary = dict(schema='structural_driver_pure_controls_v1', complete=True,
                   passed=all(record['passed'] for record in records), controls=len(records),
                   static_cases=25, resource_cases=3, records=records,
                   control_manifest_sha256=sha(manifest_path),
                   diagnostic_source_sha256=sha(diagnostic.__file__),
                   real_model_calls=0, real_eda_commands=0, score_measured=False)
    assert len(records) == 28
    save(out / 'CONTROL_RESULT.json', summary)
    if not summary['passed']:
        raise RuntimeError('structural-driver pure controls failed; original results preserved')
    return summary
