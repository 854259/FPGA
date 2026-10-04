"""Freeze all156 whole-task regression; no inference/EDA or reference in worker."""
import datetime,hashlib,json,subprocess,sys,zipfile
from pathlib import Path
R=Path(__file__).resolve().parent
OLD=R.parent/'functional_fresh_pilot_v3_20261005'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,d):p.write_text(json.dumps(d,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
assert not (R/'RUN_SPEC.json').exists()
s=json.loads((OLD/'RUN_SPEC.json').read_text())
same=[]
for n,h in s['source_hashes'].items():
    if n in ['pilot.py','audit.py']:continue
    assert sha(R/n)==h,n;same.append(n)
tests=subprocess.run([sys.executable,'-B','-m','unittest','test_full','test_fresh','-v'],cwd=R,capture_output=True,text=True)
assert tests.returncode==0,tests.stdout+tests.stderr
manifest=json.loads((R/'INPUT_MANIFEST.json').read_text())
tasks=sorted({n.split('/')[0] for n in manifest['input_sha256']});assert len(tasks)==156 and len(manifest['input_sha256'])==936
extra=['FRESH_PILOT_AUDIT.json','metrics.py','replay.py','test_full.py','raw_evidence/test_fixtures/score.py','prepare.py','HISTORICAL_AUDIT_PREFLIGHT/RESULTS.json']
s.update(schema='functional_full156_frozen_v1',identity='functional_full156_20261005_v1',base_commit='23ed4d26b57db39fdf9161b53220f2d76f3d06ab',
    cloud_root='/workspace/team/runs/fpga_owner/functional_full156_20261005_v1',task_ids=tasks,
    frozen_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),stage_timeout_s=86400,slot_minutes=1470,
    max_actual_model_requests=624,max_functional_probe_executions=6,expected_samples=312,
    predecessor_fresh_spec_sha256=sha(OLD/'RUN_SPEC.json'),prerequisite_fresh6_archive_sha256='f85211565b0fd890cf648b8758e670a31a3417ede569066d981e42c287d70c8d',
    acceptance='312 complete actual fresh samples, 156-task denominator with pinned official summarize, no tools/unconfirmed/deadlines or coefficient regression; higher C mean or equal C mean with fewer model calls permits independent validation only. No automatic deployment.',
    frozen_inference_assets_identical_to_successful_pilot=same)
for key in ['predecessor_rejected_spec_sha256','predecessor_cloud_model_calls','predecessor_cloud_eda_calls']:s.pop(key,None)
s['limits']=[
    'All156 known public tasks, one actual independent first generation/arm, no hidden or five-sample claim.',
    'Parser runtime consumes prose not task IDs; static applicability only3 known public development tasks. Remaining153 preserve original flow.',
    'Budget/original skill/extraction/once repair unchanged from audited fresh pilot. No archived reply, fixed DUT answers or per-task scripted fix.',
    'Whole task FIFO; common guard holds own locks across312 and includes integrity overhead in both arms. Shared model/instance/formal deployment/teammate untouched.',
    '24-hour outer safety bound is not ETA; historical full312 4h34. Hard300s solve includes generation/compilation/feedback, real deadlines graded not resampled.',
    'Original successful declaration patch return preserved, optional functional check abstains on unknown/extra prose and system functions.',
    'External pinned Vivado judge and score receive official references; workers see prompt/interface and generated candidate diagnostics only.',
    'Temperature0 still permits differing first replies. Preserve identities, report paired whole set and byte-identical first-reply subset separately.',
    'Complete execution and quality qualification separate; no partial score, retries or best-sample replacement. Unconfirmed inference drains at most120s, shared model not killed.',
    'Full source/DUT/message/native/tool/cleanup audit required; historical six-sample audit preflight is not a full156 audit.',
    'Current W7900 dev hardware is not target single32GB offline/protocol certificate. Fresh official baseline gain and formal API/time rules unmeasured.'
]
s['source_hashes']={n:sha(R/n) for n in sorted(set(s['source_hashes'])|set(extra))}
save(R/'RUN_SPEC.json',s)
save(R/'PREPARATION_RECEIPT.json',dict(schema='functional_full156_preparation_v1',run_spec_sha256=sha(R/'RUN_SPEC.json'),sources=len(s['source_hashes']),task_count=156,expected_samples=312,
    local_tests_passed=12,local_test_output=tests.stdout+tests.stderr,model_calls=0,eda_calls=0,inference_assets_identical_to_audited_pilot=len(same),historical_audit_preflight_valid=True,full_stage_audit_not_executed=True))
archive=R/'raw_evidence/preparation.zip'
with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
    for n in [*s['source_hashes'],'RUN_SPEC.json','PREPARATION_RECEIPT.json']:z.write(R/n,n)
save(R/'PREPARATION_ARCHIVE.json',dict(archive_sha256=sha(archive),spec_sha256=sha(R/'RUN_SPEC.json'),assets=len(s['source_hashes'])))
print(json.dumps(dict(archive_sha256=sha(archive),spec_sha256=sha(R/'RUN_SPEC.json'),assets=len(s['source_hashes']),tests_passed=12)))
