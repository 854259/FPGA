"""Fixed AMD process-probe controls; no A/P/B inference or EDA is executed."""
import argparse
from collections import Counter
import copy
import fcntl
import json
from pathlib import Path
import time

import three_arm_queue_20261005 as queue
from three_arm_queue_20261005 import official


PROBE = '''import json,sys
from pathlib import Path
request=json.loads(Path(sys.argv[1]).read_text())
folder=Path(sys.argv[1]).parent
assert sorted(p.name for p in (folder/'prompt_only').iterdir())==['interface.txt','prompt.txt']
argv=request['argv']; row=request['row']
if row['arm']=='B':
 assert any(x.endswith('/official_baseline_arm_20261005.py') for x in argv)
 assert not any(x.endswith('/worker.py') for x in argv) and '--arm' not in argv
else:
 assert any(x.endswith('/worker.py') for x in argv)
 assert argv[argv.index('--arm')+1]==row['arm']
 assert 'PAIRED_TASK_DIR='+str(folder/'prompt_only') in argv
(folder/'probe_output.txt').write_text(row['arm']+':'+row['key'])
print(json.dumps({'arm':row['arm'],'key':row['key'],'real_model_calls':0}))
'''


def preflight(args):
    resource = official.resource_module()
    resource.check_resource(args.resource_check, args.kit, first=True)
    out = args.out.resolve(); assert not out.exists(); out.mkdir(parents=True)
    start = time.monotonic(); results = []; invocations = []
    sources = queue.prepare_sources(out/'sources')
    queue.save(out/'SOURCE_COPY.json', sources)
    entry = Path(official.__file__).resolve()
    tasks = []
    for dataset in ['constructed_one', 'constructed_two']:
        folder = out/'inputs'/dataset/'same_name'; folder.mkdir(parents=True)
        (folder/'prompt.txt').write_text('Constructed routing input; not an evaluation task.')
        (folder/'interface.txt').write_text('module TopModule(input a, output y); endmodule\n')
        (folder/'tb.sv').write_text('EVALUATOR_SENTINEL')
        (folder/'reference.sv').write_text('REFERENCE_SENTINEL')
        tasks.append(dict(dataset=dataset, task='same_name', family='constructed_wire', use='development',
                          task_dir=str(folder), hashes={n:official.sha(folder/n) for n in ['prompt.txt','interface.txt']}))
    plan = queue.build_plan(tasks, 5, sources, entry, args.kit, 50, 3600)
    probe = out/'PROBE.py'; probe.write_text(PROBE)
    queue.save(out/'CONTROL_PLAN.json', plan)

    def execute(argv, row, folder):
        invocations.append(row['key'])
        queue.save(folder/'PROBE_REQUEST.json', dict(argv=argv, row=row))
        command = resource.owned_command(['/usr/bin/python3','-B',str(probe),str(folder/'PROBE_REQUEST.json')],
                                         folder, folder/'probe.log', 5)
        queue.save(folder/'PROBE_COMMAND.json', command)
        assert command['returncode'] == 0 and not command['timeout'] and not command['remaining_live_group']
        assert (folder/'probe_output.txt').read_text() == row['arm']+':'+row['key']
        return dict(complete=True, unconfirmed_calls=0, actual_calls=1, synthetic=True,
                    files={n:official.sha(folder/n) for n in ['PROBE_REQUEST.json','PROBE_COMMAND.json','probe.log','probe_output.txt']})

    def blocked(name, fn):
        before = len(invocations)
        try:
            fn()
        except (AssertionError, BlockingIOError) as error:
            assert len(invocations) == before
            results.append(dict(control=name, passed=True, rejection=str(error), additional_probes=0))
        else:
            raise AssertionError('Missing rejection: '+name)

    root = Path(sources['root'])/'queues'
    paired = root/'paired'
    for unused in range(len(plan['rows'])):
        queue.advance(plan, paired, args.resource_check, execute)
    assert len(invocations) == 30 and len(set(invocations)) == 30
    assert queue.advance(plan, paired, args.resource_check, execute)['complete']
    assert len(invocations) == 30
    results.append(dict(control='two_dataset_five_sample_three_arm_exactly_once_and_resume', passed=True,
                        process_probes=30, reserved_calls=50, actual_synthetic_calls=30,
                        independent_natural_tasks=0))
    positions = Counter((r['arm'], i%3) for i,r in enumerate(plan['rows']))
    assert max(positions.values())-min(positions.values()) <= 1
    results.append(dict(control='counterbalanced_order_and_unique_cross_dataset_keys', passed=True))
    damaged = copy.deepcopy(plan); damaged['max_calls'] += 1
    blocked('frozen_plan_drift', lambda:queue.advance(damaged,paired,args.resource_check,execute))
    damaged = copy.deepcopy(plan); damaged['rows'].pop()
    blocked('incomplete_pair_matrix', lambda:queue.validate(damaged))
    damaged = copy.deepcopy(plan); damaged['rows'].append(damaged['rows'][0])
    blocked('duplicate_row', lambda:queue.validate(damaged))
    for label, path in [('input_drift',Path(tasks[0]['task_dir'])/'prompt.txt'),
                        ('source_drift',Path(sources['root'])/'worker.py'),
                        ('terminal_evidence_drift',paired/'row_000000/probe_output.txt')]:
        original = path.read_bytes()
        path.write_bytes(original+b'\nDRIFT')
        try:
            blocked(label,lambda:queue.advance(plan,paired,args.resource_check,execute))
            (out/(label+'.observed')).write_bytes(path.read_bytes())
        finally:
            path.write_bytes(original)
    short = queue.build_plan(tasks[:1],1,sources,entry,args.kit,4,3600)
    queue.advance(short,root/'call_cap',args.resource_check,execute)
    queue.advance(short,root/'call_cap',args.resource_check,execute)
    blocked('conservative_call_cap',lambda:queue.advance(short,root/'call_cap',args.resource_check,execute))
    clock_plan = queue.build_plan(tasks[:1],1,sources,entry,args.kit,5,3600)
    queue.advance(clock_plan,root/'wall_cap',args.resource_check,execute)
    header=root/'wall_cap/QUEUE.json'; value=json.loads(header.read_text()); value['started_unix']-=3600
    queue.save(header,value)
    blocked('wall_deadline_not_restarted_on_resume',lambda:queue.advance(clock_plan,root/'wall_cap',args.resource_check,execute))
    crash = root/'crash'
    def execute_then_crash(argv,row,folder):
        execute(argv,row,folder)
        raise RuntimeError('Frozen crash after child exit, before terminal commit')
    try:
        queue.advance(clock_plan,crash,args.resource_check,execute_then_crash)
    except RuntimeError as error:
        queue.save(crash/'EXPECTED_CRASH.json',dict(reason=str(error)))
    else:
        raise AssertionError('No crash')
    blocked('crash_after_child_never_retried',lambda:queue.advance(clock_plan,crash,args.resource_check,execute))
    for name, receipt in [('unconfirmed',dict(complete=False,unconfirmed_calls=1,actual_calls=1)),
                          ('unknown_actual_calls',dict(complete=True,unconfirmed_calls=0,actual_calls='unknown'))]:
        def unknown(argv,row,folder):
            result=execute(argv,row,folder); result.update(receipt); return result
        queue.advance(clock_plan,root/name,args.resource_check,unknown)
        blocked(name,lambda:queue.advance(clock_plan,root/name,args.resource_check,execute))
    orphan=root/'orphan'; (orphan/'row_000002').mkdir(parents=True)
    blocked('orphan_result_no_new_manifest',lambda:queue.advance(clock_plan,orphan,args.resource_check,execute))
    held=root/'held'; held.mkdir()
    with (held/'queue.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        blocked('concurrent_dispatch_lock',lambda:queue.advance(clock_plan,held,args.resource_check,execute))
    # Build all156 known inputs, five samples, three arms. This is only a plan;
    # no inference, no claim that the full comprehensive batch is admitted.
    original=json.loads((queue.PARENT/'RUN_SPEC.json').read_text())
    full_tasks=[]
    for task in original['task_ids']:
        folder=args.kit/'bench/tasks_veval'/task
        full_tasks.append(dict(dataset='verilogeval156',task=task,family='not_audited',use='development',
            task_dir=str(folder),hashes={n:official.sha(folder/n) for n in ['prompt.txt','interface.txt'] if (folder/n).exists()}))
    full=queue.build_plan(full_tasks,5,sources,entry,args.kit,3900,86400)
    queue.validate(full)
    assert len(full['rows'])==2340 and full['required_reserved_calls']==3900
    queue.save(out/'PROSPECTIVE_156_PLAN.json',full)
    results.append(dict(control='full156_five_sample_manifest_only',passed=True,rows=2340,
                        prospective_reserved_calls=3900,executed_rows=0,admitted=False))
    resource.check_resource(args.resource_check,args.kit)
    terminal=dict(schema='three_arm_queue_preflight_v1',complete=True,passed=True,controls=results,
        control_count=len(results),process_probe_executions=len(invocations),real_model_calls=0,eda_calls=0,
        elapsed_s=time.monotonic()-start,source_copy_sha256=official.sha(out/'SOURCE_COPY.json'),
        prospective_manifest_sha256=official.sha(out/'PROSPECTIVE_156_PLAN.json'),
        comprehensive_batch=False,quality_measured=False,independent_natural_tasks=0,
        limitations=['Actual A/P/B solve processes were not invoked; controlled child probes exercised argv and durable queue state.',
                    'Baseline POST receipt, real27B cancellation and evaluator integration remain required.',
                    'RTLLM15 blocked entries, independent admission, credits/full budget and formal32GB remain open.',
                    'No production queue CLI is enabled; the156 plan is a component, not a full frozen batch.'])
    queue.save(out/'RESULTS.json',terminal)
    print(json.dumps(terminal))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    for name in ['kit','out','resource-check']:parser.add_argument('--'+name,type=Path,required=True)
    preflight(parser.parse_args())
