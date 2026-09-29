"""Three frozen non-RTL transport probes; never a quality or parameter search.

Prepare plan.json offline with --prepare; --run consumes that exact plan once.
Both the runner and runtime hashes are frozen. An unsuccessful gate stops the run.
"""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import threading
import time
import urllib.request


ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    temp.replace(path)


def make_plan():
    bodies = []
    for name, text, cap, seconds, expected in (
        ('stream_answer', 'Compute 17 plus 25. Output only the decimal answer.', 128, 60, 'complete'),
        ('deadline_cancel', 'List every integer from 1 to 100000, one integer per line. Continue until all are listed.', 512, 2, 'deadline'),
        ('after_cancel', 'Compute 19 plus 23. Output only the decimal answer.', 128, 60, 'complete'),
    ):
        bodies.append(dict(name=name, seconds=seconds, expected=expected, body=dict(
            model='rtl-qwen27b-awq', messages=[dict(role='system', content='Follow the instruction.'),
                                             dict(role='user', content=text)],
            temperature=0, top_p=1.0, max_tokens=cap, thinking_token_budget=32,
            return_token_ids=True, stream=True, stream_options={'include_usage': True})))
    return dict(version=1, calls_max=3, wall_seconds=240, vram_limit_bytes=32000000000,
                idle_wait_seconds=30, runtime_sha256=digest(ROOT/'submission/runtime.py'),
                runner_sha256=digest(__file__), model_path='/workspace/rtl-models/qwen36-27b-awq',
                purpose='Transport/count/deadline/cancellation/VRAM only; no RTL scores or tuning',
                requests=bodies)


def idle(runtime, limit):
    until = time.monotonic() + limit
    while True:
        with urllib.request.urlopen(runtime.endpoint().removesuffix('/v1')+'/metrics', timeout=2) as r:
            text = r.read(1024*1024).decode()
        values = [float(line.rsplit(' ', 1)[1]) for line in text.splitlines()
                  if re.match(r'vllm:num_requests_(?:running|waiting)\{', line)]
        if len(values) == 2 and not any(values):
            return text
        if time.monotonic() >= until:
            raise RuntimeError('backend idle not verified; no next request')
        time.sleep(.1)


def run(out):
    plan = json.loads((out/'plan.json').read_text())
    if plan != make_plan():
        raise ValueError('frozen plan/code mismatch')
    os.environ['LLM_BASE_URL'] = 'http://127.0.0.1:8000/v1'
    os.environ['RTL_PROFILE'] = 'submission'
    spec = importlib.util.spec_from_file_location('probe_runtime', ROOT/'submission/runtime.py')
    runtime = importlib.util.module_from_spec(spec); spec.loader.exec_module(runtime)
    # A crashed run is not silently resumed; the started marker is immutable evidence.
    with (out/'started.json').open('x') as f:
        json.dump(dict(time=time.time(), plan_sha256=digest(out/'plan.json')), f)
    began = time.monotonic()
    status = dict(status='preflight', started_calls=0, completed_calls=0, requests=[])
    save(out/'status.json', status)
    memory = []
    stop_memory = threading.Event()
    resource_fault = threading.Event()
    def monitor():
        while not stop_memory.is_set():
            used = runtime.vram_gb()
            item = dict(elapsed_s=time.monotonic()-began, used_bytes=None if used is None else round(used*1024**3))
            memory.append(item)
            if item['used_bytes'] is None or item['used_bytes'] > plan['vram_limit_bytes']:
                resource_fault.set()
            stop_memory.wait(.05)
    watcher = threading.Thread(target=monitor, daemon=True)
    watcher.start()
    try:
        from transformers import AutoTokenizer
        tokenizer = AutoTokenizer.from_pretrained(plan['model_path'], local_files_only=True)
        opening = tokenizer.encode('<think>', add_special_tokens=False)
        closing = tokenizer.encode('</think>', add_special_tokens=False)
        assert len(opening) == len(closing) == 1
        for index, request in enumerate(plan['requests']):
            if resource_fault.is_set():
                raise RuntimeError('VRAM resource gate failed')
            if plan['wall_seconds'] - (time.monotonic()-began) < request['seconds'] + plan['idle_wait_seconds'] + 15:
                raise RuntimeError('insufficient remaining wall budget')
            before = idle(runtime, 2)
            (out/f'{index}-before-metrics.txt').write_text(before)
            prompt_ids = tokenizer.apply_chat_template(request['body']['messages'], tokenize=True, add_generation_prompt=True)
            assert len(prompt_ids) + request['body']['max_tokens'] <= 16384
            assert max(i for i, n in enumerate(prompt_ids) if n == opening[0]) > max(
                (i for i, n in enumerate(prompt_ids) if n == closing[0]), default=-1)
            with (out/f'{index}.started.json').open('x') as f:
                json.dump(dict(time=time.time(), request_sha256=hashlib.sha256(
                    json.dumps(request['body'], sort_keys=True).encode()).hexdigest()), f)
            status.update(status='request_running', started_calls=index+1, current=request['name'])
            save(out/'status.json', status)
            result = runtime.chat_stream(request['body'], out/f'{index}.sse', request['seconds'], resource_fault)
            result['name'] = request['name']
            result['expected_status'] = request['expected']
            result['reasoning_tokens_received'] = 0
            thinking = True
            for n in result['token_ids']:
                if n == opening[0]: thinking = True
                elif n == closing[0]: thinking = False
                elif thinking: result['reasoning_tokens_received'] += 1
            # Save before any assertion: failed gates retain the original response.
            save(out/f'{index}.result.json', result)
            after = idle(runtime, plan['idle_wait_seconds'])
            (out/f'{index}-after-metrics.txt').write_text(after)
            assert not resource_fault.is_set(), 'VRAM resource gate failed during request'
            assert result['status'] == request['expected'], 'unexpected transport status'
            assert result['elapsed_s'] <= request['seconds'] + .75, 'absolute deadline exceeded'
            if request['expected'] == 'complete':
                assert result['content'].strip() and result['finish_reason'] == 'stop'
                assert result['prompt_token_ids'] == prompt_ids, 'prompt IDs mismatch'
                assert len(result['token_ids']) == result['usage'].get('completion_tokens'), 'completion IDs mismatch'
                assert len(prompt_ids) == result['usage'].get('prompt_tokens'), 'prompt usage mismatch'
                assert result['reasoning_tokens_received'] <= 32, 'thinking boundary exceeded'
            # Intentional cancellation has unknown total usage; never invent it from received IDs.
            status['requests'].append(dict(name=request['name'], passed=True, elapsed_s=result['elapsed_s']))
            status['completed_calls'] = index+1
            save(out/'status.json', status)
        status['status'] = 'diagnostics_passed_not_rtl_acceptance'
    except Exception as exc:
        status.update(status='stopped', error=type(exc).__name__+': '+str(exc))
        raise
    finally:
        stop_memory.set(); watcher.join(timeout=2)
        save(out/'vram-samples.json', memory)
        status.update(elapsed_s=time.monotonic()-began, vram_peak_bytes=max(
            (x['used_bytes'] or 0 for x in memory), default=0))
        save(out/'status.json', status)
        print(json.dumps(status), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('output', type=Path)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--prepare', action='store_true')
    action.add_argument('--run', action='store_true')
    args = parser.parse_args()
    if args.prepare:
        args.output.mkdir(parents=True, exist_ok=True)
        with (args.output/'plan.json').open('x', encoding='utf-8') as f:
            json.dump(make_plan(), f, indent=2)
    else:
        run(args.output)
