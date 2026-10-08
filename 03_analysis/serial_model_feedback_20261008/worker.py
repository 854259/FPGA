"""AMD-only model worker with optional prompt-serial feedback, max one repair."""
import argparse
import ctypes
import json
from pathlib import Path
import sys

import baseline_worker
import serial_feedback


def bind(solve, selected_arm):
    """Read retained model replies; never call a model or a tool to verify them."""
    root, solve = Path(__file__).resolve().parent, Path(solve).resolve()
    assert selected_arm in ('A', 'P')
    inner = 'C' if selected_arm == 'A' else 'P'
    result = json.loads((solve / 'worker_result.json').read_text())
    assert result['complete'] and result['arm'] == inner
    runtime = baseline_worker.load('table_binding_runtime', root / 'package/agent/map_runtime.py')
    baseline = baseline_worker.load('table_binding_extract', root / 'package/baseline.py')
    prompt_dir = solve / 'prompt_only'
    prompt = (prompt_dir / 'prompt.txt').read_text(encoding='utf-8')
    interface = prompt_dir / 'interface.txt'
    if interface.is_file() and interface.read_text(encoding='utf-8').strip():
        prompt += '\n\nInterface:\n' + interface.read_text(encoding='utf-8')
    skill, repair = runtime.skill_texts()
    requests = json.loads((solve / 'requests.json').read_text())
    assert 1 <= len(requests) <= 2
    trace = [json.loads(line) for line in (solve / 'trace.jsonl').read_text().splitlines()]
    prior, last = None, None
    for index, receipt in enumerate(requests):
        folder = solve / 'requests' / str(index)
        assert receipt['index'] == index and receipt['response_received'] and not receipt['replayed']
        for name in ('request', 'response'):
            assert baseline_worker.sha(folder / (name + '.json')) == receipt[name + '_sha256']
        body = json.loads((folder / 'request.json').read_text())
        response = json.loads((folder / 'response.json').read_text())
        assert body['messages'][0] == dict(role='system', content=skill + ('\n' + repair if index else ''))
        assert len(body['messages']) == 2 and body['messages'][1]['role'] == 'user'
        user = body['messages'][1]['content']
        if index == 0:
            assert user == prompt
        else:
            prefix = prompt + '\nPrevious candidate:\n' + prior + '\nCandidate diagnostics:\n'
            assert user.startswith(prefix)
            diagnostics = [e.get('excerpt', '') for e in trace
                           if e.get('tool') in ('check_source', 'check_submodules', 'lint', 'map_feedback')]
            assert user[len(prefix):] in diagnostics, 'Repair lacks retained actual diagnostic'
        last = baseline.extract(response['choices'][0]['message'].get('content') or '', 'rtl')
        prior = last
    actual = (solve / 'solution.v').read_text(encoding='utf-8')
    declaration_fix = actual != last
    if declaration_fix:
        assert any(e.get('tool') == 'declaration_fix' and e.get('rc') == 0
                   and e.get('round') == len(requests) - 1 for e in trace)
        lint = [e for e in trace if e.get('tool') == 'lint' and e.get('round') == len(requests) - 1]
        assert len(lint) == 1 and lint[0]['rc'] != 0
        assert runtime.repair_ansi_declarations(last, lint[0]['excerpt']) == actual
        journal = json.loads((solve / 'compile_journal.json').read_text())
        assert journal[-1]['returncode'] == 0
        assert journal[-1]['source_before_sha256'] == journal[-1]['source_after_sha256'] == baseline_worker.sha(solve / 'solution.v')
    assert result['solution_sha256'] == baseline_worker.sha(solve / 'solution.v')
    return dict(outer_arm=selected_arm, worker_arm=inner, model_generated_rtl_bound=True,
                actual_model_responses=len(requests), declaration_fix=declaration_fix,
                solution_sha256=result['solution_sha256'])


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'bind':
        p = argparse.ArgumentParser()
        p.add_argument('--solve', type=Path, required=True)
        p.add_argument('--arm', choices=('A', 'P'), required=True)
        a = p.parse_args(sys.argv[2:])
        binding = bind(a.solve, a.arm)
        if a.arm == 'P':
            from serial_binding import bind_serial
            binding['serial_feedback_binding'] = bind_serial(a.solve, Path(__file__).resolve().parent)
        print(json.dumps(binding))
        sys.exit(0)
    parser = argparse.ArgumentParser()
    for name in ('out', 'kit', 'resource-check'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--task', required=True)
    parser.add_argument('--arm', choices=('C', 'P'), required=True)
    args = parser.parse_args()
    assert sys.platform == 'linux' and sys.dont_write_bytecode
    assert ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0
    root = Path(__file__).resolve().parent
    spec = json.loads((root / 'RUN_SPEC.json').read_text())
    # A copied worker alone is not an execution admission.
    assert spec.get('model_generated_rtl_only') is True
    assert spec['source_hashes'].get('worker.py') == baseline_worker.sha(__file__)
    assert spec['source_hashes'].get('serial_feedback.py') == baseline_worker.sha(root / 'serial_feedback.py')
    for name, digest in spec['source_hashes'].items():
        assert baseline_worker.sha(root / name) == digest
    for name, digest in spec['dependency_hashes'].items():
        assert baseline_worker.sha(Path(spec['dependencies_cloud']) / name) == digest
    paired = baseline_worker.load('serial_feedback_owned', Path(spec['dependencies_cloud']) / 'paired_checkpoint.py')
    serial_feedback.run_worker(baseline_worker, args, paired)
