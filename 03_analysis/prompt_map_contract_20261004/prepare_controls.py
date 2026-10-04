"""Evaluation-only controls; never used as agent output or model input."""
import hashlib
import json
from pathlib import Path
import prompt_map
from test_prompt_map import prompt

ROOT=Path(__file__).resolve().parent


def controls(contract):
    names=contract['inputs'];out=contract['output']
    header='module TopModule('+','.join('input '+n for n in names)+',output '+out+');\n'
    terms=[]
    for case in contract['cases']:
        if case['expected']==1:
            terms.append('('+' & '.join(n if case['inputs'][n] else '~'+n for n in names)+')')
    positive=header+'assign '+out+' = '+' | '.join(terms)+';\nendmodule\n'
    return dict(positive=positive,constant_zero=header+"assign "+out+"=1'b0;endmodule\n",
        constant_one=header+"assign "+out+"=1'b1;endmodule\n",
        inverted=header+'assign '+out+' = ~('+' | '.join(terms)+');\nendmodule\n')


def main():
    folder=ROOT/'raw_evidence/inputs'
    synthetic=[
        ('mapped_xor2','xy','x','y',['1','0'],['1','0'],lambda b:b['x']^b['y'],()),
        ('mapped_parity3','uvw','uv','w',['10','11','00','01'],['1','0'],lambda b:b['u']^b['v']^b['w'],()),
        ('mapped_pairs4','pqrs','pr','sq',['11','00','10','01'],['01','10','00','11'],lambda b:(b['p']&b['q'])|(b['r']&b['s']),()),
        ('mapped_care4','jkln','nk','lj',['01','11','10','00'],['11','00','01','10'],lambda b:b['j']^(b['k']&b['l'])^b['n'],((0,0,0,0),(1,1,1,1))),
    ]
    independent={}
    for case,names,cols,rows,co,ro,fn,dc in synthetic:
        d=folder/case;d.mkdir(exist_ok=False)
        text=prompt(names,cols,rows,co,ro,fn,dc)
        contract=prompt_map.parse(text);assert contract['status']=='supported'
        for c in contract['cases']:
            expected=None if tuple(c['inputs'][n] for n in names) in dc else fn(c['inputs'])
            assert c['expected']==expected
        (d/'prompt.txt').write_text(text,encoding='utf-8',newline='\n')
        independent[case]=dict(expected_checked_against_separate_python_function=True,
            scope='constructed parser/EDA controls, not unseen task validation')
    cases=[]
    for d in sorted(folder.iterdir()):
        contract=prompt_map.parse((d/'prompt.txt').read_bytes().decode('utf-8'));assert contract['status']=='supported'
        (d/'contract.json').write_text(json.dumps(contract,indent=2)+'\n',encoding='utf-8',newline='\n')
        (d/'tb.sv').write_text(prompt_map.render_tb(contract,d.name),encoding='utf-8',newline='\n')
        for name,code in controls(contract).items():(d/(name+'.sv')).write_text(code,encoding='utf-8',newline='\n')
        cases.append(dict(task=d.name,checks=contract['checks'],archived_candidate=(d/'candidate.sv').exists(),
            group='known_public_development' if (d/'candidate.sv').exists() else 'constructed_calibration',
            files={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in sorted(d.iterdir()) if f.is_file()}))
    (ROOT/'CONTROL_PREPARATION.json').write_text(json.dumps(dict(cases=cases,synthetic_independent_function_checks=independent,
        controls_only_not_agent_designs=True,model_calls=0,eda_calls=0),indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'cases':len(cases),'actual_model_or_eda_calls':0}))


if __name__=='__main__':main()
