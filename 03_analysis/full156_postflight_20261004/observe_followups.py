"""Read-only follow-up observation; writes owned metadata ledger, never model/EDA."""
import datetime
import hashlib
import json
from pathlib import Path
import sys
import time

POST=Path('/workspace/team/runs/fpga_owner/full156_bundle_20261004_postflight')
PILOT=Path('/workspace/team/runs/fpga_owner/concise_output_pilot_20261004_v1')
MAP=Path('/workspace/team/runs/fpga_owner/prompt_map_contract_20261004_v1')
LEDGER=Path('/workspace/team/activity/fpga_owner')
TICKETS=Path('/workspace/team/task_fifo/tickets')


def read(path):return json.loads(Path(path).read_text())
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sync(activity):
    spec=sha(PILOT/'RUN_SPEC.json')
    received=0;accepted=0
    for p in sorted((PILOT/'samples').glob('*/*/worker/requests.json')):
        arm,task=p.parent.parent.parent.name,p.parent.parent.name
        for entry in read(p):
            assert entry['replayed'] is False
            if not entry['response_received']:continue
            folder=p.parent/'requests'/str(entry['index']);response=folder/'response.json';request=folder/'request.json'
            assert sha(response)==entry['response_sha256'] and sha(request)==entry['request_sha256']
            payload=read(response);choice=payload['choices'][0];usage=payload.get('usage') or {}
            received+=1
            activity.append(LEDGER,'calls',f"call:{PILOT.name}:{spec}:{task}:{arm}:{entry['index']}:{entry['response_sha256']}",
                f"模型调用已收回复：精简输出实验 / {task} / {arm} / round{entry['index']}",
                dict(experiment=PILOT.name,source_spec_sha256=spec,task=task,arm=arm,round=entry['index'],
                    response_id=payload.get('id'),finish_reason=choice.get('finish_reason'),
                    tokens_in=usage.get('prompt_tokens'),tokens_out=usage.get('completion_tokens'),
                    request_elapsed_s=entry.get('elapsed_s'),request_sha256=entry['request_sha256'],
                    response_sha256=entry['response_sha256'],request_path=str(request),response_path=str(response),
                    timestamp_scope='observation time; request duration is journaled, not a fabricated start time'))
    for p in sorted((PILOT/'samples').glob('*/*/accepted_row.json')):
        row=read(p)
        if 'arm' not in row:continue
        accepted+=1
        activity.append(LEDGER,'conclusions',f"sample:{PILOT.name}:{spec}:{row['arm']}:{row['task']}:{row['solution_sha256']}",
            f"逐样本：精简输出 / {row['task']} / {row['arm']} / L{row['verdict']['level']}；尚非完整阶段结论",
            dict(experiment=PILOT.name,source_spec_sha256=spec,task=row['task'],arm=row['arm'],
                level=row['verdict']['level'],solve_s=row['solve_elapsed_s'],
                request_attempts=row['actual_model_requests'],confirmed_responses=row['received_model_responses'],
                solve_deadline=row['solve_deadline_reached'],solution_sha256=row['solution_sha256'],evidence_path=str(p),
                scope='one known public pilot sample; not full156/adoption/independent validation'))
    pilot=read(PILOT/'queue_status.json')
    map_report=read(MAP/'results/summary.json') if (MAP/'results/summary.json').exists() else {}
    controller=read(POST/'continuation_status.json')
    tickets=[]
    for p in sorted(TICKETS.glob('*.json')):
        item=read(p);tickets.append({k:item.get(k) for k in ('ticket','task_name','state','error')})
    if map_report:
        activity.append(LEDGER,'conclusions',f"map-control-progress:{MAP.name}:{sha(MAP/'RUN_SPEC.json')}:{map_report['probe_executions']}:{map_report['synth_executions']}",
            f"表格校准进度：已返回{map_report['probe_executions']}个probe／{map_report['synth_executions']}个综合；0模型调用，待完整审计",
            dict(experiment=MAP.name,probe_executions=map_report['probe_executions'],
                synth_executions=map_report['synth_executions'],complete=map_report['complete'],passed=map_report['passed'],
                error=map_report.get('error'),evidence_path=str(MAP/'results/summary.json'),
                scope='known public replay plus constructed controls, no new score or model repair'))
    now=datetime.datetime.now(datetime.timezone.utc).isoformat()
    snapshot=dict(schema='owned_followup_activity_v1',observed_at_utc=now,full156_complete_audited=True,
        full_scores={'A':.7692,'C':.7641},full_C_adoption=False,
        pilot_state=pilot['state'],pilot_samples=pilot['completed_samples'],pilot_expected_samples=24,
        pilot_received_responses=received,pilot_accepted_rows=accepted,current_task=pilot.get('current_task'),
        current_arm=pilot.get('current_arm'),pilot_full_audit_available=(POST/'concise24_audit/RESULTS.json').exists(),
        calibration_complete=map_report.get('complete',False),calibration_passed=map_report.get('passed',False),
        calibration_probes=map_report.get('probe_executions',0),calibration_synths=map_report.get('synth_executions',0),
        controller_state=controller['state'],fifo=tickets,scope='own follow-ups only, not all server calls')
    temporary=LEDGER/'SNAPSHOT.json.followup.pending';temporary.write_text(json.dumps(snapshot,ensure_ascii=False,indent=2)+'\n');temporary.replace(LEDGER/'SNAPSHOT.json')
    text='# 当前自主优化与调用台账\n\n更新时间：'+now+'（UTC）\n\n'
    text+='完整156题A/C已结束并经双端审计：A0.7692／C0.7641，工具错误0，C实际改变0，**不采用helper**。这是公开集每臂1样本，不是比赛总分／五样本或隐藏题。最终证据：'+str(POST/'full312_audit/RESULTS.json')+'。\n\n'
    text+=f"精简输出实验：{pilot['state']}，**{pilot['completed_samples']}/24** 样本，已收 **{received}** 回复；当前{pilot.get('current_task')} / {pilot.get('current_arm')}。完整审计：{'已生成' if snapshot['pilot_full_audit_available'] else '未生成'}，没有自动部署。\n\n"
    text+=f"表格校准：{snapshot['calibration_probes']}/36 probe，{snapshot['calibration_synths']}/8 正稿综合；完成={snapshot['calibration_complete']}，有效={snapshot['calibration_passed']}。0模型，4已知公开归档＋4构造组；待完整证据审计，尚无模型修复／独立自然题收益。\n\n"
    text+='| FIFO票 | 整任务 | 状态 |\n|---|---|---|\n'
    for item in tickets:text+=f"| {item['ticket']} | {item['task_name']} | {item['state']} |\n"
    text+='\n调用：calls.jsonl；修改：changes.jsonl；结果与范围：conclusions.jsonl。只记自己的阶段元数据，正文／参考／账号信息不入台账。实例／共享模型／队友文件不改。\n'
    temporary=LEDGER/'STATUS.md.followup.pending';temporary.write_text(text);temporary.replace(LEDGER/'STATUS.md')
    return pilot,map_report,controller


def main():
    # The earlier full-run observer naturally exited on completion. Do not start
    # this writer until the earlier queue is authoritatively terminal.
    full=read(Path('/workspace/team/runs/fpga_owner/full156_bundle_20261004_v1/queue_status.json'))
    assert full['complete'] and full['state']=='complete'
    sys.path.insert(0,'/workspace/team/tools/task-fifo-20261004');import activity
    deadline=time.monotonic()+14400
    while time.monotonic()<deadline:
        pilot,map_report,controller=sync(activity)
        done=pilot['complete'] or pilot['state']=='stopped_with_evidence'
        if done and (map_report.get('complete') or map_report.get('error')) and (controller['complete'] or controller['state']=='stopped_with_evidence'):return
        time.sleep(30)


if __name__=='__main__':main()
