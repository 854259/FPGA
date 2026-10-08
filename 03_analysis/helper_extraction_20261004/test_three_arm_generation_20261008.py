"""New routing controls only: synthetic FAKE receipts, no HTTP or native tools."""
import argparse
import copy
import itertools
import json
from pathlib import Path
import re
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import patch

import official_baseline_arm_20261005 as official
import official_baseline_scoring_20261005 as scoring
import three_arm_generation_20261008 as generation
import three_arm_queue_20261005 as queue


def save(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True)+'\n')


def rejected(function):
    try:
        function()
    except (AssertionError, subprocess.CalledProcessError):
        return
    raise AssertionError('Tampered evidence accepted')


def table_prompt():
    return ('I would like you to implement a module named TopModule with the following\n'
            'interface. All input and output ports are one bit unless otherwise\nspecified.\n\n'
            ' - input p\n - input r\n - output answer\n\n'
            'The module should implement a combinational circuit. Read the simulation\n'
            'waveforms to determine what the circuit does, then implement it.\n\ntime p r answer\n' +
            ''.join(f'{i*5}ns {p} {r} {p^r}\n' for i, (p, r) in enumerate(itertools.product((0, 1), repeat=2))))


def run_case(root, label, kind, vector_fixture):
    source = root/'sources'/label
    spec = generation.validate(source, label)
    case = root/('case_'+label+'_'+kind)
    case.mkdir()
    prompt = case/'prompt_only'; prompt.mkdir()
    text = table_prompt() if kind == 'table' else vector_fixture.read_text() if kind == 'vector' else 'Implement a registered input with a synchronous reset.\n'
    (prompt/'prompt.txt').write_text(text)
    out = case/'solve'
    received = 2 if label == 'A' else 1
    fake_commands = []

    def fake_command(argv, cwd, log, seconds):
        fake_commands.append(argv)
        Path(log).write_text('FAKE_NEW_ROUTING_CONTROL_NO_EDA\n')
        return dict(argv=argv, timeout=False, launch_error=None, remaining_live_group=[],
                    returncode=0, elapsed_s=0.0, log_sha256=official.sha(log),
                    log_bytes=Path(log).stat().st_size, fixture='FAKE_NO_EDA')

    def fake_baseline(args, paired):
        args.out.mkdir(); (args.out/'prompt_only').mkdir()
        (args.out/'prompt_only/prompt.txt').write_bytes((prompt/'prompt.txt').read_bytes())
        (args.out/'solution.v').write_text('module TopModule; endmodule\n')
        (args.out/'requests').mkdir()
        journal = []
        for index in range(received):
            folder = args.out/'requests'/str(index); folder.mkdir()
            save(folder/'request.json', dict(model=official.MODEL, temperature=0, top_p=1,
                                           max_tokens=8192, messages=[dict(role='user', content=text)]))
            save(folder/'response.json', dict(choices=[dict(message=dict(role='assistant', content='FAKE'))]))
            journal.append(dict(index=index, response_received=True, replayed=False,
                                request_sha256=official.sha(folder/'request.json'),
                                response_sha256=official.sha(folder/'response.json')))
        save(args.out/'requests.json', journal)
        (args.out/'trace.jsonl').write_text(''.join(json.dumps(dict(tool='llm', fixture='FAKE_NO_HTTP'))+'\n' for _ in journal))
        save(args.out/'worker_result.json', dict(complete=True, arm=args.arm,
             requests=received, actual_model_requests=received, solution_sha256=official.sha(args.out/'solution.v')))

    original_load = generation.load
    patches = []

    def load(name, path):
        if name == 'paired_owned':
            return SimpleNamespace(check_resource=lambda *args: None, owned_command=fake_command)
        implementation = original_load(name, path)
        if name == 'paired_pinned_worker':
            def dependency(name, path):
                if Path(path).name == 'map_runtime.py':
                    return SimpleNamespace(vivado_tool=lambda _: spec['compiler_tools']['xvlog']['path'])
                if Path(path).name == 'probe_runner.py':
                    return SimpleNamespace(ENVIRONMENT_ERROR=re.compile('FAKE_ENVIRONMENT_ERROR'))
                raise AssertionError('Unexpected dependency')
            patches.extend([patch.object(implementation.baseline, 'load', side_effect=dependency),
                            patch.object(implementation.baseline, 'run_worker', side_effect=fake_baseline),
                            patch.object(implementation.baseline, 'functional_feedback', return_value='')])
            for p in patches:
                p.start()
        return implementation

    args = SimpleNamespace(source_root=source, arm=label, task=prompt, out=out,
                           kit=root/'FAKE_KIT', resource_check=root/'FAKE_RESOURCE.json')
    try:
        with patch.object(generation, 'load', side_effect=load), \
             patch('urllib.request.urlopen', side_effect=AssertionError('No HTTP allowed')), \
             patch('subprocess.run', side_effect=AssertionError('No native process allowed')):
            generation.worker(args)
    finally:
        for p in reversed(patches):
            p.stop()

    before = {str(p.relative_to(out)): official.sha(p) for p in out.rglob('*') if p.is_file()}
    bound = scoring.eligible(out, prompt, label, source)
    assert bound['arm'] == label and bound['worker_arm'] == 'P'
    assert bound['client_request_attempts'] == (received if kind == 'model' else 0)
    assert len(fake_commands) == (0 if kind == 'model' else 1)
    assert before == {str(p.relative_to(out)): official.sha(p) for p in out.rglob('*') if p.is_file()}
    checks = ['fresh_route_'+label+'_'+kind, 'raw_result_preserved']
    rejected(lambda: scoring.eligible(out, prompt, 'B', source))
    rejected(lambda: scoring.eligible(out, prompt, 'P' if label == 'A' else 'A', source))
    checks += ['B_source_forbidden', 'wrong_source_arm_rejected']
    if kind != 'model':
        rejected(lambda: scoring.eligible(out, prompt, 'P'))
        solution = (out/'solution.v').read_bytes()
        raw = (out/'worker_result.json').read_bytes()
        (out/'solution.v').write_bytes(solution+b'// changed\n')
        result = json.loads(raw); result['solution_sha256'] = official.sha(out/'solution.v')
        save(out/'worker_result.json', result)
        rejected(lambda: scoring.eligible(out, prompt, label, source))
        (out/'solution.v').write_bytes(solution); (out/'worker_result.json').write_bytes(raw)
        save(out/'request.json', {'fixture': 'fake hidden request'})
        rejected(lambda: scoring.eligible(out, prompt, label, source))
        (out/'request.json').unlink()
        checks += ['legacy_zero_rejected', 'solution_and_hash_forgery_rejected', 'hidden_request_rejected']
    else:
        journal = (out/'requests.json').read_bytes()
        bad = json.loads(journal); bad[0]['response_received'] = False
        save(out/'requests.json', bad)
        rejected(lambda: scoring.eligible(out, prompt, label, source))
        (out/'requests.json').write_bytes(journal)
        checks.append('unconfirmed_model_call_rejected')
    assert before == {str(p.relative_to(out)): official.sha(p) for p in out.rglob('*') if p.is_file()}
    save(case/'CONTROL_RESULT.json', dict(passed=True, checks=checks, fake_only=True,
         new_model_requests=0, new_eda_commands=0, raw_files_preserved=True))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--arm', choices=['A', 'P'], required=True)
    parser.add_argument('--kind', choices=['table', 'vector', 'model'], required=True)
    parser.add_argument('--vector-fixture', type=Path, required=True)
    args = parser.parse_args()
    run_case(args.root, args.arm, args.kind, args.vector_fixture)
