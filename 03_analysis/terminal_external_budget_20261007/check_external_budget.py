"""New missing boundary contexts only; fake terminal children, no original audit."""
import json,os,sys,time
from pathlib import Path
import terminal_outer
from owned_tree_cleanup import cleanup
ROOT=Path(__file__).resolve().parent
rows=[]
cases=[('final-write-before-real-exit',1.0,.3),
       ('post-finish-hang-rejected',.4,.2),
       ('escaped-session-adopted-cleanup',1.5,.5),
       ('cleanup-overrun-full-deadline-rejected',.4,.2)]
for label,total,reserve in cases:
    unit=ROOT/'contexts'/label;unit.mkdir(parents=True,exist_ok=False)
    artifact=unit/'FINAL.json';code="from pathlib import Path\nimport json,os,subprocess,sys,time\np=Path("+repr(str(artifact))+')\n'
    if label=='final-write-before-real-exit':
        code+="p.with_name('EARLY_FINISH.json').write_text('{\"self_elapsed\":0}')\ntime.sleep(.08)\np.write_text('{\"passed\":true}')\ntime.sleep(.08)\n"
    elif label=='post-finish-hang-rejected':
        code+="p.with_name('EARLY_FINISH.json').write_text('{\"self_elapsed\":0}')\ntime.sleep(10)\np.write_text('{\"passed\":true}')\n"
    elif label=='escaped-session-adopted-cleanup':
        code+="c=subprocess.Popen([sys.executable,'-B','-c','import time;time.sleep(10)'],start_new_session=True)\np.with_name('DETACHED_PID.json').write_text(json.dumps({'pid':c.pid}))\np.write_text('{\"passed\":true}')\n"
    else:
        code+="p.write_text('{\"passed\":true}')\n"
    fake=unit/'fake_terminal.py';fake.write_text(code)
    def slow_fake_cleanup(proc,tracked,model_pid):
        # Explicit test injection only: a one-second cleanup exceeds the .4s
        # complete cap despite fast child exit. The genuine emergency cleanup
        # still executes; no original cleanup code is modified.
        time.sleep(1)
        return cleanup(proc,tracked,model_pid)
    result=terminal_outer.run([sys.executable,'-B',str(fake)],unit,unit/'outer',
          total,reserve,[artifact],2013333,
          _cleanup_for_fake_control=slow_fake_cleanup if label.startswith('cleanup-overrun') else None)
    proc=result['terminal_process'];assert proc and proc['exec_confirmed'] and proc['leader_reaped'] and not proc['remaining_group']
    assert result['owned_cleanup']['verified'] and not result['owned_cleanup']['remaining']
    if label=='final-write-before-real-exit':
        assert result['passed'] and result['measured_complete_elapsed_s']>=.16 and artifact.exists()
    elif label=='post-finish-hang-rejected':
        assert not result['passed'] and proc['timeout'] and proc['returncode']==-9 and not artifact.exists()
    elif label=='escaped-session-adopted-cleanup':
        pid=json.loads((unit/'DETACHED_PID.json').read_bytes())['pid']
        assert result['passed'] and not (Path('/proc')/str(pid)).exists()
        assert any(r['pid']==pid for r in result['owned_cleanup']['recorded'])
    else:
        assert not result['passed'] and result['full_deadline_expired'] and result['measured_complete_elapsed_s']>=total and proc['returncode']==0 and artifact.exists()
    rows.append(dict(label=label,assertions_passed=True,result=result,explicit_fake_terminal=True))
with (ROOT/'CONTROL_RESULTS.json').open('x',encoding='utf-8') as f:
    json.dump(dict(passed=True,controls=len(rows),records=rows,actual_model_calls=0,actual_eda_calls=0,original_auditors_executed=0,old_controls_replayed=0),f,indent=2);f.write('\n')
print(json.dumps(dict(passed=True,controls=len(rows))))
