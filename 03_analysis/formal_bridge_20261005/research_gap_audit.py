"""Reproduce research package CLI/API gaps with in-process fake transport/tools."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
from unittest.mock import patch

ROOT=Path(__file__).resolve().parent
OLD=ROOT.parent/'functional_full156_20261005/package'

def main():
    spec=importlib.util.spec_from_file_location('isolated_old_candidate',OLD/'agent/map_runtime.py')
    old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old)
    expected='2f7cb98bc44a9e100d36ca12ac4ef7bf9ae2535473da358e166afa2559e96cba'
    assert hashlib.sha256((OLD/'agent/map_runtime.py').read_bytes()).hexdigest()==expected
    report={'schema':'research_candidate_formal_gap_reproduction_v1','source_core_sha256':expected,'model_calls':0,'eda_calls':0,'live_source_changed':False,'full_regression_invalidated':False}
    with tempfile.TemporaryDirectory(prefix='bridge-gap-fakes-') as td:
        root=Path(td);task=root/'in';task.mkdir();(task/'prompt.txt').write_text('Generic new specification')
        try:old.run_job('agent',task,root/'api-out',2)
        except FileNotFoundError as error:
            assert Path(error.filename)==OLD/'upstream.json'
            report['unpackaged_integrity_file_failure_reproduced']=True
        else:raise AssertionError('Expected missing research-only integrity packaging')
        calls=[]
        class Process:
            pid=0
            def __init__(self,argv,**kwargs):calls.append(argv)
            def wait(self,**kwargs):return 0
        with patch.object(old,'baseline_integrity',return_value=True),patch.object(old.subprocess,'Popen',Process),patch.object(old,'stop_tree'):
            old.run_job('agent',task,root/'dispatch-out',2)
        selected=Path(calls[0][1]);assert selected==OLD/'agent/runtime.py'
        report['research_map_API_child_selects_A_runtime']=True
        report['selected_child_sha256']=hashlib.sha256(selected.read_bytes()).hexdigest()
        work=root/'work';work.mkdir();out=root/'worker-out';out.mkdir();(out/'trace.jsonl').write_text('')
        tool=root/'tools';tool.mkdir()
        for name in ['xvlog','xvlog.bat']:(tool/name).write_text('FAKE_ONLY')
        payload={'choices':[{'finish_reason':'stop','message':{'content':'module TopModule(input a,output y);assign y=a;endmodule'}}]}
        previous=Path.cwd()
        try:
            os.chdir(work)
            with patch.dict(os.environ,MODEL_NAME='fake-model',VIVADO_BIN=str(tool),RTL_REPAIRS='1'),patch.object(old.urllib.request,'urlopen',return_value=io.BytesIO(json.dumps(payload).encode())),patch.object(old.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'')):
                try:old.worker(task,out)
                except NameError as error:
                    assert error.name=='map_feedback';report['missing_callback_nameerror_reproduced']=True
                else:raise AssertionError('Expected standalone callback gap')
        finally:os.chdir(previous)
    assert report['selected_child_sha256']=='22e32251664f31a6a8a51b9d443860442359aa2588b187ea816c6973c8cd08e7'
    report['limits']=['Research worker injects its callback and is unaffected; this is a shipping gap, not a failed full regression.',
        'Fake process/model/compiler reproduce routing only; no functional RTL or hardware proof.']
    (ROOT/'RESEARCH_API_GAPS.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))

if __name__=='__main__':main()
