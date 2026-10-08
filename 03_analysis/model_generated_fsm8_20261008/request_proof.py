"""Read-only provenance of original/forwarded wires, responses and unchanged system/budgets."""
import hashlib,json
from pathlib import Path
import fsm_guidance as boundary

digest=lambda b:hashlib.sha256(b).hexdigest()
read=lambda p:boundary.decode(Path(p).read_bytes())

def verify(work,prompt,interface,arm,model,generation,repair,allow_unconfirmed=False):
    work=Path(work)
    assert arm in ('C','P') and isinstance(model,str) and model and generation and repair
    assert type(allow_unconfirmed) is bool
    journal=read(work/'requests.json');assert isinstance(journal,list) and 1<=len(journal)<=2
    expected_names={str(i) for i in range(len(journal))}
    assert {p.name for p in (work/'requests').iterdir()}==expected_names
    assert {p.name for p in (work/'first_request_receipts').iterdir()}==expected_names
    expected_inputs={'prompt.txt'}|({'interface.txt'} if (work/'prompt_only/interface.txt').exists() else set())
    assert {p.name for p in (work/'prompt_only').iterdir()}==expected_inputs
    assert (work/'prompt_only/prompt.txt').read_bytes()==prompt.encode()
    if 'interface.txt' in expected_inputs:assert (work/'prompt_only/interface.txt').read_bytes()==interface.encode()
    else:assert interface==''
    assert not any((work/n).exists() for n in ['emission','native_receipts','internal_declaration_journal.json'])
    rounds=[]
    for index,entry in enumerate(journal):
        assert type(entry['index']) is int and entry['index']==index and entry['replayed'] is False
        assert type(entry['response_received']) is bool
        assert entry['response_received'] or (allow_unconfirmed and index==len(journal)-1)
        evidence=work/'first_request_receipts'/str(index)
        assert {p.name for p in evidence.iterdir()}=={'original.bin','forwarded.bin','receipt.json'}
        original=(evidence/'original.bin').read_bytes();forwarded=(evidence/'forwarded.bin').read_bytes()
        before=boundary.validate(original,prompt,interface,index);after=read(evidence/'forwarded.bin')
        assert before['model']==model
        expected_system=dict(role='system',content=generation+('\n'+repair if index else ''))
        assert before['messages'][0]==after['messages'][0]==expected_system
        canonical=dict(model=model,messages=before['messages'],temperature=0.0,top_p=1.0,max_tokens=8192)
        assert original==json.dumps(canonical).encode()
        proof=boundary.verify(original,forwarded,prompt,interface,arm,index,read(evidence/'receipt.json'))
        request=work/'requests'/str(index)/'request.json';response=request.with_name('response.json')
        assert read(request)==after and digest(request.read_bytes())==entry['request_sha256']
        expected_files={'request.json'}|({'response.json'} if entry['response_received'] else set())
        assert {p.name for p in request.parent.iterdir()}==expected_files
        assert response.exists()==entry['response_received']
        if response.exists():
            assert digest(response.read_bytes())==entry['response_sha256']
            payload=read(response);assert isinstance(payload['choices'],list) and len(payload['choices'])==1
            choice=payload['choices'][0];assert choice.get('finish_reason')==entry['finish_reason']
            assert payload.get('id')==entry['response_id'] and payload.get('usage')==entry.get('usage')
        rounds.append(dict(index=index,changed=proof['changed'],original_wire_sha256=digest(original),forwarded_wire_sha256=digest(forwarded),receipt_sha256=digest((evidence/'receipt.json').read_bytes()),request_sha256=entry['request_sha256'],response_sha256=entry.get('response_sha256'),original_body=before,forwarded_body=after))
    identity=[{k:v for k,v in r.items() if k not in ('original_body','forwarded_body')} for r in rounds]
    return dict(schema='fsm_model_first_user_original_response_request_proof_v1',verified=True,arm=arm,actual_model_requests=len(journal),all_responses_confirmed=all(r['response_received'] for r in journal),first_system_changed=False,first_user_changed=rounds[0]['changed'],repair_wires_unchanged=all(not r['changed'] for r in rounds[1:]),declaration_enabled=False,request_proof_sha256=digest(json.dumps(identity,sort_keys=True,separators=(',',':')).encode()),rounds=rounds)

def binding(proof):
    assert proof['verified']
    return dict(generation_route='model',stage_generation_binding_verified=True,semantic_factor_binding_verified=True,request_proof_sha256=proof['request_proof_sha256'],first_system_changed=False,first_user_changed=proof['first_user_changed'],repair_wires_unchanged=proof['repair_wires_unchanged'],declaration_enabled=False)
