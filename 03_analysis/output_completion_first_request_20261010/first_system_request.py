"""Task-independent emission rule; only P round zero changes the system wire."""
import hashlib
import json
from pathlib import Path

SCHEMA = 'first_generation_output_discipline_request_factor_source_draft_v2'
SYSTEM_SUFFIX = '\n\nReturn only the complete RTL implementation in the output format already required. Use concise RTL. Do not include analysis, prose, waveform tables, exploratory alternatives, or reasoning comments in the output. Keep only brief comments that directly explain the implemented logic. Finish every block and endmodule within the output budget; never spend the response repeating or debating the specification. Preserve the required interface and behavior.'

def digest(data):
    return hashlib.sha256(data).hexdigest()

def transform(payload, prompt, interface, arm, round_index):
    assert isinstance(payload, bytes) and isinstance(prompt, str) and isinstance(interface, str)
    assert arm in ('C', 'P') and type(round_index) is int and round_index in (0, 1)
    body = json.loads(payload)
    assert isinstance(body, dict) and set(body) == {'model', 'messages', 'temperature', 'top_p', 'max_tokens'}
    assert isinstance(body['model'], str) and body['model'] and body['temperature'] == 0
    assert body['top_p'] == 1 and type(body['max_tokens']) is int and body['max_tokens'] == 8192
    messages = body['messages']
    assert isinstance(messages, list) and len(messages) == 2
    assert all(isinstance(m, dict) and set(m) == {'role', 'content'} and isinstance(m['content'], str) for m in messages)
    assert messages[0]['role'] == 'system' and messages[0]['content'] and messages[1]['role'] == 'user'
    normalize = lambda s: s.replace('\r\n', '\n').replace('\r', '\n')
    user = normalize(prompt) + ('\n\nInterface:\n' + normalize(interface) if normalize(interface).strip() else '')
    if round_index == 0:
        assert messages[1]['content'] == user
    else:
        assert messages[1]['content'].startswith(user + '\nPrevious candidate:\n')
        assert '\nCandidate diagnostics:\n' in messages[1]['content'][len(user):]
    system = messages[0]['content']
    receipt = dict(schema=SCHEMA, arm=arm, round_index=round_index, changed=False,
        prompt_sha256=digest(prompt.encode()), interface_sha256=digest(interface.encode()),
        original_wire_sha256=digest(payload), forwarded_wire_sha256=digest(payload),
        original_wire_bytes=len(payload), forwarded_wire_bytes=len(payload),
        original_system_sha256=digest(system.encode()), forwarded_system_sha256=digest(system.encode()),
        user_sha256=digest(messages[1]['content'].encode()), system_suffix='', system_suffix_sha256=digest(b''),
        application_status='control_unchanged' if arm == 'C' else 'repair_unchanged',
        model_request_delta=0, output_token_budget=8192, maximum_requests=2,
        user_changed=False, task_specific=False, interpretation_or_answer_added=False)
    if arm == 'C' or round_index != 0:
        return payload, receipt
    assert SYSTEM_SUFFIX not in system, 'factor already present'
    body['messages'][0]['content'] += SYSTEM_SUFFIX
    forwarded = json.dumps(body).encode()
    receipt.update(changed=True, application_status='first_system_suffix', system_suffix=SYSTEM_SUFFIX,
        system_suffix_sha256=digest(SYSTEM_SUFFIX.encode()),
        forwarded_system_sha256=digest(body['messages'][0]['content'].encode()),
        forwarded_wire_sha256=digest(forwarded), forwarded_wire_bytes=len(forwarded))
    return forwarded, receipt

def request_class(base, context):
    assert isinstance(context, dict) and set(context) == {'prompt', 'interface', 'arm', 'out', 'receipts'}
    class ObservedRequest(base):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            if self.full_url != 'http://127.0.0.1:8000/v1/chat/completions':
                return
            assert self.get_method() == 'POST' and isinstance(self.data, bytes)
            index = len(context['receipts'])
            original = self.data
            forwarded, receipt = transform(original, context['prompt'], context['interface'], context['arm'], index)
            out = Path(context['out'])
            assert out.is_dir()
            folder = out / 'first_system_request_receipts' / str(index)
            folder.mkdir(parents=True, exist_ok=False)
            (folder / 'original_wire.bin').write_bytes(original)
            (folder / 'forwarded_wire.bin').write_bytes(forwarded)
            (folder / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            context['receipts'].append(receipt)
            if forwarded != original:
                self.data = forwarded
                self.remove_header('Content-length')
    return ObservedRequest
