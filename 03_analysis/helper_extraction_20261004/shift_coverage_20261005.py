"""R3: outcome-blind applicability on every frozen public156 prompt; zero model/EDA."""
import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time
import zipfile


def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def load(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m


def run(a):
    assert sys.platform=='linux';sys.dont_write_bytecode=True
    assert sha(a.candidate)=='a1ce1552754c7c72d9c33b0f596937959bc392d305c3e956c266c5a4b2188157'
    assert sha(a.candidate.with_name('SV_KEYWORDS_V12_0.json'))=='d9eb8f6bd2423e27f51206e169c8de095529079b96bc595b4e9231635f33e70c'
    assert sha(a.archive)=='64ace96d59d9a1802513f20be3e21c191786ba04d2054b9ab4072900893c7616'
    assert sha(a.paired)=='78e9b3e144f2bd43ebab371e15ac3946017686db890a8e45891db7a386841e1c'
    paired=load('r3_supervisor',a.paired);paired.check_resource(a.resource_check,a.kit,first=True)
    parser=load('r3_parser',a.candidate);a.out.mkdir(parents=True,exist_ok=False);tick=time.monotonic();rows=[]
    with zipfile.ZipFile(a.archive) as z:
        manifest=json.loads(z.read('ARCHIVE_MANIFEST.json'))['files']
        def read(n):
            data=z.read(n);item=manifest[n];assert hashlib.sha256(data).hexdigest()==(item['sha256'] if isinstance(item,dict) else item);return data
        names=sorted(n for n in z.namelist() if n.startswith('kit/bench/tasks_veval/') and n.endswith('/prompt.txt'))
        assert len(names)==156
        for n in names:
            prompt=read(n).decode();interface=n[:-len('prompt.txt')]+'interface.txt'
            if interface in manifest and read(interface).decode().strip():prompt+='\n\nInterface:\n'+read(interface).decode()
            contract=parser.parse(prompt)
            rows.append(dict(task=Path(n).parent.name,prompt_sha256=hashlib.sha256(prompt.encode()).hexdigest(),status=contract['status'],reason=contract.get('reason'),width=contract.get('width')))
        # Entire selector inventory is persisted before reading any grade.
        (a.out/'SELECTOR_ONLY.json').write_text(json.dumps(rows,indent=2)+'\n')
        for row in rows:
            v=json.loads(read('run/samples/A/'+row['task']+'/judge/verdict.json'))
            row['archived_original_level']=v['level']
            row['prior_signedness_development_task']=row['task']=='Prob115_shift18'
    counts=dict(Counter(r['status'] for r in rows));supported=[r for r in rows if r['status']=='supported']
    paired.check_resource(a.resource_check,a.kit)
    result=dict(complete=True,passed=True,scope='All frozen public156 prompts; applicability only, no fresh score',
                model_calls=0,eda_calls=0,rows=rows,counts=counts,supported=supported,
                supported_original_L3=sum(r['archived_original_level']==3 for r in supported),
                supported_outside_prior_signedness=sum(not r['prior_signedness_development_task'] for r in supported),
                independent_natural_tasks=0,full_batch_complete=False,candidate_sha256=sha(a.candidate),
                archive_sha256=sha(a.archive),selector_only_sha256=sha(a.out/'SELECTOR_ONLY.json'),
                elapsed_s=time.monotonic()-tick,deployed=False)
    (a.out/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='rows'}),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ['candidate','archive','out','paired','resource-check','kit']:p.add_argument('--'+n,type=Path,required=True)
    run(p.parse_args())
