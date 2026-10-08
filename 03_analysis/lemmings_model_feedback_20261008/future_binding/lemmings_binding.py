"""Bind retained Lemmings native events after the unchanged worker.bind proof.

AMD-only when invoked by the owner. No model, worker replay or EDA execution.
Qualification copies must be labelled simulated by their outer control report;
native bytes must still originate from actual exact-DUT native evidence.
"""
import json
from pathlib import Path
import re

import baseline_worker
import lemmings_feedback


OFFICIAL_EXTRACTOR_SHA256 = '537783e39db22079c33c19af475dbdb760a29ff1656a48c481d434131f84fb51'
CHECKER_SHA256 = 'e178d62a61bd279bb3dfcf4a17357a90e8a26b4537da83ba0f6e3714ae0a753a'


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def bind_lemmings(solve, root):
    """P arm only; callers first apply the unchanged worker.bind model proof."""
    solve, root = Path(solve).resolve(), Path(root).resolve()
    prompt = (solve / 'prompt_only/prompt.txt').read_text(encoding='utf-8')
    interface = solve / 'prompt_only/interface.txt'
    if interface.is_file() and interface.read_text(encoding='utf-8').strip():
        prompt += '\n\nInterface:\n' + interface.read_text(encoding='utf-8')
    spec = read(root / 'RUN_SPEC.json')
    sha = baseline_worker.sha
    assert sha(root / 'package/baseline.py') == OFFICIAL_EXTRACTOR_SHA256
    assert sha(root / 'lemmings_feedback.py') == CHECKER_SHA256
    assert Path(lemmings_feedback.__file__).resolve() == root / 'lemmings_feedback.py'
    for name in ('package/baseline.py', 'lemmings_feedback.py', 'lemmings_binding.py'):
        assert spec['source_hashes'][name] == sha(root / name)
    parsed = lemmings_feedback.parse(prompt)
    requests = read(solve / 'requests.json')
    assert 1 <= len(requests) <= 2
    trace = [json.loads(line) for line in (solve / 'trace.jsonl').read_text().splitlines()]
    baseline = baseline_worker.load('lemmings_binding_extract', root / 'package/baseline.py')
    present = {p.name for p in solve.glob('lemmings_check_*')}
    assert present <= {'lemmings_check_' + str(i) for i in range(len(requests))}
    if parsed is None:
        assert not present
        return dict(applicable=False, actual_checks=[], counterexamples_consumed=0)
    records = []
    for attempt in range(len(requests)):
        folder = solve / ('lemmings_check_' + str(attempt))
        response_path = solve / 'requests' / str(attempt) / 'response.json'
        assert sha(response_path) == requests[attempt]['response_sha256']
        response = read(response_path)
        code = baseline.extract(response['choices'][0]['message'].get('content') or '', 'rtl')
        lint = [e for e in trace if e.get('tool') == 'lint' and e.get('round') == attempt]
        events = [e for e in trace if e.get('tool') == 'map_feedback' and e.get('round') == attempt]
        assert len(lint) <= 1
        should_check = (len(lint) == 1 and lint[0]['rc'] == 0 and not
                        re.search(r'\$[A-Za-z_]|`(?:include|define)|\bR2Probe\b', code))
        assert folder.exists() == should_check
        if not should_check:
            if not lint or lint[0]['rc'] != 0:
                # The actual runtime cannot call map_feedback before a successful
                # lint. Do not silently accept retained diagnostics with no check.
                assert not events
            # With successful lint but a prohibited source token the Lemmings
            # hook abstains; preserve the original fallback's possible event.
            continue
        assert folder.is_dir() and not folder.is_symlink()
        assert (folder / 'input.sv').read_bytes() == code.encode('utf-8')
        assert read(folder / 'contract.json') == parsed
        paths = list((folder / 'inputs').glob('*/tb.sv'))
        assert len(paths) == 1
        tb, task = paths[0], paths[0].parent.name
        assert tb.read_bytes() == lemmings_feedback.render_tb(parsed, task).encode('utf-8')
        probe = folder / 'probe'
        original, adapter = read(probe / 'result.json'), read(probe / 'adapter_receipt.json')
        extras = {'inherited_runner_path', 'inherited_runner_sha256', 'oracle_adapter_path',
                  'oracle_adapter_sha256', 'inherited_result_path', 'inherited_result_sha256'}
        assert {k: v for k, v in adapter.items() if k not in extras} == original
        assert original.get('simulated', False) is False
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
        assert (probe / 'dut.sv').read_bytes() == code.encode('utf-8')
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
            assert stage.get('simulated', False) is False
            assert stage['returncode'] == 0 and stage['timeout'] is False and stage['launch_error'] is None
            assert stage['remaining_live_group'] == []
            log = probe / (stage['name'] + '.log')
            assert stage['log'] == str(log)
            assert stage['log_sha256'] == sha(log) and stage['log_bytes'] == log.stat().st_size
        trace_binding = dict(prompt_sha256=parsed['prompt_sha256'],
            source_sha256=sha(folder / 'input.sv'), tb_sha256=sha(tb),
            log_sha256=sha(probe / 'xsim.log'), result_path='probe/result.json',
            result_sha256=sha(probe / 'result.json'), checks=parsed['checks'], mismatches=mismatches)
        assert read(folder / 'trace_binding.json') == trace_binding
        log_text = (probe / 'xsim.log').read_text(encoding='utf-8', errors='replace')
        summaries = re.findall(
            r'^R2_PROBE_RESULT task=(\S+) checks=(\d+) mismatches=(\d+)\s*$', log_text, re.M)
        assert len(summaries) == 1, 'Native completion summary missing or ambiguous'
        found_task, found_checks, found_mismatches = summaries[0]
        assert (found_task, int(found_checks), int(found_mismatches)) == (
            task, parsed['checks'], mismatches), 'Native summary contradicts retained result'
        point = lemmings_feedback.measured_trace(log_text, parsed, mismatches)
        consumed = False
        if point is not None:
            if attempt == 0:
                assert len(requests) == 2, 'Measured mismatch must use the existing one-repair loop'
            assert read(folder / 'counterexample.json') == point
            text = lemmings_feedback.feedback_text(point)
            assert (folder / 'feedback.txt').read_bytes() == text.encode('utf-8')
            assert len(events) == 1 and events[0]['excerpt'] == text
            assert events[0]['repair_available'] == (attempt == 0)
            if attempt + 1 < len(requests):
                next_path = solve / 'requests' / str(attempt + 1) / 'request.json'
                assert sha(next_path) == requests[attempt + 1]['request_sha256']
                assert read(next_path)['messages'][1]['content'] == (
                    prompt + '\nPrevious candidate:\n' + code + '\nCandidate diagnostics:\n' + text)
                consumed = True
        else:
            assert not (folder / 'counterexample.json').exists() and not (folder / 'feedback.txt').exists()
            assert not events and attempt == len(requests) - 1
        names = ['input.sv', 'contract.json', 'trace_binding.json', 'probe/result.json',
                 'probe/adapter_receipt.json', 'probe/dut.sv', 'probe/tb.sv',
                 'probe/xvlog.log', 'probe/xelab.log', 'probe/xsim.log']
        if point is not None:
            names += ['counterexample.json', 'feedback.txt']
        records.append(dict(attempt=attempt, status=original['status'], checks=original['checks'],
                            mismatches=mismatches, counterexample_consumed=consumed,
                            first_bad_event=point['event'] if point is not None else None,
                            first_bad_event_kind=point['event_kind'] if point is not None else None,
                            model_response_sha256=requests[attempt]['response_sha256'],
                            exact_extracted_dut_sha256=sha(folder / 'input.sv'),
                            evidence_sha256={name: sha(folder / name) for name in names}))
    return dict(applicable=True, actual_checks=records,
                counterexamples_consumed=sum(row['counterexample_consumed'] for row in records))
