"""R2: full R1 regression, new keyword/case boundaries and unchanged semantics checks."""
import argparse
import ast
from collections import Counter
import ctypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import time
import unittest


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def load(name, path):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module


def run(a):
    assert sys.platform=='linux' and ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)==0
    sys.dont_write_bytecode=True
    assert sha(a.candidate)=='a1ce1552754c7c72d9c33b0f596937959bc392d305c3e956c266c5a4b2188157'
    words_path=a.candidate.with_name('SV_KEYWORDS_V12_0.json')
    assert sha(words_path)=='e11e4e031407aececed40d0e170b1a58e8ab78b76f20d66778d2ad9f86b8ab85'
    assert sha(a.paired)=='78e9b3e144f2bd43ebab371e15ac3946017686db890a8e45891db7a386841e1c'
    paired=load('r2_supervisor',a.paired);paired.check_resource(a.resource_check,a.kit,first=True)
    old_source=a.r1/'results/sources/shift_contract.py';fixture_source=a.r1/'results/sources/test_shift.py'
    assert sha(old_source)=='de93b416bd436b7caacc529b4894761131c6fbd108cd11d07679c6b561f35863'
    assert sha(fixture_source)=='f72ce775d7e03cb7ba35e97e125177cd5f37818a1405d0ad859caad17d2f83ef'
    original=load('r2_original',old_source);candidate=load('r2_candidate',a.candidate)
    sys.modules['shift_contract']=candidate;fixture=load('r2_fixture',fixture_source)
    old_ast=ast.parse(old_source.read_text());new_ast=ast.parse(a.candidate.read_text())
    for name in ['render_tb','counterexample']:
        assert ast.dump(next(n for n in old_ast.body if isinstance(n,ast.FunctionDef) and n.name==name))==ast.dump(next(n for n in new_ast.body if isinstance(n,ast.FunctionDef) and n.name==name))
    a.out.mkdir(parents=True,exist_ok=False);tick=time.monotonic()
    small=('bit','byte','shortint','int','longint','time','real','event','enum','struct','union','always_comb','always_ff','always_latch')
    roles=('load','enable','amount','data','out');cases=[]
    for w in range(8,65):
        base=fixture.material(w)
        cases.extend([(f'w{w}_plain','regression',base,True),(f'w{w}_renamed','regression',fixture.material(w,'clock','capture','run','mode','payload','state'),True)])
        for role in roles:
            for word in small:cases.append((f'w{w}_{role}_{word}','regression',fixture.material(w,**{role:word}),False))
        for label,text in [('role_only',base.replace('(3) amount:','(3) AMOUNT:')),('selector_only',base.replace('"amount."','"AMOUNT."')),('both',base.replace('(3) amount:','(3) AMOUNT:').replace('"amount."','"AMOUNT."'))]:
            cases.append((f'w{w}_case_{label}','regression',text,False))
    old_manifest=json.loads((a.r1/'results/INPUT_MANIFEST.json').read_text())
    assert sha(a.r1/'results/INPUT_MANIFEST.json')=='4c67f6faf1148def93634cfba846a37cd3ef1e186d4b44489b9c921e54d3e83b'
    assert len(cases)==4275
    for (i,_,text,e),m in zip(cases,old_manifest):
        assert i==m['id'] and hashlib.sha256(text.encode()).hexdigest()==m['prompt_sha256'] and e==m['expect_supported']
    words=json.loads(words_path.read_text())['keywords'];assert len(words)==249
    for w in [8,64]:
        for role in roles:
            for word in words:
                for name,e in [(word,False),(word.upper(),True)]:
                    cases.append((f'new_w{w}_{role}_{name}','new_lexical_boundary',fixture.material(w,**{role:name}),e))
    for w in range(8,65):
        base=fixture.material(w,amount='modeX')
        for label,text in [('role',base.replace('(3) modeX:','(3) modex:')),('selector',base.replace('"modeX."','"MODEX."')),('both',base.replace('(3) modeX:','(3) modex:').replace('"modeX."','"MODEX."'))]:
            cases.append((f'new_w{w}_case_{label}','new_case_boundary',text,False))
    assert len(cases)==9426
    manifest=[dict(id=i,group=g,prompt_sha256=hashlib.sha256(p.encode()).hexdigest(),expect_supported=e) for i,g,p,e in cases]
    (a.out/'INPUT_MANIFEST.json').write_text(json.dumps(manifest,indent=2)+'\n')
    report=dict(complete=False,passed=False,model_calls=0,eda_calls=0,rows=[],compiler_controls=[],error=None,
                candidate_sha256=sha(a.candidate),keyword_sha256=sha(words_path),input_manifest_sha256=sha(a.out/'INPUT_MANIFEST.json'),
                independent_natural_tasks=0,full_batch_complete=False)
    counts=Counter()
    try:
        for i,g,p,e in cases:
            c=candidate.parse(p);actual=c['status']=='supported';counts[g+'/total']+=1
            if actual!=e:counts[g+'/mismatch']+=1
            if actual:
                prior=original.parse(p)
                if prior['status']=='supported':assert c==prior,'supported semantics changed'
            report['rows'].append(dict(id=i,group=g,expected_supported=e,actual_supported=actual))
        with (a.out/'legacy_tests.log').open('w') as log:
            tests=unittest.TextTestRunner(stream=log).run(unittest.defaultTestLoader.loadTestsFromModule(fixture))
        report['legacy_tests']=dict(run=tests.testsRun,passed=tests.wasSuccessful());assert tests.wasSuccessful()
        for w in range(8,65):
            c=candidate.parse(fixture.material(w));assert fixture.bit_state(c)==[o['expected'] for o in c['observations']]
        report['independent_bit_oracle_widths']=57
        os.environ['LD_LIBRARY_PATH']='/workspace/team/udev-stub'
        assert sha(Path(os.environ['LD_LIBRARY_PATH'])/'libudev.so.1')=='3a2d6266ccf18909d3ebccbf21e8125ce985359319fecc6c8172aeabf13ecf87'
        for index,(w,role,name) in enumerate([(8,'data','BIT'),(64,'data','ALWAYS_FF'),(8,'out','CASE'),(64,'amount','INT')]):
            assert time.monotonic()-tick<150;paired.check_resource(a.resource_check,a.kit)
            prompt=fixture.material(w,**{role:name});c=candidate.parse(prompt);assert c['status']=='supported'
            wd=a.out/'compile'/str(index);wd.mkdir(parents=True);(wd/'prompt.txt').write_text(prompt);(wd/'tb.sv').write_text(candidate.render_tb(c,'R2Witness'))
            receipt=paired.owned_command(['/workspace/AMD/2026.1/Vivado/bin/xvlog','--sv',str(wd/'tb.sv')],wd,wd/'compile.log',15)
            report['eda_calls']+=1;report['compiler_controls'].append(receipt)
            assert receipt['returncode']==0 and not receipt['timeout'] and not receipt['remaining_live_group'] and 'VRFC ' in (wd/'compile.log').read_text()
        assert not any(v for k,v in counts.items() if k.endswith('/mismatch'))
        paired.check_resource(a.resource_check,a.kit)
        report.update(complete=True,passed=True,counts=dict(counts),supported_semantics_unchanged=True,renderer_and_counterexample_ast_unchanged=True)
    except BaseException as exc:
        report['error']=type(exc).__name__+': '+str(exc);raise
    finally:
        report['elapsed_s']=time.monotonic()-tick
        (a.out/'summary.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps({k:v for k,v in report.items() if k not in ['rows','compiler_controls']}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ['candidate','r1','out','paired','resource-check','kit']:p.add_argument('--'+n,type=Path,required=True)
    run(p.parse_args())
