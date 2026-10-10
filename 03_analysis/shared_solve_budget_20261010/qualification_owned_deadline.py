"""AMD new absolute-process deadline controls; no shared model or EDA.

Real owned CPU children, one independent sentinel, synthetic Popen delay and
queue admission. Aged parent budgets avoid a physical300 run. Full production
B CLI/model cancellation and full resource admission remain unqualified.
"""
import ctypes,hashlib,json,os,signal,subprocess,sys,threading,time,types
from pathlib import Path
ROOT=Path(sys.argv[1]).resolve();OUT=Path(sys.argv[2]).resolve()
assert sys.platform=='linux' and sys.dont_write_bytecode
assert ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)==0
OUT.mkdir(exist_ok=False);sys.path.insert(0,str(ROOT))
import owned_deadline as owned,shared_budget as budget
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
manifest=json.loads((ROOT/'SOURCE_MANIFEST.json').read_bytes())
assert all(sha(ROOT/n)==h for n,h in manifest.items())
results=[];real_popen=owned.subprocess.Popen
sentinel=real_popen(['/usr/bin/python3','-B','-c','import time;time.sleep(20)'],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
sentinel_identity=owned._stat(sentinel.pid)
assert sentinel_identity and sentinel_identity['pgid']==sentinel.pid
def safe():
 assert owned._stat(sentinel.pid)==sentinel_identity and sentinel.poll() is None
def old_supervisor_must_not_run(*a):raise AssertionError('Refreshed legacy supervisor was invoked')
def folder(name):
 p=OUT/name;p.mkdir();return p
def record(name,**values):
 safe();results.append(dict(case=name,passed=True,**values))
try:
 p=folder('fast_owned_operation');b=budget.SolveBudget(300,parent_started=time.monotonic()-299)
 receipt=b.owned_operation(old_supervisor_must_not_run)(['/usr/bin/python3','-B','-c','print("OWNED_FAST")'],p,p/'log.bin',300)
 assert receipt['returncode']==0 and not receipt['timeout'] and receipt['leader_reaped'] and not receipt['remaining_live_group']
 assert receipt['parent_deadline_monotonic']==b.end
 record('fast_owned_operation',receipt=receipt,actual_shared_budget_operation=True)

 p=folder('expired_after_preparation_no_dispatch');marker=p/'launched'
 b=budget.SolveBudget(300,parent_started=time.monotonic()-299.9);stale=b.remaining();time.sleep(.14)
 expired=False
 try:b.owned_operation(old_supervisor_must_not_run)(['/usr/bin/python3','-B','-c','from pathlib import Path;Path('+repr(str(marker))+').write_text("bad")'],p,p/'log.bin',stale)
 except budget.BudgetExpired:expired=True
 assert expired and not marker.exists() and not (p/'log.bin').exists()
 record('expired_after_preparation_no_dispatch',expired=True,stale_remaining_s=stale,actual_child_count=0)

 p=folder('shared_parent_deadline_kills_wait');b=budget.SolveBudget(300,parent_started=time.monotonic()-299.8)
 receipt=b.owned_operation(old_supervisor_must_not_run)(['/usr/bin/python3','-B','-c','import time;time.sleep(20)'],p,p/'log.bin',300)
 assert receipt['timeout'] and receipt['returncode']<0 and receipt['leader_reaped'] and not receipt['remaining_live_group']
 assert receipt['elapsed_s']<1.5 and receipt['parent_deadline_monotonic']==b.end
 record('shared_parent_deadline_kills_wait',receipt=receipt,aged_parent_clock=True)

 p=folder('Popen_delay_does_not_refresh_wait');events=[]
 def delayed_popen(*a,**kw):
  time.sleep(.18);proc=real_popen(*a,**kw);events.append(dict(pid=proc.pid,returned_monotonic=time.monotonic()));return proc
 owned.subprocess.Popen=delayed_popen
 started=time.monotonic()
 try:receipt=owned.owned_command(['/usr/bin/python3','-B','-c','import time;time.sleep(20)'],p,p/'log.bin',1,deadline=started+.06)
 finally:owned.subprocess.Popen=real_popen
 assert receipt['timeout'] and receipt['returncode']<0 and not receipt['remaining_live_group']
 assert events[0]['returned_monotonic']>receipt['work_deadline_monotonic']
 assert time.monotonic()-events[0]['returned_monotonic']<.5
 record('Popen_delay_does_not_refresh_wait',receipt=receipt,Popen_delay_is_synthetic=True,launch=events[0])

 p=folder('parent_first_group_cleanup');pid_path=p/'grandchild.pid'
 code='import subprocess,sys,time;from pathlib import Path;p=subprocess.Popen([sys.executable,"-B","-c","import time;time.sleep(20)"]);Path('+repr(str(pid_path))+').write_text(str(p.pid));time.sleep(.08)'
 receipt=owned.owned_command(['/usr/bin/python3','-B','-c',code],p,p/'log.bin',2,deadline=time.monotonic()+2)
 grandchild=int(pid_path.read_text());assert receipt['returncode']==0 and receipt['leader_reaped'] and not receipt['remaining_live_group']
 assert owned._stat(grandchild) is None
 record('parent_first_group_cleanup',receipt=receipt,retired_grandchild=grandchild)

 p=folder('signal_cancellation_reaps_owned_child');pid_path=p/'child.pid'
 before={s:signal.getsignal(s) for s in (signal.SIGTERM,signal.SIGINT)}
 timer=threading.Timer(.15,lambda:os.kill(os.getpid(),signal.SIGTERM));cancelled=False;timer.start()
 try:
  code='import os,time;from pathlib import Path;Path('+repr(str(pid_path))+').write_text(str(os.getpid()));time.sleep(20)'
  owned.owned_command(['/usr/bin/python3','-B','-c',code],p,p/'log.bin',2,deadline=time.monotonic()+2)
 except InterruptedError:cancelled=True
 finally:timer.cancel();timer.join()
 assert cancelled and all(signal.getsignal(s)==h for s,h in before.items())
 child=int(pid_path.read_text());assert owned._stat(child) is None
 record('signal_cancellation_reaps_owned_child',cancelled=True,retired_child=child,signal_handlers_restored=True)

 p=folder('one_hard_cleanup_endpoint');started=time.monotonic();hard=started+.5
 receipt=owned.owned_command(['/usr/bin/python3','-B','-c','import time;time.sleep(20)'],p,p/'log.bin',1,deadline=started+.1,cleanup_deadline=hard)
 assert receipt['timeout'] and receipt['leader_reaped'] and not receipt['remaining_live_group']
 assert receipt['cleanup_deadline_monotonic']==hard and time.monotonic()<hard
 record('one_hard_cleanup_endpoint',receipt=receipt,hard_cleanup_endpoint=hard)

 import three_arm_queue_20261005 as queue
 p=folder('actual_queue_absolute_supervisor_bridge');leaf=p/'no_model_exit.py';leaf.write_text('raise SystemExit(1)\n')
 actual_validate,actual_launch,actual_resource=queue.validate,queue.launch_args,queue.official.resource_module
 actual_owned=owned.owned_command;calls=[]
 def observed_owned(*a,**kw):
  result=actual_owned(*a,**kw);calls.append(dict(seconds=a[3],deadline=kw['deadline'],cleanup_deadline=kw['cleanup_deadline'],receipt=result));return result
 try:
  queue.validate=lambda plan:None
  queue.launch_args=lambda *a:['/usr/bin/python3','-B',str(leaf)]
  queue.official.resource_module=lambda:types.SimpleNamespace(check_resource=lambda *a:None)
  owned.owned_command=observed_owned
  plan=dict(kit=str(p/'synthetic_kit'),sources=dict(root=str(ROOT),model_feedback=True),allow_shared_budget_failure=True,solve_supervisor_s=310,solve_deadline_s=300)
  row=dict(arm='A',evaluator_dir=str(p/'not_read'))
  receipt=queue.execute_row(plan,queue.launch_args(None),row,p,None)
 finally:
  queue.validate,queue.launch_args,queue.official.resource_module=actual_validate,actual_launch,actual_resource
  owned.owned_command=actual_owned
 assert receipt['complete'] is False and receipt['actual_calls'] is None and receipt['error']=='Solver supervision failure'
 clock=json.loads((p/'SOLVE_CLOCK.json').read_bytes())
 assert len(calls)==1 and calls[0]['seconds']==310
 assert calls[0]['deadline']==calls[0]['cleanup_deadline']==clock['started_monotonic']+310
 assert clock['owned_deadline_source_sha256']==sha(ROOT/'owned_deadline.py')
 record('actual_queue_absolute_supervisor_bridge',call=calls[0],clock=clock,queue_admission_is_synthetic=True)
finally:
 owned.subprocess.Popen=real_popen
 if sentinel.poll() is None:
  assert owned._stat(sentinel.pid)==sentinel_identity;sentinel.kill()
 sentinel.wait(timeout=3)
assert owned._stat(sentinel.pid) is None
assert all(sha(ROOT/n)==h for n,h in manifest.items())
report=dict(passed=True,controls=results,independent_sentinel_retired=True,source_manifest=manifest,
 real_CPU_only=True,physical300_run=False,production_B_CLI_qualified=False,real_model_cancellation_qualified=False,
 full_production_chain_qualified=False,new_model_calls=0,new_EDA=0,new_FIFO=0)
(OUT/'QUALIFICATION_RESULT.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(dict(passed=True,controls=len(results),full_production_chain_qualified=False)))
