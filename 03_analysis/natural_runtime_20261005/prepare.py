"""Freeze engineering sources only. Never creates real runtime authorization."""
from pathlib import Path
import ast
import datetime
import hashlib
import json
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value):
    Path(path).write_bytes((json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode())


def main():
    assert not (ROOT / 'TOOLS_SPEC.json').exists()
    assert not (ROOT / 'RUN_SPEC.json').exists()
    sources = sorted(path.name for path in ROOT.glob('*.py')) + ['INPUT_MANIFEST.json']
    result = json.loads((ROOT / 'ENGINEERING_CHECKS.json').read_bytes())
    assert result['passed'] and result['failures'] == result['errors'] == 0
    assert result['actual_model_calls'] == result['actual_eda_calls'] == result['actual_native_tests'] == 0
    assert result['real_execution_admitted'] is False and result['quality_verified'] is False
    assert result['source_hashes'] == {name: sha(ROOT / name) for name in sources}
    for name in sources:
        if name.endswith('.py'): ast.parse((ROOT / name).read_bytes(), filename=name)
    originals = {'adapter.py': ROOT.parent / 'natural_input_adapter_20261005/adapter.py',
                 'native_reset_contract.py': ROOT.parent / 'native_reset_contract_20261005/native_reset_contract.py',
                 'guard_wrapper.py': ROOT.parent / 'phase_full156_20261005/guard_wrapper.py',
                 'INPUT_MANIFEST.json': ROOT.parent / 'phase_full156_20261005/INPUT_MANIFEST.json'}
    assert all((ROOT / name).read_bytes() == path.read_bytes() for name, path in originals.items())
    spec = dict(schema='natural_runtime_engineering_tools_frozen_v1', identity='natural_runtime_20261005_v1',
                cloud_root='/workspace/team/runs/fpga_owner/natural_runtime_20261005_v1',
                frozen_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                base_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                source_hashes=result['source_hashes'], local_tests_run=result['tests_run'],
                source_binding_originals={name: sha(path) for name, path in originals.items()},
                real_execution_admitted=False, execution_authorized_by_root=False, run_spec_created=False,
                actual_model_calls=0, actual_eda_calls=0, actual_fifo_submitted=False,
                total_solve_budget_s=300, child_work_budget_s=272, cleanup_reserve_s=24, receipt_reserve_s=4,
                full300s_timeout_verified=False, production_guard_integration_verified=False,
                frozen_policy_equivalence=False, quality_verified=False, adoption=False,
                scope='Engineering source package with synthetic IO and owned Python process controls; TOOLS_SPEC never authorizes actual HTTP/model/native execution.')
    save(ROOT / 'TOOLS_SPEC.json', spec)
    receipt = dict(spec_sha256=sha(ROOT / 'TOOLS_SPEC.json'), assets=len(sources),
                   actual_model_calls=0, actual_eda_calls=0, actual_fifo_submitted=False,
                   exact_original_sources=True, execution_authorized=False)
    save(ROOT / 'PREPARATION_RECEIPT.json', receipt)
    archive_path = ROOT / 'raw_evidence/preparation.zip'
    with zipfile.ZipFile(archive_path, 'x', zipfile.ZIP_DEFLATED) as archive:
        for name in sources + ['TOOLS_SPEC.json', 'PREPARATION_RECEIPT.json']:
            archive.write(ROOT / name, name)
    save(ROOT / 'PREPARATION_ARCHIVE.json', dict(archive_sha256=sha(archive_path), **receipt))
    print(json.dumps(receipt))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
