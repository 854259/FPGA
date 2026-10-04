"""Linux owned-process integration using fake executable tools and fake model."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from test_bridge import app,prompt,FakeModel,GOOD,BAD

FAKE_TOOL=r'''#!/usr/bin/env python3
import json,os,pathlib,re,subprocess,sys,time
name=pathlib.Path(sys.argv[0]).name
if name=='xsim':
 sleep=float(os.environ.get('FAKE_XSIM_SLEEP','0'))
 if sleep:
  child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)'])
  def identity(pid):return {'pid':pid,'starttime':pathlib.Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[19]}
  pathlib.Path(os.environ['FAKE_OWNED_PIDFILE']).write_text(json.dumps({'tool':identity(os.getpid()),'descendant':identity(child.pid),'tool_pgid':os.getpgrp()}))
  time.sleep(sleep)
 tb=pathlib.Path('tb.sv').read_text();dut=pathlib.Path('dut.sv').read_text()
 task=re.search(r'R2_PROBE_RESULT task=(\S+) checks',tb)[1]
 checks=int(re.search(r'_prioritycheck_checks!=(\d+)',tb)[1])
 bad='assign idx=1;' in dut
 if bad:print('PRIORITY_FIRST value=3 expected=0 observed=1')
 print(f'R2_PROBE_RESULT task={task} checks={checks} mismatches={int(bad)}')
elif name=='vivado':print('Vivado v2026.1 FAKE_TEST_ONLY')
else:print('FAKE_TOOL_NO_AMD_EXECUTION')
'''

@unittest.skipUnless(sys.platform=='linux','Linux process-group checks run in queued stage')
class LinuxBridge(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='bridge-linux-owned-');self.root=Path(self.tmp.name)
        self.tools=self.root/'tools';self.tools.mkdir()
        for name in ['xvlog','xelab','xsim','vivado']:
            p=self.tools/name;p.write_text(FAKE_TOOL);p.chmod(0o700)
        FakeModel.requests=[];FakeModel.busy=False
        self.model=ThreadingHTTPServer(('127.0.0.1',0),FakeModel);self.mt=threading.Thread(target=self.model.serve_forever,daemon=True);self.mt.start()
        self.agent=ThreadingHTTPServer(('127.0.0.1',0),app.core.Handler);self.at=threading.Thread(target=self.agent.serve_forever,daemon=True);self.at.start()
        self.env=patch.dict(os.environ,LLM_BASE_URL=f'http://127.0.0.1:{self.model.server_port}/v1',MODEL_NAME='fake-model',FPGACHINA_TOKEN='test-only-local',RTL_PROFILE='development',VIVADO_BIN=str(self.tools),RTL_REPAIRS='1',RTL_MAX_TOKENS='8192',RTL_TEMPERATURE='0',FAKE_XSIM_SLEEP='0');self.env.start()
    def tearDown(self):
        for s,t in [(self.agent,self.at),(self.model,self.mt)]:s.shutdown();s.server_close();t.join()
        self.env.stop();self.tmp.cleanup()
    def post(self,deadline=10,mode='agent'):
        data={'task_id':'opaque/../新的题目','nonce':str(time.monotonic()),'mode':mode,'prompt':prompt(),'interface':'','deadline_s':deadline}
        req=urllib.request.Request(f'http://127.0.0.1:{self.agent.server_port}/v1/solve',data=json.dumps(data).encode(),headers={'Content-Type':'application/json','Authorization':'Bearer test-only-local'})
        with urllib.request.urlopen(req,timeout=20) as r:return json.load(r)
    def test_real_child_path_and_fake_native_feedback_reach_original_repair(self):
        result=self.post();self.assertEqual(result['solution'],GOOD);self.assertEqual(len(FakeModel.requests),2)
        events=[json.loads(s) for s in result['trace'].splitlines()]
        self.assertEqual(sum(e['tool']=='functional_probe' for e in events),2)
        self.assertEqual(sum(e['tool']=='xsim' for e in events),2)
        self.assertIn('least significant',FakeModel.requests[1]['messages'][1]['content'])
        self.assertNotIn('R2Probe',json.dumps(FakeModel.requests));self.assertNotIn('PRIVATE_DO_NOT_READ',json.dumps(FakeModel.requests))
    def test_deadline_stops_owned_tool_descendant_and_next_request_recovers(self):
        pidfile=self.root/'owned_pids.json'
        with patch.dict(os.environ,FAKE_XSIM_SLEEP='60',FAKE_OWNED_PIDFILE=str(pidfile)):
            started=time.monotonic();result=self.post(deadline=2);elapsed=time.monotonic()-started
        self.assertLess(elapsed,8);self.assertTrue(pidfile.exists(),'Must actually reach owned native tool before cancellation')
        identities=json.loads(pidfile.read_text())
        def live(identity):
            try:
                fields=Path(f'/proc/{identity["pid"]}/stat').read_text().rsplit(')',1)[1].split()
                return fields[19]==identity['starttime'] and fields[0] not in ['Z','X']
            except FileNotFoundError:return False
        until=time.monotonic()+3
        while any(live(identities[k]) for k in ['tool','descendant']) and time.monotonic()<until:time.sleep(.05)
        self.assertFalse(live(identities['tool']));self.assertFalse(live(identities['descendant']))
        self.assertNotEqual(identities['tool']['pid'],identities['tool_pgid'],'Tool must inherit worker group instead of creating another session')
        self.assertIn(result['solution'],[BAD,''])
        self.assertEqual(self.post(mode='baseline')['solution'],BAD)
        self.assertTrue(self.at.is_alive());self.assertTrue(self.mt.is_alive())

if __name__=='__main__':unittest.main()
