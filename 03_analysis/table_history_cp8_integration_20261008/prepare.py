"""AMD-only fixed-seven serial-frame composition comparison; original budget, no inference."""
import argparse,datetime,hashlib,importlib.util,json,os,shutil,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
read=lambda p:json.loads(Path(p).read_bytes())

def save(p,j):
 with Path(p).open('xb') as f:f.write((json.dumps(j,ensure_ascii=False,indent=2)+'\n').encode())

def load(n,p):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def main():
 assert sys.platform=='linux' and sys.dont_write_bytecode and sys.version_info[:2]==(3,12)
 assert not any((ROOT/n).exists() for n in ['RUN_SPEC.json','PREPARATION_RECEIPT.json','results','guard'])
 seed=read(ROOT/'PREPARATION_INPUTS.json');kit=Path(seed['kit'])
 assert seed['schema']=='table_history_cp8_score7_freeze_inputs_v1' and seed['cloud_root']==str(ROOT)
 manifest=read(ROOT/'SOURCE_MANIFEST.json');assert sha(ROOT/'SOURCE_MANIFEST.json')==seed['source_manifest_sha256']
 for n,h in manifest.items():assert sha(ROOT/n)==h,n
 for n,h in seed['qualification_receipts'].items():assert sha(n)==h,n
 for n,h in seed['qualification_sources'].items():assert sha(ROOT/n)==h,n
 groups=read(ROOT/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json')
 assert sha(ROOT/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json')=='8f88ffbb61504a29336f9c235ba907c50c40d8924acde980ff1f7d3675b43686'
 protect=load('history_cp8_7_prepare_protection',ROOT/'protected_sources.py');before=protect.check(groups)
 assert before['verified'] and len(groups['groups'])==141
 for n,h in seed['additional_protected_sources'].items():assert sha(n)==h
 guard=load('history_cp8_7_prepare_original_guard',ROOT/'guard_wrapper.py');identity=guard.identity(2013333)
 assert identity==dict(pid=2013333,starttime='823869819',exe='llama-server',command_sha256='2ef1233963df0e5cc660fc2bed2baa2fca4e30b84d450e79bc9f77381cbd24e1')
 env=dict(PATH='/workspace/AMD/2026.1/Vivado/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',VIVADO_BIN='/workspace/AMD/2026.1/Vivado/bin',LD_LIBRARY_PATH='/workspace/team/udev-stub');os.environ.update(env)
 environment=load('history_cp8_7_prepare_original_environment',ROOT/'original_environment.py').validate_environment()
 inputs=read(ROOT/'INPUT_MANIFEST.json');protected=guard.protected(kit)
 assert protected['tasks']==inputs['input_sha256'] and protected['official']==inputs['official_sha256']
 original=read(ROOT/'upstream/RUN_SPEC.json');assert sha(ROOT/'upstream/RUN_SPEC.json')=='3fb1531c14b011f80ff58de559e326a4904d3fbdbcf3cdce7d6c955285860ba1'
 for n,h in original['source_hashes'].items():assert sha(ROOT/'upstream'/n)==h
 originalworker=(ROOT/'upstream/worker.py').read_bytes();common=(ROOT/'baseline_worker.py').read_bytes()
 old=b"candidate=args.arm == 'P'";assert originalworker.count(old)==1
 assert originalworker.replace(old,b'candidate=True')==common
 for n in ['package/agent/map_runtime.py','package/baseline.py']:
  assert (ROOT/n).read_bytes()==(ROOT/'upstream'/n).read_bytes()
 import source_admission
 admission=source_admission.verify(ROOT)
 tasks=seed['task_ids']
 assert tasks==['Prob045_edgedetect2','Prob057_kmap2','Prob127_lemmings1','Prob137_fsm_serial','Prob143_fsm_onehot','Prob146_fsm_serialdata','Prob151_review2015_fsm']
 reference=read(ROOT/'FULL_BASELINE_REFERENCE.json');assert sha(ROOT/'FULL_BASELINE_REFERENCE.json')=='8677fcf01f6589d7afee636cd328e7b296c5abef96da92adecd4929c007171ce'
 assert len(reference['levels'])==156 and sum(v==3 for v in reference['levels'].values())==113
 selected={n:h for n,h in inputs['input_sha256'].items() if n.split('/')[0] in tasks and n.split('/')[-1] in ['prompt.txt','interface.txt']}
 assert set(n.split('/')[0] for n in selected)==set(tasks)
 for n,h in selected.items():assert sha(kit/'bench/tasks_veval'/n)==h
 # Both arms delegate model fallback to the exact original common worker.
 # There is no new model request text or token budget in this factor.
 assert shutil.disk_usage(ROOT).free>=2*1024**3
 names=set(manifest)|{'SOURCE_MANIFEST.json','PREPARATION_INPUTS.json'}
 sources={n:sha(ROOT/n) for n in sorted(names)}
 deps={n:sha(ROOT/'dependencies'/n) for n in ['full156_postflight_audit.py','paired_checkpoint.py','probe_runner.py']}
 spec=dict(schema='table_history_cp8_score7_frozen_v1',identity=ROOT.name,cloud_root=str(ROOT),base_commit=seed['base_commit'],kit=str(kit),model=seed['model'],model_pid=2013333,model_identity=identity,
  dependencies_cloud=str(ROOT/'dependencies'),dependency_hashes=deps,source_hashes=sources,input_hashes=selected,
  compiler_tools=environment['tools'],compiler_env=environment['compiler_env'],udev_files=environment['udev_files'],protected=protected,
  additional_protected_sources=seed['additional_protected_sources'],task_ids=tasks,historically_correct_tasks=[t for t in tasks if reference['levels'][t]==3],arms=['C','P'],expected_samples=14,max_actual_model_requests=28,
  solve_deadline_s=300,judge_timeout_s=300,judge_supervisor_timeout_s=360,max_worker_requests_per_arm=2,output_tokens=8192,repairs=1,retries=0,expected_protection_receipts=29,stage_timeout_s=10000,guard_timeout_s=10400,slot_minutes=180,
  minimum_disk_free_bytes=2*1024**3,official_score_sha256=inputs['official_sha256']['selftest/score.py'],frozen_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
  original44_spec_sha256=sha(ROOT/'upstream/RUN_SPEC.json'),historical_reference_sha256=sha(ROOT/'FULL_BASELINE_REFERENCE.json'),qualification=seed['qualification_receipts'],model_request_factor='unchanged_original_common_worker',
  diagnostic_only=True,qualified_for_full156=False,adoption=False,limits='Seven preselected development inputs,14 fresh outputs/max28 requests. Both arms retain complete table+history; only P genuine no_complete_contract abstentions reach unchanged qualified serial framing. Historical145 remains outside this screen and must be restored before whole-candidate adoption. No full156 admission, score addition or hidden generalization. Original history113, paired/unchanged/historical/total cost gates remain necessary. Stage/guard/slot are safety caps, not ETA.')
 save(ROOT/'RUN_SPEC.json',spec)
 pilot=load('history_cp8_7_prepared_stage',ROOT/'pilot.py');assert pilot.frozen(kit)==spec
 auditor=load('history_cp8_7_prepared_auditor',ROOT/'audit.py');auditor.sources(ROOT,spec)
 assert protect.check(groups)==before and guard.identity(2013333)==identity
 for n,h in seed['additional_protected_sources'].items():assert sha(n)==h
 receipt=dict(schema='table_history_cp8_score7_actual_preparation_receipt_v1',passed=True,spec_sha256=sha(ROOT/'RUN_SPEC.json'),source_assets=len(sources),original44_bound=True,common_phase_P_bound=True,existing_qualified_sources_bound=True,source_admission=admission,model_request_factor="unchanged_original_common_worker",
  expected_samples=14,max_actual_model_requests=28,historical_subset=spec['historically_correct_tasks'],model_identity=identity,old_controls_not_reexecuted=True,new_model_EDA_FIFO_calls=0,whole_stage_executed=False,score_measured=False,qualified_for_full156=False,adoption=False)
 save(ROOT/'PREPARATION_RECEIPT.json',receipt);print(json.dumps(receipt))

if __name__=='__main__':main()
