"""AMD-only, zero-model causal probe of I1 bypassing a successful original repair.

Constructed development data, not a natural accuracy estimate or full batch.
The original worker receives fixed replies; I1 replays byte-identical requests.
"""
import argparse
import ctypes
import io
import json
import os
import shutil
import sys
import time
from pathlib import Path
from pilot import REPO, load, materials, save, sha


def original_worker(args):
    runtime = load('bypass_original_runtime', args.package/'agent/runtime.py')
    baseline = load('baseline', args.package/'baseline.py')
    sys.modules['baseline'] = baseline
    expected = json.loads((args.input/'request.json').read_text())
    replies = json.loads((args.input/'constructed_replies.json').read_text())
    args.out.mkdir(parents=True, exist_ok=False)
    task = args.out/'prompt_only_task'; task.mkdir()
    (task/'prompt.txt').write_text(expected['messages'][1]['content'])
    requests = []

    def fixed_urlopen(request, timeout=None):
        index = len(requests); body = json.loads(request.data)
        assert request.full_url == 'http://127.0.0.1:8000/v1/chat/completions'
        assert index < 2
        assert all(body[k] == expected[k] for k in ('model','temperature','top_p','max_tokens'))
        if index == 0:
            assert body == expected
        else:
            assert body['messages'][1]['content'].startswith(expected['messages'][1]['content']+'\nPrevious candidate:\n')
        tick = time.monotonic()
        payload = {'choices':[{'message':{'content':replies[index]},'finish_reason':'stop'}]}
        save(args.out/('request_'+str(index)+'.json'), body)
        save(args.out/('response_'+str(index)+'.json'), payload)
        requests.append(dict(round=index, elapsed_s=time.monotonic()-tick, constructed=True))
        return io.StringIO(json.dumps(payload))

    # All worker HTTP is replaced, including repair: no fallback to a real endpoint.
    runtime.urllib.request.urlopen = fixed_urlopen
    os.environ.update(MODEL_NAME=expected['model'], LLM_BASE_URL='http://127.0.0.1:8000/v1',
                      RTL_REPAIRS='1', RTL_TEMPERATURE='0', RTL_MAX_TOKENS='8192')
    os.chdir(args.out); tick = time.monotonic()
    try:
        runtime.worker(task, args.out)
    finally:
        save(args.out/'worker_receipt.json', dict(actual_model_calls=0, constructed=True,
             requests=requests, logical_worker_requests=len(requests), elapsed_s=time.monotonic()-tick,
             solution_sha256=sha(args.out/'solution.v') if (args.out/'solution.v').exists() else None))


