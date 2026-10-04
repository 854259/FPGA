"""Independent bit-array controls; evaluation only, never agent DUT answers."""
import json
from pathlib import Path
import shift_contract as parser
from test_shift import material,bit_state

ROOT=Path(__file__).resolve().parent
NAMES=['positive','negative_edge_positive','logical_right','enable_priority','asynchronous_load','constant_zero']


def controls(c):
    r=c['roles'];w=c['width'];out=r['output'];clk=r['clock'];load=r['load'];ena=r['enable'];amount=r['amount'];data=r['data']
    header=f'module TopModule(input {clk},{load},{ena},input [1:0] {amount},input [{w-1}:0] {data},output [{w-1}:0] {out});\n'
    shift=f'case({amount}) 0: _state<=_state<<1; 1: _state<=_state<<8; 2: _state<=_state>>>1; 3: _state<=_state>>>8; endcase'
    def reg(edge='posedge',signed=True,enable_first=False,asynchronous=False):
        declarations=f'reg {"signed " if signed else ""}[{w-1}:0] _state; assign {out}=_state;\n'
        sensitivity=f'{edge} {clk}'+(f' or posedge {load}' if asynchronous else '')
        body=(f'if({ena}) begin {shift} end else if({load}) _state<={data};' if enable_first else
            f'if({load}) _state<={data}; else if({ena}) begin {shift} end')
        return header+declarations+f'always @({sensitivity}) begin {body} end endmodule\n'
    return dict(positive=reg(),negative_edge_positive=reg(edge='negedge'),logical_right=reg(signed=False),
        enable_priority=reg(enable_first=True),asynchronous_load=reg(asynchronous=True),constant_zero=header+f'assign {out}={w}\'d0; endmodule\n')


def control_observations(c,name):
    r=c['roles'];w=c['width'];bits=[0]*w;previous_load=0;results=[]
    def number():return sum(b*(2**i) for i,b in enumerate(bits))
    def load_bits(data):return [(data//(2**i))%2 for i in range(w)]
    def moved(amount):
        count=1 if amount in (0,2) else 8
        if amount<2:return [0]*count+bits[:-count]
        fill=0 if name=='logical_right' else bits[-1]
        return bits[count:]+[fill]*count
    for i,step in enumerate(c['steps']):
        d=step['inputs'];load,ena,amount,data=[d[r[k]] for k in ['load','enable','amount','data']]
        if name=='asynchronous_load' and load and not previous_load:bits=load_bits(data)
        if i:results.append(0 if name=='constant_zero' else number())
        if name=='enable_priority' and ena:bits=moved(amount)
        elif load:bits=load_bits(data)
        elif ena:bits=moved(amount)
        results.append(0 if name=='constant_zero' else number());previous_load=load
    return results


def main():
    inputs=ROOT/'raw_evidence/inputs'
    for name,width,roles in [('shift8',8,('clock','capture','run','mode','payload','state')),('shift16',16,('clk','load','ena','amount','data','q'))]:
        folder=inputs/name;folder.mkdir()
        (folder/'prompt.txt').write_text(material(width,*roles),encoding='utf-8',newline='\n')
    cases=[]
    for folder in sorted(inputs.iterdir()):
        c=parser.parse((folder/'prompt.txt').read_bytes().decode('utf-8'));assert c['status']=='supported'
        expected=[o['expected'] for o in c['observations']];assert bit_state(c)==expected
        counts={name:sum(a!=b for a,b in zip(control_observations(c,name),expected)) for name in NAMES}
        assert counts['positive']==counts['negative_edge_positive']==0 and all(counts[n]>0 for n in NAMES[2:])
        (folder/'contract.json').write_text(json.dumps(c,indent=2)+'\n',encoding='utf-8',newline='\n')
        (folder/'tb.sv').write_text(parser.render_tb(c,folder.name),encoding='utf-8',newline='\n')
        for name,code in controls(c).items():(folder/(name+'.sv')).write_text(code,encoding='utf-8',newline='\n')
        cases.append(dict(task=folder.name,checks=c['checks'],archived_candidate=(folder/'candidate.sv').exists(),
            group='known_public_development' if (folder/'candidate.sv').exists() else 'constructed_calibration',expected_control_mismatches=counts))
    (ROOT/'CONTROL_PREPARATION.json').write_text(json.dumps(dict(cases=cases,controls_only_not_agent_DUTs=True,
        independent_bit_state_matches_all_expected_rows=True,model_calls=0,eda_calls=0),indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(dict(cases=len(cases),checks_per_case=[c['checks'] for c in cases],controls=[c['expected_control_mismatches'] for c in cases])))


if __name__=='__main__':main()
