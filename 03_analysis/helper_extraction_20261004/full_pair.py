"""Authorized AMD full-worker pairing with a shared, captured initial reply."""
import argparse
import ctypes
import io
import json
import os
import shutil
import sys
import tarfile
import time
import urllib.request
from pathlib import Path
from types import SimpleNamespace
from pilot import REPO, load, save, sha
from replay_best import BEST


def worker(args):
    runtime=load('full_pair_runtime',args.package/'agent/runtime.py')
    baseline=load('baseline',args.package/'baseline.py');sys.modules['baseline']=baseline
    original=baseline.extract;selections=[]
    if args.arm=='retained_helpers':
        extension=load('full_pair_extension',REPO/'03_analysis/semantic_repair_20261004/complete_module_extract.py')
        lexer=load('full_pair_lexer',REPO/'03_analysis/selective_runtime_integration_20261003/package/agent/signedness_selector.py')
        detector=load('full_pair_detector',args.kit/'submission/agent/runtime.py')
        def extract(text,track):
            if track!='rtl':return original(text,track)
            result,record=extension.extract_hierarchy(text,SimpleNamespace(extract=original),lexer._strip_noncode,detector.undefined_submodules)
            selections.append(record);return result
        baseline.extract=extract
    args.out.mkdir(parents=True,exist_ok=False)
    expected=json.loads((args.input/'request.json').read_text())
    task=args.out/'prompt_only_task';task.mkdir();(task/'prompt.txt').write_text(expected['messages'][1]['content'])
    real_urlopen=urllib.request.urlopen;requests=[];actual_calls=0;response_count=0
    def controlled_urlopen(request,timeout=None):
        nonlocal actual_calls,response_count
        body=json.loads(request.data);round_index=len(requests)
        assert request.full_url=='http://127.0.0.1:8000/v1/chat/completions' and round_index<2
        assert body['model']==expected['model'] and body['temperature']==0 and body['top_p']==1 and body['max_tokens']==8192
        if round_index==0:assert body==expected
        else:assert body['messages'][1]['content'].startswith(expected['messages'][1]['content']+'\nPrevious candidate:\n')
        record=dict(round=round_index,reused_initial=(args.arm=='retained_helpers' or getattr(args,'replay_initial',False)) and round_index==0)
        requests.append(record);save(args.out/('request_'+str(round_index)+'.json'),body)
        tick=time.monotonic()
        if record['reused_initial']:
            payload=json.loads((args.input/'response_0.json').read_text())
        else:
            actual_calls+=1
            assert actual_calls <= (2 if args.arm=='original' else 1)
            save(args.out/('attempt_'+str(round_index)+'.json'),dict(started=True,network_call=actual_calls))
            with real_urlopen(request,timeout=300) as response:payload=json.load(response)
            response_count+=1
        record['elapsed_s']=time.monotonic()-tick
        save(args.out/('response_'+str(round_index)+'.json'),payload)
        if payload['choices'][0].get('finish_reason')!='stop':
            raise RuntimeError('incomplete model response; stop without retry')
        return io.StringIO(json.dumps(payload))
    runtime.urllib.request.urlopen=controlled_urlopen
    os.environ.update(MODEL_NAME=expected['model'],LLM_BASE_URL='http://127.0.0.1:8000/v1',RTL_REPAIRS='1',RTL_TEMPERATURE='0',RTL_MAX_TOKENS='8192')
    os.chdir(args.out);tick=time.monotonic()
    try:
        runtime.worker(task,args.out)
    finally:
        save(args.out/'worker_receipt.json',dict(actual_model_calls=actual_calls,responses=response_count,logical_worker_requests=len(requests),requests=requests,selections=selections,elapsed_s=time.monotonic()-tick,
            solution_sha256=sha(args.out/'solution.v') if (args.out/'solution.v').exists() else None,best_runtime_sha256=sha(args.package/'agent/runtime.py')))


