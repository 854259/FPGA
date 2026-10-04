"""Frozen AMD I1: bounded elaboration fallback, captured workers, then fresh pairs."""
import argparse
import ctypes
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from pilot import REPO, load, save, sha, materials
from replay_best import BEST
from full_pair import elaboration_gate

HERE=Path(__file__).resolve().parent
OLD=Path('/workspace/team/runs/fpga_teammate/rtllm_pair_20261002T074340Z')
PACKAGE=Path('/workspace/team/runs/fpga_teammate/helper_G1_20261004T052000Z_3576ccf/results/package')


def engineering(out, package, paired, kit):
    baseline=load('i1_baseline',package/'baseline.py')
    runtime=load('i1_runtime',package/'agent/runtime.py')
    extension=load('i1_extract',REPO/'03_analysis/semantic_repair_20261004/complete_module_extract.py')
    lexer=load('i1_lexer',REPO/'03_analysis/selective_runtime_integration_20261003/package/agent/signedness_selector.py')
    detector=load('i1_detector',kit/'submission/agent/runtime.py')
    cases,positive,negative,tb=materials()
    top='module TopModule(input a, output y);\nH h(.a(a), .y(y));\nendmodule\n'
    helper='module H(input a, output y);\nassign y=~a;\nendmodule\n'
    fence=lambda s:'\x60\x60\x60verilog\n'+s+'\x60\x60\x60\n'
    extra=[
        ('parameterized_helper',fence(top.replace('H h','H #(.W(1)) h')+
         'module H #(parameter W=1)(input [W-1:0] a, output [W-1:0] y);\nassign y=~a;\nendmodule\n'),True,True),
        ('multiple_drivers',fence(top+'module H(input a, output reg y);\nalways @(*) y=a;\nassign y=~a;\nendmodule\n'),True,False),
        ('syntax_error_helper',fence(top+helper.replace('assign y=~a;','assign y = ;')),True,False),
        ('file_access_helper',fence(top+helper.replace('assign y=~a;','integer f; initial f=$fopen("unused.txt"); assign y=~a;')),True,False)]
    fixed=[dict(name=n,raw=t,selector_changed=c,accept=c,semantic_expected=s) for n,t,c,s in cases]
    fixed += [dict(name=n,raw=t,selector_changed=c,accept=a,semantic_expected=None) for n,t,c,a in extra]
    save(out/'frozen_controls.json',fixed)
    rows=[]
    for item in fixed:
        old=baseline.extract(item['raw'],'rtl')
        new,selection=extension.extract_hierarchy(item['raw'],baseline,lexer._strip_noncode,detector.undefined_submodules)
        assert selection['changed']==item['selector_changed'],(item['name'],selection)
        gate=elaboration_gate(new,out/item['name'],runtime,paired) if selection['changed'] else None
        accepted=bool(gate and gate['accepted'])
        final=new if accepted else old
        row=dict(name=item['name'],selection=selection,gate=gate,accepted=accepted,
                 expected_accept=item['accept'],original_preserved=final==old,
                 final_sha256=hashlib.sha256(final.encode()).hexdigest())
        rows.append(row)
        assert accepted==item['accept'],row
        if not accepted:assert final==old
        # This deliberately wrong helper must pass elaboration: structure is not semantics.
        if item['name']=='wrong_helper_preserved':assert accepted and item['semantic_expected'] is False
    flat=positive
    missing=elaboration_gate(flat,out/'missing_tool',SimpleNamespace(vivado_tool=lambda n:None),paired)
    assert not missing['accepted'] and missing['reason']=='tool_unavailable'
    fake=out/'timeout_tool'
    fake.write_text('#!/usr/bin/env python3\nimport subprocess,time\np=subprocess.Popen(["sleep","60"])\nprint(p.pid,flush=True)\ntime.sleep(60)\n')
    fake.chmod(0o700)
    timeout=elaboration_gate(flat,out/'timeout',SimpleNamespace(vivado_tool=lambda n:str(fake)),paired,seconds=.25)
    assert timeout['reason']=='timeout' and not timeout['accepted']
    assert timeout['stages'] and not timeout['stages'][0]['remaining_live_group']
    save(out/'engineering.json',dict(passed=True,cases=rows,missing_tool=missing,timeout=timeout,
         semantic_safety_proven=False,wrong_function_passes_structure=True))
    return dict(passed=True,cases=rows,missing_tool=missing,timeout=timeout,
                semantic_safety_proven=False,wrong_function_passes_structure=True)


