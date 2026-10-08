
"""Independent AMD native tools; repair receives only actual candidate and compiler log."""
import argparse,hashlib,importlib.util,json,re,sys,time
from pathlib import Path
import internal_wire_repair
ROOT=Path(__file__).parent
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();read=lambda p:json.loads(Path(p).read_bytes())
def save(p,j):
 with Path(p).open('x',encoding='utf-8') as f:json.dump(j,f,indent=2);f.write('\n')
def load(n,p):
 s=importlib.util.spec_from_file_location(n,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def main():
 p=argparse.ArgumentParser();p.add_argument('--resource-check',type=Path,required=True);a=p.parse_args();spec=read(ROOT/'RUN_SPEC.json');started=time.monotonic()
 assert sys.platform=='linux' and sys.dont_write_bytecode
 paired=load('wire_native_paired',ROOT/'dependencies/paired_checkpoint.py');protected=load('wire_native_protected',ROOT/'dependencies/protected_sources.py');bounded=load('wire_native_bounded',ROOT/'bounded_owned_exec.py')
 before_protected=protected.check(read(ROOT/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json'));ledger=Path('/workspace/team/activity/fpga_owner');primary={n:sha(ledger/n) for n in ('STATUS.md','SNAPSHOT.json')}
 results=ROOT/'results';results.mkdir(exist_ok=False);guards=0;commands=[]
 def gate():
  nonlocal guards
  paired.check_resource(a.resource_check,Path(spec['kit']))
  for n,h in spec['source_hashes'].items():assert sha(ROOT/n)==h
  for n,h in spec['tool_hashes'].items():assert sha(n)==h
  assert primary=={n:sha(ledger/n) for n in primary}
  peer=Path('/workspace/team/runs/fpga_teammate/serial_framing_synthesis_full156_20261007_v1');assert sha(peer/'RUN_SPEC.json')=='dbce8beb5342fe590078dd8eafb29a4d762575a58db2599cab9942f453331c4b'
  for n,h in read(peer/'RUN_SPEC.json')['source_hashes'].items():assert sha(peer/n)==h
  save(results/('protection_'+str(guards)+'.json'),dict(resource=read(a.resource_check),source_held=True,peer120_held=True,tool_scripts_held=True,PRIMARY_held=True));guards+=1
 def command(argv,work,label,success=True):
  gate();record=bounded.run(argv,work,work/label,spec['tool_cap_s']);gate()
  assert record['normal_completion'] and record['exec_confirmed'] and record['leader_reaped'] and not record['remaining_group']
  assert (record['returncode']==0)==success,(label,record['returncode'])
  commands.append(dict(label=label,record=record));return (work/label/'stdout.bin').read_text(errors='replace')
 gate();fixtures=read(ROOT/'NATIVE_FIXTURES.json')['cases'];rows=[]
 for i,c in enumerate(fixtures):
  work=results/str(i);work.mkdir();source=work/'candidate.sv';source.write_text(c['candidate']);original=sha(source)
  log=command([spec['tools']['xvlog'],'--sv',str(source)],work,'C_compile',False)
  lines=[s for s in log.splitlines() if re.search('ERROR|WARNING|FATAL',s)];feedback='\n'.join(lines)[:2048] or log[-2048:]
  # No testbench is on disk before this invocation; no fixture name/path is passed.
  patch,receipt=internal_wire_repair.repair(source.read_text(),feedback);assert patch is not None and receipt['status']=='compiler_named_internal_wire_changed';assert sha(source)==original
  save(work/'ACTUAL_REPAIR.json',receipt);source.write_text(patch);patched=sha(source)
  tb=work/'tb.sv';tb.write_text(c['testbench']);tbsha=sha(tb)
  command([spec['tools']['xvlog'],'--sv',str(source),str(tb)],work,'P_compile')
  command([spec['tools']['xelab'],'tb','-s','wire_snapshot'],work,'P_elaborate')
  sim=command([spec['tools']['xsim'],'wire_snapshot','-runall'],work,'P_simulate')
  markers=re.findall(r'WIRE_NATIVE_PASS\s+(\d+)',sim);assert markers==[str(c['expected_observations'])] and 'MISMATCH' not in sim and 'Fatal:' not in sim
  assert sha(source)==patched and sha(tb)==tbsha
  row=dict(name=c['name'],passed=True,observations=c['expected_observations'],actual_compiler_feedback_sha256=receipt['feedback_sha256'],repair_input_received_no_TB_or_fixture_ID=True,original_sha256=original,patched_sha256=patched,testbench_sha256=tbsha);save(work/'CHECK.json',row);rows.append(row)
 assert guards==41 and len(commands)==20 and sum(r['observations'] for r in rows)==2122
 assert before_protected==protected.check(read(ROOT/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json'))
 result=dict(schema='internal_wire_independent_native20_v1',complete=True,passed=True,native_commands=20,physical_protection_receipts=41,finite_observations=2122,finite_clock_and_width_scope=True,all_parameter_or_all_clock_proof=False,model_calls=0,scoring_calls=0,old22_and_engineering8_not_replayed=True,protected141_groups_unchanged=True,peer120_sources_held=True,source_manifest_held=True,elapsed_native_child_s=time.monotonic()-started,score_measured=False,adoption=False,goal_achieved=False,rows=rows,commands=commands)
 save(results/'summary.json',result);print(json.dumps({k:v for k,v in result.items() if k not in ('rows','commands')}))
if __name__=='__main__':main()
