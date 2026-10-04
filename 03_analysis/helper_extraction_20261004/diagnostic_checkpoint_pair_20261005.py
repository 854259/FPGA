"""Q5: all original-arm compiler-repair checkpoints; frozen initial reply, live repairs.

Development mechanism preflight, not independent validation or a complete batch.
Only prompt/skills/initial response reach workers. Judge assets appear afterwards.
"""
import argparse
from collections import Counter
import ctypes
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
import zipfile
from diagnostic_feedback_20261005 import compact_diagnostics
from diagnostic_worker_gate_20261005 import candidate_source

ARCHIVE_SHA = '64ace96d59d9a1802513f20be3e21c191786ba04d2054b9ab4072900893c7616'
BEST_SHA = '22e32251664f31a6a8a51b9d443860442359aa2588b187ea816c6973c8cd08e7'
CANDIDATE_SHA = '1b3e183e80235c9662c87e90ea91dfa1fe3759089f84295e4d4a6191fdbd0c66'
MODEL = 'Qwen3.6-27B-Q4_K_M'
ENDPOINT = 'http://127.0.0.1:8000/v1'
HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, data):
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def inventory(z):
    """Exhaustive outcome-independent selection: failed lint followed by a repair request."""
    names = set(z.namelist())
    manifest = json.loads(z.read('ARCHIVE_MANIFEST.json'))['files']
    def read(name):
        data = z.read(name); item = manifest[name]
        assert hashlib.sha256(data).hexdigest() == (item['sha256'] if isinstance(item, dict) else item), name
        return data
    counts = Counter(); eligible = []; rows = 0
    for name in sorted(names):
        if not name.startswith('run/samples/') or not name.endswith('/worker/trace.jsonl'):
            continue
        rows += 1
        base = name[:-len('trace.jsonl')]
        arm, task = name.split('/')[2:4]
        events = [json.loads(line) for line in read(name).decode().splitlines() if line]
        repairs = next(e['repairs'] for e in events if e['tool'] == 'agent_meta')
        for event in events:
            if event['tool'] != 'lint' or event.get('rc') in (0, None):
                continue
            rnd = event['round']
            fixed = any(e['tool'] == 'declaration_fix' and e.get('round') == rnd and e.get('rc') == 0 for e in events)
            request = base + 'requests/' + str(rnd + 1) + '/request.json'
            category = 'declaration_success' if fixed else 'budget_exhausted' if rnd >= repairs else 'next_request_captured' if request in names else 'no_captured_next_request'
            counts[arm + '/' + category] += 1
            if category != 'next_request_captured':
                continue
            body = json.loads(read(request))
            assert body['messages'][1]['content'].rsplit('\nCandidate diagnostics:\n', 1)[-1] == event['excerpt']
            first_start = next(e['ts'] for e in events if e['tool'] == 'llm_start' and e['round'] == 0)
            first_end = next(e['ts'] for e in events if e['tool'] == 'llm' and e['round'] == 0)
            eligible.append(dict(arm=arm, task=task, round=rnd, base=base,
                first_request_sha256=hashlib.sha256(read(base + 'requests/0/request.json')).hexdigest(),
                first_response_sha256=hashlib.sha256(read(base + 'requests/0/response.json')).hexdigest(),
                archived_initial_model_s=first_end - first_start))
    assert rows == 312
    selected = [row for row in eligible if row['arm'] == 'A']
    assert len(selected) == 7 and all(row['round'] == 0 for row in selected)
    assert counts['A/declaration_success'] == 7 and counts['A/budget_exhausted'] == 2
    return read, dict(rows=rows, counts=dict(counts), eligible=eligible, selected=selected)


