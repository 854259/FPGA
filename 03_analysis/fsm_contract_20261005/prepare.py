"""Freeze native-only FSM contract calibration after pure preflight."""
import datetime,hashlib,json,subprocess,sys,zipfile
from pathlib import Path
R=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,d):p.write_text(json.dumps(d,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
assert not (R/'RUN_SPEC.json').exists()
t=subprocess.run([sys.executable,'-B','-m','unittest','discover','-p','test_*.py','-v'],cwd=R,capture_output=True,text=True)
assert t.returncode==0,t.stdout+t.stderr
controls=json.loads((R/'CONTROL_PREPARATION.json').read_text())
old=json.loads((R.parent/'shift_contract_20261005/RUN_SPEC.json').read_text())
env=json.loads((R.parent/'functional_full156_20261005/RUN_SPEC.json').read_text())
names=['fsm_contract.py','reserved_keywords.py','templates.py','test_fsm.py','test_schedule.py','prepare_controls.py','calibrate.py','collect_evidence.py','audit.py','guard_wrapper.py','prepare.py','INPUT_MANIFEST.json','CONTROL_PREPARATION.json']
names.extend(p.relative_to(R).as_posix() for p in sorted((R/'raw_evidence/inputs').rglob('*')) if p.is_file())
spec=dict(schema='fsm_contract_calibration_frozen_v1',identity='fsm_contract_20261005_v1',base_commit='485e91d',
    frozen_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),cloud_root='/workspace/team/runs/fpga_owner/fsm_contract_20261005_v1',
    kit=env['kit'],model=env['model'],model_pid=env['model_pid'],cases=controls['cases'],control_names=['positive','missing_hold','missing_output','wrong_condition','shifted_encoding','constant_zero'],
    expected_natural_candidates={'Prob143_fsm_onehot':'fail','Prob150_review2015_fsmonehot':'fail'},source_hashes={n:sha(R/n) for n in sorted(names)},
    dependencies_cloud=old['dependencies_cloud'],dependency_hashes=old['dependency_hashes'],timeout_s=1140,guard_stage_timeout_s=1200,slot_minutes=25,
    max_probe_executions=26,max_synth_executions=4,max_model_requests=0,
    acceptance='All six control exact mismatch counts on four contracts, all positive syntheses and true archived candidate checks; complete readonly audit needed. No model/agent answer generation or deployment.',
    limits=['Two known public archived candidates plus two constructed cases, not independent natural validation.',
        'Complete bounded combinational one-hot table prose; renamed roles, changed width, condition coverage and reserved/case boundaries; no task ID selection in parser.',
        'Vector form explicitly permits multiple active states: enumerate every state bit pattern and scalar input. Partial scalar form only enumerates valid one-hot states and all scalar inputs.',
        'Evaluation control DUTs never used as model input or production answers; parser only produces TB and observed failure facts.',
        'No model/EDA in ten pure tests including actual stage with 26 fake probes and four fake syntheses; fake native results are not evidence of RTL correctness.',
        'Running full156 and frozen edge assets, teammate/shared model/formal deployment unchanged; native stage waits whole-task FIFO.',
        'No repair/full score/hidden/five-sample/offline32GB proof; only complete real native audit can admit original-budget model research.'])
save(R/'RUN_SPEC.json',spec)
save(R/'PREPARATION_RECEIPT.json',dict(schema='fsm_contract_preparation_v1',run_spec_sha256=sha(R/'RUN_SPEC.json'),assets=len(names),pure_tests_passed=10,local_test_output=t.stdout+t.stderr,
    cases=4,model_calls=0,eda_calls=0,native_calibration_executed=False,independent_natural_tasks=0))
archive=R/'raw_evidence/preparation.zip'
with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
    for n in [*names,'RUN_SPEC.json','PREPARATION_RECEIPT.json']:z.write(R/n,n)
save(R/'PREPARATION_ARCHIVE.json',dict(archive_sha256=sha(archive),spec_sha256=sha(R/'RUN_SPEC.json'),assets=len(names)))
print(json.dumps(dict(archive_sha256=sha(archive),spec_sha256=sha(R/'RUN_SPEC.json'),assets=len(names),tests=10)))
