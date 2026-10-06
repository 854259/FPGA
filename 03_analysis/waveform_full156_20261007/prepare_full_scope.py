"""Fresh AMD full156 freeze; original104 and new scope controls are reused."""
import datetime,hashlib,json,os,shutil,sys,time,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
read=lambda p:json.loads(Path(p).read_bytes())
def save(path,j):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 with path.open('x',encoding='utf-8') as f:json.dump(j,f,ensure_ascii=False,indent=2);f.write('\n')
def main():
 assert sys.platform=='linux' and sys.version_info[:2]==(3,12) and sys.dont_write_bytecode
 assert str(ROOT)=='/workspace/team/runs/fpga_owner/waveform_first_request_full156_20261007_v1' and not (ROOT/'RUN_SPEC.json').exists()
 controls=Path('/workspace/team/runs/fpga_owner/waveform_full156_scope_pure_20261007_v1')
 assert sha(controls/'ACTUAL_SCOPE_RECEIPT.json')=='77d42fecd65f12c99cea04b96f06c4e296fcf825173d568646bd7ff6a8d51abf'
 assert sha(controls/'SCOPE_EVIDENCE.zip')=='1e8a73ff3a4fe8a22a5bf03d0c78d60f10b2f4144253d13a3cb15e490b1f208d'
 m=read(controls/'SOURCE_MANIFEST.json');r=read(controls/'ACTUAL_SCOPE_RECEIPT.json');assert len(m)==105 and r['source_manifest']==m
 assert r['passed'] and r['controls']==7 and not r['new_spec_exists'] and r['new_model_calls']==r['new_eda_calls']==0
 process=r['actual_owned_process'];assert process['returncode']==0 and process['exec_confirmed'] and process['normal_completion'] and process['leader_reaped'] and not process['remaining_group'] and not process['timeout']
 assert sha(controls/'processes/scope/stdout.bin')==process['stdout_sha256']==r['stdout_sha256']
 for n,h in m.items():assert sha(controls/n)==sha(ROOT/n)==h,n
 parent=Path('/workspace/team/runs/fpga_teammate/waveform_first_request_cp6_20261006_v4')
 assert sha(parent/'RUN_SPEC.json')==sha(ROOT/'QUALIFYING_CP6_SPEC.json')=='216637107d75156c6ad4c1db13656e6ea94f7fce225a8df9da03b7b2f6db25cb'
 cp=read(ROOT/'QUALIFYING_CP6_SPEC.json');kit=Path(cp['kit']);os.environ.update(cp['compiler_env'])
 os.environ.update(RTL_MAX_TOKENS='8192',RTL_REPAIRS='1',RTL_TEMPERATURE='0',MODEL_NAME=cp['model'],LLM_BASE_URL='http://127.0.0.1:8000/v1')
 import factor_proof,metrics,pilot,preparation_inputs,protected_sources,guard_wrapper
 proof=factor_proof.verify(ROOT);assert proof==read(ROOT/'SOURCE_FACTOR_PROOF.json')
 terminal=Path('/workspace/team/runs/fpga_teammate/waveform104_terminal_review_20261006_v1')
 assert sha(terminal/'audit/RESULTS.json')==sha(ROOT/'QUALIFYING_CP6_AUDIT.json')=='b46456f68f8383f23c7bea3c192d2b797d82921fb4339c4d90f3adcd7af0405a'
 qualifying=read(ROOT/'QUALIFYING_CP6_AUDIT.json')
 assert qualifying['evidence_valid'] and qualifying['qualified_for_new_full_regression'] and qualifying['audited_generation_provenance_bound'] and qualifying['expected_samples']==12 and qualifying['actual_model_requests']==18
 assert qualifying['guard_pass'] and qualifying['regressions']==[] and qualifying['unchanged_task_request_cost'] and qualifying['historically_correct_request_cost'] and not qualifying['unconfirmed_attempts'] and not qualifying['solve_deadlines']
 assert sha(terminal/'COMPLETE.json')==sha(ROOT/'QUALIFYING_CP6_TERMINAL.json')=='e6b605fd5a17f2986f60484bb68f77ff0c008d7171d165e34a55e980c38f599e'
 assert read(terminal/'COMPLETE.json')['passed']
 for n,h in cp['source_hashes'].items():assert sha(parent/n)==h,n
 for n,h in read(ROOT/'DRAFT_SOURCE_SCOPE_PROOF.json')['immutable_production'].items():assert sha(ROOT/n)==cp['source_hashes'][n]==h,n
 assert sha(ROOT/'PRODUCTION_ADMISSION.json')==cp['source_hashes']['PRODUCTION_ADMISSION.json']
 admission=read(ROOT/'PRODUCTION_ADMISSION.json');assert admission['status_counts']==dict(supported=1,abstain=11,skip=144)
 selected=preparation_inputs.validate_kit(ROOT,kit);assert selected['task_ids']==metrics.TASKS and selected['guard_tasks']==metrics.GUARDS and selected['advice_tasks']==metrics.ADVICE_TASKS
 assert len(selected['task_ids'])==156 and len(selected['guard_tasks'])==113 and selected['expected_samples']==312
 inputs=read(ROOT/'INPUT_MANIFEST.json')
 for n,h in inputs['input_sha256'].items():assert sha(kit/'bench/tasks_veval'/n)==h,n
 for n,h in inputs['official_sha256'].items():assert sha(kit/'official_reference'/n)==h,n
 protection=read(ROOT/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json');groups=protection['groups']
 assert len(groups)==96 and protection['source_assets']==6533
 with zipfile.ZipFile(controls/'SCOPE_EVIDENCE.zip') as z:
  archive_manifest=json.loads(z.read('ARCHIVE_MANIFEST.json'));assert len(z.namelist())==115
  for n,h in archive_manifest['files'].items():assert hashlib.sha256(z.read(n)).hexdigest()==sha(controls/n)==h,n
 sources=dict(archive_manifest['files']);sources['SCOPE_EVIDENCE.zip']=sha(controls/'SCOPE_EVIDENCE.zip')
 groups['waveform_full156_scope_controls_v1']=dict(cloud_root=str(controls),spec_name='SOURCE_MANIFEST.json',spec_sha256=sha(controls/'SOURCE_MANIFEST.json'),source_hashes=sources)
 protection['source_assets']=sum(len(g['source_hashes']) for g in groups.values())
 checked=protected_sources.check(protection)
 environment=pilot.validate_environment();assert environment['tools']==cp['compiler_tools'] and environment['compiler_env']==cp['compiler_env'] and environment['udev_files']==cp['udev_files']
 for n,h in cp['dependency_hashes'].items():assert sha(ROOT/'dependencies'/n)==h
 captured=read(ROOT/'raw_evidence/ENVIRONMENT_CAPTURE.json')
 fresh_protected=guard_wrapper.protected(kit);fresh_model=guard_wrapper.identity(cp['model_pid'])
 assert fresh_protected==captured['protected'] and fresh_model==cp['model_identity']==captured['model_identity']
 captured.update(schema='actual_waveform_full156_fresh_environment_capture_v1',observed_at_epoch=time.time(),dependencies_cloud=str(ROOT/'dependencies'),dependency_hashes=cp['dependency_hashes'],compiler_tools=environment['tools'],compiler_env=environment['compiler_env'],udev_files=environment['udev_files'],protected=fresh_protected,model_identity=fresh_model,disk_free_bytes=shutil.disk_usage(ROOT).free,task_submitted=False)
 assert sha('/usr/bin/python3')=='8295ee25cfdb239f3e165afceda7f46de73e2b606ff0e2e3d8623e3facd30acc'
 for name,j in [('ENVIRONMENT_CAPTURE.json',captured),('PROTECTED_GROUPS_CAPTURE.json',protection)]:
  path=ROOT/'raw_evidence'/name;path.rename(path.with_name('ARCHIVAL_CP6_'+name));save(path,j)
 save(ROOT/'ACTUAL_FULL_SCOPE_BINDING.json',dict(schema='waveform_full156_actual_scope_control_reuse_v1',controls_reused=7,receipt_sha256=sha(controls/'ACTUAL_SCOPE_RECEIPT.json'),source_manifest_sha256=sha(controls/'SOURCE_MANIFEST.json'),archive_sha256=sha(controls/'SCOPE_EVIDENCE.zip'),same_exact_production_and_binding_functions=True,new_tests_in_preparation=0,original104_rerun=False,original156_prompt_only_intake_rerun=False,model_calls=0,eda_calls=0,new_fifo=False))
 stable=('kit','model','model_pid','solve_deadline_s','judge_timeout_s','judge_supervisor_timeout_s','max_worker_requests_per_arm','retries','python_major_minor','dependency_hashes','minimum_disk_free_bytes','facts_revision','facts_sha256','resource_fix_source_commit')
 spec={k:cp[k] for k in stable}
 spec.update(schema='waveform_first_request_full156_frozen_v1',identity=ROOT.name,cloud_root=str(ROOT),base_commit='2ae22034aab37007aaf05c7c784d38e5bf588ec3',dependencies_cloud=str(ROOT/'dependencies'),**selected,arms=['C','P'],samples_per_arm_per_task=1,max_actual_model_requests=624,stage_timeout_s=43200,guard_timeout_s=43600,slot_minutes=740,first_generation_replayed=False,
  original_phase_baseline_spec_sha256=cp['original_phase_baseline_spec_sha256'],source_factor_proof_sha256=sha(ROOT/'SOURCE_FACTOR_PROOF.json'),qualifying_cp6_audit_sha256=sha(ROOT/'QUALIFYING_CP6_AUDIT.json'),environment_capture_sha256=sha(ROOT/'raw_evidence/ENVIRONMENT_CAPTURE.json'),protected_groups_capture_sha256=sha(ROOT/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json'),external_inventory_manifest_sha256=sha(ROOT/'EXTERNAL_SOURCE_MANIFEST.json'),
  compiler_tools=environment['tools'],compiler_env=environment['compiler_env'],udev_files=environment['udev_files'],protected=captured['protected'],model_identity=captured['model_identity'],protected_group_count=len(groups),protected_source_assets=protection['source_assets'],frozen_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
  qualification='Original104 corrected terminal qualification and immutable production plus7 new AMD full scope controls; exact original156 prompt-only intake reused.',
  acceptance='All156/312 original judge rows; P>=120L3 and weighted>=.80; historical113 allL3, all paired grades nondecreasing, P total and unchanged-grade and historical-correct task requests<=C; no deadline/unconfirmed/source/tool failure; complete original archive audit required.',
  limits=['Single-factor waveform same-budget development regression; no redraw, independent/hidden/five/adoption/deployment claim.','Only original supported first-request observations; common phase-P runtime/skills/repair/native/judge including x-z and8192/max2/repair1/absolute300s unchanged.','No onehot/FSM/vector/table factor composition or taskID-specific production rule; original prompt only determines advice.','Stage43200/guard43600/slot740min are safety ceilings, not ETA.','New capture and final dependency paths AND hashes must exactly agree; no relocation weakening.','Original6-task screen and all156 are known development exposure; scores are never added across candidates.'])
 excluded={'RUN_SPEC.json','SOURCE_MANIFEST.json','PREPARATION_RECEIPT.json'}
 spec['source_hashes']={p.relative_to(ROOT).as_posix():sha(p) for p in sorted(ROOT.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.relative_to(ROOT).as_posix() not in excluded and not p.relative_to(ROOT).as_posix().startswith(('raw_evidence/ACTUAL_PREPARE/','results/','guard/'))}
 save(ROOT/'RUN_SPEC.json',spec)
 assert captured['dependencies_cloud']==spec['dependencies_cloud'] and captured['dependency_hashes']==spec['dependency_hashes']
 assert pilot.frozen(kit)==spec and protected_sources.check(protection)==checked and factor_proof.verify(ROOT)==proof
 receipt=dict(schema='waveform_full156_actual_preparation_v1',passed=True,spec_sha256=sha(ROOT/'RUN_SPEC.json'),source_assets=len(spec['source_hashes']),actual_scope_controls_reused=7,new_tests_in_preparation=0,qualifying104_audit_sha256=sha(ROOT/'QUALIFYING_CP6_AUDIT.json'),tasks=156,outputs=312,max_requests=624,historical_guards=113,advice_task_count=1,original156_admission_reused=True,dependency_path_and_hash_map_exact=True,protected_group_count=len(groups),protected_source_assets=protection['source_assets'],model_calls=0,eda_calls=0,new_fifo=False,new_score=False)
 save(ROOT/'PREPARATION_RECEIPT.json',receipt);print(json.dumps(receipt))
if __name__=='__main__':main()
