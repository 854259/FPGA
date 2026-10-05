"""Read-only fixed S4/S5 archives; only four pinned pure string functions are evaluated."""
import ast
from collections import Counter
import hashlib
import io
import json
from pathlib import Path
import re
import types
import zipfile

R=Path(__file__).resolve().parent
PINS={
    'S4':('72be46c8150f8bfed9bfeb335fb51979592081bd9c8b4a0da31502bda06ac157',
          '22658a7ca54687254e021cd767303142dd1c0db0038530df9619522f047eb3a0',17,56),
    'S5':('17b28d710dbe42bc41c4648c222dc195ab7e199bc99b92fb4a27fa402076997e',
          '9846de2dd7802ee3d693e7179cac0ae510fafeac3b6916373570aa3a3f1e077a',19,54)}
DRIVER='source/03_analysis/rtllm_contract_audit_20261002/cvdp_name_binding_20261005.py'
DATA='inputs/cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl'
DATA_SHA='cbcd81295561ebb16e4d857e096f4d9908d042c33aff3b58abf236e868411857'
def sha(b):return hashlib.sha256(b).hexdigest()
def read(z,n):return json.loads(z.read(n))


def pure_functions(raw,pin):
    assert sha(raw)==pin
    tree=ast.parse(raw.decode('utf-8'))
    selected=[n for n in tree.body if isinstance(n,ast.FunctionDef)
              and n.name in ['word','valid_name','bind_prompt','bind_source']]
    assert len(selected)==4 and all(not n.decorator_list for n in selected)
    allowed_calls={'bool','list','len','sorted','set','reversed','all','any','enumerate','ValueError','word','valid_name'}
    allowed_methods={'escape','fullmatch','search','finditer','sub','group','span','start','end'}
    for node in ast.walk(ast.Module(body=selected,type_ignores=[])):
        assert not isinstance(node,(ast.Import,ast.ImportFrom,ast.Global,ast.Nonlocal,ast.With,ast.AsyncWith))
        if isinstance(node,ast.Attribute):assert node.attr in allowed_methods
        if isinstance(node,ast.Name):assert not node.id.startswith('__')
        if isinstance(node,ast.Call):
            assert (isinstance(node.func,ast.Name) and node.func.id in allowed_calls
                    or isinstance(node.func,ast.Attribute) and node.func.attr in allowed_methods)
    env={'re':re,'__builtins__':{k:v for k,v in dict(bool=bool,list=list,len=len,sorted=sorted,set=set,
                                                  reversed=reversed,all=all,any=any,enumerate=enumerate,ValueError=ValueError).items()}}
    exec(compile(ast.Module(body=selected,type_ignores=[]),'pinned-pure-name-functions','exec'),env)
    return types.SimpleNamespace(**{n.name:env[n.name] for n in selected})


def keywords(raw):
    assert sha(raw)=='3546fb60545966885a050b74590fd5ce4645ee8f37671e3f1768088c0d98756e'
    tree=ast.parse(raw.decode('utf-8'))
    value=next(n.value for n in tree.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='KEYWORDS' for t in n.targets))
    assert isinstance(value,ast.Call) and isinstance(value.func,ast.Name) and value.func.id=='frozenset'
    arg=value.args[0]
    assert isinstance(arg,ast.Call) and isinstance(arg.func,ast.Attribute) and arg.func.attr=='split'
    return frozenset(ast.literal_eval(arg.func.value).split())


def commands(z,prefix,tool_prefix,expected_top='tb',simulation_rc=0):
    rows=read(z,prefix+'/commands.json');assert len(rows)==2
    expected=[[tool_prefix+'/bin/iverilog','-g2012','-s',expected_top,'-o','simulation.vvp','dut.sv','tb.sv'],
              [tool_prefix+'/bin/vvp','simulation.vvp']]
    for i,row in enumerate(rows):
        assert row['argv']==expected[i] and row['rc']==(0 if i==0 else simulation_rc)
        assert row['log_sha256']==sha(z.read(prefix+f'/command_{i}.log'))
        if 'elapsed_s' in row:assert row['elapsed_s']>=0
    assert z.read(prefix+'/simulation.vvp')
    return z.read(prefix+'/command_1.log').decode('utf-8')


