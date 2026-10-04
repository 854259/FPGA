"""Queued real native bridge parity on a constructed renamed priority contract.

Fake loopback replies exercise the packaged HTTP worker. No real inference,
benchmark prompt, reference answer, external judge, or synth is used.
"""
import hashlib,importlib.util,json,os,shutil,sys,threading,urllib.request
from pathlib import Path
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from test_bridge import app,prompt,FakeModel,GOOD,BAD

ROOT=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,d):p.write_text(json.dumps(d,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')

def main():
    assert sys.platform=='linux'
    out=ROOT/'results/native_parity';out.mkdir()
    toolroot=Path(os.environ['VIVADO_BIN']).resolve()
    assert str(toolroot)=='/workspace/AMD/2026.1/Vivado/bin'
    assert all((toolroot/n).is_file() for n in ['xvlog','xelab','xsim'])
    FakeModel.requests=[];FakeModel.busy=False
    report={'complete':False,'passed':False,'rows':[],'actual_native_probes':None,'actual_compile_commands':None,'actual_synthesis_commands':0,'actual_model_requests':0,'fake_model_requests':0,'independent_natural_tasks':0,'scope':'One constructed renamed 4-bit priority contract. Native pipeline parity, not quality score, shift parity, target hardware, offline proof or deployment.'}
    save(out/'summary.json',report)
    model=ThreadingHTTPServer(('127.0.0.1',0),FakeModel);mt=threading.Thread(target=model.serve_forever,daemon=True);mt.start()
    agent=ThreadingHTTPServer(('127.0.0.1',0),app.core.Handler);at=threading.Thread(target=agent.serve_forever,daemon=True);at.start()
    def capture(mode,task,work,seconds):
        result=app.run_job(mode,task,work,seconds)
        shutil.copytree(work,out/'http_worker')
        return result
    try:
        with patch.dict(os.environ,LLM_BASE_URL=f'http://127.0.0.1:{model.server_port}/v1',MODEL_NAME='fake-model',FPGACHINA_TOKEN='test-only-local',RTL_PROFILE='development',RTL_REPAIRS='1',RTL_MAX_TOKENS='8192',RTL_TEMPERATURE='0'),patch.object(app.core,'run_job',side_effect=capture):
            payload={'task_id':'opaque/../构造契约','nonce':'real-native-parity','mode':'agent','prompt':prompt(),'interface':'','deadline_s':120}
            req=urllib.request.Request(f'http://127.0.0.1:{agent.server_port}/v1/solve',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer test-only-local'})
            with urllib.request.urlopen(req,timeout=130) as response:reply=json.load(response)
        save(out/'http_reply.json',reply);save(out/'fake_model_requests.json',FakeModel.requests)
        assert reply['solution']==GOOD and len(FakeModel.requests)==2
        assert 'least significant' in FakeModel.requests[1]['messages'][1]['content']
        events=[json.loads(line) for line in reply['trace'].splitlines()]
        assert sum(e['tool']=='lint' and e['rc']==0 for e in events)==2
        rows=report['rows']
        for i,code,expected in [(0,BAD,12),(1,GOOD,0)]:
            folder=out/'http_worker'/('map_check_'+str(i))
            # These are actual raw receipts from the bridge's worker subprocess.
            r=json.loads((folder/'probe/report.json').read_text()) if (folder/'probe/report.json').exists() else json.loads((folder/'probe/result.json').read_text())
            assert r['checks']==16 and r['mismatches']==expected
            assert sha(folder/'input.sv')==hashlib.sha256(code.encode()).hexdigest()
            for s in r['stages']:
                assert s['returncode']==0 and not s['timeout']
                assert s['session_policy']=='inherit_supervised_worker_group'
                assert Path(s['argv'][0]).parent==toolroot
                # Copied logs retain their original absolute locations in receipts.
                log=folder/'probe'/Path(s['log']).name
                assert sha(log)==s['log_sha256']
            inputs=out/('legacy_inputs_'+str(i));inputs.mkdir();task=inputs/'ContractProbe';task.mkdir()
            (task/'tb.sv').write_bytes((folder/'inputs/ContractProbe/tb.sv').read_bytes())
            helper=inputs/'probe_runner.py';helper.write_bytes((ROOT/'package/agent/probe_runner.py').read_bytes())
            spec=importlib.util.spec_from_file_location('legacy_probe_'+str(i),helper);legacy=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy)
            legacy.TASK_CHECKS={'ContractProbe':16}
            source=inputs/'source.sv';source.write_text(code,newline='\n')
            with patch.dict(os.environ,PATH=str(toolroot)+os.pathsep+os.environ['PATH']):old=legacy.probe_candidate('ContractProbe',source,out/('legacy_probe_'+str(i)))
            assert old['checks']==r['checks'] and old['mismatches']==r['mismatches'] and old['status']==r['status'] and old['failure_kind']==r['failure_kind']
            rows.append({'candidate':'wrong' if i==0 else 'correct','bridge':r,'legacy':old})
        report.update(complete=True,passed=True,actual_native_probes=4,actual_compile_commands=2)
    except BaseException as error:
        report['error']=type(error).__name__+': '+str(error)
        raise
    finally:
        report['fake_model_requests']=len(FakeModel.requests)
        report['completed_native_receipts_observed']=len(list(out.rglob('result.json')))
        save(out/'summary.json',report)
        for server,thread in [(agent,at),(model,mt)]:server.shutdown();server.server_close();thread.join()
    return 0

if __name__=='__main__':raise SystemExit(main())
