"""Owned fresh-generation worker; original maximum of one repair."""
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
import first_system_request
import point_feedback
import shared_budget
import edge_dispatch
import edge_feedback
import phase_feedback
import phase_context
import edge_contract

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


def functional_feedback(prompt, code, out, attempt, paired, task, candidate=False):
    parser = edge_dispatch if candidate else prompt_map
    renderer = phase_feedback if candidate else point_feedback
    contract = parser.parse(prompt)
    if contract['status'] != 'supported' or re.search(r'\$[A-Za-z_]|`include', code):
        return ''
    folder = out / ('map_check_' + str(attempt))
    folder.mkdir()
    inputs = folder/'inputs'/task
    inputs.mkdir(parents=True)
    source, tb = folder/'input.sv', inputs/'tb.sv'
    source.write_text(code, encoding='utf-8', newline='\n')
    tb.write_text(parser.render_tb(contract, task), encoding='utf-8', newline='\n')
    result = paired.oracle(dict(task=task, checks=contract['checks'], tb=str(tb.relative_to(ROOT))),
                           source, folder/'probe')
    save(folder/'contract.json', contract)
    if result['status'] == 'pass':
        if candidate and contract.get('family')=='edge':
            rows,bound=phase_context.context((folder/'probe/xsim.log').read_text(),contract,edge_contract)
            assert bound is None
        assert result['mismatches'] == 0
        return ''
    if result['failure_kind'] != 'semantic_mismatch':
        raise RuntimeError('Functional checker failed; no fabricated model feedback')
    point = parser.counterexample((folder/'probe/xsim.log').read_text(), contract)
    save(folder/'counterexample.json', point)
    feedback = renderer.render(contract, result, point)
    save(folder/'feedback.json', dict(text=feedback))
    return feedback


