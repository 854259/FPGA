"""Freeze this prepared score factor only when the root explicitly runs it.

No network, native tools or Git commands occur here. The root supplies its exact
commit and verifies/injects the separate eight-group historical source protection.
"""
from pathlib import Path
import argparse,datetime,hashlib,json,re,subprocess,sys,zipfile
import metrics
import factor_proof
R=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
read=lambda p:json.loads(p.read_bytes())
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')

def prepare(base_commit):
    assert sys.version_info[:2]==(3,12) and not (R/'RUN_SPEC.json').exists()
    assert re.fullmatch('[0-9a-f]{40}',base_commit)
    original=R.parent/'elaboration_feedback_pilot_20261005'
    old=read(original/'RUN_SPEC.json')
    assert sha(original/'RUN_SPEC.json')=='87cb93c00f386f3f16ece9f0ec9a7f49b18fd260faac9c75e83d4db9d31038bf'
    capture_path=R/'raw_evidence/GUIDANCE_ENVIRONMENT_CAPTURE.json';capture=read(capture_path)
    assert capture['schema']=='actual_guidance_readonly_environment_capture_v1'
    assert capture['model_calls']==capture['eda_calls']==0 and not capture['policy_installed'] and not capture['task_submitted']
    inputs=read(R/'INPUT_MANIFEST.json')
    assert capture['protected']['tasks']==inputs['input_sha256'] and capture['protected']['official']==inputs['official_sha256']
    assert len(capture['protected']['package'])==18 and len(capture['protected']['tasks'])==936 and len(capture['protected']['official'])==35
    assert set(capture['compiler_tools'])=={'xvlog','xelab','xsim','vivado'}
    assert capture['dependency_hashes']==old['dependency_hashes']
    assert set(capture['model_identity'])=={'pid','starttime','exe','command_sha256'}
    groups=read(R/'raw_evidence/GUIDANCE_PROTECTED_GROUPS.json')
    assert groups['schema']=='actual_guidance_protected_eight_groups_v1' and len(groups['groups'])==8
    assert groups['source_assets']==sum(len(g['source_hashes']) for g in groups['groups'].values())==232
    assert groups['groups']['prompt_table_calibration_20261005_v2']['spec_sha256']=='cc1abf90fc1e38fbfcaf51df53eab0b47572c532dd8bcc91a334ed4cbfde9d74'
    save(R/'SOURCE_FACTOR_PROOF.json',factor_proof.verify(R))
    checked=subprocess.run([sys.executable,'-B','-m','unittest','discover','-v'],cwd=R,capture_output=True,text=True,encoding='utf-8')
    assert checked.returncode==0,checked.stdout+checked.stderr
    count=re.search(r'Ran (\d+) tests?',checked.stderr);assert count
    names=sorted(p.relative_to(R).as_posix() for p in R.rglob('*') if p.is_file()
                 and '__pycache__' not in p.parts and not p.is_relative_to(R/'raw_evidence')
                 and (p.suffix=='.py' or p.is_relative_to(R/'package')))
    names+=['COPY_RECEIPT.json','UPSTREAM_COPY_RECEIPT.json','CALIBRATION_AUDIT.json','INPUT_MANIFEST.json',
            'FAILURE_REVIEW_BINDING.json','PRIOR_ELABORATION_RESULT.json','SOURCE_FACTOR_PROOF.json','README.md',
            'raw_evidence/test_fixtures/priority.txt','raw_evidence/test_fixtures/shift.txt',
            'raw_evidence/source_binding/upstream_worker.py','raw_evidence/GUIDANCE_ENVIRONMENT_CAPTURE.json',
            'raw_evidence/GUIDANCE_PROTECTED_GROUPS.json']
    names=sorted(set(names))
    spec={k:old[k] for k in ['kit','model','model_pid','solve_deadline_s','judge_timeout_s','judge_supervisor_timeout_s',
          'stage_timeout_s','slot_minutes','max_actual_model_requests','max_worker_requests_per_arm','retries','python_major_minor','environment']}
    spec.update(schema='multidriver_guidance_pilot_frozen_v1',identity='multidriver_guidance_pilot_20261005_v2',
        base_commit=base_commit,frozen_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        cloud_root='/workspace/team/runs/fpga_owner/multidriver_guidance_pilot_20261005_v2',
        task_ids=sorted(metrics.TARGETS+metrics.GUARDS),arms=['C','P'],samples_per_arm_per_task=1,expected_samples=16,
        first_generation_replayed=False,source_hashes={n:sha(R/n) for n in names},
        common_control='old65 P candidate xelab and original phaseP; both arms same native checks',
        only_arm_difference='P appends exact sealed guidance to matching real native ERROR3818 facts; C original facts',
        guidance_sha256=factor_proof.GUIDANCE_SHA,source_factor_proof_sha256=sha(R/'SOURCE_FACTOR_PROOF.json'),
        prior_elaboration_spec_sha256=sha(original/'RUN_SPEC.json'),prior_elaboration_qualified_for_new_full_regression=False,
        compiler_tools=capture['compiler_tools'],compiler_env=capture['compiler_env'],udev_files=capture['udev_files'],
        model_identity=capture['model_identity'],protected=capture['protected'],
        dependencies_cloud=capture['dependencies_cloud'],dependency_hashes=capture['dependency_hashes'],
        environment_capture_sha256=sha(capture_path),
        protected_source_groups_sha256=sha(R/'raw_evidence/GUIDANCE_PROTECTED_GROUPS.json'),minimum_disk_free_bytes=2*1024**3,
        phase_source_sha256=sha(R/'phase_context.py'),native_controls=dict(compile=2,elaboration=2,model_calls=0),
        acceptance='Complete16 original judged samples, fixed8 denominator; no tool errors/deadline/unconfirmed/regression; six guards L3 same calls; at most2 added P calls; higher mean; at least1 target exact samefirst/samecode same3818 facts under owned-source-path-only normalization; P exact appendix enters original unique repair; then P actual xelab0 and strictly improved external coefficient. New full experiment only.',
        limits=['Known development tasks; no full/independent/five/adoption claim.',
                'Fresh first generations, no replay/resample/retry/best-of; original8192/one repair/absolute outer300s supervision unchanged.',
                'Same shared worker/RTL extractor/runtime/skills/native diagnostics; only P guidance append.',
                'ANSI mechanical patch-success early return unchanged; no candidate/TB/ref answer rule.',
                'Old65 remains .775/.775, qualified=false; old functional43ba failed gate and latest phase full passed gate retained.',
                'Exact owned-source-path normalization only in audit comparison; model receives original diagnostic and P appendix.',
                'Root must retain old232 assets/8groups including table_v2/spec cc1abf90 in actual FIFO protection before submission.',
                'Whole-task FIFO/guard source/model ownership; no shared model or teammate management.'])
    assert spec['solve_deadline_s']==300 and len(spec['task_ids'])==8 and spec['max_actual_model_requests']==32
    save(R/'RUN_SPEC.json',spec)
    receipt=dict(schema='multidriver_guidance_pilot_preparation_v1',spec_sha256=sha(R/'RUN_SPEC.json'),assets=len(names),
                 python=sys.version.split()[0],tests_passed=int(count[1]),model_calls=0,eda_calls=0,stdout=checked.stdout,stderr=checked.stderr)
    save(R/'PREPARATION_RECEIPT.json',receipt)
    pack=R/'raw_evidence/preparation_v1.zip'
    with zipfile.ZipFile(pack,'x',zipfile.ZIP_DEFLATED) as z:
        for n in names+['RUN_SPEC.json','PREPARATION_RECEIPT.json']:z.write(R/n,n)
    save(R/'PREPARATION_ARCHIVE.json',dict(spec_sha256=receipt['spec_sha256'],archive_sha256=sha(pack),bytes=pack.stat().st_size,files=len(names)+2))
    print(json.dumps({k:receipt[k] for k in ['spec_sha256','assets','tests_passed','model_calls','eda_calls']}))

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--base-commit',required=True)
    prepare(parser.parse_args().base_commit)
