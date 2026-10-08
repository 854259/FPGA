"""New scope-B stitching controls only; all generation metadata is simulated.

No worker, HTTP, native compiler, FIFO, old test suite, intake or full audit runs.
Positive model records deliberately stop at an unconfirmed attempt; this proves
the changed provenance seam, never real native execution or score admission.
"""
import hashlib,json,re,shutil
from pathlib import Path
from types import SimpleNamespace
import worker, request_proof, waveform_replay
import generation_binding as proof

ROOT=Path(__file__).resolve().parent
composition=worker.synthesis;common=worker.baseline
providers=[('table',composition.table_synthesis),('onehot',composition.onehot_producer),('timer',composition.timer_producer)]
modules=dict(composition=composition,providers=providers,selector=composition.selector,
    table_contract=composition.table_synthesis.contract,worker=worker,
    waveform_worker=worker.waveform_worker,waveform_request=worker.waveform_worker.waveform_request,
    waveform_facts=worker.waveform_worker.waveform_request.waveform_facts,
    request_proof=request_proof,replay=waveform_replay,baseline_worker=common,
    baseline=common.load('new_wave_proof_extract',ROOT/'package/baseline.py'),
    runtime=common.load('new_wave_proof_runtime',ROOT/'package/agent/map_runtime.py'),
    parser=common.edge_dispatch,feedback=common.phase_feedback,
    runner=common.load('new_wave_proof_runner',ROOT/'dependencies/probe_runner.py'))
