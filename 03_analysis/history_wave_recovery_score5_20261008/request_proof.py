"""Read-only reconstruction of original and forwarded request evidence.

No transformer call, HTTP, DUT generation or question identity. Full repair
diagnostics and compiler provenance are independently checked by waveform_replay.
"""
import hashlib
import json
from pathlib import Path
import waveform_facts

MARKER = '\n\n[Additional observations derived only from the supplied waveform]\n'

def digest(data):
    return hashlib.sha256(data).hexdigest()

def unique_object(pairs):
    result = {}
    for key, value in pairs:
        assert key not in result, 'Duplicate JSON member'
        result[key] = value
    return result

def decode(data):
    return json.loads(data, object_pairs_hook=unique_object)

def read(path):
    return decode(Path(path).read_bytes())

def combined(prompt, interface):
    normalize = lambda s: s.replace('\r\n', '\n').replace('\r', '\n')
    p, i = normalize(prompt), normalize(interface)
    return p + ('\n\nInterface:\n' + i if i.strip() else '')

def verify(work, prompt, interface, arm, model, generation, repair, allow_unconfirmed=False):
    work = Path(work)
    assert arm in ('C', 'P') and isinstance(prompt, str) and isinstance(interface, str)
    assert isinstance(model, str) and model and generation and repair
    assert type(allow_unconfirmed) is bool
    journal = read(work/'requests.json')
    assert isinstance(journal, list) and 1 <= len(journal) <= 2
    names = {str(i) for i in range(len(journal))}
    assert {p.name for p in (work/'requests').iterdir()} == names
    assert {p.name for p in (work/'waveform_request_receipts').iterdir()} == names
    expected_prompt_files = {'prompt.txt'} | ({'interface.txt'} if (work/'prompt_only/interface.txt').exists() else set())
    assert {p.name for p in (work/'prompt_only').iterdir()} == expected_prompt_files
    assert (work/'prompt_only/prompt.txt').read_bytes() == prompt.encode()
    assert (work/'prompt_only/interface.txt').read_bytes() == interface.encode() if 'interface.txt' in expected_prompt_files else interface == ''
    rounds = []
    expected_user = combined(prompt, interface)
    for i, entry in enumerate(journal):
        assert type(entry['index']) is int and entry['index'] == i and entry['replayed'] is False
        assert type(entry['response_received']) is bool
        assert entry['response_received'] or (allow_unconfirmed and i == len(journal)-1)
        folder = work/'waveform_request_receipts'/str(i)
        assert {p.name for p in folder.iterdir()} == {'original_wire.bin', 'forwarded_wire.bin', 'receipt.json'}
        raw = (folder/'original_wire.bin').read_bytes()
        wire = (folder/'forwarded_wire.bin').read_bytes()
        original = decode(raw)
        assert set(original) == {'model', 'messages', 'temperature', 'top_p', 'max_tokens'}
        assert original['model'] == model and type(original['max_tokens']) is int and original['max_tokens'] == 8192
        assert type(original['temperature']) in (int, float) and original['temperature'] == 0
        assert type(original['top_p']) in (int, float) and original['top_p'] == 1
        messages = original['messages']
        assert isinstance(messages, list) and len(messages) == 2
        assert all(isinstance(m, dict) and set(m) == {'role', 'content'} and isinstance(m['content'], str) for m in messages)
        assert messages[0] == dict(role='system', content=generation+('\n'+repair if i else ''))
        assert messages[1]['role'] == 'user'
        # Original runtime constructs this exact ordered JSON at Request boundary.
        canonical = dict(model=model, messages=messages, temperature=0.0, top_p=1.0, max_tokens=8192)
        assert raw == json.dumps(canonical).encode()
        if i == 0:
            assert messages[1]['content'] == expected_user
        else:
            assert messages[1]['content'].startswith(expected_user+'\nPrevious candidate:\n')
            assert '\nCandidate diagnostics:\n' in messages[1]['content'][len(expected_user):]
        advice = ''
        contract = None
        status = 'control_unchanged' if arm == 'C' else 'repair_unchanged'
        if arm == 'P' and i == 0:
            contract = waveform_facts.parse(prompt)
            advice = waveform_facts.render_advice(contract)
            status = contract['status']
        expected_body = decode(raw)
        if advice:
            assert contract['status'] == 'supported' and len(advice) <= 8192
            assert not any(contract[k] for k in ('unique_circuit_inferred', 'reset_inferred', 'initialization_inferred'))
            assert MARKER not in expected_user
            expected_body['messages'][1]['content'] += MARKER+advice
        expected_wire = json.dumps(expected_body).encode() if advice else raw
        assert wire == expected_wire
        request = work/'requests'/str(i)/'request.json'
        assert read(request) == expected_body and entry['request_sha256'] == digest(request.read_bytes())
        expected_receipt = dict(schema='waveform_observation_request_factor_v1', arm=arm, round_index=i,
            changed=bool(advice), prompt_sha256=digest(prompt.encode()), interface_sha256=digest(interface.encode()),
            original_wire_sha256=digest(raw), forwarded_wire_sha256=digest(wire),
            original_wire_bytes=len(raw), forwarded_wire_bytes=len(wire),
            advice=advice, advice_sha256=digest(advice.encode()),
            contract_sha256=digest(json.dumps(contract, sort_keys=True, separators=(',', ':')).encode()) if contract is not None else None,
            observation_status=status, model_request_delta=0, output_token_budget=8192, maximum_requests=2,
            unique_circuit_inferred=False, reset_inferred=False, initialization_inferred=False)
        assert read(folder/'receipt.json') == expected_receipt
        response = work/'requests'/str(i)/'response.json'
        assert response.exists() == entry['response_received']
        if response.exists():
            assert digest(response.read_bytes()) == entry['response_sha256']
        assert {p.name for p in request.parent.iterdir()} == {'request.json'} | ({'response.json'} if response.exists() else set())
        rounds.append(dict(index=i, changed=bool(advice), original_wire_sha256=digest(raw),
            forwarded_wire_sha256=digest(wire), factor_receipt_sha256=digest((folder/'receipt.json').read_bytes()),
            original_body=original, forwarded_body=expected_body))
    identity = [{k:v for k,v in row.items() if k not in ('original_body', 'forwarded_body')} for row in rounds]
    return dict(schema='waveform_request_wire_readonly_proof_v1', verified=True, arm=arm,
        actual_model_requests=len(journal), all_responses_confirmed=all(e['response_received'] for e in journal),
        first_request_advice_changed=rounds[0]['changed'],
        request_proof_sha256=digest(json.dumps(identity, sort_keys=True, separators=(',', ':')).encode()), rounds=rounds)

def binding(proof):
    assert proof['verified'] is True
    return dict(generation_route='model', stage_generation_binding_verified=True,
        waveform_request_binding_verified=True, request_proof_sha256=proof['request_proof_sha256'],
        first_request_advice_changed=proof['first_request_advice_changed'])