def worker(a):
    assert sys.platform == 'linux'
    sys.dont_write_bytecode = True
    runtime = load('q5_runtime', a.package / 'agent/runtime.py')
    sys.modules['baseline'] = load('baseline', a.package / 'baseline.py')
    expected = json.loads((a.input / 'request.json').read_text())
    first_response = (a.input / 'response.json').read_bytes()
    assert sha(a.package / 'agent/runtime.py') == (BEST_SHA if a.arm == 'A' else CANDIDATE_SHA)
    a.out.mkdir(parents=True, exist_ok=False)
    task = a.out / 'prompt_only'; task.mkdir()
    (task / 'prompt.txt').write_text(expected['messages'][1]['content'])
    real_urlopen = runtime.urllib.request.urlopen
    real_run = runtime.subprocess.run
    requests = []; replies = []; compiles = []; attempted = 0; confirmed = 0
    def urlopen(req, timeout=None):
        nonlocal attempted, confirmed
        index = len(requests); body = json.loads(req.data)
        assert req.full_url == ENDPOINT + '/chat/completions'
        assert index < 2, 'no implicit extra request'
        save(a.out / ('request_' + str(index) + '.json'), body)
        requests.append(body)
        if index == 0:
            assert body == expected, 'initial request differs from frozen capture'
            (a.out / 'response_0.json').write_bytes(first_response)
            replies.append(dict(replayed=True, elapsed_s=0))
            return io.BytesIO(first_response)
        assert attempted == 0
        assert all(body[k] == expected[k] for k in ('model', 'temperature', 'top_p', 'max_tokens'))
        attempted += 1
        save(a.out / 'actual_post_attempt.json', dict(attempts=attempted, started_at=time.time()))
        tick = time.monotonic()
        with real_urlopen(req, timeout=135) as response:
            data = response.read()
        payload = json.loads(data)
        assert isinstance(payload.get('choices'), list) and payload['choices']
        (a.out / 'response_1.json').write_bytes(data)
        confirmed += 1
        replies.append(dict(replayed=False, elapsed_s=time.monotonic() - tick,
                            usage=payload.get('usage'), finish=payload['choices'][0].get('finish_reason')))
        return io.BytesIO(data)
    def compile_run(argv, **kwargs):
        assert Path(argv[0]).name == 'xvlog' and len(compiles) < 4
        record = a.out / ('lint_' + str(len(compiles))); record.mkdir()
        source = Path(argv[-1]); before = source.read_bytes()
        (record / 'source_before.sv').write_bytes(before)
        tick = time.monotonic()
        result = real_run(argv, **kwargs)
        (record / 'stdout.log').write_text(result.stdout)
        row = dict(returncode=result.returncode, elapsed_s=time.monotonic() - tick,
                   source_sha256=hashlib.sha256(before).hexdigest(), argv=argv)
        compiles.append(row); save(record / 'receipt.json', row)
        return result
    runtime.urllib.request.urlopen = urlopen
    runtime.subprocess.run = compile_run
    os.environ.update(MODEL_NAME=MODEL, LLM_BASE_URL=ENDPOINT, RTL_REPAIRS='1',
                      RTL_TEMPERATURE='0', RTL_MAX_TOKENS='8192',
                      VIVADO_BIN='/workspace/AMD/2026.1/Vivado/bin')
    tick = time.monotonic()
    try:
        runtime.worker(task, a.out)
    finally:
        save(a.out / 'worker_receipt.json', dict(actual_attempts=attempted, actual_responses=confirmed,
            logical_requests=len(requests), response_metadata=replies, compiles=compiles,
            elapsed_s=time.monotonic() - tick,
            runtime_sha256=sha(a.package / 'agent/runtime.py'),
            solution_sha256=sha(a.out / 'solution.v') if (a.out / 'solution.v').exists() else None))


