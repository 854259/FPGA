
from pathlib import Path
import ctypes,hashlib,importlib.util,json,os,sys,time,traceback,zipfile
ROOT=Path(__file__).resolve().parent;ORIGINAL=Path('/workspace/team/runs/fpga_owner/serial_timer_native_20261007_v2')
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();read=lambda p:json.loads(Path(p).read_bytes())
def save(p,j):
 with Path(p).open('x',encoding='utf-8') as out:json.dump(j,out,indent=2);out.write('\n')
manifest=read(ROOT/'SOURCE_MANIFEST.json')
def sources():return {n:sha(ROOT/n) for n in manifest}
namespace={};exec(compile((ROOT/'protected_prefix.py').read_bytes(),'original_native_protection','exec'),namespace);base_protect=namespace['protect']
def protect():
    original=base_protect()
    s=importlib.util.spec_from_file_location('current_terminal_sources',ROOT/'dependencies/protected_sources.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
    current=m.check(read(ROOT/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json'))
    assert len(current['groups'])==111 and current['source_assets']==7556
    spec=read(ORIGINAL/'RUN_SPEC.json')
    assert sha(ORIGINAL/'RUN_SPEC.json')=='141f5ecf638751d37f77c6c72aa61cf4cdef5cc3c2948657906a880c8eafa778'
    assert sha(ORIGINAL/'guard_wrapper.py')==spec['source_hashes']['guard_wrapper.py']
    gs=importlib.util.spec_from_file_location('original_serial_guard',ORIGINAL/'guard_wrapper.py');gm=importlib.util.module_from_spec(gs);gs.loader.exec_module(gm)
    kit=gm.protected(Path(spec['kit']));assert kit==spec['protected']
    assert original['primary']=={'STATUS.md':'779b5966af1b2a1a0475f29a2eaa6b9543e3dd44ef3b0f932ce33e5306762465','SNAPSHOT.json':'2463e95c74c49bdce0b41281da1b4f70e269468fd0caeae7a0d7ddac71a8e870'}
    return dict(original=original,current=current,kit=kit)

result=dict(schema='serial107_original_finite_native_terminal_review_v1',complete=False,passed=False,error=None,model_calls=0,eda_calls=0,new_native_commands=0,new_scoring_runs=0,new_fifo=False,processes={})
started=time.monotonic()
try:
 assert sys.platform=='linux' and sys.version_info[:2]==(3,12) and sys.dont_write_bytecode and sha('/usr/bin/python3')=='8295ee25cfdb239f3e165afceda7f46de73e2b606ff0e2e3d8623e3facd30acc'
 assert sources()==manifest and ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)==0
 result['protected_before']=protect();spec=read(ORIGINAL/'RUN_SPEC.json');assert sha(ORIGINAL/'RUN_SPEC.json')=='141f5ecf638751d37f77c6c72aa61cf4cdef5cc3c2948657906a880c8eafa778' and len(spec['source_hashes'])==117
 for n,h in spec['source_hashes'].items():assert sha(ORIGINAL/n)==h
 ticket=read(Path('/workspace/team/task_fifo/tickets/00000107.json'));assert ticket['state']=='completed' and ticket['returncode']==0 and ticket['cwd']==str(ORIGINAL)
 for role in ('runner','child'):
  i=ticket[role];p=Path('/proc')/str(i['pid'])
  if p.exists():
   v=(p/'stat').read_text().rsplit(')',1)[1].split();assert v[19]!=i['starttime'] or v[0] in ('Z','X')
 report=read(ORIGINAL/'results/summary.json');guard=read(ORIGINAL/'guard/status.json')
 assert report['complete'] and report['passed'] and report['actual_model_requests']==0 and report['actual_native_commands']==36 and report['actual_observations']==13800 and report['guard_receipts']==73
 assert guard['complete'] and guard['passed'] and guard['owned_cleanup']['verified'] and not guard['owned_cleanup']['remaining'] and guard['own_slot_released'] and guard['model_unchanged'] and guard['protected_files_unchanged']
 import terminal_gate
 terminal_gate.require_terminal(ticket,report,guard,prior_attempt=(ORIGINAL/'ORIGINAL_AUDIT_INTENT.json').exists() or (ROOT/'ORIGINAL_AUDIT_RESULT.json').exists() or (ROOT/'processes/original_auditor').exists())
 for p in Path('/proc').glob('[0-9]*'):
  try:
   v=(p/'stat').read_text().rsplit(')',1)[1].split();cmd=(p/'cmdline').read_bytes()
   if v[0] not in ('Z','X'):assert str(ORIGINAL/'sources/audit.py').encode() not in cmd
  except OSError:pass
 (ROOT/'processes').mkdir(exist_ok=False)
 assert sha(ORIGINAL/'sources/owned_exec.py')=='9981c3a36183787d559aaed73fcfd34d36e6a7354e5da1874cf5308c6ee476c5'
 sys.path.insert(0,str(ORIGINAL/'sources'));import owned_exec
 argv=[sys.executable,'-B',str(ORIGINAL/'sources/audit.py'),'--root',str(ORIGINAL),'--out',str(ROOT/'ORIGINAL_AUDIT_RESULT.json')]
 save(ORIGINAL/'ORIGINAL_AUDIT_INTENT.json',dict(argv=argv,namespace=str(ROOT),spec_sha256=sha(ORIGINAL/'RUN_SPEC.json'),retry='Read original intent/process/result only; never repeat original audit'))
 rec=owned_exec.run(argv,ROOT,ROOT/'processes/original_auditor',60);result['processes']['original_auditor']=rec;save(ROOT/'ORIGINAL_AUDITOR_PROCESS.json',rec)
 assert rec['normal_completion'] and rec['leader_reaped'] and not rec['remaining_group'] and rec['returncode']==0
 audit=read(ROOT/'ORIGINAL_AUDIT_RESULT.json');assert audit['schema']=='serial_timer_binary_event_native_original_audit_v1' and audit['evidence_valid'] and audit['native_qualified']
 assert audit['controls']==12 and audit['positive_cases']==8 and audit['negative_mutants']==4 and audit['native_commands']==36 and audit['guard_receipts']==73 and audit['observations']==13800 and audit['model_calls']==0 and not audit['full_score_measured'] and not audit['goal_qualified'] and not audit['adoption']
 result['original_audit_sha256']=sha(ROOT/'ORIGINAL_AUDIT_RESULT.json');result['native_qualified']=True;result['full_score_measured']=False;result['goal_qualified']=False
 selected={}
 def add(label,p):
  if p.is_file():selected[label]=p
 for n in spec['source_hashes']:add('run/'+n,ORIGINAL/n)
 for n in ('RUN_SPEC.json','SUBMISSION.json','STAGE_STATUS.json','results/summary.json'):add('run/'+n,ORIGINAL/n)
 for p in (ORIGINAL/'guard').rglob('*'):
  if p.is_file():add('run/'+p.relative_to(ORIGINAL).as_posix(),p)
 for p in (ORIGINAL/'results/guard_receipts').glob('*.json'):add('run/'+p.relative_to(ORIGINAL).as_posix(),p)
 for unit in (ORIGINAL/'results').iterdir():
  if not unit.is_dir() or unit.name=='guard_receipts':continue
  for p in unit.iterdir():
   if p.is_file():add('run/'+p.relative_to(ORIGINAL).as_posix(),p)
  for name in ('xvlog','xelab','xsim'):
   for p in (unit/name).rglob('*'):
    if p.is_file():add('run/'+p.relative_to(ORIGINAL).as_posix(),p)
 add('fifo/00000107.json',Path('/workspace/team/task_fifo/tickets/00000107.json'))
 for p in ROOT.rglob('*'):
  if p.is_file() and p.name not in ('runner_boot.stdout','runner_boot.stderr'):add('terminal/'+p.relative_to(ROOT).as_posix(),p)
 hashes={n:sha(p) for n,p in selected.items()};archive=ROOT/'terminal_native_v1.zip'
 archive_manifest=dict(schema='original_serial107_finite_native_terminal_archive_v1',files=hashes,spec_sha256=sha(ORIGINAL/'RUN_SPEC.json'),audit_sha256=result['original_audit_sha256'],model_calls=0,eda_calls=0,new_native_commands=0,new_scoring_runs=0,new_fifo=False)
 with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
  for n,p in selected.items():assert sha(p)==hashes[n];z.write(p,n)
  z.writestr('ARCHIVE_MANIFEST.json',json.dumps(archive_manifest,indent=2)+'\n')
 with zipfile.ZipFile(archive) as z:
  assert len(z.namelist())==len(set(z.namelist()))==len(hashes)+1
  for n,h in hashes.items():assert hashlib.sha256(z.read(n)).hexdigest()==h
 result['archive_sha256']=sha(archive);result['archive_bytes']=archive.stat().st_size;result['archive_members']=len(hashes)+1
 result['protected_after']=protect();assert result['protected_after']==result['protected_before'] and sources()==manifest
 result['passed']=True
except BaseException as e:
 result['error']=type(e).__name__+': '+str(e);(ROOT/'FAILURE_TRACEBACK.txt').write_text(traceback.format_exc())
finally:
 result['complete']=True;result['elapsed_s']=time.monotonic()-started;save(ROOT/'TERMINAL_REVIEW_RECEIPT.json',result)
print(json.dumps({k:result.get(k) for k in ('complete','passed','error','original_audit_sha256','native_qualified','archive_sha256','archive_bytes','archive_members')}));sys.exit(0 if result['passed'] else 1)
