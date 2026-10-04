"""Replay captured model I/O through the exact archived best worker, offline."""
import argparse
import ctypes
import io
import json
import os
import shutil
import sys
import tarfile
import time
from pathlib import Path
from types import SimpleNamespace

from pilot import REPO, load, save, sha

BEST = '22e32251664f31a6a8a51b9d443860442359aa2588b187ea816c6973c8cd08e7'


def worker(args):
    runtime = load('best_worker', args.package/'agent/runtime.py')
    baseline = load('baseline',args.package/'baseline.py');sys.modules['baseline']=baseline
    original_extract = baseline.extract
    if args.arm=='retained_helpers':
        extension=load('integration_extension',REPO/'03_analysis/semantic_repair_20261004/complete_module_extract.py')
        lexer=load('integration_lexer',REPO/'03_analysis/selective_runtime_integration_20261003/package/agent/signedness_selector.py')
        detector=load('integration_detector',args.kit/'submission/agent/runtime.py')
        def extract(text,track):
            if track!='rtl':return original_extract(text,track)
            return extension.extract_hierarchy(text,SimpleNamespace(extract=original_extract),lexer._strip_noncode,detector.undefined_submodules)[0]
        baseline.extract=extract
    expected=json.loads((args.captured/'request.json').read_text())
    response=(args.captured/'response.json').read_text()
    used=[]
    def captured_urlopen(request,timeout=None):
        if request.full_url!='http://127.0.0.1:8000/v1/chat/completions' or json.loads(request.data)!=expected or used:
            raise RuntimeError('unexpected or repeated request; network remains blocked')
        used.append(dict(request_matches=True,timeout=timeout))
        return io.StringIO(response)
    # No real HTTP request is forwarded. This is an integration replay, not a model sample.
    runtime.urllib.request.urlopen=captured_urlopen
    args.out.mkdir(parents=True,exist_ok=False)
    task=args.out/'prompt_only_task';task.mkdir()
    (task/'prompt.txt').write_text(expected['messages'][1]['content'])
    os.chdir(args.out)
    os.environ.update(MODEL_NAME=expected['model'],LLM_BASE_URL='http://127.0.0.1:8000/v1',RTL_TEMPERATURE='0',RTL_MAX_TOKENS='8192',RTL_REPAIRS='1')
    tick=time.monotonic();runtime.worker(task,args.out)
    events=[json.loads(line) for line in (args.out/'trace.jsonl').read_text().splitlines()]
    assert len(used)==1 and sum(e['tool']=='llm_start' for e in events)==1
    assert any(e['tool']=='lint' and e.get('rc')==0 for e in events)
    expected_source=args.captured/('original.sv' if args.arm=='original' else 'final.sv')
    assert sha(args.out/'solution.v')==sha(expected_source)
    save(args.out/'receipt.json',dict(complete=True,valid=True,arm=args.arm,network_model_calls=0,captured_responses_replayed=1,
        original_best_runtime_sha256=sha(args.package/'agent/runtime.py'),source_matches_frozen_judged_candidate=True,
        solution_sha256=sha(args.out/'solution.v'),request_matches=True,elapsed_s=time.monotonic()-tick,
        hook='isolated process in-memory extraction hook' if args.arm!='original' else 'original extraction'))


def run(args):
    if sys.platform!='linux' or ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0):raise RuntimeError('AMD Linux required')
    paired=load('best_replay_owned',REPO/'03_analysis/selective_runtime_integration_20261003/paired_next/paired_checkpoint.py')
    paired.check_resource(args.resource_check,args.kit,first=True)
    prior=json.loads((args.captured/'summary.json').read_text())
    assert prior['complete'] and prior['valid'] and prior['model_calls']==2
    assert any(r['functional_repair'] for r in prior['live'])
    args.out.mkdir(parents=True,exist_ok=False)
    package=args.out/'package';(package/'agent').mkdir(parents=True)
    with tarfile.open(args.best_tar) as archive:
        content=archive.extractfile('04_project/amd_rtl_agent/submission/agent/runtime.py').read()
    (package/'agent/runtime.py').write_bytes(content)
    assert sha(package/'agent/runtime.py')==BEST
    for name in ['baseline.py','skill/rtl-generation/SKILL.md','skill/rtl-feedback-repair/SKILL.md']:
        target=package/name;target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(args.kit/'submission'/name,target)
    frozen={str(p):sha(p) for p in package.rglob('*') if p.is_file()}
    frozen.update({str(p):sha(p) for p in args.captured.glob('live/*/*') if p.is_file()})
    save(args.out/'inputs_frozen.json',frozen)
    report=dict(complete=False,valid=False,model_calls=0,rows=[],error=None,best_runtime_sha256=BEST,
        scope='exact worker with captured HTTP response, unchanged repair budget; in-memory extraction hook; not service acceptance')
    tick=time.monotonic()
    try:
        for row in prior['live']:
            for arm in ['original','retained_helpers']:
                paired.check_resource(args.resource_check,args.kit)
                dst=args.out/'workers'/row['task']/arm
                log=args.out/(row['task']+'_'+arm+'.log')
                cmd=[sys.executable,'-B',str(Path(__file__).resolve()),'worker','--kit',str(args.kit),'--package',str(package),'--captured',str(args.captured/'live'/row['task']),'--arm',arm,'--out',str(dst)]
                owned=paired.owned_command(cmd,args.out,log,90)
                assert owned['returncode']==0 and not owned['timeout'],owned
                receipt=json.loads((dst/'receipt.json').read_text())
                verdict=row['original' if arm=='original' else 'final']
                receipt.update(task=row['task'],reused_frozen_verdict_level=verdict['level'],verdict_source='same exact solution bytes, task hash and original F1r2 receipt',supervision=owned)
                report['rows'].append(receipt)
                print(json.dumps(dict(task=row['task'],arm=arm,level=verdict['level'],network_model_calls=0)),flush=True)
        assert all(sha(p)==h for p,h in frozen.items())
        paired.check_resource(args.resource_check,args.kit)
        report.update(complete=True,valid=True,inputs_unchanged=True,decision='worker_replay_verified_not_formal_deployment')
    except BaseException as exc:
        report['error']=type(exc).__name__+': '+str(exc);raise
    finally:
        report['elapsed_s']=time.monotonic()-tick;save(args.out/'summary.json',report)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['worker','run']);p.add_argument('--kit',type=Path,required=True);p.add_argument('--captured',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--resource-check',type=Path);p.add_argument('--package',type=Path);p.add_argument('--best-tar',type=Path);p.add_argument('--arm',choices=['original','retained_helpers'])
    a=p.parse_args();worker(a) if a.mode=='worker' else run(a)