def run(a):
    assert sys.platform == 'linux' and ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0) == 0
    sys.dont_write_bytecode = True
    assert sha(a.archive) == ARCHIVE_SHA
    protocol = json.loads((HERE / 'DIAGNOSTIC_Q5_SPEC.json').read_text())
    assert protocol['archive_sha256'] == ARCHIVE_SHA and protocol['model'] == MODEL
    assert protocol['new_model_call_cap'] == 14 and protocol['stage_timeout_s'] == 3600
    assert sha(HERE / 'diagnostic_feedback_20261005.py') == 'a6cc0b71dc3aad780dc3528472bed6b80b00d10ed6a42b2d4af469c50356d849'
    assert sha(HERE / 'diagnostic_worker_gate_20261005.py') == '6a331e15a23b2f9ab3734f12de9c71d7a69f456db8ae3a16e27f8206a2297f22'
    helper = REPO / '03_analysis/selective_runtime_integration_20261003/paired_next/paired_checkpoint.py'
    assert sha(helper) == '78e9b3e144f2bd43ebab371e15ac3946017686db890a8e45891db7a386841e1c'
    paired = load('q5_supervision', helper)
    paired.check_resource(a.resource_check, a.kit, first=True)
    assert sha(a.kit / 'official_eval.py') == '53d1d4ff661ca6c3e27bc1d20a2328815dc39e281abc3a93757099b6e60bf797'
    tool_dir = '/workspace/AMD/2026.1/Vivado/bin'
    os.environ['VIVADO_BIN'] = tool_dir
    os.environ['PATH'] = tool_dir + os.pathsep + os.environ['PATH']
    for tool in ('xvlog', 'xelab', 'xsim', 'vivado'):
        assert Path(shutil.which(tool)).resolve() == (Path(tool_dir) / tool).resolve()
    a.out.mkdir(parents=True, exist_ok=False)
    tick = time.monotonic()
    report = dict(complete=False, valid=False, rows=[], error=None, actual_attempts=0,
        actual_responses=0, call_cap=14, stage_timeout_s=3600, worker_timeout_s=150,
        protocol_sha256=sha(HERE / 'DIAGNOSTIC_Q5_SPEC.json'), driver_sha256=sha(Path(__file__)),
        full_batch_complete=False, independent_natural_tasks=0, retries=0,
        scope='All seven known original-arm compile-repair checkpoints; paired continuation, not fresh full-score evidence')
    try:
        with zipfile.ZipFile(a.archive) as z:
            read, inv = inventory(z)
            assert [case['task'] for case in inv['selected']] == protocol['tasks']
            save(a.out / 'INVENTORY.json', inv)
            for arm in ('A', 'C'):
                package = a.out / ('package_' + arm)
                for name in sorted(z.namelist()):
                    if not name.startswith('run/package/') or name.endswith('/'):
                        continue
                    rel = Path(name).relative_to('run/package')
                    assert '..' not in rel.parts
                    target = package / rel; target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(read(name))
                source = (package / 'agent/runtime.py').read_text()
                assert hashlib.sha256(source.encode()).hexdigest() == BEST_SHA
                if arm == 'C':
                    source = candidate_source(source)
                    assert hashlib.sha256(source.encode()).hexdigest() == CANDIDATE_SHA
                    (package / 'agent/runtime.py').write_text(source)
            for case in inv['selected']:
                inputs = a.out / 'inputs' / case['task']; inputs.mkdir(parents=True)
                (inputs / 'request.json').write_bytes(read(case['base'] + 'requests/0/request.json'))
                (inputs / 'response.json').write_bytes(read(case['base'] + 'requests/0/response.json'))
            # All selection and bytes are fixed before the first new request; no judge assets yet.
            save(a.out / 'INPUT_BINDING.json', {str(p.relative_to(a.out)): sha(p) for p in (a.out / 'inputs').rglob('*') if p.is_file()})
        for index, case in enumerate(inv['selected']):
            row = dict(task=case['task'], archived_initial_model_s=case['archived_initial_model_s'], arms={})
            report['rows'].append(row)
            shared = a.out / 'workspaces' / case['task']; shared.mkdir(parents=True)
            # Both arms compile at the exact same path; archive/move only this task's completed scratch.
            for arm in (('A', 'C') if index % 2 == 0 else ('C', 'A')):
                assert time.monotonic() - tick < 3300 and report['actual_attempts'] < 14
                paired.check_resource(a.resource_check, a.kit)
                paired.model_idle(ENDPOINT, MODEL)
                out = a.out / 'workers' / case['task'] / arm; out.parent.mkdir(parents=True, exist_ok=True)
                command = [sys.executable, '-B', str(Path(__file__).resolve()), 'worker', '--arm', arm,
                    '--input', str(a.out / 'inputs' / case['task']), '--package', str(a.out / ('package_' + arm)), '--out', str(out)]
                supervision = paired.owned_command(command, shared, out.parent / (arm + '.supervisor.log'), 150)
                receipt = json.loads((out / 'worker_receipt.json').read_text()) if (out / 'worker_receipt.json').exists() else {}
                row['arms'][arm] = dict(supervision=supervision, receipt=receipt)
                # Attempt files survive even if a worker is killed before writing its receipt.
                report['actual_attempts'] = len(list((a.out / 'workers').rglob('actual_post_attempt.json')))
                report['actual_responses'] = len(list((a.out / 'workers').rglob('response_1.json')))
                save(a.out / 'summary.json', report)
                assert supervision['returncode'] == 0 and not supervision['timeout'] and not supervision['remaining_live_group'], 'worker environment/timeout failure'
                assert receipt['actual_attempts'] == receipt['actual_responses'] == 1 and receipt['logical_requests'] == 2, 'incomplete or unexpected model request'
                paired.model_idle(ENDPOINT, MODEL)
                evidence = out / 'compiler_work'; evidence.mkdir()
                for path in shared.glob('compile-*'):
                    assert path.is_dir() and not path.is_symlink() and path.resolve().parent == shared.resolve()
                    shutil.move(str(path), str(evidence / path.name))
                print(json.dumps(dict(phase='worker', task=case['task'], arm=arm, completed_workers=sum(len(r['arms']) for r in report['rows']), actual_requests=report['actual_attempts'])), flush=True)
            left, right = [a.out / 'workers' / case['task'] / arm for arm in ('A', 'C')]
            assert (left / 'response_0.json').read_bytes() == (right / 'response_0.json').read_bytes()
            assert json.loads((left / 'request_0.json').read_text()) == json.loads((right / 'request_0.json').read_text())
            assert (left / 'lint_0/source_before.sv').read_bytes() == (right / 'lint_0/source_before.sv').read_bytes()
            before = json.loads((left / 'request_1.json').read_text()); after = json.loads((right / 'request_1.json').read_text())
            raw = (left / 'lint_0/stdout.log').read_text()
            prefix = before['messages'][1]['content'].rsplit('\nCandidate diagnostics:\n', 1)[0]
            assert after['messages'][1]['content'] == prefix + '\nCandidate diagnostics:\n' + compact_diagnostics(raw), 'pair changed more than diagnostic formatting'
            after['messages'][1]['content'] = before['messages'][1]['content']
            assert after == before
            row['paired_requests_verified'] = True
        # Workers have all ended. Only now expose frozen reference/TB assets to the scoring side.
        judge = load('q5_official_eval', a.kit / 'official_eval.py')
        assert judge.verify_upstream() == 'afd135e7ba5f6ec4c6d77e7c927c894327537801'
        with zipfile.ZipFile(a.archive) as z:
            manifest = json.loads(z.read('ARCHIVE_MANIFEST.json'))['files']
            for row in report['rows']:
                task = a.out / 'judge_tasks' / row['task']; task.mkdir(parents=True)
                prefix = 'kit/bench/tasks_veval/' + row['task'] + '/'
                for name in z.namelist():
                    if not name.startswith(prefix) or name.endswith('/'):
                        continue
                    data = z.read(name); item = manifest[name]
                    assert hashlib.sha256(data).hexdigest() == (item['sha256'] if isinstance(item, dict) else item)
                    rel = Path(name[len(prefix):]); assert '..' not in rel.parts and not rel.is_absolute()
                    target = task / rel; target.parent.mkdir(parents=True, exist_ok=True); target.write_bytes(data)
                for arm in ('A', 'C'):
                    paired.check_resource(a.resource_check, a.kit)
                    dst = a.out / 'grades' / row['task'] / arm; dst.mkdir(parents=True)
                    solution = a.out / 'workers' / row['task'] / arm / 'solution.v'
                    verdict = judge.judge_sample(task, solution, dst, dst / 'verdict.json', 90)
                    assert not verdict.get('tool_error') and not verdict.get('suspected_silent_degradation')
                    logs = '\n'.join(p.read_text(errors='replace') for p in dst.rglob('*.log'))
                    if solution.read_text().strip():
                        assert re.search(r'(?:INFO|ERROR): \[VRFC ', logs), 'no real compiler evidence'
                    assert not re.search(r'可执行文件不存在|command not found|No such file or directory|license checkout failed', logs, re.I)
                    row['arms'][arm]['verdict'] = verdict
                print(json.dumps(dict(phase='scored', task=row['task'], levels={k:v['verdict']['level'] for k,v in row['arms'].items()})), flush=True)
                save(a.out / 'summary.json', report)
        repairs = sum(r['arms']['A']['verdict']['level'] < 3 and r['arms']['C']['verdict']['level'] == 3 for r in report['rows'])
        regressions = sum(r['arms']['A']['verdict']['level'] == 3 and r['arms']['C']['verdict']['level'] < 3 for r in report['rows'])
        continuation_s = {arm: sum(r['arms'][arm]['receipt']['elapsed_s'] for r in report['rows']) for arm in ('A', 'C')}
        inherited_initial_s = sum(r['archived_initial_model_s'] for r in report['rows'])
        reconstructed_s = {arm: inherited_initial_s + continuation_s[arm] for arm in ('A', 'C')}
        cost_ratio = reconstructed_s['C'] / reconstructed_s['A']
        report.update(complete=True, valid=True, repairs=repairs, regressions=regressions,
            unchanged_functional=7 - repairs - regressions,
            continuation_worker_s=continuation_s, archived_initial_model_s=inherited_initial_s,
            reconstructed_worker_s=reconstructed_s, reconstructed_cost_ratio=cost_ratio,
            candidate_eligible_for_further_research=repairs > 0 and regressions == 0 and cost_ratio <= 1.10,
            deployed=False, source_archive_unchanged=sha(a.archive) == ARCHIVE_SHA)
        paired.check_resource(a.resource_check, a.kit)
        paired.model_idle(ENDPOINT, MODEL)
    except BaseException as exc:
        report['error'] = type(exc).__name__ + ': ' + str(exc)
        raise
    finally:
        report['elapsed_s'] = time.monotonic() - tick
        save(a.out / 'summary.json', report)
        print(json.dumps({k:v for k,v in report.items() if k != 'rows'}), flush=True)


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('mode', choices=['run', 'worker'])
    for flag in ('archive', 'resource-check', 'kit', 'package', 'input'):
        p.add_argument('--' + flag, type=Path)
    p.add_argument('--arm', choices=['A', 'C']); p.add_argument('--out', type=Path, required=True)
    args = p.parse_args()
    worker(args) if args.mode == 'worker' else run(args)
