"""Freeze harness-only preflight; no actual run spec/FIFO/model requests yet."""
import datetime,hashlib,json,subprocess,sys,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,d):p.write_text(json.dumps(d,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
assert not (ROOT/'TOOLS_SPEC.json').exists()
old=ROOT.parent/'formal_bridge_v2_20261005';original=json.loads((old/'RUN_SPEC.json').read_text(encoding='utf-8'))
for p in (ROOT/'package').rglob('*'):
    if p.is_file() and '__pycache__' not in p.parts:
        n=p.relative_to(ROOT).as_posix();assert sha(p)==original['source_hashes'][n],n
test=subprocess.run([sys.executable,'-B','-m','unittest','discover','-p','test_*.py','-v'],cwd=ROOT,capture_output=True,encoding='utf-8');assert test.returncode==0 and 'Ran 7 tests' in test.stderr and '\nOK\n' in test.stderr,test.stdout+test.stderr
names=['stage.py','measure.py','bind_run.py','freeze_tools.py','test_pilot.py','guard_wrapper.py','INPUT_MANIFEST.json','official_eval_guarded.py','request_audit/sitecustomize.py']
names.extend(p.relative_to(ROOT).as_posix() for p in sorted((ROOT/'package').rglob('*')) if p.is_file() and '__pycache__' not in p.parts)
spec={'schema':'formal_five_pilot_harness_frozen_v1','frozen_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'base_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,encoding='utf-8').strip(),'cloud_root':'/workspace/team/runs/fpga_owner/formal_five_pilot_tools_20261005_v1','source_hashes':{n:sha(ROOT/n) for n in sorted(names)},'local_pure_tests':7,'actual_model_requests':0,'actual_eda_calls':0,'actual_five_samples_generated':False,'fifo_submitted':False,'limits':['Three known public tasks, five fresh HTTP solves per task/mode, official baseline unchanged and external pinned judge; mean of all five, never best-of-five.','Only a preliminary interface/measurement stage, not full156 five-sample or independent natural/hidden validation, deployment or rank evidence.','CPython urllib.Request audit hook records exact outgoing body attempts without patching transport/response; received counts come from pinned worker trace, full raw model replies are not captured.','Submission health is instantaneous attributed development-card observation, not peak, hardware capacity, target R9700 single32GB or offline certificate.','No real run spec/submission until full156 and attribution quality gates plus both actual formal bridge/health readonly audits pass; model/instance/teammate and deployed package unchanged.','Guard/root source/input SHA gates and whole-task FIFO required. Failed/partial/unknown responses remain recorded, no retry or resampling to improve scores.']}
save(ROOT/'TOOLS_SPEC.json',spec);save(ROOT/'LOCAL_PREFLIGHT.json',{'tests_passed':7,'actual_model_requests':0,'actual_eda_calls':0,'actual_five_samples_generated':False,'output':test.stdout+test.stderr,'tools_spec_sha256':sha(ROOT/'TOOLS_SPEC.json')})
archive=ROOT/'raw_evidence/preparation.zip'
with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
    for n in [*names,'TOOLS_SPEC.json','LOCAL_PREFLIGHT.json']:z.write(ROOT/n,n)
save(ROOT/'PREPARATION_ARCHIVE.json',{'archive_sha256':sha(archive),'spec_sha256':sha(ROOT/'TOOLS_SPEC.json'),'assets':len(names)})
print((ROOT/'PREPARATION_ARCHIVE.json').read_text())