def run(args):
    if not args.enable_generation:raise RuntimeError('explicit approved generation launch is required')
    if sys.platform!='linux' or ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0):raise RuntimeError('AMD Linux required')
    spec=json.loads((Path(__file__).parent/'NEXT_SPEC.json').read_text())
    assert spec['max_new_model_calls']==24 and len(spec['order'])==8
    paired=load('full_pair_guard',REPO/'03_analysis/selective_runtime_integration_20261003/paired_next/paired_checkpoint.py')
    evaluator=load('full_pair_judge',args.kit/'official_eval.py')
    assert evaluator.verify_upstream()==spec['upstream_commit']
    originals={str(args.kit/k):v for k,v in spec['kit_hashes'].items()}
    tasks=Path(spec['tasks_root'])
    for name,files in spec['task_hashes'].items():originals.update({str(tasks/name/k):v for k,v in files.items()})
    assert all(sha(p)==h for p,h in originals.items())
    paired.check_resource(args.resource_check,args.kit,first=True)
    args.out.mkdir(parents=True,exist_ok=False)
    package=args.out/'package';(package/'agent').mkdir(parents=True)
    with tarfile.open(args.best_tar) as archive:content=archive.extractfile('04_project/amd_rtl_agent/submission/agent/runtime.py').read()
    (package/'agent/runtime.py').write_bytes(content);assert sha(package/'agent/runtime.py')==BEST
    for name in ['baseline.py','skill/rtl-generation/SKILL.md','skill/rtl-feedback-repair/SKILL.md']:
        target=package/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(args.kit/'submission'/name,target)
    report=dict(complete=False,valid=False,model_calls=0,responses=0,rows=[],error=None,original_hashes=originals,
        frozen_spec_sha256=sha(Path(__file__).parent/'NEXT_SPEC.json'),best_runtime_sha256=BEST,full_set_score=False,formal_deployment_modified=False)
    tick=time.monotonic()
    try:
        for index,name in enumerate(spec['order']):
            if report['model_calls']+3>24 or time.monotonic()-tick>spec['max_pre_request_elapsed_s']:raise RuntimeError('reserve insufficient for a complete pair')
            assert all(sha(p)==h for p,h in originals.items())
            sample=args.out/'samples'/(str(index)+'_'+name);sample.mkdir(parents=True)
            body=dict(model=spec['model'],messages=[dict(role='system',content=(package/'skill/rtl-generation/SKILL.md').read_text()),dict(role='user',content=(tasks/name/'prompt.txt').read_text())],temperature=0,top_p=1.0,max_tokens=8192)
            save(sample/'request.json',body);row=dict(task=name,index=index,arms={});report['rows'].append(row)
            for arm in ['original','retained_helpers']:
                paired.check_resource(args.resource_check,args.kit);paired.model_idle('http://127.0.0.1:8000/v1',spec['model'])
                out=sample/arm
                cmd=[sys.executable,'-B',str(Path(__file__).resolve()),'worker','--kit',str(args.kit),'--package',str(package),'--input',str(sample),'--arm',arm,'--out',str(out)]
                supervision=paired.owned_command(cmd,args.out,sample/(arm+'.log'),660)
                attempts=list(out.glob('attempt_*.json'))
                received=sum((out/p.name.replace('attempt_','response_')).exists() for p in attempts)
                report['model_calls']+=len(attempts);report['responses']+=received
                receipt_path=out/'worker_receipt.json'
                receipt=json.loads(receipt_path.read_text()) if receipt_path.exists() else dict(actual_model_calls=len(attempts),responses=received,error='worker receipt missing')
                row['arms'][arm]=receipt
                assert receipt['actual_model_calls']==len(attempts) and receipt['responses']==received
                if supervision['returncode']!=0 or supervision['timeout'] or receipt['responses']!=receipt['actual_model_calls']:raise RuntimeError('worker transport/execution error; no retry')
                if arm=='original':shutil.copyfile(out/'response_0.json',sample/'response_0.json')
                paired.model_idle('http://127.0.0.1:8000/v1',spec['model'])
            # Both workers finish before any hidden evaluation material is copied.
            task_copy=sample/'judge_task';shutil.copytree(tasks/name,task_copy)
            for arm in ['original','retained_helpers']:
                dst=sample/'grades'/arm;dst.mkdir(parents=True)
                verdict=evaluator.judge_sample(task_copy,sample/arm/'solution.v',dst,dst/'verdict.json',90)
                row['arms'][arm]['verdict']=verdict
                if verdict.get('tool_error') or verdict.get('suspected_silent_degradation'):raise RuntimeError('judge environment/evidence error')
            old=row['arms']['original']['verdict']['level'];new=row['arms']['retained_helpers']['verdict']['level']
            row.update(repair=old<2 and new==3,regression=new<old,unchanged_level=new==old)
            save(sample/'pair.json',row)
            print(json.dumps(dict(task=name,index=index,old=old,new=new,actual_model_calls=report['model_calls'])),flush=True)
            if row['regression']:raise RuntimeError('functional regression; stop expansion')
        assert all(sha(p)==h for p,h in originals.items())
        paired.check_resource(args.resource_check,args.kit)
        report.update(complete=True,valid=True,inputs_unchanged=True,decision='review_full_worker_net_quality_and_request_cost_before_promotion')
    except BaseException as exc:
        report['error']=type(exc).__name__+': '+str(exc);raise
    finally:
        report['elapsed_s']=time.monotonic()-tick;save(args.out/'summary.json',report)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['run','worker']);p.add_argument('--kit',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--resource-check',type=Path);p.add_argument('--best-tar',type=Path);p.add_argument('--package',type=Path);p.add_argument('--input',type=Path);p.add_argument('--arm',choices=['original','retained_helpers']);p.add_argument('--enable-generation',action='store_true');p.add_argument('--replay-initial',action='store_true')
    a=p.parse_args();worker(a) if a.mode=='worker' else run(a)
