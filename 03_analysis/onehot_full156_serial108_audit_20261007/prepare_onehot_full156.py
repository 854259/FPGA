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
 assert str(ROOT)=='/workspace/team/runs/fpga_owner/onehot_synthesis_full156_20261007_v1' and not (ROOT/'RUN_SPEC.json').exists()
 parent=Path('/workspace/team/runs/fpga_owner/onehot_synthesis_cp7_20261007_v1');terminal=Path(str(parent)+'_terminal_review_v1')
 assert sha(parent/'RUN_SPEC.json')==sha(ROOT/'QUALIFYING_CP7_SPEC.json')=='d4cc6b511450e4cbc19e95105f2479d11c5bdd7166c6782043b9da7decda70d2'
 cp=read(parent/'RUN_SPEC.json');assert len(cp['source_hashes'])==126
 for n,h in cp['source_hashes'].items():assert sha(parent/n)==h
 os.environ.update(cp['compiler_env']);os.environ.update(RTL_MAX_TOKENS='8192',RTL_REPAIRS='1',RTL_TEMPERATURE='0',MODEL_NAME=cp['model'],LLM_BASE_URL='http://127.0.0.1:8000/v1')
 import factor_proof,metrics,pilot,preparation_inputs,protected_sources,guard_wrapper
 checks=[]
 # Actual original serialized audit bytes, not reserialized derivative metadata.
 assert sha(terminal/'audit/RESULTS.json')=='5071f22193cc25d78c31c4545178e2d794087f96f9834a933c965625b63a71a0'
 assert sha(terminal/'terminal_v1.zip')=='3cc31207ae275e295d075209c3cb23827d1b93cd17ff2a0b1948698be73792d7'
 qualifying=read(terminal/'audit/RESULTS.json');assert qualifying['evidence_valid'] and qualifying['qualified_for_new_full_regression'] and qualifying['guard_pass'] and qualifying['unchanged_task_request_cost'] and qualifying['regressions']==[] and qualifying['unconfirmed_attempts']==0 and not qualifying['adoption']
 shutil.copyfile(terminal/'audit/RESULTS.json',ROOT/'QUALIFYING_CP7_AUDIT.json');assert sha(ROOT/'QUALIFYING_CP7_AUDIT.json')==sha(terminal/'audit/RESULTS.json')
 factor=factor_proof.verify(ROOT);assert factor==read(ROOT/'SOURCE_FACTOR_PROOF.json')==factor_proof.verify(parent)
 adaptation=read(ROOT/'FULL_SOURCE_ADAPTATION_PROOF.json')
 for n,h in adaptation['unchanged_production_sources'].items():assert sha(ROOT/n)==sha(parent/n)==h
 checks.append('original106 qualifier and exact unchanged single-factor production bound')
 # All input bytes and old admission retained; no new156 producer scan.
 assert sha(ROOT/'PRODUCTION_ADMISSION.json')==cp['source_hashes']['PRODUCTION_ADMISSION.json']
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
 fullfsm=Path('/workspace/team/runs/fpga_owner/fsm_synthesis_full156_20261006_v2');fsm=read(fullfsm/'RUN_SPEC.json')
 for n,b in adaptation['generic_gate_route_bijection'].items():
  assert sha(fullfsm/n)==fsm['source_hashes'][n]==b['parent_sha256'] and sha(ROOT/n)==b['current_sha256']
  assert (ROOT/n).read_bytes()==(fullfsm/n).read_bytes().replace(b'mechanical_fsm',b'mechanical_onehot')
 generic=Path('/workspace/team/runs/fpga_owner/vector_full156_controls_20261006_v1')
 assert sha(generic/'ACTUAL_CONTROLS_RECEIPT.json')=='e4ad4ecc67316d4bf19f3fe49209caaf9c5ab87f03b0b5f3aa758261174c2adf'
 gr=read(generic/'ACTUAL_CONTROLS_RECEIPT.json');assert gr['passed'] and gr['actual_controls']==15
 for n in ('generation_binding','solver_measurement'):assert function_bytes(ROOT/'pilot.py',n)==function_bytes(parent/'pilot.py',n)
 assert sha(ROOT/'upstream/official_eval_guarded.py')=='5d1911d8b730cbb460bf7ceb33cc602bf1f840402971e3dc1301f470fbd52a4c'
 checks.append('same original grade,provenance,complete300 solver measurement and historical/per-task/total cost gates retained')
 # Current immutable capture extends the original byte anchors; no replacement.
 monitor=Path('/workspace/team/runs/fpga_owner/terminal_success_summary_compatibility_20261007_v2/monitor')
 protection=read(monitor/'PROTECTED_GROUPS_CAPTURE.json');assert len(protection['groups'])==119 and protection['source_assets']==7670
 original_capture=read(ROOT/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json')
 assert all(protection['groups'].get(n)==g for n,g in original_capture['groups'].items())
 external=read(ROOT/'EXTERNAL_SOURCE_MANIFEST.json');assert external['unique_immutable_files']==6516
 def add(name,unit,spec_name,source_hashes):
  assert name not in protection['groups'];protection['groups'][name]=dict(cloud_root=str(unit),spec_name=spec_name,spec_sha256=sha(unit/spec_name),source_hashes=source_hashes)
 add('onehot106_qualifying_original_frozen',parent,'RUN_SPEC.json',cp['source_hashes'])
 for number in (1,2):
  unit=Path('/workspace/team/runs/fpga_owner/serial_timer_synthesis_cp7_20261007_v1_terminal_review_v'+str(number));sources=read(unit/'SOURCE_MANIFEST.json')
  for n in ('TERMINAL_REVIEW_RECEIPT.json','FAILURE_TRACEBACK.txt'):
   if (unit/n).is_file():sources[n]=sha(unit/n)
  add('serial108_terminal_v'+str(number)+'_sealed',unit,'SOURCE_MANIFEST.json',sources)
  mon=Path('/workspace/team/runs/fpga_owner/serial108_terminal_preparation_20261007_v'+str(number)+'/monitor');add('serial108_monitor_v'+str(number)+'_sealed',mon,'SOURCE_MANIFEST.json',read(mon/'SOURCE_MANIFEST.json'))
 serial=Path('/workspace/team/runs/fpga_owner/serial_timer_synthesis_cp7_20261007_v1');ss=read(serial/'RUN_SPEC.json');assert sha(serial/'RUN_SPEC.json')=='378c8706992c4da961dc4c237a4aad6b21bf48c4aefb13e51dfa4a8cf97ef117'
 add('serial108_original_frozen',serial,'RUN_SPEC.json',ss['source_hashes'])
 protection['source_assets']=sum(len(g['source_hashes']) for g in protection['groups'].values());checked=protected_sources.check(protection)
 assert len(protection['groups'])==125 and protection['source_assets']==7928
 checks.append('immutable95/6516 and current119/7670 retained; sealed original106/108 and failed/corrected terminal sources added')
 environment=pilot.validate_environment();assert environment['tools']==cp['compiler_tools'] and environment['compiler_env']==cp['compiler_env'] and environment['udev_files']==cp['udev_files']
 for n,h in cp['dependency_hashes'].items():assert sha(ROOT/'dependencies'/n)==h
 captured=read(ROOT/'raw_evidence/ENVIRONMENT_CAPTURE.json');fresh_protected=guard_wrapper.protected(kit);fresh_model=guard_wrapper.identity(cp['model_pid'])
 assert fresh_protected==cp['protected'] and fresh_model==cp['model_identity']
 captured.update(schema='actual_onehot_full156_fresh_environment_capture_v1',observed_at_epoch=time.time(),dependencies_cloud=str(ROOT/'dependencies'),dependency_hashes=cp['dependency_hashes'],compiler_tools=environment['tools'],compiler_env=environment['compiler_env'],udev_files=environment['udev_files'],protected=fresh_protected,model_identity=fresh_model,disk_free_bytes=shutil.disk_usage(ROOT).free,task_submitted=False)
 for n,data in [('ENVIRONMENT_CAPTURE.json',captured),('PROTECTED_GROUPS_CAPTURE.json',protection)]:
  path=ROOT/'raw_evidence'/n;path.rename(path.with_name('ARCHIVAL_CP7_'+n));save(path,data)
 save(ROOT/'ACTUAL_FULL_SCOPE_ADMISSION.json',dict(schema='onehot_full156_actual_four_scope_admission_v1',passed=True,checks=checks,new_scope_admission_groups=4,new_test_controls_executed=0,generic15_reused_not_rerun=True,old_worker17_pipeline28_intake156_native99_not_rerun=True,qualifying_audit_sha256=sha(ROOT/'QUALIFYING_CP7_AUDIT.json'),model_calls=0,eda_calls=0,new_fifo=False))
 stable=('kit','model','model_pid','solve_deadline_s','judge_timeout_s','judge_supervisor_timeout_s','max_worker_requests_per_arm','retries','python_major_minor','dependency_hashes','minimum_disk_free_bytes')
 spec={k:cp[k] for k in stable};spec.update(schema='onehot_synthesis_full156_frozen_v1',identity=ROOT.name,cloud_root=str(ROOT),base_commit='87ff602441e5dc61984a52599f79f190ef84d124',dependencies_cloud=str(ROOT/'dependencies'),**selected,arms=['C','P'],samples_per_arm_per_task=1,max_actual_model_requests=624,stage_timeout_s=43200,guard_timeout_s=43600,slot_minutes=740,first_generation_replayed=False,original_phase_baseline_spec_sha256=factor_proof.ORIGINAL_SPEC_SHA,source_factor_proof_sha256=sha(ROOT/'SOURCE_FACTOR_PROOF.json'),qualifying_cp7_audit_sha256=sha(ROOT/'QUALIFYING_CP7_AUDIT.json'),qualifying_cp7_archive_sha256=sha(terminal/'terminal_v1.zip'),environment_capture_sha256=sha(ROOT/'raw_evidence/ENVIRONMENT_CAPTURE.json'),protected_groups_capture_sha256=sha(ROOT/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json'),external_inventory_manifest_sha256=sha(ROOT/'EXTERNAL_SOURCE_MANIFEST.json'),compiler_tools=environment['tools'],compiler_env=environment['compiler_env'],udev_files=environment['udev_files'],protected=captured['protected'],model_identity=captured['model_identity'],protected_group_count=len(protection['groups']),protected_source_assets=protection['source_assets'],frozen_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),qualification='Original99 finite native and106 original known7 qualification; unchanged task-blind onehot producer/worker/fallback, original intake and generic15 controls reused;4 actual new full-scope/source/current-inventory admission groups.',acceptance='All156/312 original judge rows, P>=120 fully correct and weighted>=.80; historical113 allL3, paired grades nondecreasing; P total requests<=C and every historical-correct/unchanged-grade task P requests<=C, no deadline/unconfirmed/tool/source failure; original terminal archive audit required.',limits=['One fresh same-factor all156 development C/P run; no redraw/stored answer/five/independent/hidden/adoption/deployment.','Single onehot graph factor with common original phase-P model fallback; no taskID production dispatch or waveform/FSM/vector/table/serial composition.','8192/max2/repair1/complete worker300/judge300/super360 including x-z unchanged.','Finite native widths2..5 and one actual known width10 instance are not all-parameter proof.','Stage43200/guard43600/slot740min are safety caps, not ETA.','Original score gains are not added; target120/.80/history/cost gates all mandatory.'])
 excluded={'RUN_SPEC.json','SOURCE_MANIFEST.json','PREPARATION_RECEIPT.json'}
 spec['source_hashes']={p.relative_to(ROOT).as_posix():sha(p) for p in sorted(ROOT.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.relative_to(ROOT).as_posix() not in excluded and not p.relative_to(ROOT).as_posix().startswith(('raw_evidence/ACTUAL_PREPARE/','results/','guard/'))}
 save(ROOT/'RUN_SPEC.json',spec)
 assert pilot.frozen(kit)==spec and factor_proof.verify(ROOT)==factor and protected_sources.check(protection)==checked
 assert captured['dependencies_cloud']==spec['dependencies_cloud'] and captured['dependency_hashes']==spec['dependency_hashes']
 receipt=dict(schema='onehot_full156_actual_fresh_preparation_v1',passed=True,spec_sha256=sha(ROOT/'RUN_SPEC.json'),source_assets=len(spec['source_hashes']),tasks=156,outputs=312,max_requests=624,historical_guard_tasks=113,emitted=1,abstentions=155,actual_new_scope_admission_groups=4,new_test_controls_executed=0,generic15_reused_not_rerun=True,old_controls_intake_native_audits_not_rerun=True,strict_dependency_path_and_hash_map_equal=True,protected_group_count=125,protected_source_assets=7928,model_calls=0,eda_calls=0,new_fifo=False,score_measured=False,adoption=False)
 save(ROOT/'PREPARATION_RECEIPT.json',receipt);print(json.dumps(receipt))
if __name__=='__main__':main()
