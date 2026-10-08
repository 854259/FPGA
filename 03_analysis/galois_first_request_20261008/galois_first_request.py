"""Clarify explicit prompt semantics only at the first HTTP request boundary."""
import hashlib
import json
from pathlib import Path
import re
import galois_prompt_contract as contract

ENDPOINT='http://127.0.0.1:8000/v1/chat/completions'
SUFFIX='\n\n'
digest=lambda value:hashlib.sha256(value).hexdigest()

def unique(pairs):
    result={}
    for name,value in pairs:
        assert name not in result,'Duplicate request field'
        result[name]=value
    return result

def decode(raw):return json.loads(raw,object_pairs_hook=unique)

def combined(prompt,interface):
    normalize=lambda s:s.replace('\r\n','\n').replace('\r','\n')
    p,i=normalize(prompt),normalize(interface)
    return p+('\n\nInterface:\n'+i if i.strip() else '')

def interface_matches(interface,c):
    if not interface.strip():return True
    text=re.sub(r'\s+',' ',interface).strip()
    match=re.fullmatch(r'module\s+('+contract.IDENT+r')\s*\((.*)\)\s*;\s*endmodule',text)
    if not match or match[1]!=c['module']:return False
    ports={}
    for item in match[2].split(','):
        p=re.fullmatch(r'\s*(input|output)\s+(?:(?:wire|reg)\s+)?(?:\[\s*(\d+)\s*:\s*0\s*\]\s*)?('+contract.IDENT+r')\s*',item)
        if not p or p[3] in ports:return False
        ports[p[3]]=(p[1],int(p[2])+1 if p[2] else 1)
    return ports=={c['clock']:('input',1),c['reset']:('input',1),c['output']:('output',c['width'])}

def clarification(prompt,interface):
    c=contract.parse(prompt)
    if c['status']!='supported':return '',c['reason']
    if not interface_matches(interface,c):return '','interface_conflict_or_scope'
    return contract.clarify(c),'explicit_prompt_contract'

def validate(raw,prompt,interface,index):
    assert isinstance(raw,bytes) and type(index) is int and 0<=index<2
    assert isinstance(prompt,str) and isinstance(interface,str)
    body=decode(raw)
    assert set(body)=={'model','messages','temperature','top_p','max_tokens'}
    assert isinstance(body['model'],str) and body['model']
    assert type(body['max_tokens']) is int and body['max_tokens']==8192
    assert type(body['temperature']) in (float,int) and body['temperature']==0
    assert type(body['top_p']) in (float,int) and body['top_p']==1
    messages=body['messages'];assert isinstance(messages,list) and len(messages)==2
    assert all(isinstance(m,dict) and set(m)=={'role','content'} and isinstance(m['content'],str) for m in messages)
    assert messages[0]['role']=='system' and messages[0]['content'] and messages[1]['role']=='user'
    expected=combined(prompt,interface)
    if index==0:assert messages[1]['content']==expected
    else:
        assert messages[1]['content'].startswith(expected+'\nPrevious candidate:\n')
        assert '\nCandidate diagnostics:\n' in messages[1]['content'][len(expected):]
    return body

def transform(raw,prompt,interface,arm,index):
    assert arm in ('C','P')
    body=validate(raw,prompt,interface,index)
    text,reason=clarification(prompt,interface) if index==0 else ('','repair_unchanged')
    changed=arm=='P' and index==0 and bool(text)
    forwarded=raw
    if changed:
        assert raw==json.dumps(body).encode(),'Unexpected original wire serialization'
        body['messages'][1]['content']+=SUFFIX+text
        forwarded=json.dumps(body).encode()
    receipt=dict(schema='galois_first_request_boundary_v1',arm=arm,round_index=index,
        prompt_sha256=digest(prompt.encode()),interface_sha256=digest(interface.encode()),
        original_wire_sha256=digest(raw),forwarded_wire_sha256=digest(forwarded),
        original_wire_bytes=len(raw),forwarded_wire_bytes=len(forwarded),
        changed=changed,reason=reason,clarification_sha256=digest(text.encode()) if text else None)
    return forwarded,receipt

def verify(original,forwarded,prompt,interface,arm,index,receipt):
    """Reconstruct the allowed change without invoking the transformer."""
    assert arm in ('C','P')
    before=validate(original,prompt,interface,index)
    text,reason=clarification(prompt,interface) if index==0 else ('','repair_unchanged')
    changed=arm=='P' and index==0 and bool(text)
    after=decode(forwarded)
    if changed:
        assert original==json.dumps(before).encode()
        expected=decode(original);expected['messages'][1]['content']=combined(prompt,interface)+SUFFIX+text
        assert after==expected and forwarded==json.dumps(expected).encode()
    else:assert forwarded==original and after==before
    assert receipt==dict(schema='galois_first_request_boundary_v1',arm=arm,round_index=index,
        prompt_sha256=digest(prompt.encode()),interface_sha256=digest(interface.encode()),
        original_wire_sha256=digest(original),forwarded_wire_sha256=digest(forwarded),
        original_wire_bytes=len(original),forwarded_wire_bytes=len(forwarded),
        changed=changed,reason=reason,clarification_sha256=digest(text.encode()) if text else None)
    return dict(verified=True,changed=changed,first_system_changed=False,repair_unchanged=index>0,
                original_wire_sha256=digest(original),forwarded_wire_sha256=digest(forwarded))

def request_class(base,context):
    assert set(context)=={'prompt','interface','arm','out','receipts'}
    class ClarifiedRequest(base):
        def __init__(self,*args,**kwargs):
            super().__init__(*args,**kwargs)
            if self.full_url!=ENDPOINT:return
            assert self.get_method()=='POST' and isinstance(self.data,bytes)
            index=len(context['receipts']);original=self.data
            forwarded,receipt=transform(original,context['prompt'],context['interface'],context['arm'],index)
            folder=Path(context['out'])/'first_request_receipts'/str(index);folder.mkdir(parents=True,exist_ok=False)
            (folder/'original.bin').write_bytes(original)
            (folder/'forwarded.bin').write_bytes(forwarded)
            (folder/'receipt.json').write_bytes((json.dumps(receipt,indent=2)+'\n').encode())
            context['receipts'].append(receipt)
            self.data=forwarded
    return ClarifiedRequest
