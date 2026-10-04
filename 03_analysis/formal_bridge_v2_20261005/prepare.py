"""Freeze health-only successor without changing live/frozen packages."""
import ast,datetime,hashlib,json,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,d):p.write_text(json.dumps(d,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
assert not (ROOT/'RUN_SPEC.json').exists()
local=json.loads((ROOT/'LOCAL_PREFLIGHT.json').read_text());assert local['passed'] and local['tests_passed']==18 and local['linux_tests_skipped']==3
for p in ROOT.rglob('*.py'):
    if 'raw_evidence' not in p.parts:ast.parse(p.read_text(encoding='utf-8'))
integrity=json.loads((ROOT/'package/INTEGRITY.json').read_text())
for n,h in integrity['files'].items():assert sha(ROOT/'package'/n)==h,n
delta=json.loads((ROOT/'SOURCE_DELTA.json').read_text())
for n,h in delta['new_package_sha256'].items():assert sha(ROOT/'package'/n)==h,n
env=json.loads((ROOT.parent/'functional_full156_20261005/RUN_SPEC.json').read_text())
names=['prepare.py','stage.py','live_health.py','test_bridge.py','test_linux_bridge.py','test_health.py','test_linux_health.py','reproduce_health.py','guard_wrapper.py','INPUT_MANIFEST.json','SOURCE_REUSE.json','SOURCE_DELTA.json','LOCAL_PREFLIGHT.json','HEALTH_GAPS.json','MODEL_PROCESS_SNAPSHOT.json','UPSTREAM_REF_RECHECK.json','RESEARCH_API_GAPS.json']
names.extend(p.relative_to(ROOT).as_posix() for p in sorted((ROOT/'package').rglob('*')) if p.is_file() and '__pycache__' not in p.parts)
save(ROOT/'RUN_SPEC.json',{'schema':'formal_bridge_health_v2_frozen_v1','identity':'formal_bridge_v2_20261005_v1','base_commit':'9a6f7c9','frozen_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'cloud_root':'/workspace/team/runs/fpga_owner/formal_bridge_v2_20261005_v1','kit':env['kit'],'model':env['model'],'model_pid':env['model_pid'],'source_hashes':{n:sha(ROOT/n) for n in sorted(names)},'timeout_s':540,'guard_stage_timeout_s':600,'slot_minutes':15,'prerequisite_cloud':'/workspace/team/runs/fpga_owner/formal_bridge_20261005_v1','prerequisite_spec_sha256':'a9b4bb662902aba8b979fcee775960fa50c439b79b47d7808f7884b10e143aa3','max_actual_model_requests':0,'planned_actual_native_probes':0,'planned_actual_compile_commands':0,'planned_actual_synthesis_commands':0,'planned_vivado_version_commands':1,'acceptance':'Prior v1 source/terminal/guard success; 21 Linux tests including 200 fake solve requests, authenticated health and version-command owned descendants; actual staged GET health against unchanged shared model with real Vivado version and measured card attribution. Complete readonly audit still required.','limits':['This changes health instrumentation/binding only; original solver core, native adapter, parser, skill and official baseline bytes preserved.','Instantaneous endpoint-owned card counter is an upper bound on model use for that card; not process-exclusive memory or peak/R9700/32GB target certification.','Ambiguous/multiple/unknown GPU attribution returns null; submission readiness remains false if memory cannot be measured or is over the exact 32GiB boundary.','Two successful live health GETs and one real version query; no real model inference, synthesis or external judge.','Prior native parity only covers one constructed priority contract; shift/native family coverage and real model formal-API quality still pending.','No Docker build/image, offline proof, five independent generation, independent natural score or deployment; original queue30 and full/teammate/model remain unchanged.']})
save(ROOT/'PREPARATION_RECEIPT.json',{'run_spec_sha256':sha(ROOT/'RUN_SPEC.json'),'assets':len(names),'local_tests_passed':18,'linux_tests_skipped':3,'actual_model_requests':0,'actual_eda_calls':0,'linux_stage_executed':False})
archive=ROOT/'raw_evidence/preparation.zip'
with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
    for n in [*names,'RUN_SPEC.json','PREPARATION_RECEIPT.json']:z.write(ROOT/n,n)
save(ROOT/'PREPARATION_ARCHIVE.json',{'archive_sha256':sha(archive),'run_spec_sha256':sha(ROOT/'RUN_SPEC.json'),'assets':len(names)})
print((ROOT/'PREPARATION_ARCHIVE.json').read_text())
