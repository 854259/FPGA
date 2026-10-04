"""Six actual fresh A/C samples; pinned external judge, no deployment."""
import argparse
import ctypes
import json
from pathlib import Path
import sys
import time
from worker import load,save,sha
import metrics

ROOT=Path(__file__).resolve().parent


def frozen(kit):
    spec=json.loads((ROOT/'RUN_SPEC.json').read_text())
    for n,h in spec['source_hashes'].items():assert sha(ROOT/n)==h,n
    for n,h in spec['dependency_hashes'].items():assert sha(Path(spec['dependencies_cloud'])/n)==h,n
    inputs=json.loads((ROOT/'INPUT_MANIFEST.json').read_text())
    for n,h in inputs['input_sha256'].items():assert sha(kit/'bench/tasks_veval'/n)==h,n
    for n,h in inputs['official_sha256'].items():assert sha(kit/'official_reference'/n)==h,n
    return spec


def judge(args):
    spec=frozen(args.kit);args.out.mkdir(parents=True,exist_ok=False)
    evaluator=load('fresh_external_judge',ROOT/'official_eval_guarded.py');evaluator.OFFICIAL=args.kit/'official_reference'
    verdict=evaluator.judge_sample(args.kit/'bench/tasks_veval'/args.task,args.solution,args.out,args.out/'verdict.json',spec['judge_timeout_s'])
    assert not verdict.get('tool_error') and verdict['task_id']==args.task and verdict['judge_evidence_complete']
    save(args.out/'bound_verdict.json',dict(solution_sha256=sha(args.solution),verdict_sha256=sha(args.out/'verdict.json'),verdict=verdict))


def publish(report):
    ledger=Path('/workspace/team/activity/fpga_owner')
    save(ledger/'SNAPSHOT.json',dict(observed_at_epoch=time.time(),experiment=str(ROOT),completed_samples=len(report['rows']),
        expected_samples=312,actual_model_requests=report['actual_model_requests'],complete=report['complete'],audit_pending=True,
        first_generation_replayed=False,adoption=False,new_full_score=False))
    text='# 两类功能反馈完整156题回归\n\n原完整结果A0.7692/C0.7641，旧helper拒绝；真实新生成三题小阶段已审计通过。\n\n'
    text+='当前'+str(len(report['rows']))+'/312完整样本；实际模型请求'+str(report['actual_model_requests'])+'；结束='+str(report['complete'])+'。\n\n'
    text+='每臂156题，每题1次真实首生成，原一次修复/8192token/300秒/原技能与抽取。两类有界题面规则，仅支持3题，其余保持原流程。外侧原生官方判定。完整同预算回归终态审计前不公布新分，不部署；不是独立隐藏题/五样本。\n'
    text+='整个任务FIFO，调用/修改/结论台账共享；不改共享模型/实例/正式部署/队友。证据：'+str(ROOT)+'\n'
    temp=ledger/'STATUS.md.full.pending';temp.write_text(text);temp.replace(ledger/'STATUS.md')


