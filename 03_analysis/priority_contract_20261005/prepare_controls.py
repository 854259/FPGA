"""Evaluation controls only; no use as agent output or model answers."""
import json
from pathlib import Path
import priority_contract as parser
from test_priority import material

ROOT=Path(__file__).resolve().parent


def controls(contract):
    signal=contract['input'];out=contract['output'];width=contract['input_width'];ow=contract['output_width']
    header=f'module TopModule(input [{width-1}:0] {signal},output reg [{ow-1}:0] {out});\n'
    positive=header+f'integer bit_index; always @* begin {out}=0; for(bit_index={width-1};bit_index>=0;bit_index=bit_index-1) if({signal}[bit_index]) {out}=bit_index; end endmodule\n'
    msb=header+f'integer bit_index; always @* begin {out}=0; for(bit_index=0;bit_index<{width};bit_index=bit_index+1) if({signal}[bit_index]) {out}=bit_index; end endmodule\n'
    return dict(positive=positive,constant_zero=header.replace('output reg','output wire')+f'assign {out}={ow}\'d0; endmodule\n',
        constant_max=header.replace('output reg','output wire')+f'assign {out}={ow}\'d{width-1}; endmodule\n',msb_priority=msb)


def main():
    inputs=ROOT/'raw_evidence/inputs'
    for name,width,signal,out,illustrated in [('priority3',3,'vector','position',False),('priority5',5,'bits','index',True),('priority6',6,'data','result',False)]:
        folder=inputs/name;folder.mkdir()
        (folder/'prompt.txt').write_text(material(width,signal,out,illustrated),encoding='utf-8',newline='\n')
    cases=[]
    for folder in sorted(inputs.iterdir()):
        c=parser.parse((folder/'prompt.txt').read_bytes().decode('utf-8'));assert c['status']=='supported'
        (folder/'contract.json').write_text(json.dumps(c,indent=2)+'\n',encoding='utf-8',newline='\n')
        (folder/'tb.sv').write_text(parser.render_tb(c,folder.name),encoding='utf-8',newline='\n')
        for name,code in controls(c).items():(folder/(name+'.sv')).write_text(code,encoding='utf-8',newline='\n')
        # Independent repeated scan expectation, including the unused output codes.
        for row in c['cases']:
            value=row['inputs'][c['input']];positions=[i for i in range(c['input_width']) if (value>>i)&1]
            assert row['expected']==(positions[0] if positions else 0)
        cases.append(dict(task=folder.name,checks=c['checks'],archived_candidate=(folder/'candidate.sv').exists(),
            group='known_public_development' if (folder/'candidate.sv').exists() else 'constructed_calibration'))
    (ROOT/'CONTROL_PREPARATION.json').write_text(json.dumps(dict(cases=cases,controls_only_not_agent_DUTs=True,
        independent_bit_scan_matches_all_expected_rows=True,model_calls=0,eda_calls=0),indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(dict(cases=len(cases),expected_rows=sum(c['checks'] for c in cases),model_calls=0,eda_calls=0)))


if __name__=='__main__':main()
