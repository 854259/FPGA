"""Freeze readonly audit tools plus exact source-only synthetic dependencies."""
import datetime,hashlib,json,subprocess,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,d):p.write_text(json.dumps(d,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
assert not (ROOT/'AUDIT_TOOL_SPEC.json').exists()
t=subprocess.run([sys.executable,'-B','-m','unittest','discover','-p','test_*.py','-v'],cwd=ROOT,capture_output=True,text=True)
assert t.returncode==0,t.stdout+t.stderr
assert 'Ran 10 tests' in t.stderr and '\nOK\n' in t.stderr
files={}
for n in ['collect.py','audit.py','fixture.py','test_audit.py','prepare.py']:files['source/03_analysis/formal_bridge_audit_20261005/'+n]=ROOT/n
helper=ROOT.parent/'full156_postflight_20261004/audit.py';assert sha(helper)=='6b141e6da0bac31fd2a3f00ed448f5f600eabe327eaa93594259d760f8d07ba3'
files['source/03_analysis/full156_postflight_20261004/audit.py']=helper
for folder in ['formal_bridge_20261005','formal_bridge_v2_20261005']:
    source=ROOT.parent/folder;spec=json.loads((source/'RUN_SPEC.json').read_text())
    for n,h in spec['source_hashes'].items():assert sha(source/n)==h,n
    for n in [*spec['source_hashes'],'RUN_SPEC.json','PREPARATION_RECEIPT.json']:files['source/03_analysis/'+folder+'/'+n]=source/n
save(ROOT/'AUDIT_TOOL_SPEC.json',{'schema':'readonly_formal_bridge_audit_tools_frozen_v1','frozen_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'base_commit':'364f737','cloud_root':'/workspace/team/runs/fpga_owner/formal_bridge_audit_tools_20261005_v1','source_hashes':{n:sha(p) for n,p in sorted(files.items())},'supported_run_specs':['a9b4bb662902aba8b979fcee775960fa50c439b79b47d7808f7884b10e143aa3','b98742b9694454c2dc41654a8bcb3668b7c2ee2066bb8dc85fa6009cc3e2eee3'],'model_calls':0,'eda_calls':0,'synthetic_preflight_tests':10,'actual_shipping_evidence_audited':False,'actual_execution_verified':False,'limits':['Only fixed v1/v2 source and native/health scopes; no quality score or deployment.','Synthetic fixture default admission denied; CLI cannot waive it. Tests use explicitly marked fixtures only.','Passed collection requires frozen run identity, terminal guard and no still-live recorded owned process. Failure capture is distinct and never accepted.','Archives include package inventory, raw requests/derived TB/log/receipt bindings and nested v1 prerequisite; 936/35 protected source identities checked, not benchmark reference/TB contents.','Collectors/auditors never launch inference/EDA or change live runs, queue, model, instance or teammates.']})
save(ROOT/'LOCAL_PREFLIGHT.json',{'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'tests_passed':10,'model_calls':0,'eda_calls':0,'actual_shipping_evidence_audited':False,'output':t.stdout+t.stderr,'audit_tool_spec_sha256':sha(ROOT/'AUDIT_TOOL_SPEC.json')})
archive=ROOT/'raw_evidence/preparation.zip'
with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
    for n,p in sorted(files.items()):z.write(p,n)
    z.write(ROOT/'AUDIT_TOOL_SPEC.json','AUDIT_TOOL_SPEC.json');z.write(ROOT/'LOCAL_PREFLIGHT.json','LOCAL_PREFLIGHT.json')
save(ROOT/'PREPARATION_ARCHIVE.json',{'archive_sha256':sha(archive),'spec_sha256':sha(ROOT/'AUDIT_TOOL_SPEC.json'),'assets':len(files)})
print((ROOT/'PREPARATION_ARCHIVE.json').read_text())
