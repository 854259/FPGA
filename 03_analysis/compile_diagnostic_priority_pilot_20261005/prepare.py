"""Freeze only on the root's explicit later invocation; no Git/network/native tools."""
from pathlib import Path
import argparse,datetime,hashlib,json,re,subprocess,sys,zipfile
import factor_proof,metrics,protected_sources

R=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
read=lambda p:json.loads(p.read_bytes())

def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')


def prepare(base_commit):
    assert sys.version_info[:2]==(3,12) and not (R/'RUN_SPEC.json').exists()
    assert re.fullmatch('[0-9a-f]{40}',base_commit)
    old_path=R/'raw_evidence/source_binding/upstream_RUN_SPEC.json';old=read(old_path)
    assert sha(old_path)=='3fb1531c14b011f80ff58de559e326a4904d3fbdbcf3cdce7d6c955285860ba1'
    capture_path=R/'raw_evidence/NEXT_SCORE_ENVIRONMENT_CAPTURE.json';capture=read(capture_path)
    assert capture['schema']=='actual_diagnostic_next_readonly_environment_capture_v1'
    assert capture['model_calls']==capture['eda_calls']==0 and not capture['policy_installed'] and not capture['task_submitted']
    inputs=read(R/'INPUT_MANIFEST.json')
    assert capture['protected']['tasks']==inputs['input_sha256'] and capture['protected']['official']==inputs['official_sha256']
    assert len(capture['protected']['package'])==18 and len(capture['protected']['tasks'])==936 and len(capture['protected']['official'])==35
    assert capture['dependency_hashes']==old['dependency_hashes'] and capture['dependencies_cloud']==old['dependencies_cloud']
    assert set(capture['compiler_tools'])=={'xvlog','xelab','xsim','vivado'}
    assert set(capture['model_identity'])=={'pid','starttime','exe','command_sha256'} and capture['model_identity']['pid']==old['model_pid']
    group_path=R/'raw_evidence/NEXT_SCORE_PROTECTED_GROUPS.json';groups=read(group_path)
    protected_sources.validate(groups)
    assert groups['local_roots_supplied_and_verified_by_root'] is True
    roots={identity:item['local_root'] for identity,item in groups['groups'].items()} if sys.platform=='win32' else None
    checked_sources=protected_sources.check(groups,roots=roots)
    save(R/'raw_evidence/PRE_FREEZE_PROTECTED_CHECK.json',checked_sources)
    phase=groups['groups'][old['identity']]
    assert phase['spec_sha256']==sha(old_path) and phase['source_hashes']==old['source_hashes']
    # The root may replace both actual captures before freeze. Never infer the future bit group.
    save(R/'SOURCE_FACTOR_PROOF.json',factor_proof.verify(R))
    checked=subprocess.run([sys.executable,'-B','-m','unittest','discover','-v'],cwd=R,text=True,encoding='utf-8',capture_output=True)
    save(R/'raw_evidence/FREEZE_PURE_CHECKS.json',dict(returncode=checked.returncode,stdout=checked.stdout,stderr=checked.stderr,model_calls=0,eda_calls=0))
    assert checked.returncode==0,checked.stdout+checked.stderr
    count=re.search(r'Ran (\d+) tests?',checked.stderr);assert count
    names=sorted(p.relative_to(R).as_posix() for p in R.rglob('*') if p.is_file()
        and '__pycache__' not in p.parts and not p.is_relative_to(R/'raw_evidence')
        and (p.suffix=='.py' or p.is_relative_to(R/'package')))
    names+=['CALIBRATION_AUDIT.json','INPUT_MANIFEST.json','COPY_RECEIPT.json','MOTIVATION_BINDING.json','SOURCE_FACTOR_PROOF.json','README.md']
    names += [p.relative_to(R).as_posix() for folder in ['test_fixtures','source_binding'] for p in (R/'raw_evidence'/folder).iterdir() if p.is_file()]
    names+=['raw_evidence/NEXT_SCORE_ENVIRONMENT_CAPTURE.json','raw_evidence/NEXT_SCORE_PROTECTED_GROUPS.json']
    names=sorted(set(names))
    spec={k:old[k] for k in ['kit','model','model_pid','solve_deadline_s','judge_timeout_s','judge_supervisor_timeout_s','max_worker_requests_per_arm','retries','python_major_minor','environment']}
    spec.update(schema='compile_diag_priority_pilot_frozen_v1',identity='compile_diagnostic_priority_pilot_20261005_v1',
        base_commit=base_commit,frozen_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        cloud_root='/workspace/team/runs/fpga_owner/compile_diagnostic_priority_pilot_20261005_v1',
        task_ids=sorted(metrics.TARGETS+metrics.COUNTEREXAMPLES+metrics.GUARDS),arms=['C','P'],expected_samples=16,
        samples_per_arm_per_task=1,max_actual_model_requests=32,stage_timeout_s=14400,slot_minutes=255,
        first_generation_replayed=False,source_hashes={n:sha(R/n) for n in names},
        common_control='Latest phase_full156 P policy; no added candidate elaboration.',
        only_arm_difference='P prioritize original fullstdout only after normal actual failedcompile; C original fullstdout.',
        priority_sha256=factor_proof.PRIORITY_SHA,phase_spec_sha256=sha(old_path),
        source_factor_proof_sha256=sha(R/'SOURCE_FACTOR_PROOF.json'),
        compiler_tools=capture['compiler_tools'],compiler_env=capture['compiler_env'],udev_files=capture['udev_files'],
        model_identity=capture['model_identity'],protected=capture['protected'],
        dependencies_cloud=capture['dependencies_cloud'],dependency_hashes=capture['dependency_hashes'],
        environment_capture_sha256=sha(capture_path),protected_source_groups_sha256=sha(group_path),
        minimum_disk_free_bytes=2*1024**3,phase_source_sha256=sha(R/'phase_context.py'),
        acceptance='Complete16 original judged samples and fixed8 denominator; no errors/deadline/unknown/regression; five guards L3 same calls; P at most2 added calls; mean rises; target134 exact samefirst/samecandidate/same actual failure facts, only exact bound candidate paths normalized; P priority actually changes consumed capped2048 feedback and exact original unique repair payload; then actual direct repaired xvlog0 and external coefficient strictly rises. New full experiment only, one case not generality.',
        limits=['Known development tasks and one fresh C/P sample; no resampling, replay, retry, best-of or denominator removal.',
            'Original8192/once repair/absolute outer300 seconds; original extractor/skills/runtime/phaseP/officialjudge unchanged.',
            'No added candidate xelab, driver hints, bit suffix, new table factor or suggestions; existing phase probes and officialjudge may run native xelab.',
            'Normal positive integer native rc only; no timeout/launch/cleanup/signal pseudo diagnosis. Physical rawrc/log/argv/sourcebeforeafter remain untouched.',
            'Original mechanical ANSI patch consumes the changed capped feedback and retains original early-return behavior. Its success alone is not model-repair causal gain.',
            'Same-file same-message different unnamed scopes can be merged; original raw log retained, no lossless claim.',
            'Counterexamples082/144 remain full denominator even if both fail or show unchanged feedback.',
            'One target improvement only admits a new full experiment, not cross-task, independent, five-sample, adoption or deployment.',
            'Captured immutable groups are dynamic and must be freshly checked by root at installation/admission; no claim this early capture contains future bit group.',
            'Whole-task FIFO and own guard/cleanup; no shared model or teammate process changes.'])
    assert spec['solve_deadline_s']==spec['judge_timeout_s']==300 and spec['max_worker_requests_per_arm']==2
    save(R/'RUN_SPEC.json',spec)
    receipt=dict(schema='compile_diag_priority_pilot_preparation_v1',spec_sha256=sha(R/'RUN_SPEC.json'),assets=len(names),
        python=sys.version.split()[0],tests_passed=int(count[1]),returncode=checked.returncode,stdout=checked.stdout,stderr=checked.stderr,
        protected_groups=len(groups['groups']),protected_source_assets=groups['source_assets'],model_calls=0,eda_calls=0,stage_executed=False)
    save(R/'PREPARATION_RECEIPT.json',receipt)
    pack=R/'raw_evidence/preparation_v1.zip'
    with zipfile.ZipFile(pack,'x',zipfile.ZIP_DEFLATED) as z:
        for n in names+['RUN_SPEC.json','PREPARATION_RECEIPT.json']:z.write(R/n,n)
    save(R/'PREPARATION_ARCHIVE.json',dict(spec_sha256=receipt['spec_sha256'],archive_sha256=sha(pack),bytes=pack.stat().st_size,files=len(names)+2))
    print(json.dumps({k:receipt[k] for k in ['spec_sha256','assets','tests_passed','model_calls','eda_calls']}))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--base-commit',required=True)
    prepare(p.parse_args().base_commit)
