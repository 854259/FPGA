"""Frozen AMD continuation: dataset contracts, captured risk, then paired tasks."""
import argparse
import ctypes
import json
import re
import shutil
import sys
import time
from pathlib import Path
from pilot import REPO, load, save, sha
from replay_best import BEST

OLD = Path('/workspace/team/runs/fpga_teammate/rtllm_pair_20261002T074340Z')
CAPTURE = Path('/workspace/team/runs/fpga_teammate/helper_F1r2_20261004T045633Z_829a00d/results/live/adder_32bit')
BEST_PACKAGE = Path('/workspace/team/runs/fpga_teammate/helper_G1_20261004T052000Z_3576ccf/results/package')
TASKS = ('adder_bcd', 'barrel_shifter')
LABEL = re.compile(r'Module\s+name\s*[:：]\s*([A-Za-z_]\w*)', re.I)


def contract_material(name):
    # Evaluator-only independent arithmetic controls. Never passed to worker.
    if name == 'adder_bcd':
        ports = [('input','A','[3:0]'),('input','B','[3:0]'),('input','Cin',''),
                 ('output','Sum','[3:0]'),('output','Cout','')]
        decl = 'reg [3:0] A,B; reg Cin; wire [3:0] Sum,RSum; wire Cout,RCout; integer a,b,c,total;'
        conn = '.A(A),.B(B),.Cin(Cin),.Sum(Sum),.Cout(Cout)'
        refconn = conn.replace('.Sum(Sum)', '.Sum(RSum)').replace('.Cout(Cout)', '.Cout(RCout)')
        body = """
for(a=0;a<10;a=a+1) for(b=0;b<10;b=b+1) for(c=0;c<2;c=c+1) begin
 A=a; B=b; Cin=c; #1; total=a+b+c;
 if(RSum !== (total%10) || RCout !== (total>=10)) $fatal(1,"CONTRACT_REFERENCE_MISMATCH");
 samples=samples+1;
 if(Sum !== RSum || Cout !== RCout) errors=errors+1;
end
"""
        checks = 200
    else:
        ports = [('input','in','[7:0]'),('input','ctrl','[2:0]'),('output','out','[7:0]')]
        decl = 'reg [7:0] in; reg [2:0] ctrl; wire [7:0] out,Rout; integer a,c;'
        conn = '.in(in),.ctrl(ctrl),.out(out)'
        refconn = '.in(in),.ctrl(ctrl),.out(Rout)'
        body = """
for(a=0;a<256;a=a+1) for(c=0;c<8;c=c+1) begin
 in=a; ctrl=c; #1;
 if(Rout !== (in >> ctrl)) $fatal(1,"CONTRACT_REFERENCE_MISMATCH");
 samples=samples+1;
 if(out !== Rout) errors=errors+1;
end
"""
        checks = 2048
    tb = ('`timescale 1ns/1ps\nmodule tb;\n'+decl+'\ninteger errors=0,samples=0;\n'
          +'TopModule dut('+conn+');\nRefModule reference_dut('+refconn+');\ninitial begin\n'
          +body+'$display("Mismatches: %1d in %1d samples",errors,samples); $finish;\nend\nendmodule\n')
    return ports, tb, checks


def negative_control(source, ports):
    # Clone reference as an evaluator control, invert one output bit-vector.
    inner = re.sub(r'\bTopModule\b','NegativeCore',source)
    names = [p[1] for p in ports]
    outputs = [p for p in ports if p[0]=='output']
    declarations = [f'{d} {w} {n};' for d,n,w in ports]
    wires = [f'wire {w} internal_{n};' for _,n,w in outputs]
    bindings = [f'.{n}('+('internal_'+n if d=='output' else n)+')' for d,n,w in ports]
    assignments = [f'assign {n} = '+('~' if i==0 else '')+f'internal_{n};' for i,(_,n,_) in enumerate(outputs)]
    return inner+'\nmodule TopModule('+','.join(names)+');\n'+'\n'.join(declarations+wires+['NegativeCore core('+','.join(bindings)+');']+assignments)+'\nendmodule\n'


