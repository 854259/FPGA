"""K1 frozen zero-model engineering plus four archived complete-worker pairs."""
import argparse
import ctypes
import json
import shutil
import sys
import time
from pathlib import Path
from pilot import REPO, load, materials, save, sha
from elaboration_batch import OLD


def run(a):
    assert sys.platform=='linux' and ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)==0
    here=Path(__file__).parent
    spec=json.loads((here/'CONTINUATION_SPEC.json').read_text())
    captured=json.loads((here/'ELABORATION_SPEC.json').read_text())['captured']
    frozen={a.kit/p:h for p,h in spec['kit_hashes'].items()}
    frozen.update({a.package/p:h for p,h in spec['package_hashes'].items()})
    for case in captured: frozen.update({Path(case['root'])/p:h for p,h in case['files'].items()})
    manifest=OLD/'taskset_manifest.json';assert sha(manifest)==spec['input_manifest_sha256']
    frozen.update({OLD/'tasks_verified'/p:h for p,h in json.loads(manifest.read_text())['task_sha256'].items()})
    assert all(sha(p)==h for p,h in frozen.items())
    paired=load('k1_owned',REPO/'03_analysis/selective_runtime_integration_20261003/paired_next/paired_checkpoint.py')
    judge=load('k1_judge',a.kit/'official_eval.py');assert judge.verify_upstream()==spec['upstream_commit']
    paired.check_resource(a.resource_check,a.kit,first=True)
    a.out.mkdir(parents=True,exist_ok=False);package=a.out/'package';shutil.copytree(a.package,package)
    cases,positive,negative,tb=materials();replies={name:reply for name,reply,_,_ in cases}
    fence=lambda x:'```verilog\n'+x+'```\n'
    good=replies['helper_after'];wrong=replies['wrong_helper_preserved']
    # Booleans are frozen expected source-change decisions, not quality claims.
    constructed=[('successful_repair',wrong,fence(positive),False),
                 ('correct_initial_helper',good,fence(positive),False),
                 ('persistent_good_helper',good,good,True),
                 ('persistent_wrong_helper',wrong,wrong,True),
                 ('ambiguous_last',good,good+fence(positive),False),
                 ('uncompilable_last',good,good.replace('~a',''),False),
                 ('last_flat_wrong',good,fence(negative),False)]
    prompt='Module name: TopModule. Input a is one bit; output y is one bit. Combinationally y = ~a. No clock or state. Return synthesizable Verilog.'
    body=dict(model=spec['model'],messages=[dict(role='system',content=(package/'skill/rtl-generation/SKILL.md').read_text()),dict(role='user',content=prompt)],temperature=0,top_p=1.0,max_tokens=8192)
    rows=[];report=dict(complete=False,valid=False,rows=rows,model_calls=0,full_round_complete=False,error=None)
    tick=time.monotonic()
    try:
        jobs=[dict(name=n,first=x,last=y,changed=c,constructed=True) for n,x,y,c in constructed]
        jobs += [dict(name=c['label'],case=c,constructed=False) for c in captured]
        for job in jobs:
            assert time.monotonic()-tick<700, 'not enough reserved time for grading'
            paired.check_resource(a.resource_check,a.kit)
            sample=a.out/'pairs'/job['name'];sample.mkdir(parents=True)
            if job['constructed']:
                save(sample/'request.json',body);save(sample/'constructed_replies.json',[job['first'],job['last']])
            else:shutil.copyfile(Path(job['case']['root'])/'request.json',sample/'request.json')
            row=dict(name=job['name'],constructed=job['constructed'],arms={});rows.append(row)
            for arm in ('original','postrepair_helpers'):
                if job['constructed'] and arm=='original':
                    cmd=[sys.executable,'-B',str(here/'repair_bypass_probe.py'),'worker']
                else:
                    replay=sample/'original' if job['constructed'] else Path(job['case']['root'])/'original'
                    cmd=[sys.executable,'-B',str(here/'full_pair.py'),'worker','--arm',arm,'--replay-worker',str(replay)]
                dest=sample/arm
                cmd+=['--kit',str(a.kit),'--package',str(package),'--input',str(sample),'--out',str(dest)]
                owned=paired.owned_command(cmd,a.out,sample/(arm+'.log'),150)
                assert owned['returncode']==0 and not owned['timeout'] and not owned['remaining_live_group'],owned
                receipt=json.loads((dest/'worker_receipt.json').read_text());assert receipt['actual_model_calls']==0
                row['arms'][arm]=dict(receipt=receipt,supervision=owned)
            old,new=sample/'original',sample/'postrepair_helpers'
            for pattern in ('request_*.json','response_*.json'):
                assert {p.name:sha(p) for p in old.glob(pattern)}=={p.name:sha(p) for p in new.glob(pattern)}
            row['final_bytes_identical']=sha(old/'solution.v')==sha(new/'solution.v')
            if job['constructed']:assert row['final_bytes_identical']==(not job['changed']),job['name']
            else:assert sha(old/'solution.v')==job['case']['files']['original/solution.v']
            print(json.dumps(dict(phase='workers_complete',name=job['name'],changed=not row['final_bytes_identical'])),flush=True)
        # All complete workers end before any grading assets are materialized.
        assets=a.out/'judge_assets/HelperGate';assets.mkdir(parents=True);(assets/'tb.sv').write_text(tb)
        task=dict(task='HelperGate',checks=4,tb=str(assets/'tb.sv'));controls={}
        for label,code in [('positive',positive),('negative',negative)]:
            p=assets/(label+'.sv');p.write_text(code);controls[label]=paired.oracle(task,p,a.out/'controls'/label)
        assert controls['positive']['status']=='pass' and controls['negative']['failure_kind']=='semantic_mismatch'
        report['controls']=controls
        for row in rows:
            sample=a.out/'pairs'/row['name']
            if not row['constructed']:
                case=next(c for c in captured if c['label']==row['name'])
                task_copy=sample/'judge_task';shutil.copytree(OLD/'tasks_verified'/case['task'],task_copy)
            for arm in ('original','postrepair_helpers'):
                dest=sample/'grades'/arm
                if row['constructed']:
                    verdict=paired.oracle(task,sample/arm/'solution.v',dest)
                    assert verdict['status'] in ('pass','fail'),verdict
                    ok=verdict['status']=='pass'
                else:
                    dest.mkdir(parents=True);verdict=judge.judge_sample(task_copy,sample/arm/'solution.v',dest,dest/'verdict.json',90)
                    assert not verdict.get('tool_error') and not verdict.get('suspected_silent_degradation'),verdict
                    ok=verdict['level']==3
                row['arms'][arm].update(verdict=verdict,functional_pass=ok)
            row['correct_broken']=row['arms']['original']['functional_pass'] and not row['arms']['postrepair_helpers']['functional_pass']
            assert not row['correct_broken'],row['name']
            save(sample/'pair.json',row)
            print(json.dumps(dict(phase='graded',name=row['name'],correct_broken=row['correct_broken'])),flush=True)
        assert all(sha(p)==h for p,h in frozen.items())
        paired.check_resource(a.resource_check,a.kit)
        report.update(complete=True,valid=True,protected_unchanged=True,decision='engineering_only_review_coverage_and_cost_no_adoption')
    except BaseException as exc:
        report['error']=type(exc).__name__+': '+str(exc);raise
    finally:
        report['elapsed_s']=time.monotonic()-tick;save(a.out/'summary.json',report)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ('kit','package','out','resource-check'):p.add_argument('--'+name,type=Path,required=True)
    run(p.parse_args())
