"""Six actual fresh A/C samples; pinned external judge, no deployment."""
import argparse
import ctypes
import json
from pathlib import Path
import sys
import time
from worker import load,save,sha

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
        expected_samples=6,actual_model_requests=report['actual_model_requests'],complete=report['complete'],audit_pending=True,
        first_generation_replayed=False,adoption=False,new_full_score=False))
    text='# 自主优化当前阶段\n\n156题原成绩A0.7692／C0.7641，不采用旧helper；优先方向一次修复已审计，算术移位真实19 probe／6综合控制校准已审计。\n\n'
    text+='当前两类题面功能反馈的新生成A/C：'+str(len(report['rows']))+'/6样本，实际模型请求'+str(report['actual_model_requests'])+'；完成='+str(report['complete'])+'。\n\n'
    text+='全部首请求真实调用模型，无归档回复/答案回放；原技能、原抽取、300秒/8192 token/原一次修复。071/112/115三道已知开发题，非独立或全量/五样本分；官方判定仅在外侧。完整审计前不部署。\n'
    text+='调用元数据calls.jsonl，修改changes.jsonl，结论conclusions.jsonl。证据：'+str(ROOT)+'\n'
    temp=ledger/'STATUS.md.fresh.pending';temp.write_text(text);temp.replace(ledger/'STATUS.md')


def main(args):
    assert sys.platform=='linux' and ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)==0
    spec=frozen(args.kit);paired=load('fresh_owned',Path(spec['dependencies_cloud'])/'paired_checkpoint.py')
    paired.REPO=ROOT;paired.INHERITED_ORACLE=Path(spec['dependencies_cloud'])/'probe_runner.py'
    paired.check_resource(args.resource_check,args.kit,first=True)
    for name in ['PRIORITY_CALIBRATION_AUDIT.json','SHIFT_CALIBRATION_AUDIT.json']:
        receipt=json.loads((ROOT/name).read_text());assert receipt['evidence_valid'] and receipt['controls_valid'] and receipt['natural_hypothesis_matched']
    out=ROOT/'results';out.mkdir(exist_ok=False);started=time.monotonic()
    report=dict(schema='functional_fresh_pilot_v1',complete=False,passed=False,spec_sha256=sha(ROOT/'RUN_SPEC.json'),rows=[],
        actual_model_requests=0,first_generation_replayed=False,adoption=False,new_full_score=False,scope='3 known public development tasks, 1 fresh sample/arm, not independent natural validation')
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
                report['actual_model_requests']+=len(journal);assert report['actual_model_requests']<=12
                gate()
                argv=[sys.executable,'-B',str(ROOT/'pilot.py'),'judge','--task',task,'--solution',str(sample/'worker/solution.v'),'--out',str(sample/'judge'),'--kit',str(args.kit)]
                result=paired.owned_command(argv,ROOT,sample/'judge.log',360);result['argv']=argv;save(sample/'judge_command.json',result)
                assert result['returncode']==0 and not result['timeout'] and not result['remaining_live_group']
                bound=json.loads((sample/'judge/bound_verdict.json').read_text())
                row=dict(task=task,arm=arm,solve_deadline_reached=command['timeout'],solve_elapsed_s=command['elapsed_s'],
                    actual_model_requests=len(journal),received_model_responses=sum(r['response_received'] for r in journal),
                    solution_sha256=bound['solution_sha256'],verdict_sha256=bound['verdict_sha256'],verdict=bound['verdict'])
                save(sample/'row.json',row);report['rows'].append(row);save(out/'summary.json',report);publish(report)
        gate();pairs={t:{r['arm']:r for r in report['rows'] if r['task']==t} for t in spec['task_ids']}
        coefficients={arm:sum(pairs[t][arm]['verdict']['coefficient'] for t in spec['task_ids'])/len(spec['task_ids']) for arm in ['A','C']}
        regressions=[t for t in spec['task_ids'] if pairs[t]['C']['verdict']['coefficient']<pairs[t]['A']['verdict']['coefficient']]
        repairs=[t for t in spec['task_ids'] if pairs[t]['A']['verdict']['level']<3 and pairs[t]['C']['verdict']['level']==3]
        confirmed=all(r['received_model_responses']==r['actual_model_requests'] and not r['solve_deadline_reached'] for r in report['rows'])
        target_success=all(pairs[t]['C']['verdict']['level']==3 for t in spec['target_tasks'])
        guard=spec['correct_guard'];guard_pass=all(pairs[guard][arm]['verdict']['level']==3 for arm in ['A','C'])
        report.update(complete=True,passed=True,coefficients=coefficients,repairs=repairs,regressions=regressions,
            unconfirmed_attempts=sum(r['actual_model_requests']-r['received_model_responses'] for r in report['rows']),
            candidate_qualified_for_full_regression=confirmed and target_success and guard_pass and not regressions and coefficients['C']>coefficients['A'])
    except BaseException as e:report['error']=type(e).__name__+': '+str(e)
    finally:
        report['elapsed_s']=time.monotonic()-started;save(out/'summary.json',report);publish(report)
    sys.path.insert(0,'/workspace/team/tools/task-fifo-20261004');import activity
    activity.append(Path('/workspace/team/activity/fpga_owner'),'conclusions','functional-fresh-stage:'+spec['identity'],
        '三开发题真实新生成阶段结束；待完整证据审计，不自动部署／替代156或五样本分。',{k:v for k,v in report.items() if k!='rows'})
    return 0 if report['passed'] else 1


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['stage','judge'])
    p.add_argument('--kit',required=True,type=Path);p.add_argument('--resource-check',type=Path)
    p.add_argument('--task');p.add_argument('--solution',type=Path);p.add_argument('--out',type=Path)
    args=p.parse_args();raise SystemExit(main(args) if args.phase=='stage' else judge(args))
