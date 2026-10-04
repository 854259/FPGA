"""AMD-only extraction audit: fixed guards, two captured replies, paired judging."""
import argparse
import ctypes
import hashlib
import importlib.util
import json
import re
import shutil
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write('\n')


def materials():
    top = 'module TopModule(input a, output y);\nH h(.a(a), .y(y));\nendmodule\n'
    helper = 'module H(input a, output y);\nassign y=~a;\nendmodule\n'
    flat = 'module TopModule(input a, output y); assign y=~a; endmodule\n'
    wrong = helper.replace('~a', 'a')
    fence = lambda s: '```verilog\n' + s + '```\n'
    cases = [
        ('helper_after', fence(top+helper), True, True),
        ('helper_before', fence(helper+top), True, True),
        ('nested_helpers', fence(top+helper.replace('assign y=~a;', 'G g(.a(a), .y(y));')+helper.replace('module H(', 'module G(')), True, True),
        ('wrong_helper_preserved', fence(top+wrong), True, False),
        ('correct_flat_guard', fence(flat), False, True),
        ('missing_helper', fence(top), False, None),
        ('truncated_helper', fence(top+helper.replace('endmodule', '')), False, None),
        ('duplicate_top', fence(top+helper+top), False, None),
        ('duplicate_helper', fence(top+helper+helper), False, None),
        ('alternative_fences', fence(top+helper)+fence(flat), False, None),
        ('unclosed_fence', '```verilog\n'+top+helper, False, None),
        ('macro_context', fence('`define SOME_MACRO 1\n'+top+helper), False, None),
        ('package_context', fence('package P; endpackage\n'+top+helper), False, None),
        ('fake_endmodule_comment', fence(top.replace('H h', '/* endmodule */ H h')+helper), False, None),
        ('missing_transitive_helper', fence(top+helper.replace('assign y=~a;', 'G g(.a(a), .y(y));')), False, None),
        ('unused_helper_guard', fence(flat+helper), False, True),
        ('endmodule_label', fence(top.replace('endmodule', 'endmodule : TopModule')+helper), False, None),
        ('plain_unfenced', top+helper, False, None),
        ('unsupported_language', fence(top+helper).replace('```verilog', '```cpp'), False, None),
        ('positional_instantiation', fence(top.replace('.a(a), .y(y)', 'a, y')+helper), False, None),
        ('one_line_instantiation_abstains', fence(top.replace('\n', ' ')+helper), False, None),
    ]
    tb = '''`timescale 1ns/1ps
module R2Probe;
reg a=0; wire y; integer i, checks=0, mismatches=0;
TopModule dut(.a(a), .y(y));
initial begin
 for(i=0;i<4;i=i+1) begin
  a=i%2; #2; checks=checks+1;
  if(y !== !a) mismatches=mismatches+1;
 end
 $display("R2_PROBE_RESULT task=HelperGate checks=%0d mismatches=%0d",checks,mismatches);
 $finish;
end
endmodule
'''
    return cases, flat, flat.replace('~a', 'a'), tb


