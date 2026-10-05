"""Freeze a fresh one-factor C/E experiment with original inference/repair budget."""
import datetime
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import zipfile
import metrics

R=Path(__file__).resolve().parent
TOOLS=R.parent/'edge_feedback_20261005'
FULL=R.parent/'functional_full156_20261005'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text(encoding='utf-8'))
def save(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


if __name__=='__main__':
    assert sys.version_info[:2]==(3,12) and not (R/'RUN_SPEC.json').exists()
    assert sha(TOOLS/'TOOLS_SPEC.json')=='a5b2b9f2ce01ad144d8519a101300452f07d6a35a557535dd05481bd8a7033c0'
    tools=read(TOOLS/'TOOLS_SPEC.json');installed=read(TOOLS/'INSTALL_RECEIPT.json')
    assert installed['tests_passed']==20 and installed['model_calls']==installed['eda_calls']==0
    for n,h in tools['source_hashes'].items():
        assert sha(TOOLS/n)==h,n
        if (R/n).is_file() and n not in ['COPY_RECEIPT.json','UNFROZEN_FAILURES.json']:
            assert sha(R/n)==h,n
    full=read(FULL/'RUN_SPEC.json')
    assert sha(FULL/'RUN_SPEC.json')=='43ba0bb8da29e2ec9dd5cef5b3ae81173e5796973466c18f7f1ee34fff13bbb7'
    audit=read(FULL/'terminal_audit_local312/RESULTS.json')
    assert audit==read(FULL/'terminal_audit_cloud/RESULTS.json') and audit['evidence_valid']
    assert not audit['candidate_qualified_for_independent_validation']
    assert sha(R/'package/agent/map_runtime.py')=='2f7cb98bc44a9e100d36ca12ac4ef7bf9ae2535473da358e166afa2559e96cba'
    assert sha(R/'worker.py')==tools['source_hashes']['worker.py']
    calibration=read(R/'CALIBRATION_AUDIT.json')
    assert calibration['evidence_valid'] and calibration['controls_valid'] and calibration['natural_hypothesis_matched']
    assert calibration['probe_executions']==26 and calibration['synth_executions']==6
    assert sha(R/'edge_contract.py')==tools['source_hashes']['edge_contract.py']
    exposure=read(TOOLS/'ARCHIVED_EXPOSURE.json')
    assert exposure['archive_sha256']==audit['archive_sha256'] and exposure['newly_supported_tasks']==metrics.EDGES
    previous=read(R.parent/'repair_context_pilot_v2_20261005/terminal_audit_v1/RESULTS.json')
    assert previous['evidence_valid'] and previous['matched_compression_tasks']==[]
    assert not previous['qualified_for_new_full_regression'] and not previous['adoption']
    tests=['test_fresh','test_edge_integration','test_boundaries','test_metrics','test_replay','test_stage','test_environment']
    t=subprocess.run([sys.executable,'-B','-m','unittest',*tests,'-v'],cwd=R,capture_output=True,text=True,encoding='utf-8')
    assert t.returncode==0 and 'Ran 33 tests' in t.stderr,t.stdout+t.stderr
    names=[p.relative_to(R).as_posix() for p in R.rglob('*') if p.is_file() and '__pycache__' not in p.parts
           and not p.is_relative_to(R/'raw_evidence') and (p.suffix=='.py' or p.is_relative_to(R/'package'))]
    names+=['COPY_RECEIPT.json','CALIBRATION_AUDIT.json','INPUT_MANIFEST.json','UNFROZEN_FAILURES.json',
            'raw_evidence/test_fixtures/priority.txt','raw_evidence/test_fixtures/shift.txt','raw_evidence/test_fixtures/score.py']
    names=sorted(set(names))
    spec=dict(schema='edge_feedback_pilot_frozen_v1',identity='edge_feedback_pilot_20261005_v1',
        base_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip(),
        frozen_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        cloud_root='/workspace/team/runs/fpga_owner/edge_feedback_pilot_20261005_v1',
        kit=full['kit'],model=full['model'],model_pid=full['model_pid'],
        task_ids=sorted(metrics.EDGES+metrics.GUARDS+[metrics.UNKNOWN]),arms=['C','E'],samples_per_arm_per_task=1,
        expected_samples=16,solve_deadline_s=300,judge_timeout_s=300,judge_supervisor_timeout_s=360,
        stage_timeout_s=14400,slot_minutes=250,max_actual_model_requests=32,max_worker_requests_per_arm=2,
        first_generation_replayed=False,retries=0,python_major_minor=[3,12],
        dependencies_cloud=full['dependencies_cloud'],dependency_hashes=full['dependency_hashes'],
        source_hashes={n:sha(R/n) for n in names},predecessor_full_spec_sha256=sha(FULL/'RUN_SPEC.json'),
        predecessor_full_archive_sha256=audit['archive_sha256'],predecessor_full_gate_failed_preserved=True,
        preflight_tools_spec_sha256=sha(TOOLS/'TOOLS_SPEC.json'),edge_calibration_archive_sha256=calibration['archive_sha256'],
        historical_edge_exposure_sha256=sha(TOOLS/'ARCHIVED_EXPOSURE.json'),
        prior_context_terminal_archive_sha256=previous['archive_sha256'],
        environment=dict(vivado_bin='/workspace/AMD/2026.1/Vivado/bin',udev_stub='/workspace/team/udev-stub',scoped_launch=True),
        runtime_change='C/E identical original functional runtime; E adds only complete prompt-derived edge contract dispatch and observed native counterexample feedback. No compressed repair copy or change to initial prompts, skills, extractor, compiler, original successful declaration patch or one-repair budget.',
        acceptance='Complete16 and raw native audit; both arms free of tool errors/deadlines/unconfirmed; no per-task regression; guards058/071/112/115/124 both L3 with same call counts; unknown143 same grade/calls; E increases calls by at most2 total. Both edge tasks must have matching first replies, control belowL3, first true E native mismatch bound into original single repair, final native pass and officialL3. Permits new full156 only, no independent/five/adoption.',
        limits=['8 known public development/guard tasks, one actual fresh first generation per arm, original all8 denominator. No full156/independent/five-sample claim.',
                'All extra repair requests, tool checks and elapsed time retained. Same maximum budgets; no replay, resampling, retries or best-of selection.',
                'Temperature0 does not guarantee identical replies. Two distinct actual matched edge repair chains required; differing first replies do not prove causal gains.',
                'Control and candidate share byte-identical original runtime and skills; successful declaration patch still returns on its original branch.',
                'Only prompt/interface/own candidate/native facts enter workers; references and official TB remain in external original judge.',
                'Existing native edge calibration reused exactly; no manufactured reset/initial-state/omitted-edge obligation.',
                'Official L3 and native probe pass separately recorded; persistent mismatch cannot qualify as a successful edge repair even if official grade is L3.',
                'Frozen auditor independently binds actual requests, replies, extraction, compiler receipts, counterexample feedback and original judge; original full failed gate unchanged.',
                'Whole-task FIFO and original inner locks/resource cleanup; never manage teammate, shared model, instance or formal deployment.',
                'Outer14400s and250-minute slot are safety bounds, not expected duration. Hard300s includes model/compiler/native feedback.',
                'No automatic adoption; new full regression, independent natural tasks, official baseline/five samples, offline and target32GB remain required.'])
    save(R/'RUN_SPEC.json',spec)
    save(R/'PREPARATION_RECEIPT.json',dict(spec_sha256=sha(R/'RUN_SPEC.json'),assets=len(names),tests_passed=33,
         local_python=sys.version.split()[0],stdout=t.stdout,stderr=t.stderr,model_calls=0,eda_calls=0,
         old_failed_gate_unchanged=True,actual_trial_submitted=False))
    archive=R/'raw_evidence/preparation.zip'
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
        for n in names+['RUN_SPEC.json','PREPARATION_RECEIPT.json']:z.write(R/n,n)
    save(R/'PREPARATION_ARCHIVE.json',dict(archive_sha256=sha(archive),spec_sha256=sha(R/'RUN_SPEC.json'),assets=len(names)))
    print(json.dumps(dict(assets=len(names),tests_passed=33,spec_sha256=sha(R/'RUN_SPEC.json'),archive_sha256=sha(archive))))
