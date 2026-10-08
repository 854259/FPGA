"""AMD-only new integration: reuse captured worker evidence; never replay model/EDA."""
import copy,hashlib,json,sys,tempfile,zipfile
from pathlib import Path
import audit,factor_admission,factor_proof,metrics,pilot,preparation_inputs,request_proof
ROOT=Path(__file__).parent
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
read=lambda p:json.loads(Path(p).read_bytes())
def rejected(fn):
 try:fn()
 except (AssertionError,KeyError,ValueError):return True
 raise AssertionError('Invalid evidence was accepted')
class Scorer:
 def summarize(self,data):
  levels=[x[0]['level'] for x in data.values()]
  return dict(tasks=len(data),scored_tasks=len(data),tool_errors=0,samples_per_task=1,level_counts={f'L{i}':levels.count(i) for i in range(4)})
def main():
 assert sys.platform=='linux' and sys.dont_write_bytecode
 qualifier=factor_admission.verify(ROOT)
 proof=factor_proof.verify(ROOT)
 scope=preparation_inputs.task_groups(ROOT)
 assert scope['task_ids']==metrics.TASKS and len(scope['guard_tasks'])==8 and len(scope['target_tasks'])==7
 assert [int(t[4:7]) for t in metrics.TASKS]==[45,54,78,118,127,129,139,142,143,145,151,152,153,154,155]
 rows=[]
 for task,arm in metrics.order(metrics.TASKS):
  level=1 if task==metrics.TARGETS[0] and arm=='C' else 3
  rows.append(dict(task=task,arm=arm,verdict=dict(task_id=task,tool_error=None,level=level,coefficient=metrics.COEFFICIENTS[level]),actual_model_requests=1,received_model_responses=1,solve_deadline_reached=False,solve_elapsed_s=1.,generation_route='model',stage_generation_binding_verified=True,declaration_factor_binding_verified=True,request_proof_sha256='1'*64,first_system_changed=False,declaration_enabled=arm=='P'))
 aggregate=lambda r:metrics.aggregate(r,metrics.TASKS,Scorer())
 good=aggregate(rows);assert good['screening_eligible'] and good['strict_new_L3_net']==1
 tests=[dict(name='new15_positive_original_gates',passed=True)]
 def change(task,arm,**changes):
  r=copy.deepcopy(rows);row=next(x for x in r if x['task']==task and x['arm']==arm);row.update(changes);return r
 def verdict(task,arm,level):return change(task,arm,verdict=dict(task_id=task,tool_error=None,level=level,coefficient=metrics.COEFFICIENTS[level]))
 r=verdict(metrics.TARGETS[0],'P',1);assert not aggregate(r)['screening_eligible'];tests.append(dict(name='no_new_correct_answer_rejected',passed=True))
 r=verdict(metrics.GUARDS[0],'P',1);c=next(x for x in r if x['task']==metrics.GUARDS[0] and x['arm']=='C');c['verdict'].update(level=1,coefficient=.2)
 result=aggregate(r);assert not result['guard_pass'] and not result['screening_eligible'] and metrics.GUARDS[0] in result['original113_regressions'];tests.append(dict(name='joint_historical_failure_remains_gap',passed=True))
 result=aggregate(verdict(metrics.TARGETS[1],'P',1));assert metrics.TARGETS[1] in result['regressions'] and not result['screening_eligible'];tests.append(dict(name='paired_grade_regression_rejected',passed=True))
 r=change(metrics.GUARDS[0],'P',actual_model_requests=2,received_model_responses=2);result=aggregate(r);assert not result['unchanged_task_request_cost'] and not result['historically_correct_request_cost'] and not result['screening_eligible'];tests.append(dict(name='historical_same_grade_extra_request_rejected',passed=True))
 r=change(metrics.TARGETS[0],'P',actual_model_requests=2,received_model_responses=2);assert not aggregate(r)['screening_eligible'];tests.append(dict(name='total_request_cost_increase_rejected',passed=True))
 # The original objective does not forbid an extra request on an improved nonhistorical task if total cost is offset.
 r=change(metrics.TARGETS[0],'P',actual_model_requests=2,received_model_responses=2);offset=next(x for x in r if x['task']==metrics.TARGETS[1] and x['arm']=='C');offset.update(actual_model_requests=2,received_model_responses=2)
 result=aggregate(r);assert result['screening_eligible'] and not result['all_task_request_cost'] and result['requests_by_arm']['P']==result['requests_by_arm']['C'];tests.append(dict(name='original_offset_total_cost_rule_preserved',passed=True))
 assert not aggregate(change(metrics.TARGETS[0],'P',received_model_responses=0))['screening_eligible'];tests.append(dict(name='unconfirmed_request_rejected',passed=True))
 assert not aggregate(change(metrics.TARGETS[0],'P',solve_deadline_reached=True,solve_elapsed_s=300.))['screening_eligible'];tests.append(dict(name='solver_deadline_rejected',passed=True))
 assert rejected(lambda:aggregate(change(metrics.TARGETS[0],'P',first_system_changed=True)));tests.append(dict(name='system_prompt_factor_rejected',passed=True))
 assert rejected(lambda:aggregate(change(metrics.TARGETS[0],'P',declaration_enabled=False)));tests.append(dict(name='wrong_arm_factor_binding_rejected',passed=True))
 assert rejected(lambda:aggregate(rows[:-1]));tests.append(dict(name='incomplete30_rows_rejected',passed=True))
 provenance=[dict(task=r['task'],arm=r['arm'],generation_route='model',**{f:True for f in ['generation_route_bound','input_bytes_bound','source_hashes_bound','solution_bytes_bound','native_execution_bound','original_model_replay_bound','declaration_factor_bound']}) for r in rows]
 assert metrics.decision(good,provenance,rows)['qualified_for_new_full_regression'];provenance[0]['declaration_factor_bound']=False;assert not metrics.decision(good,provenance,rows)['qualified_for_new_full_regression'];tests.append(dict(name='missing_declaration_audit_blocks_full156',passed=True))
 archived=[];mutations=0
 with tempfile.TemporaryDirectory(prefix='declaration15-readonly-controls-',dir=ROOT) as td:
  base=Path(td)
  with zipfile.ZipFile(ROOT/'QUALIFYING_FACTOR/PIPELINE4.zip') as z:
   # Original worker evidence and authored fixture only; no production worker/model/native execution.
   for n in z.namelist():
    if n.startswith(('run/PIPELINE_RESULTS/','run/FIXTURE_KIT/')):
     p=base/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(z.read(n))
  generation=(ROOT/'package/skill/rtl-generation/SKILL.md').read_text();repair=(ROOT/'package/skill/rtl-feedback-repair/SKILL.md').read_text()
  source=base/'run/FIXTURE_KIT/bench/tasks_veval/engineering_fixture'
  pilot.request_proof=request_proof
  for case in ['mechanical_success','mechanical_failure_original_repair']:
   for arm in ['C','P']:
    work=base/'run/PIPELINE_RESULTS'/case/arm;journal=read(work/'requests.json')
    row=dict(arm=arm,actual_model_requests=len(journal),received_model_responses=len(journal))
    result,first=audit.model_requests(work,row,dict(model='pipeline-fixture-only'),generation,repair)
    bound=pilot.generation_binding(work,source,arm,journal,dict(model='pipeline-fixture-only'))
    assert result==journal and bound['declaration_factor_binding_verified'] and not bound['first_system_changed'] and bound['declaration_enabled']==(arm=='P')
    wrong=dict(row,actual_model_requests=3);assert rejected(lambda:audit.model_requests(work,wrong,dict(model='pipeline-fixture-only'),generation,repair));mutations+=1
    bad=work/'requests/0/request.json';original=bad.read_bytes();body=json.loads(original);body['messages'][0]['content']+=' altered';bad.write_bytes(json.dumps(body).encode())
    assert rejected(lambda:audit.model_requests(work,row,dict(model='pipeline-fixture-only'),generation,repair));mutations+=1;bad.write_bytes(original)
    archived.append(dict(case=case,arm=arm,requests=len(journal),generation_binding=bound))
 result=dict(schema='internal_declaration_scoring_integration_actual_result_v1',passed=True,acceptance_cases=len(tests),archived_worker_contexts=len(archived),new_audit_rejection_checks=mutations,
  factor_qualifier=qualifier,source_proof=proof,tests=tests,archived_contexts=archived,old_worker_controls_not_replayed=True,
  model_calls=0,EDA_calls=0,FIFO=False,prepared=False,score_measured=False,goal_achieved=False)
 (ROOT/'ACTUAL_INTEGRATION_RESULT.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k not in ['factor_qualifier','source_proof','tests','archived_contexts']}))
if __name__=='__main__':main()
