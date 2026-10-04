"""Prepare separate immutable fresh bundle after successful boundary reconciliation."""
import datetime,hashlib,json,shutil,subprocess,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,d):p.write_text(json.dumps(d,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
old=ROOT.parent/'functional_fresh_pilot_v2_20261005'
new=ROOT.parent/'functional_fresh_pilot_v3_20261005'
assert not new.exists();new.mkdir()
proof=json.loads((ROOT/'RESULTS.json').read_text());assert proof['passed']
spec=json.loads((old/'RUN_SPEC.json').read_text())
save(old/'ADMISSION_REJECTION.json',dict(schema='fresh_v2_admission_rejection',spec_sha256=sha(old/'RUN_SPEC.json'),reason='R1 verified lexical false acceptances, repair before inference',old_false_accepts=4047,model_calls=0,eda_calls=0,submitted=False,boundary_report_sha256=sha(ROOT/'RESULTS.json')))
for n,h in spec['source_hashes'].items():
 p=old/n;assert sha(p)==h;npath=new/n;npath.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(p,npath)
for n in ['priority_contract.py','shift_contract.py','reserved_keywords.py']:shutil.copyfile(ROOT/n,new/n)
shutil.copyfile(ROOT/'RESULTS.json',new/'BOUNDARY_RECONCILIATION.json')
shutil.copyfile(old/'README.md',new/'README.md')
test=subprocess.run([sys.executable,'-B','-m','unittest','test_fresh','-v'],cwd=new,capture_output=True,text=True)
assert test.returncode==0,test.stdout+test.stderr
spec.update(schema='functional_fresh_pilot_frozen_v3',identity='functional_fresh_20261005_v3',cloud_root='/workspace/team/runs/fpga_owner/functional_fresh_pilot_20261005_v3',frozen_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),predecessor_rejected_spec_sha256=sha(old/'RUN_SPEC.json'),identifier_boundary_report_sha256=sha(ROOT/'RESULTS.json'))
spec['source_hashes']={n:sha(new/n) for n in sorted(set(spec['source_hashes'])|{'reserved_keywords.py','BOUNDARY_RECONCILIATION.json'})}
save(new/'RUN_SPEC.json',spec)
save(new/'PREPARATION_RECEIPT.json',dict(schema='functional_fresh_local_preparation_v3',source_spec_sha256=sha(new/'RUN_SPEC.json'),sources=len(spec['source_hashes']),worker_boundary_tests_passed=7,real_model_calls=0,real_eda_calls=0,prerequisites_audited=True,identifier_boundary_passed=True,stage='prepared_not_submitted',tests_use_frozen_prompt_only_fixtures=True))
archive=new/'raw_evidence/preparation.zip'
with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
 for n in [*spec['source_hashes'],'RUN_SPEC.json','PREPARATION_RECEIPT.json']:z.write(new/n,n)
save(new/'PREPARATION_ARCHIVE.json',dict(sha256=sha(archive),spec_sha256=sha(new/'RUN_SPEC.json'),assets=len(spec['source_hashes'])))
print(json.dumps(dict(root=str(new),spec_sha256=sha(new/'RUN_SPEC.json'),archive_sha256=sha(archive),tests=7)))
