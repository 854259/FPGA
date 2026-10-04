"""Per-bit software predictions and evaluation-only DUT controls, no agent answers."""
import json
from pathlib import Path
import edge_contract as parser
from test_edge import material,bit_pulse
R=Path(__file__).resolve().parent
NAMES=['positive','opposite_edge','combinational','extra_delay','wrong_direction','constant_zero']


def controls(c):
    w=c['width'];r=c['roles'];clk,signal,out=[r[k] for k in ['clock','input','output']]
    header=f'module TopModule(input {clk},input [{w-1}:0] {signal},output [{w-1}:0] {out});\n'
    expr=f'{signal} ^ _previous' if c['kind']=='any' else f'{signal} & ~_previous'
    base=f'reg [{w-1}:0] _previous,_pulse; assign {out}=_pulse;\n'
    correct=lambda edge:header+base+f'always @({edge} {clk}) begin _previous<={signal}; _pulse<={expr}; end endmodule\n'
    opposite=f'{signal} & ~_previous' if c['kind']=='any' else f'~{signal} & _previous'
    # Two past samples detect the previous transition; no runtime/source patch is supplied.
    delayed='_previous ^ _older' if c['kind']=='any' else '_previous & ~_older'
    return dict(positive=correct('posedge'),opposite_edge=correct('negedge'),
        combinational=header+f'reg [{w-1}:0] _previous; always @(posedge {clk}) _previous<={signal}; assign {out}={expr}; endmodule\n',
        extra_delay=header+base+f'reg [{w-1}:0] _older; always @(posedge {clk}) begin _older<=_previous; _previous<={signal}; _pulse<={delayed}; end endmodule\n',
        wrong_direction=header+base+f'always @(posedge {clk}) begin _previous<={signal}; _pulse<={opposite}; end endmodule\n',
        constant_zero=header+f"assign {out}={w}'d0; endmodule\n")


def prediction(c,name):
    # Independent integer-per-bit model; ignore undefined history only where the
    # contract also ignores it. The opposite edge executes during falling phase.
    result=[];w=c['width'];values=c['steps'];lookup={(o['step'],o['phase']):o for o in c['observations']}
    def pulse(a,b,wrong=False):
        kind=c['kind']
        if wrong:
            if c['kind']=='rising':a,b=b,a
            kind='rising'
        if a is None or b is None:
            # Preserve four-state unknowns; 0 AND unknown is known zero.
            return 0 if kind=='rising' and (b==0 or a==2**w-1) else None
        return bit_pulse(a,b,w,kind)
    state=previous=older=None
    if name=='opposite_edge':
        # TB initialization drives clk X -> 0 with data 0 before its first delay;
        # this is an initial negative edge. Its pulse remains unobserved.
        state=pulse(None,0);previous=0
    for i,value in enumerate(values):
        for phase in ['stable','positive','cycle']:
            if phase=='positive' and name!='opposite_edge':
                state=pulse(older,previous) if name=='extra_delay' else pulse(previous,value,name=='wrong_direction')
                older,previous=previous,value
            if phase=='cycle' and name=='opposite_edge':state=pulse(previous,value);previous=value
            row=lookup.get((i,phase))
            if row:
                actual=0 if name=='constant_zero' else pulse(previous,value) if name=='combinational' else state
                result.append(actual)
    assert len(result)==c['checks'];return result


def main():
    inputs=R/'raw_evidence/inputs'
    for task,width,kind in [('edge_any5',5,'any'),('edge_rising3',3,'rising')]:
        f=inputs/task;f.mkdir(exist_ok=True);(f/'prompt.txt').write_text(material(width,kind,'clock','data','seen'),encoding='utf-8',newline='\n')
    cases=[]
    for f in sorted(inputs.iterdir()):
        c=parser.parse((f/'prompt.txt').read_bytes().decode());assert c['status']=='supported',f.name
        expected=[o['expected'] for o in c['observations']]
        for o in c['observations']:
            a,b=(o['older_input'],o['previous_input']) if o['phase']=='stable' else (o['previous_input'],o['input'])
            assert bit_pulse(a,b,c['width'],c['kind'])==o['expected']
        counts={n:sum(a!=b for a,b in zip(prediction(c,n),expected)) for n in NAMES}
        assert counts['positive']==0
        assert (counts['opposite_edge']==0)==(c['clock_edge']=='unspecified_cycle')
        assert all(counts[n]>0 for n in NAMES[2:])
        (f/'contract.json').write_text(json.dumps(c,indent=2)+'\n',encoding='utf-8',newline='\n')
        (f/'tb.sv').write_text(parser.render_tb(c,f.name),encoding='utf-8',newline='\n')
        for n,code in controls(c).items():(f/(n+'.sv')).write_text(code,encoding='utf-8',newline='\n')
        cases.append(dict(task=f.name,checks=c['checks'],archived_candidate=(f/'candidate.sv').exists(),
                          group='known_public_development' if (f/'candidate.sv').exists() else 'constructed_calibration',
                          expected_control_mismatches=counts,
                          positive_names=['positive','opposite_edge'] if c['clock_edge']=='unspecified_cycle' else ['positive']))
    report=dict(cases=cases,model_calls=0,eda_calls=0,independent_natural_tasks=0,controls_only_not_agent_DUTs=True,
                oracle_per_bit_matches_expected=True,scope='Constructed and two known archived development contracts; native control validity pending')
    (R/'CONTROL_PREPARATION.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report))


if __name__=='__main__':main()
