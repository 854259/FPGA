"""Freeze all original-harness controls before real native execution; no solver calls."""
from pathlib import Path
import ast,datetime,hashlib,json,subprocess,sys,zipfile
R=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text(encoding='utf-8'))
def save(p,d):p.write_bytes((json.dumps(d,ensure_ascii=False,indent=2)+'\n').encode())
if __name__=='__main__':
    assert not (R/'RUN_SPEC.json').exists()
    private=read(R/'raw_evidence/CONTROLS.json');bindings=read(R/'raw_evidence/DEPENDENCY_BINDINGS.json')
    assert len(private['cases'])==3 and sum(len(c['controls'])*c['expected_pytest_tests'] for c in private['cases'])==50
    assert sha(R/'raw_evidence/ORIGINAL_DATASET.jsonl')=='cbcd81295561ebb16e4d857e096f4d9908d042c33aff3b58abf236e868411857'
    for case in private['cases']:
        labels=[c['label'] for c in case['controls']]
        assert labels==['positive','constant_zero','constant_one','identity']+(['valid_zero'] if 'gray_to_binary' in case['record_id'] else [])+['failure_propagation']
        assert case['expected_pytest_tests'] in (1,3,5)
    sources=['stage.py','tool_journal.py','collect.py','audit.py','prepare.py','guard_wrapper.py','INPUT_MANIFEST.json',
        'raw_evidence/CONTROLS.json','raw_evidence/DEPENDENCY_BINDINGS.json','raw_evidence/ORIGINAL_DATASET.jsonl']
    for n in sources:
        if n.endswith('.py'):ast.parse((R/n).read_text(encoding='utf-8'));compile((R/n).read_text(encoding='utf-8'),n,'exec')
    full=read(R.parent/'fsm_feedback_pilot_20261005/RUN_SPEC.json')
    spec=dict(schema='natural_harness_calibration_frozen_v1',identity='natural_harness_calibration_20261005_v1',
        frozen_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),base_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip(),
        cloud_root='/workspace/team/runs/fpga_owner/natural_harness_calibration_20261005_v1',kit=full['kit'],
        dependencies_cloud=full['dependencies_cloud'],dependency_hashes=full['dependency_hashes'],
        source_hashes={n:sha(R/n) for n in sources},dataset_sha256=sha(R/'raw_evidence/ORIGINAL_DATASET.jsonl'),
        record_ids=[c['record_id'] for c in private['cases']],model_requests_max=0,compiles_max=50,simulations_max=50,
        controls=16,stage_timeout_s=1200,guard_timeout_s=1300,slot_minutes=25,
        toolchain=bindings['toolchain'],python_site=bindings['python_site'],
        real_tools={n:dict(path=bindings['toolchain']['prefix']+'/bin/'+n,sha256=bindings['toolchain']['files']['bin/'+n]) for n in ['iverilog','vvp']},
        acceptance='Complete original-harness positive/multiple-semantic-negative/sentinel controls and raw native receipt audit. A record qualifies only if positive passes, every intended wrong control fails, sentinel propagates. Keep false acceptances; no test/port/domain retuning. No natural solver/independence/adoption qualification from calibration alone.',
        policy=dict(original_prompts_context_harness_unchanged=True,original_module_names=True,evaluation_controls_only=True,LLM_calls=0,retries=0,
            full156_failed_gate_unchanged=True,independent_model_calls_blocked_until_full_qualification=True))
    save(R/'RUN_SPEC.json',spec);save(R/'PREPARATION_RECEIPT.json',dict(spec_sha256=sha(R/'RUN_SPEC.json'),assets=len(sources),static_parse_compile_passed=True,actual_eda_calls=0,actual_model_calls=0,planned_native_trials=50))
    with zipfile.ZipFile(R/'raw_evidence/preparation.zip','x',zipfile.ZIP_DEFLATED) as z:
        for n in sources+['RUN_SPEC.json','PREPARATION_RECEIPT.json']:z.write(R/n,n)
    save(R/'PREPARATION_ARCHIVE.json',dict(archive_sha256=sha(R/'raw_evidence/preparation.zip'),spec_sha256=sha(R/'RUN_SPEC.json'),assets=len(sources)))
    print(json.dumps(read(R/'PREPARATION_ARCHIVE.json')))
