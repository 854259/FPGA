"""Evaluator-only name binding controls. No dataset DUT is generated or executed."""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import sys
import time


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def save(p,x):Path(p).write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def word(name):return r'(?<![A-Za-z0-9_$])'+re.escape(name)+r'(?![A-Za-z0-9_$])'


def valid_name(name,keywords):
    return bool(re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*',name)) and name not in keywords


def bind_prompt(text,old,new,keywords):
    """Only explicit module-name slots; all other occurrences cause abstention."""
    if not all(valid_name(n,keywords) for n in [old,new]) or old==new:
        raise ValueError('unsupported_identifier')
    if re.search(word(new),text):raise ValueError('destination_already_in_public_input')
    occurrences=[m.span() for m in re.finditer(word(old),text)]
    if not occurrences:raise ValueError('original_name_absent')
    # Match identifier case exactly; only English slot labels ignore case.
    pattern=(r'(?i:\bmodule(?:\s+named|\s+name\s*:)?\s+)'
             r'(?P<quote>[`"]?)(?P<name>'+re.escape(old)+r')(?P=quote)'
             r'(?![A-Za-z0-9_$]|\.s?v\b)')
    slots=sorted(set(m.span('name') for m in re.finditer(pattern,text)))
    if slots!=occurrences:raise ValueError('name_occurrence_outside_explicit_module_slot')
    quoted=list(re.finditer(r'"(?:\\.|[^"\\])*"',text))
    masked=re.sub(r'"(?:\\.|[^"\\])*"',lambda m:' '*len(m.group()),text)
    if '"' in masked:raise ValueError('unbalanced_double_quote')
    for lo,hi in slots:
        for literal in quoted:
            if literal.start()<lo and hi<literal.end() and literal.group()!='"'+old+'"':
                raise ValueError('module_phrase_inside_string_literal')
    result=text
    for lo,hi in reversed(slots):result=result[:lo]+new+result[hi:]
    return result


def bind_source(source,old,new,keywords):
    """Rename one top declaration, keeping ports, bodies, strings and comments exact.

    Recursive/hierarchical references, macros, escaped identifiers and collisions
    are unsupported; never rewrite them speculatively.
    """
    if not all(valid_name(n,keywords) for n in [old,new]) or old==new:
        raise ValueError('unsupported_identifier')
    masked=re.sub(r'"(?:\\.|[^"\\])*"|//[^\n]*|/\*[\s\S]*?\*/',
                  lambda m:' '*len(m.group()),source)
    if any(x in masked for x in ['"','/*','\\','`']):raise ValueError('unsupported_lexical_construct')
    if re.search(word(new),masked):raise ValueError('destination_identifier_collision')
    tokens=list(re.finditer(r'[A-Za-z_][A-Za-z0-9_$]*',masked))
    originals=[m for m in tokens if m.group()==old]
    declarations=[tokens[i+1] for i,m in enumerate(tokens[:-1])
                  if m.group()=='module' and tokens[i+1].group()==old]
    if len(originals)!=1 or len(declarations)!=1 or originals[0].span()!=declarations[0].span():
        raise ValueError('top_not_single_unreferenced_declaration')
    lo,hi=originals[0].span()
    return source[:lo]+new+source[hi:]


def controls(out,tools,keywords,diagnostic_source,previous):
    positives=0;negatives=0;native=[]
    templates=['Implement module NAME with the stated ports.',
               'Implement a module named `NAME` with the stated ports.',
               'Module name: "NAME"\nPreserve every port and width.',
               'module NAME(input [7:0] d, output [7:0] q); endmodule\n']
    for old in ['Unit7','mixed_Case9','_control_2']:
        for template in templates:
            text=template.replace('NAME',old)+'\nThe identifier '+old+'_suffix is distinct.'
            converted=bind_prompt(text,old,'TopModule',keywords)
            assert bind_prompt(converted,'TopModule',old,keywords)==text
            assert old+'_suffix' in converted
            positives+=1
    rejects=[('module alpha. TopModule is another name.','alpha'),
             ('Use alpha.','alpha'),('module Alpha.','alpha'),
             ('module alpha. Output alpha must be zero.','alpha'),
             ('module alpha. Literal "alpha" is required.','alpha'),
             ('module alpha.sv is a file.','alpha'),('module alpha2.','alpha'),
             ('module \\alpha .','alpha'),('module endmodule.','endmodule'),
             ('module alpha-beta.','alpha-beta'),('module alpha$1.','alpha$1'),
             ('module alpha. File alpha.v is required.','alpha'),
             ('module alpha. Emit the string "module alpha".','alpha'),
             ('module alpha. Emit "module named alpha".','alpha'),
             ('module alpha. Emit "Module name: alpha".','alpha'),
             ('module alpha. Emit "module alpha','alpha')]
    for text,old in rejects:
        try:bind_prompt(text,old,'TopModule',keywords)
        except ValueError:negatives+=1
        else:raise AssertionError('Prompt guard accepted unsupported control')
    source_rejects=['module TopModule; TopModule child(); endmodule',
        'module TopModule; endmodule module TopModule; endmodule',
        'module TopModule(input Unit7); endmodule','module Unit7; endmodule',
        '`define N TopModule\nmodule TopModule; endmodule',
        'module \\TopModule ; endmodule','module TopModule; /* unclosed',
        'module TopModule; initial $display("unclosed); endmodule']
    for text in source_rejects:
        try:bind_source(text,'TopModule','Unit7',keywords)
        except ValueError:negatives+=1
        else:raise AssertionError('Source guard accepted unsupported control')
    # Reproduce the preserved S3 DUT's zero-time no-input-event, then trigger it.
    diagnostic=out/'initialization_diagnostic';diagnostic.mkdir()
    (diagnostic/'dut.sv').write_bytes(diagnostic_source.read_bytes())
    (diagnostic/'tb.sv').write_text('''module diag;
reg clk=0,d=0; wire q; Unit_1_0 dut(.clk(clk),.d(d),.q(q));
initial begin
#1; if(q !== 1'bx) $fatal(1,"Expected original no-event unknown");
$display("NO_INPUT_EVENT q=%b",q);
d=1; #1; if(q !== 1'b0) $fatal(1,"Changed input failed");
d=0; #1; if(q !== 1'b1) $fatal(1,"First vector after event failed");
$display("EXPLICIT_INPUT_EVENTS PASS"); $finish; end endmodule
''')
    diagnostic_commands=[]
    for i,argv in enumerate([[str(tools/'bin/iverilog'),'-g2012','-s','diag','-o','simulation.vvp','dut.sv','tb.sv'],
                             [str(tools/'bin/vvp'),'simulation.vvp']]):
        r=subprocess.run(argv,cwd=diagnostic,capture_output=True,text=True,timeout=15)
        (diagnostic/f'command_{i}.log').write_text(r.stdout+r.stderr)
        diagnostic_commands.append(dict(argv=argv,rc=r.returncode,log_sha256=sha(diagnostic/f'command_{i}.log')))
        save(diagnostic/'commands.json',diagnostic_commands)
        assert r.returncode==0,'Initialization hypothesis not reproduced'
    assert 'NO_INPUT_EVENT q=x' in r.stdout and 'EXPLICIT_INPUT_EVENTS PASS' in r.stdout
    # A frozen counterexample: lexical roundtrip alone can change a constant.
    counter=out/'quoted_literal_counterexample';counter.mkdir()
    text='Implement module Leaf7 with output [127:0] tag. The output must equal the string "module Leaf7".'
    converted=previous.bind_prompt(text,'Leaf7','TopModule',keywords)
    assert '"module TopModule"' in converted
    assert previous.bind_prompt(converted,'TopModule','Leaf7',keywords)==text
    try:bind_prompt(text,'Leaf7','TopModule',keywords)
    except ValueError as error:assert str(error)=='module_phrase_inside_string_literal'
    else:raise AssertionError('New rule must abstain from semantic literal rewrite')
    original='module Leaf7(output [127:0] tag); assign tag="module Leaf7"; endmodule\n'
    canonical='module TopModule(output [127:0] tag); assign tag="module TopModule"; endmodule\n'
    restored=bind_source(canonical,'TopModule','Leaf7',keywords)
    save(counter/'input.json',dict(original=text,old_converted=converted,new_status='abstain'))
    for label,source,expected_rc in [('original',original,0),('old_mapping',restored,1)]:
        run=counter/label;run.mkdir();(run/'dut.sv').write_text(source)
        (run/'tb.sv').write_text('module tb; wire [127:0] tag; Leaf7 dut(.tag(tag)); initial begin #1; if(tag !== "module Leaf7") $fatal(1,"LITERAL_CHANGED"); $display("LITERAL_PRESERVED"); $finish; end endmodule\n')
        records=[]
        for i,argv in enumerate([[str(tools/'bin/iverilog'),'-g2012','-s','tb','-o','simulation.vvp','dut.sv','tb.sv'],
                                 [str(tools/'bin/vvp'),'simulation.vvp']]):
            r=subprocess.run(argv,cwd=run,capture_output=True,text=True,timeout=15)
            (run/f'command_{i}.log').write_text(r.stdout+r.stderr)
            records.append(dict(argv=argv,rc=r.returncode,log_sha256=sha(run/f'command_{i}.log')))
            save(run/'commands.json',records)
            assert r.returncode==(0 if i==0 else expected_rc)
        assert ('LITERAL_PRESERVED' if expected_rc==0 else 'LITERAL_CHANGED') in r.stdout
    for width in [1,8,17,64]:
        mask=(1<<width)-1
        for sequential in [False,True]:
            old=f'Unit_{width}_{int(sequential)}'
            folder=out/old;folder.mkdir()
            body=('always @(posedge clk) q <= d ^ '+str(width)+"'h"+format(mask,'x')+';' if sequential else
                  'always @* q = d ^ '+str(width)+"'h"+format(mask,'x')+';')
            original=(f'// {old} and TopModule in comments must stay exact\n'
                f'module {old}(input clk,input [{width-1}:0] d,output reg [{width-1}:0] q);\n'
                f'initial $display("literal {old} TopModule");\n{body}\nendmodule\n')
            changed=bind_source(original,old,'TopModule',keywords)
            assert bind_source(changed,'TopModule',old,keywords)==original
            logs=[]
            values=[0,1,mask,mask>>1,1<<(width-1)]
            for label,top,source in [('original',old,original),('canonical','TopModule',changed)]:
                run=folder/label;run.mkdir();(run/'dut.sv').write_text(source)
                tb=[f'module tb; reg clk=0; reg [{width-1}:0] d; wire [{width-1}:0] q;',
                    f'{top} dut(.clk(clk),.d(d),.q(q)); initial begin #1;']
                for val in values:
                    tb.append(f"clk=0; d={width}'h{val:x}; #1; clk=1; #1; if(q !== {width}'h{val^mask:x}) $fatal(1,\"VALUE\"); clk=0; #1;")
                tb+=['$display("CHECKS=5 PASS"); $finish; end endmodule\n']
                (run/'tb.sv').write_text('\n'.join(tb))
                commands=[[str(tools/'bin/iverilog'),'-g2012','-s','tb','-o','simulation.vvp','dut.sv','tb.sv'],
                          [str(tools/'bin/vvp'),'simulation.vvp']]
                records=[]
                for index,argv in enumerate(commands):
                    tick=time.monotonic()
                    r=subprocess.run(argv,cwd=run,capture_output=True,text=True,timeout=15)
                    (run/f'command_{index}.log').write_text(r.stdout+r.stderr)
                    records.append(dict(argv=argv,rc=r.returncode,elapsed_s=time.monotonic()-tick,
                        log_sha256=sha(run/f'command_{index}.log')))
                    save(run/'commands.json',records)
                    assert r.returncode==0,(width,sequential,label,index)
                assert 'CHECKS=5 PASS' in r.stdout
                logs.append(r.stdout)
            assert logs[0]==logs[1],'Port behavior or preserved string differs'
            native.append(dict(width=width,sequential=sequential,passed=True,checks_per_mode=5))
    return dict(prompt_roundtrip_controls=positives,rejection_controls=negatives,
                native_pairs=native,initialization_diagnostic_passed=True,
                old_quoted_literal_counterexample_confirmed=True,
                actual_compile_commands=19,actual_sim_commands=19)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ['data','inventory','toolchain-manifest','keywords','paired','kit','resource-check','out','diagnostic-source','prior-driver']:
        p.add_argument('--'+name,required=True,type=Path)
    a=p.parse_args();assert sys.platform=='linux'
    pins={a.data:'cbcd81295561ebb16e4d857e096f4d9908d042c33aff3b58abf236e868411857',
        a.inventory:'6676ea45ecce71a158379a56b74c1b731437c17a2e86f0694fe7c7aa27b55a1b',
        a.toolchain_manifest:'b0864aea493587c3fef1ff156b4fa49d52bd2ee712e9f28f94909d9e69252818',
        a.keywords:'3546fb60545966885a050b74590fd5ce4645ee8f37671e3f1768088c0d98756e',
        a.paired:'78e9b3e144f2bd43ebab371e15ac3946017686db890a8e45891db7a386841e1c',
        a.diagnostic_source:'44fc85bcdbacae77ca2b90eccb986d9aaf1ae55cad798437d01112d2d2e02a68',
        a.prior_driver:'22658a7ca54687254e021cd767303142dd1c0db0038530df9619522f047eb3a0'}
    for path,digest in pins.items():assert sha(path)==digest,path.name
    sp=importlib.util.spec_from_file_location('name_resource',a.paired)
    resource=importlib.util.module_from_spec(sp);sp.loader.exec_module(resource)
    resource.check_resource(a.resource_check,a.kit,first=True)
    sp=importlib.util.spec_from_file_location('name_keywords',a.keywords)
    names=importlib.util.module_from_spec(sp);sp.loader.exec_module(names)
    sp=importlib.util.spec_from_file_location('previous_name_controls',a.prior_driver)
    previous=importlib.util.module_from_spec(sp);sp.loader.exec_module(previous)
    toolmanifest=json.loads(a.toolchain_manifest.read_text());tools=Path(toolmanifest['prefix'])
    for path,digest in toolmanifest['files'].items():assert sha(tools/path)==digest
    a.out.mkdir(exist_ok=False);(a.out/'controls').mkdir()
    tick=time.monotonic()
    report=dict(complete=False,passed=False,actual_model_requests=0,independent_tasks_admitted=0,
                full_batch_complete=False,dataset_eda_calls=0,source_sha256=pins[a.data])
    try:
        report['controls']=controls(a.out/'controls',tools,names.KEYWORDS,a.diagnostic_source,previous)
        save(a.out/'CONSTRUCTED_CONTROLS.json',report['controls'])
        # Only after constructed rules pass: apply once to all predeclared eligible rows.
        records=[json.loads(line) for line in a.data.read_text().splitlines()]
        inventory=json.loads(a.inventory.read_text())['rows']
        metadata={r['id']:r for r in inventory}
        assert len(records)==len(metadata)==302
        selected=[r['id'] for r in inventory if r['no_input_single_output'] and r['static_entrypoint_resolved']]
        assert len(selected)==167
        save(a.out/'COHORT.json',dict(ids=selected,selection='Existing no-input/single-output and statically resolved entrypoint; no score filter'))
        outputs=[]
        for row in records:
            meta=metadata[row['id']]
            if row['id'] not in selected:continue
            assert not row['input']['context'] and len(row['output']['context'])==1
            text=row['input']['prompt'];old=meta['resolved_top']
            item=dict(id=row['id'],named_family=meta['named_family'],source_top=old,
                original_prompt_sha256=hashlib.sha256(text.encode()).hexdigest(),
                original_output_path=next(iter(row['output']['context'])),admitted=False,
                exposure='Evaluator-only public-interface audit; no model/solver rule tuning; independence still unresolved')
            try:
                converted=bind_prompt(text,old,'TopModule',names.KEYWORDS)
                assert bind_prompt(converted,'TopModule',old,names.KEYWORDS)==text
                item.update(status='mechanically_reversible_needs_contract_review',converted_prompt=converted,
                    converted_prompt_sha256=hashlib.sha256(converted.encode()).hexdigest())
            except ValueError as error:item.update(status='abstain',reason=str(error))
            outputs.append(item)
        assert len(outputs)==167
        save(a.out/'PRIVATE_BINDING.json',dict(rows=outputs))
        report.update(total_source_records=302,structural_records=167,
            status_counts=dict(Counter(r['status'] for r in outputs)),
            abstention_reasons=dict(Counter(r.get('reason') for r in outputs if r['status']=='abstain')),
            private_binding_sha256=sha(a.out/'PRIVATE_BINDING.json'),
            limitations=['Reversibility is not semantic/oracle validity or source independence',
                'Rule frozen before corpus application; no exclusions by model score',
                'All published references empty; natural positive/negative oracle controls remain unresolved',
                'Do not use converted prompts for model evaluation before contract and exposure admission'])
        resource.check_resource(a.resource_check,a.kit)
        report.update(complete=True,passed=True)
    except BaseException as error:
        report['error']=type(error).__name__+': '+str(error);raise
    finally:
        report['elapsed_s']=time.monotonic()-tick;save(a.out/'PUBLIC_RESULT.json',report)
