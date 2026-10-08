"""AMD-only fixed-five wave comparison freeze; original budget, no inference."""
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
 assert seed['schema']=='table_history_wave_score5_freeze_inputs_v1' and seed['cloud_root']==str(ROOT)
 manifest=read(ROOT/'SOURCE_MANIFEST.json');assert sha(ROOT/'SOURCE_MANIFEST.json')==seed['source_manifest_sha256']
 for n,h in manifest.items():assert sha(ROOT/n)==h,n
 for n,h in seed['qualification_receipts'].items():assert sha(n)==h,n
 for n,h in seed['qualification_sources'].items():assert sha(ROOT/n)==h,n
 groups=read(ROOT/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json')
 assert sha(ROOT/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json')=='8f88ffbb61504a29336f9c235ba907c50c40d8924acde980ff1f7d3675b43686'
 protect=load('history_wave5_prepare_protection',ROOT/'protected_sources.py');before=protect.check(groups)
 assert before['verified'] and len(groups['groups'])==141
 for n,h in seed['additional_protected_sources'].items():assert sha(n)==h
 guard=load('history_wave5_prepare_original_guard',ROOT/'guard_wrapper.py');identity=guard.identity(2013333)
 assert identity==dict(pid=2013333,starttime='823869819',exe='llama-server',command_sha256='2ef1233963df0e5cc660fc2bed2baa2fca4e30b84d450e79bc9f77381cbd24e1')
 env=dict(PATH='/workspace/AMD/2026.1/Vivado/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',VIVADO_BIN='/workspace/AMD/2026.1/Vivado/bin',LD_LIBRARY_PATH='/workspace/team/udev-stub');os.environ.update(env)
 environment=load('history_wave5_prepare_original_environment',ROOT/'original_environment.py').validate_environment()
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
 assert tasks==['Prob001_zero','Prob057_kmap2','Prob143_fsm_onehot','Prob145_circuit8','Prob151_review2015_fsm']
 reference=read(ROOT/'FULL_BASELINE_REFERENCE.json');assert sha(ROOT/'FULL_BASELINE_REFERENCE.json')=='8677fcf01f6589d7afee636cd328e7b296c5abef96da92adecd4929c007171ce'
 assert len(reference['levels'])==156 and sum(v==3 for v in reference['levels'].values())==113
 selected={n:h for n,h in inputs['input_sha256'].items() if n.split('/')[0] in tasks and n.split('/')[-1] in ['prompt.txt','interface.txt']}
 assert set(n.split('/')[0] for n in selected)==set(tasks)
 for n,h in selected.items():assert sha(kit/'bench/tasks_veval'/n)==h
 # Rebuild only the two model-fallback inputs in the new composed bundle.
 # Exact old105 wires and usage are retained evidence, not new tokenization.
 import waveform_request
 import composition
 original_wire=read(ROOT/'RETAINED_MODEL_FIRST_WIRES.json')
 assert original_wire['schema']=='original105_first_model_wires_for_new_score5_v1'
 wave_metadata=ROOT/'qualification/wave105'
 assert sha(wave_metadata/'MODEL_SCOPE_RECEIPTS.json')==source_admission.WAVE_SCOPE
 scope=read(wave_metadata/'MODEL_SCOPE_RECEIPTS.json')
 assert original_wire['scope_receipts_sha256']==source_admission.WAVE_SCOPE
 assert original_wire['original_spec_sha256']==scope['original_spec_sha256']==source_admission.WAVE_SPEC
 assert original_wire['original_audit_sha256']==scope['audit_sha256']==source_admission.WAVE_AUDIT
 assert set(original_wire['tasks'])==set(scope['tasks'])=={'Prob001_zero','Prob145_circuit8'}
 generation=(ROOT/'package/skill/rtl-generation/SKILL.md').read_text()
 retained=[]
 for task in ['Prob001_zero','Prob145_circuit8']:
  source=kit/'bench/tasks_veval'/task;prompt=(source/'prompt.txt').read_bytes().decode();interface=(source/'interface.txt').read_bytes().decode() if (source/'interface.txt').exists() else ''
  assert not composition.synthesize(prompt,interface)['emitted']
  user=prompt.replace('\r\n','\n').replace('\r','\n');normalized=interface.replace('\r\n','\n').replace('\r','\n')
  if normalized.strip():user+='\n\nInterface:\n'+normalized
  body=dict(model=seed['model'],messages=[dict(role='system',content=generation),dict(role='user',content=user)],temperature=0.0,top_p=1.0,max_tokens=8192)
  raw=json.dumps(body).encode()
  for arm in ['C','P']:
   forwarded,receipt=waveform_request.transform(raw,prompt,interface,arm,0)
   previous=original_wire['tasks'][task][arm]
   folder=wave_metadata/'model_scope'/task/arm;retained_source=scope['tasks'][task][arm]
   assert set(original_wire['tasks'][task])=={'C','P'}
   for name,binding in retained_source['files'].items():assert sha(folder/name)==binding['sha256']
   usage=read(folder/'response_usage.json')
   assert previous['response_usage_sha256']==sha(folder/'response_usage.json')
   assert previous['original_request_sha256']==usage['original_request_sha256']==sha(folder/'request.json')
   assert previous['original_response_sha256']==usage['original_response_sha256']
   assert usage['model']==seed['model'] and usage['first_only'] is True and usage['not_new_tokenization'] is True
   assert previous['prompt_tokens']==usage['usage']['prompt_tokens']==retained_source['first_prompt_tokens']
   assert previous['original_wire_sha256']==sha(folder/'original_wire.bin')==retained_source['first_original_wire_sha256']
   assert previous['forwarded_wire_sha256']==sha(folder/'forwarded_wire.bin')==retained_source['first_forwarded_wire_sha256']
   assert previous['receipt']==read(folder/'receipt.json')
   assert hashlib.sha256(raw).hexdigest()==previous['original_wire_sha256']
   assert hashlib.sha256(forwarded).hexdigest()==previous['forwarded_wire_sha256']
   assert receipt==previous['receipt']
   assert receipt['changed']==(task=='Prob145_circuit8' and arm=='P')
   assert type(previous['prompt_tokens']) is int and previous['prompt_tokens']+8192<16384
   retained.append(dict(task=task,arm=arm,original_wire_sha256=receipt['original_wire_sha256'],forwarded_wire_sha256=receipt['forwarded_wire_sha256'],changed=receipt['changed'],old_first_prompt_tokens=previous['prompt_tokens'],first_context_bound=previous['prompt_tokens']+8192,old_usage_only=True,old_response_usage_sha256=previous['response_usage_sha256'],old_original_response_sha256=previous['original_response_sha256'],old_original_request_sha256=previous['original_request_sha256'],all_repair_capacity_proved=False))
 assert shutil.disk_usage(ROOT).free>=2*1024**3
 names=set(manifest)|{'SOURCE_MANIFEST.json','PREPARATION_INPUTS.json'}
 sources={n:sha(ROOT/n) for n in sorted(names)}
 deps={n:sha(ROOT/'dependencies'/n) for n in ['full156_postflight_audit.py','paired_checkpoint.py','probe_runner.py']}
 spec=dict(schema='table_history_wave_score5_frozen_v1',identity=ROOT.name,cloud_root=str(ROOT),base_commit=seed['base_commit'],kit=str(kit),model=seed['model'],model_pid=2013333,model_identity=identity,
  dependencies_cloud=str(ROOT/'dependencies'),dependency_hashes=deps,source_hashes=sources,input_hashes=selected,
  compiler_tools=environment['tools'],compiler_env=environment['compiler_env'],udev_files=environment['udev_files'],protected=protected,
  additional_protected_sources=seed['additional_protected_sources'],task_ids=tasks,historically_correct_tasks=[t for t in tasks if reference['levels'][t]==3],arms=['C','P'],expected_samples=10,max_actual_model_requests=20,
  solve_deadline_s=300,judge_timeout_s=300,judge_supervisor_timeout_s=360,max_worker_requests_per_arm=2,output_tokens=8192,repairs=1,retries=0,expected_protection_receipts=21,stage_timeout_s=7200,guard_timeout_s=7600,slot_minutes=130,
  minimum_disk_free_bytes=2*1024**3,official_score_sha256=inputs['official_sha256']['selftest/score.py'],frozen_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
  original44_spec_sha256=sha(ROOT/'upstream/RUN_SPEC.json'),historical_reference_sha256=sha(ROOT/'FULL_BASELINE_REFERENCE.json'),qualification=seed['qualification_receipts'],retained_first_model_wires=retained,
  diagnostic_only=True,qualified_for_full156=False,adoption=False,limits='Five preselected development inputs,10 fresh outputs/max20 requests. Both arms retain complete table+history; only P initial model waveform advice differs. No full156 admission, score addition or hidden generalization. Original history113, paired/unchanged/historical/total cost gates remain necessary. Stage/guard/slot are safety caps, not ETA.')
 save(ROOT/'RUN_SPEC.json',spec)
 pilot=load('history_wave5_prepared_stage',ROOT/'pilot.py');assert pilot.frozen(kit)==spec
 auditor=load('history_wave5_prepared_auditor',ROOT/'audit.py');auditor.sources(ROOT,spec)
 assert protect.check(groups)==before and guard.identity(2013333)==identity
 for n,h in seed['additional_protected_sources'].items():assert sha(n)==h
 receipt=dict(schema='table_history_wave_score5_actual_preparation_receipt_v1',passed=True,spec_sha256=sha(ROOT/'RUN_SPEC.json'),source_assets=len(sources),original44_bound=True,common_phase_P_bound=True,existing_qualified_sources_bound=True,source_admission=admission,retained_first_model_wires=retained,
  expected_samples=10,max_actual_model_requests=20,historical_subset=spec['historically_correct_tasks'],model_identity=identity,old_controls_not_reexecuted=True,new_model_EDA_FIFO_calls=0,whole_stage_executed=False,score_measured=False,qualified_for_full156=False,adoption=False)
 save(ROOT/'PREPARATION_RECEIPT.json',receipt);print(json.dumps(receipt))

if __name__=='__main__':main()
