"""Freeze native-only edge contract calibration after pure preflight."""
import datetime,hashlib,json,subprocess,sys,zipfile
from pathlib import Path
R=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,d):p.write_text(json.dumps(d,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
assert not (R/'RUN_SPEC.json').exists()
t=subprocess.run([sys.executable,'-B','-m','unittest','test_edge','-v'],cwd=R,capture_output=True,text=True)
assert t.returncode==0,t.stdout+t.stderr
controls=json.loads((R/'CONTROL_PREPARATION.json').read_text())
old=json.loads((R.parent/'shift_contract_20261005/RUN_SPEC.json').read_text())
env=json.loads((R.parent/'functional_full156_20261005/RUN_SPEC.json').read_text())
names=['edge_contract.py','reserved_keywords.py','test_edge.py','prepare_controls.py','calibrate.py','collect_evidence.py','audit.py','guard_wrapper.py','prepare.py','INPUT_MANIFEST.json','CONTROL_PREPARATION.json']
names.extend(p.relative_to(R).as_posix() for p in sorted((R/'raw_evidence/inputs').rglob('*')) if p.is_file())
spec=dict(schema='edge_contract_calibration_frozen_v1',identity='edge_contract_20261005_v1',base_commit='9350966',
    frozen_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),cloud_root='/workspace/team/runs/fpga_owner/edge_contract_20261005_v1',
    kit=env['kit'],model=env['model'],model_pid=env['model_pid'],cases=controls['cases'],control_names=['positive','opposite_edge','combinational','extra_delay','wrong_direction','constant_zero'],
    expected_natural_candidates={'Prob045_edgedetect2':'fail','Prob054_edgedetect':'fail'},source_hashes={n:sha(R/n) for n in sorted(names)},
    dependencies_cloud=old['dependencies_cloud'],dependency_hashes=old['dependency_hashes'],timeout_s=1140,guard_stage_timeout_s=1200,slot_minutes=25,
    max_probe_executions=26,max_synth_executions=6,max_model_requests=0,
    acceptance='All six control exact mismatch counts on four contracts, all positive syntheses and true archived candidate checks; complete readonly audit needed. No model/agent answer generation or deployment.',
    limits=['Two known archived public development tasks plus two constructed cases, not independent natural validation.',
        'Full bounded edge-pulse prose, sampled individual/parallel transitions and holding; no reset/initial state invented; two zero samples establish normal one-cycle history.',
        'Wrong extra-delay history remains initially unknown in software control model, including actual initial X-to-zero clock transition.',
        '045 explicitly positive edge includes active-edge and end-cycle observations;054 omits edge and both positive/negative-edge correct controls must pass.',
        'No official references or TB read by parser/controls; evaluation control DUTs never used as agent answers or model input.',
        'Running full156 frozen source/teammate/shared model/formal deployment unchanged. Native stage waits its whole-task FIFO turn.',
        'No repair/quality-cost/full score or hidden/five-sample/offline32GB claim; meaningful fresh model research only after native calibration audit.'])
save(R/'RUN_SPEC.json',spec)
save(R/'PREPARATION_RECEIPT.json',dict(schema='edge_contract_preparation_v1',run_spec_sha256=sha(R/'RUN_SPEC.json'),assets=len(names),pure_tests_passed=6,local_test_output=t.stdout+t.stderr,
    cases=4,model_calls=0,eda_calls=0,native_calibration_executed=False,independent_natural_tasks=0))
archive=R/'raw_evidence/preparation.zip'
with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
    for n in [*names,'RUN_SPEC.json','PREPARATION_RECEIPT.json']:z.write(R/n,n)
save(R/'PREPARATION_ARCHIVE.json',dict(archive_sha256=sha(archive),spec_sha256=sha(R/'RUN_SPEC.json'),assets=len(names)))
print(json.dumps(dict(archive_sha256=sha(archive),spec_sha256=sha(R/'RUN_SPEC.json'),assets=len(names),tests=6)))
