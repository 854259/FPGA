"""Read-only completed calibration archive; no tools/inference."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import zipfile


def sha(raw):return hashlib.sha256(raw).hexdigest()


def collect(root,guard,archive):
    root,guard,archive=Path(root).resolve(),Path(guard).resolve(),Path(archive).resolve()
    assert not archive.exists() and not archive.is_relative_to(root)
    spec=json.loads((root/'RUN_SPEC.json').read_text())
    report=json.loads((root/'results/summary.json').read_text())
    status=json.loads((guard/'status.json').read_text())
    assert report['complete'] and report['passed'] and status['complete'] and status['passed']
    files={}
    def add(path,name,expected=None):
        assert not path.is_symlink() and path.is_file()
        raw=path.read_bytes();assert len(raw)<=50*1024**2
        if expected:assert sha(raw)==expected,name
        assert name not in files;files[name]=raw
    for n,h in spec['source_hashes'].items():add(root/n,'run/'+n,h)
    add(root/'RUN_SPEC.json','run/RUN_SPEC.json')
    add(root/'PREPARATION_RECEIPT.json','run/PREPARATION_RECEIPT.json')
    for base,prefix in ((root/'results','run/results/'),(guard,'guard/')):
        for p in sorted(base.rglob('*')):
            if any(part in ('xsim.dir','.Xil','__pycache__') for part in p.relative_to(base).parts):continue
            if p.is_file() and p.suffix in ('.json','.jsonl','.sv','.v','.log','.txt','.tcl','.jou','.prj'):
                add(p,prefix+p.relative_to(base).as_posix())
    for n,h in spec['dependency_hashes'].items():add(Path(spec['dependencies_cloud'])/n,'dependencies/'+n,h)
    # Source identities are checked again after evidence gathering.
    for n,h in spec['source_hashes'].items():assert sha((root/n).read_bytes())==h
    manifest=dict(schema='shift_contract_calibration_archive_v1',captured_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        run_spec_sha256=sha((root/'RUN_SPEC.json').read_bytes()),collector_sha256=sha(Path(__file__).read_bytes()),
        model_calls=0,eda_calls=0,files={n:sha(raw) for n,raw in sorted(files.items())})
    with zipfile.ZipFile(archive,'x',zipfile.ZIP_DEFLATED) as z:
        for n,raw in sorted(files.items()):z.writestr(n,raw)
        z.writestr('ARCHIVE_MANIFEST.json',json.dumps(manifest,indent=2)+'\n')
    return dict(archive_sha256=sha(archive.read_bytes()),files=len(files),archive=str(archive))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',required=True,type=Path);p.add_argument('--guard',required=True,type=Path);p.add_argument('--archive',required=True,type=Path)
    a=p.parse_args();print(json.dumps(collect(a.root,a.guard,a.archive)))
