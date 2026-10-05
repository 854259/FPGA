"""Freeze one new score factor before native or model execution."""
from pathlib import Path
import datetime,hashlib,json,re,subprocess,sys,zipfile
import metrics

R=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_bytes())
def save(p,v):p.write_bytes((json.dumps(v,ensure_ascii=False,indent=2)+'\n').encode())

if __name__=='__main__':
    assert sys.version_info[:2]==(3,12) and not (R/'RUN_SPEC.json').exists()
    original=R.parent/'phase_feedback_pilot_20261005'
    old=read(original/'RUN_SPEC.json')
    copied=read(R/'COPY_RECEIPT.json')
    for n,h in copied['copied_source_hashes'].items():
        if n.startswith('package/') or n in {
            'INPUT_MANIFEST.json','guard_wrapper.py','official_eval_guarded.py',
            'edge_contract.py','edge_dispatch.py','edge_feedback.py','phase_context.py',
            'phase_feedback.py','point_feedback.py','prompt_map.py','priority_contract.py',
            'shift_contract.py','reserved_keywords.py','CALIBRATION_AUDIT.json','collect_evidence.py'}:
            assert sha(R/n)==h,n
    failures=R.parent/'score_failure_analysis_20261005/syntax_transport/EVIDENCE_BINDING.json'
    assert failures.is_file()
    baseline=R.parent/'phase_full156_20261005/PUBLIC_RESULT.json'
    admitted=read(baseline)
    assert admitted['evidence_valid'] and admitted['full156_evidence_valid']
    assert admitted['candidate_qualified_for_independent_validation'] and not admitted['adoption']
    save(R/'FAILURE_REVIEW_BINDING.json',dict(source_path=failures.relative_to(R.parent.parent).as_posix(),
                                            sha256=sha(failures),evidence=read(failures)))
    checked=subprocess.run([sys.executable,'-B','-m','unittest','discover','-v'],cwd=R,
                           capture_output=True,text=True,encoding='utf-8')
    assert checked.returncode==0,checked.stdout+checked.stderr
    count=re.search(r'Ran (\d+) tests?',checked.stderr)
    assert count and int(count[1])>=20,checked.stderr
    names=sorted(p.relative_to(R).as_posix() for p in R.rglob('*')
                 if p.is_file() and '__pycache__' not in p.parts and not p.is_relative_to(R/'raw_evidence')
                 and (p.suffix=='.py' or p.is_relative_to(R/'package')))
    names+=['COPY_RECEIPT.json','CALIBRATION_AUDIT.json','INPUT_MANIFEST.json','FAILURE_REVIEW_BINDING.json',
            'raw_evidence/test_fixtures/priority.txt','raw_evidence/test_fixtures/shift.txt']
    names=sorted(set(names))
    spec={k:old[k] for k in ['kit','model','model_pid','solve_deadline_s','judge_timeout_s',
         'judge_supervisor_timeout_s','stage_timeout_s','slot_minutes','max_actual_model_requests',
         'max_worker_requests_per_arm','retries','python_major_minor','dependencies_cloud',
         'dependency_hashes','environment']}
    spec.update(schema='elaboration_feedback_pilot_frozen_v1',identity='elaboration_feedback_pilot_20261005_v1',
        base_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip(),
        frozen_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        cloud_root='/workspace/team/runs/fpga_owner/elaboration_feedback_pilot_20261005_v1',
        task_ids=sorted(metrics.TARGETS+metrics.GUARDS),arms=['C','P'],samples_per_arm_per_task=1,
        expected_samples=16,first_generation_replayed=False,source_hashes={n:sha(R/n) for n in names},
        base_phase_spec_sha256=sha(original/'RUN_SPEC.json'),
        full_baseline_spec_sha256=admitted['spec_sha256'],
        full_baseline_archive_sha256=admitted['archive_sha256'],
        full_baseline_public_result_sha256=sha(baseline),
        phase_source_sha256=sha(R/'phase_context.py'),minimum_disk_free_bytes=2*1024**3,
        native_controls=dict(compile=2,elaboration=2,model_calls=0),
        runtime_change='Both arms share the old P phase policy and untouched runtime/skills. Only P adds self-contained TopModule elaboration before ordinary compiled candidate semantic feedback. Successful mechanical declaration patch return remains unchanged.',
        acceptance='Complete16 same8192/one-repair/300s with original judge; no errors/deadlines/unconfirmed or task regression; six guard tasks L3 with same request cost; candidate adds at most2 requests; higher mean; at least one target actual same-first xelab failure bound into unique original repair, final xelab pass and strictly higher official coefficient. Permits new full experiment only, no deployment/independent/five qualification.',
        limits=['All eight tasks are known development tasks, one fresh sample per arm; no full/independent/five claim.',
                'No first reply replay, resampling, retries or best-of selection. All outcomes/costs retained.',
                'Only prompt/interface/candidate/tool facts enter solver; official testbench/reference remain in external judge.',
                'Extra xelab time is included in the same solve300s; native controls occur before any model request.',
                'Original successful ANSI declaration patch returns unchanged and does not receive this new elaboration.',
                'The latest phase full156 passed and is the common development policy. Historical functional43ba three-deadline failed gate remains unchanged. No automatic deployment.',
                'Whole-task FIFO, guard/resource locks and owned process supervision; never manage shared model/instance/teammates.'])
    assert len(spec['task_ids'])==8 and spec['max_actual_model_requests']==32
    save(R/'RUN_SPEC.json',spec)
    receipt=dict(schema='elaboration_feedback_preparation_v1',spec_sha256=sha(R/'RUN_SPEC.json'),
                 assets=len(names),python=sys.version.split()[0],tests_passed=int(count[1]),
                 model_calls=0,eda_calls=0,stdout=checked.stdout,stderr=checked.stderr)
    save(R/'PREPARATION_RECEIPT.json',receipt)
    pack=R/'raw_evidence/preparation_v1.zip'
    with zipfile.ZipFile(pack,'x',zipfile.ZIP_DEFLATED) as z:
        for n in names+['RUN_SPEC.json','PREPARATION_RECEIPT.json']:z.write(R/n,n)
    save(R/'PREPARATION_ARCHIVE.json',dict(spec_sha256=receipt['spec_sha256'],archive_sha256=sha(pack),
                                         bytes=pack.stat().st_size,files=len(names)+2))
    print(json.dumps({k:receipt[k] for k in ['spec_sha256','assets','tests_passed','model_calls','eda_calls']}))
