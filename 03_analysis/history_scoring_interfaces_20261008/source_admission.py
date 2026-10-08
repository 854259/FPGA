"""Source and reused native qualification checks, never old native re-execution."""
import hashlib,json
from pathlib import Path
import generation_binding
sha=generation_binding.sha
read=generation_binding.read
ORIGINAL='3fb1531c14b011f80ff58de559e326a4904d3fbdbcf3cdce7d6c955285860ba1'
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
  for position in reversed(patch['after_positions']):
   assert current[position:position+len(patch['after'])]==patch['after']
   current=current[:position]+patch['before']+current[position+len(patch['after']):]
  assert hashlib.sha256(current.encode()).hexdigest()==patch['before_sha256']
 assert hashlib.sha256(current.encode()).hexdigest()==adaptation['original_worker_sha256']=='e3d53648c31fa77acf4b9a30e91eee70252651f6a85399985e40db83e3585b6b'
 assert sha(run/'FULL_BASELINE_REFERENCE.json')=='8677fcf01f6589d7afee636cd328e7b296c5abef96da92adecd4929c007171ce'
 assert sha(run/'FULL_BASELINE_SOURCE_AUDIT.json')=='3be06a7939895221aa194dfd5ff6814fe1ac84dcdee5ff2215b1b347bea05652'
 inputs=read(run/'INPUT_MANIFEST.json');admission=read(run/'PRODUCTION_ADMISSION.json');tasks=original['task_ids'];assert len(tasks)==156 and tasks==sorted(tasks)
 assert admission['schema']=='history_composed_original_route_admission_v1' and admission['task_count']==156 and set(admission['tasks'])==set(tasks)
 emitted={}
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
   if route!='model':assert task not in emitted;emitted[task]=provider
 for task,record in admission['tasks'].items():assert record==dict(emitted=task in emitted,selected_provider=emitted.get(task))
 return dict(schema='history_combined_source_and_reused_native_admission_v1',original44_bound=True,common_baseline_bound=True,worker_reversibly_bound=True,producer_native_audits=NATIVE,existing_route_union=emitted,full_original_inputs_equal=True,new_native_or_worker_execution=False,score_or_adoption=False)
