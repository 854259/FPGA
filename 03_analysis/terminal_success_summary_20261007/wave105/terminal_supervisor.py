"""Original full156 collector/auditor once; no scoring or source changes."""
from pathlib import Path
import ctypes,hashlib,importlib.util,json,os,signal,subprocess,sys,time,traceback,zipfile
import full_budget
WHOLE_STARTED=full_budget.start(450)
ROOT=Path(__file__).resolve().parent
ORIGINAL=Path('/workspace/team/runs/fpga_owner/waveform_first_request_full156_20261007_v1')
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
read=lambda p:json.loads(Path(p).read_bytes())
def save(p,j):
 with Path(p).open('x',encoding='utf-8') as f:json.dump(j,f,indent=2);f.write('\n')
manifest=read(ROOT/'SOURCE_MANIFEST.json')
def sources():
 return {n:sha(ROOT/n) for n in manifest}
namespace={};exec(compile((ROOT/'protected_prefix.py').read_bytes(),'reused_legacy_guard','exec'),namespace);legacy_protect=namespace['protect']
def protect():
 b=legacy_protect()
 assert b['primary']=={'STATUS.md':'779b5966af1b2a1a0475f29a2eaa6b9543e3dd44ef3b0f932ce33e5306762465','SNAPSHOT.json':'2463e95c74c49bdce0b41281da1b4f70e269468fd0caeae7a0d7ddac71a8e870'}
 ps=importlib.util.spec_from_file_location('wave105_current_protection',ROOT/'dependencies/protected_sources.py');pm=importlib.util.module_from_spec(ps);ps.loader.exec_module(pm)
 current=pm.check(read(ROOT/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json'));assert len(current['groups'])==115 and current['source_assets']==7591
 s=read(ORIGINAL/'RUN_SPEC.json');assert sha(ORIGINAL/'guard_wrapper.py')==s['source_hashes']['guard_wrapper.py']
 gs=importlib.util.spec_from_file_location('wave105_original_guard',ORIGINAL/'guard_wrapper.py');gm=importlib.util.module_from_spec(gs);gs.loader.exec_module(gm)
 kit=gm.protected(Path(s['kit']));assert kit==s['protected']
 return dict(legacy=b,current=current,kit=kit)

def peer_protect():
 unit=Path('/workspace/team/runs/fpga_teammate/waveform_first_request_cp6_20261006_v4')
 assert sha(unit/'RUN_SPEC.json')=='216637107d75156c6ad4c1db13656e6ea94f7fce225a8df9da03b7b2f6db25cb'
 spec=read(unit/'RUN_SPEC.json');assert len(spec['source_hashes'])==97
 for n,h in spec['source_hashes'].items():assert sha(unit/n)==h
 return dict(spec_sha256=sha(unit/'RUN_SPEC.json'),source_hashes=spec['source_hashes'])
result=dict(schema='wave105_original_full156_terminal_review_v1',complete=False,passed=False,error=None,model_calls=0,eda_calls=0,new_scoring_runs=0,new_fifo=False,processes={})
start=WHOLE_STARTED
try:
 assert str(ROOT)=='/workspace/team/runs/fpga_owner/waveform_first_request_full156_20261007_v1_terminal_review_v2'
 assert sys.platform=='linux' and sys.version_info[:2]==(3,12) and sys.dont_write_bytecode
 assert sha('/usr/bin/python3')=='8295ee25cfdb239f3e165afceda7f46de73e2b606ff0e2e3d8623e3facd30acc'
 assert sources()==manifest and ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)==0
 pid=os.getpid();d=Path('/proc')/str(pid);v=(d/'stat').read_text().rsplit(')',1)[1].split();save(ROOT/'SUPERVISOR_IDENTITY.json',dict(pid=pid,starttime=v[19],command_sha256=sha(d/'cmdline')))
 result['protected_before']=protect();result['peer104_before']=peer_protect();assert sha(ORIGINAL/'RUN_SPEC.json')=='d3b4b69f85e358c749954c12509908172a74663a83c4739a57d0c26cec5f5c5e'
 spec=read(ORIGINAL/'RUN_SPEC.json');assert len(spec['source_hashes'])==109
 for n,h in spec['source_hashes'].items():assert sha(ORIGINAL/n)==h
 ticket=read(Path('/workspace/team/task_fifo/tickets/00000105.json'));assert ticket['state']=='completed' and ticket['cwd']==str(ORIGINAL) and ticket['returncode']==0
 for key in ('runner','child'):
  i=ticket[key];d=Path('/proc')/str(i['pid'])
  if d.exists():
   v=(d/'stat').read_text().rsplit(')',1)[1].split();assert v[19]!=i['starttime'] or v[0] in ('Z','X')
 report=read(ORIGINAL/'results/summary.json');guard=read(ORIGINAL/'guard/status.json');assert report['complete'] and report['passed'] and len(report['rows'])==312 and 312 <= report['actual_model_requests'] <= spec['max_actual_model_requests'] == 624 and guard['complete'] and guard['passed']
 assert guard['owned_cleanup']['verified'] and guard['owned_cleanup']['remaining']==[] and guard['own_slot_released'] and guard['model_unchanged'] and guard['protected_files_unchanged']
 for d in Path('/proc').glob('[0-9]*'):
  try:
   v=(d/'stat').read_text().rsplit(')',1)[1].split();cmd=(d/'cmdline').read_bytes()
   if v[0] not in ('Z','X'):assert not any(str(ORIGINAL/n).encode() in cmd for n in ('collect_evidence.py','audit.py'))
  except (FileNotFoundError,ProcessLookupError):pass
 executor=dict(Path=Path,hashlib=hashlib,json=json,os=os,signal=signal,subprocess=subprocess,sys=sys,time=time,
   root=ROOT,original=ORIGINAL,spec=spec,manifest={'source_hashes':manifest,'python_sha256':sha('/usr/bin/python3')},sources=sources,sha=sha,save=save)
 exec(compile((ROOT/'terminal_process_functions.py').read_bytes(),'original_fsm96_terminal_process_functions','exec'),executor)
 execute=executor['execute']
 archive=ROOT/'terminal_v1.zip';assert not archive.exists() and not (ROOT/'audit').exists()
 assert report['schema']=='waveform_first_request_full156_measurement_v1' and report['spec_sha256']==sha(ORIGINAL/'RUN_SPEC.json') and report.get('error') is None
 assert not (ORIGINAL/'ORIGINAL_TERMINAL_AUDIT_INTENT.json').exists() and not (ROOT/'processes').exists()
 save(ORIGINAL/'ORIGINAL_TERMINAL_AUDIT_INTENT.json',dict(observer=str(ROOT),spec_sha256=sha(ORIGINAL/'RUN_SPEC.json'),collector_sha256=sha(ORIGINAL/'collect_evidence.py'),auditor_sha256=sha(ORIGINAL/'audit.py'),retry='Read same original intent/process/result only; never repeat collector or auditor'))
 for label,argv in [('collector',[sys.executable,'-B',str(ORIGINAL/'collect_evidence.py'),'--root',str(ORIGINAL),'--guard',str(ORIGINAL/'guard'),'--archive',str(archive)]),('auditor',[sys.executable,'-B',str(ORIGINAL/'audit.py'),'--archive',str(archive),'--out',str(ROOT/'audit'),'--spec-sha',sha(ORIGINAL/'RUN_SPEC.json')])]:
  assert sha(argv[2])==spec['source_hashes'][Path(argv[2]).name]
  rec=execute(label,argv,180);result['processes'][label]=rec;save(ROOT/(label+'_OWNED_PROCESS.json'),rec)
  assert rec['returncode']==0 and not rec['timeout'] and rec['error'] is None and not rec['remaining_group'] and not rec['group_signals'] and rec['source_unchanged']
  assert sources()==manifest and protect()==result['protected_before'] and peer_protect()==result['peer104_before']
  if label=='collector':
   result['archive_sha256']=sha(archive);result['archive_bytes']=archive.stat().st_size
   with zipfile.ZipFile(archive) as z:
    m=json.loads(z.read('ARCHIVE_MANIFEST.json'));assert len(z.namelist())==len(set(z.namelist()))==len(m['files'])+1 and m['run_spec_sha256']==sha(ORIGINAL/'RUN_SPEC.json') and m['collector_sha256']==sha(ORIGINAL/'collect_evidence.py')
    assert m['collector_model_calls']==m['collector_eda_calls']==0
    for n,h in m['files'].items():assert hashlib.sha256(z.read(n)).hexdigest()==h
    result['archive_members']=len(z.namelist())
 audited=read(ROOT/'audit/RESULTS.json');assert audited['schema']=='waveform_first_request_full156_readonly_audit_v1' and audited['evidence_valid'] and audited['full156_evidence_valid'] and audited['full_score_measured']
 assert audited['archive_sha256']==result['archive_sha256'] and audited['spec_sha256']==sha(ORIGINAL/'RUN_SPEC.json') and audited['auditor_sha256']==sha(ORIGINAL/'audit.py')
 assert audited['expected_samples']==312 and audited['actual_model_requests']==report['actual_model_requests'] and audited['audit_model_calls']==audited['audit_eda_calls']==0
 result['audit_sha256']=sha(ROOT/'audit/RESULTS.json');result['qualified_for_goal']=audited['qualified_for_goal'];result['protected_after']=protect();assert result['protected_before']==result['protected_after'] and sources()==manifest
 result['peer104_after']=peer_protect();assert result['peer104_before']==result['peer104_after']
 result['passed']=True
except BaseException as e:
 result['error']=type(e).__name__+': '+str(e);(ROOT/'FAILURE_TRACEBACK.txt').write_text(traceback.format_exc())
finally:
 budget=full_budget.finish();result['outer_budget']=budget
 if budget['working_deadline_expired'] or not budget['within_complete_budget']:
  result['passed']=False;result['error']=result['error'] or 'Complete terminal budget exceeded'
 result['complete']=True;result['elapsed_s']=time.monotonic()-start;save(ROOT/'TERMINAL_REVIEW_RECEIPT.json',result)
print(json.dumps({k:result.get(k) for k in ('complete','passed','error','archive_sha256','archive_bytes','archive_members','audit_sha256','qualified_for_goal','elapsed_s')}));sys.exit(0 if result['passed'] else 1)
