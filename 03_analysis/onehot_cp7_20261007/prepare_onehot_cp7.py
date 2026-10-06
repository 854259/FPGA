"""AMD-only fresh onehot CP7 freeze; no repeated intake or controls."""
import datetime,hashlib,json,os,shutil,sys,time,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
read=lambda p:json.loads(Path(p).read_bytes())
def save(p,j):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('x',encoding='utf-8') as f:json.dump(j,f,ensure_ascii=False,indent=2);f.write('\n')
def main():
 assert sys.platform=='linux' and sys.version_info[:2]==(3,12) and sys.dont_write_bytecode
 assert str(ROOT)=='/workspace/team/runs/fpga_owner/onehot_synthesis_cp7_20261007_v1' and not (ROOT/'RUN_SPEC.json').exists()
 controls=Path('/workspace/team/runs/fpga_owner/onehot_cp7_scope_pure_20261007_v1')
 assert sha(controls/'ACTUAL_SCOPE_RECEIPT.json')=='32866bd3e23b1f08ef47272e3def005e54b006bcdf0366c7466a9a94e61eccf7'
 assert sha(controls/'SCOPE_EVIDENCE.zip')=='dc1a474db17b4565066ca9a561be9988203c6c5264aad41dafeaf39a66062fe8'
 manifest=read(controls/'SOURCE_MANIFEST.json');receipt=read(controls/'ACTUAL_SCOPE_RECEIPT.json');assert len(manifest)==119 and receipt['source_manifest']==manifest
 assert receipt['passed'] and receipt['new_scope_controls']==1 and receipt['reused_pipeline_controls']==27 and receipt['model_calls']==receipt['eda_calls']==0
 process=receipt['actual_owned_process'];assert process['returncode']==0 and process['exec_confirmed'] and process['normal_completion'] and process['leader_reaped'] and not process['timeout'] and not process['remaining_group']
 assert sha(controls/'processes/current_scope/stdout.bin')==process['stdout_sha256']==receipt['stdout_sha256']
 for n,h in manifest.items():assert sha(controls/n)==sha(ROOT/n)==h,n
 old=Path('/workspace/team/runs/fpga_owner/onehot_cp_pipeline_pure_20261007_v4')
 proof=read(ROOT/'DYNAMIC_SCOPE_SOURCE_PROOF.json');assert sha(old/'ACTUAL_CHECKS_RECEIPT.json')==proof['parent_receipt_sha256']=='8ffdb184f68b6c482481fc46d80fb2a7ea66a1c75541c6a7e254054d4450b3d5'
 assert read(old/'ACTUAL_CHECKS_RECEIPT.json')['passed']
 for n,h in proof['unchanged_common_source_hashes'].items():assert sha(ROOT/n)==sha(old/n)==h,n
 wave=Path('/workspace/team/runs/fpga_owner/waveform_first_request_full156_20261007_v1')
 assert sha(wave/'RUN_SPEC.json')=='d3b4b69f85e358c749954c12509908172a74663a83c4739a57d0c26cec5f5c5e'
 base=read(wave/'RUN_SPEC.json');os.environ.update(base['compiler_env']);os.environ.update(RTL_MAX_TOKENS='8192',RTL_REPAIRS='1',RTL_TEMPERATURE='0',MODEL_NAME=base['model'],LLM_BASE_URL='http://127.0.0.1:8000/v1')
 import factor_proof,metrics,pilot,preparation_inputs,protected_sources,guard_wrapper
 new_proof=factor_proof.verify(ROOT)
 # These inherited FSM metadata bytes are archival; production never reads them.
 for n in ('SOURCE_FACTOR_PROOF.json','PRODUCTION_ADMISSION.json'):(ROOT/n).rename(ROOT/('ARCHIVAL_PARENT_'+n))
 save(ROOT/'SOURCE_FACTOR_PROOF.json',new_proof)
 intake=Path('/workspace/team/runs/fpga_owner/onehot_graph_pure_20261006_v1/original_full156_intake_v1')
 assert sha(intake/'INTAKE_RECEIPT.json')=='8ea1afdb4a334a6db42925d5a8bceeed8e95ac6a2e7623f2482080b6bebcd0d5'
 ir=read(intake/'INTAKE_RECEIPT.json');assert ir['passed'] and ir['complete'] and (ir['tasks'],ir['emitted'],ir['abstained'])==(156,1,155)
 assert ir['producer_sha256']==sha(ROOT/'synthesis.py')=='fc1af52cd3d76faf9eed812167eb8179ab40b3c3d32740062e6d444459701007'
 assert sha(intake/'PRIVATE_INTAKE_ROWS.json')==ir['private_rows_sha256']
 rows=read(intake/'PRIVATE_INTAKE_ROWS.json');assert len(rows)==156
 upstream=read(ROOT/'upstream/RUN_SPEC.json');inputs=read(ROOT/'INPUT_MANIFEST.json');kit=Path(base['kit'])
 assert [r['task'] for r in rows]==upstream['task_ids']
 admission={}
 for row in rows:
  task=row['task'];r=row['recipe'];assert r['prompt_sha256']==sha(kit/'bench/tasks_veval'/task/'prompt.txt')
  interface=kit/'bench/tasks_veval'/task/'interface.txt';assert row['interface_present']==interface.is_file()
  assert r['interface_sha256']==(sha(interface) if interface.is_file() else hashlib.sha256(b'').hexdigest())
  admission[task]={k:r.get(k) for k in ('emitted','prompt_sha256','interface_sha256','contract_sha256','rtl_sha256','reason')}
 emitted=sorted(t for t,r in admission.items() if r['emitted']);assert emitted==metrics.EMIT_TASKS and len(emitted)==1
 save(ROOT/'PRODUCTION_ADMISSION.json',dict(schema='onehot_cp7_original156_admission_exact_reuse_v1',tasks=admission,task_count=156,emitted=1,abstentions=155,original_receipt_sha256=sha(intake/'INTAKE_RECEIPT.json'),original_private_rows_sha256=ir['private_rows_sha256'],producer_sha256=ir['producer_sha256'],new_intake_calls=0,model_calls=0,eda_calls=0,not_quality_evidence=True))
 selected=preparation_inputs.validate_kit(ROOT,kit);assert selected['task_ids']==metrics.TASKS and selected['guard_tasks']==metrics.GUARDS and selected['target_tasks']==metrics.TARGETS and selected['expected_samples']==14
 for n,h in inputs['input_sha256'].items():assert sha(kit/'bench/tasks_veval'/n)==h,n
 for n,h in inputs['official_sha256'].items():assert sha(kit/'official_reference'/n)==h,n
 protection=read(ROOT/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json');assert len(protection['groups'])==98 and protection['source_assets']==6760
 with zipfile.ZipFile(controls/'SCOPE_EVIDENCE.zip') as z:
  archive_manifest=json.loads(z.read('ARCHIVE_MANIFEST.json'));assert len(z.namelist())==129
  for n,h in archive_manifest['files'].items():assert hashlib.sha256(z.read(n)).hexdigest()==sha(controls/n)==h,n
 sources=dict(archive_manifest['files']);sources['SCOPE_EVIDENCE.zip']=sha(controls/'SCOPE_EVIDENCE.zip')
 protection['groups']['onehot_cp7_current_scope_pure_v1']=dict(cloud_root=str(controls),spec_name='SOURCE_MANIFEST.json',spec_sha256=sha(controls/'SOURCE_MANIFEST.json'),source_hashes=sources)
 protection['source_assets']=sum(len(g['source_hashes']) for g in protection['groups'].values())
 assert len(protection['groups'])==99 and protection['source_assets']==6889
 checked=protected_sources.check(protection)
 environment=pilot.validate_environment();assert environment['tools']==base['compiler_tools'] and environment['compiler_env']==base['compiler_env'] and environment['udev_files']==base['udev_files']
 for n,h in base['dependency_hashes'].items():assert sha(ROOT/'dependencies'/n)==h,n
 captured=read(ROOT/'raw_evidence/ENVIRONMENT_CAPTURE.json');fresh_protected=guard_wrapper.protected(kit);fresh_model=guard_wrapper.identity(base['model_pid'])
 assert fresh_protected==captured['protected'] and fresh_model==captured['model_identity']==base['model_identity']
 captured.update(schema='actual_onehot_cp7_fresh_environment_capture_v1',observed_at_epoch=time.time(),dependencies_cloud=str(ROOT/'dependencies'),dependency_hashes=base['dependency_hashes'],compiler_tools=environment['tools'],compiler_env=environment['compiler_env'],udev_files=environment['udev_files'],protected=fresh_protected,model_identity=fresh_model,disk_free_bytes=shutil.disk_usage(ROOT).free,task_submitted=False)
 for n,j in [('ENVIRONMENT_CAPTURE.json',captured),('PROTECTED_GROUPS_CAPTURE.json',protection)]:
  f=ROOT/'raw_evidence'/n;f.rename(f.with_name('ARCHIVAL_PIPELINE_'+n));save(f,j)
 save(ROOT/'CURRENT_VALIDATION_REUSE_BINDING.json',dict(schema='onehot_cp7_actual_current_validation_reuse_v1',effective_pipeline_controls=28,new_scope_controls=1,reused_pipeline_controls=27,scope_receipt_sha256=sha(controls/'ACTUAL_SCOPE_RECEIPT.json'),scope_archive_sha256=sha(controls/'SCOPE_EVIDENCE.zip'),reused_worker_controls=17,reused_archive_gate=1,original_pipeline_receipt_sha256=proof['parent_receipt_sha256'],original17_worker_receipt_sha256='a9b7a2123eae7ce65bdf51906a27499b7e9b296128363becb0c1f1b07afbcab2',unchanged_production={'worker.py':sha(ROOT/'worker.py'),'synthesis.py':sha(ROOT/'synthesis.py'),'baseline_worker.py':sha(ROOT/'baseline_worker.py')},new_tests_in_preparation=0,new_intake_calls=0,model_calls=0,eda_calls=0,new_fifo=False,native_scope='Original99 positive widths2/3/4/5 only; natural target width10 unmeasured.'))
 stable=('kit','model','model_pid','solve_deadline_s','judge_timeout_s','judge_supervisor_timeout_s','max_worker_requests_per_arm','retries','python_major_minor','dependency_hashes','minimum_disk_free_bytes')
 spec={k:base[k] for k in stable}
 spec.update(schema='onehot_synthesis_cp7_frozen_v1',identity=ROOT.name,cloud_root=str(ROOT),base_commit='8bc19c216014382a4afa67dae5457939f130c499',dependencies_cloud=str(ROOT/'dependencies'),**selected,arms=['C','P'],samples_per_arm_per_task=1,max_actual_model_requests=28,stage_timeout_s=12000,guard_timeout_s=12400,slot_minutes=210,first_generation_replayed=False,original_phase_baseline_spec_sha256=factor_proof.ORIGINAL_SPEC_SHA,source_factor_proof_sha256=sha(ROOT/'SOURCE_FACTOR_PROOF.json'),environment_capture_sha256=sha(ROOT/'raw_evidence/ENVIRONMENT_CAPTURE.json'),protected_groups_capture_sha256=sha(ROOT/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json'),external_inventory_manifest_sha256=sha(ROOT/'EXTERNAL_SOURCE_MANIFEST.json'),compiler_tools=environment['tools'],compiler_env=environment['compiler_env'],udev_files=environment['udev_files'],protected=captured['protected'],model_identity=captured['model_identity'],protected_group_count=99,protected_source_assets=6889,frozen_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),qualification='Original99 finite native audit; unchanged producer/worker/fallback; effective28 pipeline plus17 worker plus1 archive gate with current1 new scope. Original156 intake reused.',acceptance='All14 original-judge rows and exact mechanical/model provenance; target newL3 and positive weighted net gain, all six guards bothL3, no paired grade regression, every fixed task P requests<=C and totalP<=C; no deadline/unconfirmed/source/tool failure. Original terminal archive audit required.',limits=['Known7 development C/P only; independent/hidden/formal-five qualification zero.','Native positive widths2/3/4/5 and natural target width10 remain distinct; no natural gain claimed in preparation.','Single onehot factor, common phase-P model fallback; no waveform/FSM/vector/table composition or taskID-specific production dispatch.','Original8192/max2/repair1/absolute complete worker300s/judge300/super360 retained including x-z.','Safety stage12000/guard12400/slot210min are not ETA; no redraw/requeue/adoption/deployment.','Immutable old95/6516 path+SHA inventory cannot be replaced; only fully bound sealed roots added, active105 progress excluded.','Final dependencies path AND hash mapping must match fresh capture exactly.'])
 excluded={'RUN_SPEC.json','SOURCE_MANIFEST.json','PREPARATION_RECEIPT.json'}
 spec['source_hashes']={p.relative_to(ROOT).as_posix():sha(p) for p in sorted(ROOT.rglob('*')) if p.is_file() and '__pycache__' not in p.parts and p.relative_to(ROOT).as_posix() not in excluded and not p.relative_to(ROOT).as_posix().startswith(('raw_evidence/ACTUAL_PREPARE/','results/','guard/'))}
 save(ROOT/'RUN_SPEC.json',spec)
 assert pilot.frozen(kit)==spec and factor_proof.verify(ROOT)==new_proof and protected_sources.check(protection)==checked
 assert captured['dependencies_cloud']==spec['dependencies_cloud'] and captured['dependency_hashes']==spec['dependency_hashes']
 receipt=dict(schema='onehot_cp7_actual_fresh_preparation_v1',passed=True,spec_sha256=sha(ROOT/'RUN_SPEC.json'),source_assets=len(spec['source_hashes']),tasks=7,outputs=14,max_requests=28,guard_tasks=6,effective_pipeline_controls=28,reused_worker_controls=17,reused_archive_gate=1,new_tests_in_preparation=0,original156_admission_reused=True,emitted=1,abstentions=155,strict_dependency_path_and_hash_map_equal=True,protected_group_count=99,protected_source_assets=6889,model_calls=0,eda_calls=0,new_fifo=False,new_score=False,adoption=False)
 save(ROOT/'PREPARATION_RECEIPT.json',receipt);print(json.dumps(receipt))
if __name__=='__main__':main()
