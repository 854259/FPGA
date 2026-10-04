"""Frozen four-checkpoint A/C causal probe; no new first generation."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import sys
import time
from worker import load, sha, save

ROOT = Path(__file__).resolve().parent


def publish(report):
    ledger=Path('/workspace/team/activity/fpga_owner')
    save(ledger/'SNAPSHOT.json',dict(schema='owned_map_feedback_activity_v1',
        observed_at_epoch=time.time(),experiment=str(ROOT),completed_workers=len(report['rows']),
        expected_workers=8,actual_model_requests=report['actual_model_requests'],
        complete=report['complete'],passed=report['passed'],audit_pending=True,
        formal_deployment_changed=False,scope='owned checkpoint stage only; bodies excluded'))
    text='# 自主优化当前阶段\n\n156题A0.7692/C0.7641：不采用helper。精简输出12题A0.70/C0.65：两项回归，拒绝。表格检查36仿真/8综合校准已审计有效。\n\n'
    text+='当前完整care表反馈同首回复A/C阶段：'+str(len(report['rows']))+'/8 worker；新增已收模型回复'+str(report['actual_model_requests'])+'；完成='+str(report['complete'])+'。\n\n'
    text+='4已知公开归档题、每臂最多原一次修复；首生成回放成本不计入，不是新生成或独立成绩。结束后仍须完整证据审计，不自动部署。\n\n调用calls.jsonl；修改changes.jsonl；阶段结论conclusions.jsonl。证据目录：'+str(ROOT)+'\n'
    tmp=ledger/'STATUS.md.map.pending';tmp.write_text(text);tmp.replace(ledger/'STATUS.md')


def main():
    p=argparse.ArgumentParser();p.add_argument('--kit',type=Path,required=True)
    p.add_argument('--resource-check',type=Path,required=True);a=p.parse_args()
    assert sys.platform=='linux' and ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)==0
    spec=json.loads((ROOT/'RUN_SPEC.json').read_text())
    paired=load('map_pilot_owned',Path(spec['dependencies_cloud'])/'paired_checkpoint.py')
    paired.REPO=ROOT;paired.INHERITED_ORACLE=Path(spec['dependencies_cloud'])/'probe_runner.py'
    def gate():
        for name,h in spec['source_hashes'].items():assert sha(ROOT/name)==h,name
        for name,h in spec['dependency_hashes'].items():assert sha(Path(spec['dependencies_cloud'])/name)==h
        paired.check_resource(a.resource_check,a.kit)
    paired.check_resource(a.resource_check,a.kit,first=True);gate()
    out=ROOT/'results';out.mkdir(exist_ok=False)
    report=dict(schema='prompt_map_table_checkpoint_paired_v1',complete=False,passed=False,
        spec_sha256=sha(ROOT/'RUN_SPEC.json'),rows=[],actual_model_requests=0,
        max_actual_model_requests=8,first_generation_replayed=True,first_generation_cost_measured=False,
        adoption=False,new_full_score=False,scope='4 known public archived checkpoints, not independent natural validation')
    prerequisite=json.loads((ROOT/'CALIBRATION_AUDIT.json').read_text())
    assert prerequisite['evidence_valid'] and prerequisite['controls_valid'] and prerequisite['natural_hypothesis_matched']
    assert prerequisite['archive_sha256']==spec['prerequisite_calibration_archive_sha256']
    boundary=json.loads((ROOT/'BOUNDARY_RECONCILIATION.json').read_text())
    assert boundary['passed'] and boundary['false_accepts']==0 and boundary['calibrated_contracts_preserved']==8
    assert boundary['parser_sha256']==sha(ROOT/'prompt_map.py')
    started=time.monotonic();publish(report)
    try:
        for index,task in enumerate(spec['task_ids']):
            for arm in (['A','C'] if index%2==0 else ['C','A']):
                assert not (ROOT/'STOP_AFTER_CURRENT').exists(),'Boundary stop requested'
                gate();rowdir=out/'workers'/task/arm;rowdir.parent.mkdir(parents=True,exist_ok=True)
                argv=[sys.executable,'-B',str(ROOT/'worker.py'),'--out',str(rowdir),
                    '--task',task,'--arm',arm,'--kit',str(a.kit),'--resource-check',str(a.resource_check)]
                supervised=paired.owned_command(argv,ROOT,rowdir.parent/(arm+'.supervisor.log'),300)
                supervised['argv']=argv
                assert supervised['returncode']==0 and not supervised['timeout'] and not supervised['remaining_live_group']
                worker=json.loads((rowdir/'worker_result.json').read_text())
                report['actual_model_requests']+=worker['actual_model_requests']
                assert report['actual_model_requests']<=8
                contract=json.loads((ROOT/'raw_evidence/inputs'/task/'contract.json').read_text())
                probe=paired.oracle(dict(task=task,checks=contract['checks'],tb='raw_evidence/inputs/'+task+'/tb.sv'),
                    rowdir/'solution.v',out/'final_probes'/task/arm)
                assert probe['failure_kind'] in (None,'semantic_mismatch'), 'Unusable final probe; preserve failure'
                row=dict(task=task,arm=arm,worker=worker,supervisor=supervised,probe=probe)
                report['rows'].append(row);save(out/'summary.json',report);publish(report)
        pairs={t:{r['arm']:r for r in report['rows'] if r['task']==t} for t in spec['task_ids']}
        repairs=[t for t,pair in pairs.items() if pair['A']['probe']['status']=='fail' and pair['C']['probe']['status']=='pass']
        regressions=[t for t,pair in pairs.items() if pair['A']['probe']['status']=='pass' and pair['C']['probe']['status']!='pass']
        correct=spec['correct_guard'];preserved=pairs[correct]['C']['worker']['solution_sha256']==pairs[correct]['A']['worker']['solution_sha256']
        report.update(complete=True,passed=True,repairs=repairs,regressions=regressions,
            correct_guard_unchanged=preserved,candidate_qualified_for_fresh_generation=len(repairs)>=2 and not regressions and preserved)
    except BaseException as e:
        report['error']=type(e).__name__+': '+str(e)
    finally:
        report['elapsed_s']=time.monotonic()-started;save(out/'summary.json',report);publish(report)
    sys.path.insert(0,'/workspace/team/tools/task-fifo-20261004');import activity
    activity.append(Path('/workspace/team/activity/fpga_owner'),'conclusions','map-feedback-stage:'+spec['identity'],
        '完整care表与实际反例同首回复阶段结束；待原始证据审计，不自动部署。',
        {k:v for k,v in report.items() if k!='rows'})
    return 0 if report['passed'] else 1


if __name__=='__main__':raise SystemExit(main())
