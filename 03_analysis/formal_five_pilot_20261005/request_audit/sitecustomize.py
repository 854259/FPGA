"""Observe worker POST bodies through CPython audit events; no transport patch."""
import hashlib,json,os,sys,threading,time
from pathlib import Path

folder=os.environ.get('RTL_REQUEST_AUDIT_DIR')
if folder:
    root=Path(folder).resolve();root.mkdir(parents=True,exist_ok=True)
    lock=threading.Lock()
    def observe(event,args):
        if event!='urllib.Request':return
        url,data,_headers,method=args
        if not url.endswith('/chat/completions'):return
        assert url=='http://127.0.0.1:8000/v1/chat/completions' and method=='POST'
        assert isinstance(data,bytes)
        body=json.loads(data)
        assert isinstance(body,dict)
        # No header/credential capture; preserve the exact bytes handed to urllib.
        with lock:
            journal=root/'requests.jsonl'
            count=len(journal.read_text(encoding='utf-8').splitlines()) if journal.exists() else 0
            target=root/(str(count)+'.request.json')
            with target.open('xb') as stream:stream.write(data)
            with journal.open('a',encoding='utf-8') as stream:
                stream.write(json.dumps({'index':count,'pid':os.getpid(),'at_monotonic':time.monotonic(),'url':url,'body_sha256':hashlib.sha256(data).hexdigest(),'scope':'urllib attempt before network; successful response requires matching worker trace'})+'\n')
    sys.addaudithook(observe)
