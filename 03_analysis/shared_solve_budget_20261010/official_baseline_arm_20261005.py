"""AMD-only direct official baseline arm; preserve upstream bytes and failures."""
import argparse
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import sys
import shared_budget
from urllib.parse import urlsplit


OFFICIAL = {
    'baseline.py': '537783e39db22079c33c19af475dbdb760a29ff1656a48c481d434131f84fb51',
    'run_baseline.sh': '5c46c40d32c0cf4c4e1dc52ae12e60f8396a0deccafaa4e6f69d7316a3482e75',
}
MODEL = 'Qwen3.6-27B-Q4_K_M'
PAIRED = Path('/workspace/team/runs/fpga_teammate/diagnostic_Q5_20261005_865876a/source/03_analysis/selective_runtime_integration_20261003/paired_next/paired_checkpoint.py')
PAIRED_SHA = '78e9b3e144f2bd43ebab371e15ac3946017686db890a8e45891db7a386841e1c'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')


def resource_module():
    assert sys.platform == 'linux' and sha(PAIRED) == PAIRED_SHA
    spec = importlib.util.spec_from_file_location('baseline_arm_resource', PAIRED)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_arm(official, task, out, resource, endpoint, seconds=300):
    """Engineering tests may supply another local port; production fixes :8000."""
    parsed = urlsplit(endpoint)
    assert (parsed.scheme, parsed.hostname, parsed.path) == ('http', '127.0.0.1', '/v1')
    assert parsed.port and not parsed.username and not parsed.password
    assert not parsed.query and not parsed.fragment and 0 < seconds <= 300
    official, task, out = map(Path, (official, task, out))
    assert not out.exists() and (task/'prompt.txt').is_file()
    for name, digest in OFFICIAL.items():
        assert sha(official/name) == digest, name
    out.mkdir(parents=True)
    package, prompt = out/'official', out/'prompt_only'
    package.mkdir(); prompt.mkdir()
    for name in OFFICIAL:
        shutil.copyfile(official/name, package/name)
    for name in ['prompt.txt', 'interface.txt']:
        if (task/name).is_file():
            shutil.copyfile(task/name, prompt/name)
    input_hashes = {p.name: sha(p) for p in prompt.iterdir()}
    observer = Path(__file__).with_name('official_baseline_observed_20261005.py').resolve()
    assert observer.is_file()
    # Preserve the original shell and Python files; use a scoped Python launcher
    # to install the observer explicitly before running that same baseline.py.
    python = shutil.which('python3'); assert python
    receipts, bin_dir = out/'transport', out/'bin'
    receipts.mkdir(); bin_dir.mkdir()
    launcher = bin_dir/'python3'
    launcher.write_text('#!/bin/sh\nexec '+shlex.quote(python)+' -B '+shlex.quote(str(observer))+' "$@"\n')
    launcher.chmod(0o700)
    argv = ['/usr/bin/env', 'NO_PROXY=127.0.0.1', 'no_proxy=127.0.0.1',
            'LLM_BASE_URL='+endpoint, 'MODEL_NAME='+MODEL,
            'PATH='+str(bin_dir)+os.pathsep+os.environ['PATH'], 'BASELINE_RECEIPTS='+str(receipts),
            'TRACK=rtl', 'PYTHONDONTWRITEBYTECODE=1', '/bin/bash',
            str(package/'run_baseline.sh'), str(prompt), str(out/'output')]
    save(out/'LAUNCH.json', dict(argv=argv, input_sha256=input_hashes,
         official_sha256=OFFICIAL, deadline_s=seconds, source_sha256=sha(__file__),
         observer_sha256=sha(observer), original_python=python,
         retries=0, skill_used=False, baseline_tool_calls=0))
    command = resource.owned_command(argv, out, out/'baseline.log', seconds)
    save(out/'COMMAND.json', command)
    assert not command['remaining_live_group']
    assert {p.name: sha(p) for p in prompt.iterdir()} == input_hashes
    assert all(sha(package/name) == digest for name, digest in OFFICIAL.items())
    trace_path, solution = out/'output/trace.jsonl', out/'output/solution.v'
    trace = [json.loads(line) for line in trace_path.read_text().splitlines()] if trace_path.exists() else []
    llm = [row for row in trace if row.get('tool') == 'llm']
    if trace:
        assert len(trace) == 2 and trace[0]['tool'] == 'baseline_meta' and len(llm) == 1
        meta = trace[0]
        assert meta['script_sha256'] == OFFICIAL['baseline.py']
        assert (meta['temperature'], meta['top_p'], meta['max_tokens'], meta['track']) == (0, 1, 8192, 'rtl')
        assert meta['served_model'] in [MODEL, None]
    response_confirmed = len(llm) == 1 and 'error' not in llm[0]
    transport_error = llm[0].get('error') if llm else None
    bootstrap = receipts/'BOOTSTRAP.json'
    recorder_ready = bootstrap.is_file() and json.loads(bootstrap.read_text()).get('ready') is True
    request_dirs = list(receipts.glob('request_*'))
    assert len(request_dirs) <= 1
    attempts = []
    for folder in request_dirs:
        state = json.loads((folder/'STATE.json').read_text())
        assert state['request_sha256'] == sha(folder/'request.bin')
        if state['response_body_complete']:
            assert state['response_sha256'] == sha(folder/'response.bin')
        attempts.append(state)
    if trace:
        assert recorder_ready and len(attempts) == 1
    failed = command['timeout'] or command['launch_error'] or command['returncode'] != 0 or not trace or not recorder_ready
    result = dict(schema='official_baseline_direct_arm_v1', arm='official_B',
                  complete=not failed, transport_ok=bool(response_confirmed and not failed),
                  timeout=command['timeout'], launch_error=command['launch_error'],
                  returncode=command['returncode'], transport_error=transport_error,
                  observed_llm_trace_events=len(llm), confirmed_model_responses=int(response_confirmed),
                  actual_post_count='unknown_without_server_receipt',
                  client_request_attempts=len(attempts) if recorder_ready else None,
                  client_attempt_definition='durable pre-urlopen attempt; not proof of server receipt or inference completion',
                  complete_http_bodies=sum(x['response_body_complete'] for x in attempts),
                  recorder_ready=recorder_ready, transport_receipts=attempts,
                  unconfirmed_call=bool(attempts) and not response_confirmed,
                  solve_elapsed_s=command['elapsed_s'], retry_count=0,
                  solution_present=solution.exists(), solution_sha256=sha(solution) if solution.exists() else None,
                  trace_sha256=sha(trace_path) if trace_path.exists() else None,
                  finish=llm[0].get('finish') if llm else None,
                  empty_content=llm[0].get('empty_content') if llm else None,
                  official_sha256=OFFICIAL, input_sha256=input_hashes,
                  functional_grade=None, full_batch=False)
    save(out/'RESULTS.json', result)
    return result


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--kit', type=Path, required=True)
    p.add_argument('--task', type=Path, required=True)
    p.add_argument('--out', type=Path, required=True)
    p.add_argument('--resource-check', type=Path, required=True)
    args = p.parse_args()
    resource = resource_module()
    # This child may start after earlier rows in the same admitted guard lease.
    resource.check_resource(args.resource_check, args.kit)
    budget = shared_budget.SolveBudget(300,
        parent_started=shared_budget.parent_started_from_environment())
    assert ctypes.CDLL(None, use_errno=True).prctl(36,1,0,0,0)==0
    original_owned = resource.owned_command
    try:
        resource.owned_command = budget.owned_operation(original_owned)
        result = run_arm(args.kit/'submission', args.task.resolve(), args.out.resolve(),
                         resource, 'http://127.0.0.1:8000/v1', seconds=budget.remaining())
    finally:
        resource.owned_command = original_owned
    budget.remaining()
    resource.check_resource(args.resource_check, args.kit)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
