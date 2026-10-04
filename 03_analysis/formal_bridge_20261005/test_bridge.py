"""Staged worker/protocol tests; fake backend/tools, no paid model or AMD EDA."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from unittest.mock import patch

ROOT=Path(__file__).resolve().parent
PKG=ROOT/'package'
spec=importlib.util.spec_from_file_location('staged_bridge',PKG/'agent/runtime.py')
app=importlib.util.module_from_spec(spec);spec.loader.exec_module(app)
BAD='module TopModule(input [3:0] data,output [1:0] idx);assign idx=1;endmodule\n'
GOOD="module TopModule(input [3:0] data,output [1:0] idx);assign idx=data[0]?2'd0:data[1]?2'd1:data[2]?2'd2:data[3]?2'd3:2'd0;endmodule\n"

def prompt():
    return ('I would like you to implement a module named TopModule with the following interface. '
        'All input and output ports are one bit unless otherwise specified.\n- input data (4 bits)\n- output idx (2 bits)\n'
        'The module should implement a priority encoder. A priority encoder is a combinational circuit that, when given an input bit vector, outputs the position of the first 1 bit in the vector. '
        "For example, a 8-bit priority encoder given the input 8'b10010000 would output 3'd4, because bit[4] is first bit that is high. "
        'Build a 4-bit priority encoder. For this problem, if none of the input bits are high (i.e., input is zero), output zero. Note that a 4-bit number has 16 possible combinations.')

class Worker(unittest.TestCase):
    def case(self,bad=True,persistent=False,unknown=False,patched=False):
        with tempfile.TemporaryDirectory(prefix='bridge-worker-') as td:
            root=Path(td);task=root/'in';out=root/'out';task.mkdir();out.mkdir()
            text=prompt()+(' Extra reset or output delay required.' if unknown else '')
            (task/'prompt.txt').write_text(text,encoding='utf-8')
            for name in ['ref.sv','tb.sv','task.json']:(task/name).write_text('PRIVATE_DO_NOT_READ')
            (out/'trace.jsonl').write_text('')
            tools=root/'tools';tools.mkdir()
            for name in ['xvlog','xvlog.bat']:(tools/name).write_text('FAKE_TEST_ONLY')
            calls=[];probes=[];compiles=[]
            def network(req,*a,**kw):
                url=req.full_url if isinstance(req,urllib.request.Request) else req
                if url.endswith('/slots'):return io.BytesIO(b'[{"is_processing":false}]')
                body=json.loads(req.data);calls.append(body)
                code=BAD if bad and (persistent or len(calls)==1) else GOOD
                return io.BytesIO(json.dumps({'choices':[{'finish_reason':'stop','message':{'content':code}}],'usage':{'prompt_tokens':10,'completion_tokens':20}}).encode())
            def compile(argv,**kwargs):
                compiles.append(argv)
                return subprocess.CompletedProcess(argv,1 if patched and len(compiles)==1 else 0,'ERROR: declared output not reg' if patched and len(compiles)==1 else '')
            def probe(c,code,folder):
                probes.append(c);p=folder/'probe';p.mkdir()
                wrong=bad and (persistent or len(probes)==1)
                (p/'xsim.log').write_text('PRIORITY_FIRST value=3 expected=0 observed=1\n' if wrong else '')
                return {'status':'fail' if wrong else 'pass','failure_kind':'semantic_mismatch' if wrong else None,'checks':c['checks'],'mismatches':1 if wrong else 0,'stages':[]}
            work=root/'work';work.mkdir();previous=Path.cwd()
            try:
                os.chdir(work)
                with patch.dict(os.environ,MODEL_NAME='fake-model',VIVADO_BIN=str(tools),RTL_PROFILE='development',RTL_REPAIRS='1',RTL_MAX_TOKENS='8192',RTL_TEMPERATURE='0'),patch.object(app,'_open',side_effect=network),patch.object(app.native_contract,'probe',side_effect=probe),patch.object(app.core.subprocess,'run',side_effect=compile),patch.object(app.core,'repair_ansi_declarations',return_value=GOOD if patched else None):
                    app.worker(task,out)
            finally:os.chdir(previous)
            code=(out/'solution.v').read_text(encoding='utf-8')
            events=[json.loads(s) for s in (out/'trace.jsonl').read_text().splitlines()]
            for body in calls:
                self.assertNotIn('PRIVATE_DO_NOT_READ',json.dumps(body));self.assertNotIn('R2Probe',json.dumps(body))
                self.assertEqual(body['max_tokens'],8192);self.assertEqual(body['temperature'],0)
            return calls,probes,events,code,text
    def test_package_integrity_baseline_and_core_exact(self):
        app.verify_package()
        self.assertEqual(hashlib.sha256((PKG/'agent/core.py').read_bytes()).hexdigest(),'2f7cb98bc44a9e100d36ca12ac4ef7bf9ae2535473da358e166afa2559e96cba')
        self.assertTrue(app.core.baseline_integrity())
    def test_real_staged_worker_uses_original_repair_with_factual_feedback(self):
        calls,probes,events,code,text=self.case()
        self.assertEqual((len(calls),len(probes)),(2,2));self.assertEqual(code,GOOD)
        skill,_=app.core.skill_texts()
        self.assertEqual(calls[0]['messages'],[{'role':'system','content':skill},{'role':'user','content':text}])
        self.assertIn('least significant',calls[1]['messages'][1]['content'])
        self.assertEqual(sum(e['tool']=='functional_probe' for e in events),2)
    def test_persistent_mismatch_never_third_request(self):
        calls,probes,_,code,_=self.case(persistent=True);self.assertEqual((len(calls),len(probes)),(2,2));self.assertEqual(code,BAD)
    def test_correct_source_byte_preserved_no_extra_call(self):
        calls,probes,_,code,_=self.case(bad=False);self.assertEqual((len(calls),len(probes)),(1,1));self.assertEqual(code,GOOD)
    def test_unknown_contract_skips_probe(self):
        calls,probes,_,code,_=self.case(unknown=True);self.assertEqual((len(calls),len(probes)),(1,0));self.assertEqual(code,BAD)
    def test_original_successful_declaration_patch_returns_before_optional_probe(self):
        calls,probes,_,code,_=self.case(patched=True);self.assertEqual((len(calls),len(probes)),(1,0));self.assertEqual(code,GOOD)
    def test_busy_or_invalid_slot_response_no_model_post(self):
        for data in [[{'is_processing':True}],[],['invalid'],{}]:
            with patch.object(app,'_open',return_value=io.BytesIO(json.dumps(data).encode())):
                self.assertFalse(app.slots_idle())
        with tempfile.TemporaryDirectory() as td,patch.object(app,'slots_idle',return_value=False),patch.object(app,'_run_job') as run:
            self.assertEqual(app.run_job('agent',Path(td),Path(td)/'out',10),('',''));run.assert_not_called()
    def test_child_dispatch_is_bridge_agent_and_untouched_baseline(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);task=root/'in';task.mkdir();(task/'prompt.txt').write_text('New request only')
            calls=[]
            class Process:
                pid=0
                def __init__(self,argv,**kwargs):
                    calls.append((argv,kwargs));out=Path(argv[-1] if Path(argv[1]).name=='runtime.py' else argv[-2]);(out/'solution.v').write_text(GOOD);(out/'trace.jsonl').write_text('')
                def wait(self,**kwargs):return 0
            with patch.object(app,'slots_idle',return_value=True),patch.object(app.core.subprocess,'Popen',Process),patch.object(app.core,'stop_tree'):
                for mode in ['agent','baseline']:self.assertEqual(app.run_job(mode,task,root/mode,5)[0],GOOD)
            self.assertEqual(Path(calls[0][0][1]),PKG/'agent/runtime.py')
            self.assertEqual(Path(calls[1][0][1]),PKG/'baseline.py')
            self.assertTrue(all('RTL_ABSOLUTE_DEADLINE' in kw['env'] for _,kw in calls))

class FakeModel(BaseHTTPRequestHandler):
    requests=[]
    busy=False
    def log_message(self,*a):pass
    def emit(self,x):
        data=json.dumps(x).encode();self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
    def do_GET(self):
        self.emit([{'is_processing':self.busy}] if self.path=='/slots' else {'data':[{'id':'fake-model'}]})
    def do_POST(self):
        x=json.loads(self.rfile.read(int(self.headers['Content-Length'])));self.requests.append(x)
        self.emit({'model':'fake-model','choices':[{'finish_reason':'stop','message':{'content':GOOD if 'Previous candidate:' in x['messages'][-1]['content'] else BAD}}],'usage':{'prompt_tokens':10,'completion_tokens':20}})

class Protocol(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model=ThreadingHTTPServer(('127.0.0.1',0),FakeModel);cls.mt=threading.Thread(target=cls.model.serve_forever,daemon=True);cls.mt.start()
        cls.agent=ThreadingHTTPServer(('127.0.0.1',0),app.core.Handler);cls.at=threading.Thread(target=cls.agent.serve_forever,daemon=True);cls.at.start()
    @classmethod
    def tearDownClass(cls):
        for s,t in [(cls.agent,cls.at),(cls.model,cls.mt)]:s.shutdown();s.server_close();t.join()
    def setUp(self):
        FakeModel.requests=[];FakeModel.busy=False
        self.env=patch.dict(os.environ,LLM_BASE_URL=f'http://127.0.0.1:{self.model.server_port}/v1',MODEL_NAME='fake-model',FPGACHINA_TOKEN='test-only-local',RTL_PROFILE='development',VIVADO_BIN='/intentionally-missing-tools',RTL_REPAIRS='1',RTL_MAX_TOKENS='8192',RTL_TEMPERATURE='0');self.env.start()
    def tearDown(self):self.env.stop()
    def post(self,data,token='test-only-local'):
        req=urllib.request.Request(f'http://127.0.0.1:{self.agent.server_port}/v1/solve',data=json.dumps(data).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer '+token})
        with urllib.request.urlopen(req,timeout=30) as r:return json.load(r)
    def test_http_auth_invalid_input_then_recovery(self):
        payload={'task_id':'opaque/../任务','nonce':'n1','prompt':'Fresh generic task','interface':'','deadline_s':10}
        for data,token,code in [(payload,'bad',401),({'task_id':9,'prompt':'x'},'test-only-local',400),({**payload,'mode':'other'},'test-only-local',400)]:
            with self.assertRaises(urllib.error.HTTPError) as caught:self.post(data,token)
            self.assertEqual(caught.exception.code,code)
        result=self.post(payload);self.assertEqual(result['task_id'],payload['task_id']);self.assertIn('module TopModule',result['solution'])
    def test_http_same_id_new_nonce_is_new_call_and_baseline_bypasses_skill(self):
        for mode,nonce in [('agent','n1'),('agent','n2'),('baseline','n3')]:
            response=self.post({'task_id':'same/id','nonce':nonce,'mode':mode,'prompt':'Independent generic request','interface':'','deadline_s':10})
            self.assertEqual(response['task_id'],'same/id');self.assertIn('module TopModule',response['solution'])
        self.assertEqual(len(FakeModel.requests),3)
        skill,_=app.core.skill_texts();self.assertEqual(FakeModel.requests[0]['messages'][0]['content'],skill)
        self.assertNotIn(skill,json.dumps(FakeModel.requests[-1]));self.assertNotIn('least significant',json.dumps(FakeModel.requests[-1]))
    def test_http_busy_returns_empty_then_recovers_without_restart(self):
        p={'task_id':'new','prompt':'Task','deadline_s':10};FakeModel.busy=True
        self.assertEqual(self.post(p)['solution'],'');self.assertEqual(FakeModel.requests,[])
        FakeModel.busy=False;self.assertIn('module TopModule',self.post(p)['solution']);self.assertEqual(len(FakeModel.requests),1)
    def test_http_200_consecutive_mixed_requests_same_process(self):
        for i in range(200):
            mode='baseline' if i%2 else 'agent'
            result=self.post({'task_id':f'id/{i}','nonce':f'nonce-{i}','mode':mode,'prompt':f'New generic specification {i}','interface':'','deadline_s':10})
            self.assertEqual(result['task_id'],f'id/{i}');self.assertIn('module TopModule',result['solution'])
        self.assertEqual(len(FakeModel.requests),200);self.assertTrue(self.at.is_alive());self.assertTrue(self.mt.is_alive())

if __name__=='__main__':unittest.main()