def prepare_dataset(out, builder, original):
    tasks=out/'tasks_contract_v1';shutil.copytree(OLD/'tasks_verified',tasks)
    descriptions=out/'recovered_descriptions';descriptions.mkdir()
    rows=[]
    for folder in sorted(tasks.iterdir()):
        p=folder/'prompt.txt';old=p.read_text();labels=LABEL.findall(old);raw=old
        if len(labels)==2:
            prefix='Module name: TopModule\n\n'
            assert labels==['TopModule',folder.name] and old.startswith(prefix)
            raw=old[len(prefix):]
        else:assert labels==['TopModule']
        desc=descriptions/(folder.name+'.txt');desc.write_text(raw)
        new=builder.load_prompt(desc,folder.name)
        assert LABEL.findall(new)==['TopModule']
        # Apart from removal/normalization of module labels, preserve prompt bytes.
        assert LABEL.sub('Module name: NAME',raw)==LABEL.sub('Module name: NAME',new)
        if len(labels)==1:assert old==new
        p.write_text(new)
        meta=json.loads((folder/'task.json').read_text());assert meta['top']=='TopModule'
        top=builder.parse_module((folder/'reference/solution.sv').read_text(),prefer='TopModule')
        ref=builder.parse_module((folder/'ref.sv').read_text(),prefer='RefModule')
        instance=re.search(r'\bdut\s*\((.*?)\);',(folder/'tb.sv').read_text(),re.S)
        connections=re.findall(r'\.([A-Za-z_]\w*)\s*\(',instance[1]) if instance else []
        same_ports=bool(top and ref and top[1]==ref[1])
        tb_ports_match=bool(top and set(connections)=={p[1] for p in top[1]})
        rows.append(dict(task=folder.name,old_prompt_sha256=original[folder.name+'/prompt.txt'],
                         new_prompt_sha256=sha(p),prompt_changed=old!=new,labels=LABEL.findall(new),
                         reference_interfaces_match=same_ports,tb_named_ports_match=tb_ports_match,
                         semantic_contract_status='not_fully_audited'))
    assert len(rows)==44 and sum(r['prompt_changed'] for r in rows)==23
    for name in TASKS:
        ports,tb,checks=contract_material(name);folder=tasks/name
        parsed=builder.parse_module((folder/'reference/solution.sv').read_text(),prefer='TopModule')
        actual=[(d,n,('['+w+']') if w else '') for d,n,w in parsed[1]]
        assert actual==ports,(name,actual,ports)
        (folder/'tb.sv').write_text(tb)
        (out/(name+'_negative.sv')).write_text(negative_control((folder/'reference/solution.sv').read_text(),ports))
        next(r for r in rows if r['task']==name).update(semantic_contract_status='pending_exhaustive_controls',checks=checks,independent_arithmetic_reference_check=True)
    hashes={str(p.relative_to(tasks)):sha(p) for p in sorted(tasks.rglob('*')) if p.is_file()}
    save(out/'DATASET_MANIFEST.json',dict(version='rtllm_contract_v1_20261004',source_manifest_sha256=sha(OLD/'taskset_manifest.json'),rows=rows,files=hashes,
         reused_prompt_fix_commit='ef72fc69a004d42ea1b4c1cf24eeac2607432f8e',
         recovered_description_method='remove only known legacy TopModule prefix, apply unchanged corrected load_prompt; preserve non-name text',
         original_set_modified=False,full_dataset_contract_verified=False))
    return tasks,hashes,rows