def main(args):
    assert sys.platform=='linux' and ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)==0
    spec=frozen(args.kit);paired=load('fresh_owned',Path(spec['dependencies_cloud'])/'paired_checkpoint.py')
    paired.REPO=ROOT;paired.INHERITED_ORACLE=Path(spec['dependencies_cloud'])/'probe_runner.py'
    paired.check_resource(args.resource_check,args.kit,first=True)
    for name in ['PRIORITY_CALIBRATION_AUDIT.json','SHIFT_CALIBRATION_AUDIT.json']:
        receipt=json.loads((ROOT/name).read_text());assert receipt['evidence_valid'] and receipt['controls_valid'] and receipt['natural_hypothesis_matched']
    prereq=json.loads((ROOT/'FRESH_PILOT_AUDIT.json').read_text());assert prereq['evidence_valid'] and prereq['candidate_qualified_for_full_regression']
    assert json.loads((ROOT/'BOUNDARY_RECONCILIATION.json').read_text())['passed']
    assert len(spec['task_ids'])==156 and spec['task_ids']==sorted(spec['task_ids'])
    out=ROOT/'results';out.mkdir(exist_ok=False);started=time.monotonic()
    report=dict(schema='functional_full156_v1',complete=False,passed=False,spec_sha256=sha(ROOT/'RUN_SPEC.json'),rows=[],
        actual_model_requests=0,first_generation_replayed=False,adoption=False,new_full_score=False,scope='All public156 tasks, 1 fresh sample/arm, no independent hidden or five-sample claim')
    save(out/'summary.json',report);publish(report)
    def gate():
        frozen(args.kit);paired.check_resource(args.resource_check,args.kit)
        assert time.monotonic()-started<spec['stage_timeout_s']-60
    try:
        for index,task in enumerate(spec['task_ids']):
            for arm in (['A','C'] if index%2==0 else ['C','A']):
                assert not (ROOT/'STOP_AFTER_CURRENT').exists(),'Boundary stop requested'
                gate();sample=out/'samples'/arm/task;sample.mkdir(parents=True,exist_ok=False)
                argv=[sys.executable,'-B',str(ROOT/'worker.py'),'--out',str(sample/'worker'),'--task',task,'--arm',arm,'--kit',str(args.kit),'--resource-check',str(args.resource_check)]
                command=paired.owned_command(argv,ROOT,sample/'worker.log',spec['solve_deadline_s']);command['argv']=argv;save(sample/'worker_command.json',command)
                assert not command['launch_error'] and not command['remaining_live_group']
                # An exhausted solver budget is measured, never canceled by killing the model.
                assert command['timeout'] or command['returncode']==0
                if command['timeout']:
                    until=time.monotonic()+120
                    while True:
                        try:paired.model_idle('http://127.0.0.1:8000/v1',spec['model']);break
                        except RuntimeError:
                            assert time.monotonic()<until,'Model request did not drain';time.sleep(2)
                journal=json.loads((sample/'worker/requests.json').read_text())
                assert 1<=len(journal)<=2 and all(not r['replayed'] for r in journal)
                report['actual_model_requests']+=len(journal);assert report['actual_model_requests']<=spec['max_actual_model_requests']
                gate()
                argv=[sys.executable,'-B',str(ROOT/'pilot.py'),'judge','--task',task,'--solution',str(sample/'worker/solution.v'),'--out',str(sample/'judge'),'--kit',str(args.kit)]
                result=paired.owned_command(argv,ROOT,sample/'judge.log',360);result['argv']=argv;save(sample/'judge_command.json',result)
                assert result['returncode']==0 and not result['timeout'] and not result['remaining_live_group']
                bound=json.loads((sample/'judge/bound_verdict.json').read_text())
                row=dict(task=task,arm=arm,solve_deadline_reached=command['timeout'],solve_elapsed_s=command['elapsed_s'],
                    actual_model_requests=len(journal),received_model_responses=sum(r['response_received'] for r in journal),
                    solution_sha256=bound['solution_sha256'],verdict_sha256=bound['verdict_sha256'],verdict=bound['verdict'])
                save(sample/'row.json',row);report['rows'].append(row);save(out/'summary.json',report);publish(report)
        gate()
        scorer=load('full_pinned_official_score',args.kit/'official_reference/selftest/score.py')
        aggregate=metrics.aggregate(report['rows'],spec['task_ids'],scorer)
        report.update(complete=True,passed=True,**aggregate)

    except BaseException as e:report['error']=type(e).__name__+': '+str(e)
    finally:
        report['elapsed_s']=time.monotonic()-started;save(out/'summary.json',report);publish(report)
    sys.path.insert(0,'/workspace/team/tools/task-fifo-20261004');import activity
    activity.append(Path('/workspace/team/activity/fpga_owner'),'conclusions','functional-fresh-stage:'+spec['identity'],
        '完整156题A/C阶段结束；终态证据审计前不发布新分，不部署；不是独立隐藏/五样本。',{k:v for k,v in report.items() if k!='rows'})
    return 0 if report['passed'] else 1


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['stage','judge'])
    p.add_argument('--kit',required=True,type=Path);p.add_argument('--resource-check',type=Path)
    p.add_argument('--task');p.add_argument('--solution',type=Path);p.add_argument('--out',type=Path)
    args=p.parse_args();raise SystemExit(main(args) if args.phase=='stage' else judge(args))