def run_worker(args, paired):
    budget = shared_budget.SolveBudget(300)
    original_owned = paired.owned_command
    root, out = ROOT, args.out.resolve()
    spec = json.loads((root/'RUN_SPEC.json').read_text())
    source = Path(os.environ['PAIRED_TASK_DIR']).resolve()
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
        budget.remaining()
        index = len(requests); assert index < 2
        body = json.loads(request.data)
        skill, repair = runtime.skill_texts()
        assert body['messages'][0] == dict(role='system', content=skill+('\n'+repair if index else '')+(first_system_request.SYSTEM_SUFFIX if getattr(args, 'first_system_arm', None) == 'P' and index == 0 else ''))
        assert body['model'] == spec['model'] and body['temperature'] == 0
        assert body['max_tokens'] == 8192 and body['top_p'] == 1
        folder = out/'requests'/str(index); folder.mkdir(parents=True)
        save(folder/'request.json', body)
        entry = dict(index=index, replayed=False, response_received=False, dispatch_started=False,
                     request_sha256=sha(folder/'request.json'))
        requests.append(entry); save(out/'requests.json', requests)
        tick = time.monotonic()
        gate(); paired.model_idle('http://127.0.0.1:8000/v1', spec['model'])
        sys.path.insert(0, '/workspace/team/tools/task-fifo-20261004')
        import activity
        ledger=ROOT/'activity'
        event_id='paired-fresh:'+spec['identity']+':'+str(out.relative_to(ROOT))+':'+str(index)
        activity.append(ledger,'calls',event_id+':started','实际新生成模型调用开始；只有题面/接口、原技能及当前候选真实诊断，无参考/TB/控制稿。',dict(task=args.task,arm=args.arm,round=index,**entry))
        try:
            bounded_kwargs = budget.http_timeout(positional, kwargs)
            entry['dispatch_started'] = True
            save(out/'requests.json', requests)
            with original_open(request, *positional, **bounded_kwargs) as response: raw=response.read()
        except Exception as error:
            entry.update(error=type(error).__name__,elapsed_s=time.monotonic()-tick)
            save(out/'requests.json',requests)
            activity.append(ledger,'calls',event_id+':unconfirmed','实际模型调用未收到回复，保留失败不重抽。',dict(task=args.task,arm=args.arm,round=index,**entry))
            if budget.expired():
                raise shared_budget.BudgetExpired('Shared budget ended with an unconfirmed request') from error
            raise RuntimeError('Actual fresh model request failed; do not resample') from error
        (folder/'response.json').write_bytes(raw)
        payload = json.loads(raw); choice = payload['choices'][0]
        entry.update(response_received=True, response_sha256=sha(folder/'response.json'),
                     elapsed_s=time.monotonic()-tick, finish_reason=choice.get('finish_reason'),
                     response_id=payload.get('id'), usage=payload.get('usage'))
        save(out/'requests.json', requests)
        activity.append(ledger,'calls',event_id+':received','实际新生成/原一次修复回复收到；正文只在私有证据。',dict(task=args.task,arm=args.arm,round=index,**entry))
        budget.remaining()
        return io.BytesIO(raw)

    def compiler(argv, *positional, **kwargs):
        if not isinstance(argv, list) or '--sv' not in argv or Path(argv[0]).name not in ('xvlog','xvlog.bat'):
            return original_run(argv, *positional, **kwargs)
        budget.remaining()
        gate()
        folder = Path(kwargs['cwd'])
        evidence=out/'compile_receipts'/str(len(compiles));evidence.mkdir(parents=True)
        (evidence/'source_before.sv').write_bytes(Path(argv[-1]).read_bytes())
        log=evidence/'owned_compile.log'
        result = paired.owned_command(argv, folder, log, 60)
        (evidence/'source_after.sv').write_bytes(Path(argv[-1]).read_bytes())
        compiles.append(dict(argv=argv, source_sha256=sha(argv[-1]), source_before_sha256=sha(evidence/'source_before.sv'),source_after_sha256=sha(evidence/'source_after.sv'), **result))
        save(out/'compile_journal.json', compiles)
        if result['launch_error'] or result['remaining_live_group']:
            raise RuntimeError('Native compiler supervision failure')
        if result['timeout']:
            budget.remaining()
            raise RuntimeError('Native compiler supervision failure')
        return subprocess.CompletedProcess(argv, result['returncode'], log.read_text(errors='replace'))

    def feedback(prompt, code, target, attempt):
        budget.remaining()
        gate()
        return functional_feedback(prompt, code, target, attempt, paired, args.task, candidate=True)

    runtime.map_feedback = feedback
    previous = Path.cwd()
    try:
        urllib.request.urlopen, subprocess.run = transport, compiler
        paired.owned_command = budget.owned_operation(original_owned)
        os.chdir(work); started = time.monotonic()
        runtime.worker(prompt_only, out)
        assert 1 <= len(requests) <= 2 and all(row['response_received'] for row in requests)
        budget.remaining()
        save(out/'worker_result.json', dict(complete=True, arm=args.arm,
            requests=len(requests), actual_model_requests=len(requests),
            elapsed_s=time.monotonic()-started, solution_sha256=sha(out/'solution.v')))
    except shared_budget.BudgetExpired:
        save(out/'SHARED_BUDGET_EXIT.json', budget.exit_receipt(out/'requests.json', __file__))
        raise
    finally:
        paired.owned_command = original_owned
        urllib.request.urlopen, subprocess.run = original_open, original_run
        os.chdir(previous)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    for name in ['out','kit','resource-check']: p.add_argument('--'+name, type=Path, required=True)
    p.add_argument('--task', required=True); p.add_argument('--arm', choices=['A','C','P'], required=True)
    args = p.parse_args()
    assert sys.platform == 'linux' and ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)==0
    spec = json.loads((ROOT/'RUN_SPEC.json').read_text())
    for name, digest in spec['source_hashes'].items(): assert sha(ROOT/name)==digest
    for name, digest in spec['dependency_hashes'].items(): assert sha(Path(spec['dependencies_cloud'])/name)==digest
    paired = load('map_owned', Path(spec['dependencies_cloud'])/'paired_checkpoint.py')
    run_worker(args, paired)
