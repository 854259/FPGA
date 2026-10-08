"""Read-only two-pair original-judge audit. No model or EDA execution."""
import argparse,hashlib,importlib.util,json,re,sys,tempfile
from pathlib import Path,PurePosixPath
ROOT=Path(__file__).resolve().parent
HELPER_SHA='6b141e6da0bac31fd2a3f00ed448f5f600eabe327eaa93594259d760f8d07ba3'
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
read=lambda p:json.loads(Path(p).read_bytes())

def load(n,p):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def sources(run,spec):
 assert spec['schema']=='model_generated_fsm8_diagnostic_frozen_v1'
 assert len(spec['task_ids'])==8 and spec['arms']==['C','P'] and spec['expected_samples']==16 and spec['max_actual_model_requests']==32
 assert spec['solve_deadline_s']==spec['judge_timeout_s']==300 and spec['judge_supervisor_timeout_s']==360
 assert spec['output_tokens']==8192 and spec['max_worker_requests_per_arm']==2 and spec['repairs']==1 and spec['retries']==0
 assert spec['stage_timeout_s']==12000 and spec['expected_protection_receipts']==33
 for n,h in spec['source_hashes'].items():
  rel=PurePosixPath(n);assert not rel.is_absolute() and '..' not in rel.parts and '\\' not in n
  assert sha(run/n)==h,n
 assert sha(run/'upstream/official_eval_guarded.py')=='5d1911d8b730cbb460bf7ceb33cc602bf1f840402971e3dc1301f470fbd52a4c'
 assert sha(run/'baseline_worker.py')=='7ff7ed6e397caedee071a7f46015d81370c92f2579bd61dd2cc3337458467742'
 assert sha(run/'package/agent/map_runtime.py')=='2f7cb98bc44a9e100d36ca12ac4ef7bf9ae2535473da358e166afa2559e96cba'
 assert sha(run/'package/baseline.py')=='537783e39db22079c33c19af475dbdb760a29ff1656a48c481d434131f84fb51'

