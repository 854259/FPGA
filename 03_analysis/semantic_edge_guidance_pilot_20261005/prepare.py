"""Root-invoked freeze plan; requires actual captures and sealed semantic review."""
from pathlib import Path
import argparse,datetime,hashlib,json,re,subprocess,sys,zipfile
import metrics,semantic_policy,factor_proof,protected_sources,preparation_inputs
R=Path(__file__).absolute().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
read=lambda p:json.loads(p.read_bytes())
def save(p,value):p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
def prepare(base_commit,environment_capture,protected_groups,semantic_review):
    assert sys.version_info[:2]==(3,12) and not (R/'RUN_SPEC.json').exists()
    assert re.fullmatch('[0-9a-f]{40}',base_commit)
    oldroot=R.parent/'phase_full156_20261005';old=read(oldroot/'RUN_SPEC.json')
    assert sha(oldroot/'RUN_SPEC.json')=='3fb1531c14b011f80ff58de559e326a4904d3fbdbcf3cdce7d6c955285860ba1'
    assert read(R/'COPY_RECEIPT.json')['copied_source_hashes']==old['source_hashes']
    assert (R/'raw_evidence/source_binding/upstream_RUN_SPEC.json').read_bytes()==(oldroot/'RUN_SPEC.json').read_bytes()
    for name,digest in old['source_hashes'].items():assert sha(oldroot/name)==digest,name
    env=Path(environment_capture).read_bytes();groups_bytes=Path(protected_groups).read_bytes()
    capture=json.loads(env);groups=json.loads(groups_bytes)
    counts=preparation_inputs.validate_capture(capture,groups,read(R/'INPUT_MANIFEST.json'),old)
    assert Path(semantic_review).read_bytes()==(R/'raw_evidence/SEMANTIC_REVIEW.json').read_bytes()
    for name,raw in [('ENVIRONMENT_CAPTURE.json',env),('PROTECTED_GROUPS_CAPTURE.json',groups_bytes)]:
        target=R/'raw_evidence'/name
        if target.exists():assert target.read_bytes()==raw
        else:target.write_bytes(raw)
    roots={identity:item['local_root'] for identity,item in groups['groups'].items()} if sys.platform=='win32' else None
    save(R/'raw_evidence/PRE_FREEZE_PROTECTED_CHECK.json',protected_sources.check(groups,roots=roots))
    motivation=preparation_inputs.validate_motivation(R)
    save(R/'MOTIVATION_BINDING.json',motivation)
    save(R/'SOURCE_FACTOR_PROOF.json',factor_proof.verify(R))
    checked=subprocess.run([sys.executable,'-B','-m','unittest','discover','-v'],cwd=R,text=True,encoding='utf-8',capture_output=True)
    assert checked.returncode==0,checked.stdout+checked.stderr
    count=re.search(r'Ran (\d+) tests?',checked.stderr);assert count
    names=sorted(p.relative_to(R).as_posix() for p in R.rglob('*') if p.is_file() and '__pycache__' not in p.parts
                 and not p.is_relative_to(R/'raw_evidence') and (p.suffix=='.py' or p.is_relative_to(R/'package')))
    names+=['COPY_RECEIPT.json','UPSTREAM_COPY_RECEIPT.json','APPENDIX.txt','BASELINE_BINDING.json','SOURCE_FACTOR_PROOF.json','MOTIVATION_BINDING.json','README.md',
            'FRESH_PILOT_AUDIT.json','CALIBRATION_AUDIT.json','INPUT_MANIFEST.json','REVIEW_RESULTS.json','APPLICABILITY.json','UNFROZEN_FAILURES.json',
            'raw_evidence/test_fixtures/priority.txt','raw_evidence/test_fixtures/shift.txt','raw_evidence/test_fixtures/score.py','raw_evidence/test_fixtures/phase_observation.json',
            'raw_evidence/source_binding/upstream_worker.py','raw_evidence/source_binding/upstream_RUN_SPEC.json','raw_evidence/SEMANTIC_SUPPORT_BINDINGS.json','raw_evidence/ENVIRONMENT_CAPTURE.json','raw_evidence/PROTECTED_GROUPS_CAPTURE.json','raw_evidence/SEMANTIC_REVIEW.json','raw_evidence/SEMANTIC_REVIEW_BINDING.json','raw_evidence/SEMANTIC_AUTHENTICATION.json']
    names=sorted(set(names))
    spec={key:old[key] for key in ['kit','model','model_pid','solve_deadline_s','judge_timeout_s','judge_supervisor_timeout_s','max_worker_requests_per_arm','retries','python_major_minor','environment']}
    spec.update(schema='semantic_edge_guidance_pilot_frozen_v1',identity='semantic_edge_guidance_pilot_20261005_v1',
        cloud_root='/workspace/team/runs/fpga_owner/semantic_edge_guidance_pilot_20261005_v1',base_commit=base_commit,
        frozen_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),task_ids=sorted(metrics.TARGETS+metrics.GUARDS),arms=['C','P'],
        samples_per_arm_per_task=1,expected_samples=28,max_actual_model_requests=56,stage_timeout_s=14400,slot_minutes=250,
        first_generation_replayed=False,source_hashes={name:sha(R/name) for name in names},appendix_sha256=semantic_policy.APPENDIX_SHA,
        source_factor_proof_sha256=sha(R/'SOURCE_FACTOR_PROOF.json'),base_phase_full_spec_sha256=sha(oldroot/'RUN_SPEC.json'),
        common_control='phasefull original P; no bit/driver/table/native-budget/error-priority factors',
        only_arm_difference='runtime.skill_texts wrapper: P G+A,R; C G,R; exact suffix in initial and repair system messages',
        environment_capture_sha256=sha(R/'raw_evidence/ENVIRONMENT_CAPTURE.json'),protected_groups_capture_sha256=sha(R/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json'),
        semantic_support_sha256=sha(R/'raw_evidence/SEMANTIC_SUPPORT_BINDINGS.json'),semantic_review_sha256=sha(R/'raw_evidence/SEMANTIC_REVIEW.json'),semantic_review_binding_sha256=sha(R/'raw_evidence/SEMANTIC_REVIEW_BINDING.json'),
        semantic_authentication_sha256=sha(R/'raw_evidence/SEMANTIC_AUTHENTICATION.json'),motivation_binding_sha256=sha(R/'MOTIVATION_BINDING.json'),
        compiler_tools=capture['compiler_tools'],compiler_env=capture['compiler_env'],udev_files=capture['udev_files'],protected=capture['protected'],
        model_identity=capture['model_identity'],dependencies_cloud=capture['dependencies_cloud'],dependency_hashes=capture['dependency_hashes'],
        protected_group_count=len(groups['groups']),protected_source_assets=groups['source_assets'],minimum_disk_free_bytes=2*1024**3,
        acceptance='Complete28/fixed14 denominator,0errors/deadline/unconfirmed/regression,sixguards L3 and no increased P calls,at least3 targets external coefficient gain,higher mean,totalP<=C+2; exact all initial/repair system suffix and original user/native provenance. No samefirst requirement. New full experiment only.',
        limits=['Known development tasks; one fresh per arm, no replay/retry/resample/best-of.',
                'Original8192/one repair/absolute outer300s/runtime extractor/input/skills/judge unchanged.',
                'P suffix appears in both first generation and repair system messages; first replies can differ and equality is descriptive only.',
                'No bit-mapping/driver xelab/guidance/table/error-priority/new native budget mixed in.',
                'Motivation39-report/support metadata never enter model; only original prompt/interface/current candidate/native feedback/exact appendix.',
                'Source group counts/specs from actual future capture, not guessed9/281 or10/330; root must verify installation before FIFO.',
                'Original review cross-family/equal-call proposal is superseded by root latest >=3/no guard-call-increase gate.',
                'New full gate only; no deployment,independent,five-sample or full-score proof.'])
    assert spec['solve_deadline_s']==300 and spec['max_worker_requests_per_arm']==2 and spec['retries']==0
    save(R/'RUN_SPEC.json',spec)
    receipt=dict(schema='semantic_edge_pilot_preparation_v1',spec_sha256=sha(R/'RUN_SPEC.json'),assets=len(names),tests_passed=int(count[1]),python=sys.version.split()[0],model_calls=0,eda_calls=0,stdout=checked.stdout,stderr=checked.stderr)
    save(R/'PREPARATION_RECEIPT.json',receipt)
    pack=R/'raw_evidence/preparation_v1.zip'
    with zipfile.ZipFile(pack,'x',zipfile.ZIP_DEFLATED) as z:
        for name in names+['RUN_SPEC.json','PREPARATION_RECEIPT.json']:z.write(R/name,name)
    save(R/'PREPARATION_ARCHIVE.json',dict(spec_sha256=receipt['spec_sha256'],archive_sha256=sha(pack),bytes=pack.stat().st_size,files=len(names)+2))
    print(json.dumps({key:receipt[key] for key in ['spec_sha256','assets','tests_passed','model_calls','eda_calls']}))
if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ['base-commit','environment-capture','protected-groups','semantic-review']:parser.add_argument('--'+name,required=True)
    args=parser.parse_args();prepare(args.base_commit,args.environment_capture,args.protected_groups,args.semantic_review)
