"""Draft source and retained qualification binding; no producer or native re-execution."""
import hashlib,json
from pathlib import Path
import generation_binding
sha=generation_binding.sha
read=generation_binding.read
ORIGINAL='3fb1531c14b011f80ff58de559e326a4904d3fbdbcf3cdce7d6c955285860ba1'
TABLE90_SPEC='0b9c1c07ed275eff5ba81d9281c86575db7f89b729d7951491dcafea73df6702'
TABLE90_AUDIT='bb691e96ffe900a1a23c5e581312dfe7e834c3c06e1747c204641a9f7aaaea88'
TABLE90_ARCHIVE='717720916aeee350c3468472c9ca50318ef21b0dff84cebdd943efa1b4ef9e5f'
SCREEN_TASKS=['Prob001_zero','Prob057_kmap2','Prob143_fsm_onehot','Prob145_circuit8','Prob151_review2015_fsm']
MODEL_TASKS=['Prob001_zero','Prob145_circuit8']
WAVE_SPEC='d3b4b69f85e358c749954c12509908172a74663a83c4739a57d0c26cec5f5c5e'
WAVE_AUDIT='6f5dc899dc35c95419f389499d8bb36f572d7a5b36e57b7c25e4ce07c808c4e8'
WAVE_SCOPE='b79f1bd616aafc1530e507de225bee8ddcdd077ac966c0277e3ee0c72ac954f4'
NATIVE={'onehot':'a0e506f4799f311caf8ea78b23c8ed838f2954b5d5109015fee56ee921a9e980','timer':'f57af8d7a6d2cb11abc051e757876679a8b7bc040787a52d296894cc2e84d8d7'}

