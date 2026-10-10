"""AMD changed-scope clock sealing; synthetic solver/admission, real owned CPU.

The queue and SolveBudget exit receipt execute with one deliberately aged
parent start. This tests clock binding, not a physical 300s worker/model run.
"""
import ctypes,hashlib,importlib.util,json,sys,types,time
from pathlib import Path
ROOT=Path(sys.argv[1]).resolve();OUT=Path(sys.argv[2]).resolve()
assert sys.platform=='linux' and sys.dont_write_bytecode
assert ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)==0
OUT.mkdir(exist_ok=False);sys.path.insert(0,str(ROOT))
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
manifest=json.loads((ROOT/'SOURCE_MANIFEST.json').read_bytes())
assert all(sha(ROOT/n)==h for n,h in manifest.items())
import three_arm_queue_20261005 as queue,shared_budget,failure_continuation as failure
original_resource=queue.official.resource_module()
original_clock=time.monotonic
leaf=OUT/'synthetic_budget_exit.py'
leaf.write_text('''import json,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import shared_budget
out=Path(sys.argv[2]);out.mkdir()
requests=out/'requests.json';requests.write_text('[]\\n')
budget=shared_budget.SolveBudget(300,parent_started=shared_budget.parent_started_from_environment())
receipt=budget.exit_receipt(requests,Path(sys.argv[1])/'baseline_worker.py')
(out/'SHARED_BUDGET_EXIT.json').write_text(json.dumps(receipt)+'\\n')
raise SystemExit(1)
''')
original_validate,original_launch=queue.validate,queue.launch_args
original_resource_module,original_queue_time=queue.official.resource_module,queue.time
resource=types.SimpleNamespace(owned_command=original_resource.owned_command,
 check_resource=lambda *a:dict(llm_base_url='http://127.0.0.1:8000/v1',model_name='SYNTHETIC_IDLE_NO_MODEL'),
 model_idle=lambda *a:dict(model='SYNTHETIC_IDLE_NO_MODEL',health_status='ok',processing_slots=0,slot_count=1))
results=[]
try:
 queue.validate=lambda plan:None
 queue.official.resource_module=lambda:resource
 queue.launch_args=lambda plan,row,folder,resource_check:['/usr/bin/python3','-B',str(leaf),str(ROOT),str(Path(folder)/'solve')]
 for case,mutation in [('matching_parent_with_short_supervisor',None),
                       ('child_origin_mismatch_refused','origin'),
                       ('missing_parent_clock_refused','missing'),
                       ('scheduler_binding_drift_refused','scheduler')]:
  folder=OUT/case;folder.mkdir();row=dict(key=case,arm='A',reserved_calls=2,evaluator_dir=str(OUT/'unused_evaluator'))
  plan=dict(sources=dict(root=str(ROOT),model_feedback=True,files={str(ROOT/n):sha(ROOT/n) for n in ('shared_budget.py','baseline_worker.py')}),
   kit=str(OUT/'synthetic_kit'),solve_supervisor_s=310,solve_deadline_s=300,
   scheduler_sha256=sha(ROOT/'three_arm_queue_20261005.py'),allow_shared_budget_failure=True,allow_inspected_solver_failure=True)
  queue.save(folder/'STARTED.json',dict(row=row,plan_sha256=queue.digest(plan)))
  ticks=[0]
  def aged_parent_clock():
   ticks[0]+=1
   # execute_row calls this for its own start, then the solve start. All
   # subsequent readings are real. The child inherits that same aged start.
   return original_clock()-(301 if ticks[0]==2 else 0)
  queue.time=types.SimpleNamespace(monotonic=aged_parent_clock)
  receipt=queue.execute_row(plan,queue.launch_args(plan,row,folder,None),row,folder,None)
  queue.time=original_queue_time
  assert receipt['error']=='Solver supervision failure' and not receipt['complete']
  assert receipt['actual_calls'] is None and receipt['unconfirmed_calls'] is None
  command=json.loads((folder/'SOLVE_COMMAND.json').read_bytes())
  budget=json.loads((folder/'solve/SHARED_BUDGET_EXIT.json').read_bytes())
  clock=json.loads((folder/'SOLVE_CLOCK.json').read_bytes())
  assert command['returncode']==1 and not command['timeout'] and not command['remaining_live_group']
  assert command['elapsed_s']<10 and 300<=budget['elapsed_s']<=clock['elapsed_s']
  originals={n:sha(folder/n) for n in receipt['files']}
  if mutation=='origin':
   budget['started_monotonic']-=1;budget['elapsed_s']+=1
   queue.save(folder/'solve/SHARED_BUDGET_EXIT.json',budget)
  elif mutation=='missing':(folder/'SOLVE_CLOCK.json').unlink()
  elif mutation=='scheduler':
   clock['scheduler_sha256']='0'*64;queue.save(folder/'SOLVE_CLOCK.json',clock)
  if mutation:
   receipt['files']={p.relative_to(folder).as_posix():sha(p) for p in folder.rglob('*') if p.is_file()}
  queue.save(folder/'TERMINAL.json',receipt)
  refused=False
  try:failure.seal_failed_row(folder,row,plan,queue.digest(plan),None,resource,queue.save)
  except (AssertionError,KeyError):refused=True
  assert refused==(mutation is not None)
  if not mutation:
   assert failure.verify_failed_seal(folder,row,queue.digest(plan))==receipt
   assert all(sha(folder/n)==h for n,h in originals.items())
  else:assert not (folder/'FAILED_SEALED.json').exists()
  results.append(dict(case=case,passed=True,refused=refused,command=command,
   parent_elapsed_s=clock['elapsed_s'],child_elapsed_s=budget['elapsed_s'],
   fixture_solver_not_worker_CLI=True,parent_clock_aged=True,admission_and_idle_synthetic=True))
finally:
 queue.validate,queue.launch_args=original_validate,original_launch
 queue.official.resource_module,queue.time=original_resource_module,original_queue_time
assert all(sha(ROOT/n)==h for n,h in manifest.items())
report=dict(passed=True,controls=results,source_manifest=manifest,
 actual_execute_row_and_budget_exit_and_failure_seal=True,owned_CPU_children=4,
 physical300_run=False,actual_worker_CLI=False,actual_model_cancellation=False,
 full_production_chain_qualified=False,new_model_calls=0,new_EDA=0,new_FIFO=0)
(OUT/'QUALIFICATION_RESULT.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(dict(passed=True,controls=len(results),full_production_chain_qualified=False)))
