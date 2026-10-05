"""Root-invoked freeze plan; requires actual future captures and priority report."""
from pathlib import Path
import argparse,datetime,hashlib,json,re,subprocess,sys,zipfile
import metrics,bit_policy,factor_proof,protected_sources
R=Path(__file__).absolute().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
read=lambda p:json.loads(p.read_bytes())
def save(p,value):p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
def prepare(base_commit,environment_capture,protected_groups,priority_report):
    assert sys.version_info[:2]==(3,12) and not (R/'RUN_SPEC.json').exists()
    assert re.fullmatch('[0-9a-f]{40}',base_commit)
    oldroot=R.parent/'phase_full156_20261005';old=read(oldroot/'RUN_SPEC.json')
    assert sha(oldroot/'RUN_SPEC.json')=='3fb1531c14b011f80ff58de559e326a4904d3fbdbcf3cdce7d6c955285860ba1'
    assert read(R/'COPY_RECEIPT.json')['copied_source_hashes']==old['source_hashes']
    assert (R/'raw_evidence/source_binding/upstream_RUN_SPEC.json').read_bytes()==(oldroot/'RUN_SPEC.json').read_bytes()
    paths={'ENVIRONMENT_CAPTURE.json':Path(environment_capture),'PROTECTED_GROUPS_CAPTURE.json':Path(protected_groups),'PRIORITY_REPORT.json':Path(priority_report)}
    for name,source in paths.items():
        raw=source.read_bytes();assert isinstance(json.loads(raw),dict)
        target=R/'raw_evidence'/name
        if target.exists():assert target.read_bytes()==raw
        else:target.write_bytes(raw)
    capture=read(R/'raw_evidence/ENVIRONMENT_CAPTURE.json');groups=read(R/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json')
    assert capture['schema'].startswith('actual_') and capture['model_calls']==capture['eda_calls']==0
    assert not capture.get('policy_installed',False) and not capture.get('task_submitted',False)
    inputs=read(R/'INPUT_MANIFEST.json')
    assert capture['protected']['tasks']==inputs['input_sha256'] and capture['protected']['official']==inputs['official_sha256']
    assert len(capture['protected']['package'])==18 and len(capture['protected']['tasks'])==936 and len(capture['protected']['official'])==35
    assert set(capture['compiler_tools'])=={'xvlog','xelab','xsim','vivado'}
    assert set(capture['model_identity'])=={'pid','starttime','exe','command_sha256'}
    assert capture['dependency_hashes']==old['dependency_hashes']
    assert groups['schema'].startswith('actual_') and len(groups['groups'])>=8
    assert groups['source_assets']==sum(len(g['source_hashes']) for g in groups['groups'].values())
    assert groups['model_calls']==groups['eda_calls']==0
    assert any(key.startswith('multidriver_guidance_pilot_20261005_') for key in groups['groups'])
    roots={identity:item['local_root'] for identity,item in groups['groups'].items()} if sys.platform=='win32' else None
    protection=protected_sources.check(groups,roots=roots)
    save(R/'raw_evidence/PRE_FREEZE_PROTECTED_CHECK.json',protection)
    report=read(R/'raw_evidence/PRIORITY_REPORT.json');binding=read(R/'raw_evidence/PRIORITY_BINDING.json')
    assert report['schema']=='latest_P_score_failure_priority_review_v1' and report['current_failed_denominator']==43
    assert binding['public_file_hashes_before_binding']['REVIEW.json']['sha256']==sha(R/'raw_evidence/PRIORITY_REPORT.json')
    assert binding['private_top_file_bindings']['BIT_MAPPING_SUPPORT.json']['sha256']==sha(R/'raw_evidence/BIT_MAPPING_SUPPORT.json')
    candidate=next(c for c in report['candidates'] if c['name']=='numeric_source_to_destination_bit_mapping_generation_skill_appendix')
    assert sorted(candidate['support_current_tasks'])==sorted(metrics.TARGETS) and candidate['private_support_sha256']==sha(R/'raw_evidence/BIT_MAPPING_SUPPORT.json')
    support=read(R/'raw_evidence/BIT_MAPPING_SUPPORT.json')
    assert sha(R/'raw_evidence/BIT_MAPPING_SUPPORT.json')=='77a8a0bcd2fb1e649f4da1efe03ec0ec1a4ebc63bf413af628bd70cdcfdbbb2b'
    assert sorted(support)==sorted(metrics.TARGETS)
    for task,item in support.items():
        assert item['actual_final']['task']==task
        assert item['actual_final']['prompt_sha256']==item['members']['prompt_only/prompt.txt']['sha256']==inputs['input_sha256'][task+'/prompt.txt']
    save(R/'SOURCE_FACTOR_PROOF.json',factor_proof.verify(R))
    save(R/'MOTIVATION_BINDING.json',dict(schema='bit_mapping_motivation_metadata_binding_v1',
         bit_mapping_support_sha256=sha(R/'raw_evidence/BIT_MAPPING_SUPPORT.json'),priority_report_sha256=sha(R/'raw_evidence/PRIORITY_REPORT.json'),priority_binding_sha256=sha(R/'raw_evidence/PRIORITY_BINDING.json'),
         targets=metrics.TARGETS,metadata_only=True,model_input=False))
    checked=subprocess.run([sys.executable,'-B','-m','unittest','discover','-v'],cwd=R,text=True,encoding='utf-8',capture_output=True)
    assert checked.returncode==0,checked.stdout+checked.stderr
    count=re.search(r'Ran (\d+) tests?',checked.stderr);assert count
    names=sorted(p.relative_to(R).as_posix() for p in R.rglob('*') if p.is_file() and '__pycache__' not in p.parts
                 and not p.is_relative_to(R/'raw_evidence') and (p.suffix=='.py' or p.is_relative_to(R/'package')))
    names+=['COPY_RECEIPT.json','UPSTREAM_COPY_RECEIPT.json','APPENDIX.txt','BASELINE_BINDING.json','SOURCE_FACTOR_PROOF.json','MOTIVATION_BINDING.json','README.md',
            'FRESH_PILOT_AUDIT.json','CALIBRATION_AUDIT.json','INPUT_MANIFEST.json','REVIEW_RESULTS.json','APPLICABILITY.json','UNFROZEN_FAILURES.json',
            'raw_evidence/test_fixtures/priority.txt','raw_evidence/test_fixtures/shift.txt','raw_evidence/test_fixtures/score.py','raw_evidence/test_fixtures/phase_observation.json',
            'raw_evidence/source_binding/upstream_worker.py','raw_evidence/source_binding/upstream_RUN_SPEC.json','raw_evidence/BIT_MAPPING_SUPPORT.json','raw_evidence/ENVIRONMENT_CAPTURE.json','raw_evidence/PROTECTED_GROUPS_CAPTURE.json','raw_evidence/PRIORITY_REPORT.json','raw_evidence/PRIORITY_BINDING.json']
    names=sorted(set(names))
    spec={key:old[key] for key in ['kit','model','model_pid','solve_deadline_s','judge_timeout_s','judge_supervisor_timeout_s','max_worker_requests_per_arm','retries','python_major_minor','environment']}
    spec.update(schema='bit_mapping_guidance_pilot_frozen_v1',identity='bit_mapping_guidance_pilot_20261005_v1',
        cloud_root='/workspace/team/runs/fpga_owner/bit_mapping_guidance_pilot_20261005_v1',base_commit=base_commit,
        frozen_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),task_ids=sorted(metrics.TARGETS+metrics.GUARDS),arms=['C','P'],
        samples_per_arm_per_task=1,expected_samples=20,max_actual_model_requests=40,stage_timeout_s=14400,slot_minutes=250,
        first_generation_replayed=False,source_hashes={name:sha(R/name) for name in names},appendix_sha256=bit_policy.APPENDIX_SHA,
        source_factor_proof_sha256=sha(R/'SOURCE_FACTOR_PROOF.json'),base_phase_full_spec_sha256=sha(oldroot/'RUN_SPEC.json'),
        common_control='phasefull original P; no driver/table/native-budget/error-priority factors',
        only_arm_difference='runtime.skill_texts wrapper: P G+A,R; C G,R; exact suffix in initial and repair system messages',
        environment_capture_sha256=sha(R/'raw_evidence/ENVIRONMENT_CAPTURE.json'),protected_groups_capture_sha256=sha(R/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json'),
        bit_mapping_support_sha256=sha(R/'raw_evidence/BIT_MAPPING_SUPPORT.json'),priority_report_sha256=sha(R/'raw_evidence/PRIORITY_REPORT.json'),priority_binding_sha256=sha(R/'raw_evidence/PRIORITY_BINDING.json'),
        compiler_tools=capture['compiler_tools'],compiler_env=capture['compiler_env'],udev_files=capture['udev_files'],protected=capture['protected'],
        model_identity=capture['model_identity'],dependencies_cloud=capture['dependencies_cloud'],dependency_hashes=capture['dependency_hashes'],
        protected_group_count=len(groups['groups']),protected_source_assets=groups['source_assets'],minimum_disk_free_bytes=2*1024**3,
        acceptance='Complete20/fixed10 denominator,0errors/deadline/unconfirmed/regression,sixguards L3 and no increased P calls,at least2 targets external coefficient gain,higher mean,totalP<=C+2; exact all initial/repair system suffix and original user/native provenance. No samefirst requirement. New full experiment only.',
        limits=['Known development tasks; one fresh per arm, no replay/retry/resample/best-of.',
                'Original8192/one repair/absolute outer300s/runtime extractor/input/skills/judge unchanged.',
                'P suffix appears in both first generation and repair system messages; first replies can differ and equality is descriptive only.',
                'No driver xelab/guidance/table/error-priority/new native budget mixed in.',
                'Motivation43-report/support metadata never enter model; only original prompt/interface/current candidate/native feedback/exact appendix.',
                'Source group counts/specs from actual future capture, not guessed9/281 or10/330; root must verify installation before FIFO.',
                'New full gate only; no deployment,independent,five-sample or full-score proof.'])
    assert spec['solve_deadline_s']==300 and spec['max_worker_requests_per_arm']==2 and spec['retries']==0
    save(R/'RUN_SPEC.json',spec)
    receipt=dict(schema='bit_mapping_pilot_preparation_v1',spec_sha256=sha(R/'RUN_SPEC.json'),assets=len(names),tests_passed=int(count[1]),python=sys.version.split()[0],model_calls=0,eda_calls=0,stdout=checked.stdout,stderr=checked.stderr)
    save(R/'PREPARATION_RECEIPT.json',receipt)
    pack=R/'raw_evidence/preparation_v1.zip'
    with zipfile.ZipFile(pack,'x',zipfile.ZIP_DEFLATED) as z:
        for name in names+['RUN_SPEC.json','PREPARATION_RECEIPT.json']:z.write(R/name,name)
    save(R/'PREPARATION_ARCHIVE.json',dict(spec_sha256=receipt['spec_sha256'],archive_sha256=sha(pack),bytes=pack.stat().st_size,files=len(names)+2))
    print(json.dumps({key:receipt[key] for key in ['spec_sha256','assets','tests_passed','model_calls','eda_calls']}))
if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ['base-commit','environment-capture','protected-groups','priority-report']:parser.add_argument('--'+name,required=True)
    args=parser.parse_args();prepare(args.base_commit,args.environment_capture,args.protected_groups,args.priority_report)