def review(label):
    archive,driver_pin,count,converted_count=PINS[label]
    path=R/'raw_evidence'/(label+'_EVIDENCE.zip');assert sha(path.read_bytes())==archive
    with zipfile.ZipFile(path) as z:
        manifest=read(z,'ARCHIVE_MANIFEST.json')
        assert set(z.namelist())==set(manifest)|{'ARCHIVE_MANIFEST.json'}
        for n,h in manifest.items():
            assert not Path(n).is_absolute() and '..' not in Path(n).parts and sha(z.read(n))==h
        plan=read(z,'PLAN.json');report=read(z,'results/PUBLIC_RESULT.json')
        assert sha(z.read(DRIVER))==plan['driver_sha256']==driver_pin
        assert sha(z.read('SOURCE.zip'))==plan['source_zip_sha256']
        with zipfile.ZipFile(io.BytesIO(z.read('SOURCE.zip'))) as src:
            matching=[n for n in src.namelist() if n.endswith('cvdp_name_binding_20261005.py')]
            assert len(matching)==1 and src.read(matching[0])==z.read(DRIVER)
        funcs=pure_functions(z.read(DRIVER),driver_pin);names=keywords(z.read('inputs/reserved_keywords.py'))
        assert sha(z.read(DATA))==DATA_SHA==plan['dependency_hashes']['data']==report['source_sha256']
        for key,name in [('inventory','PRIVATE_INVENTORY.json'),('toolchain-manifest','TOOLCHAIN_MANIFEST.json'),
                         ('keywords','reserved_keywords.py'),('diagnostic-source','failed_original_dut.sv')]:
            assert sha(z.read('inputs/'+name))==plan['dependency_hashes'][key]
        data=[json.loads(s) for s in z.read(DATA).decode('utf-8').splitlines()]
        assert len(data)==len({d['id'] for d in data})==302
        assert all(not v.strip() for d in data for v in d['output']['context'].values())
        inventory=read(z,'inputs/PRIVATE_INVENTORY.json')['rows'];meta={x['id']:x for x in inventory}
        assert len(meta)==302 and set(meta)=={d['id'] for d in data}
        selected=[x['id'] for x in inventory if x['no_input_single_output'] and x['static_entrypoint_resolved']]
        assert len(selected)==167 and selected==read(z,'results/COHORT.json')['ids']
        binding=read(z,'results/PRIVATE_BINDING.json')['rows'];assert len(binding)==167
        by_id={x['id']:x for x in binding};assert set(by_id)==set(selected)
        statuses=Counter();reasons=Counter()
        for original in data:
            task=original['id']
            if task not in by_id:continue
            b=by_id[task];text=original['input']['prompt'];top=meta[task]['resolved_top']
            assert not original['input']['context'] and len(original['output']['context'])==1
            assert b['source_top']==top and b['named_family']==meta[task]['named_family']
            assert b['original_output_path']==next(iter(original['output']['context']))
            assert b['original_prompt_sha256']==sha(text.encode()) and b['admitted'] is False
            try:
                converted=funcs.bind_prompt(text,top,'TopModule',names)
                assert funcs.bind_prompt(converted,'TopModule',top,names)==text
            except ValueError as error:
                assert b['status']=='abstain' and b['reason']==str(error)
                reasons[str(error)]+=1
            else:
                assert b['status']=='mechanically_reversible_needs_contract_review'
                assert b['converted_prompt']==converted and b['converted_prompt_sha256']==sha(converted.encode())
            statuses[b['status']]+=1
        assert dict(statuses)==report['status_counts'] and dict(reasons)==report['abstention_reasons']
        assert statuses['mechanically_reversible_needs_contract_review']==converted_count
        assert sha(z.read('results/PRIVATE_BINDING.json'))==report['private_binding_sha256']
        controls=read(z,'results/CONSTRUCTED_CONTROLS.json');assert controls==report['controls']
        tools=read(z,'inputs/TOOLCHAIN_MANIFEST.json')['prefix']
        for width in [1,8,17,64]:
            for sequential in [False,True]:
                old=f'Unit_{width}_{int(sequential)}';base='results/controls/'+old
                source=z.read(base+'/original/dut.sv').decode('utf-8')
                mapped=funcs.bind_source(source,old,'TopModule',names)
                assert mapped==z.read(base+'/canonical/dut.sv').decode('utf-8')
                assert funcs.bind_source(mapped,'TopModule',old,names)==source
                tb=z.read(base+'/original/tb.sv').decode('utf-8')
                assert tb.replace(old+' dut(','TopModule dut(',1)==z.read(base+'/canonical/tb.sv').decode('utf-8')
                a=commands(z,base+'/original',tools);b=commands(z,base+'/canonical',tools)
                assert a==b and 'CHECKS=5 PASS' in a
                expected=[0,1,(1<<width)-1,((1<<width)-1)>>1,1<<(width-1)]
                for v in expected:assert f"d={width}'h{v:x}" in tb and f"q !== {width}'h{v^((1<<width)-1):x}" in tb
        diagnostic='results/controls/initialization_diagnostic'
        assert z.read(diagnostic+'/dut.sv')==z.read('inputs/failed_original_dut.sv')
        log=commands(z,diagnostic,tools,expected_top='diag')
        assert 'NO_INPUT_EVENT q=x' in log and 'EXPLICIT_INPUT_EVENTS PASS' in log
        counter_verified=False
        if label=='S5':
            prior=z.read('inputs/prior_driver.py');assert sha(prior)==PINS['S4'][1]==plan['dependency_hashes']['prior-driver']
            old_funcs=pure_functions(prior,PINS['S4'][1])
            counter='results/controls/quoted_literal_counterexample';data=read(z,counter+'/input.json')
            assert old_funcs.bind_prompt(data['original'],'Leaf7','TopModule',names)==data['old_converted']
            assert old_funcs.bind_prompt(data['old_converted'],'TopModule','Leaf7',names)==data['original']
            try:funcs.bind_prompt(data['original'],'Leaf7','TopModule',names)
            except ValueError as error:assert str(error)=='module_phrase_inside_string_literal'
            else:raise AssertionError('Literal-rewrite counterexample was not refused')
            assert 'LITERAL_PRESERVED' in commands(z,counter+'/original',tools)
            assert 'LITERAL_CHANGED' in commands(z,counter+'/old_mapping',tools,simulation_rc=1)
            old_source=z.read(counter+'/old_mapping/dut.sv').decode()
            original=z.read(counter+'/original/dut.sv').decode()
            assert original.replace('"module Leaf7"','"module TopModule"')==old_source
            counter_verified=True
        count_paths=[n for n in z.namelist() if n.startswith('results/controls/') and n.endswith('/commands.json')]
        assert len(count_paths)==count==controls['actual_compile_commands']==controls['actual_sim_commands']
        guard=read(z,'guard/status.json');ticket=read(z,'FINAL_TICKET.json')
        assert all(guard[k] for k in ['complete','passed','model_unchanged','protected_files_unchanged','own_slot_released'])
        assert guard['owned_cleanup']['verified'] and not guard['owned_cleanup']['remaining']
        assert guard['stage_rc']==0 and ticket['state']=='completed' and not guard['model_managed'] and not guard['instance_managed']
        assert report['complete'] and report['passed'] and report['actual_model_requests']==report['dataset_eda_calls']==report['independent_tasks_admitted']==0
        assert not report['full_batch_complete']
        return dict(stage=label,archive_sha256=archive,manifest_files_verified=len(manifest),driver_sha256=driver_pin,
                    fixed_pure_mapping_functions_reapplied=True,original_records=302,structural_cohort=167,
                    status_counts=dict(statuses),abstention_reasons=dict(reasons),constructed_native_pairs_verified=8,
                    checks_each=5,actual_iverilog_compile_receipts_verified=count,actual_vvp_sim_receipts_verified=count,
                    quoted_literal_counterexample_verified=counter_verified,actual_dataset_eda=0,actual_model_requests=0,
                    independent_natural_tasks_admitted=0,adoption=False,
                    limits=['Icarus constructed controls, not Vivado official grading or natural dataset oracle calibration.',
                            'Fixed functions validate exact reversible transformation; reversibility alone does not establish semantics.',
                            'Natural references empty; preserved original harness/context, positive/negative calibration and exposure review still required.',
                            'No source/driver/toolchain from teammate was modified or executed as a full stage; no model/EDA call in this review.'])


if __name__=='__main__':
    output=dict(schema='team_cvdp_interface_readonly_review_v1',stages=[review('S4'),review('S5')],
                reviewer_sha256=sha(Path(__file__).read_bytes()),model_calls=0,eda_calls=0,adoption=False,
                independent_natural_tasks=0)
    (R/'RESULTS.json').write_text(json.dumps(output,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(output))