def verify(run):
 run=Path(run)
 for n,h in generation_binding.PINNED.items():assert sha(run/n)==h,n
 assert sha(run/'original_model_replay.py')=='fc5f1d2bb1f81825a4b31bee3dc4a84d7182361c24eb4644a0835420cc308ac6'
 assert sha(run/'upstream/RUN_SPEC.json')==ORIGINAL
 original=read(run/'upstream/RUN_SPEC.json');assert len(original['source_hashes'])==44
 for n,h in original['source_hashes'].items():assert sha(run/'upstream'/n)==h,n
 old=(run/'upstream/worker.py').read_bytes();before=b"candidate=args.arm == 'P'";assert old.count(before)==1
 assert old.replace(before,b'candidate=True')==(run/'baseline_worker.py').read_bytes()
 for n in ['package/agent/map_runtime.py','package/agent/runtime.py','package/baseline.py','package/skill/rtl-generation/SKILL.md','package/skill/rtl-feedback-repair/SKILL.md','reserved_keywords.py','prompt_map.py','point_feedback.py','edge_dispatch.py','edge_feedback.py','phase_feedback.py','phase_context.py','edge_contract.py']:
  assert (run/n).read_bytes()==(run/'upstream'/n).read_bytes(),n
 adaptation=read(run/'WORKER_ADAPTATION.json');current=(run/'worker.py').read_bytes().decode()
 for patch in reversed(adaptation['replacements']):
  assert hashlib.sha256(current.encode()).hexdigest()==patch['after_sha256']
  position=patch['position']
  assert type(position) is int and position>=0
  assert current[position:position+len(patch['after'])]==patch['after']
  current=current[:position]+patch['before']+current[position+len(patch['after']):]
  assert hashlib.sha256(current.encode()).hexdigest()==patch['before_sha256']
 assert hashlib.sha256(current.encode()).hexdigest()==adaptation['original_worker_sha256']=='39d7f16515a10fe9e4fb97b036ce4839095c05ed3ee419fb52842c418599e87e'
 assert sha(run/'FULL_BASELINE_REFERENCE.json')=='8677fcf01f6589d7afee636cd328e7b296c5abef96da92adecd4929c007171ce'
 assert sha(run/'FULL_BASELINE_SOURCE_AUDIT.json')=='3be06a7939895221aa194dfd5ff6814fe1ac84dcdee5ff2215b1b347bea05652'
 inputs=read(run/'INPUT_MANIFEST.json');admission=read(run/'COMPARISON_INPUT_PLAN.json');tasks=original['task_ids'];assert len(tasks)==156 and tasks==sorted(tasks)
 assert admission['schema']=='table_history_wave_score5_input_plan_v1' and admission['task_count']==5 and set(admission['tasks'])==set(SCREEN_TASKS)
 emitted={task:[] for task in tasks}
 for provider,h in NATIVE.items():
  q=run/'qualification'/provider;assert sha(q/'NATIVE_QUALIFICATION_AUDIT.json')==h
  native=read(q/'NATIVE_QUALIFICATION_AUDIT.json');assert native['evidence_valid'] and native['native_qualified'] and native['model_calls']==0
  binding=read(q/'PRODUCER_BINDING.json');expected={'synthesis.py':sha(run/(provider+'_producer.py')),'reserved_keywords.py':sha(run/'reserved_keywords.py')}
  assert binding['producer_source_hashes']==expected
  if provider=='onehot':assert binding['native_audit_sha256']==h and native['source_sha256']=='6d0d61c65f49b68a33c825a9ae6ba8f6bb8bef2f2fad05f6f0495cd868866939'
  else:
   archive=read(q/'NATIVE_ARCHIVE_BINDING.json');assert archive['passed'] and archive['original_auditor_passed'] and archive['every_member_bound_both_ends'] and archive['native_qualified']
   assert archive['audit_sha256']==h and archive['producer_sha256']==expected['synthesis.py'] and archive['spec_sha256']==native['source_sha256']==binding['native_spec_sha256']=='141f5ecf638751d37f77c6c72aa61cf4cdef5cc3c2948657906a880c8eafa778'
  oldspec=read(q/'RUN_SPEC.json');assert oldspec['source_hashes']['synthesis.py']==expected['synthesis.py']
  assert read(q/'INPUT_MANIFEST.json')==inputs
  rows=read(q/'P_GENERATION_ROUTES.json');assert len(rows)==156 and set(rows)==set(tasks)
  for task,route in rows.items():
   assert route in ['model','mechanical_onehot' if provider=='onehot' else 'mechanical_serial_timer']
   if route!='model':emitted[task].append(provider)
 # The retained parent records were independently audited in original90.
 # They select no production route: composition.py only receives prompt/interface.
 q=run/'qualification/table90'
 assert sha(q/'RUN_SPEC.json')==TABLE90_SPEC
 parent_spec=read(q/'RUN_SPEC.json')
 assert parent_spec['source_hashes']['synthesis.py']==sha(run/'table_synthesis.py')
 assert parent_spec['source_hashes']['contract.py']==sha(run/'contract.py')
 assert parent_spec['source_hashes']['baseline_worker.py']==sha(run/'baseline_worker.py')
 for name in ('INPUT_MANIFEST.json','PRODUCTION_ADMISSION.json','SOURCE_FACTOR_PROOF.json'):
  assert sha(q/name)==parent_spec['source_hashes'][name],name
 assert read(q/'INPUT_MANIFEST.json')==inputs
 assert sha(q/'RESULTS.json')==TABLE90_AUDIT
 audited=read(q/'RESULTS.json')
 assert audited['evidence_valid'] is True and audited['full156_evidence_valid'] is True
 assert audited['audited_generation_provenance_bound'] is True
 assert audited['spec_sha256']==TABLE90_SPEC and audited['archive_sha256']==TABLE90_ARCHIVE
 assert audited['adoption'] is False and audited['qualified_for_goal'] is False
 parent=read(q/'PRODUCTION_ADMISSION.json')
 assert parent['schema']=='full156_prompt_only_admission_v1'
 assert parent['task_count']==156 and set(parent['tasks'])==set(tasks)
 # Scope was fixed before a new score: three mechanical preservation pairs,
 # the old wave advice target, and the first original historical task that
 # abstained in all retained mechanical routes and the original wave worker.
 q=run/'qualification/wave105'
 assert sha(q/'RUN_SPEC.json')==WAVE_SPEC
 wave_spec=read(q/'RUN_SPEC.json')
 for name in ('INPUT_MANIFEST.json','PRODUCTION_ADMISSION.json','SOURCE_FACTOR_PROOF.json'):
  assert sha(q/name)==wave_spec['source_hashes'][name],name
 assert read(q/'INPUT_MANIFEST.json')==inputs
 for name in ('waveform_facts.py','waveform_request.py','request_proof.py','waveform_replay.py'):
  assert sha(run/name)==wave_spec['source_hashes'][name],name
 assert sha(run/'waveform_worker.py')==wave_spec['source_hashes']['worker.py']
 assert sha(q/'RESULTS.json')==WAVE_AUDIT
 wave_audit=read(q/'RESULTS.json')
 assert wave_audit['evidence_valid'] is True and wave_audit['full156_evidence_valid'] is True
 assert wave_audit['spec_sha256']==WAVE_SPEC and wave_audit['adoption'] is False
 assert sha(q/'MODEL_SCOPE_RECEIPTS.json')==WAVE_SCOPE
 scope=read(q/'MODEL_SCOPE_RECEIPTS.json')
 assert scope['schema']=='retained_wave105_two_model_scope_v1' and set(scope['tasks'])==set(MODEL_TASKS)
 assert scope['original_spec_sha256']==WAVE_SPEC and scope['audit_sha256']==WAVE_AUDIT
 assert scope['archive_sha256']==wave_audit['archive_sha256']
 for task,arms in scope['tasks'].items():
  assert set(arms)=={'C','P'}
  for arm,record in arms.items():
   folder=q/'model_scope'/task/arm
   for name,binding in record['files'].items():assert sha(folder/name)==binding['sha256'],(task,arm,name)
   receipt=read(folder/'receipt.json')
   assert receipt['prompt_sha256']==inputs['input_sha256'][task+'/prompt.txt']
   assert receipt['arm']==arm and receipt['round_index']==0
   assert receipt['original_wire_sha256']==sha(folder/'original_wire.bin')==record['first_original_wire_sha256']
   assert receipt['forwarded_wire_sha256']==sha(folder/'forwarded_wire.bin')==record['first_forwarded_wire_sha256']
   assert read(folder/'forwarded_wire.bin')==read(folder/'request.json')
   assert receipt['changed'] is (task=='Prob145_circuit8' and arm=='P')
   assert receipt['model_request_delta']==0 and receipt['output_token_budget']==8192 and receipt['maximum_requests']==2
   usage=read(folder/'response_usage.json');assert usage['usage']['prompt_tokens']==record['first_prompt_tokens']
   assert type(record['first_prompt_tokens']) is int and record['first_prompt_tokens']+8192<16384
  assert arms['C']['first_original_wire_sha256']==arms['P']['first_original_wire_sha256']
 assert scope['tasks']['Prob001_zero']['P']['observation_status']=='skip'
 assert scope['tasks']['Prob145_circuit8']['P']['observation_status']=='supported'
 reference=read(run/'FULL_BASELINE_REFERENCE.json')
 assert tasks[0]=='Prob001_zero' and reference['levels']['Prob001_zero']==3
 assert scope['tasks']['Prob001_zero']['C']['original_level']==scope['tasks']['Prob001_zero']['P']['original_level']==3
 expected={}
 for task in SCREEN_TASKS:
  prior=parent['tasks'][task];assert type(prior['emitted']) is bool
  extension=emitted[task][0] if len(emitted[task])==1 else None
  provider='table' if prior['emitted'] else extension
  expected[task]={arm:dict(route='mechanical_'+provider if provider else 'model',selected_provider=provider,
    first_request_advice_changed=scope['tasks'][task][arm]['changed'] if provider is None else False) for arm in ['C','P']}
 assert expected['Prob001_zero']['C']['route']=='model'
 assert expected['Prob057_kmap2']['C']['route']=='mechanical_table'
 assert expected['Prob143_fsm_onehot']['C']['route']=='mechanical_onehot'
 assert expected['Prob145_circuit8']['C']['route']=='model'
 assert expected['Prob151_review2015_fsm']['C']['route']=='mechanical_timer'
 assert admission['tasks']==expected
 return dict(schema='table_history_wave_score5_reused_source_binding_v1',original44_bound=True,
  common_baseline_bound=True,worker_reversibly_bound=True,worker_ancestor_sha256=adaptation['original_worker_sha256'],
  producer_native_audits=NATIVE,table_parent_original_audit_sha256=TABLE90_AUDIT,
  table_parent_original_adoption=False,wave_original_audit_sha256=WAVE_AUDIT,
  first_wire_scope_metadata_sha256=WAVE_SCOPE,task_ids=SCREEN_TASKS,
  full_original_inputs_equal=True,plan_is_scoring_metadata_only=True,
  new_native_or_worker_execution=False,new_full156_algorithm_scan=False,score_or_adoption=False)