def run(a):
    assert sys.platform=='linux' and ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)==0
    spec=json.loads((HERE/'ELABORATION_SPEC.json').read_text())
    inherited=json.loads((HERE/'CONTINUATION_SPEC.json').read_text())
    paired=load('i1_paired',REPO/'03_analysis/selective_runtime_integration_20261003/paired_next/paired_checkpoint.py')
    judge=load('i1_judge',a.kit/'official_eval.py')
    assert judge.verify_upstream()==inherited['upstream_commit']
    frozen={a.kit/p:h for p,h in inherited['kit_hashes'].items()}
    for case in spec['captured']:
        frozen.update({Path(case['root'])/p:h for p,h in case['files'].items()})
    h1=Path(spec['h1_root'])
    assert sha(h1/'results/DATASET_MANIFEST.json')==spec['h1_manifest_sha256']
    new_manifest=json.loads((h1/'results/DATASET_MANIFEST.json').read_text())
    tasks=h1/'results/tasks_contract_v1'
    frozen.update({tasks/p:h for p,h in new_manifest['files'].items()})
    old_manifest=json.loads((OLD/'taskset_manifest.json').read_text())
    assert sha(OLD/'taskset_manifest.json')==inherited['input_manifest_sha256']
    frozen.update({OLD/'tasks_verified'/p:h for p,h in old_manifest['task_sha256'].items()})
    frozen.update({PACKAGE/p:h for p,h in inherited['package_hashes'].items()})
    assert all(sha(p)==h for p,h in frozen.items())
    paired.check_resource(a.resource_check,a.kit,first=True)
    a.out.mkdir(parents=True,exist_ok=False);tick=time.monotonic()
    package=a.out/'package';shutil.copytree(PACKAGE,package);assert sha(package/'agent/runtime.py')==BEST
    report=dict(schema='i1_elaboration_fallback',complete=False,execution_valid=False,
                model_calls=0,responses=0,retries=0,rows=[],error=None,stop_reason=None,
                source_commit=(REPO/'DELIVERY_COMMIT').read_text().strip(),formal_deployment_modified=False)
    def publish(phase):
        report.update(phase=phase,elapsed_s=time.monotonic()-tick)
        (a.out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(dict(phase=phase,calls=report['model_calls'],pairs=len(report['rows']),elapsed_s=report['elapsed_s'])),flush=True)
    def gate():
        assert all(sha(p)==h for p,h in frozen.items())
        assert report['model_calls']<=spec['internal_new_model_call_cap']
        paired.check_resource(a.resource_check,a.kit)
    try:
        publish('engineering')
        report['engineering']=engineering(a.out/'engineering',package,paired,a.kit)
        publish('engineering_passed')
        def grade(task,src,dst):
            gate();dst.mkdir(parents=True)
            v=judge.judge_sample(task,src,dst,dst/'verdict.json',90)
            assert not v.get('tool_error') and not v.get('suspected_silent_degradation'),v
            return v
        def pair(label,task,case=None):
            gate()
            assert time.monotonic()-tick<spec['max_pair_start_s']
            if not case:assert report['model_calls']+3<=spec['internal_new_model_call_cap']
            sample=a.out/'pairs'/label;sample.mkdir(parents=True)
            if case:shutil.copyfile(Path(case['root'])/'request.json',sample/'request.json')
            else:
                save(sample/'request.json',dict(model=inherited['model'],
                     messages=[dict(role='system',content=(package/'skill/rtl-generation/SKILL.md').read_text()),
                               dict(role='user',content=(task/'prompt.txt').read_text())],temperature=0,top_p=1,max_tokens=8192))
            row=dict(task=label,captured=bool(case),arms={});report['rows'].append(row)
            for arm in ('original','elaborated_helpers'):
                gate();paired.model_idle('http://127.0.0.1:8000/v1',inherited['model'])
                dest=sample/arm
                cmd=[sys.executable,'-B',str(HERE/'full_pair.py'),'worker','--kit',str(a.kit),'--package',str(package),
                     '--input',str(sample),'--arm',arm,'--out',str(dest)]
                if case:cmd+=['--replay-worker',str(Path(case['root'])/'original')]
                supervision=paired.owned_command(cmd,a.out,sample/(arm+'.log'),660)
                attempts=list(dest.glob('attempt_*.json'))
                received=sum((dest/p.name.replace('attempt_','response_')).exists() for p in attempts)
                report['model_calls']+=len(attempts);report['responses']+=received
                receipt=json.loads((dest/'worker_receipt.json').read_text()) if (dest/'worker_receipt.json').exists() else {'error':'missing_receipt'}
                row['arms'][arm]=receipt;publish('worker_'+label+'_'+arm)
                assert not supervision['timeout'] and supervision['returncode']==0 and received==len(attempts),supervision
                assert receipt['actual_model_calls']==len(attempts) and receipt['responses']==received
                for select in receipt['selections']:
                    if 'gate' in select:
                        assert select['gate']['reason'] not in ('timeout','tool_unavailable','tool_launch_error')
                if case and arm=='original':
                    assert receipt['solution_sha256']==case['files']['original/solution.v']
                if not case and arm=='original':shutil.copyfile(dest/'response_0.json',sample/'response_0.json')
                paired.model_idle('http://127.0.0.1:8000/v1',inherited['model'])
            # Oracle material is introduced only after both worker processes exit.
            evaluation=sample/'judge_task';shutil.copytree(task,evaluation)
            for arm in ('original','elaborated_helpers'):
                row['arms'][arm]['verdict']=grade(evaluation,sample/arm/'solution.v',sample/'grades'/arm)
            x=row['arms']['original']['verdict']['level'];y=row['arms']['elaborated_helpers']['verdict']['level']
            row.update(functional_repair=x!=3 and y==3,correct_broken=x==3 and y!=3,
                       level_regression=y<x,unchanged_level=x==y,
                       final_bytes_identical=sha(sample/'original/solution.v')==sha(sample/'elaborated_helpers/solution.v'))
            save(sample/'pair.json',row);publish('pair_'+label)
            return row
        safe=True
        for case in spec['captured']:
            row=pair(case['label'],OLD/'tasks_verified'/case['task'],case)
            if row['level_regression']:
                safe=False;report['stop_reason']='captured_regression_'+case['label'];break
            if case['label']=='known16':assert row['arms']['elaborated_helpers']['verdict']['level']==3
            if case['label'] in ('known32','correct8','correct_multi'):assert row['final_bytes_identical']
        # Recheck new taskset controls in this exact tool environment before generation.
        if safe:
            report['controls']={}
            for name in spec['fresh_order']:
                checks=200 if name=='adder_bcd' else 2048
                group={}
                for label,src in [('positive',tasks/name/'reference/solution.sv'),('negative',h1/'results'/(name+'_negative.sv'))]:
                    v=grade(tasks/name,src,a.out/'controls'/name/label);group[label]=v
                    assert v['samples']==checks and (v['level']==3 and v['mismatches']==0 if label=='positive' else v['level']==1 and v['mismatches']==checks)
                report['controls'][name]=group;publish('controls_'+name)
            if not a.preflight_only:
                for name in spec['fresh_order']:
                    row=pair(name,tasks/name)
                    if row['level_regression']:
                        report['stop_reason']='fresh_regression_'+name;break
        gate()
        report.update(complete=True,execution_valid=True,inputs_unchanged=True,
                      preflight_only=a.preflight_only,full_experiment_complete=False,
                      decision='preflight_only_no_adoption_or_full_experiment_claim' if a.preflight_only else 'reject_if_regression_otherwise_assess_cost_and_independent_gain')
        publish('completed')
    except BaseException as e:
        report['error']=type(e).__name__+': '+str(e);raise
    finally:publish('finished' if report['complete'] else 'failed')


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ['kit','out','resource-check']:p.add_argument('--'+n,type=Path,required=True)
    p.add_argument('--preflight-only',action='store_true')
    run(p.parse_args())