def run(args):
    if sys.platform != 'linux' or ctypes.CDLL(None, use_errno=True).prctl(36,1,0,0,0):
        raise RuntimeError('AMD Linux subreaper required')
    spec = json.loads((Path(__file__).parent/'CONTINUATION_SPEC.json').read_text())
    protected = {str(args.kit/k):v for k,v in spec['kit_hashes'].items()}
    protected.update({str(args.package/k):v for k,v in spec['package_hashes'].items()})
    assert all(sha(p)==h for p,h in protected.items())
    paired = load('bypass_owned', REPO/'03_analysis/selective_runtime_integration_20261003/paired_next/paired_checkpoint.py')
    args.out.mkdir(parents=True, exist_ok=False)
    package = args.out/'package'; shutil.copytree(args.package, package)
    cases, positive, negative, tb = materials()
    variants = dict((name,reply) for name,reply,_,_ in cases)
    prompt = 'Module name: TopModule. Input a is one bit; output y is one bit. Combinationally y = ~a. No clock or state. Return synthesizable Verilog.'
    body = dict(model='Qwen3.6-27B-Q4_K_M', messages=[
        dict(role='system',content=(package/'skill/rtl-generation/SKILL.md').read_text()),
        dict(role='user',content=prompt)], temperature=0, top_p=1.0, max_tokens=8192)
    report = dict(complete=False, valid=False, model_calls=0, rows=[], controls={}, error=None,
                  scope='constructed causal development probe; not independent natural designs',
                  full_batch_complete=False, frozen_source_sha256=sha(Path(__file__)), protected=protected)
    tick = time.monotonic()
    try:
        # Fixed order, including repeat of the counterexample. Repeat adds no independent sample.
        for name, variant in [('wrong_first','wrong_helper_preserved'),
                              ('correct_first','helper_after'),
                              ('wrong_repeat','wrong_helper_preserved')]:
            sample = args.out/'samples'/name; sample.mkdir(parents=True)
            save(sample/'request.json', body)
            save(sample/'constructed_replies.json', [variants[variant], '```verilog\n'+positive+'```\n'])
            row = dict(name=name, variant=variant, arms={}); report['rows'].append(row)
            for arm in ('original','I1'):
                out = sample/arm
                if arm == 'original':
                    cmd = [sys.executable,'-B',str(Path(__file__).resolve()),'worker']
                else:
                    cmd = [sys.executable,'-B',str(Path(__file__).parent/'full_pair.py'),'worker',
                           '--arm','elaborated_helpers','--replay-worker',str(sample/'original')]
                cmd += ['--kit',str(args.kit),'--package',str(package),'--input',str(sample),'--out',str(out)]
                supervision = paired.owned_command(cmd, args.out, sample/(arm+'.log'), 120)
                if supervision['returncode'] != 0 or supervision['timeout'] or supervision['remaining_live_group']:
                    raise RuntimeError('worker execution or cleanup failure: '+name+'/'+arm)
                receipt = json.loads((out/'worker_receipt.json').read_text())
                assert receipt['actual_model_calls'] == 0
                row['arms'][arm] = dict(receipt=receipt, supervision=supervision)
            assert (sample/'original/request_0.json').read_bytes() == (sample/'I1/request_0.json').read_bytes()
            assert (sample/'original/response_0.json').read_bytes() == (sample/'I1/response_0.json').read_bytes()
            print(json.dumps(dict(phase='workers_complete',name=name)), flush=True)
        # All workers terminate before the truth table or grading files are materialized.
        assets = args.out/'judge_assets/HelperGate'; assets.mkdir(parents=True)
        (assets/'tb.sv').write_text(tb)
        task = dict(task='HelperGate',checks=4,tb=str(assets/'tb.sv'))
        for label, source in [('positive',positive),('negative',negative)]:
            path=assets/(label+'.sv'); path.write_text(source)
            report['controls'][label] = paired.oracle(task,path,args.out/'controls'/label)
        assert report['controls']['positive']['status']=='pass'
        assert report['controls']['negative']['failure_kind']=='semantic_mismatch'
        for row in report['rows']:
            sample=args.out/'samples'/row['name']
            for arm in ('original','I1'):
                verdict=paired.oracle(task,sample/arm/'solution.v',sample/'grades'/arm)
                assert verdict['status'] in ('pass','fail') and verdict['failure_kind'] in (None,'semantic_mismatch')
                row['arms'][arm]['verdict']=verdict
            row['regression']=row['arms']['original']['verdict']['status']=='pass' and row['arms']['I1']['verdict']['status']=='fail'
            save(sample/'pair.json',row)
            print(json.dumps(dict(name=row['name'], regression=row['regression'],
                 requests={k:v['receipt']['logical_worker_requests'] for k,v in row['arms'].items()})),flush=True)
        assert all(sha(p)==h for p,h in protected.items())
        report.update(complete=True,valid=True,protected_unchanged=True,
                      counterexample_reproduced=report['rows'][0]['regression'] and report['rows'][2]['regression'],
                      causal_correct_helper_passes=all(v['verdict']['status']=='pass' for v in report['rows'][1]['arms'].values()))
    except BaseException as exc:
        report['error']=type(exc).__name__+': '+str(exc)
        raise
    finally:
        report['elapsed_s']=time.monotonic()-tick
        save(args.out/'summary.json',report)


if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('mode',choices=['run','worker'])
    for name in ('kit','package','out'): p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--input',type=Path)
    a=p.parse_args(); original_worker(a) if a.mode=='worker' else run(a)
