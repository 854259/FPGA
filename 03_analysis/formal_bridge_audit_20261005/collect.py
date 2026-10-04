"""Read-only terminal bridge archive, outside the frozen run directory."""
import argparse,datetime,hashlib,json
from pathlib import Path
import zipfile
import sys

def digest(raw):return hashlib.sha256(raw).hexdigest()
def read(path):return json.loads(path.read_text(encoding='utf-8'))

def collect(root,archive,prior=None,failure=False,fixture=False):
    root,archive=Path(root).resolve(),Path(archive).resolve()
    assert not archive.exists() and not archive.is_relative_to(root)
    spec=read(root/'RUN_SPEC.json');guard=read(root/'guard/status.json')
    if not fixture:assert sys.platform=='linux' and str(root)==spec['cloud_root']
    assert guard['complete'],'Guard is not terminal'
    if not failure:
        report=read(root/'results/summary.json')
        assert report['complete'] and report['passed'] and guard['passed']
        assert guard['owned_cleanup']['verified'] and not guard['owned_cleanup']['remaining']
    # A terminal JSON alone must not be used to capture mutable live output.
    cleanup=guard.get('owned_cleanup',{})
    for identity in cleanup.get('recorded',[])+cleanup.get('remaining',[]):
        p=Path('/proc')/str(identity['pid'])/'stat'
        if p.exists():
            fields=p.read_text().rsplit(')',1)[1].split()
            assert fields[19]!=identity['starttime'] or fields[0] in ['Z','X'],'Owned process remains live'
    files={};missing=[]
    def add(path,name,expected=None):
        assert path.is_file() and not path.is_symlink()
        raw=path.read_bytes();assert len(raw)<=50*1024**2
        if expected:assert digest(raw)==expected,name
        assert name not in files;files[name]=raw
    for n,h in spec['source_hashes'].items():
        if failure and not (root/n).is_file():missing.append(n)
        else:add(root/n,'run/'+n,None if failure else h)
    add(root/'RUN_SPEC.json','run/RUN_SPEC.json')
    add(root/'PREPARATION_RECEIPT.json','run/PREPARATION_RECEIPT.json')
    # Record unexpected package files too, so an audit cannot miss shadow code.
    for p in sorted((root/'package').rglob('*')):
        if '__pycache__' in p.parts or p.suffix=='.pyc':continue
        if p.is_file() and 'run/'+p.relative_to(root).as_posix() not in files:add(p,'run/'+p.relative_to(root).as_posix())
    for base,prefix in [(root/'results','run/results/'),(root/'guard','guard/')]:
        for p in sorted(base.rglob('*')):
            if any(x in ['xsim.dir','.Xil','__pycache__'] for x in p.relative_to(base).parts):continue
            if p.is_file() and p.suffix in ['.json','.jsonl','.sv','.v','.log','.txt','.tcl','.jou','.prj','.py']:add(p,prefix+p.relative_to(base).as_posix())
    if spec['identity']=='formal_bridge_v2_20261005_v1' and not failure:assert prior is not None
    if prior:add(Path(prior).resolve(),'dependencies/v1.zip')
    if not failure:
        for n,h in spec['source_hashes'].items():assert digest((root/n).read_bytes())==h
    manifest={'schema':'formal_bridge_terminal_archive_v1','synthetic_fixture':fixture,'mode':'failure' if failure else 'passed','missing_sources':missing,'captured_at_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'run_root':str(root),'run_spec_sha256':digest((root/'RUN_SPEC.json').read_bytes()),'collector_sha256':digest(Path(__file__).read_bytes()),'collector_model_calls':0,'collector_eda_calls':0,'files':{n:digest(raw) for n,raw in sorted(files.items())}}
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
        for n,raw in sorted(files.items()):z.writestr(n,raw)
        z.writestr('ARCHIVE_MANIFEST.json',json.dumps(manifest,indent=2)+'\n')
    return {'archive_sha256':digest(archive.read_bytes()),'files':len(files),'archive':str(archive),'mode':manifest['mode']}

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--archive',type=Path,required=True);p.add_argument('--prior',type=Path);p.add_argument('--failure',action='store_true');a=p.parse_args();print(json.dumps(collect(a.root,a.archive,a.prior,a.failure)))
