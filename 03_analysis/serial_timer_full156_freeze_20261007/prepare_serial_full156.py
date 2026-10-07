"""Fresh all156 onehot admission on AMD; unchanged production and original budgets."""
import ast,datetime,hashlib,json,os,shutil,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
read=lambda p:json.loads(Path(p).read_bytes())
def save(p,j):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('x',encoding='utf-8') as f:json.dump(j,f,indent=2);f.write('\n')
def function_bytes(p,name):
 b=Path(p).read_text();n=[n for n in ast.parse(b).body if isinstance(n,ast.FunctionDef) and n.name==name];assert len(n)==1
 return ast.get_source_segment(b,n[0])
def main():
 assert sys.platform=='linux' and sys.version_info[:2]==(3,12) and sys.dont_write_bytecode and sha('/usr/bin/python3')=='8295ee25cfdb239f3e165afceda7f46de73e2b606ff0e2e3d8623e3facd30acc'
 assert str(ROOT)=='/workspace/team/runs/fpga_owner/serial_timer_synthesis_full156_20261007_v1' and not (ROOT/'RUN_SPEC.json').exists()
 parent=Path('/workspace/team/runs/fpga_owner/serial_timer_synthesis_cp7_20261007_v1');terminal=Path(str(parent)+'_terminal_review_v2')
 assert sha(parent/'RUN_SPEC.json')==sha(ROOT/'QUALIFYING_CP7_SPEC.json')=='378c8706992c4da961dc4c237a4aad6b21bf48c4aefb13e51dfa4a8cf97ef117'
 cp=read(parent/'RUN_SPEC.json');assert len(cp['source_hashes'])==101
 for n,h in cp['source_hashes'].items():assert sha(parent/n)==h
 os.environ.update(cp['compiler_env']);os.environ.update(RTL_MAX_TOKENS='8192',RTL_REPAIRS='1',RTL_TEMPERATURE='0',MODEL_NAME=cp['model'],LLM_BASE_URL='http://127.0.0.1:8000/v1')
 import factor_proof,metrics,pilot,preparation_inputs,protected_sources,guard_wrapper
 checks=[]
 # Actual original serialized audit bytes, not reserialized derivative metadata.
 assert sha(terminal/'audit/RESULTS.json')=='4578ce6bbd335d67f1e02a4a33553fa03048fde48cea04fe63c679fbe1044803'
 assert sha(terminal/'terminal_v1.zip')=='02002e35f411644992723980a0ba2103634418cb74d3a0e958114e8fcb8f3633'
 qualifying=read(terminal/'audit/RESULTS.json');assert qualifying['evidence_valid'] and qualifying['qualified_for_new_full_regression'] and qualifying['guard_pass'] and qualifying['unchanged_task_request_cost'] and qualifying['regressions']==[] and qualifying['unconfirmed_attempts']==0 and not qualifying['adoption']
 shutil.copyfile(terminal/'audit/RESULTS.json',ROOT/'QUALIFYING_CP7_AUDIT.json');assert sha(ROOT/'QUALIFYING_CP7_AUDIT.json')==sha(terminal/'audit/RESULTS.json')
 factor=factor_proof.verify(ROOT,require_native=True);assert factor==read(ROOT/'SOURCE_FACTOR_PROOF.json')==factor_proof.verify(parent,require_native=True)
 adaptation=read(ROOT/'FULL_SOURCE_ADAPTATION_PROOF.json')
 for n,h in adaptation['unchanged_production_and_native_sources'].items():assert sha(ROOT/n)==sha(parent/n)==h
 checks.append('original108 qualifier and exact unchanged single-factor production/native107 bound')
 # All input bytes and old admission retained; no new156 producer scan.
 admission=read(ROOT/'PRODUCTION_ADMISSION.json');intake=Path(admission['original_intake_root']);assert sha(intake/'INTAKE_RECEIPT.json')==admission['original_receipt_sha256']=='372887fc6483bd8f0995e88f1089575525f5b9c49c4b47e54a5c08c58b6846f0'
 assert sha(intake/'PRIVATE_INTAKE_ROWS.json')==admission['original_private_rows_sha256']=='5d062924bae20ef218a41b4985de3ae6029120bf292604e53c75f226173bf0ad'
 ir=read(intake/'INTAKE_RESULT.json');assert ir['passed'] and ir['complete'] and (ir['tasks'],ir['emitted'],ir['abstained'])==(156,1,155) and ir['producer_sha256']==admission['producer_sha256']==sha(ROOT/'synthesis.py')
 admission=read(ROOT/'PRODUCTION_ADMISSION.json');assert (admission['task_count'],admission['emitted'],admission['abstentions'])==(156,1,155)
 kit=Path(cp['kit']);inputs=read(ROOT/'INPUT_MANIFEST.json')
 for n,h in inputs['input_sha256'].items():assert sha(kit/'bench/tasks_veval'/n)==h
 for n,h in inputs['official_sha256'].items():assert sha(kit/'official_reference'/n)==h
 for task,row in admission['tasks'].items():
  source=kit/'bench/tasks_veval'/task;interface=source/'interface.txt'
  assert sha(source/'prompt.txt')==row['prompt_sha256'] and (sha(interface) if interface.is_file() else hashlib.sha256(b'').hexdigest())==row['interface_sha256']
 selected=preparation_inputs.validate_kit(ROOT,kit)
 assert selected['task_ids']==metrics.TASKS and len(metrics.TASKS)==156 and len(metrics.GUARDS)==113 and len(metrics.EMIT_TASKS)==1 and len(metrics.ABSTENTIONS)==155 and selected['expected_samples']==312
 assert sha(ROOT/'FULL_BASELINE_SOURCE_AUDIT.json')=='3be06a7939895221aa194dfd5ff6814fe1ac84dcdee5ff2215b1b347bea05652'
 checks.append('all156 input bytes,113 historical guards and exact1emit155abstain admission bound')
 # Original generic15 gate suite is a byte bijection, reused rather than rerun.
 fullfsm=Path('/workspace/team/runs/fpga_owner/onehot_synthesis_full156_20261007_v1');fsm=read(fullfsm/'RUN_SPEC.json')
 for n,b in adaptation['generic_full_gate_route_bijection'].items():
  assert sha(fullfsm/n)==fsm['source_hashes'][n]==b['parent_sha256'] and sha(ROOT/n)==b['current_sha256']
  assert (ROOT/n).read_bytes()==(fullfsm/n).read_bytes().replace(b'mechanical_onehot',b'mechanical_serial_timer')
 generic=Path('/workspace/team/runs/fpga_owner/vector_full156_controls_20261006_v1')
 assert sha(generic/'ACTUAL_CONTROLS_RECEIPT.json')=='e4ad4ecc67316d4bf19f3fe49209caaf9c5ab87f03b0b5f3aa758261174c2adf'
 gr=read(generic/'ACTUAL_CONTROLS_RECEIPT.json');assert gr['passed'] and gr['actual_controls']==15
 for n in ('generation_binding','solver_measurement'):assert function_bytes(ROOT/'pilot.py',n)==function_bytes(parent/'pilot.py',n)
 assert sha(ROOT/'upstream/official_eval_guarded.py')=='5d1911d8b730cbb460bf7ceb33cc602bf1f840402971e3dc1301f470fbd52a4c'
 checks.append('same original grade,provenance,complete300 solver measurement and historical/per-task/total cost gates retained')
 # New inventory starts from the immutable active109 source capture; excludes progress files.
 active=Path('/workspace/team/runs/fpga_owner/onehot_synthesis_full156_20261007_v1');assert sha(active/'RUN_SPEC.json')=='11717fea37f096c5e4e32f40d8ea7172304f339318c00f14e0ecbd7ac4bd4311'
 active_spec=read(active/'RUN_SPEC.json');assert len(active_spec['source_hashes'])==136
 protection=read(active/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json');assert len(protection['groups'])==125 and protection['source_assets']==7928
 original_capture=read(ROOT/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json')
 assert all(protection['groups'].get(n)==g for n,g in original_capture['groups'].items())
 assert sha(ROOT/'raw_evidence/IMMUTABLE_ORIGINAL109_CAPTURE.json')=='61972041751052691c9e42e0683a7d49e51abb9a956c8c32271ed711409091c3'
 anchor=read(ROOT/'raw_evidence/IMMUTABLE_ORIGINAL109_CAPTURE.json');assert all(protection['groups'].get(n)==g for n,g in anchor['groups'].items())
 assert 'onehot109_active_original_frozen_sources' not in protection['groups']
 protection['groups']['onehot109_active_original_frozen_sources']=dict(cloud_root=str(active),spec_name='RUN_SPEC.json',spec_sha256=sha(active/'RUN_SPEC.json'),source_hashes=active_spec['source_hashes'])
 protection['source_assets']=sum(len(g['source_hashes']) for g in protection['groups'].values());checked=protected_sources.check(protection)
 assert len(protection['groups'])==126 and protection['source_assets']==8064
 checks.append('immutable95/6516,original109/7389 and current125/7928 retained;136 active109 frozen sources added, progress excluded')
 environment=pilot.validate_environment();assert environment['tools']==cp['compiler_tools'] and environment['compiler_env']==cp['compiler_env'] and environment['udev_files']==cp['udev_files']
 for n,h in cp['dependency_hashes'].items():assert sha(ROOT/'dependencies'/n)==h
 captured=read(ROOT/'raw_evidence/ENVIRONMENT_CAPTURE.json');fresh_protected=guard_wrapper.protected(kit);fresh_model=guard_wrapper.identity(cp['model_pid'])
 assert fresh_protected==cp['protected'] and fresh_model==cp['model_identity']
 captured.update(schema='actual_serial_timer_full156_fresh_environment_capture_v1',observed_at_epoch=time.time(),dependencies_cloud=str(ROOT/'dependencies'),dependency_hashes=cp['dependency_hashes'],compiler_tools=environment['tools'],compiler_env=environment['compiler_env'],udev_files=environment['udev_files'],protected=fresh_protected,model_identity=fresh_model,disk_free_bytes=shutil.disk_usage(ROOT).free,task_submitted=False)
 for n,data in [('ENVIRONMENT_CAPTURE.json',captured),('PROTECTED_GROUPS_CAPTURE.json',protection)]:
  path=ROOT/'raw_evidence'/n;path.rename(path.with_name('ARCHIVAL_CP7_'+n));save(path,data)
 save(ROOT/'ACTUAL_FULL_SCOPE_ADMISSION.json',dict(schema='serial_timer_full156_actual_four_scope_admission_v1',passed=True,checks=checks,new_scope_admission_groups=4,new_test_controls_executed=0,generic15_reused_not_rerun=True,old_worker20_pipeline30_intake156_native107_not_rerun=True,qualifying_audit_sha256=sha(ROOT/'QUALIFYING_CP7_AUDIT.json'),model_calls=0,eda_calls=0,new_fifo=False))
 stable=('kit','model','model_pid','solve_deadline_s','judge_timeout_s','judge_supervisor_timeout_s','max_worker_requests_per_arm','retries','python_major_minor','dependency_hashes','minimum_disk_free_bytes')
 spec={k:cp[k] for k in stable};spec.update(schema='serial_timer_synthesis_full156_frozen_v1',identity=ROOT.name,cloud_root=str(ROOT),base_commit='9c0d896a3624793029c62d06cd66fcd671e590db',dependencies_cloud=str(ROOT/'dependencies'),**selected,arms=['C','P'],samples_per_arm_per_task=1,max_actual_model_requests=624,stage_timeout_s=43200,guard_timeout_s=43600,slot_minutes=740,first_generation_replayed=False,original_phase_baseline_spec_sha256=factor_proof.ORIGINAL_SPEC_SHA,source_factor_proof_sha256=sha(ROOT/'SOURCE_FACTOR_PROOF.json'),qualifying_cp7_audit_sha256=sha(ROOT/'QUALIFYING_CP7_AUDIT.json'),qualifying_cp7_archive_sha256=sha(terminal/'terminal_v1.zip'),environment_capture_sha256=sha(ROOT/'raw_evidence/ENVIRONMENT_CAPTURE.json'),protected_groups_capture_sha256=sha(ROOT/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json'),external_inventory_manifest_sha256=sha(ROOT/'EXTERNAL_SOURCE_MANIFEST.json'),compiler_tools=environment['tools'],compiler_env=environment['compiler_env'],udev_files=environment['udev_files'],protected=captured['protected'],model_identity=captured['model_identity'],protected_group_count=len(protection['groups']),protected_source_assets=protection['source_assets'],frozen_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),qualification='Original107 finite native and108 original known7 qualification; unchanged task-blind serial timer producer/worker/fallback, original intake and generic15 controls reused;4 actual new full-scope/source/current-inventory admission groups.',acceptance='All156/312 original judge rows, P>=120 fully correct and weighted>=.80; historical113 allL3, paired grades nondecreasing; P total requests<=C and every historical-correct/unchanged-grade task P requests<=C, no deadline/unconfirmed/tool/source failure; original terminal archive audit required.',limits=['One fresh same-factor all156 development C/P run; no redraw/stored answer/five/independent/hidden/adoption/deployment.','Single serial timer factor with common original phase-P model fallback; no taskID production dispatch or waveform/FSM/vector/table/onehot composition.','8192/max2/repair1/complete worker300/judge300/super360 including x-z unchanged.','Finite107 binary pattern/shift/event/reset three-output qualification and one actual known151 instance are not internal-next/xz/all-parameter proof.','Stage43200/guard43600/slot740min are safety caps, not ETA.','Original score gains are not added; target120/.80/history/cost gates all mandatory.'])
 excluded={'RUN_SPEC.json','SOURCE_MANIFEST.json','PREPARATION_RECEIPT.json'}
 spec['source_hashes']={p.relative_to(ROOT).as_posix():sha(p) for p in sorted(ROOT.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.relative_to(ROOT).as_posix() not in excluded and not p.relative_to(ROOT).as_posix().startswith(('raw_evidence/ACTUAL_PREPARE/','results/','guard/'))}
 save(ROOT/'RUN_SPEC.json',spec)
 assert pilot.frozen(kit)==spec and factor_proof.verify(ROOT,require_native=True)==factor and protected_sources.check(protection)==checked
 assert captured['dependencies_cloud']==spec['dependencies_cloud'] and captured['dependency_hashes']==spec['dependency_hashes']
 receipt=dict(schema='serial_timer_full156_actual_fresh_preparation_v1',passed=True,spec_sha256=sha(ROOT/'RUN_SPEC.json'),source_assets=len(spec['source_hashes']),tasks=156,outputs=312,max_requests=624,historical_guard_tasks=113,emitted=1,abstentions=155,actual_new_scope_admission_groups=4,new_test_controls_executed=0,generic15_reused_not_rerun=True,old_controls_intake_native_audits_not_rerun=True,strict_dependency_path_and_hash_map_equal=True,protected_group_count=126,protected_source_assets=8064,model_calls=0,eda_calls=0,new_fifo=False,score_measured=False,adoption=False)
 save(ROOT/'PREPARATION_RECEIPT.json',receipt);print(json.dumps(receipt))
if __name__=='__main__':main()
