"""AMD-only pure two-pair diagnostic freeze; reuses qualified controls, never inference."""
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
 assert seed['schema']=='galois_pair2_current_freeze_inputs_v1' and seed['cloud_root']==str(ROOT)
 manifest=read(ROOT/'SOURCE_MANIFEST.json');assert sha(ROOT/'SOURCE_MANIFEST.json')==seed['source_manifest_sha256']
 for n,h in manifest.items():assert sha(ROOT/n)==h,n
 for n,h in seed['qualification_receipts'].items():assert sha(n)==h,n
 for n,h in seed['qualification_sources'].items():assert sha(ROOT/n)==h,n
 groups=read(ROOT/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json')
 assert sha(ROOT/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json')=='8f88ffbb61504a29336f9c235ba907c50c40d8924acde980ff1f7d3675b43686'
 protect=load('galois_diag_prepare_protection',ROOT/'protected_sources.py');before=protect.check(groups)
 assert before['verified'] and len(groups['groups'])==141
 for n,h in seed['additional_protected_sources'].items():assert sha(n)==h
 guard=load('galois_diag_prepare_original_guard',ROOT/'guard_wrapper.py');identity=guard.identity(2013333)
 assert identity==dict(pid=2013333,starttime='823869819',exe='llama-server',command_sha256='2ef1233963df0e5cc660fc2bed2baa2fca4e30b84d450e79bc9f77381cbd24e1')
 env=dict(PATH='/workspace/AMD/2026.1/Vivado/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',VIVADO_BIN='/workspace/AMD/2026.1/Vivado/bin',LD_LIBRARY_PATH='/workspace/team/udev-stub');os.environ.update(env)
 environment=load('galois_diag_prepare_original_environment',ROOT/'original_environment.py').validate_environment()
 inputs=read(ROOT/'INPUT_MANIFEST.json');protected=guard.protected(kit)
 assert protected['tasks']==inputs['input_sha256'] and protected['official']==inputs['official_sha256']
 original=read(ROOT/'upstream/RUN_SPEC.json');assert sha(ROOT/'upstream/RUN_SPEC.json')=='3fb1531c14b011f80ff58de559e326a4904d3fbdbcf3cdce7d6c955285860ba1'
 for n,h in original['source_hashes'].items():assert sha(ROOT/'upstream'/n)==h
 originalworker=(ROOT/'upstream/worker.py').read_bytes();common=(ROOT/'baseline_worker.py').read_bytes()
 old=b"candidate=args.arm == 'P'";assert originalworker.count(old)==1
 assert originalworker.replace(old,b'candidate=True')==common
 for n in ['package/agent/map_runtime.py','package/baseline.py']:
  assert (ROOT/n).read_bytes()==(ROOT/'upstream'/n).read_bytes()
 replay_proof=read(ROOT/'MODEL_REPLAY_ADAPTATION.json');assert replay_proof['original_sha256']==sha(ROOT/'upstream/replay.py')
 assert replay_proof['adapted_sha256']==sha(ROOT/'model_replay.py')
 adapted=(ROOT/'upstream/replay.py').read_bytes().decode()
 for change in replay_proof['changes']:
  assert adapted.count(change['old'])==1;adapted=adapted.replace(change['old'],change['new'])
 assert adapted.encode()==(ROOT/'model_replay.py').read_bytes()
 intake=read(seed['intake_result_path']);tasks=intake['changed_tasks']
 assert intake['passed'] and intake['inputs']==156 and len(tasks)==2 and tasks==sorted(tasks)
 reference=read(ROOT/'FULL_BASELINE_REFERENCE.json');assert sha(ROOT/'FULL_BASELINE_REFERENCE.json')=='8677fcf01f6589d7afee636cd328e7b296c5abef96da92adecd4929c007171ce'
 assert len(reference['levels'])==156 and sum(v==3 for v in reference['levels'].values())==113
 selected={n:h for n,h in inputs['input_sha256'].items() if n.split('/')[0] in tasks and n.split('/')[-1] in ['prompt.txt','interface.txt']}
 assert set(n.split('/')[0] for n in selected)==set(tasks)
 for n,h in selected.items():assert sha(kit/'bench/tasks_veval'/n)==h
 # Only retain the already-intaken two changed wires. No repeated156 intake, tokenization or requests.
 boundary=load('galois_diag_prepare_boundary',ROOT/'galois_first_request.py');generation=(ROOT/'package/skill/rtl-generation/SKILL.md').read_text()
 retained=[]
 for task in tasks:
  source=kit/'bench/tasks_veval'/task;prompt=(source/'prompt.txt').read_bytes().decode();interface=(source/'interface.txt').read_bytes().decode() if (source/'interface.txt').exists() else ''
  payload=dict(model=seed['model'],messages=[dict(role='system',content=generation),dict(role='user',content=boundary.combined(prompt,interface))],temperature=0.0,top_p=1.0,max_tokens=8192)
  raw=json.dumps(payload).encode();forwarded,receipt=boundary.transform(raw,prompt,interface,'P',0)
  oldrow=next(r for r in intake['rows'] if r['task']==task)
  assert receipt['changed'] and hashlib.sha256(forwarded).hexdigest()==oldrow['forwarded_wire_sha256']
  assert oldrow['conservative_context_total']<16384
  retained.append(dict(task=task,forwarded_wire_sha256=oldrow['forwarded_wire_sha256'],context_bound=oldrow['conservative_context_total']))
 assert shutil.disk_usage(ROOT).free>=2*1024**3
 names=set(manifest)|{'SOURCE_MANIFEST.json','PREPARATION_INPUTS.json'}
 sources={n:sha(ROOT/n) for n in sorted(names)}
 deps={n:sha(ROOT/'dependencies'/n) for n in ['full156_postflight_audit.py','paired_checkpoint.py','probe_runner.py']}
 spec=dict(schema='galois_pair2_diagnostic_frozen_v1',identity=ROOT.name,cloud_root=str(ROOT),base_commit=seed['base_commit'],kit=str(kit),model=seed['model'],model_pid=2013333,model_identity=identity,
  dependencies_cloud=str(ROOT/'dependencies'),dependency_hashes=deps,source_hashes=sources,input_hashes=selected,
  compiler_tools=environment['tools'],compiler_env=environment['compiler_env'],udev_files=environment['udev_files'],protected=protected,
  additional_protected_sources=seed['additional_protected_sources'],task_ids=tasks,historically_correct_tasks=[t for t in tasks if reference['levels'][t]==3],arms=['C','P'],expected_samples=4,max_actual_model_requests=8,
  solve_deadline_s=300,judge_timeout_s=300,judge_supervisor_timeout_s=360,max_worker_requests_per_arm=2,output_tokens=8192,repairs=1,retries=0,expected_protection_receipts=9,stage_timeout_s=3600,guard_timeout_s=4000,slot_minutes=70,
  minimum_disk_free_bytes=2*1024**3,official_score_sha256=inputs['official_sha256']['selftest/score.py'],frozen_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
  original44_spec_sha256=sha(ROOT/'upstream/RUN_SPEC.json'),historical_reference_sha256=sha(ROOT/'FULL_BASELINE_REFERENCE.json'),qualification=seed['qualification_receipts'],retained_intake_wires=retained,
  diagnostic_only=True,qualified_for_full156=False,adoption=False,limits='Two eligible development inputs,4 fresh outputs/max8 requests. No full156 admission, score addition or hidden generalization. Original history113, paired/unchanged/historical/total cost gates remain necessary. Stage/guard/slot are safety caps, not ETA.')
 save(ROOT/'RUN_SPEC.json',spec)
 pilot=load('galois_diag_prepared_stage',ROOT/'pilot.py');assert pilot.frozen(kit)==spec
 auditor=load('galois_diag_prepared_auditor',ROOT/'audit.py');auditor.sources(ROOT,spec)
 assert protect.check(groups)==before and guard.identity(2013333)==identity
 for n,h in seed['additional_protected_sources'].items():assert sha(n)==h
 receipt=dict(schema='galois_pair2_actual_pure_preparation_receipt_v1',passed=True,spec_sha256=sha(ROOT/'RUN_SPEC.json'),source_assets=len(sources),original44_bound=True,common_phase_P_bound=True,existing_qualified_sources_bound=True,retained_intake_wires=retained,
  expected_samples=4,max_actual_model_requests=8,historical_subset=spec['historically_correct_tasks'],model_identity=identity,old_controls_not_reexecuted=True,new_model_EDA_FIFO_calls=0,whole_stage_executed=False,score_measured=False,qualified_for_full156=False,adoption=False)
 save(ROOT/'PREPARATION_RECEIPT.json',receipt);print(json.dumps(receipt))

if __name__=='__main__':main()
