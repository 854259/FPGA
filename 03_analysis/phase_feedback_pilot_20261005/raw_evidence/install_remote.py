from pathlib import Path
import json,hashlib,subprocess,sys,zipfile,os
archive=Path('/workspace/team/runs/fpga_owner/phase_feedback_pilot_20261005_v1_preparation.zip');root=Path('/workspace/team/runs/fpga_owner/phase_feedback_pilot_20261005_v1');assert not root.exists()
assert hashlib.sha256(archive.read_bytes()).hexdigest()=='5c68183580c760bd5acdc08cdd5d456b590b650937eacf8f5b498752d4988a21'
with zipfile.ZipFile(archive) as z:
 spec=json.loads(z.read('RUN_SPEC.json'));assert hashlib.sha256(z.read('RUN_SPEC.json')).hexdigest()=='2539dcbc8ac9144a33b1d9a207361f0e695725c1788add314a653c8d71484ae5'
 assert set(z.namelist())==set(spec['source_hashes'])|{'RUN_SPEC.json','PREPARATION_RECEIPT.json'}
 for n,h in spec['source_hashes'].items():
  assert not Path(n).is_absolute() and '..' not in Path(n).parts and hashlib.sha256(z.read(n)).hexdigest()==h,n
 root.mkdir();z.extractall(root)
def protected():
 kit=Path(spec['kit']);m=json.loads((root/'INPUT_MANIFEST.json').read_text())
 for key,base in [('input_sha256',kit/'bench/tasks_veval'),('official_sha256',kit/'official_reference')]:
  for n,h in m[key].items():assert hashlib.sha256((base/n).read_bytes()).hexdigest()==h,n
 for n,h in spec['dependency_hashes'].items():assert hashlib.sha256((Path(spec['dependencies_cloud'])/n).read_bytes()).hexdigest()==h,n
 return dict(input_files=len(m['input_sha256']),official_files=len(m['official_sha256']))
x=Path('/proc/2013333/stat').read_text().rsplit(')',1)[1].split();assert x[0] not in ('Z','X') and x[19]=='823869819'
before=protected()
result=subprocess.run([sys.executable,'-B','-m','unittest','test_fresh','test_edge_integration','test_boundaries','test_metrics','test_replay','test_stage','test_environment','test_phase','-v'],cwd=root,text=True,encoding='utf-8',capture_output=True,timeout=30)
assert result.returncode==0 and 'Ran 36 tests' in result.stderr,result.stdout+result.stderr
for n,h in spec['source_hashes'].items():assert hashlib.sha256((root/n).read_bytes()).hexdigest()==h,n
assert protected()==before
os.environ['VIVADO_BIN']='/workspace/AMD/2026.1/Vivado/bin';os.environ['LD_LIBRARY_PATH']='/workspace/team/udev-stub';os.environ['PATH']='/workspace/AMD/2026.1/Vivado/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
sys.path.insert(0,str(root));import pilot
environment=pilot.validate_environment()
receipt=dict(spec_sha256='2539dcbc8ac9144a33b1d9a207361f0e695725c1788add314a653c8d71484ae5',archive_sha256='5c68183580c760bd5acdc08cdd5d456b590b650937eacf8f5b498752d4988a21',assets=len(spec['source_hashes']),python=sys.version.split()[0],tests_passed=36,returncode=0,model_calls=0,eda_calls=0,source_unchanged=True,protected=before,actual_experiment_submitted=False,environment=environment,stdout=result.stdout,stderr=result.stderr)
(root/'LINUX_PREFLIGHT_RECEIPT.json').write_text(json.dumps(receipt,indent=2)+chr(10),encoding='utf-8');print(json.dumps(receipt))

tickets=[json.loads(p.read_text()) for p in Path("/workspace/team/task_fifo/tickets").glob("*.json")]
print(json.dumps(dict(recent_tickets=[dict(ticket=t["ticket"],task=t["task_name"],state=t["state"],cwd=t["cwd"]) for t in sorted(tickets,key=lambda t:t["ticket"])[-8:]])))
