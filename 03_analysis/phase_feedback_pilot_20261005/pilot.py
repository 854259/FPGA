"""Sixteen actual fresh C/E samples; original external judge, no deployment."""
import argparse
import ctypes
import os
import shutil
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
    save(ledger/'SNAPSHOT.json',dict(observed_at_epoch=time.time(),experiment=str(ROOT),completed_samples=len(report['rows']),expected_samples=16,actual_model_requests=report['actual_model_requests'],complete=report['complete'],audit_pending=True,first_generation_replayed=False,adoption=False,new_full_score=False))
    text='边沿功能反例8题C/E真实对照；当前'+str(len(report['rows']))+'/16，实际请求'+str(report['actual_model_requests'])+'。只扩题面边沿检查和实际失配反馈，首稿/原技能/一次修复/8192token/300秒保持。原官方判定，未终态审计不发布新分或收益、不部署。整任务FIFO，只写自己日志/目录，模型/实例/队友保持。证据 '+str(ROOT)
    temporary=ledger/'STATUS.md.pending';temporary.write_text(text,encoding='utf-8');temporary.replace(ledger/'STATUS.md')


def validate_environment(tools=None,stub=None):
    tools=Path(tools or '/workspace/AMD/2026.1/Vivado/bin').resolve()
    stub=Path(stub or '/workspace/team/udev-stub').resolve()
    assert Path(os.environ.get('VIVADO_BIN','')).resolve()==tools, 'VIVADO_BIN not pinned'
    assert str(stub) in os.environ.get('LD_LIBRARY_PATH','').split(os.pathsep), 'Missing scoped udev stub path'
    assert stub.is_dir(), 'Missing udev stub directory'
    checked={}
    for name in ['xvlog','xelab','xsim','vivado']:
        found=shutil.which(name)
        assert found and Path(found).resolve()==(tools/name).resolve(), 'Missing/wrong pinned tool on PATH: '+name
        assert os.access(found,os.X_OK), 'Tool not executable: '+name
        checked[name]=dict(path=str(Path(found).resolve()),sha256=sha(Path(found)))
    return dict(verified=True,tools=checked,vivado_bin=str(tools),udev_stub=str(stub),model_calls=0,eda_calls=0)

def main(args):
    assert sys.version_info[:2]==(3,12)
    assert sys.platform=='linux' and ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)==0
    environment=validate_environment()
    spec=frozen(args.kit);paired=load('fresh_owned',Path(spec['dependencies_cloud'])/'paired_checkpoint.py')
    paired.REPO=ROOT;paired.INHERITED_ORACLE=Path(spec['dependencies_cloud'])/'probe_runner.py'
    paired.check_resource(args.resource_check,args.kit,first=True)
    assert len(spec['task_ids'])==8 and spec['task_ids']==sorted(spec['task_ids'])
    assert spec['arms']==['C','P'] and spec['schema']=='phase_feedback_pilot_frozen_v1'
    out=ROOT/'results';out.mkdir(exist_ok=False);started=time.monotonic()
    save(out/'ENVIRONMENT_PREFLIGHT.json',environment)
    report=dict(schema='phase_feedback_pilot_v1',complete=False,passed=False,spec_sha256=sha(ROOT/'RUN_SPEC.json'),rows=[],
        actual_model_requests=0,first_generation_replayed=False,adoption=False,new_full_score=False,scope='8 known development/guard tasks, one fresh C/E sample each, no independent/full156/five-sample claim')
    save(out/'summary.json',report);publish(report)
    def gate():
        frozen(args.kit);paired.check_resource(args.resource_check,args.kit)
        assert time.monotonic()-started<spec['stage_timeout_s']-60
    try:
        for index,task in enumerate(spec['task_ids']):
            for arm in (['C','P'] if index%2==0 else ['P','C']):
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
        '8题C/E边沿修复阶段结束；实际原始审计前不发布收益，不部署，不是全156/独立/五样本。',{k:v for k,v in report.items() if k!='rows'})
    return 0 if report['passed'] else 1


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('phase',choices=['stage','judge'])
    p.add_argument('--kit',required=True,type=Path);p.add_argument('--resource-check',type=Path)
    p.add_argument('--task');p.add_argument('--solution',type=Path);p.add_argument('--out',type=Path)
    args=p.parse_args();raise SystemExit(main(args) if args.phase=='stage' else judge(args))
