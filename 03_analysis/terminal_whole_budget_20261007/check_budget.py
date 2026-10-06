"""Three new real-child budget contexts; explicit fake auditor, no EDA/model/FIFO."""
import ctypes, hashlib, json, os, signal, subprocess, sys, time
from pathlib import Path
import full_budget

ROOT=Path(__file__).resolve().parent
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()

def save(p,j):
    with Path(p).open('x',encoding='utf-8') as o:
        json.dump(j,o,indent=2);o.write('\n')

assert sys.platform=='linux' and sys.dont_write_bytecode
assert ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)==0
records=[]
for label, kind, total in [('normal-full450','paired',450),
                            ('paired-outer-expiry','paired',20.2),
                            ('native-outer-expiry','native',20.2)]:
    case=ROOT/'cases'/label;case.mkdir(parents=True,exist_ok=False)
    original=case/'fake_original';original.mkdir()
    script=original/'audit.py'
    script.write_text("import time\ntime.sleep("+('0.03' if label=='normal-full450' else '3')+")\n",encoding='utf-8')
    argv=[sys.executable,'-B',str(script)]
    total_started=full_budget.start(total)
    try:
        if kind=='paired':
            source=ROOT/'terminal_process_functions.py'
            manifest={'source_hashes':{'terminal_process_functions.py':sha(source)},
                      'python_sha256':sha(sys.executable)}
            spec={'source_hashes':{'audit.py':sha(script)}}
            context=dict(Path=Path,hashlib=hashlib,json=json,os=os,signal=signal,
                         subprocess=subprocess,sys=sys,time=time,root=case,
                         original=original,spec=spec,manifest=manifest,
                         sources=lambda:{'terminal_process_functions.py':sha(source)},
                         sha=sha,save=save)
            exec(compile(source.read_bytes(),'exact_original102_process_functions','exec'),context)
            rec=context['execute']('auditor',argv,180)
        else:
            import owned_exec
            rec=owned_exec.run(argv,case,case/'owned_auditor',60)
    finally:
        budget=full_budget.finish()
    assert budget['within_complete_budget'] and not rec['remaining_group']
    if label=='normal-full450':
        assert rec['returncode']==0 and not rec['error'] and not budget['working_deadline_expired']
        assert rec['group_signals']==[]
    else:
        assert budget['working_deadline_expired'] and 'complete terminal working deadline expired' in rec['error']
        assert rec['returncode']==-9
        assert 'SIGKILL_bound_unreaped_group' in rec.get('group_signals',rec.get('signals',[]))
        if kind=='native':assert rec['leader_reaped'] and not rec['normal_completion']
    identity=rec['child_identity'];unit=Path('/proc')/str(identity['pid'])
    if unit.exists():
        fields=(unit/'stat').read_text().rsplit(')',1)[1].split()
        assert fields[19]!=identity['starttime']
    row=dict(label=label,explicit_fake_auditor=True,inner_cap_s=180 if kind=='paired' else 60,
             process=rec,whole_budget=budget,passed=True)
    save(case/'CASE_RESULT.json',row);records.append(row)
save(ROOT/'CONTROL_RESULTS.json',dict(schema='terminal_whole_budget_three_new_contexts_v1',
    passed=True,controls=3,records=records,actual_model_calls=0,actual_eda_calls=0,
    new_fifo=False,original_collector_executed=False,original_auditor_executed=False,
    terminal_supervisor_executed=False,native_qualified=False,natural_score=False))
print(json.dumps(dict(passed=True,controls=3,elapsed_s=[r['whole_budget']['elapsed_s'] for r in records])))
