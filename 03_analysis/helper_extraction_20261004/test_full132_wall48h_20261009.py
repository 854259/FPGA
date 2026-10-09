"""New AMD-only budget/amendment controls; no model, EDA or production mutation."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace
from unittest.mock import patch

import full132_wall48h_20261009 as extension


def controls(root, original, identity_only=False):
    root.mkdir(exist_ok=False)
    queue = extension.load_module(original/'three_arm_queue_20261005.py', 'queue48_control')
    recovery = extension.load_module(root.parent/'fifo_wait_recovery_20261009.py', 'recovery48_control')
    fifo_path = Path('/workspace/team/tools/task-fifo-20261004/task_fifo.py')
    fifo = extension.load_module(fifo_path, 'fifo48_control')
    assert extension.sha(fifo_path) == extension.FIFO_SHA
    amended, function_sha = extension.amended_advance(queue)
    results, calls = [], []

    def receipt(folder):
        (folder/'FAKE.txt').write_text('FAKE_NO_MODEL_NO_EDA\n')
        return dict(complete=True, actual_calls=0, unconfirmed_calls=0,
                    files={'FAKE.txt':extension.sha(folder/'FAKE.txt')})

    def case(name, max_calls=5):
        base = root/name
        (base/'queue').mkdir(parents=True)
        (base/'fifo/tickets').mkdir(parents=True)
        (base/'fifo/registry.lock').touch()
        (base/'queue/runner.lock').touch()
        (base/'queue/queue.lock').touch()
        (base/'guard').mkdir()
        out = base/'extension'
        out.mkdir()
        task = base/'input'
        task.mkdir()
        (task/'prompt.txt').write_text('FAKE wall-budget continuation fixture.\n')
        tasks = [dict(dataset='synthetic', task='FAKE_WALL48', family='synthetic', use='development',
                      task_dir=str(task), hashes={'prompt.txt':extension.sha(task/'prompt.txt')})]
        sources = dict(root=str(base), files={str(Path(queue.__file__)):extension.QUEUE_SHA})
        plan = queue.build_plan(tasks, 1, sources, original/'official_baseline_arm_20261005.py',
                                '/workspace/team/tasks/autodl-rtl-kit/project', 5, 129600)
        plan['execution_authorized'] = True
        plan['max_calls'] = max_calls
        queue.save(base/'PLAN.json', plan)
        queue.save(base/'queue/PLAN.json', plan)
        header = dict(plan_sha256=queue.digest(plan), started_unix=time.time()-129610)
        queue.save(base/'queue/QUEUE.json', header)
        for index, row in enumerate(plan['rows'][:2]):
            folder = base/'queue'/('row_%06d'%index)
            folder.mkdir()
            queue.save(folder/'STARTED.json', dict(row=row,plan_sha256=queue.digest(plan),fixture='FAKE'))
            queue.save(folder/'TERMINAL.json',receipt(folder))
            queue.seal_row(folder,row,queue.digest(plan))
        (base/'queue/RUNNER_EVENTS.jsonl').write_text(json.dumps(dict(event='stopped',
            error_type='AssertionError', error=extension.WALL_ERROR, at_unix=time.time()))+'\n')
        guard = dict(complete=True,passed=False,stage_rc=1,owned_cleanup={'verified':True,'recorded':[]},
                     model_unchanged=True,protected_files_unchanged=True,own_slot_released=True,
                     model_idle_after={'fixture':'FAKE'})
        queue.save(base/'guard/status.json',guard)
        ticket = dict(schema='whole_task_fifo_v1',ticket=132,task_name='SYNTHETIC_ONLY',
            accepted_at_utc='synthetic',state='running',command=['MUST_NOT_EXECUTE'],cwd=str(base),
            completion_json=str(base/'guard/status.json'),slot_owner_prefix='SYNTHETIC',adopted_process=None,
            started_at_utc='synthetic',runner={'pid':999999990,'starttime':'1'},
            child={'pid':999999991,'starttime':'1'},task_fifo_sha256=extension.FIFO_SHA)
        target=base/'fifo/tickets/00000132.json'
        queue.save(target,dict(ticket,state='held_for_inspection',error=extension.FIFO_ERROR))
        (base/'fifo/task_00000132.log').write_text('ORIGINAL_LOG_PRESERVED\n')
        config=dict(original_root=str(base),fifo_root=str(base/'fifo'),original_ticket=ticket,
            original_processes=[dict(pid=999999990,starttime='1',command_sha256='old')],
            original_header=header,deadline_unix=header['started_unix']+extension.TOTAL_SECONDS,
            files={str(base/'PLAN.json'):extension.sha(base/'PLAN.json')},fifo_source=str(fifo_path),
            owner48='SYNTHETIC48')
        current=recovery.proc_record(os.getpid())
        config['model_identity']={k:current[k] for k in ('pid','starttime','command_sha256')}
        return base,out,plan,config,target,guard

    if identity_only:
        for name in ('matching_identity','wrong_birth','wrong_command','changed_under_registry'):
            base,out,plan,config,target,guard=case(name)
            if name=='wrong_birth':config['model_identity']['starttime']='wrong'
            if name=='wrong_command':config['model_identity']['command_sha256']='wrong'
            before=target.read_bytes()
            with patch.object(fifo,'probe',return_value=True),patch.object(extension.subprocess,'Popen',side_effect=AssertionError('no launch')):
                if name=='changed_under_registry':
                    real=extension.require_original_model
                    def changing(c,r):
                        changing.count+=1
                        if changing.count==2:raise RuntimeError('original shared model identity changed')
                        return real(c,r)
                    changing.count=0
                    with patch.object(extension,'require_original_model',side_effect=changing), \
                            patch.object(extension,'command_for',return_value=['FAKE']):
                        try:extension.resume_once(config,out/'PLAN.json','FAKE',recovery,fifo,queue)
                        except RuntimeError as error:assert 'model identity changed' in str(error)
                        else:raise AssertionError('identity race accepted')
                    assert changing.count==2
                else:
                    try:result=extension.eligible(config,recovery,fifo,queue)
                    except RuntimeError as error:
                        assert name!='matching_identity' and 'model identity changed' in str(error)
                    else:assert name=='matching_identity' and result['outcome']=='eligible'
            assert target.read_bytes()==before and not (out/'RESUME_INTENT.json').exists()
            results.append(name)
        return dict(passed=True,checks=results,old20_controls_rerun=False,
                    model_calls=0,eda_commands=0,production_fifo_mutations=0)

    def fake_execute(argv,row,folder):
        calls.append(row['key'])
        return receipt(folder)

    # Real original queue checks/seals, with one new FAKE dispatch beyond 36h.
    base,out,plan,config,target,guard=case('real_queue_unstarted_suffix')
    before={str(p):extension.sha(p) for p in (base/'queue').glob('row_*/*') if p.is_file()}
    try:
        queue.advance(plan,base/'queue',base/'FAKE_RESOURCE',fake_execute)
    except AssertionError as error:
        assert str(error)==extension.WALL_ERROR
    else:
        raise AssertionError('original 36h cap was not retained')
    assert not calls
    result=amended(plan,base/'queue',base/'FAKE_RESOURCE',fake_execute)
    assert result['reserved_calls']==5 and len(calls)==1
    assert all(extension.sha(p)==digest for p,digest in before.items())
    assert amended(plan,base/'queue',base/'FAKE_RESOURCE',fake_execute)['complete']
    assert len(calls)==1 and extension.sha(base/'PLAN.json')==config['files'][str(base/'PLAN.json')]
    results.append('original36h_refuses_extended48h_dispatches_only_missing_row_prefix_unchanged')
    for name,change in (('cap48', 'time'),('max_calls','calls'),('unfinished_prefix','unfinished'),('corrupt_zip','zip')):
        base,out,plan,config,target,guard=case(name,4 if change=='calls' else 5)
        if change=='time':
            queue.save(base/'queue/QUEUE.json',dict(config['original_header'],started_unix=time.time()-172131))
        elif change=='calls':
            assert plan['max_calls']==4
        elif change=='unfinished':
            (base/'queue/row_000001/TERMINAL.json').unlink()
        else:
            p=base/'queue/row_000001/EVIDENCE.zip'
            p.write_bytes(p.read_bytes()+b'CHANGED')
        count=len(calls)
        try:
            amended(plan,base/'queue',base/'FAKE_RESOURCE',fake_execute)
        except (AssertionError,FileNotFoundError):
            pass
        else:
            raise AssertionError('unsafe suffix accepted: '+name)
        assert len(calls)==count
        results.append(name+'_refused_without_dispatch')

    cases=('wrong_ticket','wrong_stop','early_stop','guard_error','cleanup_unverified',
           'live_descendant','resource_not_idle','frozen_drift','empty_prefix','expired')
    for name in cases:
        base,out,plan,config,target,guard=case(name)
        probe=True
        if name=='wrong_ticket':
            item=extension.read(target);item['command']=['CHANGED'];queue.save(target,item)
        elif name in ('wrong_stop','early_stop'):
            p=base/'queue/RUNNER_EVENTS.jsonl';event=json.loads(p.read_text())
            if name=='wrong_stop':event['error']='a different failure'
            else:event['at_unix']=config['original_header']['started_unix']+10
            p.write_text(json.dumps(event)+'\n')
        elif name=='guard_error':guard['error']='synthetic error'
        elif name=='cleanup_unverified':guard['owned_cleanup']['verified']=False
        elif name=='live_descendant':
            current=recovery.proc_record(os.getpid())
            guard['owned_cleanup']['recorded']=[{k:current[k] for k in ('pid','starttime')}]
        elif name=='resource_not_idle':probe=False
        elif name=='frozen_drift':(base/'PLAN.json').write_text('{}')
        elif name=='empty_prefix':
            # Scope only these newly created synthetic fixtures.
            for folder in (base/'queue').glob('row_*'):
                folder.rename(folder.with_name('saved_'+folder.name))
        else:config['deadline_unix']=time.time()+669
        queue.save(base/'guard/status.json',guard)
        before=target.read_bytes()
        with patch.object(fifo,'probe',return_value=probe),patch.object(extension.subprocess,'Popen',side_effect=AssertionError('forbidden')):
            try:extension.eligible(config,recovery,fifo,queue)
            except (RuntimeError,TimeoutError,AssertionError):pass
            else:raise AssertionError('bad eligibility accepted: '+name)
        assert target.read_bytes()==before and not (out/'RESUME_INTENT.json').exists()
        results.append(name+'_refused_unchanged_ticket')

    for name in ('adoption','first_launch_failure','guard_identity_unknown','monitor_launch_failure'):
        base,out,plan,config,target,guard=case(name)
        before=target.read_bytes()
        log_before=extension.sha(base/'fifo/task_00000132.log')
        command=['/usr/bin/flock','-n',str(base/'FAKE_LOCK'),'FAKE_GUARD']
        process=SimpleNamespace(pid=999999992,poll=lambda:None)
        def popen(*args,**kwargs):
            popen.count+=1
            if name=='first_launch_failure' or (name=='monitor_launch_failure' and popen.count==2):
                raise OSError('FAKE launch failure')
            return process
        popen.count=0
        def bind(proc,argv,rec):
            if name=='guard_identity_unknown':raise RuntimeError('FAKE unknown identity')
            return dict(pid=proc.pid,starttime='FAKE_BIRTH',state='S',argv=argv,sid=proc.pid,ppid=os.getpid())
        with patch.object(fifo,'probe',return_value=True),patch.object(recovery,'matching_monitors',return_value=[]), \
                patch.object(extension,'command_for',return_value=command),patch.object(extension.subprocess,'Popen',side_effect=popen), \
                patch.object(extension,'bind_process',side_effect=bind):
            try:observed=extension.resume_once(config,out/'PLAN.json','FAKE_PLAN',recovery,fifo,queue)
            except (OSError,RuntimeError):assert name!='adoption'
            else:assert name=='adoption' and observed['completed_prefix_rows']==2
            try:extension.resume_once(config,out/'PLAN.json','FAKE_PLAN',recovery,fifo,queue)
            except RuntimeError as error:assert 'intent exists' in str(error)
            else:raise AssertionError('duplicate continuation accepted')
        assert extension.sha(base/'fifo/task_00000132.log')==log_before
        assert extension.read(out/'RESUME_INTENT.json')['failed_ticket_utf8'].encode()==before
        if name in ('adoption','monitor_launch_failure'):
            assert extension.read(target)['adopted_process']['starttime']=='FAKE_BIRTH'
            assert extension.read(target)['ticket']==132
        else:assert target.read_bytes()==before
        if name!='adoption':
            assert extension.read(out/'RESUME_FAILURE.json')['task_may_continue']==(name!='first_launch_failure')
        results.append(name+'_preserves_original_and_never_retries')

    # Real unchanged FIFO adoption, isolated files and synthetic process only.
    base,out,plan,config,target,guard=case('real_original_fifo_adoption')
    guard_script=out/'synthetic_guard.py'
    guard_script.write_text('import time,json\nfrom pathlib import Path\ntime.sleep(.5)\n'
        +'Path('+repr(str(out/'guard48/status.json'))+').write_text(json.dumps(dict(complete=True,passed=True)))\n')
    (out/'guard48').mkdir()
    child=subprocess.Popen([sys.executable,'-B',str(guard_script)],start_new_session=True)
    born=recovery.proc_record(child.pid)
    item=extension.read(target)
    item.update(state='queued',adopted_process={k:born[k] for k in ('pid','starttime')},
                completion_json=str(out/'guard48/status.json'))
    queue.save(target,item)
    log_before=extension.sha(base/'fifo/task_00000132.log')
    fifo.execute(base/'fifo',132,check=lambda item:True,poll_s=.01,lifetime_s=3)
    assert child.wait(timeout=3)==0
    done=extension.read(target)
    assert done['state']=='completed' and done['returncode'] is None
    assert done['completion_sha256']==extension.sha(out/'guard48/status.json')
    assert extension.sha(base/'fifo/task_00000132.log')==log_before
    assert recovery.proc_record(child.pid) is None
    results.append('unchanged_fifo_adopts_real_synthetic_process_preserves_log_completed_returncode_none')
    return dict(passed=True,checks=results,amended_advance_sha256=function_sha,
                fake_row_dispatches=len(calls),synthetic_guard_pid=child.pid,
                synthetic_guard_retired=True,model_calls=0,eda_commands=0,production_fifo_mutations=0)


if __name__=='__main__':
    assert sys.platform=='linux' and sys.dont_write_bytecode
    result=controls(Path(sys.argv[1]),Path(sys.argv[2]),len(sys.argv)>3 and sys.argv[3]=='identity-only')
    extension.new_json(Path(sys.argv[1]).parent/'RESULT.json',result)
    print(json.dumps(result))
