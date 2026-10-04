"""Request-local prompt-derived probes in the supervised worker process group."""
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time
import prompt_map
import point_feedback

ROOT=Path(__file__).resolve().parent
INTERNAL_TASK='ContractProbe'
CORE=None

def remaining():
    deadline=os.environ.get('RTL_ABSOLUTE_DEADLINE')
    return max(0,float(deadline)-time.monotonic()) if deadline else 300.0

def run_stage(name,argv,outdir):
    """Inherit the outer worker group; its supervisor cleans all descendants.

    Unlike the research harness, do not create a separate tool session which
    would escape the HTTP worker's deadline cleanup. Never select shared PIDs.
    """
    started=time.monotonic();log=outdir/(name+'.log')
    result=dict(name=name,argv=argv,timeout=False,returncode=None,launch_error=None,
                group_signals=[],session_policy='inherit_supervised_worker_group')
    with log.open('xb') as stream:
        timeout=min(60.0,remaining())
        if timeout<=0:
            result['timeout']=True;stream.write(b'Worker deadline exhausted before native launch\n')
        else:
            try:
                proc=subprocess.Popen(argv,cwd=outdir,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT)
            except OSError as error:
                result['launch_error']=type(error).__name__;stream.write(str(error).encode())
            else:
                try:proc.wait(timeout=timeout)
                except subprocess.TimeoutExpired:
                    result['timeout']=True
                    if proc.poll() is None:proc.kill()
                    proc.wait(timeout=5)
                finally:
                    if proc.poll() is None:proc.kill();proc.wait(timeout=5)
                result['returncode']=proc.returncode
    result.update(elapsed_s=round(time.monotonic()-started,6),log=str(log),
                  log_sha256=hashlib.sha256(log.read_bytes()).hexdigest(),log_bytes=log.stat().st_size)
    return result

def probe(contract,code,folder):
    inputs=folder/'inputs';inputs.mkdir();task=inputs/INTERNAL_TASK;task.mkdir()
    source=folder/'input.sv';source.write_text(code,encoding='utf-8',newline='\n')
    (task/'tb.sv').write_text(prompt_map.render_tb(contract,INTERNAL_TASK),encoding='utf-8',newline='\n')
    copied=inputs/'probe_runner.py';copied.write_bytes((ROOT/'probe_runner.py').read_bytes())
    spec=importlib.util.spec_from_file_location('request_local_probe',copied)
    runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
    runner.TASK_CHECKS={INTERNAL_TASK:contract['checks']}
    def stage(name,argv,outdir):
        tool=CORE.vivado_tool(name)
        if tool:argv=[tool,*argv[1:]]
        else:argv=[str(inputs/'unavailable'/name),*argv[1:]]
        return run_stage(name,argv,outdir)
    runner._run_stage=stage
    return runner.probe_candidate(INTERNAL_TASK,source,folder/'probe')

def feedback(prompt,code,out,attempt):
    contract=prompt_map.parse(prompt)
    if contract['status']!='supported' or re.search(r'\$[A-Za-z_]|`include',code):return ''
    folder=out/('map_check_'+str(attempt));folder.mkdir()
    (folder/'contract.json').write_text(json.dumps(contract,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    result=probe(contract,code,folder)
    for stage in result.get('stages',[]):
        CORE.trace(out,stage['name'],rc=stage['returncode'],timeout=stage['timeout'],
                   excerpt=Path(stage['log']).read_text(encoding='utf-8',errors='replace')[-2048:])
    CORE.trace(out,'functional_probe',round=attempt,status=result['status'],checks=result['checks'],
               mismatches=result['mismatches'],failure_kind=result['failure_kind'],
               prompt_sha256=contract['prompt_sha256'],source_sha256=hashlib.sha256(code.encode()).hexdigest())
    if result['status']=='pass':
        assert result['mismatches']==0
        return ''
    if result['failure_kind']!='semantic_mismatch':
        raise RuntimeError('Functional checker unavailable; do not fabricate feedback')
    point=prompt_map.counterexample((folder/'probe/xsim.log').read_text(encoding='utf-8'),contract)
    (folder/'counterexample.json').write_text(json.dumps(point,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    text=point_feedback.render(contract,result,point)
    (folder/'feedback.json').write_text(json.dumps({'text':text},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return text
