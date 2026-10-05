"""Root-only freeze entry; no model/EDA/SSH/Git; copied original prepare is unused."""
from pathlib import Path
import argparse,datetime,hashlib,json,re,subprocess,sys,zipfile
import stability_protected
R=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
save=lambda p,v:p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
def prepare(base_commit):
    assert re.fullmatch('[0-9a-f]{40}',base_commit) and not (R/'RUN_SPEC.json').exists()
    old=json.loads((R/'raw_evidence/upstream_RUN_SPEC.json').read_bytes())
    copied=json.loads((R/'STABILITY_SOURCE_COPY.json').read_bytes())
    assert sha(R/'raw_evidence/upstream_RUN_SPEC.json')==copied['phase_spec_sha256']=='3fb1531c14b011f80ff58de559e326a4904d3fbdbcf3cdce7d6c955285860ba1'
    assert copied['copied_source_hashes']==old['source_hashes'] and len(old['source_hashes'])==44
    for n,h in copied['copied_source_hashes'].items():assert sha(R/n)==h
    c=json.loads((R/'raw_evidence/STABILITY_ENVIRONMENT_CAPTURE.json').read_bytes())
    b=json.loads((R/'raw_evidence/STABILITY_PROTECTED_GROUPS.json').read_bytes());stability_protected.validate(b)
    roots={identity:item['local_root'] for identity,item in b['groups'].items()} if sys.platform=='win32' else None
    save(R/'raw_evidence/PRE_FREEZE_PROTECTED_CHECK.json',stability_protected.check(b,roots=roots))
    assert c['model_calls']==c['eda_calls']==0 and not c['policy_installed'] and not c['task_submitted']
    assert c['dependency_hashes']==old['dependency_hashes']
    checked=subprocess.run([sys.executable,'-B','-m','unittest','test_stability','-v'],cwd=R,text=True,encoding='utf-8',capture_output=True)
    assert checked.returncode==0,checked.stdout+checked.stderr
    extras=['stability_worker.py','stability_stage.py','stability_audit.py','stability_metrics.py','stability_protected.py',
        'prepare_stability.py','test_stability.py','README_STABILITY.md','STABILITY_SOURCE_COPY.json',
        'raw_evidence/upstream_RUN_SPEC.json','raw_evidence/STABILITY_ENVIRONMENT_CAPTURE.json','raw_evidence/STABILITY_PROTECTED_GROUPS.json']
    names=sorted(set(copied['copied_source_hashes'])|set(extras))
    spec={k:old[k] for k in ['kit','model','model_pid','solve_deadline_s','judge_timeout_s','judge_supervisor_timeout_s','max_worker_requests_per_arm','retries','python_major_minor','dependencies_cloud','dependency_hashes','environment','task_ids']}
    spec.update(schema='phaseP_stability156x5_frozen_v1',identity='phase_P_stability156x5_20261005_v1',base_commit=base_commit,
        cloud_root='/workspace/team/runs/fpga_owner/phase_P_stability156x5_20261005_v1',frozen_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        arms=['P'],repetitions=5,samples_per_arm_per_task=5,expected_samples=780,max_actual_model_requests=1560,
        first_generation_replayed=False,source_hashes={n:sha(R/n) for n in names},stage_timeout_s=43200,guard_stage_timeout_s=43400,slot_minutes=735,
        minimum_disk_free_bytes=2*1024**3,compiler_tools=c['compiler_tools'],compiler_env=c['compiler_env'],udev_files=c['udev_files'],
        model_identity=c['model_identity'],protected=c['protected'],protected_source_groups_sha256=sha(R/'raw_evidence/STABILITY_PROTECTED_GROUPS.json'),
        environment_capture_sha256=sha(R/'raw_evidence/STABILITY_ENVIRONMENT_CAPTURE.json'),
        acceptance='All780 original fresh native-judged development samples, fixed156x5 denominator, original phaseP/8192/one repair/absolute300; report repeated weighted mean and all failures. No selection/retry, hidden/formal five/independent/deployment claim. Twelve-hour cap preserves incomplete failure.',
        limits=['Only approved latest phase_full156 P; all44 inference/orchestration/skill sources copied exact bytes.',
            'New wrapper only separates activity event IDs by repeat; no model payload/native policy/budget changes.',
            'Original guard/collector/official judge/dependencies preserved; one whole FIFO task; no shared model/teammate management.',
            'Each repeated sample owns separate directory; all requests/responses/native logs/physical rc retained.',
            'Actual capture is a past snapshot; root must protect/verify later semantic source group separately at admission.',
            'If cap stops before780, preserve partial evidence, no complete five or full score, no resampling.'])
    save(R/'RUN_SPEC.json',spec)
    save(R/'PREPARATION_RECEIPT.json',dict(schema='phaseP_stability_preparation_v1',assets=len(names),spec_sha256=sha(R/'RUN_SPEC.json'),returncode=checked.returncode,stdout=checked.stdout,stderr=checked.stderr,model_calls=0,eda_calls=0,stage_executed=False))
    pack=R/'raw_evidence/preparation_v1.zip'
    with zipfile.ZipFile(pack,'x',zipfile.ZIP_DEFLATED) as z:
        for n in names+['RUN_SPEC.json','PREPARATION_RECEIPT.json']:z.write(R/n,n)
    save(R/'PREPARATION_ARCHIVE.json',dict(spec_sha256=sha(R/'RUN_SPEC.json'),archive_sha256=sha(pack),bytes=pack.stat().st_size,files=len(names)+2))
    print(json.dumps(dict(spec_sha256=sha(R/'RUN_SPEC.json'),assets=len(names),model_calls=0,eda_calls=0)))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--base-commit',required=True);prepare(p.parse_args().base_commit)
