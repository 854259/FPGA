"""AMD-only preparation of one genuinely model-generated eight-input diagnostic."""
import datetime,hashlib,importlib.util,json,os,shutil,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
read=lambda p:json.loads(Path(p).read_bytes())
def load(n,p):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def save(p,j):
 with p.open('x',encoding='utf-8') as f:json.dump(j,f,indent=2);f.write('\n')
def main():
 assert sys.platform=='linux' and sys.dont_write_bytecode and not (ROOT/'RUN_SPEC.json').exists()
 seed=read(ROOT/'PREPARATION_INPUTS.json');assert seed['cloud_root']==str(ROOT)
 manifest=read(ROOT/'SOURCE_MANIFEST.json')
 for n,h in manifest.items():assert sha(ROOT/n)==h,n
 for n,h in seed['additional_protected_sources'].items():assert sha(n)==h,n
 kit=Path(seed['kit']);env=dict(PATH='/workspace/AMD/2026.1/Vivado/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',VIVADO_BIN='/workspace/AMD/2026.1/Vivado/bin',LD_LIBRARY_PATH='/workspace/team/udev-stub')
 os.environ.update(env);environment=load('fsm_model_environment',ROOT/'original_environment.py').validate_environment()
 guard=load('fsm_model_original_guard',ROOT/'guard_wrapper.py');identity=guard.identity(2013333)
 assert identity==seed['model_identity']
 protected=guard.protected(kit);inputs=read(ROOT/'INPUT_MANIFEST.json')
 assert protected['tasks']==inputs['input_sha256'] and protected['official']==inputs['official_sha256']
 groups=read(ROOT/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json')
 before=load('fsm_model_protection',ROOT/'protected_sources.py').check(groups);assert before['verified']
 original=read(ROOT/'upstream/RUN_SPEC.json');assert sha(ROOT/'upstream/RUN_SPEC.json')=='3fb1531c14b011f80ff58de559e326a4904d3fbdbcf3cdce7d6c955285860ba1'
 for n,h in original['source_hashes'].items():assert sha(ROOT/'upstream'/n)==h
 assert (ROOT/'upstream/worker.py').read_bytes().replace(b"candidate=args.arm == 'P'",b'candidate=True')==(ROOT/'baseline_worker.py').read_bytes()
 boundary=load('fsm_model_boundary',ROOT/'fsm_guidance.py');parser=load('fsm_model_scope',ROOT/'edge_dispatch.py')
 tasks=seed['task_ids'];assert len(tasks)==len(set(tasks))==8 and tasks==sorted(tasks)
 generation=(ROOT/'package/skill/rtl-generation/SKILL.md').read_text();wires=[]
 for task in tasks:
  source=kit/'bench/tasks_veval'/task;prompt=(source/'prompt.txt').read_bytes().decode();interface=(source/'interface.txt').read_bytes().decode() if (source/'interface.txt').exists() else ''
  # This fixed diagnostic introduces no functional checker beyond the existing model solver.
  assert parser.parse(boundary.combined(prompt,interface))['status']!='supported'
  payload=dict(model=seed['model'],messages=[dict(role='system',content=generation),dict(role='user',content=boundary.combined(prompt,interface))],temperature=0.0,top_p=1.0,max_tokens=8192)
  raw=json.dumps(payload).encode();forwarded,receipt=boundary.transform(raw,prompt,interface,'P',0)
  boundary.verify(raw,forwarded,prompt,interface,'P',0,receipt)
  # UTF-8 bytes are a conservative bound for the fixed byte-fallback tokenizer.
  assert len(forwarded)+8192+128<16384
  wires.append(dict(task=task,changed=receipt['changed'],forwarded_wire_sha256=hashlib.sha256(forwarded).hexdigest(),conservative_context_bytes_plus_output=len(forwarded)+8192+128))
 names=set(manifest)|{'SOURCE_MANIFEST.json','PREPARATION_INPUTS.json'};sources={n:sha(ROOT/n) for n in sorted(names)}
 selected={n:h for n,h in inputs['input_sha256'].items() if n.split('/')[0] in tasks and n.split('/')[-1] in ['prompt.txt','interface.txt']}
 reference=read(ROOT/'FULL_BASELINE_REFERENCE.json')
 assert shutil.disk_usage(ROOT).free>=2*1024**3
 spec=dict(schema='model_generated_fsm8_diagnostic_frozen_v1',identity=ROOT.name,cloud_root=str(ROOT),base_commit=seed['base_commit'],kit=str(kit),model=seed['model'],model_pid=2013333,model_identity=identity,dependencies_cloud=str(ROOT/'dependencies'),dependency_hashes={n:sha(ROOT/'dependencies'/n) for n in ['full156_postflight_audit.py','paired_checkpoint.py','probe_runner.py']},source_hashes=sources,input_hashes=selected,compiler_tools=environment['tools'],compiler_env=environment['compiler_env'],udev_files=environment['udev_files'],protected=protected,additional_protected_sources=seed['additional_protected_sources'],task_ids=tasks,historically_correct_tasks=[t for t in tasks if reference['levels'][t]==3],arms=['C','P'],expected_samples=16,max_actual_model_requests=32,solve_deadline_s=300,judge_timeout_s=300,judge_supervisor_timeout_s=360,max_worker_requests_per_arm=2,output_tokens=8192,repairs=1,retries=0,expected_protection_receipts=33,stage_timeout_s=12000,guard_timeout_s=12400,slot_minutes=215,minimum_disk_free_bytes=2*1024**3,official_score_sha256=inputs['official_sha256']['selftest/score.py'],frozen_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),model_generated_RTL_required=True,mechanical_producers_included=False,diagnostic_only=True,qualified_for_full156=False,adoption=False,private_per_task_cost_veto=False,official100_unknown=True)
 save(ROOT/'RUN_SPEC.json',spec)
 assert load('fsm_model_prepared_pilot',ROOT/'pilot.py').frozen(kit)==spec
 load('fsm_model_prepared_audit',ROOT/'audit.py').sources(ROOT,spec)
 assert load('fsm_model_post_protect',ROOT/'protected_sources.py').check(groups)==before and guard.identity(2013333)==identity
 save(ROOT/'PREPARATION_RECEIPT.json',dict(passed=True,spec_sha256=sha(ROOT/'RUN_SPEC.json'),source_assets=len(sources),first_wires=wires,model_generated_RTL_required=True,old_controls_replayed=False,new_model_EDA_FIFO_calls=0,score_measured=False,adoption=False))
 print(json.dumps(dict(passed=True,spec_sha256=sha(ROOT/'RUN_SPEC.json'),source_assets=len(sources),first_wires=wires)))
if __name__=='__main__':main()
