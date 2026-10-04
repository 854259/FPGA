"""Readonly exposure audit of actual historical second-request context copies."""
import collections
import hashlib
import json
from pathlib import Path
import zipfile
import context

ROOT=Path(__file__).resolve().parent
ARCHIVE=ROOT.parent/'functional_full156_20261005/raw_evidence/terminal_v1.zip'


def main():
    digest=hashlib.sha256(ARCHIVE.read_bytes()).hexdigest()
    assert digest=='ac3b27f553bbf274d2edc875a7a3354b42741a9861ca409b37b779d1c6067055'
    rows=[]
    with zipfile.ZipFile(ARCHIVE) as z:
        for name in sorted(z.namelist()):
            if not name.endswith('/worker/requests/1/request.json'):
                continue
            body=json.loads(z.read(name));user=body['messages'][1]['content']
            assert user.count('\nPrevious candidate:\n')==1
            source=user.split('\nPrevious candidate:\n',1)[1].rsplit('\nCandidate diagnostics:\n',1)[0]
            result,receipt=context.compress(source)
            parts=Path(name).parts;task=parts[4];arm=parts[3]
            assert arm in ['A','C'] and task.startswith('Prob')
            rows.append(dict(task=task,arm=arm,request_sha256=hashlib.sha256(z.read(name)).hexdigest(),**receipt))
    assert len(rows)==21
    report=dict(schema='repair_context_archived_exposure_v1',archive_sha256=digest,
                candidate_source_sha256=hashlib.sha256((ROOT/'context.py').read_bytes()).hexdigest(),
                observed_repair_requests=len(rows),changed_contexts=sum(r['changed'] for r in rows),
                reason_counts=dict(collections.Counter(r['reason'] for r in rows)),rows=rows,
                new_model_calls=0,new_eda_calls=0,new_score=False,adoption=False,
                scope='Historical prompt copies only, not fresh solving or speed/quality evidence.')
    (ROOT/'ARCHIVED_EXPOSURE.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='rows'}))
    print(json.dumps([r for r in rows if r['changed']]))


if __name__=='__main__':main()