def main(a):
    assert sys.platform=='linux' and ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)==0
    spec=json.loads((Path(__file__).parent/'CONTINUATION_SPEC.json').read_text())
    assert sha(OLD/'taskset_manifest.json')==spec['input_manifest_sha256']
    old=json.loads((OLD/'taskset_manifest.json').read_text())['task_sha256']
    assert len(old)==220 and all(sha(OLD/'tasks_verified'/p)==h for p,h in old.items())
    paired=load('continuation_owned',REPO/'03_analysis/selective_runtime_integration_20261003/paired_next/paired_checkpoint.py')
    judge=load('continuation_judge',a.kit/'official_eval.py')
    builder=load('continuation_builder',REPO/'04_project/amd_rtl_agent/bench/build_rtllm_taskset.py')
    assert judge.verify_upstream()==spec['upstream_commit']
    assert all(sha(a.kit/p)==h for p,h in spec['kit_hashes'].items())
    assert sha(CAPTURE/'request.json')==spec['capture_request_sha256']
    assert sha(CAPTURE/'response.json')==spec['capture_response_sha256']
    paired.check_resource(a.resource_check,a.kit,first=True)
    a.out.mkdir(parents=True,exist_ok=False);tick=time.monotonic()
    report=dict(complete=False,execution_valid=False,phase='prepare',model_calls=0,responses=0,controls={},pairs=[],error=None,stop_reason=None,source_commit=(REPO/'DELIVERY_COMMIT').read_text().strip())
    def publish(phase):
        report.update(phase=phase,elapsed_s=time.monotonic()-tick)
        (a.out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(dict(phase=phase,model_calls=report['model_calls'],pairs=len(report['pairs']),elapsed_s=report['elapsed_s'])),flush=True)
    try:
        tasks,hashes,rows=prepare_dataset(a.out,builder,old)
        package=a.out/'package';shutil.copytree(BEST_PACKAGE,package)
        assert sha(package/'agent/runtime.py')==BEST
        for p,h in spec['package_hashes'].items():assert sha(package/p)==h
        publish('dataset_prepared')
        def gate():
            assert all(sha(tasks/p)==h for p,h in hashes.items())
            assert all(sha(OLD/'tasks_verified'/p)==h for p,h in old.items())
            assert report['model_calls']<=9
            paired.check_resource(a.resource_check,a.kit)
        def grade(task,source,dst):
            gate();dst.mkdir(parents=True,exist_ok=False)
            v=judge.judge_sample(task,source,dst,dst/'verdict.json',90)
            if v.get('tool_error') or v.get('suspected_silent_degradation'):raise RuntimeError('judge environment/evidence error')
            return v
        for name in TASKS:
            checks=contract_material(name)[2];group={}
            for label,source in [('positive',tasks/name/'reference/solution.sv'),('negative',a.out/(name+'_negative.sv'))]:
                v=grade(tasks/name,source,a.out/'controls'/name/label);group[label]=v
                assert v['samples']==checks and (v['level']==3 and v['mismatches']==0 if label=='positive' else v['level']==1 and v['mismatches']==checks),(name,label,v)
            report['controls'][name]=group
            next(r for r in rows if r['task']==name)['semantic_contract_status']='exhaustive_default_domain_controls_passed'
            publish('control_passed_'+name)
        def pair(name,task,captured=None):
            gate()
            assert time.monotonic()-tick<1500 and report['model_calls']+3<=9
            sample=a.out/'pairs'/name;sample.mkdir(parents=True)
            if captured:
                shutil.copyfile(captured/'request.json',sample/'request.json');shutil.copyfile(captured/'response.json',sample/'response_0.json')
            else:
                body=dict(model=spec['model'],messages=[dict(role='system',content=(package/'skill/rtl-generation/SKILL.md').read_text()),dict(role='user',content=(task/'prompt.txt').read_text())],temperature=0,top_p=1,max_tokens=8192)
                save(sample/'request.json',body)
            row=dict(task=name,captured_initial=bool(captured),arms={});report['pairs'].append(row)
            for arm in ['original','retained_helpers']:
                gate();paired.model_idle('http://127.0.0.1:8000/v1',spec['model'])
                dest=sample/arm
                cmd=[sys.executable,'-B',str(Path(__file__).parent/'full_pair.py'),'worker','--kit',str(a.kit),'--package',str(package),'--input',str(sample),'--arm',arm,'--out',str(dest)]
                if captured:cmd+=['--replay-initial']
                supervision=paired.owned_command(cmd,a.out,sample/(arm+'.log'),660)
                attempts=list(dest.glob('attempt_*.json'));received=sum((dest/p.name.replace('attempt_','response_')).exists() for p in attempts)
                report['model_calls']+=len(attempts);report['responses']+=received
                receipt=json.loads((dest/'worker_receipt.json').read_text()) if (dest/'worker_receipt.json').exists() else dict(error='missing_worker_receipt')
                row['arms'][arm]=receipt
                publish('worker_'+name+'_'+arm)
                if supervision['returncode']!=0 or supervision['timeout'] or received!=len(attempts):raise RuntimeError('worker transport/execution failure; no retry')
                assert receipt['actual_model_calls']==len(attempts) and receipt['responses']==received
                if arm=='original' and not captured:shutil.copyfile(dest/'response_0.json',sample/'response_0.json')
                paired.model_idle('http://127.0.0.1:8000/v1',spec['model'])
            evaluation=sample/'judge_task';shutil.copytree(task,evaluation)
            for arm in ['original','retained_helpers']:
                row['arms'][arm]['verdict']=grade(evaluation,sample/arm/'solution.v',sample/'grades'/arm)
            x=row['arms']['original']['verdict']['level'];y=row['arms']['retained_helpers']['verdict']['level']
            row.update(repair=x<2 and y==3,regression=y<x,unchanged_level=x==y)
            save(sample/'pair.json',row);publish('pair_'+name)
            return not row['regression']
        safe=pair('captured_adder_32bit',OLD/'tasks_verified/adder_32bit',CAPTURE)
        if safe:
            for name in TASKS:
                if not pair(name,tasks/name):
                    report['stop_reason']='observed_regression_on_'+name;break
        else:report['stop_reason']='observed_regression_on_captured_adder_32bit'
        gate()
        report.update(complete=True,execution_valid=True,inputs_unchanged=True,dataset_rows=rows,decision='reject_automatic_extraction' if report['stop_reason'] else 'review_independent_evidence_before_promotion')
        publish('completed')
    except BaseException as e:
        report['error']=type(e).__name__+': '+str(e);raise
    finally:
        publish('finished' if report['complete'] else 'failed')


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ['kit','out','resource-check']:p.add_argument('--'+n,type=Path,required=True)
    main(p.parse_args())