generation=(ROOT/'package/skill/rtl-generation/SKILL.md').read_text()
repair=(ROOT/'package/skill/rtl-feedback-repair/SKILL.md').read_text()
spec=dict(model='Qwen3.6-27B-Q4_K_M')
positives=[];negatives=[]
save=lambda p,j:Path(p).write_text(json.dumps(j,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
digest=lambda b:hashlib.sha256(b).hexdigest()

def rejects(label,call):
    try:call()
    except (AssertionError,KeyError,ValueError,FileNotFoundError):negatives.append(label);return
    raise AssertionError('Malformed new wave stitching record accepted: '+label)

def route_metadata(work,source,arm,prompt,interface):
    source.mkdir(parents=True);work.mkdir(parents=True);(work/'prompt_only').mkdir()
    for root in (source,work/'prompt_only'):
        (root/'prompt.txt').write_bytes(prompt.encode());(root/'interface.txt').write_bytes(interface.encode())
    receipt=composition.synthesize(prompt,interface)
    route=dict(schema='table_history_wave_generation_route_v1',route='mechanical_'+receipt['selected_provider'] if receipt['emitted'] else 'model',outer_arm=arm,prompt_sha256=proof.digest(prompt),interface_sha256=proof.digest(interface),interface_present=True,baseline_worker_sha256=proof.sha(ROOT/'baseline_worker.py'),synthesis_source_sha256=proof.sha(ROOT/'composition.py'),generated_solution_sha256=receipt['rtl_sha256'] if receipt['emitted'] else None)
    save(work/'synthesis_receipt.json',receipt);save(work/'generation_route.json',route)
    return route,receipt

def model_metadata(label,arm,prompt,interface,repair_round=False):
    base=ROOT/'FAKE_NEW_WAVE_PROOF_METADATA'/label;work=base/'worker';source=base/'input'
    route,recipe=route_metadata(work,source,arm,prompt,interface);assert not recipe['emitted']
    combined=request_proof.combined(prompt,interface);journal=[]
    trace=[dict(tool='agent_meta',repairs=1,skill_sha256=digest(generation.encode()),repair_skill_sha256=digest(repair.encode()))]
    count=2 if repair_round else 1
    for i in range(count):
        # Original baseline extract('', 'rtl') preserves its mandatory final newline.
        previous_candidate='\n'
        user=combined if i==0 else combined+'\nPrevious candidate:\n'+previous_candidate+'\nCandidate diagnostics:\nReturn a complete TopModule ending in endmodule.'
        body=dict(model=spec['model'],messages=[dict(role='system',content=generation+('\n'+repair if i else '')),dict(role='user',content=user)],temperature=0.0,top_p=1.0,max_tokens=8192)
        raw=json.dumps(body).encode()
        forwarded,receipt=modules['waveform_request'].transform(raw,prompt,interface,arm,i)
        evidence=work/'waveform_request_receipts'/str(i);evidence.mkdir(parents=True)
        (evidence/'original_wire.bin').write_bytes(raw);(evidence/'forwarded_wire.bin').write_bytes(forwarded);save(evidence/'receipt.json',receipt)
        req=work/'requests'/str(i);req.mkdir(parents=True);save(req/'request.json',json.loads(forwarded))
        entry=dict(index=i,replayed=False,response_received=repair_round and i==0,request_sha256=proof.sha(req/'request.json'))
        trace.append(dict(tool='llm_start',round=i))
        if entry['response_received']:
            payload=dict(id='SIMULATED_NEW_WAVE_PROOF_METADATA',choices=[dict(finish_reason='stop',message=dict(content=''))],usage=dict(prompt_tokens=0,completion_tokens=0))
            save(req/'response.json',payload);entry.update(response_sha256=proof.sha(req/'response.json'),finish_reason='stop',response_id=payload['id'],usage=payload['usage'])
            trace.append(dict(tool='llm',round=i,finish='stop',tokens_in=0,tokens_out=0))
        journal.append(entry)
    save(work/'requests.json',journal)
    (work/'trace.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in trace),encoding='utf-8')
    (work/'solution.v').write_bytes(b'')
    row=dict(task='SIMULATED_NEW_WAVE_BOUNDARY',arm=arm,generation_route='model',selected_provider=None,actual_model_requests=count,received_model_responses=int(repair_round),solve_deadline_reached=True)
    return work,source,row

def verify_model(case):
    work,source,row=case
    return proof.verify(work,ROOT,source,row['arm'],row,work,spec,modules,lambda *a:(_ for _ in ()).throw(AssertionError('No probe expected in simulated missing-code metadata')))

def clone_case(case,label):
    work,source,row=case;dest=ROOT/'FAKE_NEW_WAVE_MUTANTS'/label;shutil.copytree(work,dest)
    return dest,source,dict(row)

def forged_forwarded(case,index,suffix):
    work,source,row=case;folder=work/'waveform_request_receipts'/str(index)
    body=json.loads((folder/'forwarded_wire.bin').read_bytes());body['messages'][1]['content']+=suffix
    wire=json.dumps(body).encode();(folder/'forwarded_wire.bin').write_bytes(wire)
    save(work/'requests'/str(index)/'request.json',body)
    journal=proof.read(work/'requests.json');journal[index]['request_sha256']=proof.sha(work/'requests'/str(index)/'request.json');save(work/'requests.json',journal)
    receipt=proof.read(folder/'receipt.json');receipt.update(forwarded_wire_sha256=digest(wire),forwarded_wire_bytes=len(wire))
    if index==0:receipt['advice']+=suffix;receipt['advice_sha256']=digest(receipt['advice'].encode())
    save(folder/'receipt.json',receipt)

def main():
    proof.bound_modules(ROOT,modules)
    fixtures=proof.read(ROOT/'NEW_WAVE_PROOF_INPUTS_PRIVATE.json')
    mechan={}
    for f in fixtures['mechanical']:
        pair=[]
        for arm in ('C','P'):
            root=ROOT/'FAKE_NEW_WAVE_PROOF_METADATA'/(f['label']+'_'+arm)
            work=root/'worker';src=root/'input';route,receipt=route_metadata(work,src,arm,f['prompt'],f['interface'])
            actual,bound=proof.bound_route(work,ROOT,arm,f['prompt'],f['interface'],True,composition,providers)
            assert actual==route and bound==receipt and receipt['selected_provider']==f['label']
            assert receipt['original_recipe']==f['receipt'];pair.append(receipt)
            mechan[(f['label'],arm)]=(work,src,receipt,f);positives.append('same_common_mechanical_'+f['label']+'_'+arm)
        assert pair[0]==pair[1]
    wave=fixtures['wave']
    c=model_metadata('wave_C','C',wave['prompt'],wave['interface'])
    p=model_metadata('wave_P','P',wave['prompt'],wave['interface'])
    unchanged=model_metadata('unsupported_P','P','Unspecified design.','')
    repaired=model_metadata('wave_P_repair','P',wave['prompt'],wave['interface'],True)
    proofs={}
    for label,case,changed in [('C_supported',c,False),('P_supported',p,True),('P_unsupported',unchanged,False),('P_repair',repaired,True)]:
        result=verify_model(case);assert result['first_request_advice_changed'] is changed
        assert result['waveform_request_binding_verified'] and result['repair_wires_unchanged']
        assert result['parent_route']=='model' and result['parent_abstention_bound'] and result['common_mechanical_strategy_bound']
        proofs[label]=result;positives.append(label)
    assert proofs['C_supported']['first_original_wire_sha256']==proofs['P_supported']['first_original_wire_sha256']
    assert proofs['C_supported']['first_forwarded_wire_sha256']!=proofs['P_supported']['first_forwarded_wire_sha256']
    # A C historical mechanical route must never carry the wave wrapper's records.
    work,src,receipt,f=mechan[('onehot','C')];(work/'waveform_request_receipts').mkdir()
    rejects('mechanical_C_onehot_forbidden_wave_receipt',lambda:proof.bound_route(work,ROOT,'C',f['prompt'],f['interface'],True,composition,providers))
    # New C onehot permission does not make simulated native metadata admissible.
    save(work/'requests.json',[]);(work/'solution.v').write_bytes(receipt['rtl'].encode());(work/'emission').mkdir()
    (work/'emission/emitted.sv').write_bytes(receipt['rtl'].encode());save(work/'emission/contract.json',receipt['contract'])
    native=work/'native_receipts/0';native.mkdir(parents=True);save(native/'command.json',dict(simulated=True))
    row=dict(arm='C',selected_provider='onehot',solve_deadline_reached=False,actual_model_requests=0,received_model_responses=0)
    rejects('new_C_onehot_still_rejects_fake_native',lambda:proof.mechanical_provenance(work,ROOT,'SIMULATED',row,receipt,work,modules['runner'],modules['parser'],None))
    wrong=clone_case(p,'missing_round');shutil.rmtree(wrong[0]/'waveform_request_receipts/0')
    rejects('model_missing_wave_round',lambda:verify_model(wrong))
    wrong=clone_case(p,'extra_round');(wrong[0]/'waveform_request_receipts/99').mkdir()
    rejects('model_extra_wave_round',lambda:verify_model(wrong))
    wrong=clone_case(p,'forged_advice');forged_forwarded(wrong,0,'\nFORGED_ADVICE')
    rejects('independent_first_advice_reconstruction',lambda:verify_model(wrong))
    wrong=clone_case(repaired,'changed_repair');forged_forwarded(wrong,1,'\nFORGED_REPAIR')
    rejects('repair_must_keep_original_prompt',lambda:verify_model(wrong))
    for name in ('selector','waveform_worker','waveform_facts'):
        altered=dict(modules);altered[name]=SimpleNamespace(__file__=modules[name].__file__)
        rejects('same_path_different_'+name+'_object',lambda:proof.bound_modules(ROOT,altered))
    altered=dict(modules);altered['request_proof']=SimpleNamespace(__file__=request_proof.__file__,waveform_facts=SimpleNamespace(__file__=modules['waveform_facts'].__file__))
    rejects('request_proof_cached_wrong_facts_object',lambda:proof.bound_modules(ROOT,altered))
    proof.bound_modules(ROOT,modules)
    result=dict(schema='table_history_wave_new_generation_stitch_controls_v1',passed=True,positive_contexts=len(positives),rejection_contexts=len(negatives),positives=positives,rejections=negatives,model_records_simulated_with_unconfirmed_attempts=True,new_worker_model_EDA_FIFO_calls=0,old_test_suites_native_intake_and_full_auditor_not_rerun=True,real_native_positive=False,scoring_qualified=False,adoption=False)
    save(ROOT/'ACTUAL_WAVE_GENERATION_STITCH_RESULT.json',result);print(json.dumps(result))

if __name__=='__main__':main()
