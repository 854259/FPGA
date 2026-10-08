"""New source-admission/scoring/probe bridge controls; no worker/model/EDA/FIFO."""
import copy,hashlib,importlib.util,json,shutil,sys
from pathlib import Path
import source_admission,probe_evidence,metrics
ROOT=Path(__file__).resolve().parent
read=lambda p:json.loads(Path(p).read_bytes());sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,j):Path(p).write_bytes((json.dumps(j,indent=2)+'\n').encode())
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def reject(call):
 try:call()
 except (AssertionError,KeyError,ValueError,FileNotFoundError):return
 raise AssertionError('Malformed evidence accepted')
def main():
 manifest=read(ROOT/'SOURCE_MANIFEST.json');assert all(sha(ROOT/n)==h for n,h in manifest.items())
 admission=source_admission.verify(ROOT);assert admission['new_native_or_worker_execution'] is False
 positives=['actual_reused_native_qualifications_and_original44_source_admission'];negatives=[]
 for case in ['worker','upstream','worker_adaptation','onehot_native','timer_native','timer_archive','provider_binding','input_manifest','route_collision','production_admission']:
  folder=ROOT/'SOURCE_MUTANTS'/case
  for n in manifest:
   p=folder/n;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes((ROOT/n).read_bytes())
  if case in ['worker','upstream']:
   p=folder/('worker.py' if case=='worker' else 'upstream/worker.py');p.write_bytes(p.read_bytes()+b'\n')
  else:
   name={'worker_adaptation':'WORKER_ADAPTATION.json','onehot_native':'qualification/onehot/NATIVE_QUALIFICATION_AUDIT.json','timer_native':'qualification/timer/NATIVE_QUALIFICATION_AUDIT.json','timer_archive':'qualification/timer/NATIVE_ARCHIVE_BINDING.json','provider_binding':'qualification/onehot/PRODUCER_BINDING.json','input_manifest':'qualification/timer/INPUT_MANIFEST.json','route_collision':'qualification/timer/P_GENERATION_ROUTES.json','production_admission':'PRODUCTION_ADMISSION.json'}[case]
   p=folder/name;j=read(p)
   if case=='worker_adaptation':j['replacements'][-1]['after_positions'][0]+=1
   elif case in ['onehot_native','timer_native','timer_archive']:j['native_qualified']=False
   elif case=='provider_binding':j['producer_source_hashes']['synthesis.py']='0'*64
   elif case=='input_manifest':j['input_sha256'][next(iter(j['input_sha256']))]='0'*64
   elif case=='route_collision':j[next(t for t,p in admission['existing_route_union'].items() if p=='onehot')]='mechanical_serial_timer'
   else:j['tasks'][next(iter(admission['existing_route_union']))]['emitted']=False
   save(p,j)
  reject(lambda:source_admission.verify(folder));negatives.append('source_'+case)
 scorer=load('history_new_controls_original_score',ROOT/'OFFICIAL_SCORER.py');template=read(ROOT/'SYNTHETIC_VERDICT_TEMPLATE.json');levels=read(ROOT/'FULL_BASELINE_REFERENCE.json')['levels']
 def rows():
  result=[]
  for task,arm in metrics.order(metrics.TASKS):
   verdict=copy.deepcopy(template);verdict.update(task_id=task,level=levels[task],coefficient=metrics.COEFFICIENTS[levels[task]],tool_error=False)
   provider=admission['existing_route_union'].get(task) if arm=='P' else None
   result.append(dict(task=task,arm=arm,verdict=verdict,actual_model_requests=0 if provider else 1,received_model_responses=0 if provider else 1,solve_deadline_reached=False,solve_elapsed_s=.5,stage_generation_binding_verified=True,generation_route='mechanical_'+provider if provider else 'model',selected_provider=provider,producer_contract_sha256='a'*64 if provider else None,synthesis_receipt_sha256='b'*64 if provider else None,emitted_solution_sha256='c'*64 if provider else None,solution_sha256='c'*64,route_receipt_sha256='d'*64))
  return result
 def aggregate(r):return metrics.aggregate(r,metrics.TASKS,scorer)
 r=rows();a=aggregate(r);assert a['guard_pass'] and a['unchanged_task_request_cost'] and not a['screening_eligible'] and not a['goal_score_thresholds_met'];assert a['fully_correct_by_arm']==dict(C=113,P=113);positives.append('synthetic_two_zero_call_routes_original113_no_invented_gain')
 improved=metrics.TARGETS[:7]
 def favorable():
  r=rows()
  for x in r:
   if x['arm']=='P' and x['task'] in improved:x['verdict'].update(level=3,coefficient=1.)
  return r
 r=favorable();a=aggregate(r);assert a['goal_score_thresholds_met'] and a['screening_eligible'] and a['fully_correct_by_arm']['P']==120;positives.append('synthetic_threshold_control_not_measured_score')
 r=rows();t=next(t for t in metrics.TARGETS if levels[t]!=2)
 for x in r:
  if x['task']==t:x['verdict'].update(level=2,coefficient=.7)
 a=aggregate(r);assert not a['screening_eligible'];positives.append('synthetic_L2_coefficient_point7_preserved')
 for case in ['historical_regression','historical_extra_call','unchanged_extra_call','total_extra_calls','deadline','unconfirmed']:
  r=favorable()
  if case=='historical_regression':
   x=next(x for x in r if x['arm']=='P' and x['task'] in metrics.GUARDS and x['selected_provider'] is None);x['verdict'].update(level=1,coefficient=.2)
  elif case=='historical_extra_call':
   x=next(x for x in r if x['arm']=='P' and x['task'] in metrics.GUARDS and x['selected_provider'] is None);x['actual_model_requests']=x['received_model_responses']=2
  elif case=='unchanged_extra_call':
   x=next(x for x in r if x['arm']=='P' and x['task'] in metrics.TARGETS and x['task'] not in improved);x['actual_model_requests']=x['received_model_responses']=2
  elif case=='total_extra_calls':
   for x in r:
    if x['arm']=='P' and x['task'] in improved:x['actual_model_requests']=x['received_model_responses']=2
  elif case=='deadline':next(x for x in r if x['arm']=='P')['solve_deadline_reached']=True
  else:
   x=next(x for x in r if x['arm']=='P' and x['selected_provider'] is None);x['received_model_responses']=0
  a=aggregate(r);assert not a['screening_eligible'] and not a['goal_score_thresholds_met'];negatives.append('synthetic_gate_'+case)
 for case in ['wrong_provider','zero_model','wrong_emitted_solution','missing_row','reordered']:
  r=rows()
  if case=='wrong_provider':next(x for x in r if x['selected_provider']=='timer')['selected_provider']='onehot'
  elif case=='zero_model':next(x for x in r if x['generation_route']=='model')['actual_model_requests']=0
  elif case=='wrong_emitted_solution':next(x for x in r if x['selected_provider'])['emitted_solution_sha256']='0'*64
  elif case=='missing_row':r.pop()
  else:r[0],r[1]=r[1],r[0]
  reject(lambda:aggregate(r));negatives.append('synthetic_malformed_'+case)
 runner=load('history_controls_retained_native_runner',ROOT/'dependencies/probe_runner.py');shared=load('history_controls_original_common_helper',ROOT/'dependencies/full156_postflight_audit.py')
 parser=load('history_controls_original_parser',ROOT/'edge_dispatch.py');feedback=load('history_controls_original_feedback',ROOT/'phase_feedback.py');phase=load('history_controls_original_phase',ROOT/'phase_context.py');edge=load('history_controls_original_edge',ROOT/'edge_contract.py')
 binding=read(ROOT/'RETAINED_COMMON_PROBE/BINDING.json');check=ROOT/'RETAINED_COMMON_PROBE/map_check_0';contract=read(check/'contract.json')
 native=probe_evidence.verify(check,binding['task'],contract,parser,feedback,runner,shared,ROOT/'dependencies',phase,edge);assert native['task']==binding['task'];positives.append('new_probe_callback_reads_one_unchanged_old_native_record_no_execution')
 assert all(sha(ROOT/n)==h for n,h in manifest.items())
 result=dict(schema='history_scoring_new_interfaces_controls_v1',passed=True,positive_contexts=len(positives),rejection_contexts=len(negatives),positives=positives,rejections=negatives,scoring_cases_explicitly_synthetic=True,source_admission_reuses_old_qualifications=True,one_old_native_probe_record_read_only=True,old_worker_algorithm_native_intake_full_auditor_not_rerun=True,new_worker_model_EDA_FIFO_calls=0,full_stage_or_full_archive_auditor_executed=False,real_score_or_full156_qualification=False)
 save(ROOT/'ACTUAL_SCORING_INTERFACE_RESULT.json',result);print(json.dumps(result))
if __name__=='__main__':main()
