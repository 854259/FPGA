"""Owned checkpoint worker: fixed first reply, one original repair at most."""
import argparse
import ctypes
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import urllib.request
import prompt_map

ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.pending')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    temporary.replace(path)


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def functional_feedback(prompt, code, out, attempt, paired, task):
    contract = prompt_map.parse(prompt)
    if contract['status'] != 'supported' or re.search(r'\$[A-Za-z_]|`include', code):
        return ''
    folder = out / ('map_check_' + str(attempt))
    folder.mkdir()
    inputs = folder/'inputs'/task
    inputs.mkdir(parents=True)
    source, tb = folder/'input.sv', inputs/'tb.sv'
    source.write_text(code, encoding='utf-8', newline='\n')
    tb.write_text(prompt_map.render_tb(contract, task), encoding='utf-8', newline='\n')
    result = paired.oracle(dict(task=task, checks=contract['checks'], tb=str(tb.relative_to(ROOT))),
                           source, folder/'probe')
    save(folder/'contract.json', contract)
    if result['status'] == 'pass':
        assert result['mismatches'] == 0
        return ''
    if result['failure_kind'] != 'semantic_mismatch':
        raise RuntimeError('Functional checker failed; no fabricated model feedback')
    point = prompt_map.counterexample((folder/'probe/xsim.log').read_text(), contract)
    save(folder/'counterexample.json', point)
    inputs = ', '.join(k+'='+str(v) for k, v in point['inputs'].items())
    return ('ERROR: Candidate simulation disagrees with the supplied Karnaugh map. '
            'At '+inputs+', '+point['output']+' should be '+str(point['expected'])+
            ', but the candidate produced '+point['observed']+'.')


def run_worker(args, paired):
    root, out = ROOT, args.out.resolve()
    spec = json.loads((root/'RUN_SPEC.json').read_text())
    source = root/'raw_evidence/inputs'/args.task
    runtime = load('map_'+args.arm+'_runtime', root/'package/agent'/
                   ('runtime.py' if args.arm == 'A' else 'map_runtime.py'))
    paired.REPO = root
    paired.INHERITED_ORACLE = Path(spec['dependencies_cloud'])/'probe_runner.py'
    out.mkdir(parents=True, exist_ok=False)
    work, prompt_only = out/'work', out/'prompt_only'
    work.mkdir(); prompt_only.mkdir()
    for name in ['prompt.txt', 'interface.txt']:
        if (source/name).exists(): (prompt_only/name).write_bytes((source/name).read_bytes())
    (out/'solution.v').write_text(''); (out/'trace.jsonl').write_text('')
    requests, compiles = [], []
    save(out/'requests.json', requests)
    original_open, original_run = urllib.request.urlopen, subprocess.run

    def gate():
        paired.check_resource(args.resource_check, args.kit)

    def transport(request, *positional, **kwargs):
        url = request.full_url if isinstance(request, urllib.request.Request) else str(request)
        if not url.endswith('/chat/completions'):
            return original_open(request, *positional, **kwargs)
        assert url == 'http://127.0.0.1:8000/v1/chat/completions'
        assert request.get_method() == 'POST'
        index = len(requests); assert index < 2
        body = json.loads(request.data)
        skill, repair = runtime.skill_texts()
        assert body['messages'][0] == dict(role='system', content=skill+('\n'+repair if index else ''))
        assert body['model'] == spec['model'] and body['temperature'] == 0
        assert body['max_tokens'] == 8192 and body['top_p'] == 1
        folder = out/'requests'/str(index); folder.mkdir(parents=True)
        save(folder/'request.json', body)
        entry = dict(index=index, replayed=index==0, response_received=False,
                     request_sha256=sha(folder/'request.json'))
        requests.append(entry); save(out/'requests.json', requests)
        tick = time.monotonic()
        if index == 0:
            assert body == json.loads((source/'initial_request.json').read_text())
            raw = (source/'initial_response.json').read_bytes()
        else:
            gate(); paired.model_idle('http://127.0.0.1:8000/v1', spec['model'])
            with original_open(request, *positional, **kwargs) as response: raw = response.read()
        (folder/'response.json').write_bytes(raw)
        payload = json.loads(raw); choice = payload['choices'][0]
        entry.update(response_received=True, response_sha256=sha(folder/'response.json'),
                     elapsed_s=time.monotonic()-tick, finish_reason=choice.get('finish_reason'),
                     response_id=payload.get('id'), usage=payload.get('usage'))
        save(out/'requests.json', requests)
        if index:
            sys.path.insert(0, '/workspace/team/tools/task-fifo-20261004')
            import activity
            activity.append(Path('/workspace/team/activity/fpga_owner'), 'calls',
                'map-feedback:'+spec['identity']+':'+args.task+':'+args.arm+':'+str(index),
                '题面反例触发原一次模型复查；不发送官方TB/参考/判定。',
                dict(task=args.task, arm=args.arm, round=index, **entry))
        return io.BytesIO(raw)

    def compiler(argv, *positional, **kwargs):
        if not isinstance(argv, list) or '--sv' not in argv or Path(argv[0]).name not in ('xvlog','xvlog.bat'):
            return original_run(argv, *positional, **kwargs)
        gate()
        folder = Path(kwargs['cwd']); log = folder/'owned_compile.log'
        result = paired.owned_command(argv, folder, log, 60)
        compiles.append(dict(argv=argv, source_sha256=sha(argv[-1]), **result))
        save(out/'compile_journal.json', compiles)
        if result['timeout'] or result['launch_error'] or result['remaining_live_group']:
            raise RuntimeError('Native compiler supervision failure')
        return subprocess.CompletedProcess(argv, result['returncode'], log.read_text(errors='replace'))

    def feedback(prompt, code, target, attempt):
        gate()
        return functional_feedback(prompt, code, target, attempt, paired, args.task)

    runtime.map_feedback = feedback
    previous = Path.cwd()
    try:
        urllib.request.urlopen, subprocess.run = transport, compiler
        os.chdir(work); started = time.monotonic()
        runtime.worker(prompt_only, out)
        assert 1 <= len(requests) <= 2 and all(row['response_received'] for row in requests)
        save(out/'worker_result.json', dict(complete=True, arm=args.arm,
            requests=len(requests), actual_model_requests=len(requests)-1,
            elapsed_s=time.monotonic()-started, solution_sha256=sha(out/'solution.v')))
    finally:
        urllib.request.urlopen, subprocess.run = original_open, original_run
        os.chdir(previous)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    for name in ['out','kit','resource-check']: p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--task', required=True); p.add_argument('--arm', choices=['A','C'], required=True)
    args = p.parse_args()
    assert sys.platform == 'linux' and ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)==0
    spec = json.loads((ROOT/'RUN_SPEC.json').read_text())
    for name, digest in spec['source_hashes'].items(): assert sha(ROOT/name)==digest
    for name, digest in spec['dependency_hashes'].items(): assert sha(Path(spec['dependencies_cloud'])/name)==digest
    paired = load('map_owned', Path(spec['dependencies_cloud'])/'paired_checkpoint.py')
    run_worker(args, paired)
