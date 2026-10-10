"""New official-B budget failure controls on AMD, not model/EDA qualification.

Exercises main/argparse, original shell/Python/observer and new queue/seal path.
Parent clock age, resource/idle admission and endpoint redirection are fixtures.
"""
import ctypes,hashlib,json,os,sys,threading,time,types
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
ROOT=Path(sys.argv[1]).resolve();OUT=Path(sys.argv[2]).resolve()
assert sys.platform=='linux' and sys.dont_write_bytecode
assert ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)==0
OUT.mkdir(exist_ok=False);sys.path.insert(0,str(ROOT))
import three_arm_queue_20261005 as queue
import failure_continuation as failure
import deadline_supervisor as owned
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
manifest=json.loads((ROOT/'SOURCE_MANIFEST.json').read_bytes())
assert all(sha(ROOT/n)==h for n,h in manifest.items())
posts=[];records=[]

class Handler(BaseHTTPRequestHandler):
 def log_message(self,*args):pass
 def do_GET(self):
  assert self.path=='/v1/models'
  data=json.dumps(dict(data=[dict(id='Qwen3.6-27B-Q4_K_M')])).encode()
  self.send_response(200);self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
 def do_POST(self):
  assert self.path=='/v1/chat/completions'
  body=self.rfile.read(int(self.headers['Content-Length']));posts.append(json.loads(body))
  self.send_response(200);self.send_header('Content-Length','1000');self.end_headers()
  time.sleep(4) # The fixture child is killed at the inherited remaining budget.

server=ThreadingHTTPServer(('127.0.0.1',0),Handler);server.daemon_threads=True
thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
url='http://127.0.0.1:'+str(server.server_address[1])+'/v1'
original_time,original_validate=queue.time,queue.validate
original_launch,original_resource=queue.launch_args,queue.official.resource_module
sources={str(ROOT/n):h for n,h in manifest.items()}
resource=types.SimpleNamespace(check_resource=lambda *a:dict(llm_base_url='http://127.0.0.1:8000/v1',model_name='Qwen3.6-27B-Q4_K_M'),
 model_idle=lambda *a:dict(model='Qwen3.6-27B-Q4_K_M',health_status='ok',processing_slots=0,slot_count=1))
try:
 for name,age in [('B_actual_CLI_budget_timeout',298.5),('B_expired_before_dispatch',301.)]:
  folder=OUT/name;folder.mkdir()
  row=dict(arm='B',key=name,reserved_calls=1,evaluator_dir=str(folder/'never_read'))
  plan=dict(kit=str(ROOT/'fixture_kit'),sources=dict(root=str(ROOT),model_feedback=True,files=sources),
   allow_shared_budget_failure=True,allow_inspected_solver_failure=True,solve_supervisor_s=310,
   solve_deadline_s=300,scheduler_sha256=sha(ROOT/'three_arm_queue_20261005.py'))
  calls=[]
  def aged_clock():
   calls.append(True)
   return time.monotonic()-age if len(calls)<=2 else time.monotonic()
  queue.time=types.SimpleNamespace(monotonic=aged_clock)
  queue.validate=lambda p:None
  argv=['/usr/bin/env','B_FIXTURE_HTTP='+url,'/usr/bin/python3','-B',str(ROOT/'baseline_main_fixture.py'),
   '--kit',str(ROOT/'fixture_kit'),'--task',str(ROOT/'fixture_task'),'--out',str(folder/'solve'),
   '--resource-check',str(ROOT/'UNUSED_FIXTURE_RESOURCE.json')]
  queue.launch_args=lambda *a:argv
  queue.official.resource_module=lambda:resource
  queue.save(folder/'STARTED.json',dict(row=row,plan_sha256=queue.digest(plan)))
  receipt=queue.execute_row(plan,argv,row,folder,None)
  queue.save(folder/'TERMINAL.json',receipt)
  assert not receipt['complete'] and receipt['error']=='Solver supervision failure'
  assert receipt['actual_calls'] is None and receipt['unconfirmed_calls'] is None
  budget=json.loads((folder/'solve/SHARED_BUDGET_EXIT.json').read_bytes())
  requests=json.loads((folder/'solve/requests.json').read_bytes())
  proof=json.loads((folder/'solve/BASELINE_BUDGET_FAILURE.json').read_bytes())
  assert budget['worker_role']=='official_B' and budget['elapsed_s']>=300
  assert len(requests)==(1 if age<300 else 0) and proof['client_attempts']==len(requests)
  assert not requests or requests[0]['response_received'] is False
  # Refuse a wrong observer source before any sealing mutation. Keep the real
  # immutable row/plan hash; the explicitly bad source lookup is a unit fault.
  bad=dict(plan,sources=dict(plan['sources'],files=dict(sources)))
  bad['sources']['files'][str(ROOT/'official_baseline_observed_20261005.py')]='0'*64
  refused=False
  try:failure.seal_failed_row(folder,row,bad,queue.digest(plan),None,resource,queue.save)
  except AssertionError as error:
   import traceback
   frame=traceback.extract_tb(error.__traceback__)[-1]
   assert 'observer' in (frame.line or '') and 'proof' in (frame.line or ''),frame
   refused=True
  assert refused and not (folder/'FAILED_SEALED.json').exists()
  inspection=failure.seal_failed_row(folder,row,plan,queue.digest(plan),None,resource,queue.save)
  assert failure.verify_failed_seal(folder,row,queue.digest(plan))['complete'] is False
  records.append(dict(case=name,passed=True,request_count=len(requests),main_executed=True,
   original_baseline_executed=age<300,clock=budget,inspection_is_synthetic=True,
   source_binding_negative_passed=True,failed_seal_sha256=sha(folder/'FAILED_SEALED.json'),
   command=json.loads((folder/'SOLVE_COMMAND.json').read_bytes())))
finally:
 queue.time,queue.validate,queue.launch_args,queue.official.resource_module=original_time,original_validate,original_launch,original_resource
 server.shutdown();server.server_close();thread.join(timeout=2)
assert len(posts)==1 and (posts[0]['temperature'],posts[0]['top_p'],posts[0]['max_tokens'])==(0,1,8192)
assert all(sha(ROOT/n)==h for n,h in manifest.items())
result=dict(passed=True,controls=records,new_B_main_controls=2,observer_source_refusals=2,
 actual_local_HTTP_POSTs=1,new_model_calls=0,new_EDA=0,new_FIFO=0,
 original_baseline_python_shell_preserved=True,physical300=False,real_model_cancel_idle=False,
 full_resource_admission=False,full_production_chain=False,source_manifest=manifest)
(OUT/'QUALIFICATION_RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(dict(passed=True,main_cases=2,source_refusals=2,local_fixture_POSTs=1)))
