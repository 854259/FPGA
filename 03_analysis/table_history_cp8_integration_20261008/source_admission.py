"""CP8 fixed-seven source and retained qualification binding; no producer or native re-execution."""
import hashlib,json
from pathlib import Path
import generation_binding
sha=generation_binding.sha
read=generation_binding.read
ORIGINAL='3fb1531c14b011f80ff58de559e326a4904d3fbdbcf3cdce7d6c955285860ba1'
TABLE90_SPEC='0b9c1c07ed275eff5ba81d9281c86575db7f89b729d7951491dcafea73df6702'
TABLE90_AUDIT='bb691e96ffe900a1a23c5e581312dfe7e834c3c06e1747c204641a9f7aaaea88'
TABLE90_ARCHIVE='717720916aeee350c3468472c9ca50318ef21b0dff84cebdd943efa1b4ef9e5f'
CP8_SPEC='b11485bc55efe5eaf9c5dde6d55ed6f4d719eee4548a5e906b3f344f75518167'
CP8_AUDIT='15c1025f0b897afc058312ee845e928236b09ea1cba1174e12b4422b7841c4ff'
CP8_NATIVE='a909a642fc7f55b79b57915bf6981a0463359c30aca8b858ef48c92a9c4d1809'
TASKS=['Prob045_edgedetect2', 'Prob057_kmap2', 'Prob127_lemmings1', 'Prob137_fsm_serial', 'Prob143_fsm_onehot', 'Prob146_fsm_serialdata', 'Prob151_review2015_fsm']
HISTORICAL=['Prob045_edgedetect2','Prob127_lemmings1','Prob143_fsm_onehot','Prob151_review2015_fsm']
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
 cp8_adaptation=read(run/'CP8_WORKER_ADAPTATION.json');current=(run/'worker.py').read_bytes().decode()
 for patch in reversed(cp8_adaptation['replacements']):
  if patch['label'] in ('composition_import','producer_binding','normal_abstention_framing_extension'):continue
  assert hashlib.sha256(current.encode()).hexdigest()==patch['after_sha256']
  assert current.count(patch['after'])==1
  current=current.replace(patch['after'],patch['before'])
  assert hashlib.sha256(current.encode()).hexdigest()==patch['before_sha256']
 assert hashlib.sha256(current.encode()).hexdigest()==cp8_adaptation['base_worker_sha256']=='39d7f16515a10fe9e4fb97b036ce4839095c05ed3ee419fb52842c418599e87e'
 adaptation=read(run/'WORKER_ADAPTATION.json')
 for patch in reversed(adaptation['replacements']):
  assert hashlib.sha256(current.encode()).hexdigest()==patch['after_sha256']
  position=patch['position']
  assert type(position) is int and position>=0
  assert current[position:position+len(patch['after'])]==patch['after']
  current=current[:position]+patch['before']+current[position+len(patch['after']):]
  assert hashlib.sha256(current.encode()).hexdigest()==patch['before_sha256']
 assert hashlib.sha256(current.encode()).hexdigest()==adaptation['original_worker_sha256']=='16a824d901625dac008c92f6eeb71cf0f81c66f2d5bab521871c5e8edca26eb0'
 assert sha(run/'FULL_BASELINE_REFERENCE.json')=='8677fcf01f6589d7afee636cd328e7b296c5abef96da92adecd4929c007171ce'
 assert sha(run/'FULL_BASELINE_SOURCE_AUDIT.json')=='3be06a7939895221aa194dfd5ff6814fe1ac84dcdee5ff2215b1b347bea05652'
 inputs=read(run/'INPUT_MANIFEST.json');admission=read(run/'COMPARISON_INPUT_PLAN.json');tasks=original['task_ids'];assert len(tasks)==156 and tasks==sorted(tasks)
 assert admission['schema']=='table_history_cp8_score7_input_plan_v1' and admission['task_count']==7 and set(admission['tasks'])==set(TASKS)
 reference=read(run/'FULL_BASELINE_REFERENCE.json')
 assert [task for task in TASKS if reference['levels'][task]==3]==HISTORICAL
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
 # Original111 native and original113 scored source are reused without execution.
 q=run/'qualification/serial_framing'
 assert sha(q/'RUN_SPEC.json')==CP8_SPEC and sha(q/'RESULTS.json')==CP8_AUDIT
 serial_spec=read(q/'RUN_SPEC.json');serial_audit=read(q/'RESULTS.json')
 assert serial_spec['source_hashes']['synthesis.py']==sha(run/'serial_framing_producer.py')
 assert serial_spec['source_hashes']['reserved_keywords.py']==sha(run/'reserved_keywords.py')
 assert serial_spec['source_hashes']['baseline_worker.py']==sha(run/'baseline_worker.py')
 for name in ('INPUT_MANIFEST.json','SOURCE_FACTOR_PROOF.json','PRODUCER_PREPARATION_BINDING.json','NATIVE_QUALIFICATION_AUDIT.json','NATIVE_ARCHIVE_BINDING.json'):
  assert sha(q/name)==serial_spec['source_hashes'][name],name
 assert read(q/'INPUT_MANIFEST.json')==inputs
 assert serial_audit['spec_sha256']==CP8_SPEC and serial_audit['evidence_valid'] is True
 assert serial_audit['audited_generation_provenance_bound'] is True and serial_audit['screening_eligible'] is True
 assert serial_audit['adoption'] is False and serial_audit['full156_evidence_valid'] is False
 assert sha(q/'NATIVE_QUALIFICATION_AUDIT.json')==CP8_NATIVE
 native=read(q/'NATIVE_QUALIFICATION_AUDIT.json');archive=read(q/'NATIVE_ARCHIVE_BINDING.json');binding=read(q/'PRODUCER_PREPARATION_BINDING.json')
 assert native['evidence_valid'] is True and native['native_qualified'] is True and native['model_calls']==0
 assert archive['passed'] and archive['original_auditor_passed'] and archive['every_member_bound_both_ends'] and archive['native_qualified']
 assert archive['audit_sha256']==CP8_NATIVE and archive['producer_sha256']==sha(run/'serial_framing_producer.py')
 assert archive['spec_sha256']==native['source_sha256']==binding['native_spec_sha256']=='97adb9aa656b7df1eabd37757f2bedf6f01138e10b692baf8e9703ddeccb560e'
 assert binding['producer_source_hashes']=={'synthesis.py':sha(run/'serial_framing_producer.py'),'reserved_keywords.py':sha(run/'reserved_keywords.py')}
 serial_emits={p['task'] for p in serial_audit['provenance'] if p['arm']=='P' and p['generation_route']=='mechanical_serial_framing'}
 assert serial_emits==set(serial_spec['target_tasks'])=={'Prob137_fsm_serial','Prob146_fsm_serialdata'}
 expected={}
 for task in TASKS:
  prior=parent['tasks'][task];assert type(prior['emitted']) is bool
  parent_provider='table' if prior['emitted'] else None
  extension=emitted[task][0] if len(emitted[task])==1 else None
  common=parent_provider or extension
  assert common is not None or len(emitted[task])==0, 'Conflicting parent metadata cannot admit an extension'
  candidate=common or ('serial_framing' if task in serial_emits else None)
  expected[task]={arm:dict(route='mechanical_'+choice if choice else 'model',selected_provider=choice)
    for arm,choice in [('C',common),('P',candidate)]}
 assert admission['tasks']==expected
 return dict(schema='table_history_cp8_source_and_reused_native_admission_v1',original44_bound=True,
  common_baseline_bound=True,worker_reversibly_bound=True,worker_ancestor_sha256=adaptation['original_worker_sha256'],
  producer_native_audits=dict(NATIVE,serial_framing=CP8_NATIVE),table_parent_original_audit_sha256=TABLE90_AUDIT,
  table_parent_original_adoption=False,serial_original_spec_sha256=CP8_SPEC,serial_original_audit_sha256=CP8_AUDIT,
  existing_history_route_candidates=emitted,original_parent_input_routes_bound=True,full_original_inputs_equal=True,
  planned_task_count=7,known_uncovered_history=['Prob145_circuit8'],
  plan_is_scoring_metadata_only=True,new_native_or_worker_execution=False,score_or_adoption=False)
