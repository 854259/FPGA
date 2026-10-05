"""Freeze the FAKE-only natural worker engineering package; no real calls."""
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
    results = json.loads((ROOT / 'RESULTS.json').read_bytes())
    assert results['passed'] and results['tests_run'] == 52
    assert results['failures'] == results['errors'] == results['skipped'] == 0
    assert results['real_model_calls'] == results['real_eda_calls'] == 0
    for name, digest in results['source_hashes'].items():
        assert sha(ROOT / name) == digest, name
    original = ROOT.parent / 'natural_input_adapter_20261005/adapter.py'
    assert (ROOT / 'adapter.py').read_bytes() == original.read_bytes()
    assert sha(original) == '9b41ef3adfd345ff037ee4dcd3ef918d991c3bc5e52562ed8bc309355e0a39f9'
    save(ROOT / 'ORIGINAL_ADAPTER_RECEIPT.json', dict(original_adapter_sha256=sha(original),
        copied_adapter_sha256=sha(ROOT / 'adapter.py'), exact_bytes_equal=True,
        real_model_calls=0, real_eda_calls=0))
    sources = ['adapter.py', 'worker.py', 'test_worker.py', 'run_checks.py', 'prepare.py']
    for name in sources:
        code = (ROOT / name).read_bytes()
        ast.parse(code, filename=name)
        compile(code, name, 'exec')
    spec = dict(schema='natural_worker_fake_tools_frozen_v1',
        identity='natural_worker_20261005_v1',
        cloud_root='/workspace/team/runs/fpga_owner/natural_worker_20261005_v1',
        frozen_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        base_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
        source_hashes={name: sha(ROOT / name) for name in sources}, pure_tests=52,
        actual_model_calls=0, actual_eda_calls=0, actual_fifo_submitted=False,
        adapter_exact_original=True, max_requests=2, max_tokens=8192,
        temperature=0, top_p=1, solve_timeout_s=300,
        real_timeout_cancellation_integrated=False, real_transport_integrated=False,
        real_compiler_integrated=False, functional_feedback_integrated=False,
        external_callback_fidelity_verified=False, quality_qualification=False, adoption=False,
        scope='FAKE-only engineering: complete public context/output files, owned physical paths, budget protocol, callback argument mutation detection and partial evidence retention. C/P share identical engineering policy; no official baseline or candidate quality comparison.')
    save(ROOT / 'TOOLS_SPEC.json', spec)
    save(ROOT / 'PREPARATION_RECEIPT.json', dict(spec_sha256=sha(ROOT / 'TOOLS_SPEC.json'),
        assets=len(sources), actual_model_calls=0, actual_eda_calls=0, actual_fifo_submitted=False))
    with zipfile.ZipFile(ROOT / 'raw_evidence/preparation.zip', 'x', zipfile.ZIP_DEFLATED) as archive:
        for name in sources + ['TOOLS_SPEC.json', 'PREPARATION_RECEIPT.json', 'ORIGINAL_ADAPTER_RECEIPT.json']:
            archive.write(ROOT / name, name)
    save(ROOT / 'PREPARATION_ARCHIVE.json', dict(archive_sha256=sha(ROOT / 'raw_evidence/preparation.zip'),
        spec_sha256=sha(ROOT / 'TOOLS_SPEC.json'), assets=len(sources)))
    print(json.dumps(json.loads((ROOT / 'PREPARATION_ARCHIVE.json').read_bytes())))
