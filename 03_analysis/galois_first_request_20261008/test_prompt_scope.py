"""Only new residual-behavior admission controls; reuse earlier semantic/pipeline evidence."""
import hashlib,json,sys
from pathlib import Path
import galois_prompt_contract as g
import galois_first_request as boundary
import prompt_scope
ROOT=Path(__file__).parent
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
read=lambda p:json.loads(Path(p).read_bytes())

def fixture(width,taps,seed,output='state'):
    positions=', '.join(map(str,taps[:-1]))+' and '+str(taps[-1]) if len(taps)>1 else str(taps[0])
    return f'''I would like you to implement a module named ToyScope with the following interface.
 - input clk
 - input reset
 - output {output} ({width} bits)
A Galois LFSR is one particular arrangement that shifts right, where a bit position with a "tap" is XORed with the LSB output bit ({output}[0]) to produce its next value, while bit positions without a tap shift right unchanged.
The module should implement a {width}-bit Galois LFSR with taps at bit positions {positions}.
Reset should be active high synchronous, and should reset the output {output} to {width}'h{seed:x}.
Assume all sequential logic is triggered on the positive edge of the clock.
'''

def raw(prompt):
    return json.dumps(dict(model='explicitly-simulated-scope',messages=[dict(role='system',content='unchanged synthetic system'),dict(role='user',content=prompt)],temperature=0.0,top_p=1.0,max_tokens=8192)).encode()

def main():
    assert sys.platform=='linux' and sys.dont_write_bytecode
    for n,h in read(ROOT/'SOURCE_MANIFEST.json').items():assert sha(ROOT/n)==h
    base=fixture(7,[7,6],65)
    extra='When reset is deasserted and state is 3, hold state at 3 instead of advancing.'
    counter=base+extra
    old=g.parse(counter);assert old['status']=='supported'
    # Exact teammate static counterexample, now observed at the admission boundary.
    implied=(3>>1)^sum(1<<(p-1) for p in old['taps']);assert implied==97 and implied!=3
    assert not prompt_scope.complete(counter,old)
    maximum=fixture(11,[11,9],131,'bits').replace('interface.','interface. All input and output ports are one bit unless otherwise specified.').replace('A Galois','A linear feedback shift register is a shift register usually with a few XOR gates to produce the next state of the shift register. A Galois')
    maximum=maximum.replace('shift right unchanged.','shift right unchanged. If the taps positions are carefully chosen, the LFSR can be made to be "maximum-length". A maximum-length LFSR of n bits cycles through 2**n-1 states before repeating (the all-zero state is never reached).').replace('a 11-bit Galois','an 11-bit maximal-length Galois').replace('Reset should be active high synchronous, and should reset the output bits to','The active-high synchronous reset should reset the LFSR output to')
    positives=[base,fixture(8,[8,5],19,'value'),maximum]
    for prompt in positives:
        assert prompt_scope.complete(prompt,g.parse(prompt))
        before=raw(prompt);after,receipt=boundary.transform(before,prompt,'','P',0)
        assert receipt['changed'] and after!=before;boundary.verify(before,after,prompt,'','P',0,receipt)
        control,_=boundary.transform(before,prompt,'','C',0);assert control==before
    negatives=[counter,extra+'\n'+base,base.replace('The module should',extra+' The module should'),base+'Except for the state 3, which remains constant.',base+'Invert state after every clock.',base+'The initial state is different from reset.',base+'Produce zero whenever state equals 3.',base.replace('positive edge of the clock.','positive edge of the clock. If state is 3 do not update.'),base+' state[1] must always be high.']
    for prompt in negatives:
        # The old fragment parser still supports these; only the new complete-consumption guard changes.
        assert g.parse(prompt)['status']=='supported'
        before=raw(prompt);after,receipt=boundary.transform(before,prompt,'','P',0)
        assert not receipt['changed'] and after==before and receipt['reason']=='unconsumed_prompt_behavior'
        boundary.verify(before,after,prompt,'','P',0,receipt)
    intake=Path('/workspace/team/runs/fpga_owner/galois_first_request_intake156_20261008_v1')
    assert sha(intake/'ACTUAL_TRANSPORT_RECEIPT.json')=='d815dd35b645351de92d620c9e3dbaa554de9b49002f591590bd1c51f94b4d53'
    prior=read(intake/'ACTUAL_INTAKE_RESULT.json');changed=[r for r in prior['rows'] if r['changed']];assert len(changed)==2
    oldroot=Path('/workspace/team/runs/fpga_teammate/serial_framing_synthesis_full156_20261007_v1');retained=[]
    for row in changed:
        work=oldroot/'results/samples/C'/row['task']/'worker';source=work/'prompt_only'
        assert sha(source/'prompt.txt')==row['prompt_sha256'] and sha(work/'requests/0/request.json')==row['original_request_json_sha256']
        prompt=(source/'prompt.txt').read_bytes().decode();interface=(source/'interface.txt').read_bytes().decode() if (source/'interface.txt').exists() else ''
        assert boundary.clarification(prompt,interface)[0]
        request=json.dumps(read(work/'requests/0/request.json')).encode();after,receipt=boundary.transform(request,prompt,interface,'P',0)
        assert receipt['changed'] and boundary.digest(after)==row['forwarded_wire_sha256'];boundary.verify(request,after,prompt,interface,'P',0,receipt)
        retained.append(dict(task=row['task'],forwarded_wire_sha256=row['forwarded_wire_sha256'],prior_conservative_capacity_reused=row['conservative_context_total']))
    result=dict(schema='galois_prompt_complete_scope_new_controls_v1',passed=True,teammate_comment=6051168108,exact_counterexample_reproduced_old_parser=True,old_implied_next_state=97,required_hold_state=3,new_scope_abstains=True,new_positive_scope_cases=3,new_extra_behavior_cases=9,previously_eligible_inputs_retained=2,retained=retained,remaining154_cannot_expand_by_AND_guard=True,previous_156_intake_not_reexecuted=True,old_4_19_664_semantic_and4_worker_controls_not_reexecuted=True,only_production_delta='AND full prompt consumption before existing clarification',shared_model_EDA_FIFO_calls=0,score_measured=False,qualified_for_full156=False,adoption=False)
    (ROOT/'ACTUAL_SCOPE_RESULT.json').write_bytes((json.dumps(result,indent=2)+'\n').encode());print(json.dumps(result))
if __name__=='__main__':main()