def run(args):
    if sys.platform != 'linux' or ctypes.CDLL(None, use_errno=True).prctl(36, 1, 0, 0, 0):
        raise RuntimeError('AMD Linux subreaper required')
    spec = json.loads(args.spec.read_text())
    originals = {str(args.kit/k):v for k,v in spec['kit_hashes'].items()}
    tasks_root = Path(spec['tasks_root'])
    for name, files in spec['task_hashes'].items():
        originals.update({str(tasks_root/name/k):v for k,v in files.items()})
    if any(sha(p) != h for p,h in originals.items()):
        raise RuntimeError('frozen input mismatch')
    paired = load('helper_pair', REPO/'03_analysis/selective_runtime_integration_20261003/paired_next/paired_checkpoint.py')
    baseline = load('helper_baseline', args.kit/'submission/baseline.py')
    runtime = load('helper_runtime', args.kit/'submission/agent/runtime.py')
    selector = load('helper_lexer', REPO/'03_analysis/selective_runtime_integration_20261003/package/agent/signedness_selector.py')
    extraction = load('helper_extraction', REPO/'03_analysis/semantic_repair_20261004/complete_module_extract.py')
    evaluator = load('helper_evaluator', args.kit/'official_eval.py')
    assert evaluator.verify_upstream() == spec['upstream_commit']
    paired.check_resource(args.resource_check, args.kit, first=True)
    args.out.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    report = dict(schema='helper_extraction_f1', complete=False, valid=False, model_calls=0, responses=0,
                  retries=0, guards=[], live=[], error=None, original_hashes=originals, formal_runtime_modified=False)
    extract = lambda text: extraction.extract_hierarchy(text, baseline, selector._strip_noncode, runtime.undefined_submodules)
    try:
        if args.preflight_only:
            report['references']={}
            for name in spec['preflight_tasks']:
                paired.check_resource(args.resource_check,args.kit)
                task_copy=args.out/'preflight'/name/'task';shutil.copytree(tasks_root/name,task_copy)
                dst=args.out/'preflight'/name/'grade';dst.mkdir(parents=True)
                verdict=evaluator.judge_sample(task_copy,task_copy/'reference/solution.sv',dst,dst/'verdict.json',90)
                report['references'][name]=verdict
                assert verdict['level']==3 and not verdict.get('tool_error') and not verdict.get('suspected_silent_degradation'),(name,verdict)
                print(json.dumps(dict(phase='reference_preflight',task=name,level=verdict['level'])),flush=True)
            assert all(sha(p)==h for p,h in originals.items())
            report.update(complete=True,valid=True,inputs_unchanged=True,decision='reference_preflight_only_no_generation_authorized_by_this_run')
            return
        cases, positive, negative, tb = materials()
        folder = args.out/'inputs/HelperGate'; folder.mkdir(parents=True)
        for name, value in [('positive.sv', positive), ('negative.sv', negative), ('tb.sv',tb)]:
            (folder/name).write_text(value)
        save(args.out/'guards_frozen.json', {'cases':cases,'tb_sha256':sha(folder/'tb.sv')})
        probe = lambda source, out: paired.oracle(dict(task='HelperGate',checks=4,tb=str(folder/'tb.sv')),source,out)
        controls = {name:probe(folder/(name+'.sv'),args.out/'controls'/name) for name in ['positive','negative']}
        report['controls']=controls
        assert controls['positive']['status']=='pass' and controls['negative']['failure_kind']=='semantic_mismatch'
        for name, raw, expected_changed, expected_correct in cases:
            paired.check_resource(args.resource_check,args.kit)
            old=baseline.extract(raw,'rtl');new,record=extract(raw)
            assert record['changed']==expected_changed, (name,record)
            assert extract(raw)==(new,record),name
            if not expected_changed: assert new==old,name
            row=dict(name=name,expected_changed=expected_changed,selection=record,repeated_identical=True,
                     original_sha256=hashlib.sha256(old.encode()).hexdigest(),final_sha256=hashlib.sha256(new.encode()).hexdigest())
            report['guards'].append(row)
            d=args.out/'guards'/name;d.mkdir(parents=True)
            (d/'raw.txt').write_text(raw);(d/'original.sv').write_text(old);(d/'final.sv').write_text(new)
            if expected_correct is not None:
                row['final_probe']=probe(d/'final.sv',d/'final_probe')
                assert row['final_probe']['status'] != 'environment_error',row
                assert (row['final_probe']['status']=='pass')==expected_correct,row
                if not expected_correct: assert row['final_probe']['failure_kind']=='semantic_mismatch',row
                if expected_changed:
                    row['original_probe']=probe(d/'original.sv',d/'original_probe')
                    assert row['original_probe']['status']=='fail',row
                    assert row['original_probe']['failure_kind']!='semantic_mismatch',row
            save(d/'receipt.json',row)
        report['guards_verified']=True
        print(json.dumps(dict(phase='guards_complete',cases=len(cases),model_calls=0)),flush=True)
        # Unchanged final RTL is not raw response evidence; use it only as a no-op guard.
        report['archive_preservation']={}
        for archive, expected_count in zip(spec['archives'], spec['expected_archive_counts']):
            rows=[]
            for p in sorted(Path(archive).glob('*/s0/solution.v')):
                raw=p.read_text();old=baseline.extract(raw,'rtl');new,record=extract(raw)
                assert new==old and not record['changed'],p
                rows.append(dict(task=p.parent.parent.name,sha256=sha(p)))
            assert len(rows)==expected_count,(archive,len(rows))
            report['archive_preservation'][archive]=dict(candidates=len(rows),changed=0)
            save(args.out/('archive_'+str(len(report['archive_preservation']))+'.json'),rows)
        save(args.out/'precall.json',report)
        for sample_index,name in enumerate(spec['order']):
            paired.check_resource(args.resource_check,args.kit)
            paired.model_idle('http://127.0.0.1:8000/v1',spec['model'])
            if report['model_calls']>=spec['max_new_model_calls'] or time.monotonic()-started>spec.get('max_pre_request_elapsed_s',1000):
                raise RuntimeError('call/time ceiling before request')
            assert all(sha(p)==h for p,h in originals.items())
            prompt=(tasks_root/name/'prompt.txt').read_text()
            skill=(args.kit/'submission/skill/rtl-generation/SKILL.md').read_text()
            body=dict(model=spec['model'],messages=[dict(role='system',content=skill),dict(role='user',content=prompt)],temperature=0,top_p=1.0,max_tokens=8192)
            sample_key=name if spec['order'].count(name)==1 else name+'_'+str(sample_index)
            d=args.out/'live'/sample_key;d.mkdir(parents=True)
            save(d/'request.json',body)
            report['model_calls']+=1
            save(d/'attempt_started.json',dict(number=report['model_calls'],request_sha256=sha(d/'request.json')))
            tick=time.monotonic()
            request=urllib.request.Request('http://127.0.0.1:8000/v1/chat/completions',data=json.dumps(body).encode(),headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(request,timeout=300) as response:payload=json.load(response)
            save(d/'response.json',payload);report['responses']+=1
            choice=payload['choices'][0];raw=choice['message'].get('content') or ''
            (d/'raw.txt').write_text(raw)
            paired.model_idle('http://127.0.0.1:8000/v1',spec['model'])
            old=baseline.extract(raw,'rtl');new,record=extract(raw)
            (d/'original.sv').write_text(old);(d/'final.sv').write_text(new)
            row=dict(task=name,sample_key=sample_key,generation_s=time.monotonic()-tick,finish=choice.get('finish_reason'),usage=payload.get('usage'),selection=record,
                     raw_sha256=sha(d/'raw.txt'),original_sha256=sha(d/'original.sv'),final_sha256=sha(d/'final.sv'),request_sha256=sha(d/'request.json'))
            report['live'].append(row)
            if not raw or choice.get('finish_reason')!='stop':
                raise RuntimeError('incomplete generation; preserve without retry')
            # Judge sees reference/TB only after the model request and extraction are frozen.
            task_copy=d/'judge_task';shutil.copytree(tasks_root/name,task_copy)
            for kind, source in [('reference',task_copy/'reference/solution.sv'),('original',d/'original.sv'),('final',d/'final.sv')]:
                if kind=='final' and old==new:
                    row[kind]=row['original'];row['final_reused_original']=True;continue
                paired.check_resource(args.resource_check,args.kit)
                dst=d/'grades'/kind;dst.mkdir(parents=True)
                v=evaluator.judge_sample(task_copy,source,dst,dst/'verdict.json',90)
                row[kind]=v
                if v.get('tool_error') or v.get('suspected_silent_degradation'):raise RuntimeError('judge infrastructure/evidence error')
                if kind=='reference' and v['level']!=3:raise RuntimeError('reference control not L3')
            row.update(functional_repair=row['original']['level']<2 and row['final']['level']==3,
                       regression=row['final']['level']<row['original']['level'])
            save(d/'receipt.json',row)
            print(json.dumps(dict(phase='live_pair',task=name,old=row['original']['level'],new=row['final']['level'],model_calls=report['model_calls'])),flush=True)
            if row['regression']:raise RuntimeError('regression; stop expansion')
        assert all(sha(p)==h for p,h in originals.items())
        paired.check_resource(args.resource_check,args.kit)
        report.update(complete=True,valid=True,inputs_unchanged=True,
            decision='retain_research_only_pending_best_runtime_integration_and_independent_validation' if any(r['functional_repair'] for r in report['live']) else 'no_observed_natural_repair_do_not_promote')
    except BaseException as exc:
        report['error']=type(exc).__name__+': '+str(exc)
        raise
    finally:
        report['elapsed_s']=time.monotonic()-started
        save(args.out/'summary.json',report)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--kit',type=Path,required=True);p.add_argument('--resource-check',type=Path,required=True);p.add_argument('--out',type=Path,required=True)
    p.add_argument('--spec',type=Path,default=HERE/'RUN_SPEC.json');p.add_argument('--preflight-only',action='store_true')
    run(p.parse_args())
