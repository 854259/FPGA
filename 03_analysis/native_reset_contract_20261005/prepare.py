"""Freeze pure native contract tools, without invoking a model or EDA tool."""
from pathlib import Path
import ast
import datetime
import hashlib
import json
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, data):
    path.write_bytes((json.dumps(data, ensure_ascii=False, indent=2) + '\n').encode())


if __name__ == '__main__':
    assert not (ROOT / 'TOOLS_SPEC.json').exists()
    checks = json.loads((ROOT / 'LOCAL_CHECKS.json').read_bytes())
    assert checks['status'] == 'passed' and checks['tests'] == 35 and checks['subtests'] == 242
    assert checks['actual_model_calls'] == checks['actual_eda_calls'] == 0
    for name, digest in checks['files_sha256'].items():
        assert sha(ROOT / name) == digest, name
    assert sha(ROOT / 'raw_evidence/input.prompt') == 'b55622d75576a72d6a5b321a592cc78c2a554dbc0da9e385d35b519fb6f535dc'
    sources = ['native_reset_contract.py', 'test_native_reset_contract.py', 'inventory.py',
               'prepare.py', 'raw_evidence/input.prompt']
    for name in sources:
        if name.endswith('.py'):
            source = (ROOT / name).read_bytes()
            ast.parse(source, filename=name)
            compile(source, name, 'exec')
    spec = dict(schema='native_reset_pure_tools_frozen_v1',
                identity='native_reset_contract_20261005_v1',
                cloud_root='/workspace/team/runs/fpga_owner/native_reset_contract_20261005_v1',
                frozen_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                base_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                source_hashes={name: sha(ROOT / name) for name in sources},
                dataset_sha256='cbcd81295561ebb16e4d857e096f4d9908d042c33aff3b58abf236e868411857',
                pure_tests=35, pure_subtests=242,
                planned_model_calls=0, planned_eda_calls=0,
                scope='Complete bounded prompt-only grammar, generated research TB and synthetic transcript integrity. All302 dispatch coverage only; no native execution, model quality, independent qualification or deployment.',
                quality_qualification=False, adoption=False)
    save(ROOT / 'TOOLS_SPEC.json', spec)
    save(ROOT / 'PREPARATION_RECEIPT.json', dict(spec_sha256=sha(ROOT / 'TOOLS_SPEC.json'),
                                               assets=len(sources), actual_model_calls=0,
                                               actual_eda_calls=0, actual_fifo_submitted=False))
    with zipfile.ZipFile(ROOT / 'raw_evidence/preparation.zip', 'x', zipfile.ZIP_DEFLATED) as archive:
        for name in sources + ['TOOLS_SPEC.json', 'PREPARATION_RECEIPT.json']:
            archive.write(ROOT / name, name)
    save(ROOT / 'PREPARATION_ARCHIVE.json', dict(archive_sha256=sha(ROOT / 'raw_evidence/preparation.zip'),
                                               spec_sha256=sha(ROOT / 'TOOLS_SPEC.json'), assets=len(sources)))
    print(json.dumps(json.loads((ROOT / 'PREPARATION_ARCHIVE.json').read_bytes())))
