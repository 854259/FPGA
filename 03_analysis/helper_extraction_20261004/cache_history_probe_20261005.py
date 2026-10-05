"""AMD-only bounded cache-path diagnosis, never a scored RTL experiment.

Use archived solver requests only. No reference, testbench, grades or repair calls.
An observed cache-path contrast is not an explanation of all historical drift.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
import urllib.request
import zipfile


def sha(data):
    return hashlib.sha256(data).hexdigest()


def save(path, value):
    path.write_text(json.dumps(value, indent=2) + '\n')


def prepare(a):
    assert sys.platform == 'linux'
    assert sha(a.archive.read_bytes()) == 'ac3b27f553bbf274d2edc875a7a3354b42741a9861ca409b37b779d1c6067055'
    metadata = json.loads(a.metadata.read_text())
    assert metadata['complete'] and metadata['pairs'] == 156
    assert metadata['checks']['request_equal'] == 156
    eligible = [r for r in metadata['rows'] if not r['content_equal'] and r['cached_tokens_equal']
                and max(r[s]['completion_tokens'] for s in ('old', 'new')) <= 512
                and all(r[s]['finish_reason'] == 'stop' for s in ('old', 'new'))]
    eligible.sort(key=lambda r:r['new']['request_sha256'])
    assert len(eligible) >= 6
    a.out.mkdir(exist_ok=False)
    inputs = []
    with zipfile.ZipFile(a.archive) as archive:
        for i, row in enumerate(eligible[:6]):
            name = 'run/results/samples/A/' + row['task'] + '/worker/requests/0/request.json'
            raw = archive.read(name)
            assert sha(raw) == row['new']['request_sha256']
            body = json.loads(raw)
            assert body['temperature'] == 0 and body['max_tokens'] == 8192
            assert 'cache_prompt' not in body
            target = a.out / ('request_%02d.json' % i)
            target.write_bytes(raw)
            inputs.append(dict(index=i, task=row['task'], path=str(target), sha256=sha(raw),
                               exposure='historical_development_engineering_only'))
    spec = dict(source_commit=a.source_commit, driver_sha256=sha(Path(__file__).read_bytes()),
        source_archive_sha256=sha(a.archive.read_bytes()), metadata_sha256=sha(a.metadata.read_bytes()),
        selection='Among different old/new replies with equal cache counts and both stop <=512 tokens, choose first six sorted by archived request SHA256; no grade access.',
        eligible_count=len(eligible), inputs=inputs, schedule=['C1', 'W1', 'C2', 'W2'],
        max_model_requests=24, max_http_wait_s=80, supervisor_s=90,
        stage_timeout_s=1800, reserve_s=120, retries=0, eda_calls=0,
        question='Does cold recomputation versus immediate warm reuse change identical greedy requests, and is each path repeatable in this bounded control?',
        stop='Stop on missing response, truncation, metadata/integrity/resource mismatch or insufficient remaining time, not on content differences.',
        limits='Six already-seen requests, four cache-path calls each; not a full batch, five independent solves or a quality comparison. No server restart or baseline change.')
    save(a.out / 'RUN_SPEC.json', spec)
    print(json.dumps(dict(prepared=True, eligible=len(eligible), spec_sha256=sha((a.out/'RUN_SPEC.json').read_bytes()))))


def request_one(a):
    a.out.mkdir(exist_ok=False)
    request = json.loads(a.request.read_text())
    request['cache_prompt'] = a.mode.startswith('W')
    raw = json.dumps(request).encode()
    (a.out/'request.json').write_bytes(raw)
    journal = dict(actual_post_attempted=True, response_received=False, mode=a.mode,
                   request_sha256=sha(raw), started_at=time.time())
    save(a.out/'CALL.json', journal)
    tick = time.monotonic()
    try:
        req = urllib.request.Request('http://127.0.0.1:8000/v1/chat/completions', data=raw,
                                     headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req, timeout=80) as response:
            data = response.read()
        (a.out/'response.json').write_bytes(data)
        journal.update(response_received=True, response_sha256=sha(data))
    except Exception as error:
        journal.update(error=type(error).__name__ + ': ' + str(error))
        raise
    finally:
        journal.update(elapsed_s=time.monotonic()-tick)
        save(a.out/'CALL.json', journal)


def run(a):
    assert sys.platform == 'linux'
    assert sha(a.spec.read_bytes()) == a.spec_sha256
    spec = json.loads(a.spec.read_text())
    assert sha(Path(__file__).read_bytes()) == spec['driver_sha256']
    assert sha(a.paired.read_bytes()) == '78e9b3e144f2bd43ebab371e15ac3946017686db890a8e45891db7a386841e1c'
    imp = importlib.util.spec_from_file_location('cache_probe_owned', a.paired)
    resource = importlib.util.module_from_spec(imp)
    imp.loader.exec_module(resource)
    resource.check_resource(a.resource_check, a.kit, first=True)
    for item in spec['inputs']:
        assert sha(Path(item['path']).read_bytes()) == item['sha256']
    a.out.mkdir(exist_ok=False)
    tick = time.monotonic()
    result = dict(complete=False, valid=False, scope=spec['limits'], source_commit=spec['source_commit'],
                  spec_sha256=a.spec_sha256, actual_model_requests=0, received_responses=0,
                  rows=[], task_comparisons=[], eda_calls=0, full_batch_complete=False, independent_tasks=0)

    def checkpoint():
        calls = [json.loads(p.read_text()) for p in a.out.glob('task_*/**/CALL.json')]
        result.update(actual_model_requests=sum(c['actual_post_attempted'] for c in calls),
                      received_responses=sum(c['response_received'] for c in calls), elapsed_s=time.monotonic()-tick)
        save(a.out/'summary.json', result)
        print(json.dumps({k:result[k] for k in ('actual_model_requests','received_responses','elapsed_s','complete')}), flush=True)

    try:
        checkpoint()
        for item in spec['inputs']:
            task_out = a.out / ('task_%02d' % item['index'])
            task_out.mkdir()
            for mode in spec['schedule']:
                assert time.monotonic()-tick < spec['stage_timeout_s']-spec['reserve_s']
                assert result['actual_model_requests'] < spec['max_model_requests']
                resource.check_resource(a.resource_check, a.kit)
                out = task_out/mode
                command = [sys.executable, '-B', str(Path(__file__)), 'request', '--request', item['path'],
                           '--mode', mode, '--out', str(out)]
                receipt = resource.owned_command(command, task_out, task_out/(mode+'.log'), spec['supervisor_s'])
                save(task_out/(mode+'_supervision.json'), receipt)
                checkpoint()
                assert receipt['returncode'] == 0 and not receipt['timeout'] and not receipt['remaining_live_group'], 'Request worker did not exit cleanly'
                call = json.loads((out/'CALL.json').read_text())
                assert call['response_received'], 'No confirmed response; preserve and stop, no retry'
                body = json.loads((out/'request.json').read_text())
                assert body.pop('cache_prompt') == mode.startswith('W')
                assert body == json.loads(Path(item['path']).read_text())
                response = json.loads((out/'response.json').read_text())
                choice, usage, timings = response['choices'][0], response['usage'], response['timings']
                assert response['model'] == 'Qwen3.6-27B-Q4_K_M'
                assert response['system_fingerprint'] == 'b1-c13fcbf'
                assert choice['finish_reason'] == 'stop', 'Truncated diagnostic is invalid, do not expand budget'
                assert timings['cache_n'] == usage['prompt_tokens_details']['cached_tokens']
                assert timings['cache_n'] + timings['prompt_n'] == usage['prompt_tokens']
                assert timings['predicted_n'] == usage['completion_tokens']
                assert (timings['cache_n'] > 0) if mode.startswith('W') else (timings['cache_n'] == 0)
                content = choice['message']['content']
                assert isinstance(content, str) and content
                result['rows'].append(dict(index=item['index'], task=item['task'], mode=mode,
                    content_sha256=sha(content.encode()), request_sha256=call['request_sha256'],
                    response_sha256=call['response_sha256'], cached_tokens=timings['cache_n'],
                    evaluated_prompt_tokens=timings['prompt_n'], completion_tokens=usage['completion_tokens'],
                    elapsed_s=call['elapsed_s'], prompt_ms=timings['prompt_ms'], generation_ms=timings['predicted_ms']))
                resource.check_resource(a.resource_check, a.kit)
                checkpoint()
            values = {r['mode']:r['content_sha256'] for r in result['rows'] if r['index']==item['index']}
            result['task_comparisons'].append(dict(index=item['index'], task=item['task'],
                cold_repeat_equal=values['C1']==values['C2'], warm_repeat_equal=values['W1']==values['W2'],
                cross_path_equal_first=values['C1']==values['W1'], cross_path_equal_second=values['C2']==values['W2']))
        assert result['actual_model_requests'] == result['received_responses'] == 24
        result.update(complete=True, valid=True)
    except Exception as error:
        result['error'] = type(error).__name__ + ': ' + str(error)
        raise
    finally:
        checkpoint()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['prepare','request','run'])
    for name in ('archive','metadata','out','request','spec','paired','kit','resource-check'):
        parser.add_argument('--'+name, type=Path)
    for name in ('source-commit','spec-sha256','mode'):
        parser.add_argument('--'+name)
    args = parser.parse_args()
    {'prepare':prepare,'request':request_one,'run':run}[args.action](args)
