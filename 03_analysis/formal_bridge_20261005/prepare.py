"""Freeze staged bridge assets; never change the running research package."""
import ast,datetime,hashlib,json,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,d):p.write_text(json.dumps(d,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
assert not (ROOT/'RUN_SPEC.json').exists()
local=json.loads((ROOT/'LOCAL_PREFLIGHT.json').read_text())
assert local['passed'] and local['tests_passed']==12 and local['linux_tests_skipped']==2
for p in ROOT.rglob('*.py'):
    if 'raw_evidence' not in p.parts:ast.parse(p.read_text(encoding='utf-8'))
integrity=json.loads((ROOT/'package/INTEGRITY.json').read_text())
for n,h in integrity['files'].items():assert sha(ROOT/'package'/n)==h,n
env=json.loads((ROOT.parent/'functional_full156_20261005/RUN_SPEC.json').read_text())
names=['prepare.py','stage.py','native_parity.py','test_bridge.py','test_linux_bridge.py','guard_wrapper.py','INPUT_MANIFEST.json','SOURCE_REUSE.json','LOCAL_PREFLIGHT.json','RESEARCH_API_GAPS.json','MODEL_PROCESS_SNAPSHOT.json','UPSTREAM_REF_RECHECK.json']
names.extend(p.relative_to(ROOT).as_posix() for p in sorted((ROOT/'package').rglob('*')) if p.is_file() and '__pycache__' not in p.parts)
save(ROOT/'RUN_SPEC.json',{'schema':'formal_bridge_frozen_v1','identity':'formal_bridge_20261005_v1','base_commit':'7eb1d69','frozen_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'cloud_root':'/workspace/team/runs/fpga_owner/formal_bridge_20261005_v1','kit':env['kit'],'model':env['model'],'model_pid':env['model_pid'],'source_hashes':{n:sha(ROOT/n) for n in sorted(names)},'timeout_s':540,'guard_stage_timeout_s':600,'slot_minutes':15,'max_actual_model_requests':0,'planned_actual_native_probes':4,'planned_actual_compile_commands':2,'planned_actual_synthesis_commands':0,'acceptance':'14 Linux tests including 200 fake HTTP requests and owned descendant timeout cleanup; real Vivado negative/positive parity on one constructed priority contract, followed by complete readonly audit. No deployment or quality score.','limits':['Llama.cpp /slots telemetry required, np=1 ctx16384; bridge does not claim generic inference compatibility.','Production core/parser/skills/baseline copied byte-for-byte from pinned research candidate; callback packaging/process supervision new and requires its own evidence.','Native parity uses 2 fake loopback model replies, 2 bridge probes and 2 legacy probes plus 2 compiles; no real inference/synthesis/external judge.','Constructed 4-bit renamed priority contract is not independent natural validation or shift-family native bridge parity.','No Docker image/build, target R9700, offline single32GB, five independent samples, same-round official baseline or competition rank certificate.','Existing deployment, dataset, research live run, shared model and teammate work unchanged; whole-task FIFO admission.']})
save(ROOT/'PREPARATION_RECEIPT.json',{'run_spec_sha256':sha(ROOT/'RUN_SPEC.json'),'assets':len(names),'local_tests_passed':12,'linux_tests_skipped':2,'actual_model_requests':0,'actual_eda_calls':0,'linux_stage_executed':False})
archive=ROOT/'raw_evidence/preparation.zip'
with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
    for n in [*names,'RUN_SPEC.json','PREPARATION_RECEIPT.json']:z.write(ROOT/n,n)
save(ROOT/'PREPARATION_ARCHIVE.json',{'archive_sha256':sha(archive),'run_spec_sha256':sha(ROOT/'RUN_SPEC.json'),'assets':len(names)})
print((ROOT/'PREPARATION_ARCHIVE.json').read_text())
