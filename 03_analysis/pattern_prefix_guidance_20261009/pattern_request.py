"""One prompt-derived first-request factor; no HTTP, DUT, task ID or oracle input."""
import hashlib
import json
from pathlib import Path
import pattern_guidance

SCHEMA = 'explicit_pattern_prefix_request_factor_draft_v1'
MARKER = '\n\n[Binary pattern prefix guidance derived from the supplied specification]\n'

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
    normalized = prompt.replace('\r\n', '\n').replace('\r', '\n')
    normalized_interface = interface.replace('\r\n', '\n').replace('\r', '\n')
    user = normalized + ('\n\nInterface:\n' + normalized_interface if normalized_interface.strip() else '')
    if round_index == 0:
        assert messages[1]['content'] == user, 'initial request differs from original runtime prompt/interface'
    else:
        assert messages[1]['content'].startswith(user + '\nPrevious candidate:\n')
        assert '\nCandidate diagnostics:\n' in messages[1]['content'][len(user):]
    receipt = dict(schema=SCHEMA, arm=arm, round_index=round_index, changed=False,
                   prompt_sha256=digest(prompt.encode()), interface_sha256=digest(interface.encode()),
                   original_wire_sha256=digest(payload), forwarded_wire_sha256=digest(payload),
                   original_wire_bytes=len(payload), forwarded_wire_bytes=len(payload),
                   addendum='', addendum_sha256=digest(b''), extraction_sha256=None,
                   extraction_status=None,
                   application_status='control_unchanged' if arm == 'C' else 'repair_unchanged',
                   model_request_delta=0, output_token_budget=8192, maximum_requests=2,
                   maximum_additional_user_chars=8192,
                   derives_semantic_prefix_transitions=False, emits_rtl=False, determines_reset_enable_output_timing=False)
    if arm == 'C' or round_index != 0:
        return payload, receipt
    extraction = pattern_guidance.extract(prompt, interface)
    addendum = extraction['addendum']
    assert isinstance(addendum, str) and extraction['status'] in ('supported', 'abstain')
    receipt.update(extraction_status=extraction['status'],
                   application_status=extraction['status'],
                   extraction_sha256=digest(json.dumps(extraction, sort_keys=True, separators=(',', ':')).encode()))
    if not addendum:
        assert extraction['status'] == 'abstain'
        receipt['reason'] = extraction['reason']
        return payload, receipt
    assert extraction['status'] == 'supported' and extraction['derives_semantic_prefix_transitions']
    assert not extraction['emits_rtl'] and not extraction['determines_reset_enable_output_timing']
    if len(MARKER) + len(addendum) > 8192:
        receipt.update(application_status='abstain', reason='addendum_bound_exceeded_no_truncation')
        return payload, receipt
    assert MARKER not in messages[1]['content']
    body['messages'][1]['content'] += MARKER + addendum
    forwarded = json.dumps(body).encode()
    receipt.update(changed=True, derives_semantic_prefix_transitions=True, addendum=addendum, addendum_sha256=digest(addendum.encode()),
                   forwarded_wire_sha256=digest(forwarded), forwarded_wire_bytes=len(forwarded))
    return forwarded, receipt

def request_class(base, context):
    """The original worker still owns HTTP and accounting; record exact boundary bytes."""
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
            assert out.is_dir(), 'original worker must create its own output directory first'
            folder = out / 'pattern_request_receipts' / str(index)
            folder.mkdir(parents=True, exist_ok=False)
            (folder / 'original_wire.bin').write_bytes(original)
            (folder / 'forwarded_wire.bin').write_bytes(forwarded)
            (folder / 'receipt.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            context['receipts'].append(receipt)
            if forwarded != original:
                self.data = forwarded
                self.remove_header('Content-length')
    return ObservedRequest
