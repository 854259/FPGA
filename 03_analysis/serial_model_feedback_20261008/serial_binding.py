"""Read retained serial evidence after the inherited worker.bind model proof.

No model calls, subprocesses or EDA reruns. Execute only on authorized AMD.
"""
import json
from pathlib import Path
import re

import baseline_worker
import serial_feedback


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def bind_serial(solve, root):
    solve, root = Path(solve).resolve(), Path(root).resolve()
    prompt = (solve / 'prompt_only/prompt.txt').read_text(encoding='utf-8')
    interface = solve / 'prompt_only/interface.txt'
    if interface.is_file() and interface.read_text(encoding='utf-8').strip():
        prompt += '\n\nInterface:\n' + interface.read_text(encoding='utf-8')
    parsed = serial_feedback.parse(prompt)
    requests = read(solve / 'requests.json')
    assert 1 <= len(requests) <= 2
    trace = [json.loads(line) for line in (solve / 'trace.jsonl').read_text().splitlines()]
    baseline = baseline_worker.load('serial_binding_extract', root / 'package/baseline.py')
    present = {p.name for p in solve.glob('serial_check_*')}
    assert present <= {'serial_check_' + str(i) for i in range(len(requests))}
    if parsed is None:
        assert not present
        return dict(applicable=False, actual_checks=[], counterexamples_consumed=0)
    spec = read(root / 'RUN_SPEC.json')
    sha = baseline_worker.sha
    records = []
    for attempt in range(len(requests)):
        folder = solve / ('serial_check_' + str(attempt))
        response = read(solve / 'requests' / str(attempt) / 'response.json')
        code = baseline.extract(response['choices'][0]['message'].get('content') or '', 'rtl')
        lint = [e for e in trace if e.get('tool') == 'lint' and e.get('round') == attempt]
        should_check = (len(lint) == 1 and lint[0]['rc'] == 0 and not
                        re.search(r'\$[A-Za-z_]|`(?:include|define)|\bR2Probe\b', code))
        assert folder.exists() == should_check
        if not should_check:
            continue  # Source/compile rejection can precede the functional check.
        assert folder.is_dir() and not folder.is_symlink()
        assert (folder / 'input.sv').read_text(encoding='utf-8') == code
        assert read(folder / 'contract.json') == parsed
        paths = list((folder / 'inputs').glob('*/tb.sv'))
        assert len(paths) == 1
        tb, task = paths[0], paths[0].parent.name
        assert tb.read_text(encoding='utf-8') == serial_feedback.render_tb(parsed, task)
        probe = folder / 'probe'
        original, adapter = read(probe / 'result.json'), read(probe / 'adapter_receipt.json')
        extras = {'inherited_runner_path', 'inherited_runner_sha256', 'oracle_adapter_path',
                  'oracle_adapter_sha256', 'inherited_result_path', 'inherited_result_sha256'}
        assert {k: v for k, v in adapter.items() if k not in extras} == original
        assert adapter['inherited_result_path'] == str(probe / 'result.json')
        assert adapter['inherited_result_sha256'] == sha(probe / 'result.json')
        for name, key in [('probe_runner.py', 'inherited_runner'),
                          ('paired_checkpoint.py', 'oracle_adapter')]:
            dependency = Path(spec['dependencies_cloud']) / name
            assert adapter[key + '_path'] == str(dependency)
            assert adapter[key + '_sha256'] == sha(dependency) == spec['dependency_hashes'][name]
        assert original['task'] == task and original['outdir'] == str(probe)
        assert original['inputs_unchanged'] is True
        assert original['solution_sha256'] == sha(folder / 'input.sv') == sha(probe / 'dut.sv')
        assert original['tb_sha256'] == sha(tb) == sha(probe / 'tb.sv')
        assert original['runner_sha256'] == spec['dependency_hashes']['probe_runner.py']
        assert original['checks'] == parsed['checks']
        mismatches = original['mismatches']
        assert type(mismatches) is int and 0 <= mismatches <= parsed['checks']
        assert ((original['status'] == 'pass' and mismatches == 0) or
                (original['status'] == 'fail' and original['failure_kind'] == 'semantic_mismatch'
                 and mismatches > 0))
        assert [stage['name'] for stage in original['stages']] == ['xvlog', 'xelab', 'xsim']
        for stage in original['stages']:
            assert stage['returncode'] == 0 and not stage['timeout'] and not stage['launch_error']
            assert not stage['remaining_live_group']
            log = probe / (stage['name'] + '.log')
            assert stage['log'] == str(log)
            assert stage['log_sha256'] == sha(log) and stage['log_bytes'] == log.stat().st_size
        point = serial_feedback.measured_trace(
            (probe / 'xsim.log').read_text(encoding='utf-8', errors='replace'), parsed, mismatches)
        consumed = False
        if point is not None:
            if attempt == 0:
                assert len(requests) == 2, 'Measured mismatch must use the existing one-repair loop'
            assert read(folder / 'counterexample.json') == point
            text = serial_feedback.feedback_text(point)
            assert (folder / 'feedback.txt').read_text(encoding='utf-8') == text
            events = [e for e in trace if e.get('tool') == 'map_feedback' and e.get('round') == attempt]
            assert len(events) == 1 and events[0]['excerpt'] == text
            assert events[0]['repair_available'] == (attempt == 0)
            if attempt + 1 < len(requests):
                next_body = read(solve / 'requests' / str(attempt + 1) / 'request.json')
                assert next_body['messages'][1]['content'] == (
                    prompt + '\nPrevious candidate:\n' + code + '\nCandidate diagnostics:\n' + text)
                consumed = True
        else:
            assert not (folder / 'counterexample.json').exists() and not (folder / 'feedback.txt').exists()
            assert attempt == len(requests) - 1
        # The queue's existing terminal manifest binds every retained raw file.
        # This small addition explicitly ties the diagnostic to model output and
        # to the exact next request without reimplementing the queue or judge.
        names = ['input.sv', 'contract.json', 'probe/result.json', 'probe/adapter_receipt.json',
                 'probe/dut.sv', 'probe/tb.sv', 'probe/xvlog.log', 'probe/xelab.log', 'probe/xsim.log']
        if point is not None:
            names += ['counterexample.json', 'feedback.txt']
        records.append(dict(attempt=attempt, status=original['status'], checks=original['checks'],
                            mismatches=mismatches, counterexample_consumed=consumed,
                            model_response_sha256=requests[attempt]['response_sha256'],
                            evidence_sha256={name: sha(folder / name) for name in names}))
    return dict(applicable=True, actual_checks=records,
                counterexamples_consumed=sum(row['counterexample_consumed'] for row in records))