def protections(run,spec):
 groups=read(run/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json')
 assert sha(run/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json')=='8f88ffbb61504a29336f9c235ba907c50c40d8924acde980ff1f7d3675b43686'
 expected={n:dict(spec_sha256=g['spec_sha256'],source_hashes=g['source_hashes'],source_assets=len(g['source_hashes'])) for n,g in groups['groups'].items()}
 paths=sorted((run/'results/protected_source_checks').glob('*.json'))
 assert [p.name for p in paths]==[str(i).zfill(3)+'.json' for i in range(33)]
 for i,p in enumerate(paths):
  assert read(p)==dict(index=i,schema='semantic_edge_protected_source_check_v1',verified=True,groups=expected,source_assets=groups['source_assets'],model_calls=0,eda_calls=0)

def generation(work,source,arm,spec,deadline,modules,cloudwork):
 proof,replay,baseline,runtime,parser,feedback=modules
 prompt=(source/'prompt.txt').read_bytes().decode();interface=(source/'interface.txt').read_bytes().decode() if (source/'interface.txt').exists() else ''
 assert {p.name for p in (work/'prompt_only').iterdir()}=={n for n in ['prompt.txt','interface.txt'] if (source/n).exists()}
 generation=(ROOT/'package/skill/rtl-generation/SKILL.md').read_text();repair=(ROOT/'package/skill/rtl-feedback-repair/SKILL.md').read_text()
 wire=proof.verify(work,prompt,interface,arm,spec['model'],generation,repair,allow_unconfirmed=deadline)
 combined=proof.boundary.combined(prompt,interface);contract=parser.parse(combined)
 assert contract['status']!='supported'
 trace=[json.loads(x) for x in (work/'trace.jsonl').read_text().splitlines()]
 assert trace and trace[0]['tool']=='agent_meta' and trace[0]['repairs']==1
 assert trace[0]['skill_sha256']==hashlib.sha256(generation.encode()).hexdigest()
 assert trace[0]['repair_skill_sha256']==hashlib.sha256(repair.encode()).hexdigest()
 journal=read(work/'requests.json')
 assert [e['round'] for e in trace if e['tool']=='llm_start']==list(range(len(journal)))
 for i,entry in enumerate(journal):
  if entry['response_received']:
   events=[e for e in trace if e['tool']=='llm' and e['round']==i];assert len(events)==1
   payload=read(work/'requests'/str(i)/'response.json');usage=payload.get('usage') or {}
   assert events[0]['finish']==entry['finish_reason'] and events[0]['tokens_in']==usage.get('prompt_tokens') and events[0]['tokens_out']==usage.get('completion_tokens')
 native=replay.replay(work,combined,arm,contract,baseline,runtime,parser,feedback,lambda *a:(_ for _ in ()).throw(AssertionError('Unexpected native oracle')),sha,read,deadline,first_user=wire['rounds'][0]['forwarded_body']['messages'][1]['content'])
 for e in read(work/'compile_journal.json') if (work/'compile_journal.json').exists() else []:
  assert e.get('simulated',False) is False
  assert e['argv'][0]=='/workspace/AMD/2026.1/Vivado/bin/xvlog'
  folder=PurePosixPath(e['argv'][-1]).parent.name;assert folder in ['compile-0','compile-1']
  assert e['argv'][-1]==str(cloudwork/'work'/folder/'candidate.sv')
 if not deadline:
  result=read(work/'worker_result.json');assert result['complete'] and result['arm']==arm
  assert result['requests']==result['actual_model_requests']==len(journal) and result['solution_sha256']==sha(work/'solution.v')
 return dict(binding=proof.binding(wire),original_replay=native,solution_sha256=sha(work/'solution.v'),first_original_wire_sha256=wire['rounds'][0]['original_wire_sha256'],first_forwarded_wire_sha256=wire['rounds'][0]['forwarded_wire_sha256'])

def audit(archive,out,spec_sha):
 assert sys.platform=='linux' and sys.dont_write_bytecode and sys.version_info[:2]==(3,12) and not out.exists()
 assert sha(ROOT/'RUN_SPEC.json')==spec_sha;local_spec=read(ROOT/'RUN_SPEC.json');sources(ROOT,local_spec)
 helper=ROOT/'dependencies/full156_postflight_audit.py';assert sha(helper)==HELPER_SHA;shared=load('fsm_model_diag_original_evidence_checks',helper)
 old=list(sys.path)
 with tempfile.TemporaryDirectory(prefix='model-fsm8-original-audit-') as temporary:
  root=Path(temporary);manifest=shared.unpack(archive,root);run=root/'run'
  assert sha(run/'RUN_SPEC.json')==manifest['run_spec_sha256']==spec_sha;spec=read(run/'RUN_SPEC.json');assert spec==local_spec;sources(run,spec)
  assert manifest['collector_sha256']==sha(run/'collect_evidence.py') and manifest['collector_model_calls']==manifest['collector_eda_calls']==0
  for n,h in spec['dependency_hashes'].items():assert sha(root/'dependencies'/n)==h
  prep=read(run/'PREPARATION_RECEIPT.json');assert prep['passed'] and prep['spec_sha256']==spec_sha
  inputs=read(run/'INPUT_MANIFEST.json')
  for n,h in inputs['input_sha256'].items():
   if n.split('/')[0] in spec['task_ids']:assert sha(root/'kit/bench/tasks_veval'/n)==h
  for n,h in inputs['official_sha256'].items():assert sha(root/'kit/official_reference'/n)==h
  guard=read(root/'guard/status.json');resource=read(root/'guard/resource_check.json');environment=read(run/'results/ENVIRONMENT_PREFLIGHT.json')
  assert all(guard[k] for k in ['complete','passed','model_unchanged','protected_files_unchanged','own_slot_released'])
  assert guard['stage_rc']==0 and not guard['model_managed'] and not guard['instance_managed']
  assert guard['owned_cleanup']['verified'] and not guard['owned_cleanup']['remaining']
  assert guard['model_idle_after']['processing_slots']==0 and guard['model_idle_after']['model_pid_owns_port']
  assert resource['model_identity']==spec['model_identity'] and resource['resource_idle'] and resource['model_name']==spec['model']
  assert resource['protected']['tasks']==inputs['input_sha256'] and resource['protected']['official']==inputs['official_sha256']
  assert environment['verified'] and environment['model_calls']==environment['eda_calls']==0
  assert environment['tools']==spec['compiler_tools'] and environment['compiler_env']==spec['compiler_env'] and environment['udev_files']==spec['udev_files']
  protections(run,spec);sys.path[:0]=[str(run),str(run/'package')]
  proof=load('fsm_model_diag_archive_wire',run/'request_proof.py');replay=load('fsm_model_diag_archive_replay',run/'model_replay.py')
  baseline=load('fsm_model_diag_archive_extract',run/'package/baseline.py');runtime=load('fsm_model_diag_archive_runtime',run/'package/agent/map_runtime.py')
  parser=load('fsm_model_diag_archive_parser',run/'edge_dispatch.py');feedback=load('fsm_model_diag_archive_feedback',run/'phase_feedback.py');metrics=load('fsm_model_diag_archive_metrics',run/'metrics.py')
  report=read(run/'results/summary.json');assert report['complete'] and report['passed'] and report['spec_sha256']==spec_sha and not report['first_generation_replayed']
  assert [(r['task'],r['arm']) for r in report['rows']]==metrics.order(spec['task_ids'])
  assert {(p.parent.name,p.parent.parent.name) for p in (run/'results/samples').glob('*/*/row.json')}==set(metrics.order(spec['task_ids']))
  provenance=[];total=0
  for row in report['rows']:
   task,arm=row['task'],row['arm'];sample=run/'results/samples'/arm/task;work=sample/'worker';cloud=PurePosixPath(spec['cloud_root']);samplecloud=cloud/'results/samples'/arm/task
   assert row==read(sample/'row.json');command=read(sample/'worker_command.json');shared.command(command,sample/'worker.log',allow_timeout=True)
   assert command['argv']==['/usr/bin/python3','-B',str(cloud/'worker.py'),'--out',str(samplecloud/'worker'),'--task',task,'--arm',arm,'--kit',spec['kit'],'--resource-check',str(cloud/'guard/resource_check.json')]
   assert row['solve_elapsed_s']==command['elapsed_s'] and row['solve_deadline_reached']==command['timeout']
   judged=read(sample/'judge_command.json');shared.command(judged,sample/'judge.log')
   assert judged['argv']==['/usr/bin/python3','-B',str(cloud/'pilot.py'),'judge','--task',task,'--solution',str(samplecloud/'worker/solution.v'),'--out',str(samplecloud/'judge'),'--kit',spec['kit']]
   verdict=shared.judge(sample/'judge',work/'solution.v',task)
   assert row['verdict']==verdict and row['verdict_sha256']==sha(sample/'judge/verdict.json') and row['solution_sha256']==sha(work/'solution.v')
   bound=generation(work,root/'kit/bench/tasks_veval'/task,arm,spec,command['timeout'],(proof,replay,baseline,runtime,parser,feedback),samplecloud/'worker')
   assert read(sample/'generation_proof.json')==bound
   assert all(row[k]==v for k,v in bound['binding'].items())
   assert row['first_original_wire_sha256']==bound['first_original_wire_sha256'] and row['first_forwarded_wire_sha256']==bound['first_forwarded_wire_sha256']
   journal=read(work/'requests.json');assert row['actual_model_requests']==len(journal) and row['received_model_responses']==sum(e['response_received'] for e in journal)
   total+=len(journal);provenance.append(dict(task=task,arm=arm,**bound))
  score=root/'kit/official_reference/selftest/score.py';assert sha(score)==spec['official_score_sha256'];scorer=load('fsm_model_diag_archive_original_score',score)
  aggregate=metrics.aggregate(report['rows'],spec['task_ids'],spec['historically_correct_tasks'],scorer)
  assert total==report['actual_model_requests']<=32
  for k,v in aggregate.items():assert report[k]==v,k
  result=dict(schema='model_generated_fsm8_original_complete_audit_v1',evidence_valid=True,archive_sha256=sha(archive),spec_sha256=spec_sha,auditor_sha256=sha(Path(__file__)),expected_samples=16,actual_model_requests=total,provenance=provenance,audit_model_calls=0,audit_eda_calls=0,**aggregate)
 sys.path[:]=old;out.mkdir(parents=True);(out/'RESULTS.json').write_bytes((json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode());return result

if __name__=='__main__':
 p=argparse.ArgumentParser();p.add_argument('--archive',type=Path,required=True);p.add_argument('--out',type=Path,required=True);p.add_argument('--spec-sha',required=True);a=p.parse_args()
 r=audit(a.archive,a.out,a.spec_sha);print(json.dumps({k:r[k] for k in ['evidence_valid','actual_model_requests','diagnostic_promising','qualified_for_new_full_regression','adoption']}))
