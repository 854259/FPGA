"""Freeze complete-only readonly attribution tools, without inference or EDA."""
import datetime,hashlib,json,subprocess,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,d):p.write_text(json.dumps(d,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
assert not (ROOT/'DECISION_SPEC.json').exists()
t=subprocess.run([sys.executable,'-B','-m','unittest','discover','-p','test_*.py','-v'],cwd=ROOT,capture_output=True,encoding='utf-8')
assert t.returncode==0 and 'Ran 9 tests' in t.stderr and '\nOK\n' in t.stderr,t.stdout+t.stderr
files={'source/03_analysis/full156_decision_20261005/'+n:ROOT/n for n in ['decision.py','test_decision.py','prepare.py']}
full=ROOT.parent/'functional_full156_20261005';spec=json.loads((full/'RUN_SPEC.json').read_text(encoding='utf-8'))
assert sha(full/'RUN_SPEC.json')=='43ba0bb8da29e2ec9dd5cef5b3ae81173e5796973466c18f7f1ee34fff13bbb7'
for n in ['audit.py','RUN_SPEC.json']:
    if n!='RUN_SPEC.json':assert sha(full/n)==spec['source_hashes'][n]
    files['source/03_analysis/functional_full156_20261005/'+n]=full/n
save(ROOT/'DECISION_SPEC.json',{'schema':'full156_complete_attribution_tools_frozen_v1','frozen_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'base_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,encoding='utf-8').strip(),'cloud_root':'/workspace/team/runs/fpga_owner/full156_decision_tools_20261005_v1','source_hashes':{n:sha(p) for n,p in sorted(files.items())},'supported_run_spec_sha256':sha(full/'RUN_SPEC.json'),'pure_tests':9,'model_calls':0,'eda_calls':0,'actual_full_result_processed':False,'adoption':False,'limits':['Only accepts completed full156 audit and matching raw archive; no score filtering, new model or EDA calls.','Adds observed matched-draft native repair requirement and anomaly investigation to frozen quality gate; never relaxes regression/deadline/unconfirmed limits.','Synthetic parser fixtures are explicitly marked and rejected by production CLI.','No statistical interval computation, teammate T1 duplication, independent natural or five-sample certification.']})
save(ROOT/'LOCAL_PREFLIGHT.json',{'at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'tests_passed':9,'model_calls':0,'eda_calls':0,'actual_full_result_processed':False,'output':t.stdout+t.stderr,'decision_spec_sha256':sha(ROOT/'DECISION_SPEC.json')})
archive=ROOT/'raw_evidence/preparation.zip'
with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
    for n,p in sorted(files.items()):z.write(p,n)
    z.write(ROOT/'DECISION_SPEC.json','DECISION_SPEC.json');z.write(ROOT/'LOCAL_PREFLIGHT.json','LOCAL_PREFLIGHT.json')
save(ROOT/'PREPARATION_ARCHIVE.json',{'archive_sha256':sha(archive),'spec_sha256':sha(ROOT/'DECISION_SPEC.json'),'assets':len(files)})
print((ROOT/'PREPARATION_ARCHIVE.json').read_text())
