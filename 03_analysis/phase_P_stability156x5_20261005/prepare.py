"""Same inference assets as qualified fresh phase58; freeze full312, no model/EDA."""
from pathlib import Path
import datetime,hashlib,json,subprocess,sys,zipfile
R=Path(__file__).resolve().parent;P=R.parent/'phase_feedback_pilot_20261005'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_bytes())
def save(p,v):p.write_bytes((json.dumps(v,ensure_ascii=False,indent=2)+'\n').encode())
if __name__=='__main__':
    assert sys.version_info[:2]==(3,12) and not (R/'RUN_SPEC.json').exists()
    old=read(P/'RUN_SPEC.json');a=read(P/'terminal_audit_v1/RESULTS.json')
    assert a['evidence_valid'] and a['qualified_for_new_full_regression'] and a['matched_native_repair_tasks']==['Prob045_edgedetect2','Prob054_edgedetect']
    assert sha(R/'FRESH_PILOT_AUDIT.json')==sha(P/'terminal_audit_v1/RESULTS.json')
    copy=read(R/'COPY_RECEIPT.json');copy['identical_assets'].pop('test_stage.py',None);copy['replaced_stage_test']='test_full.py proves original scheduling extends to all312 rather than old16';save(R/'COPY_RECEIPT.json',copy)
    for n,h in copy['identical_assets'].items():assert sha(R/n)==h,n
    # Deterministic full-cohort applicability; never derived from references or official TB.
    import edge_dispatch,prompt_map
    with zipfile.ZipFile(P/'raw_evidence/terminal_v1.zip') as z:
        public_inputs=read(R/'INPUT_MANIFEST.json');tasks=sorted({n.split('/')[0] for n in public_inputs['input_sha256']});assert len(tasks)==156
    # The already frozen full archive carries original prompt/interface bytes for all156.
    exposure=[]
    full=R.parent/'functional_full156_20261005/raw_evidence/terminal_v1.zip'
    assert sha(full)=='ac3b27f553bbf274d2edc875a7a3354b42741a9861ca409b37b779d1c6067055'
    with zipfile.ZipFile(full) as z:
        for t in tasks:
            prefix='kit/bench/tasks_veval/'+t+'/'
            prompt=z.read(prefix+'prompt.txt').decode();interface=z.read(prefix+'interface.txt').decode() if t+'/interface.txt' in public_inputs['input_sha256'] else ''
            assert hashlib.sha256(z.read(prefix+'prompt.txt')).hexdigest()==public_inputs['input_sha256'][t+'/prompt.txt']
            if t+'/interface.txt' in public_inputs['input_sha256']:assert hashlib.sha256(z.read(prefix+'interface.txt')).hexdigest()==public_inputs['input_sha256'][t+'/interface.txt']
            if interface.strip():prompt+='\n\nInterface:\n'+interface
            c=prompt_map.parse(prompt);p=edge_dispatch.parse(prompt)
            exposure.append(dict(task=t,C_status=c['status'],P_status=p['status'],P_family=p.get('family'),new_edge=p.get('family')=='edge' and p['status']=='supported' and c['status']!='supported'))
    assert [v['task'] for v in exposure if v['new_edge']]==['Prob045_edgedetect2','Prob054_edgedetect']
    save(R/'APPLICABILITY.json',dict(schema='full_prompt_only_dispatch_v1',input_files=936,official_files=35,tasks=156,rows=exposure,newly_supported=2,remaining_dispatch_identical=154,model_calls=0,eda_calls=0))
    tests=subprocess.run([sys.executable,'-B','-m','unittest','discover','-v'],cwd=R,text=True,encoding='utf-8',capture_output=True);assert tests.returncode==0 and 'Ran 39 tests' in tests.stderr,tests.stdout+tests.stderr
    names=sorted(p.relative_to(R).as_posix() for p in R.rglob('*') if p.is_file() and '__pycache__' not in p.parts and not p.is_relative_to(R/'raw_evidence') and (p.suffix=='.py' or p.is_relative_to(R/'package')))
    names+=['COPY_RECEIPT.json','FRESH_PILOT_AUDIT.json','CALIBRATION_AUDIT.json','INPUT_MANIFEST.json','REVIEW_RESULTS.json','APPLICABILITY.json','UNFROZEN_FAILURES.json','raw_evidence/test_fixtures/priority.txt','raw_evidence/test_fixtures/shift.txt','raw_evidence/test_fixtures/score.py','raw_evidence/test_fixtures/phase_observation.json'];names=sorted(set(names))
    s={k:old[k] for k in ['kit','model','model_pid','solve_deadline_s','judge_timeout_s','judge_supervisor_timeout_s','max_worker_requests_per_arm','retries','python_major_minor','dependencies_cloud','dependency_hashes','environment']}
    s.update(schema='phase_full156_frozen_v1',identity='phase_full156_20261005_v1',cloud_root='/workspace/team/runs/fpga_owner/phase_full156_20261005_v1',base_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=R,text=True).strip(),frozen_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),task_ids=tasks,arms=['C','P'],samples_per_arm_per_task=1,expected_samples=312,max_actual_model_requests=624,stage_timeout_s=86400,slot_minutes=1470,first_generation_replayed=False,source_hashes={n:sha(R/n) for n in names},fresh_pilot_spec_sha256=sha(P/'RUN_SPEC.json'),fresh_pilot_archive_sha256=a['archive_sha256'],fresh_pilot_audit_sha256=sha(R/'FRESH_PILOT_AUDIT.json'),old_full_gate_failed_preserved=True,phase_source_sha256=sha(R/'phase_context.py'),minimum_disk_free_bytes=2*1024**3,acceptance='All312 complete at original once-repair 8192/300 budgets; full156 denominator and original native judge, no tools/deadlines/unconfirmed or per-task regression, higher P coefficient or equal coefficient with fewer calls, P adds at most2 requests total. Two edge gains must bind same first response to native failure, actual original repair payload and final native+officialL3; permits faithful independent model validation only, no deployment/five/offline/target-hardware certification.',limits=old['limits']+['All156 known public development tasks, one fresh C/P sample per arm; no resampling, reply replay, retries or best-of. All per-task outcomes and costs retained.','Fresh pilot gate preserved; old full156 A/C three deadlines remain failed, new independent gate requires complete fresh C/P proof.','Original C/P inference sources and skills identical to phase58, only full orchestration/aggregate/audit change. New edge support2, remaining154 dispatch preserved.','24-hour stage and1470-minute lease are safety caps, not ETA. At least2GiB free required between samples. No automatic removal of teammate artifacts or model changes.'])
    save(R/'RUN_SPEC.json',s);receipt=dict(schema='phase_full312_preparation_v1',spec_sha256=sha(R/'RUN_SPEC.json'),assets=len(names),identical_pilot_assets=len(copy['identical_assets']),local_checks=39,python=sys.version.split()[0],model_calls=0,eda_calls=0,full_stage_executed=False,stdout=tests.stdout,stderr=tests.stderr);save(R/'PREPARATION_RECEIPT.json',receipt)
    pack=R/'raw_evidence/preparation_v1.zip'
    with zipfile.ZipFile(pack,'x',zipfile.ZIP_DEFLATED) as z:
        for n in names+['RUN_SPEC.json','PREPARATION_RECEIPT.json']:z.write(R/n,n)
    save(R/'PREPARATION_ARCHIVE.json',dict(archive_sha256=sha(pack),bytes=pack.stat().st_size,files=len(names)+2,spec_sha256=receipt['spec_sha256']))
    print(json.dumps({k:receipt[k] for k in ['spec_sha256','assets','identical_pilot_assets','local_checks','model_calls','eda_calls']}))
