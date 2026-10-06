"""AMD-only fresh serial CP7 freeze from measured sources and original107."""
import datetime,hashlib,json,os,shutil,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
read=lambda p:json.loads(Path(p).read_bytes())
def save(p,j):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('x',encoding='utf-8') as f:json.dump(j,f,ensure_ascii=False,indent=2);f.write('\n')
def main():
 assert sys.platform=='linux' and sys.version_info[:2]==(3,12) and sys.dont_write_bytecode
 assert str(ROOT)=='/workspace/team/runs/fpga_owner/serial_timer_synthesis_cp7_20261007_v1' and not (ROOT/'RUN_SPEC.json').exists()
 old=Path('/workspace/team/runs/fpga_owner/serial_timer_cp_pipeline_pure_20261007_v1')
 assert sha(old/'ACTUAL_PURE_RECEIPT.json')=='a6785a284e4ef80752a5324337cea1a7a5b72188b0192c608c78083ce43eb304'
 assert sha(old/'PURE_EVIDENCE.zip')=='39a66b53ee16d5a62a8144af53321235e39dc96b88088c3ba88d0e0812a280c9'
 manifest=read(old/'SOURCE_MANIFEST.json');assert len(manifest)==86
 for n,h in manifest.items():assert sha(old/n)==sha(ROOT/n)==h,n
 label=Path('/workspace/team/runs/fpga_owner/serial_timer_activity_label_20261007_v1')
 assert sha(label/'pilot.py')=='4843a1a85ff5144d231169141e18ede7d1f63e15b1cda9b9cebe2f39cfdf1853'
 b=(label/'pilot.py').read_bytes();original=(ROOT/'pilot.py').read_bytes()
 for before,after in [('onehot-synthesis-stage:','serial-timer-synthesis-stage:'),('完整onehot图机械生成14输出阶段结束；确定性输出与实际模型调用分开统计；终态审计前不发布收益或全量资格，不部署。','完整串行计时器机械生成14输出阶段结束；确定性输出与实际模型调用分开统计；终态审计前不发布收益或全量资格，不部署。')]:
  assert b.count(after.encode())==1;b=b.replace(after.encode(),before.encode())
 assert b==original
 (ROOT/'pilot.py').rename(ROOT/'ARCHIVAL_PIPELINE_PILOT.py');shutil.copyfile(label/'pilot.py',ROOT/'pilot.py')
 wave=Path('/workspace/team/runs/fpga_owner/waveform_first_request_full156_20261007_v1')
 assert sha(wave/'RUN_SPEC.json')=='d3b4b69f85e358c749954c12509908172a74663a83c4739a57d0c26cec5f5c5e'
 base=read(wave/'RUN_SPEC.json');os.environ.update(base['compiler_env']);os.environ.update(RTL_MAX_TOKENS='8192',RTL_REPAIRS='1',RTL_TEMPERATURE='0',MODEL_NAME=base['model'],LLM_BASE_URL='http://127.0.0.1:8000/v1')
 for n,h in base['dependency_hashes'].items():
  source=Path(base['dependencies_cloud'])/n;assert sha(source)==h
  dest=ROOT/'dependencies'/n;dest.parent.mkdir(parents=True,exist_ok=True)
  if dest.exists():assert sha(dest)==h
  else:shutil.copyfile(source,dest)
 for n,source in [('guard_wrapper.py',ROOT/'upstream/guard_wrapper.py'),('protected_sources.py',ROOT/'dependencies/protected_sources.py'),('INPUT_MANIFEST.json',ROOT/'upstream/INPUT_MANIFEST.json')]:
  assert not (ROOT/n).exists();shutil.copyfile(source,ROOT/n)
 native=Path('/workspace/team/runs/fpga_owner/serial_timer_native_20261007_v2');terminal=Path(str(native)+'_terminal_review_v2')
 assert sha(native/'RUN_SPEC.json')=='141f5ecf638751d37f77c6c72aa61cf4cdef5cc3c2948657906a880c8eafa778'
 ns=read(native/'RUN_SPEC.json');assert len(ns['source_hashes'])==117
 for n,h in ns['source_hashes'].items():assert sha(native/n)==h
 assert sha(terminal/'ORIGINAL_AUDIT_RESULT.json')=='f57af8d7a6d2cb11abc051e757876679a8b7bc040787a52d296894cc2e84d8d7'
 assert sha(terminal/'terminal_native_v1.zip')=='6a471b2046c54281dc8e9c862cd3a4e41a75914161e1dc57e8908f531f07ff7d'
 shutil.copyfile(terminal/'ORIGINAL_AUDIT_RESULT.json',ROOT/'NATIVE_QUALIFICATION_AUDIT.json');shutil.copyfile(terminal/'terminal_native_v1.zip',ROOT/'NATIVE_EVIDENCE.zip')
 binding=read(ROOT/'NATIVE_ARCHIVE_BINDING.json');assert binding['every_member_bound_both_ends'] and binding['native_qualified']
 assert binding['archive_sha256']==sha(ROOT/'NATIVE_EVIDENCE.zip') and binding['audit_sha256']==sha(ROOT/'NATIVE_QUALIFICATION_AUDIT.json')
 import factor_proof,metrics,pilot,preparation_inputs,protected_sources,guard_wrapper
 factor=factor_proof.verify(ROOT,require_native=True);save(ROOT/'SOURCE_FACTOR_PROOF.json',factor)
 protection_path=ROOT/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json';protection_path.rename(protection_path.with_name('ARCHIVAL_PIPELINE_PROTECTED_GROUPS_CAPTURE.json'))
 current=Path('/workspace/team/runs/fpga_owner/terminal_success_summary_compatibility_20261007_v2/monitor/PROTECTED_GROUPS_CAPTURE.json');protection=read(current)
 anchor=read(ROOT/'raw_evidence/IMMUTABLE_ORIGINAL109_CAPTURE.json')
 assert sha(ROOT/'raw_evidence/IMMUTABLE_ORIGINAL109_CAPTURE.json')=='61972041751052691c9e42e0683a7d49e51abb9a956c8c32271ed711409091c3'
 assert len(anchor['groups'])==109 and anchor['source_assets']==7389 and all(protection['groups'].get(n)==g for n,g in anchor['groups'].items())
 assert len(protection['groups'])==119 and protection['source_assets']==7670
 save(protection_path,protection);checked=protected_sources.check(protection)
 kit=Path(base['kit']);selected=preparation_inputs.validate_kit(ROOT,kit)
 assert selected['task_ids']==metrics.TASKS and len(selected['task_ids'])==7 and len(selected['guard_tasks'])==6 and selected['expected_samples']==14
 environment=pilot.validate_environment();assert all(environment[k]==base[k] for k in ('compiler_env','compiler_tools','udev_files') if k in environment)
 assert environment['tools']==base['compiler_tools']
 protected=guard_wrapper.protected(kit);model=guard_wrapper.identity(base['model_pid']);assert model==base['model_identity']
 inputs=read(ROOT/'INPUT_MANIFEST.json');assert protected['tasks']==inputs['input_sha256'] and protected['official']==inputs['official_sha256']
 capture=dict(schema='serial_cp7_actual_fresh_environment_capture_v1',observed_at_epoch=time.time(),dependencies_cloud=str(ROOT/'dependencies'),dependency_hashes=base['dependency_hashes'],compiler_tools=environment['tools'],compiler_env=environment['compiler_env'],udev_files=environment['udev_files'],protected=protected,model_identity=model,disk_free_bytes=shutil.disk_usage(ROOT).free,task_submitted=False)
 save(ROOT/'raw_evidence/ENVIRONMENT_CAPTURE.json',capture)
 reuse=dict(schema='serial_cp7_source_native_and_pipeline_reuse_v1',old_pipeline_sources=86,pipeline_controls_reused_without_execution=30,worker_controls_reused_without_execution=20,native_original107_audit_bound=True,native_controls=12,native_commands=36,native_observations=13800,native_archive_members=509,native_archive_sha256=binding['archive_sha256'],pipeline_receipt_sha256=sha(old/'ACTUAL_PURE_RECEIPT.json'),pipeline_archive_sha256=sha(old/'PURE_EVIDENCE.zip'),label_only_reverse_delta_exact=True,pilot_sha256=sha(ROOT/'pilot.py'),production_sources={n:sha(ROOT/n) for n in ('worker.py','synthesis.py','baseline_worker.py','factor_proof.py','metrics.py','audit.py')},new_tests=0,new_model_calls=0,new_eda_calls=0,new_fifo=False,natural_score=False,adoption=False)
 save(ROOT/'CURRENT_VALIDATION_REUSE_BINDING.json',reuse)
 stable=('kit','model','model_pid','solve_deadline_s','judge_timeout_s','judge_supervisor_timeout_s','max_worker_requests_per_arm','retries','python_major_minor','dependency_hashes','minimum_disk_free_bytes')
 spec={k:base[k] for k in stable}
 spec.update(schema='serial_timer_synthesis_cp7_frozen_v1',identity=ROOT.name,cloud_root=str(ROOT),base_commit='81c073379d2e436ca17b634ee63e225437830e8c',dependencies_cloud=str(ROOT/'dependencies'),**selected,arms=['C','P'],samples_per_arm_per_task=1,max_actual_model_requests=28,stage_timeout_s=12000,guard_timeout_s=12400,slot_minutes=210,first_generation_replayed=False,original_phase_baseline_spec_sha256=factor_proof.ORIGINAL_SPEC_SHA,source_factor_proof_sha256=sha(ROOT/'SOURCE_FACTOR_PROOF.json'),environment_capture_sha256=sha(ROOT/'raw_evidence/ENVIRONMENT_CAPTURE.json'),protected_groups_capture_sha256=sha(protection_path),external_inventory_manifest_sha256=sha(ROOT/'EXTERNAL_SOURCE_MANIFEST.json'),compiler_tools=environment['tools'],compiler_env=environment['compiler_env'],udev_files=environment['udev_files'],protected=protected,model_identity=model,protected_group_count=119,protected_source_assets=7670,frozen_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),qualification='Original107 finite binary-event native audit and509-member complete dual archive; exact worker20/pipeline30 evidence reused; two activity labels reversed byte-exactly; no original controls rerun',acceptance='All14 original-judge rows and generation provenance; target newL3 and weighted net gain; six guards bothL3; no paired grade decline; every fixed task P requests<=C and totalP<=C; no deadline/unconfirmed/tool/source failure. Original terminal archive audit required.',limits=['Known fixed7 development C/P, no independent/hidden/formal-five/adoption.','Finite binary three-output native qualification only; internal-next placeholder and x/z not qualified.','Single task-blind serial-timer synthesis factor; common original phase-P fallback, no other-factor composition or taskID production dispatch.','Original8192/max2/repair1/complete worker300/judge300/super360 including x-z unchanged.','Safety stage12000/guard12400/slot210min are not ETA; whole-task FIFO, no redraw.','Original109/7389 inventory anchor unchanged and contained in119/7670 exact current capture.'])
 excluded={'RUN_SPEC.json','SOURCE_MANIFEST.json','PREPARATION_RECEIPT.json'}
 spec['source_hashes']={f.relative_to(ROOT).as_posix():sha(f) for f in sorted(ROOT.rglob('*')) if f.is_file() and '__pycache__' not in f.parts and f.relative_to(ROOT).as_posix() not in excluded and not f.relative_to(ROOT).as_posix().startswith(('raw_evidence/ACTUAL_PREPARE/','results/','guard/'))}
 save(ROOT/'RUN_SPEC.json',spec)
 assert pilot.frozen(kit)==spec and factor_proof.verify(ROOT,require_native=True)==factor and protected_sources.check(protection)==checked
 receipt=dict(schema='serial_cp7_actual_fresh_preparation_v1',passed=True,spec_sha256=sha(ROOT/'RUN_SPEC.json'),source_assets=len(spec['source_hashes']),tasks=7,outputs=14,max_requests=28,guard_tasks=6,pipeline_controls_reused=30,worker_controls_reused=20,new_tests=0,native_original_audit_bound=True,native_archive_members=509,pilot_sha256=sha(ROOT/'pilot.py'),strict_dependency_path_and_hash_map_equal=True,protected_group_count=119,protected_source_assets=7670,model_calls=0,eda_calls=0,new_fifo=False,natural_score=False,adoption=False)
 save(ROOT/'PREPARATION_RECEIPT.json',receipt);print(json.dumps(receipt))
if __name__=='__main__':main()
