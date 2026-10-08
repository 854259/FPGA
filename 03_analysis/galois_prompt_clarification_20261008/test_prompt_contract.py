"""Independent toy interfaces and bit movement invariants; AMD-only execution."""
import hashlib,json
from pathlib import Path
import galois_prompt_contract as g

ROOT=Path(__file__).parent
def fixture(width,taps,seed,output='state',clock='clk',reset='reset'):
    positions=', '.join(map(str,taps[:-1]))+' and '+str(taps[-1]) if len(taps)>1 else str(taps[0])
    return f'''I would like you to implement a module named ToyLfsr with the following interface.
 - input {clock}
 - input {reset}
 - output {output} ({width} bits)
A Galois LFSR is one particular arrangement that shifts right, where a bit position with a "tap" is XORed with the LSB output bit ({output}[0]) to produce its next value, while bit positions without a tap shift right unchanged.
The module should implement a {width}-bit Galois LFSR with taps at bit positions {positions}.
Reset should be active high synchronous, and should reset the output {output} to {width}'h{seed:x}.
Assume all sequential logic is triggered on the positive edge of the clock.
'''

def main():
    positives=[(3,[3,2],1,'state','clk','reset'),(4,[4,1],3,'value','clock','rst'),(7,[7,6],65,'out','clk','rst'),(9,[9,5],257,'bits','clock','reset')]
    checks=0;rendered=[]
    for width,taps,seed,out,clk,rst in positives:
        c=g.parse(fixture(width,taps,seed,out,clk,rst));assert c['status']=='supported',c
        assert (c['width'],c['taps'],c['seed'],c['output'],c['clock'],c['reset'])==(width,taps,seed,out,clk,rst)
        # Independent per-destination movement, not the production parser's mask construction.
        for old in range(1<<width):
            vector=[(old>>i)&1 for i in range(width)];new=[]
            for destination in range(width):
                incoming=vector[destination+1] if destination+1<width else 0
                new.append(incoming ^ (vector[0] if destination+1 in taps else 0))
            independent=sum(bit<<i for i,bit in enumerate(new))
            compact=(old>>1)^(c['tap_mask'] if old&1 else 0)
            assert independent==compact;checks+=1
        text=g.clarify(c);assert 'old bit i+1' in text and 'destination' in text and 'not an XOR reduction' in text
        assert all(x not in text for x in ('module ','always @','assign ','Prob','tb.sv','ref.sv'));rendered.append(text)
    base=fixture(7,[7,6],65)
    invalid=[base.replace('shifts right','shifts left'),base.replace('Galois','Fibonacci'),base.replace('synchronous','asynchronous'),base.replace('active high','active low'),base.replace('positive edge','negative edge'),base.replace('(7 bits)','(8 bits)'),base.replace('positions 7 and 6','positions 7 and 7'),base.replace('positions 7 and 6','positions 7 and 0'),base.replace('positions 7 and 6','positions 7 and 8'),base.replace('positions 7 and 6','positions 6 and 2'),base.replace("7'h41","8'h41"),base.replace("7'h41","7'hff"),base.replace("7'h41","7'h0"),base.replace("to 7'h41.","as specified."),base.replace(' - input reset',' - input reset\n - input enable'),base.replace('with the following interface.','with the following diagram and interface.'),base.replace('(state[0])','(other[0])'),base.replace('shift right unchanged','remain unchanged'),base+' Enable should hold the register.']
    reasons=[]
    for prompt in invalid:
        c=g.parse(prompt);assert c['status']=='unsupported',c;assert g.clarify(c)=='';reasons.append(c['reason'])
    # A left-shift mutant differs from the independently derived right-shift mapping.
    for width,taps,seed,_,_,_ in positives:
        c=g.parse(fixture(width,taps,seed));right=(seed>>1)^(c['tap_mask'] if seed&1 else 0)
        wrong=((seed<<1)&((1<<width)-1))^(c['tap_mask'] if seed&1 else 0);assert right!=wrong
    result=dict(schema='generic_galois_prompt_clarification_toy_controls_v1',passed=True,positive_interfaces=len(positives),negative_interfaces=len(invalid),independent_state_transition_checks=checks,direction_mutants_rejected=4,model_calls=0,EDA_calls=0,FIFO_calls=0,real_benchmark_generation=False,score_measured=False,production_integration=False,source_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [ROOT/'galois_prompt_contract.py',Path(__file__)]},rejection_reasons=reasons)
    with (ROOT/'ACTUAL_RESULT.json').open('x',encoding='utf-8') as f:json.dump(result,f,indent=2);f.write('\n')
    print(json.dumps(result));return 0
if __name__=='__main__':raise SystemExit(main())
