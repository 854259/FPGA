"""Owned continuation: full evidence audit, then one frozen FIFO pilot. No retries."""
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


ROOT = Path(__file__).resolve().parent
RUN = Path('/workspace/team/runs/fpga_owner/full156_bundle_20261004_v1')
PILOT = Path('/workspace/team/runs/fpga_owner/concise_output_pilot_20261004_v1')
FIFO = Path('/workspace/team/tools/task-fifo-20261004')
FULL_SPEC = '200ec12684229812029466ae5ffd1c63f461b9afa494a51e389d6377ee710e0b'
PILOT_SPEC = '105d05a41f304be3e5e029949c6bdf352d4dfc919c0aab8f7fa3922274d20398'
TOOLS = {'collect_evidence.py':'7b59d5ac6d503370aa11fbee65f33d03dc9c4f8408477780874a4c44841e6ece',
         'audit.py':'6b141e6da0bac31fd2a3f00ed448f5f600eabe327eaa93594259d760f8d07ba3'}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def save(path, data):
    temporary = Path(str(path)+'.pending')
    temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    temporary.replace(path)


def main():
    status_path = ROOT/'continuation_status.json'
    assert not status_path.exists(), 'Never resubmit/retry a partial continuation silently'
    status = dict(schema='full156_owned_continuation_v1',complete=False,state='waiting_for_full156',
        pid=os.getpid(),started_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        model_calls=0,eda_calls=0,formal_deployment_changed=False,instance_or_model_managed=False)
    save(status_path,status)
    sys.path.insert(0,str(FIFO))
    import activity
    ledger=Path('/workspace/team/activity/fpga_owner')
    deadline=time.monotonic()+7200
    def check():
        assert not (ROOT/'STOP_AUTONOMOUS').exists(), 'Authorized boundary stop requested'
        assert time.monotonic()<deadline, 'Continuation admission window expired'
        assert sha(RUN/'RUN_SPEC.json')==FULL_SPEC
        assert sha(PILOT/'RUN_SPEC.json')==PILOT_SPEC
        for name,h in TOOLS.items():assert sha(ROOT/name)==h,name
        for name,h in read(PILOT/'RUN_SPEC.json')['source_hashes'].items():assert sha(PILOT/name)==h,name
        for name,h in read(PILOT/'PREPARATION_RECEIPT.json')['postflight_hashes'].items():assert sha(PILOT/name)==h,name
    try:
        while True:
            check()
            queue=read(RUN/'queue_status.json')
            assert queue['state']!='stopped_with_evidence',queue
            status['completed_full_samples']=queue['completed_samples']
            save(status_path,status)
            if queue['complete']:
                assert queue['state']=='complete' and queue['completed_samples']==312
                break
            time.sleep(30)
        check()
        archive=ROOT/'full312.zip';audit_out=ROOT/'full312_audit'
        assert not archive.exists() and not audit_out.exists()
        status['state']='collecting_full_evidence';save(status_path,status)
        with (ROOT/'full312_collect.log').open('xb') as log:
            subprocess.run([sys.executable,'-B',str(ROOT/'collect_evidence.py'),
                '--run-root',str(RUN),'--archive',str(archive)],stdout=log,stderr=subprocess.STDOUT,check=True)
        status.update(state='auditing_full_evidence',archive_sha256=sha(archive));save(status_path,status)
        with (ROOT/'full312_audit.log').open('xb') as log:
            subprocess.run([sys.executable,'-B',str(ROOT/'audit.py'),
                '--archive',str(archive),'--out',str(audit_out)],stdout=log,stderr=subprocess.STDOUT,check=True)
        result=read(audit_out/'RESULTS.json')
        assert result['evidence_valid'] and result['full_round_complete'] and result['snapshot_samples']==312
        assert result['archive_sha256']==sha(archive)
        assert all(x['scored_tasks']==156 and x['tool_errors']==0 for x in result['scores'].values())
        activity.append(ledger,'conclusions','full312-offline-audit-v1',
            '312样本完整回归与离线证据审计完成；A/C为单样本已知公开题结果，不是比赛总分或部署',
            dict(result_path=str(audit_out/'RESULTS.json'),result_sha256=sha(audit_out/'RESULTS.json'),
                archive_sha256=sha(archive),scores=result['scores'],totals=result['totals'],decision=result['decision'],
                helper_changed_samples=sum(bool(x['changed_extractions']) for x in result['rows'] if x['arm']=='C'),
                independent_validation=False,adoption=False))
        check()
        # Full run has ended. FIFO may still be retiring its reservation; submit
        # normally so any teammate already queued is respected. Never release it.
        assert not (PILOT/'queue_status.json').exists() and not (PILOT/'SUBMISSION.json').exists()
        env=dict(os.environ,MODEL_NAME='Qwen3.6-27B-Q4_K_M',LLM_BASE_URL='http://127.0.0.1:8000/v1',
                 VIVADO_BIN='/workspace/AMD/2026.1/Vivado/bin',RTL_REPAIRS='1',RTL_MAX_TOKENS='8192',RTL_TEMPERATURE='0')
        env['PATH']='/workspace/AMD/2026.1/Vivado/bin:'+env.get('PATH','')
        # Matches the observed frozen full-run environment; avoid changing EDA
        # library behavior as a second experimental variable.
        env['LD_LIBRARY_PATH']='/workspace/team/udev-stub'
        command=[sys.executable,'-B',str(FIFO/'task_fifo.py'),'submit','--task-name','concise_output_12task_v1',
            '--cwd',str(PILOT),'--completion-json',str(PILOT/'queue_status.json'),
            '--slot-owner-prefix','fpga_owner_concise_output_','--',
            sys.executable,'-B',str(PILOT/'evaluate_batch.py'),'queue']
        submitted=subprocess.run(command,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        (ROOT/'pilot_submit.stdout.log').write_text(submitted.stdout)
        (ROOT/'pilot_submit.stderr.log').write_text(submitted.stderr)
        assert submitted.returncode==0, 'Submission failed; preserve stdout/stderr, do not retry automatically'
        receipt=json.loads(submitted.stdout)
        receipt.update(source_spec_sha256=PILOT_SPEC,prior_full_archive_sha256=sha(archive),
            prior_full_audit_sha256=sha(audit_out/'RESULTS.json'),queue_submission_not_actual_start=True)
        save(PILOT/'SUBMISSION.json',receipt)
        save(PILOT/'LAUNCH.json',dict(schema='concise_output_fifo_submission_v1',**receipt))
        activity.append(ledger,'changes','concise-output-pilot-submitted-v1',
            '完整156题审计后提交12题源码无注释单因素FIFO实验；原抽取／复查保持，helper追加关闭，尚无收益结论',
            dict(receipt=receipt,source_directory=str(PILOT),planned_samples=24,max_request_attempts=48,
                formal_deployment_changed=False,model_changed=False,teammate_files_changed=False))
        status.update(state='full_audited_pilot_submitted',submission=receipt,
            full_result_path=str(audit_out/'RESULTS.json'));save(status_path,status)
        watch_deadline=time.monotonic()+14400
        while True:
            if (ROOT/'STOP_AUTONOMOUS').exists():
                (PILOT/'STOP_AFTER_CURRENT').write_text('Owned continuation boundary stop; preserve model/server\n')
                raise RuntimeError('Stopped future stages; own pilot will stop between samples')
            assert time.monotonic()<watch_deadline,'Pilot observation window exhausted; no restart or process killing'
            if (PILOT/'queue_status.json').exists():
                pilot_queue=read(PILOT/'queue_status.json')
                assert pilot_queue['state']!='stopped_with_evidence',pilot_queue
                status.update(state='observing_pilot',completed_pilot_samples=pilot_queue['completed_samples'],
                    current_task=pilot_queue.get('current_task'),current_arm=pilot_queue.get('current_arm'))
                save(status_path,status)
                if pilot_queue['complete']:
                    assert pilot_queue['state']=='complete' and pilot_queue['completed_samples']==24
                    break
            time.sleep(30)
        for name,h in read(PILOT/'PREPARATION_RECEIPT.json')['postflight_hashes'].items():assert sha(PILOT/name)==h,name
        pilot_archive=ROOT/'concise24.zip';pilot_audit=ROOT/'concise24_audit'
        assert not pilot_archive.exists() and not pilot_audit.exists()
        for name,argv in (
            ('pilot_collect',[str(PILOT/'collect_evidence.py'),'--run-root',str(PILOT),'--archive',str(pilot_archive)]),
            ('pilot_audit',[str(PILOT/'audit.py'),'--archive',str(pilot_archive),'--out',str(pilot_audit)])):
            with (ROOT/(name+'.log')).open('xb') as log:
                subprocess.run([sys.executable,'-B',*argv],stdout=log,stderr=subprocess.STDOUT,check=True)
        pilot_result=read(pilot_audit/'RESULTS.json')
        assert pilot_result['evidence_valid'] and pilot_result['pilot_complete']
        assert pilot_result['full_round_complete'] is False and pilot_result['snapshot_samples']==24
        activity.append(ledger,'conclusions','concise24-offline-audit-v1',
            '12题源码无注释单因素实验与完整证据审计结束；结论见绑定文件，不是156题成绩或已部署收益',
            dict(result_path=str(pilot_audit/'RESULTS.json'),result_sha256=sha(pilot_audit/'RESULTS.json'),
                archive_sha256=sha(pilot_archive),diagnostic_scores=pilot_result['diagnostic_scores'],
                totals=pilot_result['totals'],decision=pilot_result['decision'],independent_validation=False,adoption=False))
        status.update(complete=True,state='full_and_pilot_audited',pilot_result_path=str(pilot_audit/'RESULTS.json'),
            pilot_decision=pilot_result['decision'],finished_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
    except BaseException as e:
        status.update(state='stopped_with_evidence',error=type(e).__name__+': '+str(e))
        raise
    finally:
        save(status_path,status)


if __name__=='__main__':main()
