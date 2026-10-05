"""Archive completed zero-model original edge calibration, without executing tools."""
from pathlib import Path
import argparse,datetime,hashlib,json,zipfile
def sha(b):return hashlib.sha256(b).hexdigest()
def collect(root,archive):
    root=root.resolve();assert not archive.exists() and not archive.is_relative_to(root)
    spec=json.loads((root/'RUN_SPEC.json').read_text());summary=json.loads((root/'results/summary.json').read_text());guard=json.loads((root/'guard/status.json').read_text())
    assert summary['complete'] and summary['passed'] and guard['complete'] and guard['passed']
    files={}
    def add(p,n,h=None):
        assert p.is_file() and not p.is_symlink() and n not in files
        b=p.read_bytes();assert len(b)<50*1024**2
        if h:assert sha(b)==h,n
        files[n]=b
    for n,h in spec['source_hashes'].items():add(root/n,'run/'+n,h)
    add(root/'RUN_SPEC.json','run/RUN_SPEC.json');add(root/'PREPARATION_RECEIPT.json','run/PREPARATION_RECEIPT.json')
    for directory in ['results','guard','tools']:
        for p in sorted((root/directory).rglob('*')):
            if '__pycache__' in p.parts or p.suffix=='.pyc':continue
            if p.is_file():add(p,'run/'+p.relative_to(root).as_posix())
    for n,h in spec['dependency_hashes'].items():add(Path(spec['dependencies_cloud'])/n,'dependencies/'+n,h)
    manifest=dict(schema='natural_edge_original_harness_archive_v1',captured_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),run_spec_sha256=sha((root/'RUN_SPEC.json').read_bytes()),collector_sha256=sha(Path(__file__).read_bytes()),model_calls=0,eda_calls=0,files={n:sha(b) for n,b in files.items()})
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
        for n,b in files.items():z.writestr(n,b)
        z.writestr('ARCHIVE_MANIFEST.json',json.dumps(manifest,indent=2)+'\n')
    return dict(archive=str(archive),archive_sha256=sha(archive.read_bytes()),files=len(files))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--archive',type=Path,required=True);a=p.parse_args();print(json.dumps(collect(a.root,a.archive)))
