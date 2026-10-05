"""Freeze fresh C/P whole edge-policy screen. No model/EDA operations."""
from pathlib import Path
import datetime,hashlib,json,subprocess,sys,zipfile
import metrics
R=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_bytes())
def save(p,v):p.write_bytes((json.dumps(v,ensure_ascii=False,indent=2)+'\n').encode())
if __name__=='__main__':
    assert sys.version_info[:2]==(3,12) and not (R/'RUN_SPEC.json').exists()
    previous=R.parent/'edge_feedback_pilot_20261005';full=R.parent/'functional_full156_20261005';review=R.parent/'team_phase_repair_review_20261005/RESULTS.json'
    a=read(review);old=read(previous/'RUN_SPEC.json');prior=read(previous/'terminal_audit_v1/RESULTS.json');f=read(full/'terminal_audit_local312/RESULTS.json')
    assert a['evidence_valid'] and a['signal_supports_fresh_same_budget_pilot'] and a['first_generation_replayed'] and not a['qualified_for_full']
    assert prior['evidence_valid'] and not prior['qualified_for_new_full_regression'] and not f['candidate_qualified_for_independent_validation']
    assert sha(R/'phase_context.py')==a['phase_source_sha256']=='90b7c71b480a7cdd9d485e7401509feef996520111e76c03666ac519a2d01afa'
    assert sha(R/'package/agent/map_runtime.py')=='2f7cb98bc44a9e100d36ca12ac4ef7bf9ae2535473da358e166afa2559e96cba'
    for n,h in old['source_hashes'].items():
        if n.startswith('package/') or n in ['edge_contract.py','edge_feedback.py','point_feedback.py','prompt_map.py','priority_contract.py','shift_contract.py','reserved_keywords.py','INPUT_MANIFEST.json','guard_wrapper.py','official_eval_guarded.py','CALIBRATION_AUDIT.json']:assert sha(R/n)==h,n
    tests=['test_fresh','test_edge_integration','test_boundaries','test_metrics','test_replay','test_stage','test_environment','test_phase']
    t=subprocess.run([sys.executable,'-B','-m','unittest',*tests,'-v'],cwd=R,capture_output=True,text=True,encoding='utf-8');assert t.returncode==0 and 'Ran 36 tests' in t.stderr,t.stdout+t.stderr
    (R/'REVIEW_RESULTS.json').write_bytes(review.read_bytes())
    names=sorted(p.relative_to(R).as_posix() for p in R.rglob('*') if p.is_file() and '__pycache__' not in p.parts and not p.is_relative_to(R/'raw_evidence') and (p.suffix=='.py' or p.is_relative_to(R/'package')))
    names+=['COPY_RECEIPT.json','CALIBRATION_AUDIT.json','INPUT_MANIFEST.json','REVIEW_RESULTS.json','UNFROZEN_FAILURES.json','raw_evidence/test_fixtures/priority.txt','raw_evidence/test_fixtures/shift.txt','raw_evidence/test_fixtures/score.py','raw_evidence/test_fixtures/phase_observation.json'];names=sorted(set(names))
    spec={k:old[k] for k in ['kit','model','model_pid','solve_deadline_s','judge_timeout_s','judge_supervisor_timeout_s','stage_timeout_s','slot_minutes','max_actual_model_requests','max_worker_requests_per_arm','retries','python_major_minor','dependencies_cloud','dependency_hashes','environment']}
    spec.update(schema='phase_feedback_pilot_frozen_v1',identity='phase_feedback_pilot_20261005_v1',base_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip(),frozen_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),cloud_root='/workspace/team/runs/fpga_owner/phase_feedback_pilot_20261005_v1',task_ids=sorted(metrics.EDGES+metrics.GUARDS+[metrics.UNKNOWN]),arms=['C','P'],samples_per_arm_per_task=1,expected_samples=16,first_generation_replayed=False,source_hashes={n:sha(R/n) for n in names},prior_edge_archive_sha256=prior['archive_sha256'],predecessor_full_archive_sha256=f['archive_sha256'],previous_full_gate_failed_preserved=True,review_sha256=sha(review),teammate_archives=a['archive_sha256'],phase_source_sha256=a['phase_source_sha256'],runtime_change='Original C priority/shift versus P complete prompt-derived edge verification with native phase-group observations. Tests the whole edge feedback policy, not phase-only causal isolation. Initial prompts, skills, extractor, compiler, successful declaration patch return and original one-repair 8192/300 budgets unchanged.',acceptance=old['acceptance'].replace('E ','P ').replace('true E ','true P '),limits=old['limits']+['Teammate phase-only mechanism uses replayed known checkpoints. This experiment uses fresh first generation C/P and cannot attribute whole-policy benefit exclusively to phase grouping.','T7 48 native controls reused; no repeated constructed EDA. Phase source bytes identical to reviewed T7/T8. All true native observation rows bound before feedback; missing/duplicate/order/expected/count defects rejected.'])
    save(R/'RUN_SPEC.json',spec)
    receipt=dict(schema='fresh_phase_preparation_v1',spec_sha256=sha(R/'RUN_SPEC.json'),assets=len(names),python=sys.version.split()[0],tests_passed=36,model_calls=0,eda_calls=0,first_generation_replayed=False,stdout=t.stdout,stderr=t.stderr)
    save(R/'PREPARATION_RECEIPT.json',receipt);pack=R/'raw_evidence/preparation_v1.zip'
    with zipfile.ZipFile(pack,'x',zipfile.ZIP_DEFLATED) as z:
        for n in names+['RUN_SPEC.json','PREPARATION_RECEIPT.json']:z.write(R/n,n)
    save(R/'PREPARATION_ARCHIVE.json',dict(archive_sha256=sha(pack),bytes=pack.stat().st_size,files=len(names)+2,source_spec_sha256=receipt['spec_sha256']))
    print(json.dumps({k:receipt[k] for k in ['spec_sha256','assets','tests_passed','model_calls','eda_calls']}))
