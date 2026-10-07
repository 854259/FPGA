
"""AMD task-independent compile pairs only; no model or scoring requests."""
import argparse,hashlib,importlib.util,json,sys,time
from pathlib import Path
import agent_extract_boundary
ROOT=Path(__file__).parent
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
read=lambda p:json.loads(Path(p).read_bytes())
def save(p,j):
 with Path(p).open('x',encoding='utf-8') as f:json.dump(j,f,indent=2);f.write('\n')
def load(n,p):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def main():
 p=argparse.ArgumentParser();p.add_argument('--resource-check',type=Path,required=True);a=p.parse_args()
 assert sys.platform=='linux' and sys.dont_write_bytecode and sha('/usr/bin/python3')=='8295ee25cfdb239f3e165afceda7f46de73e2b606ff0e2e3d8623e3facd30acc'
 spec=read(ROOT/'RUN_SPEC.json');started=time.monotonic()
 paired=load('lexical_native_pair_guard',ROOT/'dependencies/paired_checkpoint.py');protected=load('lexical_native_source_guard',ROOT/'dependencies/protected_sources.py');bounded=load('lexical_native_tool_owned',ROOT/'bounded_owned_exec.py')
 baseline=load('lexical_native_official_extract',ROOT/'package/baseline.py')
 capture=read(ROOT/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json');original_protected=protected.check(capture)
 ledger=Path('/workspace/team/activity/fpga_owner');primary={n:sha(ledger/n) for n in ('STATUS.md','SNAPSHOT.json')}
 before_peer=read('/workspace/team/runs/fpga_teammate/serial_framing_synthesis_full156_20261007_v1/RUN_SPEC.json')
 assert len(before_peer['source_hashes'])==120
 results=ROOT/'results';results.mkdir(exist_ok=False);checks=results/'guard_checks';checks.mkdir();guard_records=[]
 def gate():
  resource=paired.check_resource(a.resource_check,Path(spec['kit']))
  assert sha(spec['xvlog'])==spec['xvlog_script_sha256']
  for n,h in spec['source_hashes'].items():assert sha(ROOT/n)==h,n
  assert primary=={n:sha(ledger/n) for n in primary}
  peer=Path('/workspace/team/runs/fpga_teammate/serial_framing_synthesis_full156_20261007_v1');assert sha(peer/'RUN_SPEC.json')=='dbce8beb5342fe590078dd8eafb29a4d762575a58db2599cab9942f453331c4b'
  for n,h in before_peer['source_hashes'].items():assert sha(peer/n)==h,n
  receipt=dict(index=len(guard_records),category='admission' if not guard_records else 'native_protection',source15_held=True,peer115_120_held=True,model_identity=resource['model_identity'],resource_check_sha256=sha(a.resource_check),primary_two_file_sha256=primary,xvlog_script_held=True)
  save(checks/(str(len(guard_records))+'.json'),receipt);guard_records.append(receipt)
 gate();rows=[];guards=0
 fixtures=read(ROOT/'SYNTHETIC_CASES.json')['positive_boundary_cases'];assert len(fixtures)==7
 expected_C=[True,True,False,False,False,True,True]
 for i,c in enumerate(fixtures):
  candidate,receipt=agent_extract_boundary.extract_with_receipt(c['text'],'rtl',baseline.extract)
  assert candidate==c['expected_code'] and receipt['semantic_edits']==0
  pair={}
  for arm,code in [('C',baseline.extract(c['text'],'rtl')),('P',candidate)]:
   gate();guards+=1;work=results/str(i)/arm;work.mkdir(parents=True);source=work/'candidate.sv';source.write_text(code,encoding='utf-8',newline='\n');before=sha(source)
   command=[spec['xvlog'],'--sv',str(source)];record=bounded.run(command,work,work/'tool',60)
   gate();guards+=1;assert sha(source)==before
   supervised=record['normal_completion'] and record['exec_confirmed'] and record['leader_reaped'] and not record['remaining_group']
   expected=True if arm=='P' else expected_C[i]
   passed=bool(supervised and (record['returncode']==0)==expected)
   row=dict(arm=arm,expected_compile_success=expected,compile_success=record['returncode']==0,passed=passed,source_sha256=before,record=record)
   save(work/'CHECK.json',row);pair[arm]=row
  rows.append(dict(name=c['name'],pair=pair,passed=all(r['passed'] for r in pair.values()),extraction=receipt))
  save(results/('pair_'+str(i)+'.json'),rows[-1])
 gate();guards+=1;assert protected.check(capture)==original_protected
 assert len(rows)==7 and guards==29 and len(guard_records)==30
 result=dict(schema='agent_lexical_boundary_native14_v1',complete=True,passed=all(r['passed'] for r in rows),native_commands=14,protection_receipts=29,admission_receipts=1,all_guard_receipts_physical=True,model_calls=0,scoring_calls=0,original16_and_engineering8_not_replayed=True,protected141_groups_unchanged=True,peer115_120_sources_unchanged=True,source_manifest_unchanged=True,primary_two_files_unchanged=True,official_baseline_unchanged=True,elapsed_stage_before_summary_s=time.monotonic()-started,score_measured=False,adoption=False,goal_achieved=False,rows=rows)
 save(results/'summary.json',result);print(json.dumps({k:v for k,v in result.items() if k!='rows'}));return 0 if result['passed'] else 2
if __name__=='__main__':raise SystemExit(main())
