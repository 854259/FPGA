"""One whole FIFO stage; original phaseP worker/judge budgets and source bytes."""
from pathlib import Path
import argparse,ctypes,json,os,shutil,sys,time
import pilot,worker,stability_metrics as metrics,stability_protected
R=Path(__file__).resolve().parent

def main(args):
    assert sys.version_info[:2]==(3,12) and sys.platform=='linux'
    assert ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)==0
    spec=pilot.frozen(args.kit);env=pilot.validate_environment()
    assert spec['arms']==['P'] and spec['repetitions']==5 and spec['expected_samples']==780
    assert spec['stage_timeout_s']==43200 and spec['slot_minutes']==735
    assert env['tools']==spec['compiler_tools']
    assert {k:os.environ.get(k) for k in spec['compiler_env']}==spec['compiler_env']
    assert {p.relative_to(Path(env['udev_stub'])).as_posix():worker.sha(p) for p in Path(env['udev_stub']).rglob('*') if p.is_file()}==spec['udev_files']
    paired=worker.load('stability_owned',Path(spec['dependencies_cloud'])/'paired_checkpoint.py')
    paired.REPO=R;paired.INHERITED_ORACLE=Path(spec['dependencies_cloud'])/'probe_runner.py'
    paired.check_resource(args.resource_check,args.kit,first=True)
    out=R/'results';out.mkdir(exist_ok=False);started=time.monotonic();index=0
    worker.save(out/'ENVIRONMENT_PREFLIGHT.json',env)
    report=dict(schema='phaseP_stability156x5_v1',complete=False,passed=False,spec_sha256=worker.sha(R/'RUN_SPEC.json'),
        rows=[],actual_model_requests=0,first_generation_replayed=False,adoption=False,new_full_score=False,
        scope='780 fixed development samples, phaseP only, no resampling or formal five-sample qualification.')
    def save():worker.save(out/'summary.json',report)
    def gate():
        nonlocal index
        pilot.frozen(args.kit);paired.check_resource(args.resource_check,args.kit)
        assert shutil.disk_usage(R).free>=spec['minimum_disk_free_bytes']
        b=json.loads((R/'raw_evidence/STABILITY_PROTECTED_GROUPS.json').read_bytes())
        checked=stability_protected.check(b);folder=out/'protected_source_checks';folder.mkdir(exist_ok=True)
        worker.save(folder/(str(index).zfill(4)+'.json'),dict(index=index,**checked));index+=1
        assert time.monotonic()-started<spec['stage_timeout_s']-60
    save()
    try:
        gate()
        for task,arm,repeat in metrics.order(spec['task_ids']):
            assert not (R/'STOP_AFTER_CURRENT').exists(),'Boundary stop requested'
            gate();sample=out/'samples'/arm/('repeat-'+str(repeat))/task;sample.mkdir(parents=True,exist_ok=False)
            argv=[sys.executable,'-B',str(R/'stability_worker.py'),'--out',str(sample/'worker'),'--task',task,'--arm','P','--repeat',str(repeat),'--kit',str(args.kit),'--resource-check',str(args.resource_check)]
            command=paired.owned_command(argv,R,sample/'worker.log',300);command['argv']=argv;worker.save(sample/'worker_command.json',command)
            assert not command['launch_error'] and not command['remaining_live_group']
            assert command['timeout'] or type(command['returncode']) is int and command['returncode']==0
            if command['timeout']:
                until=time.monotonic()+120
                while True:
                    try:paired.model_idle('http://127.0.0.1:8000/v1',spec['model']);break
                    except RuntimeError:assert time.monotonic()<until;time.sleep(2)
            journal=json.loads((sample/'worker/requests.json').read_bytes())
            assert 1<=len(journal)<=2 and all(not r['replayed'] for r in journal)
            report['actual_model_requests']+=len(journal);assert report['actual_model_requests']<=1560
            gate()
            argv=[sys.executable,'-B',str(R/'pilot.py'),'judge','--task',task,'--solution',str(sample/'worker/solution.v'),'--out',str(sample/'judge'),'--kit',str(args.kit)]
            judged=paired.owned_command(argv,R,sample/'judge.log',360);judged['argv']=argv;worker.save(sample/'judge_command.json',judged)
            assert type(judged['returncode']) is int and judged['returncode']==0 and not judged['timeout'] and not judged['remaining_live_group'] and not judged['launch_error']
            bound=json.loads((sample/'judge/bound_verdict.json').read_bytes())
            row=dict(task=task,arm='P',repeat=repeat,solve_deadline_reached=command['timeout'],solve_elapsed_s=command['elapsed_s'],
                actual_model_requests=len(journal),received_model_responses=sum(r['response_received'] for r in journal),
                solution_sha256=bound['solution_sha256'],verdict_sha256=bound['verdict_sha256'],verdict=bound['verdict'])
            worker.save(sample/'row.json',row);report['rows'].append(row);save()
        gate();scorer=worker.load('stability_score',args.kit/'official_reference/selftest/score.py')
        report.update(metrics.aggregate(report['rows'],spec['task_ids'],scorer));report.update(complete=True,passed=True)
    except BaseException as error:report['error']=type(error).__name__+': '+str(error)
    finally:report['elapsed_s']=time.monotonic()-started;save()
    return 0 if report['passed'] else 1

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--kit',type=Path,required=True);p.add_argument('--resource-check',type=Path,required=True)
    raise SystemExit(main(p.parse_args()))
