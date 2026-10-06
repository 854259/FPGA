"""Linux parent observes terminal child's real exit, adopted cleanup and final files.

The receipt belongs to the observer; its own serialization is not evidence of its
exit. Acceptance also requires the launch reader to confirm observer retirement.
The timed subject is the terminal child (including its final receipt/archive),
then all owned descendants and artifact binding. A missed cap never passes.
"""
import hashlib,json,os,signal,stat,sys,time
from pathlib import Path
import bounded_owned_exec
from owned_tree_cleanup import cleanup,descendants

def run(argv,cwd,out,total_cap_s,cleanup_reserve_s,required_files,model_pid,
        *,_cleanup_for_fake_control=None):
    assert sys.platform=='linux' and sys.dont_write_bytecode
    assert 0<cleanup_reserve_s<total_cap_s<=450 and model_pid>1
    assert signal.getitimer(signal.ITIMER_REAL)==(0.0,0.0)
    root=Path(out);root.mkdir(exist_ok=False)
    required=[Path(f).resolve() for f in required_files]
    assert required and len(required)==len(set(required))
    started=time.monotonic();expired=False;error=None;process=None;tree=None
    artifacts={};tracked={};cleanup_impl=_cleanup_for_fake_control or cleanup
    def deadline(sig,frame):
        nonlocal expired
        expired=True
        raise TimeoutError('external complete terminal process deadline')
    old=signal.signal(signal.SIGALRM,deadline)
    signal.setitimer(signal.ITIMER_REAL,total_cap_s)
    try:
        process=bounded_owned_exec.run(argv,cwd,root/'terminal_child',
                                     total_cap_s-cleanup_reserve_s)
        tracked.update(descendants(os.getpid()))
        tree=cleanup_impl(None,tracked,model_pid)
        assert tree['verified'] and not tree['remaining'],'owned tree not retired'
        assert process['normal_completion'] and process['returncode']==0,'terminal child not normal rc0'
        assert process['exec_confirmed'] and process['leader_reaped'] and not process['remaining_group']
        for f in required:
            assert stat.S_ISREG(f.stat().st_mode) and not f.is_symlink(),'final artifact must be regular'
            b=f.read_bytes()
            artifacts[str(f)]=dict(bytes=len(b),sha256=hashlib.sha256(b).hexdigest())
        # Includes the child's actual exit/reap, tree cleanup and final reads.
        assert time.monotonic()-started<=total_cap_s,'complete cap exceeded'
    except BaseException as exc:
        error=type(exc).__name__+': '+str(exc)
    finally:
        # Only owned descendants may be signalled. Deadline/overshoot remains
        # a rejection even if emergency cleanup subsequently succeeds.
        if tree is None or not tree['verified']:
            try:
                tracked.update(descendants(os.getpid()))
                tree=cleanup(None,tracked,model_pid)
            except BaseException as exc:
                error=(error+'; ' if error else '')+type(exc).__name__+': '+str(exc)
        elapsed=time.monotonic()-started
        signal.setitimer(signal.ITIMER_REAL,0)
        signal.signal(signal.SIGALRM,old)
    passed=bool(error is None and not expired and elapsed<=total_cap_s
                and process and process['normal_completion'] and process['returncode']==0
                and process['leader_reaped'] and not process['remaining_group']
                and tree and tree['verified'] and not tree['remaining']
                and set(artifacts)=={str(f) for f in required})
    record=dict(schema='terminal_external_process_budget_v1',passed=passed,
                total_cap_s=total_cap_s,cleanup_reserve_s=cleanup_reserve_s,
                child_cap_s=total_cap_s-cleanup_reserve_s,
                measured_complete_elapsed_s=elapsed,full_deadline_expired=expired,
                error=error,terminal_process=process,owned_cleanup=tree,
                final_artifacts=artifacts,observer_exit_verified_by_this_receipt=False,
                scope='exact terminal child birth gate through real exit/reap; all adopted descendants; final artifact binding',
                fake_cleanup_injection_used=_cleanup_for_fake_control is not None)
    with (root/'EXTERNAL_PROCESS_RECEIPT.json').open('x',encoding='utf-8') as f:
        json.dump(record,f,indent=2);f.write('\n')
    return record
