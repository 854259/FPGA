"""Identity-only observation at the HTTP Request boundary; never changes payloads."""
import hashlib,json
from pathlib import Path
def digest(b):return hashlib.sha256(b).hexdigest()
def request_class(base,context):
    assert set(context)=={'prompt','interface','arm','out','receipts'}
    class ObservedRequest(base):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs)
            if self.full_url!='http://127.0.0.1:8000/v1/chat/completions':return
            assert self.get_method()=='POST' and isinstance(self.data,bytes)
            i=len(context['receipts']);assert i<2 and context['arm'] in ('C','P')
            raw=self.data;body=json.loads(raw)
            receipt=dict(schema='internal_declaration_identity_wire_v1',arm=context['arm'],round_index=i,
                prompt_sha256=digest(context['prompt'].encode()),interface_sha256=digest(context['interface'].encode()),
                wire_sha256=digest(raw),wire_bytes=len(raw),changed=False)
            folder=Path(context['out'])/'identity_request_receipts'/str(i);folder.mkdir(parents=True,exist_ok=False)
            (folder/'wire.bin').write_bytes(raw)
            (folder/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
            context['receipts'].append(receipt)
            assert self.data==raw
    return ObservedRequest
