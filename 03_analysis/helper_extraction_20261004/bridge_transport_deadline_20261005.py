"""AMD-only slow HTTP controls for the unchanged bridge; no real inference/EDA."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import select
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,x):Path(p).write_text(json.dumps(x,indent=2)+'\n')


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ['owner-copy','paired','kit','resource-check','out']:
        p.add_argument('--'+name,required=True,type=Path)
    a=p.parse_args()
    assert sys.platform=='linux'
    assert sha(a.owner_copy/'RUN_SPEC.json')=='b98742b9694454c2dc41654a8bcb3668b7c2ee2066bb8dc85fa6009cc3e2eee3'
    for name,digest in json.loads((a.owner_copy/'RUN_SPEC.json').read_text())['source_hashes'].items():
        assert sha(a.owner_copy/name)==digest,name
    assert sha(a.paired)=='78e9b3e144f2bd43ebab371e15ac3946017686db890a8e45891db7a386841e1c'
    sp=importlib.util.spec_from_file_location('transport_resource',a.paired)
    resource=importlib.util.module_from_spec(sp);sp.loader.exec_module(resource)
    resource.check_resource(a.resource_check,a.kit,first=True)
    sys.path.insert(0,str(a.owner_copy))
    from test_bridge import app,FakeModel
    app.verify_package()
    a.out.mkdir(exist_ok=False)
    GOOD='module TopModule(output y); assign y=0; endmodule\n'
    PARTIAL='module TopModule\n'
    report=dict(complete=False,passed=False,actual_model_requests=0,actual_eda_commands=0,
                fake_model_requests=0,rows=[],independent_tasks=0,full_batch_complete=False)
    started=time.monotonic()

    class SlowModel(FakeModel):
        scenario=''
        requests=[]
        disconnected=threading.Event()
        halt=threading.Event()
        def do_POST(self):
            body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            self.requests.append(body)
            num=len(self.requests)
            if self.scenario=='recovery' or (self.scenario=='repair_headers' and num==1):
                code=GOOD if self.scenario=='recovery' else PARTIAL
                self.emit(dict(choices=[dict(finish_reason='stop',message=dict(content=code))]))
                return
            if self.scenario.endswith('headers'):
                while not self.halt.wait(.02):
                    ready,_,_=select.select([self.connection],[],[],0)
                    if ready and not self.connection.recv(1,socket.MSG_PEEK):
                        self.disconnected.set();return
            else:
                data=json.dumps(dict(choices=[dict(finish_reason='stop',message=dict(content=GOOD))])).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers()
                try:
                    for byte in data:
                        if self.halt.wait(.05):return
                        self.wfile.write(bytes([byte]));self.wfile.flush()
                except (BrokenPipeError,ConnectionResetError):self.disconnected.set()

    model=ThreadingHTTPServer(('127.0.0.1',0),SlowModel)
    agent=ThreadingHTTPServer(('127.0.0.1',0),app.core.Handler)
    threads=[]
    for server in [model,agent]:
        t=threading.Thread(target=server.serve_forever,daemon=True);t.start();threads.append(t)
    original_popen=subprocess.Popen
    spawned=[]
    def tracked(argv,**kwargs):
        proc=original_popen(argv,**kwargs)
        fields=Path(f'/proc/{proc.pid}/stat').read_text().rsplit(')',1)[1].split()
        spawned.append(dict(pid=proc.pid,starttime=fields[19],argv=argv))
        return proc
    def live(row):
        try:
            f=Path(f'/proc/{row["pid"]}/stat').read_text().rsplit(')',1)[1].split()
            return f[19]==row['starttime'] and f[0] not in ['Z','X']
        except FileNotFoundError:return False
    def post(nonce):
        body=dict(task_id='opaque_transport_control',nonce=nonce,mode='agent',
                  prompt='Constructed interface-only transport control.',interface='',deadline_s=3)
        req=urllib.request.Request(f'http://127.0.0.1:{agent.server_port}/v1/solve',
            data=json.dumps(body).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer test-only-local'})
        t=time.monotonic()
        with urllib.request.urlopen(req,timeout=10) as response:reply=json.load(response)
        return reply,time.monotonic()-t
    try:
        with patch.dict(os.environ,LLM_BASE_URL=f'http://127.0.0.1:{model.server_port}/v1',
                MODEL_NAME='fake-model',FPGACHINA_TOKEN='test-only-local',RTL_PROFILE='development',
                VIVADO_BIN='/intentionally-missing-tools',RTL_REPAIRS='1',RTL_MAX_TOKENS='8192',RTL_TEMPERATURE='0'), \
                patch.object(app.core.subprocess,'Popen',side_effect=tracked):
            for case in ['first_headers','first_body','repair_headers']:
                resource.check_resource(a.resource_check,a.kit)
                folder=a.out/case;folder.mkdir()
                SlowModel.scenario=case;SlowModel.requests=[];SlowModel.disconnected.clear()
                spawned.clear()
                def capture(mode,task,work,seconds):
                    result=app.run_job(mode,task,work,seconds)
                    shutil.copytree(work,folder/'worker')
                    return result
                with patch.object(app.core,'run_job',side_effect=capture):reply,elapsed=post(case)
                save(folder/'reply.json',reply);save(folder/'requests.json',SlowModel.requests)
                save(folder/'processes.json',spawned)
                report['fake_model_requests']+=len(SlowModel.requests)
                assert len(SlowModel.requests)==(2 if case=='repair_headers' else 1)
                assert reply['solution']==(PARTIAL if case=='repair_headers' else '')
                assert elapsed<4.0,(case,elapsed)
                assert SlowModel.disconnected.wait(2),'Fake backend must observe peer closure'
                assert len(spawned)==1 and not any(live(r) for r in spawned)
                events=[json.loads(x) for x in reply['trace'].splitlines()]
                assert any(e.get('event')=='deadline' or (e.get('tool')=='llm' and e.get('error')) for e in events)
                assert not any(e.get('tool') in ['lint_start','xvlog','xelab','xsim'] for e in events)
                if case=='repair_headers':assert PARTIAL in SlowModel.requests[1]['messages'][-1]['content']
                SlowModel.scenario='recovery';SlowModel.requests=[];spawned.clear()
                recovered,recovery_s=post(case+'_recovery')
                report['fake_model_requests']+=len(SlowModel.requests)
                save(folder/'recovery.json',dict(reply=recovered,requests=SlowModel.requests,processes=spawned))
                assert recovered['solution']==GOOD and len(SlowModel.requests)==1
                assert recovery_s<3 and len(spawned)==1 and not any(live(r) for r in spawned)
                report['rows'].append(dict(case=case,passed=True,elapsed_s=elapsed,recovery_s=recovery_s,
                    backend_peer_closed=True,owned_worker_gone=True,implicit_retry=False))
                save(a.out/'summary.json',report)
        resource.check_resource(a.resource_check,a.kit)
        assert len(report['rows'])==3 and report['fake_model_requests']==7
        report.update(complete=True,passed=True)
    except BaseException as error:
        report['error']=type(error).__name__+': '+str(error)
        raise
    finally:
        SlowModel.halt.set()
        report['elapsed_s']=time.monotonic()-started
        save(a.out/'summary.json',report)
        for server,t in zip([model,agent],threads):server.shutdown();server.server_close();t.join()
