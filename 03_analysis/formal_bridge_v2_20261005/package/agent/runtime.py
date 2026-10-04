"""Staged CLI/HTTP bridge for the pinned functional candidate, not deployed."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
import urllib.request

ROOT=Path(__file__).resolve().parent
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
spec=importlib.util.spec_from_file_location('formal_candidate_core',ROOT/'core.py')
core=importlib.util.module_from_spec(spec);spec.loader.exec_module(core)
import native_contract
import health_probe
native_contract.CORE=core
core.map_feedback=native_contract.feedback
core.vivado_version=health_probe.vivado_version
core.vram_gb=lambda:health_probe.vram_gb(core.endpoint())

def verify_package():
    manifest=json.loads((ROOT.parent/'INTEGRITY.json').read_text(encoding='utf-8'))
    for name,digest in manifest['files'].items():
        if hashlib.sha256((ROOT.parent/name).read_bytes()).hexdigest()!=digest:
            raise ValueError('Staged package integrity mismatch: '+name)
    if not core.baseline_integrity():raise ValueError('Official baseline integrity mismatch')

_run_job=core.run_job
_open=urllib.request.urlopen

def slots_idle(timeout=2):
    # This bridge declares llama.cpp with /slots telemetry; other inference
    # stacks need a separate verified adapter. No model request while busy.
    base=core.endpoint()
    if not base.endswith('/v1'):raise ValueError('Declared llama.cpp /v1 endpoint required')
    with _open(base[:-3]+'/slots',timeout=timeout) as response:slots=json.load(response)
    return isinstance(slots,list) and bool(slots) and all(isinstance(s,dict) and s.get('is_processing') is False for s in slots)

def run_job(mode,task,out,seconds):
    started=time.monotonic()
    verify_package()
    left=seconds-(time.monotonic()-started)
    if left<=0 or not slots_idle(min(2,left)):return '',''
    left=seconds-(time.monotonic()-started)
    if left<=0:return '',''
    previous=os.environ.get('RTL_ABSOLUTE_DEADLINE')
    os.environ['RTL_ABSOLUTE_DEADLINE']=str(started+seconds)
    try:return _run_job(mode,task,out,left)
    finally:
        if previous is None:os.environ.pop('RTL_ABSOLUTE_DEADLINE',None)
        else:os.environ['RTL_ABSOLUTE_DEADLINE']=previous

def worker(task,out):
    verify_package()
    if int(os.environ.get('RTL_REPAIRS','1'))!=1 or int(os.environ.get('RTL_MAX_TOKENS','8192'))!=8192 or float(os.environ.get('RTL_TEMPERATURE','0'))!=0:
        raise ValueError('Staged candidate requires the evaluated one-repair/8192-token/temperature-zero configuration')
    # Only the supervised worker is patched, never the long-lived service's
    # request transport. API routing/task IDs remain the pinned core's code.
    def transport(request,*args,**kwargs):
        url=request.full_url if isinstance(request,urllib.request.Request) else str(request)
        if url.endswith('/chat/completions'):
            left=native_contract.remaining()
            if left<=0:raise OSError('Worker deadline exhausted before model POST')
            if not slots_idle(min(2,left)):raise OSError('Declared model is busy; no POST submitted')
            left=native_contract.remaining()
            if left<=0:raise OSError('Worker deadline exhausted before model POST')
            kwargs['timeout']=min(float(kwargs.get('timeout',300)),left)
        return _open(request,*args,**kwargs)
    previous=urllib.request.urlopen;urllib.request.urlopen=transport
    try:return _worker(task,out)
    finally:urllib.request.urlopen=previous

_worker=core.worker
core.worker=worker
core.run_job=run_job
_health=core.health
def health():
    try:verify_package()
    except (OSError,ValueError,KeyError):
        return dict(ready=False,track='rtl',model=os.environ.get('MODEL_NAME',''),vram_gb=None)
    return _health()
core.health=health

if __name__=='__main__':
    verify_package()
    core.main()
