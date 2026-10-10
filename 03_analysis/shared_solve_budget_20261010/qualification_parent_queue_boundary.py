"""AMD changed-scope pre-grading boundary; admission/grade clock are simulated.

Real owned CPU echo children verify the inherited parent start for A/P/B.
Successful but over-budget receipts must not reach grading. This is not full
production admission, a B-model run, or model cancellation evidence.
"""
import hashlib,json,sys,time,types,ctypes
from pathlib import Path
ROOT=Path(sys.argv[1]).resolve();OUT=Path(sys.argv[2]).resolve()
assert sys.platform=='linux' and sys.dont_write_bytecode
assert ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)==0
OUT.mkdir(exist_ok=False);sys.path.insert(0,str(ROOT))
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
manifest=json.loads((ROOT/'SOURCE_MANIFEST.json').read_bytes())
assert all(sha(ROOT/n)==h for n,h in manifest.items())
import three_arm_queue_20261005 as queue,official_baseline_scoring_20261005 as scoring
original_resource=queue.official.resource_module()
original_validate,original_launch,original_resource_module=queue.validate,queue.launch_args,queue.official.resource_module
original_eligible=scoring.eligible;real_clock=time.monotonic
grade_calls=[];reports=[];offset=[0]
def no_grade(*a,**k):grade_calls.append(True);raise AssertionError('Over-budget success reached grading')
def shifted_clock():return real_clock()+offset[0]
code="import json,os,time;print(json.dumps(dict(parent_start=float(os.environ['RTL_SOLVE_PARENT_STARTED_MONOTONIC']),child_clock=time.monotonic())),flush=True)"
argv=['/usr/bin/python3','-B','-c',code]
try:
    queue.validate=lambda plan:None
    queue.launch_args=lambda *a:argv
    scoring.eligible=no_grade
    time.monotonic=shifted_clock
    for index,(arm,scope) in enumerate([('A','reported303'),('A','underreported_parent_over300'),('P','reported303'),('B','underreported_parent_over300')]):
        offset[0]=0;folder=OUT/str(index);folder.mkdir();raw=[]
        def controlled(argv,cwd,log,cap):
            result=original_resource.owned_command(argv,cwd,log,cap)
            assert result['returncode']==0 and not result['timeout'] and not result['remaining_live_group']
            event=json.loads(Path(log).read_text())
            assert 0<=event['child_clock']-event['parent_start']<2
            raw.append(dict(original_supervision_receipt=result,received_clock=event,argv=argv))
            result=dict(result)
            if scope=='reported303':result['elapsed_s']=303
            else:offset[0]=300.1
            return result
        queue.official.resource_module=lambda:types.SimpleNamespace(check_resource=lambda *a:None,owned_command=controlled)
        plan=dict(kit=str(ROOT),solve_supervisor_s=310,solve_deadline_s=300,allow_shared_budget_failure=True,
                  sources=dict(model_feedback=True,root=str(ROOT)))
        row=dict(arm=arm,evaluator_dir=str(ROOT/'synthetic_task'))
        receipt=queue.execute_row(plan,argv,row,folder,ROOT/'synthetic_admission.json')
        assert not receipt['complete'] and receipt['error']=='Solver deadline exceeded before grading'
        assert receipt['actual_calls'] is None and not grade_calls
        queue.save(folder/'BOUNDARY_RESULT.json',dict(receipt=receipt,raw_CPU_receipts=raw,
                   simulated_grade_clock_or_reported_elapsed=True,real_owned_CPU=True))
        reports.append(dict(arm=arm,case=scope,passed=True,real_parent_environment_bridge=True,
                            grading_not_reached=True,actual_CPU_command_elapsed_s=raw[0]['original_supervision_receipt']['elapsed_s']))
finally:
    time.monotonic=real_clock
    queue.validate,queue.launch_args,queue.official.resource_module=original_validate,original_launch,original_resource_module
    scoring.eligible=original_eligible
assert all(sha(ROOT/n)==h for n,h in manifest.items())
result=dict(schema='parent_queue_pregrading_clock_boundary_changed_scope_v1',passed=True,cases=reports,
            actual_execute_row_function=True,actual_owned_CPU_children=4,synthetic_admission_plan_validation_and_grade_clocks=True,
            production_B_CLI_or_full_chain_qualified=False,real_model_cancel_idle_qualified=False,
            original_upstream_baseline_bytes_changed=False,new_model_calls=0,new_EDA=0,new_FIFO=0,full_goal_complete=False)
(OUT/'QUALIFICATION_RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(dict(passed=True,cases=4,grading_not_reached=True,new_model_calls=0)))
