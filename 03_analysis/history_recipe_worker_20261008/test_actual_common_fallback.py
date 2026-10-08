"""New router contexts through the original baseline/runtime; services are fake."""
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import types
import urllib.request
from unittest.mock import patch
import worker
import baseline_worker

ROOT=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
read=lambda p:json.loads(Path(p).read_bytes())
save=lambda p,j:Path(p).write_bytes((json.dumps(j,indent=2)+'\n').encode())


def main():
    assert sys.platform=='linux' and sys.dont_write_bytecode
    assert sha(ROOT/'baseline_worker.py')=='7ff7ed6e397caedee071a7f46015d81370c92f2579bd61dd2cc3337458467742'
    assert sha(ROOT/'package/agent/map_runtime.py')=='2f7cb98bc44a9e100d36ca12ac4ef7bf9ae2535473da358e166afa2559e96cba'
    manifest=read(ROOT/'SOURCE_MANIFEST.json');assert all(sha(ROOT/n)==h for n,h in manifest.items())
    save(ROOT/'RUN_SPEC.json',dict(dependencies_cloud=str(ROOT),model='SIMULATED-history-router',identity='history-router-new-common-path-controls'))
    os.environ.update(MODEL_NAME='SIMULATED-history-router',RTL_REPAIRS='1',RTL_MAX_TOKENS='8192',RTL_TEMPERATURE='0',LLM_BASE_URL='http://127.0.0.1:8000/v1')
    sys.path.insert(0,str(ROOT/'package'));import baseline
    first=baseline.extract('module TopModule(input clk); wire value; always @(posedge clk) value<=1; endmodule','rtl')
    fixed=first.replace('wire value','reg value')
    error='ERROR: explicitly simulated first compiler failure'
    fixtures=read(ROOT/'RETAINED_INPUTS_PRIVATE.json')
    unrelated=dict(prompt='Unrelated unsupported interface requirement\r\n',interface='module TopModule(input clk); endmodule\r\n')
    cases=[('supported_'+f['label']+'_C',f,'C',True) for f in fixtures]
    cases += [('unrelated_'+arm+'_'+('repair' if fail_first else 'one'),unrelated,arm,fail_first) for fail_first in [False,True] for arm in ['C','P']]
    old_open,old_run,old_load=urllib.request.urlopen,subprocess.run,baseline_worker.load
    original_request=urllib.request.Request
    runtimes=[];activity=[];rows=[];pairs={}
    def load(name,path):
        module=old_load(name,path)
        if str(path).endswith('/agent/map_runtime.py'):
            module.vivado_tool=lambda n:'/SIMULATED/'+n;runtimes.append(module)
        return module
    class Paired:
        REPO=ROOT
        def check_resource(self,*args):return True
        def model_idle(self,*args):return True
        def owned_command(self,argv,wd,log,cap):
            assert cap==60 and argv[:2]==['/SIMULATED/xvlog','--sv']
            index=len(compiles);compiles.append(Path(argv[-1]).read_text())
            log.write_text(error if fail_first and index==0 else '')
            return dict(returncode=1 if fail_first and index==0 else 0,timeout=False,launch_error=None,remaining_live_group=[],log_sha256=sha(log),log_bytes=log.stat().st_size,elapsed_s=0,simulated=True)
    fake_activity=types.SimpleNamespace(append=lambda *a:activity.append(dict(simulated=True,event=str(a[2]))))
    with patch.dict(sys.modules,activity=fake_activity),patch.object(baseline_worker,'load',side_effect=load),patch.object(baseline_worker,'functional_feedback',return_value=''):
        for name,f,arm,fail_first in cases:
            source=ROOT/'SIMULATED_KIT'/name/'bench/tasks_veval/generic_input';source.mkdir(parents=True)
            (source/'prompt.txt').write_bytes(f['prompt'].encode());(source/'interface.txt').write_bytes(f['interface'].encode())
            folder=ROOT/'ACTUAL_BASELINE_MOCK_OUTPUTS'/name
            wires=[];compiles=[]
            expected=(source/'prompt.txt').read_text()
            interface=(source/'interface.txt').read_text()
            if interface.strip():expected+='\n\nInterface:\n'+interface
            def transport(request,**kwargs):
                index=len(wires);assert index<2 and kwargs==dict(timeout=300)
                assert request.full_url=='http://127.0.0.1:8000/v1/chat/completions'
                body=json.loads(request.data)
                generation,repair=runtimes[-1].skill_texts()
                assert body['messages'][0]==dict(role='system',content=generation+('\n'+repair if index else ''))
                assert body['messages'][1]['content']==expected+('\nPrevious candidate:\n'+first+'\nCandidate diagnostics:\n'+error if index else '')
                assert body['max_tokens']==8192 and body['temperature']==0 and body['top_p']==1
                wires.append(request.data)
                return io.BytesIO(json.dumps(dict(id='explicitly-simulated-'+str(index),choices=[dict(message=dict(content=first if index==0 else fixed),finish_reason='stop')],usage=dict(prompt_tokens=0,completion_tokens=0))).encode())
            args=types.SimpleNamespace(kit=source.parents[2],task='generic_input',arm=arm,out=folder,resource_check=ROOT/'SIMULATED_RESOURCE.json')
            with patch('urllib.request.urlopen',side_effect=transport):worker.run_worker(args,Paired())
            assert urllib.request.urlopen is old_open and subprocess.run is old_run and urllib.request.Request is original_request
            count=2 if fail_first else 1
            assert len(wires)==len(compiles)==count
            assert (folder/'solution.v').read_text()==(fixed if fail_first else first)
            journal=read(folder/'requests.json');assert len(journal)==count and all(r['response_received'] for r in journal)
            for index in range(count):assert json.loads(wires[index])==read(folder/'requests'/str(index)/'request.json')
            route=read(folder/'generation_route.json');assert route['route']=='model' and route['selected_provider'] is None
            assert not (folder/'synthesis_receipt.json').exists() and not (folder/'native_receipts').exists()
            if arm=='P':assert read(folder/'generation_selection.json')['reason']=='no_complete_contract'
            else:assert not (folder/'generation_selection.json').exists()
            hashes=[hashlib.sha256(b).hexdigest() for b in wires]
            if name.startswith('unrelated_'):pairs.setdefault(fail_first,{})[arm]=hashes
            rows.append(dict(case=name,arm=arm,requests=count,first_wire_sha256=hashes[0],repair_wire_sha256=hashes[1] if count==2 else None,model_route=True))
        assert all(pair['C']==pair['P'] for pair in pairs.values())
        # One unconfirmed transport is retained, never retried or reported successful.
        source=ROOT/'SIMULATED_KIT/unrelated_P_one/bench/tasks_veval/generic_input'
        failed=ROOT/'ACTUAL_BASELINE_MOCK_OUTPUTS/transport_failure'
        args=types.SimpleNamespace(kit=source.parents[2],task='generic_input',arm='P',out=failed,resource_check=ROOT/'SIMULATED_RESOURCE.json')
        with patch('urllib.request.urlopen',side_effect=OSError('explicit simulated failure')) as transport:
            try:worker.run_worker(args,Paired())
            except RuntimeError:pass
            else:raise AssertionError('Unconfirmed call accepted')
            assert transport.call_count==1
        assert len(read(failed/'requests.json'))==1 and read(failed/'requests.json')[0]['response_received'] is False
        assert not (failed/'worker_result.json').exists()
    assert urllib.request.urlopen is old_open and subprocess.run is old_run and urllib.request.Request is original_request
    save(ROOT/'SIMULATED_ACTIVITY.json',activity)
    result=dict(schema='history_router_new_original_baseline_runtime_mock_contexts_v1',passed=True,complete_baseline_runtime_contexts=6,transport_failure_contexts=1,C_P_first_and_repair_wires_byte_equal=True,original_baseline_runtime_and_skills_executed=True,HTTP_native_functional_probe_activity_simulated=True,old_test_methods_native_intake_not_run=True,rows=rows,new_real_model_EDA_FIFO_calls=0,native_or_score_qualification=False)
    save(ROOT/'ACTUAL_COMMON_FALLBACK_RESULT.json',result);print(json.dumps(result))


if __name__=='__main__':main()
