"""Original-budget five-pair wave-only diagnostic; fresh solver/judge execution only under owned FIFO."""
import argparse,ctypes,hashlib,importlib.util,json,os,shutil,sys,time
from pathlib import Path,PurePosixPath
ROOT=Path(__file__).resolve().parent
entry_module=None;metrics_module=None;source_module=None
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
read=lambda p:json.loads(Path(p).read_bytes())

def save(path,value):
    path=Path(path);temporary=path.with_name(path.name+'.pending')
    temporary.write_bytes((json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode());temporary.replace(path)

def load(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def frozen(kit):
    spec=read(ROOT/'RUN_SPEC.json');assert spec['schema']=='table_history_wave_score5_frozen_v1'
    for n,h in spec['source_hashes'].items():assert sha(ROOT/n)==h,n
    for n,h in spec['dependency_hashes'].items():assert sha(Path(spec['dependencies_cloud'])/n)==h,n
    for n,h in spec['input_hashes'].items():assert sha(kit/'bench/tasks_veval'/n)==h,n
    assert sha(ROOT/'baseline_worker.py')=='7ff7ed6e397caedee071a7f46015d81370c92f2579bd61dd2cc3337458467742'
    assert sha(ROOT/'package/agent/map_runtime.py')=='2f7cb98bc44a9e100d36ca12ac4ef7bf9ae2535473da358e166afa2559e96cba'
    assert sha(ROOT/'package/baseline.py')=='537783e39db22079c33c19af475dbdb760a29ff1656a48c481d434131f84fb51'
    assert sha(ROOT/'upstream/official_eval_guarded.py')=='5d1911d8b730cbb460bf7ceb33cc602bf1f840402971e3dc1301f470fbd52a4c'
    assert len(spec['task_ids'])==5 and spec['arms']==['C','P'] and spec['expected_samples']==10 and spec['max_actual_model_requests']==20
    assert spec['solve_deadline_s']==300 and spec['judge_timeout_s']==300 and spec['judge_supervisor_timeout_s']==360
    assert spec['max_worker_requests_per_arm']==2 and spec['retries']==0 and spec['expected_protection_receipts']==21
    assert spec['output_tokens']==8192 and spec['repairs']==1 and spec['stage_timeout_s']==7200
    global entry_module,metrics_module,source_module
    if entry_module is None:entry_module=load('wave_score5_generation_entry',ROOT/'generation_entry.py')
    if metrics_module is None:metrics_module=load('wave_score5_metrics',ROOT/'metrics.py')
    if source_module is None:source_module=load('wave_score5_source_admission',ROOT/'source_admission.py')
    assert spec['task_ids']==metrics_module.TASKS and spec['historically_correct_tasks']==metrics_module.HISTORICAL
    assert spec['diagnostic_only'] is True and spec['qualified_for_full156'] is False
    assert spec['guard_timeout_s']==7600 and spec['slot_minutes']==130
    source_module.verify(ROOT)
    return spec

def verify_generation(work,source,arm,spec,deadline=False):
    return entry_module.verify(work,ROOT,source,arm,spec,deadline,work)


def publish(report):
    save(ROOT/'STAGE_STATUS.json',dict(completed_samples=len(report['rows']),expected_samples=10,actual_model_requests=report['actual_model_requests'],complete=report['complete'],audit_pending=True,adoption=False,full156_qualified=False))

def judge(args):
    spec=frozen(args.kit);args.out.mkdir(parents=True,exist_ok=False)
    evaluator=load('wave_score5_original_judge',ROOT/'upstream/official_eval_guarded.py');evaluator.OFFICIAL=args.kit/'official_reference'
    verdict=evaluator.judge_sample(args.kit/'bench/tasks_veval'/args.task,args.solution,args.out,args.out/'verdict.json',spec['judge_timeout_s'])
    assert not verdict.get('tool_error') and verdict['task_id']==args.task and verdict['judge_evidence_complete']
    save(args.out/'bound_verdict.json',dict(solution_sha256=sha(args.solution),verdict_sha256=sha(args.out/'verdict.json'),verdict=verdict))

def worker(args):
    """The explicitly frozen score5 entry owns admission; standalone draft CLI stays closed."""
    assert sys.platform=='linux' and sys.dont_write_bytecode and sys.version_info[:2]==(3,12)
    assert ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)==0
    spec=frozen(args.kit)
    assert args.task in spec['task_ids'] and args.arm in spec['arms']
    assert args.out is not None and args.resource_check is not None
    _,modules=entry_module.modules(ROOT)
    paired=load('wave_score5_worker_owned',Path(spec['dependencies_cloud'])/'paired_checkpoint.py')
    paired.REPO=ROOT;paired.INHERITED_ORACLE=Path(spec['dependencies_cloud'])/'probe_runner.py'
    paired.check_resource(args.resource_check,args.kit)
    modules['worker'].run_worker(args,paired)


def main(args):
    assert sys.platform=='linux' and sys.dont_write_bytecode and sys.version_info[:2]==(3,12)
    assert ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)==0
    spec=frozen(args.kit);paired=load('wave_score5_owned',Path(spec['dependencies_cloud'])/'paired_checkpoint.py');paired.REPO=ROOT;paired.INHERITED_ORACLE=Path(spec['dependencies_cloud'])/'probe_runner.py'
    paired.check_resource(args.resource_check,args.kit,first=True)
    environment=load('wave_score5_original_environment',ROOT/'original_environment.py').validate_environment()
    assert environment['tools']==spec['compiler_tools'] and environment['compiler_env']==spec['compiler_env'] and environment['udev_files']==spec['udev_files']
    assert os.environ.get('RTL_REPAIRS')=='1' and os.environ.get('RTL_MAX_TOKENS')=='8192' and os.environ.get('RTL_TEMPERATURE','0')=='0'
    out=ROOT/'results';out.mkdir(exist_ok=False);start=time.monotonic();protection_index=0
    report=dict(schema='table_history_wave_score5_diagnostic_measurement_v1',complete=False,passed=False,spec_sha256=sha(ROOT/'RUN_SPEC.json'),rows=[],actual_model_requests=0,first_generation_replayed=False,adoption=False,full156_qualified=False)
    save(out/'ENVIRONMENT_PREFLIGHT.json',environment);save(out/'summary.json',report);publish(report)
    def gate():
        nonlocal protection_index
        frozen(args.kit);paired.check_resource(args.resource_check,args.kit)
        protection=load('wave_score5_source_protection',ROOT/'protected_sources.py').check(read(ROOT/'raw_evidence/PROTECTED_GROUPS_CAPTURE.json'))
        for path,h in spec['additional_protected_sources'].items():assert sha(path)==h
        folder=out/'protected_source_checks';folder.mkdir(exist_ok=True);save(folder/(str(protection_index).zfill(3)+'.json'),dict(index=protection_index,**protection));protection_index+=1
        assert shutil.disk_usage(ROOT).free>=spec['minimum_disk_free_bytes'] and time.monotonic()-start<spec['stage_timeout_s']-60
    try:
        for task,arm in metrics_module.order(spec['task_ids']):
            assert not (ROOT/'STOP_AFTER_CURRENT').exists();gate()
            sample=out/'samples'/arm/task;sample.mkdir(parents=True,exist_ok=False)
            argv=[sys.executable,'-B',str(ROOT/'pilot.py'),'worker','--out',str(sample/'worker'),'--task',task,'--arm',arm,'--kit',str(args.kit),'--resource-check',str(args.resource_check)]
            command=paired.owned_command(argv,ROOT,sample/'worker.log',300);command['argv']=argv;save(sample/'worker_command.json',command)
            assert not command['launch_error'] and not command['remaining_live_group'] and (command['timeout'] or command['returncode']==0)
            if command['timeout']:
                until=time.monotonic()+120
                while True:
                    try:paired.model_idle('http://127.0.0.1:8000/v1',spec['model']);break
                    except RuntimeError:assert time.monotonic()<until;time.sleep(2)
            journal=read(sample/'worker/requests.json');report['actual_model_requests']+=len(journal)
            assert report['actual_model_requests']<=20;save(out/'summary.json',report)
            bound=verify_generation(sample/'worker',args.kit/'bench/tasks_veval'/task,arm,spec,command['timeout']);save(sample/'generation_proof.json',bound)
            gate()
            argv=[sys.executable,'-B',str(ROOT/'pilot.py'),'judge','--task',task,'--solution',str(sample/'worker/solution.v'),'--out',str(sample/'judge'),'--kit',str(args.kit)]
            judged=paired.owned_command(argv,ROOT,sample/'judge.log',360);judged['argv']=argv;save(sample/'judge_command.json',judged)
            assert judged['returncode']==0 and not judged['timeout'] and not judged['launch_error'] and not judged['remaining_live_group']
            verdict=read(sample/'judge/bound_verdict.json')
            assert verdict['solution_sha256']==bound['solution_sha256']==sha(sample/'worker/solution.v')
            row=dict(task=task,arm=arm,solve_deadline_reached=command['timeout'],solve_elapsed_s=command['elapsed_s'],actual_model_requests=len(journal),received_model_responses=sum(r['response_received'] for r in journal),solution_sha256=verdict['solution_sha256'],verdict_sha256=verdict['verdict_sha256'],verdict=verdict['verdict'],**bound['binding'])
            save(sample/'row.json',row);report['rows'].append(row);save(out/'summary.json',report);publish(report)
        gate();assert protection_index==21
        score=args.kit/'official_reference/selftest/score.py';assert sha(score)==spec['official_score_sha256'];scorer=load('wave_score5_original_score',score)
        report.update(complete=True,passed=True,**metrics_module.aggregate(report['rows'],spec['task_ids'],spec['historically_correct_tasks'],scorer))
    except BaseException as error:report['error']=type(error).__name__+': '+str(error);raise
    finally:report['elapsed_s']=time.monotonic()-start;save(out/'summary.json',report);publish(report)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=('run','worker','judge'));parser.add_argument('--kit',type=Path,required=True);parser.add_argument('--resource-check',type=Path);parser.add_argument('--task');parser.add_argument('--arm',choices=['C','P']);parser.add_argument('--solution',type=Path);parser.add_argument('--out',type=Path)
    args=parser.parse_args()
    if args.action=='judge':judge(args)
    elif args.action=='worker':worker(args)
    else:assert args.resource_check is not None;main(args)
